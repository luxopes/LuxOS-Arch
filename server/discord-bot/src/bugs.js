"use strict";
// #bug-reports: kazde nove hlaseni posoudi model (kratce, nizke usili). Srozumitelne hlaseni hned
// preposle e-mailem tymu a oznaci ✅. Jen nejasne hlaseni dostane jednu otazku ve vlakne na chybejici
// udaje; po odpovedi autora se posoudi znovu a preposle, nejpozdeji po druhe odpovedi.
// Jeden e-mail na hlaseni, tajne udaje se pred odeslanim odstrani. Odpovedi z dokumentace tu nejsou.

const { redact } = require("./secrets");

const MAX_REPORT_CHARS = 4000;
const MAX_ROUNDS = 2;
const CHECK = "%E2%9C%85"; // ✅ v URL

const THANKS = {
  en: "Thanks, forwarded to the LuxOS team.",
  cs: "Díky, předáno týmu LuxOS."
};

function attachmentsOf(msg) {
  return (msg.attachments || []).map((a) => a.url).filter((u) => typeof u === "string" && /^https:\/\//.test(u)).slice(0, 10);
}

class BugReports {
  constructor({ bot, rest, assistant, mailer, state, log }) {
    Object.assign(this, { bot, rest, assistant, mailer, state, log });
    if (!this.state.data.bugs) this.state.data.bugs = {};
  }

  report(id) { return this.state.data.bugs[id]; }

  setReport(id, values) {
    this.state.data.bugs[id] = { ...(this.state.data.bugs[id] || {}), ...values, at: Date.now() };
    // stare zaznamy (30 dni) pryc
    for (const [key, r] of Object.entries(this.state.data.bugs)) {
      if (Date.now() - r.at > 30 * 86400_000) delete this.state.data.bugs[key];
    }
    this.state.save();
    return this.state.data.bugs[id];
  }

  // top = zprava primo v #bug-reports; jinak zprava ve vlakne pod nim
  async onMessage(msg, channel, top) {
    if (top) {
      await this.newReport(msg, channel);
      return;
    }
    const report = this.report(channel.id); // vlakno ma stejne id jako zprava s hlasenim
    if (!report || report.forwarded || msg.author.id !== report.author) return;
    const answers = [...(report.answers || []), redact(msg.content).slice(0, MAX_REPORT_CHARS)];
    const attachments = [...(report.attachments || []), ...attachmentsOf(msg)];
    this.setReport(channel.id, { answers, attachments });
    const text = this.fullText(report.text, answers);
    const verdict = await this.evaluate(text);
    if (verdict.clear || answers.length >= MAX_ROUNDS) {
      await this.forward(channel.id, report.channelId, msg.author, text, attachments, verdict, report.lang);
      await this.bot.send(channel.id, THANKS[report.lang] || THANKS.en);
      return;
    }
    await this.bot.send(channel.id, verdict.question);
  }

  async newReport(msg, channel) {
    if (this.report(msg.id)) return;
    const text = redact(msg.content || "").slice(0, MAX_REPORT_CHARS);
    const attachments = attachmentsOf(msg);
    const verdict = await this.evaluate(text + (attachments.length ? `\n[${attachments.length} attachment(s)]` : ""));
    const lang = verdict.lang === "cs" ? "cs" : "en";
    this.setReport(msg.id, { author: msg.author.id, channelId: channel.id, text, attachments, answers: [], lang });
    if (verdict.clear) {
      await this.forward(msg.id, channel.id, msg.author, text, attachments, verdict, lang);
      try {
        await this.rest.put(`/channels/${channel.id}/messages/${msg.id}/reactions/${CHECK}/@me`);
      } catch {
        await this.bot.send(channel.id, THANKS[lang], msg.id);
      }
      return;
    }
    // nejasne: jedna otazka ve vlakne na hlaseni
    const name = `Bug: ${verdict.summary || text.replace(/\s+/g, " ")}`.slice(0, 90);
    const thread = await this.rest.post(`/channels/${channel.id}/messages/${msg.id}/threads`, { name, auto_archive_duration: 4320 });
    this.bot.cacheChannel({ ...thread, owner_id: msg.author.id });
    await this.bot.send(thread.id, verdict.question);
    this.log(`bug report needs details report=${msg.id}`);
  }

  fullText(text, answers) {
    return [text, ...answers.map((a, i) => `[Answer ${i + 1} from the author]\n${a}`)].join("\n\n");
  }

  async evaluate(text) {
    try {
      return await this.assistant.evaluateBug(text);
    } catch (error) {
      // model nedostupny: radeji preposlat nez otravovat dotazy
      this.log(`bug evaluation failed: ${error.message}`);
      return { clear: true, summary: "", version: "", question: "", lang: "" };
    }
  }

  async forward(reportId, channelId, author, text, attachments, verdict, lang) {
    if (this.report(reportId).forwarded) return;
    this.setReport(reportId, { forwarded: true });
    const link = `https://discord.com/channels/${this.bot.guildId}/${channelId}/${reportId}`;
    try {
      const sent = await this.mailer.sendBug({
        summary: verdict.summary || text.replace(/\s+/g, " ").slice(0, 80),
        author: author.global_name ? `${author.global_name} (@${author.username})` : `@${author.username}`,
        text: redact(text),
        attachments,
        link,
        version: verdict.version || ""
      });
      this.log(sent ? `bug report forwarded report=${reportId}` : `bug report mail skipped (rate limit) report=${reportId}`);
    } catch (error) {
      this.log(`bug report mail failed report=${reportId}: ${error.message}`);
    }
  }
}

module.exports = { BugReports };
