const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { _electron: electron } = require('playwright');

async function until(page, check, expected) {
  await page.waitForFunction(check, expected, { timeout: 10000 });
}

async function run() {
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'vela-browser-test-'));
  const requests = [];
  const server = http.createServer((request, response) => {
    requests.push([request.headers.host, request.url]);
    response.setHeader('Cache-Control', 'no-store');
    if (request.url === '/slow') {
      // Hold the headers until closing the pending tab cancels the request.
    } else if (request.url === '/failed') {
      request.socket.destroy();
    } else if (request.url === '/download') {
      response.setHeader('Content-Disposition', 'attachment; filename="vela-fixture.txt"');
      response.end('Vela download fixture');
    } else if (request.url === '/redirect') {
      response.writeHead(302, { Location: '/second' }).end();
    } else if (request.url === '/blank') {
      const port = server.address().port;
      response.end(`<!doctype html><title>Vela blank fixture</title><main></main>
        <script src="http://ad.doubleclick.net:${port}/blocked-content.js"></script>`);
    } else if (request.url === '/blocked-content.js') {
      response.setHeader('Content-Type', 'text/javascript');
      response.end('document.querySelector("main").textContent = "Content restored";');
    } else if (request.url === '/content.js' || request.url === '/analytics.js' || request.url === '/ads.js') {
      response.setHeader('Content-Type', 'text/javascript');
      response.setHeader('Access-Control-Allow-Origin', '*');
      response.end('window.loadedScripts = (window.loadedScripts || 0) + 1;');
    } else if (request.url === '/long-title') {
      response.end('<!doctype html><title>Wide ' + 'a very long title '.repeat(25) + '</title><main>Long title fixture</main>');
    } else if (request.url === '/second') {
      response.end('<!doctype html><title>Vela second page</title><strong>Second page</strong>');
    } else {
      const port = server.address().port;
      response.end(`<!doctype html><title>Vela fixture</title>
        <a href="/slow" id="slow">Slow page</a>
        <a href="/download" id="download">Download fixture</a>
        <a href="/redirect" id="redirect">Follow a redirect</a>
        <a href="/second" target="_blank" id="new-tab">Open a tab</a>
        <script src="/content.js"></script>
        <script src="http://ad.doubleclick.net:${port}/ads.js"></script>
        <script src="http://pixel.quantserve.com:${port}/analytics.js"></script>`);
    }
  });
  let browser;
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = 'http://127.0.0.1:' + server.address().port;
  const appDir = process.env.VELA_APP || path.resolve(__dirname, '..');
  const args = [
    '--host-resolver-rules=MAP ad.doubleclick.net 127.0.0.1, MAP pixel.quantserve.com 127.0.0.1',
    '--no-proxy-server', appDir
  ];
  const env = { ...process.env, XDG_CONFIG_HOME: profile };
  const executablePath = process.env.VELA_ELECTRON || '/usr/lib/electron44/electron';
  const launch = () => electron.launch({ executablePath, args, env, chromiumSandbox: true, timeout: 15000 });
  try {
    browser = await launch();
    let chrome = await browser.firstWindow();
    chrome.setDefaultTimeout(10000);
    await chrome.locator('#tabs [aria-selected=true]').waitFor();
    if (process.env.VELA_SCREENSHOT) await chrome.screenshot({ path: process.env.VELA_SCREENSHOT });
    await chrome.locator('#address').fill('file:///etc/passwd');
    await chrome.locator('#address').press('Enter');
    await until(chrome, () => !document.querySelector('#address').validity.valid);
    const go = async target => {
      await chrome.locator('#address').fill(target);
      await chrome.locator('#address').press('Enter');
    };
    await go(url);
    await until(chrome, () => document.querySelector('.selected bdi')?.textContent === 'Vela fixture');
    const tabWidth = await chrome.locator('.tab.selected').evaluate(tab => tab.getBoundingClientRect().width);
    const addressInput = chrome.locator('#address');
    const expectSuggestion = text => until(chrome, label =>
      Array.from(document.querySelectorAll('#address-accessible-results [role=option]')).some(option => option.textContent.startsWith(label)), text);
    await go(url + '/long-title');
    await until(chrome, () => document.querySelector('.selected bdi')?.textContent.startsWith('Wide'));
    const longTitle = await chrome.locator('.tab.selected').evaluate(tab => {
      const label = tab.querySelector('bdi');
      const close = tab.querySelector('.tab-close').getBoundingClientRect();
      const bounds = tab.getBoundingClientRect();
      return { width: bounds.width, truncated: label.scrollWidth > label.clientWidth, closeInside: close.right < bounds.right };
    });
    assert.deepEqual(longTitle, { width: tabWidth, truncated: true, closeInside: true });
    await addressInput.fill('vela fix');
    await expectSuggestion('Vela fixture');
    const popup = await browser.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0];
      const views = win.contentView.children;
      const hints = views.find(view => view.webContents?.getURL().endsWith('/address-suggestions.html'));
      const page = views.find(view => view.webContents?.getURL().includes('/long-title'));
      return { visible: hints?.getVisible(), onTop: views.at(-1) === hints, pageTop: page?.getBounds().y };
    });
    assert.deepEqual(popup, { visible: true, onTop: true, pageTop: 96 });
    await addressInput.press('ArrowDown');
    await until(chrome, () => document.querySelector('#address').hasAttribute('aria-activedescendant'));
    await addressInput.press('Enter');
    await until(chrome, () => document.querySelector('.selected bdi')?.textContent === 'Vela fixture');
    await addressInput.fill('wide');
    await expectSuggestion('Wide');
    await addressInput.press('Escape');
    await until(chrome, () => document.querySelector('#address').getAttribute('aria-expanded') === 'false');
    await addressInput.fill('wide');
    await expectSuggestion('Wide');
    await browser.evaluate(({ webContents }) => webContents.getAllWebContents()
      .find(contents => contents.getURL().endsWith('/address-suggestions.html'))
      .executeJavaScript("document.querySelector('.address-result').click()"));
    await until(chrome, () => document.querySelector('.selected bdi')?.textContent.startsWith('Wide'));
    await go(url);
    await until(chrome, () => document.querySelector('.selected bdi')?.textContent === 'Vela fixture');
    const evaluatePage = expression => browser.evaluate(({ webContents }, code) => {
      const page = webContents.getAllWebContents().find(contents => contents.getURL().startsWith('http://127.0.0.1:'));
      return page?.executeJavaScript(code, true);
    }, expression);
    await until(chrome, () => document.querySelector('.badge').textContent === '2');
    await until(chrome, () => !document.querySelector('.selected').classList.contains('loading'));
    assert.deepEqual(await evaluatePage('[typeof window.vela, typeof require, typeof process, loadedScripts]'),
      ['undefined', 'undefined', 'undefined', 1]);
    assert.equal(requests.some(([, resource]) => ['/analytics.js', '/ads.js'].includes(resource)), false);

    if (process.env.VELA_TEST_GPU === '1') {
      const gpu = await evaluatePage(`(async () => {
        const adapter = await navigator.gpu.requestAdapter();
        if (!adapter) return null;
        const device = await adapter.requestDevice();
        const input = device.createBuffer({ size: 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC });
        const output = device.createBuffer({ size: 4, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
        const module = device.createShaderModule({ code:
          '@group(0) @binding(0) var<storage,read_write> data: array<u32>; @compute @workgroup_size(1) fn main() { data[0] = 42u; }' });
        const pipeline = device.createComputePipeline({ layout: 'auto', compute: { module } });
        const bind = device.createBindGroup({ layout: pipeline.getBindGroupLayout(0),
          entries: [{ binding: 0, resource: { buffer: input } }] });
        const commands = device.createCommandEncoder();
        const pass = commands.beginComputePass();
        pass.setPipeline(pipeline);
        pass.setBindGroup(0, bind);
        pass.dispatchWorkgroups(1);
        pass.end();
        commands.copyBufferToBuffer(input, 0, output, 0, 4);
        device.queue.submit([commands.finish()]);
        await output.mapAsync(GPUMapMode.READ);
        const result = { value: new Uint32Array(output.getMappedRange())[0],
          vendor: adapter.info.vendor, fallback: adapter.info.isFallbackAdapter };
        output.unmap();
        device.destroy();
        return result;
      })()`);
      assert.equal(gpu?.value, 42);
      assert.equal(gpu?.fallback, false);
      console.log('GPU compute shader completed on', gpu.vendor);
    }

    await chrome.locator('#privacy-button').click();
    await chrome.locator('#protection').uncheck();
    await until(chrome, () => document.querySelector('#privacy-button').classList.contains('paused'));
    await until(chrome, () => !document.querySelector('.selected').classList.contains('loading'));
    assert.equal(await evaluatePage('loadedScripts'), 3, JSON.stringify(requests));
    assert(requests.some(([, resource]) => resource === '/ads.js'));
    assert(requests.some(([, resource]) => resource === '/analytics.js'));
    await chrome.locator('#protection').check();
    await until(chrome, () => document.querySelector('.badge').textContent === '2');
    if (process.env.VELA_PRIVACY_SCREENSHOT) await chrome.screenshot({ path: process.env.VELA_PRIVACY_SCREENSHOT });

    const settingsSection = name => chrome.locator(`[data-section="${name}"]`).click();
    await chrome.locator('#settings-button').click();
    await chrome.locator('#settings-page').waitFor();
    assert.equal(await chrome.locator('#panel').isVisible(), false);
    const visibleViews = () => browser.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].contentView.children
      .filter(view => view.webContents && view.getVisible()).length);
    assert.equal(await visibleViews(), 0);
    await chrome.locator('#theme').selectOption('dark');
    await until(chrome, () => getComputedStyle(document.documentElement).colorScheme === 'dark');
    await chrome.locator('#search-engine').selectOption('seznam');
    await until(chrome, () => document.querySelector('#search').placeholder.endsWith('Seznam'));
    await chrome.locator('#page-zoom').selectOption('1.25');
    const zoom = () => browser.evaluate(({ webContents }) => webContents.getAllWebContents()
      .find(contents => contents.getURL().startsWith('http://127.0.0.1:')).getZoomFactor());
    assert(Math.abs(await zoom() - 1.25) < 0.00001);
    await settingsSection('privacy');
    await chrome.locator('#exception-site').fill('invalid.example/path');
    await chrome.locator('#exception-site').press('Enter');
    await chrome.locator('#settings-feedback').waitFor({ state: 'visible' });
    assert.equal(await chrome.locator('#exceptions-list button').count(), 0);
    await chrome.locator('#exception-site').fill('127.0.0.1');
    await chrome.locator('#exception-site').press('Enter');
    await chrome.locator('#exceptions-list button').waitFor();
    await until(chrome, () => document.querySelector('#privacy-button').classList.contains('paused') &&
      !document.querySelector('.selected').classList.contains('loading'));
    assert.equal(await evaluatePage('loadedScripts'), 3);
    await chrome.locator('#exceptions-list button').click();
    await until(chrome, () => document.querySelector('.badge').textContent === '2');
    await chrome.locator('#blocking').uncheck();
    await until(chrome, () => document.querySelector('#privacy-button').classList.contains('paused') &&
      !document.querySelector('.selected').classList.contains('loading'));
    assert.equal(await evaluatePage('loadedScripts'), 3);
    await chrome.locator('#blocking').check();
    await until(chrome, () => document.querySelector('.badge').textContent === '2');
    if (process.env.VELA_SETTINGS_SCREENSHOT) await chrome.screenshot({ path: process.env.VELA_SETTINGS_SCREENSHOT });
    await settingsSection('downloads');
    const folder = path.join(profile, 'test-downloads');
    await fs.mkdir(folder);
    await fs.writeFile(path.join(folder, 'vela-fixture.txt'), 'existing');
    await browser.evaluate(({ dialog }, directory) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [directory] });
    }, folder);
    await chrome.locator('#choose-folder').click();
    await until(chrome, expected => document.querySelector('#download-folder').textContent === expected, folder);
    await chrome.locator('#ask-download').uncheck();
    await chrome.locator('#close-settings').click();
    assert.equal(await visibleViews(), 1);
    await evaluatePage("document.querySelector('#download').click()");
    await chrome.locator('#downloads-button').click();
    await chrome.locator('#downloads-panel .download-entry button').waitFor({ state: 'visible' });
    assert.equal(await fs.readFile(path.join(folder, 'vela-fixture.txt'), 'utf8'), 'existing');
    assert.equal(await fs.readFile(path.join(folder, 'vela-fixture (1).txt'), 'utf8'), 'Vela download fixture');
    await chrome.locator('#close-panel').click();

    const pressShortcut = (keyCode, modifiers = []) => browser.evaluate(({ BrowserWindow, webContents }, key) => {
      const win = BrowserWindow.getAllWindows()[0];
      const contents = webContents.getFocusedWebContents() ?? win.webContents;
      contents.sendInputEvent({ type: 'keyDown', ...key });
      if (!contents.isDestroyed()) contents.sendInputEvent({ type: 'keyUp', ...key });
    }, { keyCode, modifiers });
    await evaluatePage("document.querySelector('#slow').click()");
    await chrome.locator('#pending').waitFor();
    assert.equal(await browser.evaluate(({ BrowserWindow, webContents }) =>
      BrowserWindow.getAllWindows()[0].webContents === webContents.getFocusedWebContents()), true);
    await pressShortcut('T', ['control']);
    await until(chrome, () => document.querySelectorAll('.tab').length === 2 && !document.querySelector('#start').hidden);
    await chrome.locator('.tab-main').first().click();
    await chrome.locator('#pending').waitFor();
    await pressShortcut('W', ['control']);
    await until(chrome, () => document.querySelectorAll('.tab').length === 1 && !document.querySelector('#start').hidden);
    await go(url + '/slow');
    await chrome.locator('#pending').waitFor();
    await pressShortcut('W', ['control']);
    await until(chrome, () => !document.querySelector('#start').hidden);

    await go(url);
    await until(chrome, () => document.querySelector('.selected bdi')?.textContent === 'Vela fixture');
    const verifyGeometry = async expected => {
      await until(chrome, fullscreen => document.body.classList.contains('fullscreen') === fullscreen, expected);
      let dimensions;
      for (let attempt = 0; attempt < 30; attempt++) {
        dimensions = await browser.evaluate(({ BrowserWindow }) => {
          const win = BrowserWindow.getAllWindows()[0];
          const [width, height] = win.getContentSize();
          const view = win.contentView.children.find(child => child.webContents && child.getVisible());
          return { width, height, bounds: view.getBounds(), fullscreen: win.isFullScreen() };
        });
        const { width, height, bounds, fullscreen } = dimensions;
        if (fullscreen === expected && bounds.x === 0 && bounds.y === (expected ? 0 : 96) &&
          bounds.width === width && bounds.height + bounds.y === height) return;
        await new Promise(resolve => setTimeout(resolve, 35));
      }
      assert.fail(JSON.stringify(dimensions));
    };
    await pressShortcut('F11');
    await verifyGeometry(true);
    await pressShortcut('F11');
    await verifyGeometry(false);
    await evaluatePage('document.documentElement.requestFullscreen()');
    await verifyGeometry(true);
    assert.equal(await evaluatePage('Boolean(document.fullscreenElement)'), true);
    await pressShortcut('Escape');
    await verifyGeometry(false);
    for (let attempt = 0; attempt < 30 && await evaluatePage('Boolean(document.fullscreenElement)'); attempt++)
      await new Promise(resolve => setTimeout(resolve, 35));
    assert.equal(await evaluatePage('Boolean(document.fullscreenElement)'), false);
    await pressShortcut('F11');
    await verifyGeometry(true);
    await evaluatePage('document.documentElement.requestFullscreen()');
    await evaluatePage('document.exitFullscreen()');
    await verifyGeometry(true);
    await pressShortcut('F11');
    await verifyGeometry(false);

    await go(url + '/failed');
    await chrome.locator('#error').waitFor({ state: 'visible' });
    assert.match(await chrome.locator('#error-code').textContent(), /^ERR_/);
    await go(url + '/blank');
    await chrome.locator('#blocked-notice').waitFor({ state: 'visible' });
    assert.equal(await evaluatePage('document.body.innerText.trim()'), '');
    await chrome.locator('#allow-page').click();
    await chrome.locator('#blocked-notice').waitFor({ state: 'hidden' });
    await until(chrome, () => !document.querySelector('.selected').classList.contains('loading'));
    assert.equal(await evaluatePage('document.querySelector("main").textContent'), 'Content restored');
    await go(url);
    await until(chrome, () => document.querySelector('.badge').textContent === '2');

    await evaluatePage("document.querySelector('#redirect').click()");
    await until(chrome, target => document.querySelector('#address').value === target, url + '/second');
    await chrome.locator('#back').click();
    await until(chrome, () => document.querySelector('.selected bdi')?.textContent === 'Vela fixture');
    await evaluatePage("document.querySelector('#new-tab').click()");
    await until(chrome, () => document.querySelectorAll('#tabs .tab').length === 2
      && document.querySelector('.selected bdi')?.textContent === 'Vela second page');
    await browser.close();
    browser = await launch();
    chrome = await browser.firstWindow();
    await until(chrome, () => document.querySelectorAll('#tabs .tab').length === 2
      && document.querySelector('.selected bdi')?.textContent === 'Vela second page');
    await chrome.locator('#settings-button').click();
    await settingsSection('general');
    assert.equal(await chrome.locator('#page-zoom').inputValue(), '1.25');
    assert.equal(await chrome.locator('#theme').inputValue(), 'dark');
    assert.equal(await chrome.locator('#search-engine').inputValue(), 'seznam');
    await settingsSection('downloads');
    assert.equal(await chrome.locator('#download-folder').textContent(), folder);
    assert.equal(await chrome.locator('#ask-download').isChecked(), false);
    await chrome.locator('#reset-folder').click();
    await until(chrome, value => document.querySelector('#download-folder').textContent !== value, folder);
    await chrome.locator('#close-settings').click();
    await chrome.locator('#address').fill('wide');
    await expectSuggestion('Wide');
    await chrome.locator('#settings-button').click();
    await settingsSection('privacy');
    await chrome.locator('#ask-clear-history').click();
    await chrome.locator('#cancel-clear-history').click();
    assert.equal(await chrome.locator('#ask-clear-history').isEnabled(), true);
    await chrome.locator('#ask-clear-history').click();
    await chrome.locator('#confirm-clear-history').click();
    await until(chrome, () => document.querySelector('#ask-clear-history').disabled);
    await chrome.locator('#history-suggestions').uncheck();
    await chrome.locator('#close-settings').click();
    await chrome.locator('#address').fill('wide');
    assert.equal(await chrome.locator('#address').getAttribute('aria-expanded'), 'false');
    await chrome.locator('#settings-button').click();
    await settingsSection('general');
    await chrome.locator('#startup').selectOption('new');
    await browser.close();
    browser = await launch();
    chrome = await browser.firstWindow();
    await until(chrome, () => document.querySelectorAll('#tabs .tab').length === 1
      && document.querySelector('#address').value === '');
    const saved = JSON.parse(await fs.readFile(path.join(profile, 'Lux Vela', 'vela-state.json'), 'utf8'));
    assert.deepEqual(saved.history, []);
    assert.equal(saved.preferences.history, false);
    console.log('Browser, settings, fullscreen, blank-site recovery, blocking, navigation and session tests passed.');
  } finally {
    await browser?.close();
    server.closeAllConnections();
    server.close();
    await fs.rm(profile, { recursive: true, force: true });
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
