"use strict";
// Pevne texty bota (limity, predani cloveku). Odpovedi modelu jsou v jazyce dotazu;
// tyto texty jsou anglicky a cesky (vetsina uzivatelu LuxOS), jine jazyky dostanou anglictinu.

const { normalize } = require("./knowledge");

const TEXTS = {
  en: {
    handoff: (mail) => `I've asked the LuxOS team to take a look - a human will reply in this thread. You can also e-mail ${mail}.`,
    handoffAlready: (mail) => `The LuxOS team already knows about this thread and will reply here. For anything urgent, e-mail ${mail}.`,
    notConfident: "I'm not sure about this one, so I've asked the LuxOS team to check.",
    elsewhere: (support, mail) => `For help from a human, please open a post in ${support} or e-mail ${mail}.`,
    slow: (minutes) => `You're asking faster than I can keep up. Please try again in about ${minutes} min.`,
    dailyUser: "You've reached today's limit of questions for me. Please try again tomorrow, or wait for someone from the community.",
    dailyGlobal: (mail) => `I've answered all the questions I can for today. Someone from the community or the LuxOS team will get back to you, or e-mail ${mail}.`,
    threadCap: (mail) => `This thread is getting long for me. A human from the LuxOS team or the community will continue - or e-mail ${mail}.`,
    busy: "I'm a bit overloaded right now. Please send your question again in a few minutes.",
    error: (mail) => `Sorry, I couldn't get an answer from LuxAI right now. Please try again later, or e-mail ${mail}.`,
    tooLong: (max) => `(Your message was long, so I only read the first ${max} characters.)`,
    membersOnly: "I only answer members of the LuxOS Discord server. Join the server and ask in #support.",
    docs: "Docs",
    secret: "It looks like your message may contain a password, key or token. Please delete that message and change the secret - never post secrets here."
  },
  cs: {
    handoff: (mail) => `Požádal jsem tým LuxOS, aby se na to podíval – v tomto vlákně odpoví člověk. Můžete také napsat na ${mail}.`,
    handoffAlready: (mail) => `Tým LuxOS o tomto vlákně už ví a odpoví tady. V naléhavém případě pište na ${mail}.`,
    notConfident: "Tady si nejsem jistý, proto jsem požádal tým LuxOS o kontrolu.",
    elsewhere: (support, mail) => `Pro pomoc od člověka založte příspěvek v ${support} nebo napište na ${mail}.`,
    slow: (minutes) => `Ptáte se rychleji, než stíhám. Zkuste to prosím znovu asi za ${minutes} min.`,
    dailyUser: "Pro dnešek jste vyčerpali limit otázek pro mě. Zkuste to prosím zítra, nebo počkejte na někoho z komunity.",
    dailyGlobal: (mail) => `Na dnešek už jsem odpověděl na všechny otázky, na které můžu. Ozve se někdo z komunity nebo z týmu LuxOS, případně pište na ${mail}.`,
    threadCap: (mail) => `Toto vlákno je už na mě dlouhé. Pokračovat bude člověk z týmu LuxOS nebo komunity – případně pište na ${mail}.`,
    busy: "Teď mám moc práce. Pošlete prosím otázku znovu za pár minut.",
    error: (mail) => `Promiňte, z LuxAI se teď nepodařilo získat odpověď. Zkuste to prosím později, nebo pište na ${mail}.`,
    tooLong: (max) => `(Zpráva byla dlouhá, přečetl jsem jen prvních ${max} znaků.)`,
    membersOnly: "Odpovídám jen členům Discord serveru LuxOS. Připojte se na server a zeptejte se v #support.",
    docs: "Dokumentace",
    secret: "Vypadá to, že zpráva obsahuje heslo, klíč nebo token. Zprávu prosím smažte a tajný údaj změňte – nikdy ho sem nepište."
  }
};

const CZECH_WORDS = new Set(["jak", "nefunguje", "mam", "muzu", "proc", "kde", "neni", "prosim", "dekuji", "diky", "dobry", "den", "ahoj", "chci", "potrebuji", "pocitac", "nejde", "nevim", "jsem", "nebo", "kdyz", "jde", "aplikace", "nastaveni", "zdravim", "otazka"]);

const ENGLISH_WORDS = new Set(["the", "is", "are", "how", "what", "my", "i", "it", "to", "do", "does", "can", "not", "with", "on", "in", "why", "when", "and", "of", "for", "about", "there", "this", "work"]);
// caste kratke slovo nemciny, spanelstiny, francouzstiny, italstiny, polstiny, portugalstiny
const OTHER_WORDS = new Set(["ich", "wie", "nicht", "und", "ist", "der", "die", "das", "mit", "kann", "funktioniert", "el", "la", "que", "como", "por", "para", "est", "pas", "pour", "les", "une", "je", "comment", "il", "non", "che", "di", "nie", "czy", "jest", "sie", "nao", "uma"]);

// Hruby odhad jazyka: cestina/slovenstina podle diakritiky a castych slov, jinak "other", anglictina podle slov
function detectLanguage(text) {
  const raw = String(text);
  if (/[ěščřžůťďň]/i.test(raw)) return "cs";
  const words = normalize(raw).split(/[^a-z]+/).filter(Boolean);
  if (words.filter((w) => CZECH_WORDS.has(w)).length >= 1 && words.length <= 40) {
    if (words.filter((w) => CZECH_WORDS.has(w)).length / words.length > 0.08) return "cs";
  }
  // jine pismo nebo diakritika (krome ceske vyse) = jiny jazyk; jinak podle castych slov
  if (/[^\x00-\x7f‘’“”–—…]/.test(raw.replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, ""))) return "other";
  const english = words.filter((w) => ENGLISH_WORDS.has(w)).length;
  const other = words.filter((w) => OTHER_WORDS.has(w)).length;
  return other > english ? "other" : "en";
}

function texts(lang) {
  return TEXTS[lang] || TEXTS.en;
}

module.exports = { texts, detectLanguage };
