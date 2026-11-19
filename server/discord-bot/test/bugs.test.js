"use strict";
// #bug-reports: srozumitelne hlaseni hned e-mailem, nejasne jedna otazka ve vlakne, tajne udaje pryc.

const test = require("node:test");
const assert = require("node:assert/strict");
const { startBot, user, waitFor } = require("./harness");

const verdict = (fields) => JSON.stringify({ clear: true, summary: "Calculator crashes on division", version: "", lang: "en", question: "", ...fields });

test("clear report: forwarded once with ✅, no question, no doc answer", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const reporter = user("reporter");
  h.luxapi.bugVerdict = () => verdict({ version: "1.0.3" });
  const msg = h.discord.userMessage(h.bugs.id, reporter, "LuxOS 1.0.3: Calculator closes when I divide by zero, expected an error message. Steps: open Calculator, 1/0, Enter.", {
    attachments: [{ id: "1", url: "https://cdn.discordapp.com/attachments/1/2/crash.png", filename: "crash.png" }]
  });
  await waitFor(() => h.smtp.mails.length === 1, 3000, "mail");
  await waitFor(() => h.discord.reactions.length === 1);
  assert.deepEqual(h.discord.reactions[0], { channel: h.bugs.id, message: msg.id, emoji: "✅" });
  const mail = h.smtp.mails[0].data;
  assert.match(mail, /Subject: \[LuxOS bug\] Calculator crashes on division/);
  assert.match(mail, /Author:  reporter \(@reporter\)/);
  assert.match(mail, /LuxOS:   1\.0\.3/);
  assert.match(mail, /divide by zero/);
  assert.match(mail, /crash\.png/);
  assert.match(mail, new RegExp(`discord\\.com/channels/${h.discord.guild.id}/${h.bugs.id}/${msg.id}`));
  assert.equal(h.luxapi.bugRequests.length, 1);
  assert.equal(h.luxapi.bugRequests[0].reasoning_effort, "low");
  await h.settle();
  assert.equal(h.discord.posted(h.bugs.id).length, 0, "no question, no doc answer");
  assert.equal(h.discord.channels.filter((c) => c.parent_id === h.bugs.id).length, 0, "no thread");
  assert.equal(h.luxapi.requests.length + h.luxapi.keywordRequests.length, 0, "no support answer in #bug-reports");
  // stejna zprava znovu (napr. po obnoveni gateway) se nepreposila
  h.discord.dispatch("MESSAGE_CREATE", { ...msg, guild_id: h.discord.guild.id });
  await h.settle();
  assert.equal(h.smtp.mails.length, 1);
});

test("unclear report: one question in a thread, forwarded after the author's answer", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const reporter = user("reporter");
  h.luxapi.bugVerdict = () => verdict({ clear: false, summary: "Something is broken", question: "Which app was it, and what happened exactly? Please add your LuxOS version (About This Computer)." });
  const msg = h.discord.userMessage(h.bugs.id, reporter, "it doesn't work");
  const thread = await waitFor(() => h.discord.channels.find((c) => c.parent_id === h.bugs.id && c.type === 11), 3000, "thread");
  assert.equal(thread.id, msg.id, "thread on the report message");
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  assert.match(h.discord.posted(thread.id)[0].content, /Which app was it/);
  assert.equal(h.smtp.mails.length, 0);

  // ostatni ve vlakne se nepocitaji
  h.discord.userMessage(thread.id, user("other"), "same here");
  await h.settle();
  assert.equal(h.luxapi.bugRequests.length, 1);

  h.luxapi.bugVerdict = () => verdict({ summary: "Weather app shows no data", version: "1.0.3" });
  h.discord.userMessage(thread.id, reporter, "The Weather app shows no data since the update, LuxOS 1.0.3");
  await waitFor(() => h.smtp.mails.length === 1, 3000, "mail after answer");
  await waitFor(() => h.discord.posted(thread.id).length === 2);
  assert.match(h.discord.posted(thread.id)[1].content, /forwarded to the LuxOS team/);
  const mail = h.smtp.mails[0].data;
  assert.match(mail, /Subject: \[LuxOS bug\] Weather app shows no data/);
  assert.match(mail, /it doesn't work/);
  assert.match(mail, /\[Answer 1 from the author\]\nThe Weather app shows no data/);

  h.discord.userMessage(thread.id, reporter, "also the icon is wrong");
  await h.settle();
  assert.equal(h.smtp.mails.length, 1, "one mail per report");
});

test("still unclear after two answers: forwarded anyway", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  const reporter = user();
  h.luxapi.bugVerdict = () => verdict({ clear: false, question: "What happened exactly?" });
  h.discord.userMessage(h.bugs.id, reporter, "bug");
  const thread = await waitFor(() => h.discord.channels.find((c) => c.parent_id === h.bugs.id && c.type === 11));
  await waitFor(() => h.discord.posted(thread.id).length === 1);
  h.discord.userMessage(thread.id, reporter, "it crashed");
  await waitFor(() => h.discord.posted(thread.id).length === 2);
  assert.equal(h.smtp.mails.length, 0);
  h.discord.userMessage(thread.id, reporter, "the whole thing");
  await waitFor(() => h.smtp.mails.length === 1);
});

test("secrets are redacted before mailing; own daily cap for bug mails", async (t) => {
  const h = await startBot({ mail: { bugsPerDay: 1 } });
  t.after(() => h.stop());
  const key = `lux-${"s".repeat(40)}`;
  h.discord.userMessage(h.bugs.id, user(), `Mail app login fails. password: hunter2secret and my key ${key}`);
  await waitFor(() => h.smtp.mails.length === 1);
  const mail = h.smtp.mails[0].data;
  assert.doesNotMatch(mail, /hunter2secret|ssssssss/);
  assert.match(mail, /\[redacted\]/);
  assert.doesNotMatch(JSON.stringify(h.luxapi.bugRequests), /hunter2secret|ssssssss/, "not sent to the model either");

  h.discord.userMessage(h.bugs.id, user(), "Calendar shows the wrong week number in the month view");
  await h.settle(300);
  assert.equal(h.smtp.mails.length, 1, "BUG_MAILS_PER_DAY=1");
  assert.ok(h.lines.some((l) => /bug report mail skipped \(rate limit\)/.test(l)));
});

test("model unavailable: the report is forwarded instead of nagging", async (t) => {
  const h = await startBot();
  t.after(() => h.stop());
  h.luxapi.bugVerdict = () => "not json at all";
  h.discord.userMessage(h.bugs.id, user(), "Files app freezes when opening a folder with 10000 photos");
  await waitFor(() => h.smtp.mails.length === 1);
  assert.equal(h.discord.channels.filter((c) => c.parent_id === h.bugs.id).length, 0);
});
