"use strict";
// Ziva chyba: po "Needs human" bot mlcel, a samotna zminka "@LuxOS Support" nic neudelala.

const test = require("node:test");
const assert = require("node:assert/strict");
const { startBot, user, meta, waitFor } = require("./harness");

const PRINTING = "https://luxos.lux-ai.cz/docs/luxos/printing-scanning.html";
const CARE = "https://luxos.lux-ai.cz/docs/luxos/care-updates.html";

test("a plain question in a 'Needs human' thread is answered normally, without a second mail", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const owner = user("owner");
  h.luxapi.keywords = () => "QUESTION | fingerprint reader elan";
  const thread = h.discord.forumPost(h.support.id, owner, "Fingerprint", "Does the Elan fingerprint reader work?");
  await waitFor(() => h.smtp.mails.length === 1);
  assert.ok(h.discord.channels.find((c) => c.id === thread.id).applied_tags.includes(h.tagNeeds.id));

  h.luxapi.keywords = () => "QUESTION | update system software";
  h.luxapi.reply = () => `Run \`lux config channel staging\`: ${CARE}\n${meta({})}`;
  h.discord.userMessage(thread.id, owner, "I need to know how to set updates to staging");
  await waitFor(() => h.discord.posted(thread.id).length === 2, 3000, "answer after hand-off");
  assert.match(h.discord.posted(thread.id)[1].content, /lux config channel staging/);
  await h.settle();
  assert.equal(h.smtp.mails.length, 1);
});

test("the same in #bot-testing", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const owner = user("owner");
  h.luxapi.keywords = () => "QUESTION | fingerprint reader elan";
  h.discord.userMessage(h.testing.id, owner, "Does the Elan fingerprint reader work?");
  const thread = await waitFor(() => h.discord.channels.find((c) => c.parent_id === h.testing.id));
  await waitFor(() => h.smtp.mails.length === 1);
  h.luxapi.keywords = () => "QUESTION | update system software";
  h.luxapi.reply = () => `Run \`lux config channel staging\`: ${CARE}\n${meta({})}`;
  h.discord.userMessage(thread.id, owner, "I need to know how to set updates to staging");
  await waitFor(() => h.discord.posted(thread.id).length === 2);
  assert.match(h.discord.posted(thread.id)[1].content, /staging/);
});

test("mention only after an unanswered question answers that question (#general)", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const owner = user("owner");
  h.luxapi.reply = () => `Run \`lux update\`: ${CARE}\n${meta({})}`;
  const question = h.discord.userMessage(h.general.id, owner, "how do I update the system?");
  await h.settle();
  assert.equal(h.discord.posted(h.general.id).length, 0, "not mentioned: no answer");
  h.discord.userMessage(h.general.id, owner, `<@${h.discord.bot.id}>`, { mentions: [h.discord.bot] });
  const [reply] = await waitFor(() => h.discord.posted(h.general.id).length && h.discord.posted(h.general.id));
  assert.match(reply.content, /lux update/);
  assert.equal(reply.message_reference.message_id, question.id, "replies to the question it answers");
  assert.match(h.luxapi.requests[0].messages.at(-1).content, /how do I update the system\?/);
});

test("mention only with nothing to answer asks what the user wants to know", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const owner = user();
  h.discord.userMessage(h.general.id, owner, `<@${h.discord.bot.id}> ?`, { mentions: [h.discord.bot] });
  await waitFor(() => h.discord.posted(h.general.id).length === 1);
  assert.match(h.discord.posted(h.general.id)[0].content, /What would you like to know\?/);
  // stara otazka, na kterou uz bot odpovedel, se znovu nezodpovida
  h.discord.userMessage(h.general.id, owner, `<@${h.discord.bot.id}> pls`, { mentions: [h.discord.bot] });
  await waitFor(() => h.discord.posted(h.general.id).length === 2);
  assert.match(h.discord.posted(h.general.id)[1].content, /What would you like to know\?/);
  assert.equal(h.luxapi.requests.length + h.luxapi.keywordRequests.length, 0);
  assert.equal(h.smtp.mails.length, 0);
});

test("after a helper replied in a #support thread the bot stays quiet, but answers when mentioned", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const op = user("op");
  const thread = h.discord.forumPost(h.support.id, op, "Printer", "how do I add a printer?");
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  h.discord.userMessage(thread.id, user("helper"), "Try turning the printer off and on first.");
  await h.settle();
  h.discord.userMessage(thread.id, op, "the printer still is not found on the network");
  await h.settle();
  assert.equal(h.discord.posted(thread.id).length, 1, "quiet while a human helps");

  h.luxapi.reply = () => `Network printers are added after you click them: ${PRINTING}\n${meta({})}`;
  h.discord.userMessage(thread.id, op, `<@${h.discord.bot.id}>`, { mentions: [h.discord.bot] });
  await waitFor(() => h.discord.posted(thread.id).length === 2, 3000, "answer on mention");
  assert.match(h.luxapi.requests.at(-1).messages.at(-1).content, /still is not found on the network/);
});
