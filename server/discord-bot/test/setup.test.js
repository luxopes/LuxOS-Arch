"use strict";
// Nastaveni serveru proti falesnemu Discordu: vytvori vse, druhe spusteni nic nezmeni.

const test = require("node:test");
const assert = require("node:assert/strict");
const { FakeDiscord } = require("./fakes");
const { Rest } = require("../src/rest");
const { Setup, BOT_PERMISSIONS, RULES, SELF_ROLES, ONBOARDING_PROMPT, inviteUrl } = require("../src/setup");

async function run(discord, mode, extra = {}) {
  const lines = [];
  const setup = new Setup({ rest: new Rest({ api: discord.api, token: discord.token }), guildId: "", mode, log: (l) => lines.push(l), ...extra });
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
  assert.ok(byName(discord, "bot-testing"));
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
  // #bot-testing: jen Team + bot, bot smi vlakna
  const testing = byName(discord, "bot-testing");
  assert.equal(discord.channels.find((c) => c.id === testing.parent_id).name, "STAFF");
  assert.ok((BigInt(testing.permission_overwrites.find((o) => o.id === discord.guild.id).deny) & (1n << 10n)) !== 0n, "hidden from @everyone");
  assert.ok(testing.permission_overwrites.some((o) => o.id === roles.Team && (BigInt(o.allow) & (1n << 10n))));
  assert.ok((BigInt(testing.permission_overwrites.find((o) => o.id === discord.bot.id).allow) & (1n << 35n)) !== 0n, "bot creates threads");
  // #bug-reports: bot reaguje a pta se ve vlaknech
  const bugAllow = BigInt(byName(discord, "bug-reports").permission_overwrites.find((o) => o.id === discord.bot.id).allow);
  assert.ok((bugAllow & (1n << 6n)) !== 0n && (bugAllow & (1n << 35n)) !== 0n, "bot may react and open threads in #bug-reports");
  assert.match(discord.posted(byName(discord, "bug-reports").id)[0].content, /Reports here are forwarded to the LuxOS team; the bot may ask for details/);
  assert.match(discord.posted(byName(discord, "testers").id)[0].content, /open to anyone who wants to test/);
  assert.match(discord.posted(byName(discord, "testers").id)[0].content, /lux config channel stable/);

  // Onboarding: povinna otazka s jednou volbou Tester / Member, vychozi verejne kanaly
  assert.equal(discord.onboarding.enabled, true);
  assert.equal(discord.onboarding.mode, 0);
  const prompt = discord.onboarding.prompts[0];
  assert.equal(prompt.title, ONBOARDING_PROMPT);
  assert.equal(prompt.single_select, true);
  assert.equal(prompt.required, true);
  assert.deepEqual(prompt.options.map((o) => o.title), SELF_ROLES.map((r) => r.title));
  assert.deepEqual(prompt.options.map((o) => o.role_ids[0]), [roles.Tester, roles.Member]);
  assert.ok(discord.onboarding.default_channel_ids.length >= 7);
  assert.ok(!discord.onboarding.default_channel_ids.includes(byName(discord, "testers").id), "private channels are not defaults");
  assert.equal(discord.posted(byName(discord, "welcome-and-rules").id).length, 1, "no role buttons when Onboarding works");
  assert.ok(first.setup.notes.some((n) => /Server Settings → Access → "Server rules"/.test(n) && n.includes(RULES[0])), "rules click path");
  assert.ok(!discord.requests.some((r) => r.path.includes("member-verification")), "old screening API not used");
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
  // bez Community neni Onboarding: zprava s tlacitky Tester / Member
  const roleMessage = discord.posted(byName(discord, "welcome-and-rules").id).find((m) => /Choose your role/.test(m.content));
  assert.deepEqual(roleMessage.components[0].components.map((b) => b.custom_id), ["role:Tester", "role:Member"]);
  assert.match(inviteUrl("1", true), /permissions=275146411008$/, "Manage Roles added for the buttons");
  assert.equal(first.setup.usesRoleButtons, true);
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
  assert.equal(result.changes, 3, "topic, new #off-topic and its id in the Onboarding defaults");
  assert.ok(discord.onboarding.default_channel_ids.includes(byName(discord, "off-topic").id));
  assert.match(byName(discord, "ideas").topic, /Ideas and wishes/);
  assert.ok(byName(discord, "off-topic"));
});

test("Onboarding refused by Discord: role buttons instead; idempotent", async (t) => {
  const discord = await new FakeDiscord({ community: true }).start();
  t.after(() => discord.stop());
  discord.onboardingFails = true;
  const first = await run(discord, "auto");
  assert.ok(first.setup.notes.some((n) => /Onboarding could not be set/.test(n)));
  const welcome = discord.posted(byName(discord, "welcome-and-rules").id);
  assert.equal(welcome.length, 2);
  assert.ok(welcome.some((m) => m.components && m.components.length));
  const again = await run(discord, "auto");
  assert.equal(again.result.changes, 0);
});

test("existing Onboarding prompts of the owner are kept; changed options are restored", async (t) => {
  const discord = await new FakeDiscord({ community: true }).start();
  t.after(() => discord.stop());
  await run(discord, "auto");
  discord.onboarding.prompts.push({ id: "123", type: 0, title: "Your language?", single_select: false, required: false, in_onboarding: true,
    options: [{ id: "124", title: "Czech", description: "", role_ids: [], channel_ids: [] }] });
  discord.onboarding.prompts[0].options[0].title = "changed";
  const { result } = await run(discord, "auto");
  assert.equal(result.changes, 1);
  assert.deepEqual(discord.onboarding.prompts.map((p) => p.title), [ONBOARDING_PROMPT, "Your language?"]);
  assert.equal(discord.onboarding.prompts[0].options[0].title, SELF_ROLES[0].title);
});

test("default Discord channels: listed without the flag, deleted with --cleanup-defaults (only empty ones)", async (t) => {
  const discord = await new FakeDiscord({ community: true }).start();
  t.after(() => discord.stop());
  const textCat = discord.addChannel({ name: "Textové kanály", type: 4 });
  const voiceCat = discord.addChannel({ name: "Hlasové kanály", type: 4 });
  const obecne = discord.addChannel({ name: "obecné", type: 0, parent_id: textCat.id });
  discord.addChannel({ name: "Obecné", type: 2, parent_id: voiceCat.id });
  const first = await run(discord, "auto");
  assert.ok(first.setup.notes.some((n) => /Empty default Discord channels outside the LuxOS categories: .*#obecné.*voice Obecné/.test(n) && /--cleanup-defaults/.test(n)));
  assert.ok(byName(discord, "obecné"), "nothing deleted without the flag");

  const second = await run(discord, "auto", { cleanupDefaults: true });
  assert.equal(discord.channels.some((c) => c.name.toLowerCase() === "obecné"), false);
  assert.equal(discord.channels.some((c) => c.id === textCat.id || c.id === voiceCat.id), false, "empty default categories removed");
  assert.ok(second.result.changes >= 4);
  assert.ok(discord.channels.some((c) => c.name === "General" && c.type === 2), "our voice General stays");
  assert.ok(discord.channels.some((c) => c.id === obecne.id) === false);
  const third = await run(discord, "auto", { cleanupDefaults: true });
  assert.equal(third.result.changes, 0);
});

test("a default channel with messages is never deleted", async (t) => {
  const discord = await new FakeDiscord({ community: true }).start();
  t.after(() => discord.stop());
  const obecne = discord.addChannel({ name: "obecné", type: 0 });
  discord.addMessage(obecne.id, { id: "5", username: "someone" }, "ahoj");
  const { setup } = await run(discord, "auto", { cleanupDefaults: true });
  assert.ok(byName(discord, "obecné"));
  assert.ok(setup.notes.some((n) => /#obecné \(a default Discord channel\) has messages/.test(n)));
});

test("minimal bot permissions after setup", () => {
  const bits = BigInt(BOT_PERMISSIONS);
  assert.equal(bits, (1n << 10n) | (1n << 11n) | (1n << 16n) | (1n << 38n));
  assert.equal(bits & 8n, 0n, "no Administrator");
  assert.match(inviteUrl("123"), /client_id=123&scope=bot\+applications\.commands&permissions=274877975552$/);
});
