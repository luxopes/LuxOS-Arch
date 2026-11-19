"use strict";
// Pozdravy, diky, smalltalk a temata mimo LuxOS: kratka odpoved, nikdy e-mail, stitek ani prejmenovani.
// Ziva chyba: "Hey Lux" v #bot-testing skoncilo jako "[Needs human] Hey Lux" + e-mail.

const test = require("node:test");
const assert = require("node:assert/strict");
const { startBot, user, meta, waitFor } = require("./harness");
const { shortCategory } = require("../src/texts");
const { parseClassification } = require("../src/assistant");

function noEscalation(h, threadId) {
  assert.equal(h.smtp.mails.length, 0, "no mail");
  if (threadId) {
    const thread = h.discord.channels.find((c) => c.id === threadId);
    assert.doesNotMatch(thread.name, /Needs human/, "not renamed");
    assert.ok(!(thread.applied_tags || []).includes(h.tagNeeds.id), "not tagged");
  }
}

test("'Hey Lux' in #bot-testing: friendly intro, no model call, no mail, no rename", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  h.discord.userMessage(h.testing.id, user("owner"), "Hey Lux");
  const thread = await waitFor(() => h.discord.channels.find((c) => c.parent_id === h.testing.id));
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  assert.match(h.discord.posted(thread.id)[0].content, /^Hi! I'm the LuxOS assistant\. Ask me anything about LuxOS/);
  await h.settle();
  assert.equal(h.luxapi.keywordRequests.length + h.luxapi.requests.length, 0);
  noEscalation(h, thread.id);
});

test("'ahoj' as a forum post gets a Czech greeting; the next real question in the post is handled and may escalate", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const alice = user();
  const thread = h.discord.forumPost(h.support.id, alice, "ahoj", "ahoj");
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  assert.match(h.discord.posted(thread.id)[0].content, /^Ahoj! Jsem asistent LuxOS/);
  noEscalation(h, thread.id);

  // skutecna otazka, na kterou dokumentace nestaci -> predani tymu je ted spravne
  h.luxapi.keywords = () => "QUESTION | fingerprint reader elan driver";
  h.discord.userMessage(thread.id, alice, "Funguje ve LuxOS čtečka otisků prstů Elan 04f3?");
  await waitFor(() => h.smtp.mails.length === 1, 3000, "escalation mail");
  assert.match(h.discord.posted(thread.id)[1].content, /V dokumentaci LuxOS jsem to nenašel/);
  assert.ok(h.discord.channels.find((c) => c.id === thread.id).applied_tags.includes(h.tagNeeds.id));
  assert.equal(h.luxapi.requests.length, 0, "weak match: no model answer");
});

test("'thanks!' and 'díky' get a short 'you're welcome' and nothing else", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const op = user();
  h.luxapi.reply = () => `Printers are added in Printers and Scanners: https://luxos.lux-ai.cz/docs/luxos/printing-scanning.html\n${meta({})}`;
  const thread = h.discord.forumPost(h.support.id, op, "Printer", "how do I add a printer?");
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  h.discord.userMessage(thread.id, op, "thanks!");
  await waitFor(() => h.discord.posted(thread.id).length === 2);
  assert.match(h.discord.posted(thread.id)[1].content, /^You're welcome!/);
  h.discord.userMessage(thread.id, op, "díky");
  await waitFor(() => h.discord.posted(thread.id).length === 3);
  assert.match(h.discord.posted(thread.id)[2].content, /^Rádo se stalo!/);
  await h.settle();
  assert.equal(h.luxapi.requests.length, 1, "no extra answers");
  assert.equal(h.luxapi.keywordRequests.length, 1, "thanks recognised without the model");
  noEscalation(h, thread.id);
});

test("'bitcoin price?' is off-topic: polite 'only LuxOS', no mail", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  h.luxapi.keywords = () => "OFFTOPIC |";
  const thread = h.discord.forumPost(h.support.id, user(), "bitcoin price?", "bitcoin price?");
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  assert.match(h.discord.posted(thread.id)[0].content, /I can only help with LuxOS and LuxAI/);
  await h.settle();
  assert.equal(h.luxapi.requests.length, 0);
  noEscalation(h, thread.id);

  // v #general po zmince taky, jako odpoved na zpravu
  const q = h.discord.userMessage(h.general.id, user(), `<@${h.discord.bot.id}> whats the best pizza in Prague`, { mentions: [h.discord.bot] });
  await waitFor(() => h.discord.posted(h.general.id).length === 1);
  assert.equal(h.discord.posted(h.general.id)[0].message_reference.message_id, q.id);
  noEscalation(h);
});

test("longer greetings and small talk classified by the model never escalate", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const cases = [
    ["Hello everyone, I'm new here and installed LuxOS yesterday :)", "GREETING |", /Hi! I'm the LuxOS assistant/],
    ["Are you a real AI or a person typing?", "SMALLTALK |", /Hi! I'm the LuxOS assistant/],
    ["Already solved it myself, it was the cable, thank you anyway", "THANKS |", /You're welcome/]
  ];
  for (const [text, category, expected] of cases) {
    h.luxapi.keywords = () => category;
    const thread = h.discord.forumPost(h.support.id, user(), text.slice(0, 40), text);
    await waitFor(() => h.discord.posted(thread.id).length === 1, 3000, category);
    assert.match(h.discord.posted(thread.id)[0].content, expected);
    noEscalation(h, thread.id);
  }
  assert.match(h.luxapi.keywordRequests[0].messages[1].content, /^Thread title: .*\nMessage: Hello everyone/);
});

test("short-message check and classification parsing", () => {
  for (const [text, category] of [["Hey Lux", "GREETING"], ["ahoj", "GREETING"], ["Dobrý den!", "GREETING"], ["hi there 👋", "GREETING"],
    [`<@${"1".repeat(18)}> hello`, "GREETING"], ["thanks!", "THANKS"], ["díky", "THANKS"], ["Thank you so much", "THANKS"],
    ["díky moc, už to funguje", "THANKS"], ["are you there?", "SMALLTALK"], ["jsi tu?", "SMALLTALK"]]) {
    assert.equal(shortCategory(text), category, text);
  }
  for (const text of ["bitcoin price?", "hey, my wifi does not work", "thanks, but how do I print?", "hi, how do I install Steam", "test the printer"]) {
    assert.equal(shortCategory(text), "", text);
  }
  assert.deepEqual(parseClassification("QUESTION | printer not printing"), { category: "QUESTION", keywords: "printer not printing" });
  assert.deepEqual(parseClassification("OFFTOPIC |"), { category: "OFFTOPIC", keywords: "" });
  assert.deepEqual(parseClassification("greeting"), { category: "GREETING", keywords: "" });
  assert.deepEqual(parseClassification("printer wifi"), { category: "QUESTION", keywords: "printer wifi" }, "no category = question");
  assert.deepEqual(parseClassification("NONE"), { category: "SMALLTALK", keywords: "" });
});
