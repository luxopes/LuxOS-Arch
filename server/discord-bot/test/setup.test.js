"use strict";
// Nastaveni serveru proti falesnemu Discordu: vytvori vse, druhe spusteni nic nezmeni.

const test = require("node:test");
const assert = require("node:assert/strict");
const { FakeDiscord } = require("./fakes");
const { Rest } = require("../src/rest");
const { Setup, BOT_PERMISSIONS, RULES, inviteUrl } = require("../src/setup");

async function run(discord, mode) {
  const lines = [];
  const setup = new Setup({ rest: new Rest({ api: discord.api, token: discord.token }), guildId: "", mode, log: (l) => lines.push(l) });
  const result = await setup.run();
  return { result, lines, setup };
}

const byName = (discord, name) => discord.channels.find((c) => c.name === name);

test("without Community: creates the basics, explains the clicks and stops", async (t) => {
  const discord = await new FakeDiscord().start();
  t.after(() => discord.stop());
  const { result, lines } = await run(discord, "auto");
  assert.equal(result.complete, false);
  assert.deepEqual(discord.roles.filter((r) => !r.managed && r.name !== "@everyone").map((r) => r.name).sort(), ["Member", "Team", "Tester"]);
  assert.ok(byName(discord, "welcome-and-rules"));
  assert.ok(byName(discord, "team"));
  assert.equal(byName(discord, "support"), undefined, "no #support yet (the forum needs Community)");
  const help = lines.join("\n");
  assert.match(help, /Server Settings → Enable Community/);
  assert.match(help, /--enable-community/);
  assert.match(help, /Discoverable/);
});

test("--enable-community: full setup, then a second run changes nothing", async (t) => {
  const discord = await new FakeDiscord().start();
  t.after(() => discord.stop());
  await run(discord, "auto");
  const first = await run(discord, "enable-community");
  assert.equal(first.result.complete, true);
  assert.ok(discord.guild.features.includes("COMMUNITY"));
  assert.equal(discord.guild.rules_channel_id, byName(discord, "welcome-and-rules").id);
  assert.equal(discord.guild.public_updates_channel_id, byName(discord, "team").id);
  assert.equal(discord.guild.verification_level, 1);

  const support = byName(discord, "support");
  assert.equal(support.type, 15, "forum");
  assert.deepEqual(support.available_tags.map((tag) => tag.name), ["Installation", "Hardware", "Apps", "LuxAI", "Solved", "Needs human"]);
  assert.equal(support.available_tags.find((tag) => tag.name === "Needs human").moderated, true);
  assert.equal(byName(discord, "announcements").type, 5, "announcement channel");
  for (const name of ["general", "show-your-desktop", "off-topic", "ideas", "bug-reports", "testers"]) assert.equal(byName(discord, name).type, 0, name);
  assert.equal(byName(discord, "General").type, 2, "voice");
  for (const [name, category] of [["welcome-and-rules", "INFO"], ["general", "COMMUNITY"], ["support", "SUPPORT"], ["testers", "DEVELOPMENT"], ["General", "VOICE"]]) {
    assert.equal(discord.channels.find((c) => c.id === byName(discord, name).parent_id).name, category, `${name} in ${category}`);
  }

  // jen Team a bot pisou do #announcements a #welcome-and-rules; #testers jen Tester + Team
  const roles = Object.fromEntries(discord.roles.map((r) => [r.name, r.id]));
  const ann = byName(discord, "announcements").permission_overwrites;
  assert.ok((BigInt(ann.find((o) => o.id === discord.guild.id).deny) & (1n << 11n)) !== 0n, "@everyone cannot post");
  assert.ok((BigInt(ann.find((o) => o.id === roles.Team).allow) & (1n << 11n)) !== 0n, "Team can post");
  assert.ok((BigInt(ann.find((o) => o.id === discord.bot.id && o.type === 1).allow) & (1n << 11n)) !== 0n, "bot can post");
  const testers = byName(discord, "testers").permission_overwrites;
  assert.ok((BigInt(testers.find((o) => o.id === discord.guild.id).deny) & (1n << 10n)) !== 0n, "hidden from @everyone");
  assert.ok(testers.some((o) => o.id === roles.Tester) && testers.some((o) => o.id === roles.Team));
  const botSupport = BigInt(support.permission_overwrites.find((o) => o.id === discord.bot.id).allow);
  assert.ok((botSupport & (1n << 34n)) !== 0n, "bot may tag threads in #support (Manage Threads)");

  // zpravy: pravidla s AI upozornenim, testeri se staging, bug-reports s GitHubem
  const welcome = discord.posted(byName(discord, "welcome-and-rules").id);
  assert.equal(welcome.length, 1);
  assert.ok(welcome[0].content.length <= 2000);
  assert.match(welcome[0].content, /Support answers come from the LuxOS AI assistant based on the LuxOS documentation/);
  assert.match(welcome[0].content, /info@lux-ai\.cz/);
  assert.match(welcome[0].content, new RegExp(`<#${support.id}>`));
  assert.match(discord.posted(byName(discord, "testers").id)[0].content, /lux config channel staging/);
  assert.match(discord.posted(byName(discord, "bug-reports").id)[0].content, /github\.com\/luxopes\/LuxOS-Arch\/issues/);
  assert.match(byName(discord, "bug-reports").topic, /github\.com/);

  assert.equal(discord.commands.length, 1);
  assert.equal(discord.commands[0].name, "human");
  assert.equal(discord.screening.enabled, true);
  assert.deepEqual(discord.screening.form_fields[0].values, RULES);
  assert.match(first.result.invite, /^https:\/\/discord\.gg\/luxos0$/);
  assert.equal(discord.invites[0].max_age, 0);

  const mutationsBefore = discord.mutations().length;
  const second = await run(discord, "auto");
  assert.equal(second.result.changes, 0);
  assert.equal(discord.mutations().length, mutationsBefore, "second run sends no changes to Discord");
  assert.equal(second.result.invite, first.result.invite, "same invite link");
});

test("Community already on (clicked by the owner): wizard channels are reported, not deleted", async (t) => {
  const discord = await new FakeDiscord({ community: true }).start();
  t.after(() => discord.stop());
  discord.addChannel({ name: "rules", type: 0 });
  discord.addChannel({ name: "moderator-only", type: 0 });
  const { result, setup } = await run(discord, "auto");
  assert.equal(result.complete, true);
  assert.ok(byName(discord, "rules"), "not deleted");
  assert.ok(setup.notes.some((n) => /#rules was created by the Community wizard/.test(n)));
  assert.equal(discord.guild.rules_channel_id, byName(discord, "welcome-and-rules").id);
  const again = await run(discord, "auto");
  assert.equal(again.result.changes, 0);
});

test("--no-community: text #support and read-only text #announcements; idempotent", async (t) => {
  const discord = await new FakeDiscord().start();
  t.after(() => discord.stop());
  const first = await run(discord, "no-community");
  assert.equal(first.result.complete, true);
  assert.equal(byName(discord, "support").type, 0);
  assert.equal(byName(discord, "announcements").type, 0);
  assert.equal(discord.guild.features.includes("COMMUNITY"), false);
  assert.equal(discord.screening.enabled, false, "screening needs Community");
  const before = discord.mutations().length;
  const second = await run(discord, "no-community");
  assert.equal(second.result.changes, 0);
  assert.equal(discord.mutations().length, before);

  // Community zapnuta pozdeji: #announcements se prevede, #support zustane s poznamkou
  discord.guild.features.push("COMMUNITY");
  const third = await run(discord, "auto");
  assert.equal(byName(discord, "announcements").type, 5);
  assert.ok(third.setup.notes.some((n) => /delete #support/.test(n)));
});

test("drift is repaired: a changed topic and a deleted channel come back", async (t) => {
  const discord = await new FakeDiscord({ community: true }).start();
  t.after(() => discord.stop());
  await run(discord, "auto");
  byName(discord, "ideas").topic = "something else";
  discord.channels = discord.channels.filter((c) => c.name !== "off-topic");
  const { result } = await run(discord, "auto");
  assert.equal(result.changes, 2);
  assert.match(byName(discord, "ideas").topic, /Ideas and wishes/);
  assert.ok(byName(discord, "off-topic"));
});

test("minimal bot permissions after setup", () => {
  const bits = BigInt(BOT_PERMISSIONS);
  assert.equal(bits, (1n << 10n) | (1n << 11n) | (1n << 16n) | (1n << 38n));
  assert.equal(bits & 8n, 0n, "no Administrator");
  assert.match(inviteUrl("123"), /client_id=123&scope=bot\+applications\.commands&permissions=274877975552$/);
});
