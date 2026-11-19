"use strict";
// Oznameni z announcements.json a release.json: kazde jen jednou, i po restartu (stavovy soubor).

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { FakeDiscord, FakeSite } = require("./fakes");
const { Rest } = require("../src/rest");
const { State } = require("../src/state");
const { Announcer } = require("../src/announce");
const { load } = require("../src/config");

const day = (offset) => new Date(Date.now() + offset * 86400_000).toISOString().slice(0, 10);

test("announcements are posted once, old/expired/future ones are skipped", async (t) => {
  const discord = await new FakeDiscord({ community: true }).start();
  const site = await new FakeSite().start();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luxos-discord-ann-"));
  t.after(async () => { await discord.stop(); await site.stop(); fs.rmSync(dir, { recursive: true, force: true }); });

  const channel = discord.addChannel({ name: "announcements", type: 5 });
  const config = load();
  config.announce = { ...config.announce, url: site.url("announcements.json"), releaseUrl: site.url("release.json"), releases: true };
  const rest = new Rest({ api: discord.api, token: discord.token });
  const bot = { findChannel: (name) => (name === "announcements" ? channel : null) };
  const make = () => new Announcer({ config, rest, state: new State(path.join(dir, "state.json")), bot, log: () => {} });

  site.announcements.announcements = [
    { id: "old-news", date: day(-30), title: "Old news" },
    { id: "maintenance", date: day(-1), title: { en: "Server maintenance", cs: "Údržba" }, body: { en: "Short outage on Sunday." }, url: "https://luxos.lux-ai.cz/" },
    { id: "expired", date: day(-3), until: day(-2), title: "Expired" },
    { id: "future", date: day(2), title: "Planned" },
    { id: "BAD ID", date: day(0), title: "invalid" }
  ];
  let announcer = make();
  assert.equal(await announcer.poll(), 1);
  let posted = discord.posted(channel.id);
  assert.equal(posted.length, 1);
  assert.equal(posted[0].content, "**Server maintenance**\nShort outage on Sunday.\n<https://luxos.lux-ai.cz/>");
  assert.ok(discord.requests.some((r) => r.path.endsWith(`/messages/${posted[0].id}/crosspost`)), "published to followers");
  announcer.state.flush();

  // restart bota: stav ze souboru, nic znovu
  announcer = make();
  assert.equal(await announcer.poll(), 0);

  // nova polozka + nove vydani (ohlasene i v announcements.json -> neopakovat)
  site.announcements.announcements.unshift({ id: "luxos-1-0-4", date: day(0), title: "LuxOS 1.0.4 is out" });
  site.release = { version: "1.0.4", codename: "Sirius" };
  assert.equal(await announcer.poll(), 1);
  assert.equal(await announcer.poll(), 0);
  posted = discord.posted(channel.id);
  assert.equal(posted.length, 2);
  assert.match(posted[1].content, /LuxOS 1\.0\.4 is out/);

  // vydani bez oznameni: zprava z release.json, jen jednou
  site.release = { version: "1.1.0", codename: "Vega" };
  assert.equal(await announcer.poll(), 1);
  assert.equal(await announcer.poll(), 0);
  posted = discord.posted(channel.id);
  assert.match(posted[2].content, /^\*\*LuxOS 1\.1\.0 “Vega” is out\*\*/);
  assert.match(posted[2].content, /<https:\/\/luxos\.lux-ai\.cz\/changes\/>/);
});

test("first run remembers the current release without posting; bad feed posts nothing", async (t) => {
  const discord = await new FakeDiscord().start();
  const site = await new FakeSite().start();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luxos-discord-ann-"));
  t.after(async () => { await discord.stop(); await site.stop(); fs.rmSync(dir, { recursive: true, force: true }); });
  const channel = discord.addChannel({ name: "announcements", type: 0 });
  const config = load();
  config.announce = { ...config.announce, url: site.url("announcements.json"), releaseUrl: site.url("release.json") };
  const announcer = new Announcer({ config, rest: new Rest({ api: discord.api, token: discord.token }),
    state: new State(path.join(dir, "state.json")), bot: { findChannel: () => channel }, log: () => {} });
  assert.equal(await announcer.poll(), 0);
  assert.equal(announcer.state.data.announcements.release, "1.0.3");
  site.announcements = { version: 2, announcements: [{ id: "x", date: day(0), title: "x" }] };
  await assert.rejects(announcer.poll(), /unknown format/);
  assert.equal(discord.posted(channel.id).length, 0);
  assert.ok(!discord.requests.some((r) => r.path.endsWith("/crosspost")), "text channel: no crosspost");
});
