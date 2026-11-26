const { app, BrowserWindow, dialog, ipcMain, Menu, nativeTheme, session, shell, WebContentsView } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { AddressSuggestions } = require('./address-suggestions.cjs');
const { History } = require('./history.cjs');
const { writableDirectory, downloadName, reserveDownload } = require('./downloads.cjs');
const { blocks, loadBlocker } = require('./blocker.cjs');

app.setName('Lux Vela');
app.setDesktopName('luxos-vela.desktop');
app.enableSandbox();
app.commandLine.appendSwitch('site-per-process');
// Dawn needs the Vulkan backend on Linux. Keep Chromium's GPU restrictions enabled.
if (process.platform === 'linux') app.commandLine.appendSwitch('enable-features', 'Vulkan');

const chromeHeight = 96;
const noticeHeight = 54;
const panelWidth = 328;
const searchProviders = {
  duckduckgo: 'https://duckduckgo.com/?q=',
  google: 'https://www.google.com/search?q=',
  seznam: 'https://search.seznam.cz/?q='
};
const preferenceValues = { theme: ['system', 'light', 'dark'], startup: ['restore', 'new'],
  search: Object.keys(searchProviders), blocking: [true, false], history: [true, false],
  zoom: [0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2], askDownload: [true, false] };
const preferences = { theme: 'system', startup: 'restore', search: 'duckduckgo', blocking: true, history: true, zoom: 1, askDownload: true, downloadFolder: '' };
const webPreferences = { sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true };
const translations = {
  en: { newTab: 'New tab', context: ['Open link in new tab', 'Copy', 'Paste', 'Select all'] },
  cs: { newTab: 'Nová karta', context: ['Otevřít odkaz v nové kartě', 'Kopírovat', 'Vložit', 'Vybrat vše'] }
};

const tabs = new Map();
const downloads = new Map();
const tabByContents = new Map();
let nextId = 0;
let activeId;
let panel = '';
let win;
let browsing;
let locale;
let blocker;
let statePath;
let saveTimer;
let excludedSites = new Set();
let pendingUrls = [];
let browserFullscreen = false;
let pageFullscreen;
let fullscreenTransition;
let focusAddressOnExit = false;
let history;
let suggestions;

function webUrl(value) {
  if (typeof value !== 'string' || value.length > 16384) return '';
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : '';
  } catch {
    return '';
  }
}

function address(value) {
  if (typeof value !== 'string') return '';
  const input = value.trim();
  if (!input || input.length > 8192) return '';
  const direct = webUrl(input);
  if (direct) return direct;
  if (/^(localhost|\[[\da-f:]+\]|[^\s:/]+\.[^\s:/]+)(:\d+)?(?:[/?#]|$)/i.test(input) && !/\s/.test(input)) {
    const host = input.split('/')[0];
    const local = /^(localhost|127(?:\.\d+){3}|\[::1\])(?::\d+)?$/i.test(host);
    return webUrl((local ? 'http://' : 'https://') + input);
  }
  if (/^[a-z][a-z\d+.-]*:/i.test(input)) return '';
  return searchUrl(input);
}

function searchUrl(query) {
  if (typeof query !== 'string' || !query.trim() || query.length > 8192) return '';
  return searchProviders[preferences.search] + encodeURIComponent(query.trim());
}

function applyPreference(name, value) {
  if (!Object.hasOwn(preferenceValues, name) || !preferenceValues[name].includes(value)) return false;
  preferences[name] = value;
  if (name === 'theme') nativeTheme.themeSource = value;
  return true;
}

function safeRead() {
  try {
    return JSON.parse(fs.readFileSync(statePath, 'utf8')) || {};
  } catch (error) {
    if (error.code !== 'ENOENT') console.error('Could not read Vela state:', error.message);
    return {};
  }
}

function save() {
  clearTimeout(saveTimer);
  if (!statePath) return;
  const saved = { tabs: [...tabs.values()].map(tab => tab.url), active: [...tabs.keys()].indexOf(activeId),
    excludedSites: [...excludedSites], preferences, history: history?.serialize() };
  try {
    fs.writeFileSync(statePath + '.tmp', JSON.stringify(saved), { mode: 0o600 });
    fs.renameSync(statePath + '.tmp', statePath);
  } catch (error) {
    console.error('Could not save Vela state:', error.message);
  }
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 180);
}

function active() { return tabs.get(activeId); }

function site(url) {
  if (url) return new URL(url).hostname;
  return '';
}

function protectionFor(tab) {
  return preferences.blocking && !excludedSites.has(site(tab?.url)) && !tab?.allowPage;
}

function update() {
  if (!win || win.isDestroyed()) return;
  const tab = active();
  const navigation = tab?.view?.webContents.navigationHistory;
  win.webContents.send('vela:state', {
    locale: app.getLocale(),
    fullscreen: win.isFullScreen(),
    panel,
    preferences,
    settings: panel === 'settings' ? {
      excludedSites: [...excludedSites].sort(),
      historyCount: history.size,
      downloadFolder: preferences.downloadFolder || app.getPath('downloads')
    } : null,
    tabs: [...tabs.values()].map(({ id, title, url, loading }) => ({ id, title, url, loading })),
    active: tab && { id: tab.id, url: tab.url, loading: tab.loading, error: tab.error, blocked: tab.blocked,
      site: site(tab.url), protected: protectionFor(tab), temporary: Boolean(tab.allowPage),
      blank: tab.blank, pending: tab.pending,
      back: Boolean(navigation?.canGoBack()), forward: Boolean(navigation?.canGoForward()) },
    downloads: [...downloads.values()].map(({ item, ...info }) => info)
  });
}

function layout() {
  if (!win || win.isDestroyed()) return;
  const { width, height } = win.contentView.getBounds();
  const top = win.isFullScreen() ? 0 : chromeHeight + (active()?.blank ? noticeHeight : 0);
  for (const tab of tabs.values()) {
    if (!tab.view) continue;
    const visible = panel !== 'settings' && tab.id === activeId && Boolean(tab.url) && !tab.error && !tab.pending;
    if (visible) tab.view.setBounds({ x: 0, y: top, width: Math.max(1, width - (panel ? panelWidth : 0)),
      height: Math.max(1, height - top) });
    tab.view.setVisible(visible);
  }
  suggestions?.layout();
}

function focusAddress(openSuggestions = false) {
  win.webContents.focus();
  win.webContents.send('vela:focus-address', openSuggestions);
}

function syncFullscreen() {
  if (!win || win.isDestroyed()) return;
  const desired = browserFullscreen || Boolean(pageFullscreen);
  if (fullscreenTransition === undefined && win.isFullScreen() !== desired) {
    fullscreenTransition = desired;
    win.setFullScreen(desired);
  }
  layout();
  update();
  if (!desired && !win.isFullScreen() && fullscreenTransition === undefined && focusAddressOnExit) {
    focusAddressOnExit = false;
    focusAddress(true);
  }
}

function exitPageFullscreen() {
  const contents = pageFullscreen?.view?.webContents;
  pageFullscreen = undefined;
  if (contents && !contents.isDestroyed()) {
    contents.executeJavaScriptInIsolatedWorld(1001, [{
      code: 'if (document.fullscreenElement) void document.exitFullscreen().catch(() => {})'
    }]).catch(() => {});
  }
}

function leaveFullscreen() {
  browserFullscreen = false;
  exitPageFullscreen();
  syncFullscreen();
}

function nativeFullscreenChanged(entered) {
  if (fullscreenTransition === undefined) {
    browserFullscreen = entered;
    if (!entered) exitPageFullscreen();
  }
  fullscreenTransition = undefined;
  syncFullscreen();
}

function toggleFullscreen() {
  suggestions?.close();
  if (browserFullscreen || pageFullscreen) leaveFullscreen();
  else {
    panel = '';
    browserFullscreen = true;
    syncFullscreen();
    focusPage();
  }
}

function focusPage() {
  const tab = active();
  if (panel !== 'settings' && tab?.view && !tab.pending && !tab.error) tab.view.webContents.focus();
}

function retryOrReload(tab) {
  if (tab?.error || tab?.allowPage) navigate(tab, tab.url);
  else tab?.view?.webContents.reload();
}

function select(id, focus = true) {
  if (!tabs.has(id)) return;
  if (id !== activeId) {
    suggestions?.close();
    leaveFullscreen();
    panel = '';
  }
  activeId = id;
  const tab = active();
  if (tab.url && !tab.view) navigate(tab, tab.url);
  layout();
  update();
  if (focus) {
    if (tab.pending) win.webContents.focus();
    else if (tab.view && !tab.error) tab.view.webContents.focus();
    else focusAddress();
  }
  scheduleSave();
}

function addTab(url = '', foreground = true) {
  const tab = { id: ++nextId, url, title: '', loading: false, pending: false, blocked: 0, error: '', blank: false, view: null };
  tabs.set(tab.id, tab);
  if (foreground) select(tab.id);
  else update();
  scheduleSave();
  return tab;
}

function closeTab(id) {
  const tab = tabs.get(id);
  if (!tab) return;
  const ids = [...tabs.keys()];
  const next = ids[ids.indexOf(id) + 1] ?? ids[ids.indexOf(id) - 1];
  if (tab.view) {
    tabByContents.delete(tab.view.webContents.id);
    clearTimeout(tab.blockUpdate);
    clearTimeout(tab.blankTimer);
    if (pageFullscreen === tab) leaveFullscreen();
    win.contentView.removeChildView(tab.view);
    tab.view.webContents.close();
  }
  tabs.delete(id);
  if (activeId === id) {
    if (next) select(next);
    else addTab();
  }
  update();
  scheduleSave();
}

function handleKeys(event, key) {
  if (key.type !== 'keyDown') return;
  const value = key.key.toLowerCase();
  const tab = active();
  const contents = tab?.view?.webContents;
  let action;
  if (key.control && !key.alt && !key.meta) {
    if (value === 'l') action = () => { focusAddressOnExit = true; leaveFullscreen(); };
    if (value === 't') action = () => addTab();
    if (value === 'w') action = () => closeTab(activeId);
    if (value === 'r') action = () => retryOrReload(tab);
    if (value === 'j') action = () => togglePanel('downloads');
    if (value === ',') action = () => togglePanel('settings');
    if (value === 'tab') action = () => {
      const ids = [...tabs.keys()];
      const next = ids.indexOf(activeId) + (key.shift ? -1 : 1);
      select(ids[(next + ids.length) % ids.length]);
    };
  }
  if (key.alt && value === 'arrowleft') action = () => contents?.navigationHistory.goBack();
  if (key.alt && value === 'arrowright') action = () => contents?.navigationHistory.goForward();
  if (value === 'f5') action = () => retryOrReload(tab);
  if (value === 'f11' && !key.isAutoRepeat) action = toggleFullscreen;
  if (value === 'escape' && suggestions?.close()) {
    event.preventDefault();
    return;
  }
  if (value === 'escape' && (panel || browserFullscreen || pageFullscreen || win.isFullScreen())) action = () => {
    leaveFullscreen();
    if (panel) togglePanel(panel);
  };
  if (action) {
    event.preventDefault();
    action();
  }
}

function createView(tab) {
  const view = new WebContentsView({ webPreferences: { ...webPreferences, session: browsing, disableHtmlFullscreenWindowResize: true } });
  tab.view = view;
  const contents = view.webContents;
  tabByContents.set(contents.id, tab);
  view.setBackgroundColor(nativeTheme.shouldUseDarkColors ? '#21242b' : '#ffffff');
  view.setVisible(false);
  win.contentView.addChildView(view);
  const preventUnsafe = event => { if (event.isMainFrame && !webUrl(event.url)) event.preventDefault(); };
  contents.on('will-navigate', event => { if (!webUrl(event.url)) event.preventDefault(); });
  contents.on('will-redirect', preventUnsafe);
  contents.setWindowOpenHandler(({ url, disposition }) => {
    const target = webUrl(url);
    if (target) setImmediate(() => addTab(target, disposition !== 'background-tab'));
    return { action: 'deny' };
  });
  contents.on('before-input-event', handleKeys);
  contents.on('focus', () => suggestions?.close());
  contents.on('context-menu', (_event, params) => {
    const [open, copy, paste, all] = locale.context;
    const link = webUrl(params.linkURL);
    const items = [];
    if (link) items.push({ label: open, click: () => addTab(link) });
    if (params.selectionText) items.push({ label: copy, click: () => contents.copy() });
    if (params.isEditable) items.push({ label: paste, click: () => contents.paste() },
      { label: all, click: () => contents.selectAll() });
    if (items.length) Menu.buildFromTemplate(items).popup({ window: win });
  });
  contents.on('did-start-navigation', ({ url, isSameDocument, isMainFrame }) => {
    if (!isMainFrame || isSameDocument || !webUrl(url)) return;
    if (pageFullscreen === tab) {
      exitPageFullscreen();
      syncFullscreen();
    }
    if (tab.allowPage !== url) tab.allowPage = '';
    tab.historyStatus = 0;
    tab.historyKey = '';
    tab.historyUrl = '';
    clearTimeout(tab.blankTimer);
    tab.blank = false;
    tab.url = url;
    tab.pending = true;
    tab.title = '';
    tab.error = '';
    tab.blocked = 0;
    // The window must keep a focused renderer while the loading page is hidden.
    if (tab === active() && !panel) win.webContents.focus();
    layout();
    update();
  });
  contents.on('did-redirect-navigation', ({ url, isMainFrame }) => {
    if (isMainFrame && webUrl(url)) {
      if (tab.allowPage !== url) tab.allowPage = '';
      tab.url = url;
      update();
    }
  });
  const committed = (_event, url, mainFrame = true) => {
    if (!mainFrame || !webUrl(url)) return;
    const pending = tab.pending;
    if (pending) contents.setZoomFactor(preferences.zoom);
    tab.pending = false;
    tab.error = '';
    tab.url = url;
    layout();
    update();
    if (pending && tab === active() && !panel && win.isFocused()) contents.focus();
    scheduleSave();
  };
  const recordVisit = url => {
    if (!preferences.history || !(tab.historyStatus >= 200 && tab.historyStatus < 400)) return;
    const target = webUrl(url).split('#')[0];
    if (!target || target === tab.historyUrl) return;
    tab.historyUrl = target;
    tab.historyKey = history.record(target, contents.getTitle());
    if (tab.historyKey) scheduleSave();
  };
  contents.on('did-navigate', (event, url, status) => {
    tab.historyStatus = status;
    committed(event, url);
  });
  contents.on('did-navigate-in-page', (event, url, mainFrame) => {
    committed(event, url, mainFrame);
    if (mainFrame) recordVisit(url);
  });
  contents.on('did-finish-load', () => recordVisit(contents.getURL()));
  contents.on('page-title-updated', (_event, title) => {
    tab.title = title.slice(0, 300);
    if (preferences.history && history.updateTitle(tab.historyKey, tab.title)) scheduleSave();
    update();
  });
  contents.on('did-start-loading', () => { tab.loading = true; update(); });
  contents.on('did-stop-loading', () => {
    tab.loading = false;
    if (tab.pending) {
      tab.pending = false;
      tab.url = webUrl(contents.getURL());
      tab.title = tab.url ? contents.getTitle().slice(0, 300) : '';
      layout();
    }
    update();
    checkBlankPage(tab, contents);
  });
  contents.on('did-fail-load', (_event, code, reason, url, mainFrame) => {
    if (!mainFrame || code === -3 || url !== tab.url) return;
    tab.pending = false;
    tab.error = reason;
    layout();
    update();
  });
  contents.on('render-process-gone', () => {
    tab.pending = false;
    tab.error = 'ERR_RENDERER_GONE';
    layout();
    update();
  });
  contents.on('enter-html-full-screen', () => {
    if (tab !== active()) return;
    suggestions?.close();
    panel = '';
    pageFullscreen = tab;
    syncFullscreen();
    focusPage();
  });
  contents.on('leave-html-full-screen', () => {
    if (pageFullscreen !== tab) return;
    pageFullscreen = undefined;
    syncFullscreen();
  });
  return view;
}

function checkBlankPage(tab, contents) {
  clearTimeout(tab.blankTimer);
  if (!tab.blocked || !protectionFor(tab) || tab.error || !tab.url) return;
  const url = tab.url;
  let remaining = 3;
  const check = async () => {
    if (contents.isDestroyed() || tab.url !== url || tab.loading || tab.error || !protectionFor(tab)) return;
    try {
      const blank = await contents.executeJavaScriptInIsolatedWorld(1001, [{
        code: `Boolean(document.body && !document.body.innerText.trim() &&
          !document.body.querySelector('canvas, video, iframe, img, svg, object, embed, input, button'))`
      }]);
      if (contents.isDestroyed() || tab.url !== url || tab.loading || !protectionFor(tab)) return;
      if (tab.blank !== blank) {
        tab.blank = blank;
        layout();
        update();
      }
      if (blank && --remaining > 0) tab.blankTimer = setTimeout(check, 2300);
    } catch {}
  };
  tab.blankTimer = setTimeout(check, 1300);
}

function navigate(tab, url, allowPage = false) {
  if (tab === active()) suggestions?.close();
  tab.allowPage = allowPage ? url : '';
  tab.blank = false;
  tab.url = url;
  tab.pending = true;
  tab.error = '';
  const view = tab.view ?? createView(tab);
  if (tab === active() && !panel) win.webContents.focus();
  layout();
  view.webContents.loadURL(url).catch(error => {
    if (!tab.pending || tab.url !== url || error.code === 'ERR_ABORTED') return;
    tab.pending = false;
    tab.error = error.code ?? 'ERR_FAILED';
    layout();
    update();
  });
  update();
  scheduleSave();
}

function togglePanel(name) {
  suggestions?.close();
  leaveFullscreen();
  panel = panel === name ? '' : name;
  layout();
  update();
  if (panel || active()?.pending) win.webContents.focus();
  else focusPage();
}

function configureSession() {
  browsing = session.fromPartition('persist:vela-web');
  const canFullscreen = (contents, permission) => permission === 'fullscreen' && contents &&
    panel !== 'settings' && active()?.view?.webContents === contents && !active().pending && !active().error;
  browsing.setPermissionRequestHandler((contents, permission, callback) => callback(Boolean(canFullscreen(contents, permission))));
  browsing.setPermissionCheckHandler((contents, permission) => Boolean(canFullscreen(contents, permission)));
  browsing.setDisplayMediaRequestHandler((_request, callback) => callback({}));
  browsing.webRequest.onBeforeRequest((details, callback) => {
    if (details.resourceType === 'mainFrame') return callback({ cancel: !webUrl(details.url) });
    const tab = tabByContents.get(details.webContentsId);
    const root = tab?.url;
    if (!protectionFor(tab)) return callback({});
    const sourceUrl = webUrl(details.frame?.url) || root || webUrl(details.referrer);
    if (!blocks(blocker, { url: details.url, sourceUrl, type: details.resourceType })) return callback({});
    if (tab) {
      tab.blocked++;
      if (!tab.blockUpdate) tab.blockUpdate = setTimeout(() => { tab.blockUpdate = null; update(); }, 120);
    }
    callback({ cancel: true });
  });
  browsing.on('will-download', (_event, item) => {
    const id = ++nextId;
    const record = { item, id, name: item.getFilename(), received: 0, total: item.getTotalBytes(), state: 'progressing' };
    downloads.set(id, record);
    const folder = writableDirectory(preferences.downloadFolder || app.getPath('downloads'));
    const reservation = folder && !preferences.askDownload ? reserveDownload(folder, record.name) : null;
    if (reservation) item.setSavePath(reservation.target);
    else item.setSaveDialogOptions({ defaultPath: path.join(folder || app.getPath('downloads'), downloadName(record.name)) });
    item.on('updated', (_event, state) => { record.received = item.getReceivedBytes(); record.state = state; update(); });
    item.once('done', (_event, state) => {
      record.state = state;
      record.path = state === 'completed' ? item.getSavePath() : '';
      if (state !== 'completed') reservation?.discard();
      record.item = null;
      update();
    });
    update();
  });
}

function openSuggestion(entry) {
  if (!entry || !active()) return false;
  const url = entry.kind === 'search' ? searchUrl(entry.value) : webUrl(entry.value);
  if (!url) return false;
  if (panel === 'settings') panel = '';
  navigate(active(), url);
  return true;
}

function exceptionHost(value) {
  if (typeof value !== 'string' || value.length > 253) return '';
  const raw = value.trim();
  if (!raw || /[\s\\/@?#%*]/u.test(raw) || (raw.includes(':') && !/^\[[\da-f:.]+\]$/i.test(raw))) return '';
  const url = webUrl('https://' + raw);
  if (!url || new URL(url).port) return '';
  const host = site(url);
  return host === 'localhost' || host.includes('.') || host.startsWith('[') ? host : '';
}

function changeException(value, add) {
  const host = exceptionHost(value);
  if (!host) {
    win.webContents.send('vela:settings-feedback', 'invalidException');
    return;
  }
  if (add) excludedSites.add(host);
  else excludedSites.delete(host);
  save();
  const tab = active();
  if (preferences.blocking && tab?.url && site(tab.url) === host) navigate(tab, tab.url);
  else update();
  win.webContents.send('vela:settings-feedback', add ? 'exceptionAdded' : 'exceptionRemoved');
}

async function chooseDownloadFolder() {
  const window = win;
  try {
    const result = await dialog.showOpenDialog(window, {
      defaultPath: preferences.downloadFolder || app.getPath('downloads'), properties: ['openDirectory']
    });
    if (result.canceled || window.isDestroyed()) return;
    const folder = writableDirectory(result.filePaths[0]);
    if (!folder) {
      window.webContents.send('vela:settings-feedback', 'folderUnavailable');
      return;
    }
    preferences.downloadFolder = folder;
    save();
    update();
  } catch {
    if (!window.isDestroyed()) window.webContents.send('vela:settings-feedback', 'folderUnavailable');
  }
}

function installIpc() {
  ipcMain.on('vela:action', (event, command, value) => {
    if (command === 'suggestion-clicked' && suggestions?.accepts(event)) {
      openSuggestion(suggestions.clicked(value));
      return;
    }
    if (event.sender !== win?.webContents || event.senderFrame !== win.webContents.mainFrame) return;
    const tab = active();
    const contents = tab?.view?.webContents;
    switch (command) {
      case 'ready': update(); break;
      case 'new': addTab(); break;
      case 'select': select(value); break;
      case 'close-tab': closeTab(value); break;
      case 'suggest': {
        if (!preferences.history || !value || typeof value.value !== 'string' || value.value.length > 8192 ||
          !Number.isFinite(value.x) || value.x < 0 || !Number.isFinite(value.width) || value.width < 1 ||
          win.isFullScreen()) break;
        suggestions.open(history.suggestions(value.all === true ? '' : value.value), value);
        break;
      }
      case 'suggestion-step': suggestions.step(value); break;
      case 'dismiss-suggestions': suggestions.close(); break;
      case 'search':
      case 'go': {
        if (command === 'go' && openSuggestion(suggestions.choice(value))) break;
        suggestions.close();
        const url = command === 'search' ? searchUrl(value) : address(value);
        if (url && tab) {
          if (panel === 'settings') panel = '';
          navigate(tab, url);
        }
        else if (typeof value === 'string' && value.trim()) win.webContents.send('vela:invalid-address');
        break;
      }
      case 'back':
        if (panel === 'settings') togglePanel('settings');
        else contents?.navigationHistory.goBack();
        break;
      case 'forward': contents?.navigationHistory.goForward(); break;
      case 'reload':
        if (tab?.loading && !tab.error) contents?.stop();
        else retryOrReload(tab);
        break;
      case 'privacy':
      case 'downloads':
      case 'settings': togglePanel(command); break;
      case 'fullscreen': toggleFullscreen(); break;
      case 'allow-page':
        if (tab?.blank && protectionFor(tab)) navigate(tab, tab.url, true);
        break;
      case 'preference':
        if (!value || !applyPreference(value.name, value.value)) break;
        if (value.name === 'history') suggestions.close();
        if (value.name === 'zoom') {
          for (const { view } of tabs.values()) view?.webContents.setZoomFactor(preferences.zoom);
        }
        save();
        if (value.name === 'blocking' && tab?.url) navigate(tab, tab.url);
        else update();
        break;
      case 'clear-history':
        if (panel !== 'settings') break;
        suggestions.close();
        history.clear();
        save();
        update();
        win.webContents.send('vela:settings-feedback', 'historyCleared');
        break;
      case 'add-exception':
      case 'remove-exception':
        if (panel === 'settings') changeException(value, command === 'add-exception');
        break;
      case 'choose-folder':
        if (panel === 'settings') void chooseDownloadFolder();
        break;
      case 'reset-folder':
        if (panel !== 'settings') break;
        preferences.downloadFolder = '';
        save();
        update();
        break;
      case 'protection': {
        const host = site(tab?.url);
        if (!host || !preferences.blocking) break;
        if (!excludedSites.delete(host)) excludedSites.add(host);
        save();
        navigate(tab, tab.url);
        break;
      }
      case 'show-download': {
        const file = downloads.get(value)?.path;
        if (file) shell.showItemInFolder(file);
        break;
      }
      case 'cancel-download': downloads.get(value)?.item?.cancel(); break;
      case 'minimize': win.minimize(); break;
      case 'maximize':
        if (win.isMaximized()) win.unmaximize();
        else win.maximize();
        break;
      case 'close': win.close(); break;
    }
  });
}

function openArguments(args) { return args.map(webUrl).filter(Boolean); }

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', (_event, args) => {
    const urls = openArguments(args);
    if (!win) pendingUrls.push(...urls);
    else {
      urls.forEach(url => addTab(url));
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(async () => {
    locale = app.getLocale().startsWith('cs') ? translations.cs : translations.en;
    statePath = path.join(app.getPath('userData'), 'vela-state.json');
    try {
      blocker = loadBlocker(path.join(__dirname, '..', 'rules'));
    } catch (error) {
      dialog.showErrorBox('Lux Vela', error.message);
      app.exit(1);
      return;
    }
    const saved = safeRead();
    for (const name of Object.keys(preferenceValues)) applyPreference(name, saved.preferences?.[name]);
    if (typeof saved.preferences?.downloadFolder === 'string' && path.isAbsolute(saved.preferences.downloadFolder))
      preferences.downloadFolder = saved.preferences.downloadFolder;
    history = new History(saved.history, preferences.history && Array.isArray(saved.tabs) ? saved.tabs.slice(0, 100) : []);
    if (Array.isArray(saved.excludedSites)) excludedSites = new Set(saved.excludedSites.filter(host => typeof host === 'string'));
    configureSession();
    win = new BrowserWindow({ title: 'Lux Vela', width: 1200, height: 800, minWidth: 560, minHeight: 430,
      show: false, frame: false, backgroundColor: nativeTheme.shouldUseDarkColors ? '#21242b' : '#f2f2f7',
      icon: path.join(__dirname, '..', 'luxos-vela.png'),
      webPreferences: { ...webPreferences, preload: path.join(__dirname, 'preload.cjs') } });
    suggestions = new AddressSuggestions(win, { ...webPreferences, preload: path.join(__dirname, 'preload.cjs') },
      () => preferences.theme);
    win.on('blur', () => suggestions.close());
    win.webContents.on('will-navigate', event => event.preventDefault());
    win.webContents.on('will-redirect', event => event.preventDefault());
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('before-input-event', handleKeys);
    win.contentView.on('bounds-changed', layout);
    win.on('enter-full-screen', () => nativeFullscreenChanged(true));
    win.on('leave-full-screen', () => nativeFullscreenChanged(false));
    win.on('close', save);
    win.on('closed', () => {
      suggestions.destroy();
      for (const tab of tabs.values()) {
        if (tab.view && !tab.view.webContents.isDestroyed()) tab.view.webContents.close();
      }
      win = null;
    });
    installIpc();
    await win.loadFile(path.join(__dirname, 'index.html'));
    const restored = preferences.startup === 'restore' && Array.isArray(saved.tabs) ? saved.tabs.slice(0, 100) : [];
    for (const url of restored) addTab(webUrl(url), false);
    const urls = [...openArguments(process.argv.slice(1)), ...pendingUrls];
    urls.forEach(url => addTab(url, false));
    win.show();
    if (!tabs.size) addTab();
    else {
      const ids = [...tabs.keys()];
      select(urls.length ? ids.at(-1) : ids[saved.active] ?? ids[0]);
    }
  });
  app.on('window-all-closed', () => app.quit());
}
