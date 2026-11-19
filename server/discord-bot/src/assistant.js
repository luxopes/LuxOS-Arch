"use strict";
// Odpovedi z LuxAI: prompt s useky dokumentace, volani lux-api (OpenAI kompatibilni
// /v1/chat/completions, model "flash", nizke usili) a rozbor strukturovaneho priznaku na konci odpovedi.

const SYSTEM_PROMPT = `You are the LuxOS support assistant on the official LuxOS Discord server.
LuxOS is a fast Linux distribution based on Arch Linux with a macOS-like desktop, made by the LuxOS team (https://luxos.lux-ai.cz). LuxAI is its AI assistant and account service.

Rules:
- Answer only questions about LuxOS, LuxAI, Lux Code, LSL and using Linux on LuxOS. For anything else, say briefly that you can only help with LuxOS.
- Base your answer on the documentation excerpts below. If they do not cover the question, say honestly that you are not sure; do not invent commands, settings, menu names or features.
- Never ask for passwords, API keys, tokens, recovery codes or other secrets, and tell users not to post them.
- Before any command that can delete data, repartition disks, remove packages or change boot settings, clearly warn about the risk and suggest a backup. Prefer the LuxOS apps and \`lux\` commands from the docs over generic Arch advice (LuxOS has no pacman for users).
- Cite the documentation links you used as plain URLs (e.g. https://luxos.lux-ai.cz/docs/luxos/apps.html). Use only links that appear in the excerpts.
- Write in the language of the user's latest message (English if unclear). Be concise and friendly: short paragraphs or steps, Discord markdown, at most about 250 words.
- You cannot see the user's screen or computer. Ask for missing details (LuxOS version from About This Computer, hardware, exact error message) when needed.

End every reply with one final line in exactly this format (it is removed before posting):
META {"confident": true, "handoff": false, "lang": "en", "summary": "one short sentence describing the problem"}
- "confident": false when the excerpts do not support a reliable answer.
- "handoff": true when the user asks for a human, a team member or a real person, or when the problem clearly needs the LuxOS team (bug in LuxOS, account or billing problem, security issue).
- "lang": ISO 639-1 code of the user's language.`;

const META_RE = /\n?\s*META\s*(\{[^\n]*\})\s*$/;

function parseReply(content) {
  let text = String(content || "").trim();
  let meta = { confident: true, handoff: false, lang: "", summary: "" };
  const match = META_RE.exec(text);
  if (match) {
    text = text.slice(0, match.index).trim();
    try {
      const parsed = JSON.parse(match[1]);
      meta = {
        confident: parsed.confident !== false,
        handoff: parsed.handoff === true,
        lang: typeof parsed.lang === "string" && /^[a-z]{2}$/.test(parsed.lang) ? parsed.lang : "",
        summary: typeof parsed.summary === "string" ? parsed.summary.slice(0, 300) : ""
      };
    } catch { /* poskozeny priznak = beznou odpoved */ }
  }
  // model obcas zopakuje META i uprostred - odstranit
  text = text.replace(/^\s*META\s*\{.*\}\s*$/gm, "").trim();
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
    const content = data && data.choices && data.choices[0] && data.choices[0].message ? data.choices[0].message.content : "";
    if (!content) throw new Error("LuxAI returned an empty answer");
    return content;
  }

  // Dotaz v jinem jazyce nez anglictine -> anglicka klicova slova pro vyhledani v dokumentaci
  async searchTerms(question) {
    const content = await this.complete([
      { role: "system", content: "Translate the user's question into short English search keywords for the LuxOS documentation. Reply with the keywords only, one line." },
      { role: "user", content: question.slice(0, 1500) }
    ], 60);
    return content.replace(/\s+/g, " ").slice(0, 300);
  }

  // history: [{role: "user"|"assistant", content}], posledni je aktualni dotaz
  async answer(history, passages) {
    const messages = [
      { role: "system", content: `${SYSTEM_PROMPT}\n\nDocumentation excerpts:\n\n${excerptsBlock(passages)}` },
      ...history
    ];
    return parseReply(await this.complete(messages));
  }
}

module.exports = { Assistant, parseReply, SYSTEM_PROMPT };
