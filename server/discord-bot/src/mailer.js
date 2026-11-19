"use strict";
// E-mail tymu LuxOS pri predani vlakna cloveku: mistni SMTP (127.0.0.1:25) jako lux-account,
// nejvys jeden mail na vlakno (hlida bot) a nejvys MAILS_PER_HOUR / MAILS_PER_DAY celkem.

const nodemailer = require("nodemailer");

class Mailer {
  constructor({ host, port, tlsServername, from, to, perHour, perDay }, state) {
    Object.assign(this, { from, to, perHour, perDay, state });
    this.transport = nodemailer.createTransport({
      host, port, secure: false,
      tls: { servername: tlsServername, minVersion: "TLSv1.2" },
      connectionTimeout: 15_000, greetingTimeout: 15_000, socketTimeout: 30_000
    });
  }

  allowed() {
    const now = Date.now();
    const mails = this.state.data.mails.filter((t) => now - t < 24 * 3600 * 1000);
    return mails.length < this.perDay && mails.filter((t) => now - t < 3600 * 1000).length < this.perHour;
  }

  // summary = {title, link, author, reason, summary, question}
  async escalate(info) {
    if (!this.allowed()) return false;
    this.state.data.mails.push(Date.now());
    this.state.save();
    const text = [
      `A question on the LuxOS Discord needs a human.`,
      ``,
      `Thread:  ${info.title}`,
      `Link:    ${info.link}`,
      `Author:  ${info.author}`,
      `Reason:  ${info.reason}`,
      info.summary ? `Summary: ${info.summary}` : null,
      ``,
      `Question (shortened):`,
      info.question,
      ``,
      `-- LuxOS Discord bot (one mail per thread; reply in Discord, not to this e-mail)`
    ].filter((line) => line !== null).join("\n");
    await this.transport.sendMail({
      from: this.from,
      to: this.to,
      subject: `[LuxOS Discord] Needs human: ${info.title}`.slice(0, 150),
      text,
      dsn: { notify: "never" }
    });
    return true;
  }
}

module.exports = { Mailer };
