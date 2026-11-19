"use strict";
// Bot proti falesnemu Discordu (Gateway + REST), lux-api a SMTP.

const test = require("node:test");
const assert = require("node:assert/strict");
const { startBot, user, meta, waitFor } = require("./harness");

test("answers every new post in the #support forum, with docs in the prompt", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const alice = user("alice");
  h.luxapi.reply = () => `Open the **Store** and click Install.\nSee https://luxos.lux-ai.cz/docs/luxos/apps.html\n${meta({})}`;

  const thread = h.discord.forumPost(h.support.id, alice, "How do I install apps?", "Where do I get new apps?");
  const [reply] = await waitFor(() => h.discord.posted(thread.id).length && h.discord.posted(thread.id), 3000, "reply");
  assert.match(reply.content, /Store/);
  assert.doesNotMatch(reply.content, /META/);
  assert.equal(reply.flags, 4, "link embeds suppressed");
  assert.deepEqual(reply.allowed_mentions.parse, [], "never pings anyone");

  assert.equal(h.luxapi.requests.length, 1, "English question: no translation call");
  const request = h.luxapi.requests[0];
  assert.equal(request.model, "flash");
  assert.equal(request.reasoning_effort, "low");
  assert.match(request.messages[0].content, /LuxOS support assistant/);
  assert.match(request.messages[0].content, /docs\/luxos\/apps\.html/, "top passage in the prompt");
  assert.match(request.messages.at(-1).content, /How do I install apps\?\n\nWhere do I get new apps\?/);

  // druha otazka tazatele ve vlakne: odpoved s historii
  h.luxapi.reply = () => `Right-click it in Launchpad.\n${meta({})}`;
  h.discord.userMessage(thread.id, alice, "And how do I remove one?");
  await waitFor(() => h.discord.posted(thread.id).length === 2, 3000, "follow-up");
  const roles = h.luxapi.requests[1].messages.map((m) => m.role);
  assert.deepEqual(roles, ["system", "user", "assistant", "user"]);
  assert.doesNotMatch(h.luxapi.requests[1].messages[2].content, /-# /, "docs footer not repeated to the model");

  // cizi uzivatel ve vlakne bez zminky: bot mlci
  h.discord.userMessage(thread.id, user("bob"), "same problem here");
  await h.settle();
  assert.equal(h.discord.posted(thread.id).length, 2);
  assert.equal(h.luxapi.requests.length, 2);
});

test("adds doc links when the model cites none", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  h.luxapi.reply = () => `Use the Store.\n${meta({})}`;
  const thread = h.discord.forumPost(h.support.id, user(), "Install apps", "how to install apps from the store");
  const [reply] = await waitFor(() => h.discord.posted(thread.id).length && h.discord.posted(thread.id));
  assert.match(reply.content, /\n-# Docs: <https:\/\/luxos\.lux-ai\.cz\/docs\/luxos\/apps\.html>/);
});

test("#general: answers only when mentioned, as a reply", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const alice = user();
  h.discord.userMessage(h.general.id, alice, "how do I update the system?");
  await h.settle();
  assert.equal(h.discord.posted(h.general.id).length, 0);
  assert.equal(h.luxapi.requests.length, 0);

  h.luxapi.reply = () => `Run \`lux update\`.\n${meta({})}`;
  const question = h.discord.userMessage(h.general.id, alice, `<@${h.discord.bot.id}> how do I update the system?`, { mentions: [h.discord.bot] });
  const [reply] = await waitFor(() => h.discord.posted(h.general.id).length && h.discord.posted(h.general.id));
  assert.equal(reply.message_reference.message_id, question.id);
  assert.doesNotMatch(h.luxapi.requests[0].messages.at(-1).content, /<@/, "mention stripped");

  // zminka v jinem kanalu (#off-topic) se ignoruje
  h.discord.userMessage(h.offTopic.id, alice, `<@${h.discord.bot.id}> hi`, { mentions: [h.discord.bot] });
  await h.settle();
  assert.equal(h.discord.posted(h.offTopic.id).length, 0);
});

test("non-English question: English search terms first, canned texts in the user's language", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  h.luxapi.reply = (body) => body.messages[0].content.startsWith("Translate")
    ? "install apps store"
    : `Aplikace nainstalujete v Obchodě.\n${meta({ lang: "cs", confident: false })}`;
  const thread = h.discord.forumPost(h.support.id, user(), "Jak nainstalovat aplikace?", "Kde najdu nové programy?");
  await waitFor(() => h.discord.posted(thread.id).length >= 2, 3000, "answer + handoff");
  assert.equal(h.luxapi.requests.length, 2);
  assert.match(h.luxapi.requests[0].messages[1].content, /Jak nainstalovat/);
  assert.match(h.luxapi.requests[1].messages[0].content, /docs\/luxos\/apps\.html/, "found via the translated terms");
  const posted = h.discord.posted(thread.id).map((m) => m.content);
  assert.match(posted[0], /Obchodě/);
  assert.match(posted[0], /Dokumentace:/);
  assert.match(posted[1], /tým LuxOS/, "handoff text in Czech");
});

test("escalation: tag 'Needs human' and exactly one e-mail per thread", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const alice = user("alice");
  h.luxapi.reply = () => `I'm not sure the docs cover this GPU.\n${meta({ confident: false, summary: "GPU artefacts on boot" })}`;
  const thread = h.discord.forumPost(h.support.id, alice, "Weird GPU artefacts", "My screen flickers with an old GPU");
  await waitFor(() => h.smtp.mails.length === 1, 3000, "mail");
  const posted = h.discord.posted(thread.id).map((m) => m.content);
  assert.match(posted[0], /not sure/);
  assert.match(posted[1], /asked the LuxOS team/);
  const fakeThread = h.discord.channels.find((c) => c.id === thread.id);
  assert.ok(fakeThread.applied_tags.includes(h.tagNeeds.id), "tagged Needs human");

  const mail = h.smtp.mails[0];
  assert.match(mail.from, /accounts@lux-ai\.cz/);
  assert.match(mail.to.join(), /info@lux-ai\.cz/);
  assert.match(mail.data, /Subject: \[LuxOS Discord\] Needs human: Weird GPU artefacts/);
  assert.match(mail.data, new RegExp(`https://discord\\.com/channels/${h.discord.guild.id}/${thread.id}`));
  assert.match(mail.data, /GPU artefacts on boot/);

  // tazatel pise dal: vlakno uz resi clovek, bot nevola model
  h.discord.userMessage(thread.id, alice, "any news?");
  await h.settle();
  assert.equal(h.luxapi.requests.length, 1);

  // /human ve stejnem vlaknu: "uz vi", zadny dalsi mail
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
  assert.equal(h.luxapi.requests.length, 0);
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
  // jiny uzivatel limit nema
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
  const thread = h2.discord.forumPost(h2.support.id, op, "Long", "printer question");
  await waitFor(() => h2.discord.posted(thread.id).length === 1);
  h2.discord.userMessage(thread.id, op, "more about printers");
  await waitFor(() => h2.discord.posted(thread.id).length === 2);
  h2.discord.userMessage(thread.id, op, "and more");
  await waitFor(() => h2.smtp.mails.length === 1, 3000, "cap escalation mail");
  assert.match(h2.discord.posted(thread.id)[2].content, /getting long/);
  assert.equal(h2.luxapi.requests.length, 2);
});

test("ignores bots, webhooks, @everyone and messages with secrets never reach the model", async (t) => {
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
  assert.equal(h.luxapi.requests.length, 0);
  assert.ok(h.lines.every((l) => !l.includes("aaaa")), "no message content in the log");
});

test("DMs: only members of the server get answers", async (t) => {
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

  h.luxapi.reply = () => `Run lux update.\n${meta({})}`;
  h.discord.userMessage("700000000000000002", member, "how do I update?");
  await waitFor(() => h.discord.posted("700000000000000002").length === 1);
  assert.equal(h.luxapi.requests.length, 1);
});

test("#support as a text channel (no Community): question becomes a thread", async (t) => {
  const h = await startBot({ community: false });
  t.after(() => h.stop());
  const alice = user();
  h.discord.userMessage(h.support.id, alice, "How do I install apps from the store?");
  const thread = await waitFor(() => h.discord.channels.find((c) => c.type === 11 && c.parent_id === h.support.id));
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  assert.equal(thread.name, "How do I install apps from the store?");
  h.discord.dispatch("THREAD_CREATE", thread); // owner_id = bot, tazatel je ve stavu
  h.luxapi.reply = () => `I can't tell.\n${meta({ handoff: true })}`;
  h.discord.userMessage(thread.id, alice, "it still fails with an error");
  await waitFor(() => h.smtp.mails.length === 1);
  const renamed = h.discord.channels.find((c) => c.id === thread.id);
  assert.match(renamed.name, /^\[Needs human\] /);
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
