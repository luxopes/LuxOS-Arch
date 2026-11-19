"use strict";
// Nastaveni bota z promennych prostredi. Tajne udaje (token Discordu, klic LuxAI) jen ze souboru,
// nikdy z promennych ani argumentu; pod systemd z LoadCredential ($CREDENTIALS_DIRECTORY).

const fs = require("fs");
const path = require("path");

function secretPath(envName, credentialName, fallback) {
  if (process.env[envName]) return process.env[envName];
  if (process.env.CREDENTIALS_DIRECTORY) return path.join(process.env.CREDENTIALS_DIRECTORY, credentialName);
  return fallback;
}

function readSecret(file, what) {
  let value;
  try {
    value = fs.readFileSync(file, "utf8").trim();
  } catch (error) {
    throw new Error(`cannot read ${what} from ${file}: ${error.code || error.message}`);
  }
  if (!value || /\s/.test(value)) throw new Error(`${what} in ${file} is empty or malformed`);
  return value;
}

function int(name, fallback, min = 0, max = 1e9) {
  const raw = process.env[name];
  const value = raw === undefined || raw === "" ? fallback : Number(raw);
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${name} must be an integer ${min}..${max}`);
  return value;
}

function str(name, fallback) {
  const value = process.env[name];
  return value === undefined || value === "" ? fallback : value;
}

function load() {
  return {
    tokenFile: secretPath("DISCORD_TOKEN_FILE", "discord-token", "/etc/luxos-discord/token"),
    luxaiKeyFile: secretPath("LUXAI_KEY_FILE", "luxai-key", "/etc/luxos-discord/luxai-key"),
    discordApi: str("DISCORD_API", "https://discord.com/api/v10").replace(/\/$/, ""),
    guildId: str("DISCORD_GUILD_ID", ""),
    channels: {
      support: str("SUPPORT_CHANNEL", "support"),
      general: str("GENERAL_CHANNEL", "general"),
      announcements: str("ANNOUNCEMENTS_CHANNEL", "announcements"),
      botTesting: str("BOT_TESTING_CHANNEL", "bot-testing"),
      bugs: str("BUG_REPORTS_CHANNEL", "bug-reports")
    },
    luxai: {
      url: str("LUXAI_URL", "http://127.0.0.1:3002/v1/chat/completions"),
      model: str("LUXAI_MODEL", "flash"),
      effort: str("LUXAI_EFFORT", "low"),
      // Flash premysli i pri nizkem usili a premysleni se pocita do max_tokens
      maxTokens: int("LUXAI_MAX_TOKENS", 4000, 500, 16000),
      timeoutMs: int("LUXAI_TIMEOUT_MS", 90_000, 100, 600_000)
    },
    mail: {
      host: str("SMTP_HOST", "127.0.0.1"),
      port: int("SMTP_PORT", 25, 1, 65535),
      tlsServername: str("SMTP_TLS_SERVERNAME", "mail.lux-ai.cz"),
      from: str("MAIL_FROM", "LuxOS Discord <accounts@lux-ai.cz>"),
      to: str("MAIL_TO", "info@lux-ai.cz"),
      perHour: int("MAILS_PER_HOUR", 6, 0, 1000),
      perDay: int("MAILS_PER_DAY", 30, 0, 10000),
      bugsPerDay: int("BUG_MAILS_PER_DAY", 20, 0, 10000)
    },
    stateDir: str("STATE_DIRECTORY", path.join(__dirname, "..", "state")).split(":")[0],
    knowledgeFile: str("KNOWLEDGE_FILE", path.join(__dirname, "..", "knowledge.json")),
    // prah shody s dokumentaci (ladeno na skutecnem indexu, viz README): pod nim se model nepta
    match: {
      minScore: Number(str("MIN_MATCH_SCORE", "4")),
      minCoverage: Number(str("MIN_MATCH_COVERAGE", "0.6"))
    },
    announce: {
      url: str("ANNOUNCEMENTS_URL", "https://luxos.lux-ai.cz/announcements.json"),
      releaseUrl: str("RELEASE_URL", "https://luxos.lux-ai.cz/release.json"),
      changesUrl: str("CHANGES_URL", "https://luxos.lux-ai.cz/changes/"),
      intervalMs: int("ANNOUNCE_INTERVAL_MIN", 15, 0, 1440) * 60_000,
      releases: str("ANNOUNCE_RELEASES", "1") !== "0"
    },
    limits: {
      userPer10Min: int("USER_ANSWERS_PER_10MIN", 4, 1, 1000),
      userPerDay: int("USER_ANSWERS_PER_DAY", 25, 1, 10000),
      dailyCap: int("DAILY_ANSWER_CAP", 400, 0, 1_000_000),
      threadReplies: int("THREAD_REPLY_CAP", 8, 1, 1000),
      questionChars: int("MAX_QUESTION_CHARS", 3000, 200, 20000),
      concurrent: int("MAX_CONCURRENT_ANSWERS", 3, 1, 50),
      queue: int("MAX_QUEUED_ANSWERS", 20, 0, 1000)
    },
    contactMail: "info@lux-ai.cz",
    issuesUrl: "https://github.com/luxopes/LuxOS-Arch/issues"
  };
}

module.exports = { load, readSecret };
