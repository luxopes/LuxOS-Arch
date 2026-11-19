"use strict";
// Bot proti falesnemu Discordu (Gateway + REST), lux-api a SMTP.

const test = require("node:test");
const assert = require("node:assert/strict");
const { startBot, user, meta, waitFor } = require("./harness");

const APPS = "https://luxos.lux-ai.cz/docs/luxos/apps.html";
const CARE = "https://luxos.lux-ai.cz/docs/luxos/care-updates.html";
const NOT_FOUND = /couldn't find this in the LuxOS documentation, so I've passed your question to the LuxOS team/;

test("answers every new post in the #support forum: docs in the prompt, cited answer posted, no mail", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const alice = user("alice");
  h.luxapi.reply = () => `Open the **Store** and click Install.\nSee ${APPS}\n${meta({})}`;

  const thread = h.discord.forumPost(h.support.id, alice, "How do I install apps?", "Where do I get new apps?");
  const [reply] = await waitFor(() => h.discord.posted(thread.id).length && h.discord.posted(thread.id), 3000, "reply");
  assert.match(reply.content, /Store/);
  assert.doesNotMatch(reply.content, /META/);
  assert.equal(reply.flags, 4, "link embeds suppressed");
  assert.deepEqual(reply.allowed_mentions.parse, [], "never pings anyone");

  assert.equal(h.luxapi.keywordRequests.length, 1, "topic keywords first");
  assert.equal(h.luxapi.requests.length, 1);
  const request = h.luxapi.requests[0];
  assert.equal(request.model, "flash");
  assert.equal(request.reasoning_effort, "low");
  assert.equal(request.max_tokens, 4000, "room for Flash's thinking");
  assert.match(request.messages[0].content, /Answer ONLY from the documentation excerpts/);
  assert.match(request.messages[0].content, /docs\/luxos\/apps\.html/, "top passage in the prompt");
  assert.match(request.messages.at(-1).content, /How do I install apps\?\n\nWhere do I get new apps\?/);

  // druha otazka tazatele ve vlakne: odpoved s historii
  h.luxapi.reply = () => `Right-click it in Launchpad, see ${APPS}\n${meta({})}`;
  h.discord.userMessage(thread.id, alice, "And how do I remove one?");
  await waitFor(() => h.discord.posted(thread.id).length === 2, 3000, "follow-up");
  assert.deepEqual(h.luxapi.requests[1].messages.map((m) => m.role), ["system", "user", "assistant", "user"]);

  // dik ve vlakne: bez tematu, bot mlci
  h.luxapi.keywords = () => "NONE";
  h.discord.userMessage(thread.id, alice, "thanks!");
  // cizi uzivatel ve vlakne bez zminky: bot mlci
  h.discord.userMessage(thread.id, user("bob"), "same problem here");
  await h.settle();
  assert.equal(h.discord.posted(thread.id).length, 2);
  assert.equal(h.luxapi.requests.length, 2);
  assert.equal(h.smtp.mails.length, 0, "confident cited answers send no mail");
});

test("weak documentation match: no model answer, honest reply and a mail with the passages found", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  h.luxapi.keywords = () => "goulash recipe dumplings";
  const thread = h.discord.forumPost(h.support.id, user("cook"), "Recipe", "Hello, can somebody share a good goulash recipe?");
  await waitFor(() => h.smtp.mails.length === 1, 3000, "mail");
  assert.equal(h.luxapi.requests.length, 0, "the model is not asked to answer");
  const posted = h.discord.posted(thread.id);
  assert.equal(posted.length, 1);
  assert.match(posted[0].content, NOT_FOUND);
  assert.ok(h.discord.channels.find((c) => c.id === thread.id).applied_tags.includes(h.tagNeeds.id));
  const mail = h.smtp.mails[0].data;
  assert.match(mail, /Reason:  no good match in the LuxOS documentation/);
  assert.match(mail, /goulash recipe/);
  assert.match(mail, /Documentation passages found:/);
});

test("answers without a doc link, unconfident or with a truncated META are discarded and escalated", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const cases = [
    ["no link", () => `Printers are added in Printers and Scanners.\n${meta({})}`, /cited no documentation link/],
    ["unconfident", () => `Maybe see https://luxos.lux-ai.cz/docs/luxos/printing-scanning.html\n${meta({ confident: false })}`, /not confident/],
    // ziva chyba: useknuty META na konci (max_tokens), dalsi pokus taky useknuty
    ["truncated", () => ({ content: 'Tiskárny: https://luxos.lux-ai.cz/docs/luxos/printing-scanning.html\nMETA {"confident": true, "handoff": false, "lang": "cs", "summ', finish: "length" }), /not confident/]
  ];
  for (const [name, reply, reason] of cases) {
    h.luxapi.reply = reply;
    const before = h.smtp.mails.length;
    const thread = h.discord.forumPost(h.support.id, user(), `Printer ${name}`, "my printer prints nothing");
    await waitFor(() => h.smtp.mails.length === before + 1, 3000, `mail ${name}`);
    const posted = h.discord.posted(thread.id);
    assert.equal(posted.length, 1, name);
    assert.match(posted[0].content, NOT_FOUND, name);
    assert.doesNotMatch(posted[0].content, /META|Printers are added|Maybe/, `${name}: model text not posted`);
    assert.match(h.smtp.mails.at(-1).data, reason, name);
    assert.match(h.smtp.mails.at(-1).data, /printing-scanning\.html/, `${name}: passages in the mail`);
  }
  // useknuta odpoved: jeden opakovany pokus s vetsim rozpoctem
  const truncated = h.luxapi.requests.slice(-2);
  assert.deepEqual(truncated.map((r) => r.max_tokens), [4000, 8000]);
});

test("a truncated first attempt that succeeds on the retry is posted", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  let calls = 0;
  h.luxapi.reply = () => (++calls === 1
    ? { content: "Printers are", finish: "length" }
    : `Printers are added in Printers and Scanners: https://luxos.lux-ai.cz/docs/luxos/printing-scanning.html\n${meta({})}`);
  const thread = h.discord.forumPost(h.support.id, user(), "Printer", "how do I add a printer");
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  assert.match(h.discord.posted(thread.id)[0].content, /Printers and Scanners/);
  assert.equal(h.smtp.mails.length, 0);
});

test("#general: answers only when mentioned, as a reply; uncertainty is mailed with the message link", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const alice = user();
  h.discord.userMessage(h.general.id, alice, "how do I update the system?");
  await h.settle();
  assert.equal(h.discord.posted(h.general.id).length, 0);
  assert.equal(h.luxapi.keywordRequests.length, 0);

  h.luxapi.reply = () => `Run \`lux update\` (${CARE}).\n${meta({})}`;
  const question = h.discord.userMessage(h.general.id, alice, `<@${h.discord.bot.id}> how do I update the system?`, { mentions: [h.discord.bot] });
  const [reply] = await waitFor(() => h.discord.posted(h.general.id).length && h.discord.posted(h.general.id));
  assert.equal(reply.message_reference.message_id, question.id);
  assert.doesNotMatch(h.luxapi.requests[0].messages.at(-1).content, /<@/, "mention stripped");

  h.luxapi.reply = () => `No idea.\n${meta({ confident: false })}`;
  const q2 = h.discord.userMessage(h.general.id, alice, `<@${h.discord.bot.id}> printer update broke`, { mentions: [h.discord.bot] });
  await waitFor(() => h.smtp.mails.length === 1);
  assert.match(h.smtp.mails[0].data, new RegExp(`discord\\.com/channels/${h.discord.guild.id}/${h.general.id}/${q2.id}`));

  // zminka v jinem kanalu (#off-topic) se ignoruje
  h.discord.userMessage(h.offTopic.id, alice, `<@${h.discord.bot.id}> hi`, { mentions: [h.discord.bot] });
  await h.settle();
  assert.equal(h.discord.posted(h.offTopic.id).length, 0);
});

test("non-English question: English keywords, answer and texts in the user's language", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  h.luxapi.keywords = () => "install apps store";
  h.luxapi.reply = () => `Aplikace nainstalujete v Obchodě: ${APPS}\n${meta({ lang: "cs" })}`;
  const thread = h.discord.forumPost(h.support.id, user(), "Jak nainstalovat aplikace?", "Kde najdu nové programy?");
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  assert.match(h.luxapi.keywordRequests[0].messages[1].content, /Jak nainstalovat/);
  assert.match(h.luxapi.requests[0].messages[0].content, /docs\/luxos\/apps\.html/, "found via the keywords");
  assert.match(h.discord.posted(thread.id)[0].content, /Obchodě/);

  h.luxapi.keywords = () => "goulash";
  const other = h.discord.forumPost(h.support.id, user(), "Recept", "Máte recept na guláš?");
  await waitFor(() => h.discord.posted(other.id).length === 1);
  assert.match(h.discord.posted(other.id)[0].content, /V dokumentaci LuxOS jsem to nenašel/);
});

test("hand-off: tag 'Needs human', exactly one e-mail per thread, /human afterwards", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const alice = user("alice");
  h.luxapi.reply = () => `I can't tell.\n${meta({ confident: false, summary: "printer garbage" })}`;
  const thread = h.discord.forumPost(h.support.id, alice, "Printer prints garbage", "My printer prints random characters");
  await waitFor(() => h.smtp.mails.length === 1, 3000, "mail");
  const mail = h.smtp.mails[0];
  assert.match(mail.from, /accounts@lux-ai\.cz/);
  assert.match(mail.to.join(), /info@lux-ai\.cz/);
  assert.match(mail.data, /Subject: \[LuxOS Discord\] Needs human: Printer prints garbage/);
  assert.match(mail.data, new RegExp(`https://discord\\.com/channels/${h.discord.guild.id}/${thread.id}`));
  assert.match(mail.data, /Author:  alice \(@alice\)/);

  h.discord.userMessage(thread.id, alice, "any news about the printer?");
  await h.settle();
  assert.equal(h.luxapi.requests.length, 1, "thread is with a human now");

  h.discord.dispatch("INTERACTION_CREATE", {
    id: "1", token: "tok", type: 2, data: { name: "human" }, guild_id: h.discord.guild.id, channel_id: thread.id,
    member: { user: alice }, locale: "en-US"
  });
  await waitFor(() => h.discord.interactionReplies.length === 1);
  assert.match(h.discord.interactionReplies[0].data.content, /already knows/);
  await h.settle();
  assert.equal(h.smtp.mails.length, 1);
});

test("explicit request for a human: no model call, mail sent; mail rate limit holds", async (t) => {
  const h = await startBot({ mail: { perHour: 2 } });
  t.after(() => h.stop());
  const threads = [];
  for (let i = 0; i < 3; i++) {
    threads.push(h.discord.forumPost(h.support.id, user(), `Account problem ${i}`, "I want to talk to a human please"));
    await waitFor(() => h.discord.posted(threads[i].id).length === 1, 3000, `handoff ${i}`);
    await h.settle();
  }
  assert.equal(h.luxapi.requests.length + h.luxapi.keywordRequests.length, 0);
  assert.equal(h.smtp.mails.length, 2, "MAILS_PER_HOUR=2");
  for (const thread of threads) {
    assert.ok(h.discord.channels.find((c) => c.id === thread.id).applied_tags.includes(h.tagNeeds.id), "every thread tagged");
  }
  assert.ok(h.lines.some((l) => /mail skipped \(rate limit\)/.test(l)));
});

test("/human outside a support thread answers privately", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  h.discord.dispatch("INTERACTION_CREATE", {
    id: "2", token: "tok", type: 2, data: { name: "human" }, guild_id: h.discord.guild.id, channel_id: h.general.id,
    member: { user: user() }, locale: "cs"
  });
  await waitFor(() => h.discord.interactionReplies.length === 1);
  const reply = h.discord.interactionReplies[0];
  assert.equal(reply.data.flags & 64, 64, "ephemeral");
  assert.match(reply.data.content, new RegExp(`<#${h.support.id}>`));
  assert.match(reply.data.content, /založte příspěvek/);
  assert.equal(h.smtp.mails.length, 0);
});

test("#bot-testing: every message gets a thread and an answer, any team member, mails marked [test]", async (t) => {
  const h = await startBot({ limits: { userPer10Min: 1 } });
  t.after(() => h.stop());
  const tester = user("tester");
  for (const text of ["How do I add a printer?", "printer again", "printer third"]) h.discord.userMessage(h.testing.id, tester, text);
  await waitFor(() => h.discord.channels.filter((c) => c.parent_id === h.testing.id).length === 3, 3000, "threads");
  const threads = h.discord.channels.filter((c) => c.parent_id === h.testing.id);
  await waitFor(() => threads.every((th) => h.discord.posted(th.id).length === 1), 3000, "answers");
  assert.equal(h.luxapi.requests.length, 3, "no per-user limit in #bot-testing");

  // jiny clen tymu ve vlakne: taky odpoved
  h.discord.userMessage(threads[0].id, user("colleague"), "and a network printer?");
  await waitFor(() => h.discord.posted(threads[0].id).length === 2);

  h.luxapi.reply = () => `Hmm.\n${meta({ confident: false })}`;
  h.discord.userMessage(h.testing.id, tester, "printer makes smoke");
  await waitFor(() => h.smtp.mails.length === 1);
  assert.match(h.smtp.mails[0].data, /Subject: \[LuxOS Discord\] \[test\] Needs human: printer makes smoke/);
  assert.match(h.smtp.mails[0].data, /TEST from #bot-testing/);
});

test("role buttons: Tester/Member toggle, ephemeral confirmation, Team can never be self-assigned", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  h.discord.roles.push({ id: "900000000000000001", name: "Tester" }, { id: "900000000000000002", name: "Member" }, { id: "900000000000000003", name: "Team" });
  for (const role of h.discord.roles.slice(-3)) h.discord.dispatch("GUILD_ROLE_CREATE", { guild_id: h.discord.guild.id, role });
  await waitFor(() => h.bot.roles.has("Team"));
  const member = { user: user(), roles: [] };
  const click = (id, customId, roles) => h.discord.dispatch("INTERACTION_CREATE", {
    id, token: "tok", type: 3, data: { custom_id: customId, component_type: 2 }, guild_id: h.discord.guild.id,
    channel_id: h.general.id, member: { ...member, roles }, locale: "en-US"
  });
  click("10", "role:Tester", []);
  await waitFor(() => h.discord.interactionReplies.length === 1);
  assert.ok(h.discord.memberRoles.get(member.user.id).has("900000000000000001"));
  assert.match(h.discord.interactionReplies[0].data.content, /You now have the Tester role/);
  assert.equal(h.discord.interactionReplies[0].data.flags & 64, 64);

  click("11", "role:Tester", ["900000000000000001"]);
  await waitFor(() => h.discord.interactionReplies.length === 2);
  assert.equal(h.discord.memberRoles.get(member.user.id).has("900000000000000001"), false);

  click("12", "role:Team", []);
  await waitFor(() => h.discord.interactionReplies.length === 3);
  assert.equal(h.discord.memberRoles.get(member.user.id).has("900000000000000003"), false);
  assert.match(h.discord.interactionReplies[2].data.content, /couldn't change your role/);
});

test("per-user rate limit: notice once, no model calls over the limit", async (t) => {
  const h = await startBot({ limits: { userPer10Min: 2 } });
  t.after(() => h.stop());
  const carol = user();
  const threads = [];
  for (let i = 0; i < 4; i++) {
    threads.push(h.discord.forumPost(h.support.id, carol, `Question ${i}`, `printer question number ${i}`));
    await h.settle();
  }
  assert.equal(h.luxapi.requests.length, 2);
  assert.match(h.discord.posted(threads[2].id)[0].content, /try again in about 10 min/);
  assert.equal(h.discord.posted(threads[3].id).length, 0, "the notice is not repeated");
  const other = h.discord.forumPost(h.support.id, user(), "Other", "printer question");
  await waitFor(() => h.discord.posted(other.id).length === 1);
  assert.equal(h.luxapi.requests.length, 3);
});

test("daily global answer cap and per-thread reply cap", async (t) => {
  const h = await startBot({ limits: { dailyCap: 1 } });
  t.after(() => h.stop());
  const first = h.discord.forumPost(h.support.id, user(), "One", "printer question");
  await waitFor(() => h.discord.posted(first.id).length === 1);
  const second = h.discord.forumPost(h.support.id, user(), "Two", "printer question");
  await waitFor(() => h.discord.posted(second.id).length === 1);
  assert.match(h.discord.posted(second.id)[0].content, /answered all the questions I can for today/);
  assert.equal(h.luxapi.requests.length, 1);
  assert.equal(h.state.data.answersToday, 1);

  const h2 = await startBot({ limits: { threadReplies: 2 } });
  t.after(() => h2.stop());
  const op = user();
  const thread = h2.discord.forumPost(h2.support.id, op, "Printer", "printer question");
  await waitFor(() => h2.discord.posted(thread.id).length === 1);
  h2.discord.userMessage(thread.id, op, "more about printers");
  await waitFor(() => h2.discord.posted(thread.id).length === 2);
  h2.discord.userMessage(thread.id, op, "and more printers");
  await waitFor(() => h2.smtp.mails.length === 1, 3000, "cap escalation mail");
  assert.match(h2.discord.posted(thread.id)[2].content, /getting long/);
  assert.equal(h2.luxapi.requests.length, 2);
});

test("ignores bots, webhooks, @everyone; secrets never reach the model", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const otherBot = { id: "999", username: "otherbot", bot: true };
  const thread1 = h.discord.forumPost(h.support.id, otherBot, "Bot post", "printer question");
  const thread2 = h.discord.addChannel({ name: "everyone", type: 11, parent_id: h.support.id, owner_id: "5" });
  h.discord.dispatch("THREAD_CREATE", thread2);
  h.discord.userMessage(thread2.id, user(), "@everyone printer question", { id: thread2.id, mention_everyone: true });
  await h.settle();
  assert.equal(h.discord.posted(thread1.id).length, 0);
  assert.equal(h.discord.posted(thread2.id).length, 0);

  const thread3 = h.discord.forumPost(h.support.id, user(), "Key", `my key is lux-${"a".repeat(40)} why fails`);
  await waitFor(() => h.discord.posted(thread3.id).length === 1);
  assert.match(h.discord.posted(thread3.id)[0].content, /password, key or token/);
  assert.equal(h.luxapi.requests.length + h.luxapi.keywordRequests.length, 0);
  assert.ok(h.lines.every((l) => !l.includes("aaaa")), "no message content in the log");
});

test("DMs: only members of the server get answers; uncertainty points to #support", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const stranger = user();
  const member = user();
  h.discord.members.add(member.id);
  h.discord.userMessage("700000000000000001", stranger, "how do I update?");
  h.discord.userMessage("700000000000000001", stranger, "hello??");
  await h.settle();
  const toStranger = h.discord.posted("700000000000000001");
  assert.equal(toStranger.length, 1);
  assert.match(toStranger[0].content, /only answer members/);

  h.luxapi.reply = () => `Run lux update: ${CARE}\n${meta({})}`;
  h.discord.userMessage("700000000000000002", member, "how do I update?");
  await waitFor(() => h.discord.posted("700000000000000002").length === 1);
  assert.equal(h.luxapi.requests.length, 1);

  h.luxapi.keywords = () => "goulash";
  h.discord.userMessage("700000000000000002", member, "goulash recipe?");
  await waitFor(() => h.discord.posted("700000000000000002").length === 2);
  assert.match(h.discord.posted("700000000000000002")[1].content, new RegExp(`open a post in <#${h.support.id}>`));
  assert.equal(h.smtp.mails.length, 0, "the team cannot answer in a DM");
});

test("#support as a text channel (no Community): question becomes a thread", async (t) => {
  const h = await startBot({ community: false });
  t.after(() => h.stop());
  const alice = user();
  h.luxapi.reply = () => `Use the Store: ${APPS}\n${meta({})}`;
  h.discord.userMessage(h.support.id, alice, "How do I install apps from the store?");
  const thread = await waitFor(() => h.discord.channels.find((c) => c.type === 11 && c.parent_id === h.support.id));
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  assert.equal(thread.name, "How do I install apps from the store?");
  h.discord.dispatch("THREAD_CREATE", thread);
  h.luxapi.reply = () => `I can't tell.\n${meta({ handoff: true, confident: false })}`;
  h.discord.userMessage(thread.id, alice, "it still fails with an error");
  await waitFor(() => h.smtp.mails.length === 1);
  assert.match(h.discord.channels.find((c) => c.id === thread.id).name, /^\[Needs human\] /);
});

test("gateway resumes after a dropped connection", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  assert.equal(h.discord.identifies, 1);
  assert.equal(h.discord.lastIdentify.intents, 1 | 512 | 4096 | 32768);
  for (const ws of h.discord.sockets) ws.close(4000);
  await waitFor(() => h.discord.resumes === 1, 5000, "resume");
  assert.equal(h.discord.identifies, 1);
  const thread = h.discord.forumPost(h.support.id, user(), "After resume", "printer question");
  await waitFor(() => h.discord.posted(thread.id).length === 1);
});
