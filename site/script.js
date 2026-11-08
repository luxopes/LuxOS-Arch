// LuxOS web: nabidka na mobilu, svetly/tmavy rezim (pamatuje si volbu), galerie, kopirovani,
// aktualni vydani z /release.json (stranka uz ma hodnoty z generatoru, tady se jen obnovi).
const isCs = document.documentElement.lang === 'cs';
const locale = isCs ? 'cs-CZ' : 'en-GB';
const navButton = document.querySelector('.mobile-nav-toggle');
const mobileNav = document.querySelector('.mobile-nav');
navButton?.addEventListener('click', () => {
  const open = mobileNav.classList.toggle('open');
  navButton.setAttribute('aria-expanded', String(open));
});
mobileNav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
  mobileNav.classList.remove('open');
  navButton?.setAttribute('aria-expanded', 'false');
}));

// ---- svetly/tmavy rezim ----
const themeButton = document.querySelector('.theme-toggle');
const store = {
  get: key => { try { return localStorage.getItem(key); } catch { return null; } },
  set: (key, value) => { try { localStorage.setItem(key, value); } catch { /* bez ulozeni */ } },
};
const applyTheme = light => {
  document.body.classList.toggle('light', light);
  themeButton?.setAttribute('aria-pressed', String(light));
  const knob = document.querySelector('.toggle-knob');
  if (knob) knob.style.marginLeft = light ? '0' : '10px';
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', light ? '#ecf0fa' : '#080b16');
  // snimky plochy ve vzhledu webu: src i srcset (jinak by prohlizec dal bral obrazek ze srcset)
  document.querySelectorAll('img[data-dark][data-light]').forEach(img => {
    const set = light ? img.dataset.lightSrcset : img.dataset.darkSrcset;
    if (set && img.getAttribute('srcset') !== set) img.setAttribute('srcset', set);
    // <picture> (notebook na uvodni strance): zdroj podle systemoveho vzhledu musi nest volbu webu
    if (set && img.parentElement?.tagName === 'PICTURE') {
      img.parentElement.querySelectorAll('source').forEach(s => { if (s.getAttribute('srcset') !== set) s.setAttribute('srcset', set); });
    }
    const src = light ? img.dataset.light : img.dataset.dark;
    if (img.getAttribute('src') !== src) img.setAttribute('src', src);
  });
};
const saved = store.get('luxos-theme');
applyTheme(saved ? saved === 'light' : matchMedia('(prefers-color-scheme: light)').matches);
themeButton?.addEventListener('click', () => {
  document.body.classList.add('theme-animating');
  const light = !document.body.classList.contains('light');
  applyTheme(light);
  store.set('luxos-theme', light ? 'light' : 'dark');
  window.clearTimeout(window.__luxThemeTimer);
  window.__luxThemeTimer = window.setTimeout(() => document.body.classList.remove('theme-animating'), 700);
});
matchMedia('(prefers-color-scheme: light)').addEventListener?.('change', e => {
  if (!store.get('luxos-theme')) applyTheme(e.matches);
});

// ---- kopirovani ----
const bindCopy = button => button.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    const previous = button.textContent;
    button.textContent = '✓';
    setTimeout(() => { button.textContent = previous; }, 1300);
  } catch {
    button.title = isCs ? 'Kopírování funguje jen přes HTTPS.' : 'Copying works only over HTTPS.';
  }
});
document.querySelectorAll('[data-copy]').forEach(bindCopy);

// ---- galerie ----
const lightbox = document.querySelector('.lightbox');
const shots = [...document.querySelectorAll('.gallery-item')];
let current = 0;
const showShot = index => {
  current = (index + shots.length) % shots.length;
  const item = shots[current];
  const img = lightbox.querySelector('img');
  const dark = !document.body.classList.contains('light') && item.dataset.fullDark;
  img.src = dark || item.getAttribute('href');
  img.alt = item.querySelector('img')?.alt || '';
  lightbox.querySelector('figcaption').textContent = item.dataset.caption || '';
};
shots.forEach((item, index) => item.addEventListener('click', event => {
  if (!lightbox?.showModal) return;          // bez <dialog>: odkaz otevre obrazek
  event.preventDefault();
  showShot(index);
  lightbox.showModal();
}));
lightbox?.querySelector('.lightbox-close').addEventListener('click', () => lightbox.close());
lightbox?.querySelector('.lightbox-prev').addEventListener('click', () => showShot(current - 1));
lightbox?.querySelector('.lightbox-next').addEventListener('click', () => showShot(current + 1));
lightbox?.addEventListener('click', event => { if (event.target === lightbox) lightbox.close(); });
lightbox?.addEventListener('keydown', event => {
  if (event.key === 'ArrowLeft') showShot(current - 1);
  if (event.key === 'ArrowRight') showShot(current + 1);
});
let touchX = null;
lightbox?.addEventListener('touchstart', e => { touchX = e.touches[0].clientX; }, { passive: true });
lightbox?.addEventListener('touchend', e => {
  if (touchX === null) return;
  const dx = e.changedTouches[0].clientX - touchX;
  if (Math.abs(dx) > 50) showShot(current + (dx < 0 ? 1 : -1));
  touchX = null;
});

// ---- aktualni vydani ----
const formatSize = bytes => `${(bytes / 2 ** 30).toLocaleString(locale, { maximumFractionDigits: 1 })} GB`;
const formatDate = iso => new Date(`${iso}T12:00:00`).toLocaleDateString(locale, { day: 'numeric', month: 'long', year: 'numeric' });
fetch('/release.json', { cache: 'no-cache' })
  .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
  .then(rel => {
    const iso = rel.iso || {};
    const values = {
      version: rel.version, codename: rel.codename, iso_version: iso.version, iso_file: iso.file,
      iso_size: iso.size ? formatSize(iso.size) : null, iso_date: iso.date ? formatDate(iso.date) : null,
      iso_sha256: iso.sha256,
    };
    document.querySelectorAll('[data-release]').forEach(el => {
      const v = values[el.dataset.release];
      if (v) el.textContent = v;
    });
    document.querySelectorAll('[data-release-copy]').forEach(el => {
      const v = values[el.dataset.releaseCopy];
      if (v) el.dataset.copy = v;
    });
    if (iso.file) {
      const links = { iso: `/download/${iso.file}`, sig: `/download/${iso.file}.sig`, sums: '/download/SHA256SUMS' };
      document.querySelectorAll('[data-release-href]').forEach(el => { el.href = links[el.dataset.releaseHref]; });
      const cmd = document.querySelector('#verify .terminal .copy');
      if (cmd) cmd.dataset.copy = `sha256sum -c SHA256SUMS\ngpg --import luxos.gpg\ngpg --verify ${iso.file}.sig ${iso.file}`;
    }
    const note = document.querySelector('[data-release-show="update_note"]');
    if (note) note.hidden = !(rel.version && iso.version && rel.version !== iso.version);
  })
  .catch(() => { /* zustanou hodnoty ze stranky */ });

// ---- prepinac jazyka: zvyrazneni prejede na druhy jazyk a teprve pak se prejde na jeho stranku ----
// (nova stranka se uz vykresli se zvyraznenim na spravnem miste; Ctrl/Shift/stredni tlacitko =
// beznym zpusobem do noveho panelu/okna; pri omezeni pohybu se prejde hned)
document.querySelectorAll('.lang-switch').forEach(sw => {
  const links = [...sw.querySelectorAll('a')];
  links.forEach((link, index) => link.addEventListener('click', event => {
    if (link.hasAttribute('aria-current') || event.button !== 0 || event.metaKey || event.ctrlKey
        || event.shiftKey || event.altKey || event.defaultPrevented) return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    event.preventDefault();
    sw.classList.add('switching');
    sw.dataset.active = String(index);
    let gone = false;
    const go = () => { if (!gone) { gone = true; window.location.href = link.href; } };
    sw.querySelector('.lang-pill')?.addEventListener('transitionend', go, { once: true });
    window.setTimeout(go, 400);
  }));
});
// navrat tlacitkem Zpet (bfcache): zvyrazneni zpet na aktualni jazyk stranky
window.addEventListener('pageshow', event => {
  if (!event.persisted) return;
  document.querySelectorAll('.lang-switch').forEach(sw => {
    sw.classList.remove('switching');
    const current = [...sw.querySelectorAll('a')].findIndex(a => a.hasAttribute('aria-current'));
    sw.dataset.active = String(Math.max(0, current));
  });
});
