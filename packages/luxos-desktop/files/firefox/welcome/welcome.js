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
    if (Object.prototype.hasOwnProperty.call(strings, base)) {
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
  // ceska verze webu jen u stranek, ktere cesky existuji (data-cs), jinak anglicka
  if (lang === "cs") {
    for (const a of document.querySelectorAll('a[data-cs][href^="https://luxos.lux-ai.cz/docs/"]')) {
      a.href = a.href.replace("https://luxos.lux-ai.cz/docs/", "https://luxos.lux-ai.cz/cs/docs/");
    }
  }

  // Firefox (luxos.cfg) pozna na teto mistni strance odkaz #import-<cas> (pruvodce importem Firefoxu)
  // a #open-<aplikace>-<cas> (otevre aplikaci LuxOS, bez ni stranku napovedy na webu). Adresa se hned
  // vrati zpet bez #, aby tlacitko Zpet ani obnoveni relace akci neopakovaly.
  const trigger = (what) => {
    location.replace("#" + what + "-" + Date.now());
    setTimeout(() => {
      try {
        history.replaceState(null, "", location.pathname + location.search);
      } catch (e) {}
    }, 400);
  };
  const plain = (ev) => ev.button === 0 && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey && !ev.altKey;
  const button = document.getElementById("import-button");
  if (button) {
    button.addEventListener("click", (ev) => {
      ev.preventDefault();
      trigger("import");
    });
  }
  // dlazdice aplikaci: obycejne kliknuti otevre aplikaci, prostredni / Ctrl+klik dal otevre web
  for (const a of document.querySelectorAll("a[data-app]")) {
    a.addEventListener("click", (ev) => {
      if (plain(ev)) {
        ev.preventDefault();
        trigger("open-" + a.dataset.app);
      }
    });
  }
})();
