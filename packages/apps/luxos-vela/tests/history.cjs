const assert = require('node:assert/strict');
const path = require('node:path');

const application = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const { History } = require(path.join(application, 'app', 'history.cjs'));
const history = new History(undefined, [
  'https://www.google.com/search?q=%C4%8Desk%C3%A9+hled%C3%A1n%C3%AD&source=test',
  'https://example.org/oauth?code=private',
  'https://example.org/docs#section-1'
]);
history.record('https://duckduckgo.com/?q=%C4%8Desk%C3%A9+hled%C3%A1n%C3%AD');
history.record('https://duckduckgo.com/?q=%C4%8Desk%C3%A9+hled%C3%A1n%C3%AD');
const key = history.record('https://example.org/docs#section-2', 'Dokumentace');
history.updateTitle(key, 'Česká dokumentace');

assert.deepEqual(history.suggestions('').map(row => row.value), ['české hledání', 'https://example.org/docs']);
assert.equal(history.suggestions('ceske hle')[0].kind, 'search');
assert.equal(history.suggestions('ceska dok')[0].value, 'https://example.org/docs');
assert.equal(history.suggestions('example.org')[0].title, 'Česká dokumentace');
assert.deepEqual(history.suggestions('private'), []);
assert.strictEqual(history.serialize().find(row => row.kind === 'search').visits, 3);
assert.deepEqual(new History(history.serialize(), []).suggestions('ceske hle').map(row => row.value), ['české hledání']);
console.log('Local history ranks visits and searches, preserves entries, and skips OAuth callbacks.');
