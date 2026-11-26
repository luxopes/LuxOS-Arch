const path = require('node:path');
const { WebContentsView } = require('electron');

const rowHeight = 42;
const popupPadding = 22;
const top = 93;

class AddressSuggestions {
  constructor(win, webPreferences, getTheme) {
    this.win = win;
    this.webPreferences = webPreferences;
    this.getTheme = getTheme;
    this.results = [];
    this.selected = -1;
    this.generation = 0;
  }

  open(results, input) {
    if (!results.length) return this.close();
    this.results = results;
    this.input = input;
    this.selected = -1;
    this.generation++;
    if (!this.view) this.createView();
    this.draw();
  }

  createView() {
    const view = new WebContentsView({ webPreferences: this.webPreferences });
    this.view = view;
    view.setBackgroundColor('#00000000');
    view.setVisible(false);
    this.win.contentView.addChildView(view);
    const contents = view.webContents;
    contents.on('will-navigate', event => event.preventDefault());
    contents.on('will-redirect', event => event.preventDefault());
    contents.setWindowOpenHandler(() => ({ action: 'deny' }));
    contents.loadFile(path.join(__dirname, 'address-suggestions.html')).then(() => {
      this.ready = true;
      this.draw();
    }).catch(() => this.close());
  }

  accepts(event) {
    const contents = this.view?.webContents;
    return Boolean(contents && !contents.isDestroyed() && event.sender === contents && event.senderFrame === contents.mainFrame);
  }

  step(direction) {
    if (!this.results.length || ![-1, 1].includes(direction)) return;
    const count = this.results.length;
    this.selected = this.selected === -1 ? (direction > 0 ? 0 : count - 1) : (this.selected + direction + count) % count;
    this.draw();
  }

  choice(input) {
    return this.input?.value === input ? this.results[this.selected] : undefined;
  }

  clicked(value) {
    if (value?.generation !== this.generation || !Number.isInteger(value.index)) return undefined;
    return this.results[value.index];
  }

  close() {
    if (!this.results.length) return false;
    this.results = [];
    this.input = undefined;
    this.selected = -1;
    this.draw();
    return true;
  }

  layout() {
    if (!this.view || this.win.isDestroyed()) return;
    if (!this.results.length || !this.ready || this.win.isFullScreen()) {
      this.view.setVisible(false);
      return;
    }
    const { width: available } = this.win.contentView.getBounds();
    const x = Math.min(Math.round(this.input.x), Math.max(0, available - 140));
    const width = Math.max(1, Math.min(Math.round(this.input.width), available - x, 744));
    this.view.setBounds({ x, y: top, width, height: popupPadding + this.results.length * rowHeight });
    if (!this.view.getVisible()) {
      // The suggestions float above the page without resizing its viewport.
      this.win.contentView.addChildView(this.view);
      this.view.setVisible(true);
    }
  }

  draw() {
    if (this.win.isDestroyed()) return;
    if (this.results.length && !this.ready) return;
    const state = { rows: this.results, selected: this.selected, generation: this.generation, theme: this.getTheme() };
    if (this.ready && !this.view.webContents.isDestroyed()) this.view.webContents.send('vela:suggestions', state);
    this.layout();
    this.win.webContents.send('vela:suggestions', state);
  }

  destroy() {
    const contents = this.view?.webContents;
    if (contents && !contents.isDestroyed()) contents.close();
  }
}

module.exports = { AddressSuggestions };
