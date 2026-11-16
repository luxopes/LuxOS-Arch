// LuxOS - uvitaci stranka Firefoxu: jazyk z ?lang= (jazyk systemu z luxos.cfg), jinak podle Firefoxu,
// jinak anglictina; ceska verze odkazuje na ceskou dokumentaci webu LuxOS.
(function () {
  "use strict";
  const strings = window.LUXOS_WELCOME_STRINGS || {};
  const wanted = [];
  try {
    const q = new URLSearchParams(location.search).get("lang");
    if (q) {
      wanted.push(q);
    }
  } catch (e) {}
  for (const l of navigator.languages || [navigator.language || ""]) {
    wanted.push(l);
  }
  let lang = "en";
  for (const l of wanted) {
    const base = String(l).toLowerCase().split(/[-_.]/)[0];
    if (strings[base]) {
      lang = base;
      break;
    }
  }
  const t = Object.assign({}, strings.en || {}, strings[lang] || {});
  document.documentElement.lang = lang;
  for (const el of document.querySelectorAll("[data-i18n]")) {
    const v = t[el.dataset.i18n];
    if (v) {
      el.textContent = v;
    }
  }
  if (lang === "cs") {
    for (const a of document.querySelectorAll('a[href^="https://luxos.lux-ai.cz/docs/"]')) {
      a.href = a.href.replace("https://luxos.lux-ai.cz/docs/", "https://luxos.lux-ai.cz/cs/docs/");
    }
  }
  // Import: Firefox (luxos.cfg) pozna odkaz #import-<cas> na teto mistni strance a otevre sveho pruvodce
  const button = document.getElementById("import-button");
  if (button) {
    button.addEventListener("click", (ev) => {
      ev.preventDefault();
      location.hash = "import-" + Date.now();
    });
  }
})();
