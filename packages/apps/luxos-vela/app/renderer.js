const $ = selector => document.querySelector(selector);
const action = (command, value) => window.vela.action(command, value);
const strings = {
  en: {
    close: 'Close window', minimize: 'Minimize', maximize: 'Maximize or restore', newTab: 'New tab',
    closeTab: 'Close tab', back: 'Back', forward: 'Forward', reload: 'Reload', stop: 'Stop loading',
    privacy: 'Privacy protection', downloads: 'Downloads', closePanel: 'Close panel', searchAction: 'Search',
    address: 'Search or enter an address', search: 'Search with DuckDuckGo', tabs: 'Tabs', navigation: 'Navigation',
    blocked: 'Requests blocked on this page', protection: 'Protection for this site', inactive: 'Protection is paused',
    error: 'This page could not load', retry: 'Try again', invalid: 'Enter a valid HTTP or HTTPS address.',
    noDownloads: 'No downloads this session', progressing: 'Downloading', interrupted: 'Interrupted',
    completed: 'Completed', cancelled: 'Cancelled', show: 'Show in folder', cancel: 'Cancel',
    settings: 'Settings', theme: 'Appearance', themeSystem: 'System', themeLight: 'Light', themeDark: 'Dark',
    startup: 'On startup', startupRestore: 'Restore tabs', startupNew: 'Open a new tab', searchEngine: 'Search engine',
    globalBlocking: 'Block ads and trackers', fullscreen: 'Full screen', loadingPage: 'Loading page…',
    emptyPage: 'Blocking may have prevented this page from displaying.', allowPage: 'Reload without blocking',
    temporary: 'Protection is paused for this page', searchWith: 'Search with',
    historySuggestions: 'Suggestions from history', addressSuggestions: 'Address suggestions',
    general: 'General', privacyShort: 'Privacy', closeSettings: 'Close settings',
    zoom: 'Page zoom', zoomDescription: 'Default scale for websites',
    searchDescription: 'Used by the address bar and new tab page',
    exceptions: 'Blocking exceptions', exceptionsDescription: 'Protection is paused for the exact sites listed here.',
    exceptionSite: 'Site hostname', add: 'Add', remove: 'Remove', invalidException: 'Enter a hostname such as example.com.',
    exceptionAdded: 'Exception added.', exceptionRemoved: 'Exception removed.',
    historyDescription: 'Save visits and searches on this device to suggest them in the address bar.',
    clearHistory: 'Clear local history', clearDescription: 'Removes saved visits and searches used for suggestions.',
    confirmClear: 'Clear all saved visits and searches?', clear: 'Clear history', historyCleared: 'Local history cleared.',
    downloadFolder: 'Download folder', choose: 'Choose…', reset: 'Reset', askDownload: 'Ask where to save each file',
    folderUnavailable: 'Choose a writable folder.'
  },
  cs: {
    close: 'Zavřít okno', minimize: 'Minimalizovat', maximize: 'Maximalizovat nebo obnovit', newTab: 'Nová karta',
    closeTab: 'Zavřít kartu', back: 'Zpět', forward: 'Vpřed', reload: 'Načíst znovu', stop: 'Zastavit načítání',
    privacy: 'Ochrana soukromí', downloads: 'Stažené soubory', closePanel: 'Zavřít panel', searchAction: 'Hledat',
    address: 'Hledejte nebo zadejte adresu', search: 'Hledat přes DuckDuckGo', tabs: 'Karty', navigation: 'Navigace',
    blocked: 'Zablokované požadavky na této stránce', protection: 'Ochrana pro tento web', inactive: 'Ochrana je pozastavena',
    error: 'Stránku se nepodařilo načíst', retry: 'Zkusit znovu', invalid: 'Zadejte platnou adresu HTTP nebo HTTPS.',
    noDownloads: 'V této relaci nic nestahujete', progressing: 'Stahování', interrupted: 'Přerušeno',
    completed: 'Dokončeno', cancelled: 'Zrušeno', show: 'Zobrazit ve složce', cancel: 'Zrušit',
    settings: 'Nastavení', theme: 'Vzhled', themeSystem: 'Podle systému', themeLight: 'Světlý', themeDark: 'Tmavý',
    startup: 'Při spuštění', startupRestore: 'Obnovit karty', startupNew: 'Otevřít novou kartu',
    searchEngine: 'Vyhledávač', globalBlocking: 'Blokovat reklamy a trackery', fullscreen: 'Celá obrazovka',
    loadingPage: 'Načítání stránky…', emptyPage: 'Blokování mohlo zabránit zobrazení této stránky.',
    allowPage: 'Načíst bez blokování', temporary: 'Ochrana je pro tuto stránku pozastavena', searchWith: 'Hledat přes',
    historySuggestions: 'Návrhy z historie', addressSuggestions: 'Návrhy adres a hledání',
    general: 'Obecné', privacyShort: 'Soukromí', closeSettings: 'Zavřít nastavení',
    zoom: 'Přiblížení stránek', zoomDescription: 'Výchozí měřítko webových stránek',
    searchDescription: 'Používá se v adresním řádku a na nové kartě',
    exceptions: 'Výjimky z blokování', exceptionsDescription: 'Ochrana je pozastavena pro zde uvedené adresy.',
    exceptionSite: 'Adresa webu', add: 'Přidat', remove: 'Odebrat', invalidException: 'Zadej název hostitele, například example.com.',
    exceptionAdded: 'Výjimka přidána.', exceptionRemoved: 'Výjimka odebrána.',
    historyDescription: 'Ukládá návštěvy a hledání do tohoto zařízení pro návrhy v adresním řádku.',
    clearHistory: 'Vymazat místní historii', clearDescription: 'Odstraní uložené návštěvy a hledání z návrhů.',
    confirmClear: 'Vymazat všechny uložené návštěvy a hledání?', clear: 'Vymazat historii', historyCleared: 'Místní historie vymazána.',
    downloadFolder: 'Složka pro stahování', choose: 'Vybrat…', reset: 'Obnovit', askDownload: 'U každého souboru se zeptat, kam ho uložit',
    folderUnavailable: 'Vyber složku, do které lze zapisovat.'
  }
};

let language;
let t = strings.en;
let current;
let previousActive;
let previousUrl;
const address = $('#address');
const search = $('#search');
const tabElements = new Map();
const addressForm = $('#address-form');
const accessibleResults = $('#address-accessible-results');
let suggestionsOpen = false;
let settingsSection = 'general';
let previousExceptions = '';
const exceptionList = $('#exceptions-list');
const settingsFeedback = $('#settings-feedback');
const clearConfirmation = $('#clear-history-confirmation');

function requestSuggestions(all = false) {
  const { left, width } = addressForm.getBoundingClientRect();
  action('suggest', { value: address.value, all, x: left, width });
}

function dismissSuggestions() { action('dismiss-suggestions'); }

function label(element, text) {
  element.title = text;
  element.setAttribute('aria-label', text);
}

function setLanguage(locale) {
  const next = locale.startsWith('cs') ? 'cs' : 'en';
  if (language === next) return;
  language = next;
  document.documentElement.lang = next;
  t = strings[next];
  document.querySelectorAll('[data-label]').forEach(element => label(element, t[element.dataset.label]));
  document.querySelectorAll('[data-text]').forEach(element => { element.textContent = t[element.dataset.text]; });
  label($('#tabs'), t.tabs);
  label($('nav'), t.navigation);
  address.placeholder = t.address;
  address.setAttribute('aria-label', t.address);
  accessibleResults.setAttribute('aria-label', t.addressSuggestions);
  search.placeholder = t.search;
  search.setAttribute('aria-label', t.search);
  $('#error-title').textContent = t.error;
  $('#try-again').textContent = t.retry;
  $('#protection-label').textContent = t.protection;
  $('#blocked-message').textContent = t.emptyPage;
  $('#allow-page').textContent = t.allowPage;
  $('#pending-label').textContent = t.loadingPage;
}

function renderTabs(tabs, selected) {
  const strip = $('#tabs');
  const open = new Set(tabs.map(tab => tab.id));
  for (const [id, element] of tabElements) {
    if (open.has(id)) continue;
    element.remove();
    tabElements.delete(id);
  }
  for (const tab of tabs) {
    let element = tabElements.get(tab.id);
    if (!element) {
      element = document.createElement('div');
      element.className = 'tab';
      element.innerHTML = '<button class="tab-main" role="tab"><i class="tab-dot"></i><bdi></bdi></button><button class="tab-close"><i class="icon cross"></i></button>';
      element.firstElementChild.addEventListener('click', () => action('select', tab.id));
      element.lastElementChild.addEventListener('click', () => action('close-tab', tab.id));
      element.addEventListener('auxclick', event => {
        if (event.button === 1) { event.preventDefault(); action('close-tab', tab.id); }
      });
      strip.append(element);
      tabElements.set(tab.id, element);
    }
    const title = tab.title || (tab.url ? new URL(tab.url).hostname : t.newTab);
    element.firstElementChild.title = title;
    element.querySelector('bdi').textContent = title;
    label(element.lastElementChild, t.closeTab);
    element.classList.toggle('selected', tab.id === selected);
    element.classList.toggle('loading', tab.loading);
    element.firstElementChild.setAttribute('aria-selected', String(tab.id === selected));
  }
  if (previousActive !== selected) tabElements.get(selected)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function renderDownloads() {
  const parent = $('#downloads-panel');
  parent.replaceChildren();
  if (!current.downloads.length) {
    const empty = document.createElement('p');
    empty.className = 'panel-note';
    empty.textContent = t.noDownloads;
    parent.append(empty);
  }
  for (const download of [...current.downloads].reverse()) {
    const row = document.createElement('div');
    row.className = 'download-entry';
    const title = document.createElement('strong');
    title.textContent = download.name;
    title.dir = 'auto';
    const detail = document.createElement('small');
    detail.textContent = t[download.state] ?? download.state;
    row.append(title, detail);
    if (download.state === 'progressing') {
      const progress = document.createElement('progress');
      if (download.total > 0) {
        progress.max = download.total;
        progress.value = download.received;
      }
      row.append(progress);
    }
    const command = download.state === 'completed' ? ['show-download', t.show]
      : download.item === null || download.state !== 'progressing' ? null : ['cancel-download', t.cancel];
    if (command) {
      const button = document.createElement('button');
      button.textContent = command[1];
      button.addEventListener('click', () => action(command[0], download.id));
      row.append(button);
    }
    parent.append(row);
  }
}

function selectSettingsSection(section) {
  settingsSection = section;
  document.querySelectorAll('[data-section]').forEach(button => {
    const selected = button.dataset.section === section;
    button.setAttribute('aria-pressed', String(selected));
    $('#settings-' + button.dataset.section).hidden = !selected;
  });
  settingsFeedback.hidden = true;
  clearConfirmation.hidden = true;
}

function renderSettings(settings) {
  const show = Boolean(settings);
  const opening = show && $('#settings-page').hidden;
  $('#settings-page').hidden = !show;
  if (!show) return;
  if (opening) {
    selectSettingsSection(settingsSection);
    $('#settings-title').focus({ preventScroll: true });
  }
  $('#page-zoom').value = String(current.preferences.zoom);
  $('#ask-download').checked = current.preferences.askDownload;
  $('#download-folder').textContent = settings.downloadFolder;
  $('#reset-folder').disabled = !current.preferences.downloadFolder;
  $('#ask-clear-history').disabled = !settings.historyCount;
  const signature = JSON.stringify([language, settings.excludedSites]);
  if (previousExceptions === signature) return;
  previousExceptions = signature;
  exceptionList.replaceChildren();
  for (const host of settings.excludedSites) {
    const row = document.createElement('div');
    row.className = 'setting-row';
    const name = document.createElement('bdi');
    name.textContent = host;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'setting-button';
    remove.textContent = t.remove;
    remove.setAttribute('aria-label', t.remove + ' ' + host);
    remove.addEventListener('click', () => action('remove-exception', host));
    row.append(name, remove);
    exceptionList.append(row);
  }
}

window.vela.onState(state => {
  current = state;
  setLanguage(state.locale);
  const active = state.active;
  renderTabs(state.tabs, active?.id);
  document.body.classList.toggle('fullscreen', state.fullscreen);
  const settings = state.panel === 'settings';
  const sidePanel = Boolean(state.panel && !settings);
  document.body.classList.toggle('with-panel', sidePanel);
  const showNotice = Boolean(active?.blank) && !state.fullscreen && !settings;
  document.body.classList.toggle('with-notice', showNotice);
  $('#blocked-notice').hidden = !showNotice;
  $('#pending').hidden = settings || !active?.pending;
  const url = active?.url ?? '';
  if (previousActive !== active?.id || previousUrl !== url || document.activeElement !== address) {
    if (address.value !== url) address.value = url;
    address.setCustomValidity('');
  }
  previousActive = active?.id;
  previousUrl = url;
  $('#back').disabled = !settings && !active?.back;
  $('#forward').disabled = settings || !active?.forward;
  $('#reload').disabled = settings || !url;
  $('#reload i').className = 'icon ' + (active?.loading ? 'cross' : 'reload');
  label($('#reload'), active?.loading ? t.stop : t.reload);
  $('#start').hidden = settings || Boolean(url);
  $('#error').hidden = settings || !active?.error;
  $('#error-code').textContent = active?.error ?? '';
  const badge = $('.badge');
  badge.hidden = !active?.blocked || !active.protected;
  badge.textContent = active?.blocked > 99 ? '99+' : active?.blocked ?? '';
  $('#privacy-button').classList.toggle('paused', !active?.protected);
  $('#privacy-button').setAttribute('aria-expanded', String(state.panel === 'privacy'));
  $('#downloads-button').setAttribute('aria-expanded', String(state.panel === 'downloads'));
  $('#settings-button').setAttribute('aria-expanded', String(state.panel === 'settings'));
  $('#panel').hidden = !sidePanel;
  $('#panel-title').textContent = t[state.panel] ?? '';
  renderSettings(state.settings);
  document.documentElement.dataset.theme = state.preferences.theme;
  $('#theme').value = state.preferences.theme;
  $('#startup').value = state.preferences.startup;
  const engine = $('#search-engine');
  engine.value = state.preferences.search;
  search.placeholder = t.searchWith + ' ' + engine.selectedOptions[0].textContent;
  search.setAttribute('aria-label', search.placeholder);
  $('#blocking').checked = state.preferences.blocking;
  $('#history-suggestions').checked = state.preferences.history;
  $('#privacy-panel').hidden = state.panel !== 'privacy';
  $('#downloads-panel').hidden = state.panel !== 'downloads';
  $('#blocked-count').textContent = active?.blocked ?? 0;
  $('#blocked-label').textContent = active?.protected ? t.blocked : active?.temporary ? t.temporary : t.inactive;
  $('#site-settings').hidden = !active?.site;
  $('#site-name').textContent = active?.site ?? '';
  $('#protection').checked = Boolean(active?.protected);
  $('#protection').disabled = !state.preferences.blocking || Boolean(active?.temporary);
  if (state.panel === 'downloads') renderDownloads();
});

window.vela.onSuggestions(({ rows, selected }) => {
  suggestionsOpen = rows.length > 0;
  address.setAttribute('aria-expanded', String(suggestionsOpen));
  accessibleResults.hidden = !suggestionsOpen;
  accessibleResults.replaceChildren();
  for (const [index, row] of rows.entries()) {
    const option = document.createElement('div');
    option.id = 'address-option-' + index;
    option.setAttribute('role', 'option');
    option.setAttribute('aria-selected', String(index === selected));
    option.textContent = row.title;
    accessibleResults.append(option);
  }
  if (selected >= 0) address.setAttribute('aria-activedescendant', 'address-option-' + selected);
  else address.removeAttribute('aria-activedescendant');
});

window.vela.onFocusAddress(openSuggestions => {
  address.focus();
  address.select();
  if (openSuggestions) requestSuggestions(true);
});
address.addEventListener('click', () => requestSuggestions(address.value === (previousUrl ?? '')));
address.addEventListener('input', () => requestSuggestions());
address.addEventListener('keydown', event => {
  if (!event.altKey && !event.ctrlKey && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    event.preventDefault();
    if (!suggestionsOpen) requestSuggestions(address.value === (previousUrl ?? ''));
    action('suggestion-step', event.key === 'ArrowDown' ? 1 : -1);
  } else if (event.key === 'Escape' || event.key === 'Tab') {
    dismissSuggestions();
  }
});
document.addEventListener('pointerdown', event => {
  if (!addressForm.contains(event.target)) dismissSuggestions();
});
window.vela.onInvalidAddress(() => {
  const input = document.activeElement === search ? search : address;
  input.setCustomValidity(t.invalid);
  input.reportValidity();
});
for (const input of [address, search]) input.addEventListener('input', () => input.setCustomValidity(''));
$('#address-form').addEventListener('submit', event => { event.preventDefault(); action('go', address.value); });
$('#search-form').addEventListener('submit', event => { event.preventDefault(); action('search', search.value); });
$('#close-panel').addEventListener('click', () => action(current.panel));
document.querySelectorAll('[data-section]').forEach(button => button.addEventListener('click', () =>
  selectSettingsSection(button.dataset.section)));
$('#add-exception').addEventListener('submit', event => {
  event.preventDefault();
  action('add-exception', $('#exception-site').value);
});
$('#ask-clear-history').addEventListener('click', () => {
  clearConfirmation.hidden = false;
  $('#cancel-clear-history').focus();
});
$('#cancel-clear-history').addEventListener('click', () => {
  clearConfirmation.hidden = true;
  $('#ask-clear-history').focus();
});
window.vela.onSettingsFeedback(message => {
  if (current?.panel !== 'settings' || typeof t[message] !== 'string') return;
  if (message === 'exceptionAdded') $('#exception-site').value = '';
  if (message === 'historyCleared') clearConfirmation.hidden = true;
  settingsFeedback.textContent = t[message];
  settingsFeedback.hidden = false;
});
$('#protection').addEventListener('change', () => action('protection'));
for (const [id, name] of [['theme', 'theme'], ['startup', 'startup'], ['search-engine', 'search'],
  ['blocking', 'blocking'], ['history-suggestions', 'history'], ['page-zoom', 'zoom'], ['ask-download', 'askDownload']]) {
  const input = $('#' + id);
  input.addEventListener('change', () => {
    const value = input.type === 'checkbox' ? input.checked : name === 'zoom' ? Number(input.value) : input.value;
    action('preference', { name, value });
  });
}
document.querySelectorAll('[data-action]').forEach(button =>
  button.addEventListener('click', () => action(button.dataset.action)));
action('ready');
