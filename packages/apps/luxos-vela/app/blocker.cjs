const { readFileSync } = require('node:fs');
const path = require('node:path');
const { FiltersEngine, Request } = require('@ghostery/adblocker');

const rules = ['easylist.txt', 'easyprivacy.txt'];

function loadBlocker(directory) {
  const lists = rules.map(name => readFileSync(path.join(directory, name), 'utf8'));
  return FiltersEngine.parse(lists.join('\n'), {
    loadCosmeticFilters: false,
    loadExtendedSelectors: false,
    loadHTMLFilters: false
  });
}

function blocks(engine, { url, sourceUrl, type }) {
  if (type === 'mainFrame' || !/^(https?|wss?):/i.test(url)) return false;
  return engine.match(Request.fromRawDetails({ url, sourceUrl, type })).match;
}

module.exports = { loadBlocker, blocks, rules };
