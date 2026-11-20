"use strict";
// Odpovedi z LuxAI: prompt s useky dokumentace, volani lux-api (OpenAI kompatibilni
// /v1/chat/completions, model "flash", nizke usili) a rozbor strukturovaneho priznaku na konci odpovedi.

const SYSTEM_PROMPT = `You are the LuxOS support assistant on the official LuxOS Discord server.
LuxOS is a fast Linux distribution based on Arch Linux with a macOS-like desktop, made by the LuxOS team (https://luxos.lux-ai.cz). LuxAI is its AI assistant and account service.

Rules:
- Answer only questions about LuxOS, LuxAI, Lux Code, LSL and using Linux on LuxOS.
- Answer ONLY from the documentation excerpts below. Every factual claim must be backed by an excerpt. Never guess commands, file paths, settings, menu names, versions, prices or hardware support, and don't use general Linux knowledge to fill gaps.
- If the excerpts don't answer the question, don't try to answer it: set "confident": false (the LuxOS team is then asked automatically).
- Never ask for passwords, API keys, tokens, recovery codes or other secrets, and tell users not to post them.
- Before any command that can delete data, repartition disks, remove packages or change boot settings, clearly warn about the risk and suggest a backup. Prefer the LuxOS apps and \`lux\` commands from the docs over generic Arch advice (LuxOS has no pacman for users).
- Always cite the excerpt links you used as plain URLs (e.g. https://luxos.lux-ai.cz/docs/luxos/apps.html). Use only links that appear in the excerpts. An answer without a link is not posted.
- Write in the language of the user's latest message (English if unclear). Be concise and friendly: short paragraphs or steps, Discord markdown, at most about 250 words.
- You cannot see the user's screen or computer. Ask for missing details (LuxOS version from About This Computer, hardware, exact error message) when needed.

End every reply with one final line in exactly this format (it is removed before posting):
META {"confident": true, "handoff": false, "lang": "en", "summary": "one short sentence describing the problem"}
- "confident": true only when every claim in your reply is backed by the excerpts; otherwise false.
- "handoff": true when the user asks for a human, a team member or a real person, or when the problem clearly needs the LuxOS team (bug in LuxOS, account or billing problem, security issue).
- "lang": ISO 639-1 code of the user's language.`;

const KEYWORDS_PROMPT = `Classify the user's latest message on the LuxOS support Discord (the line after "Message:"; the thread title is only context) and extract search keywords.
Reply with exactly one line: CATEGORY | keywords
CATEGORY is one of:
- GREETING: hello, hi, "hey Lux", introducing yourself, with no question
- THANKS: thanks, it works now, problem solved, with no new question
- SMALLTALK: "are you there?", "how are you?", "test", jokes, chit-chat about the bot itself
- OFFTOPIC: clearly unrelated to computers, software, Linux, LuxOS or LuxAI (prices, recipes, sports, homework, politics)
- QUESTION: anything else - a question, problem, bug or request about LuxOS, LuxAI, Lux Code, LSL, Linux, apps, hardware or accounts (when unsure, QUESTION)
keywords: only for QUESTION, 3-8 short English search keywords for the LuxOS documentation (translate if needed; leave out filler words, names, greetings and story details); empty otherwise.
Use the technical words a Linux documentation page would use rather than the user's everyday words, e.g. "snapshot rollback" for protection against a broken update, "backup restore" for losing files, "driver" for hardware that does not work, "firewall sandbox" for protection against viruses. Keep only the 1-2 most important words of the user's own wording.
Examples: "GREETING |", "QUESTION | printer not printing network", "QUESTION | update snapshot rollback broken system", "OFFTOPIC |"`;

const CATEGORIES = new Set(["GREETING", "THANKS", "SMALLTALK", "OFFTOPIC", "QUESTION"]);

// "QUESTION | printer wifi" -> {category, keywords}; bez kategorie = otazka (starsi format), NONE = smalltalk
function parseClassification(content) {
  const line = String(content || "").replace(/\s+/g, " ").trim();
  const match = /^\W*([A-Za-z]+)\W*?(?:\||:|$)\s*(.*)$/.exec(line);
  const word = match ? match[1].toUpperCase() : "";
  if (CATEGORIES.has(word)) return { category: word, keywords: word === "QUESTION" ? match[2].slice(0, 300) : "" };
  if (word === "NONE") return { category: "SMALLTALK", keywords: "" };
  return { category: "QUESTION", keywords: line.slice(0, 300) };
}

const BUG_PROMPT = `You check bug reports posted on the LuxOS Discord before they are forwarded to the LuxOS developers.
A report is "clear" when a developer can act on it: it says what happened (and ideally what was expected) and in which app or part of LuxOS. Steps to reproduce and the LuxOS version are nice to have; their absence alone does not make a report unclear.
Reply with JSON only, on one line:
{"clear": true|false, "summary": "short English summary, max 80 characters", "version": "LuxOS version if mentioned, else empty", "lang": "ISO 639-1 code of the report", "question": "only when not clear: a short friendly message in the report's language asking ONLY for the missing details (what happened vs. what you expected, which app, steps to reproduce, LuxOS version from About This Computer); else empty"}`;

const META_RE = /\n?\s*META\s*(\{[^\n]*\})\s*$/;

function parseReply(content) {
  let text = String(content || "").trim();
  // bez platneho priznaku META se odpoved nepovazuje za jistou (nezverejni se)
  let meta = { confident: false, handoff: false, lang: "", summary: "" };
  const match = META_RE.exec(text);
  if (match) {
    text = text.slice(0, match.index).trim();
    try {
      const parsed = JSON.parse(match[1]);
      meta = {
        confident: parsed.confident === true,
        handoff: parsed.handoff === true,
        lang: typeof parsed.lang === "string" && /^[a-z]{2}$/.test(parsed.lang) ? parsed.lang : "",
        summary: typeof parsed.summary === "string" ? parsed.summary.slice(0, 300) : ""
      };
    } catch { /* poskozeny priznak = nejista odpoved */ }
  }
  // vzdy odstranit kazdy radek zacinajici META - i useknuty ({"confident": true, "summ...)
  // nebo zopakovany uprostred; takova odpoved bez platneho priznaku je nejista
  text = text.replace(/^[ \t]*META\b.*$/gm, "").trim();
  return { text, meta };
}

function excerptsBlock(passages) {
  if (!passages.length) return "No documentation excerpts matched this question.";
  return passages.map((p, i) => `[${i + 1}] ${p.title}\nSource: ${p.url}\n${p.text}`).join("\n\n---\n\n");
}

class Assistant {
  constructor({ url, key, model, effort, maxTokens, timeoutMs }) {
    Object.assign(this, { url, key, model, effort, maxTokens, timeoutMs });
  }

  // Vraci {content, finish}. Flash vzdy premysli a premysleni se pocita do max_tokens - proto
  // velkorysy rozpocet; finish "length" = odpoved je useknuta.
  async complete(messages, maxTokens = this.maxTokens) {
    const response = await fetch(this.url, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: this.model, reasoning_effort: this.effort, max_tokens: maxTokens, temperature: 0.2, messages }),
      signal: AbortSignal.timeout(this.timeoutMs)
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const code = data && data.error && data.error.code ? data.error.code : "";
      const error = new Error(`LuxAI HTTP ${response.status}${code ? ` ${code}` : ""}`);
      error.status = response.status;
      throw error;
    }
    const choice = data && data.choices && data.choices[0];
    const content = choice && choice.message && typeof choice.message.content === "string" ? choice.message.content : "";
    const finish = choice && choice.finish_reason ? String(choice.finish_reason) : "";
    if (!content && finish !== "length") throw new Error("LuxAI returned an empty answer");
    return { content, finish };
  }

  // Druh zpravy (pozdrav, dik, smalltalk, mimo tema, otazka) a u otazky anglicka klicova slova
  // tematu (i pro jine jazyky). Podle nich bot hleda v dokumentaci a rozhoduje, zda ji pokryva.
  async classify(title, message) {
    const { content, finish } = await this.complete([
      { role: "system", content: KEYWORDS_PROMPT },
      { role: "user", content: `${title ? `Thread title: ${title.slice(0, 200)}\n` : ""}Message: ${message.slice(0, 1500)}` }
    ], 1500);
    if (finish === "length" || !content.trim()) throw new Error("LuxAI keywords incomplete");
    return parseClassification(content);
  }

  // Posouzeni hlaseni chyby: {clear, summary, version, lang, question}
  async evaluateBug(report) {
    const { content } = await this.complete([
      { role: "system", content: BUG_PROMPT },
      { role: "user", content: report.slice(0, 6000) }
    ], 2000);
    const match = /\{[\s\S]*\}/.exec(content);
    if (!match) throw new Error("bug evaluation without JSON");
    const data = JSON.parse(match[0]);
    const text = (value, max) => (typeof value === "string" ? value.replace(/\s+/g, " ").trim().slice(0, max) : "");
    const question = text(data.question, 800);
    return {
      // nejasne jen s konkretni otazkou; jinak preposlat
      clear: data.clear !== false || !question,
      summary: text(data.summary, 80),
      version: text(data.version, 40),
      lang: typeof data.lang === "string" && /^[a-z]{2}$/.test(data.lang) ? data.lang : "",
      question
    };
  }

  // history: [{role: "user"|"assistant", content}], posledni je aktualni dotaz
  async answer(history, passages) {
    const messages = [
      { role: "system", content: `${SYSTEM_PROMPT}\n\nDocumentation excerpts:\n\n${excerptsBlock(passages)}` },
      ...history
    ];
    // useknuta odpoved (finish "length"): jednou znovu s dvojnasobnym rozpoctem, pak je nejista
    let result = await this.complete(messages);
    if (result.finish === "length") result = await this.complete(messages, Math.min(16000, this.maxTokens * 2));
    const reply = parseReply(result.content);
    if (result.finish === "length") reply.meta.confident = false;
    return reply;
  }
}

module.exports = { Assistant, parseReply, parseClassification, SYSTEM_PROMPT, KEYWORDS_PROMPT, BUG_PROMPT };
