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

  // Spojeni s Firefoxem (luxos.cfg): stranka posle #hello-<cas>, luxos.cfg odpovi adresou
  // #ok-<cas>[-ubo] (hash se zmeni bez noveho nacteni; "-ubo" = uBlock Origin je zapnuty). Potom
  // #import-<cas> otevre pruvodce importem Firefoxu a #open-<aplikace>-<cas> aplikaci LuxOS. Bez
  // odpovedi (Firefox spusteny pred aktualizaci LuxOS se starym luxos.cfg, stranka otevrena jinde)
  // vedou dlazdice na web a import ukaze navod - nikdy se nic netvari, ze se deje.
  const clean = () => {
    try {
      history.replaceState(null, "", location.pathname + location.search);
    } catch (e) {}
  };
  let hook = null;                       // null = ceka se, true/false = luxos.cfg odpovida / ne
  const waiting = [];
  const answered = (flags) => {
    if (hook !== null) {
      return;
    }
    hook = true;
    document.documentElement.dataset.hook = "on";
    if (flags.includes("ubo")) {
      const badge = document.getElementById("badge-ubo");
      if (badge) {
        badge.hidden = false;
      }
    }
    clean();
    waiting.splice(0).forEach((f) => f());
  };
  const okRe = /^#ok-(\d+)((?:-[a-z]+)*)$/;
  const checkOk = () => {
    const m = okRe.exec(location.hash);
    if (m) {
      answered(m[2].split("-"));
    }
  };
  window.addEventListener("hashchange", checkOk);
  if (okRe.test(location.hash)) {
    checkOk();
  } else {
    location.replace("#hello-" + Date.now());
    setTimeout(() => {
      if (hook === null) {
        hook = false;
        document.documentElement.dataset.hook = "off";
        clean();
        waiting.splice(0).forEach((f) => f());
      }
    }, 1500);
  }
  const whenReady = (f) => (hook === null ? waiting.push(f) : f());
  const trigger = (what) => {
    location.replace("#" + what + "-" + Date.now());
    // adresa hned zpet bez #: tlacitko Zpet ani obnoveni relace akci neopakuji
    setTimeout(clean, 400);
  };
  const plain = (ev) => ev.button === 0 && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey && !ev.altKey;
  const button = document.getElementById("import-button");
  const help = document.getElementById("import-help");
  if (button) {
    button.addEventListener("click", (ev) => {
      ev.preventDefault();
      whenReady(() => {
        // i bez odpovedi to zkusime (starsi luxos.cfg import umel), navod ukazeme vzdy
        trigger("import");
        if (!hook && help) {
          help.hidden = false;
          help.focus();
        }
      });
    });
  }
  // dlazdice aplikaci: obycejne kliknuti otevre aplikaci, prostredni / Ctrl+klik a bez luxos.cfg web
  for (const a of document.querySelectorAll("a[data-app]")) {
    a.addEventListener("click", (ev) => {
      if (!plain(ev) || hook === false) {
        return;
      }
      ev.preventDefault();
      whenReady(() => {
        if (hook) {
          trigger("open-" + a.dataset.app);
        } else {
          window.open(a.href, "_blank", "noopener,noreferrer");
        }
      });
    });
  }
})();
