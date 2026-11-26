const assert = require('node:assert/strict');
const path = require('node:path');

const application = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const { loadBlocker, blocks } = require(path.join(application, 'app', 'blocker.cjs'));
const blocker = loadBlocker(path.join(application, 'rules'));
const sourceUrl = 'https://example.org/';
const match = (url, type = 'script') => blocks(blocker, { url, sourceUrl, type });

assert.equal(match('https://ad.doubleclick.net/ads.js'), true);
assert.equal(match('https://www.google-analytics.com/analytics.js'), true);
assert.equal(match('https://example.org/content.js'), false);
assert.equal(match('https://ad.doubleclick.net/ads.js', 'mainFrame'), false);
console.log('EasyList and EasyPrivacy block ads and trackers without blocking ordinary scripts or direct navigation.');
