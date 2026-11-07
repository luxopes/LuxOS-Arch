// LuxOS web: stranka Pouzivani LuxOS - grafy z /stats/usage.json (tydenni pocitadla countme ze serveru).
// Bez knihoven: SVG se kresli rucne podle sirky prvku (text tak ma stejnou velikost i na mobilu).
(() => {
  const root = document.querySelector('[data-usage]');
  if (!root) return;
  const cs = document.documentElement.lang === 'cs';
  const locale = cs ? 'cs-CZ' : 'en-GB';
  const L = cs ? {
    loading: 'Načítám statistiky…',
    unavailable: 'Statistiky zatím nejsou k dispozici. Zkuste to prosím později.',
    totals: 'Aktivní počítače po týdnech', age: 'Počítače podle doby používání LuxOS',
    ages: ['Nové (první týden)', 'Do 1 měsíce', '1–6 měsíců', 'Déle'],
    week: w => `${w}. týden`, from: d => `od ${d}`, computers: 'Počítače', total: 'celkem',
    progress: 'probíhá', change: (a, b) => `z ${a} na ${b}`,
    partial: (w, d) => `Aktuální týden (${w}, od ${d}) ještě probíhá – jeho hodnota je čárkovaně a ještě poroste.`,
    breakdown: d => `Za poslední celý týden (od ${d}).`, breakdownCur: 'Za aktuální, zatím neúplný týden.', generated: d => `Aktualizováno ${d}.`,
    desc: (a, b, max, last) => `Od ${a} do ${b}. Nejvíce ${max} počítačů za týden, v posledním celém týdnu ${last}.`,
  } : {
    loading: 'Loading statistics…',
    unavailable: 'Statistics are not available yet. Please check back later.',
    totals: 'Weekly active computers', age: 'Computers by how long they have used LuxOS',
    ages: ['New (first week)', 'Up to 1 month', '1–6 months', 'Longer'],
    week: w => `week ${w}`, from: d => `from ${d}`, computers: 'Computers', total: 'total',
    progress: 'in progress', change: (a, b) => `from ${a} to ${b}`,
    partial: (w, d) => `The current week (${w}, from ${d}) is still in progress – its value is drawn dashed and will still grow.`,
    breakdown: d => `In the last complete week (from ${d}).`, breakdownCur: 'In the current week, which is not complete yet.', generated: d => `Updated ${d}.`,
    desc: (a, b, max, last) => `From ${a} to ${b}. At most ${max} computers in a week, ${last} in the last complete week.`,
  };
  const $ = sel => root.querySelector(sel);
  const msg = $('[data-usage-msg]');
  const dash = $('[data-usage-dash]');
  const num = n => Number(n || 0).toLocaleString(locale);
  const pct = (x, sign) => new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0, signDisplay: sign ? 'exceptZero' : 'auto' }).format(x);
  const day = (iso, year) => new Date(`${iso}T12:00:00Z`).toLocaleDateString(locale, year ? { day: 'numeric', month: 'long', year: 'numeric' } : { day: 'numeric', month: 'short' });
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  msg.hidden = false;
  msg.textContent = L.loading;

  const fail = () => { msg.hidden = false; msg.textContent = L.unavailable; msg.classList.add('usage-msg-off'); dash.hidden = true; };

  const niceMax = v => {
    if (v <= 4) return 4;
    const step = 10 ** Math.floor(Math.log10(v / 4));
    // krok osy = nasobek 1, 2, 2.5, 3, 4, 5, 6, 8 nebo 10 a cele cislo
    const m = [1, 2, 2.5, 3, 4, 5, 6, 8, 10].find(f => Number.isInteger(f * step) && f * step * 4 >= v);
    return m * step * 4;
  };

  fetch('/stats/usage.json', { cache: 'no-cache' })
    .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(d => {
      const weeks = Array.isArray(d && d.weeks) ? d.weeks : [];
      const n = weeks.length;
      const ok = arr => Array.isArray(arr) && arr.length === n;
      if (!d || d.schema !== 1 || !n || !ok(d.totals) || !d.totals.some(v => v > 0)) return fail();
      const tot = d.totals.map(v => +v || 0);
      const starts = ok(d.week_start) ? d.week_start : weeks.map(() => null);
      const ages = ['1', '2', '3', '4'].map(k => (ok(d.by_age && d.by_age[k]) ? d.by_age[k].map(v => +v || 0) : weeks.map(() => 0)));
      const partial = weeks[n - 1] === d.current_week;
      const last = partial ? n - 2 : n - 1;            // posledni cely tyden
      const wnum = i => L.week(+String(weeks[i]).split('W')[1] || weeks[i]);
      const wdate = (i, y) => (starts[i] ? day(starts[i], y) : weeks[i]);
      render(d, { n, tot, ages, partial, last, wnum, wdate });
    })
    .catch(fail);

  function render(d, s) {
    const { n, tot, ages, partial, last, wnum, wdate } = s;
    msg.hidden = true;
    dash.hidden = false;
    const kpi = (k, v) => { const el = $(`[data-kpi="${k}"]`); if (el) el.textContent = v; };
    if (last >= 0) {
      kpi('total', num(tot[last]));
      kpi('week', `${wnum(last)}, ${L.from(wdate(last))}`);
      if (last >= 1 && tot[last - 1] > 0) {
        kpi('change', pct((tot[last] - tot[last - 1]) / tot[last - 1], true));
        kpi('change-sub', L.change(num(tot[last - 1]), num(tot[last])));
      }
      if (tot[last] > 0) kpi('returning', pct((ages[1][last] + ages[2][last] + ages[3][last]) / tot[last]));
      $('[data-breakdown-week]').textContent = L.breakdown(wdate(last, true));
    } else {
      $('[data-breakdown-week]').textContent = L.breakdownCur;
    }
    const pn = $('[data-partial-note]');
    pn.textContent = partial ? L.partial(wnum(n - 1), wdate(n - 1)) : '';
    pn.hidden = !partial;
    if (d.generated) {
      const g = new Date(d.generated);
      if (!isNaN(g)) $('[data-generated]').textContent = L.generated(g.toLocaleString(locale, { dateStyle: 'long', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC');
    }

    // vodorovne pruhy: verze, kanaly, architektura v poslednim celem tydnu
    const bi = last >= 0 ? last : n - 1;
    root.querySelectorAll('[data-bars]').forEach(box => {
      const obj = d[box.dataset.bars] || {};
      const rows = Object.keys(obj).map(k => [k, +(obj[k] || [])[bi] || 0]).filter(r => r[1] > 0).sort((a, b) => b[1] - a[1]);
      const sum = rows.reduce((a, r) => a + r[1], 0);
      box.innerHTML = rows.length ? rows.map(([k, v]) => `<div class="u-bar"><span class="u-bar-label">${esc(k)}</span>`
        + `<span class="u-bar-track"><span class="u-bar-fill" style="width:${Math.max(1, (v / rows[0][1]) * 100).toFixed(1)}%"></span></span>`
        + `<span class="u-bar-val">${num(v)} <small>${pct(v / sum)}</small></span></div>`).join('') : '<p class="usage-note">–</p>';
    });

    // tabulka pro ctecky obrazovky a pro presna cisla (nejnovejsi nahore)
    let rows = '';
    for (let i = n - 1; i >= 0; i--) {
      rows += `<tr><th scope="row">${esc(wdate(i, true))} <small>(${esc(wnum(i))}${partial && i === n - 1 ? ', ' + L.progress : ''})</small></th>`
        + `<td>${num(tot[i])}</td>${ages.map(a => `<td>${num(a[i])}</td>`).join('')}</tr>`;
    }
    $('[data-table]').innerHTML = rows;

    const figs = [...root.querySelectorAll('[data-chart]')];
    let width = 0;
    const draw = () => {
      const w = Math.round(figs[0].clientWidth);
      if (!w || w === width) return;
      width = w;
      figs.forEach(f => chart(f, f.dataset.chart, w, s));
    };
    draw();
    let raf = 0;
    window.addEventListener('resize', () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); });
  }

  function chart(fig, kind, W, s) {
    const { n, tot, ages, partial, last, wnum, wdate } = s;
    const H = W < 520 ? 210 : 260;
    const m = { l: 42, r: 14, t: 14, b: 28 };
    const pw = W - m.l - m.r;
    const ph = H - m.t - m.b;
    const ymax = niceMax(Math.max(...tot));
    const y = v => m.t + ph - (v / ymax) * ph;
    const bars = kind === 'age';
    const step = bars ? pw / n : pw / Math.max(1, n - 1);
    const x = i => (bars ? m.l + step * (i + 0.5) : (n > 1 ? m.l + step * i : m.l + pw / 2));
    const f1 = v => v.toFixed(1);
    let g = '';
    for (let k = 0; k <= 4; k++) {
      const v = (ymax / 4) * k;
      g += `<line class="u-grid" x1="${m.l}" x2="${W - m.r}" y1="${f1(y(v))}" y2="${f1(y(v))}"/>`
        + `<text class="u-axis" x="${m.l - 6}" y="${f1(y(v) + 4)}" text-anchor="end">${num(v)}</text>`;
    }
    const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 74))));
    for (let i = n - 1; i >= 0; i -= every) {
      g += `<text class="u-axis" x="${f1(x(i))}" y="${H - 8}" text-anchor="${i === n - 1 && !bars ? 'end' : 'middle'}">${esc(wdate(i))}</text>`;
    }
    let marks = '';
    if (bars) {
      const bw = Math.max(2, Math.min(28, step * 0.68));
      for (let i = 0; i < n; i++) {
        let base = 0;
        for (let a = 3; a >= 0; a--) {                 // odspodu: nejdele pouzivane, nahore nove
          const v = ages[a][i];
          if (!v) continue;
          const y0 = y(base), y1 = y(base + v);
          const h = Math.max(0.5, y0 - y1 - (base ? 2 : 0));   // 2px mezera mezi useky
          marks += `<rect class="u-a${a + 1}${partial && i === n - 1 ? ' u-partial' : ''}" x="${f1(x(i) - bw / 2)}" y="${f1(y1)}" width="${f1(bw)}" height="${f1(h)}" rx="2"/>`;
          base += v;
        }
      }
    } else {
      const pts = tot.map((v, i) => `${f1(x(i))},${f1(y(v))}`);
      const end = partial ? n - 1 : n;                 // plna cara jen pres cele tydny
      if (end > 1) {
        marks += `<path class="u-area" d="M${pts[0]}L${pts.slice(1, end).join('L')}L${f1(x(end - 1))},${f1(y(0))}L${f1(x(0))},${f1(y(0))}Z"/>`;
        marks += `<path class="u-line" d="M${pts.slice(0, end).join('L')}"/>`;
      }
      if (partial && n > 1) marks += `<path class="u-line u-dash" d="M${pts[n - 2]}L${pts[n - 1]}"/>`;
      if (last >= 0) {
        marks += `<circle class="u-dot" cx="${f1(x(last))}" cy="${f1(y(tot[last]))}" r="4.5"/>`;
        marks += `<text class="u-val" x="${f1(x(last) - 8)}" y="${f1(y(tot[last]) - 10)}" text-anchor="end">${num(tot[last])}</text>`;
      }
      if (partial) marks += `<circle class="u-dot u-open" cx="${f1(x(n - 1))}" cy="${f1(y(tot[n - 1]))}" r="4.5"/>`;
    }
    const max = Math.max(...tot);
    const title = bars ? L.age : L.totals;
    const desc = L.desc(wdate(0, true), wdate(n - 1, true), num(max), last >= 0 ? num(tot[last]) : '–');
    fig.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-labelledby="t-${kind} d-${kind}">`
      + `<title id="t-${kind}">${esc(title)}</title><desc id="d-${kind}">${esc(desc)}</desc>`
      + `${g}<line class="u-guide" y1="${m.t}" y2="${m.t + ph}" x1="0" x2="0" visibility="hidden"/>${marks}`
      + `<rect class="u-hit" x="${m.l}" y="${m.t}" width="${pw}" height="${ph}"/></svg><div class="u-tip" hidden></div>`;

    // popisek pri najeti mysi / dotyku
    const svg = fig.firstChild, tip = fig.lastChild, guide = svg.querySelector('.u-guide');
    const hide = () => { tip.hidden = true; guide.setAttribute('visibility', 'hidden'); };
    svg.addEventListener('pointerleave', hide);
    svg.addEventListener('pointermove', ev => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const i = Math.min(n - 1, Math.max(0, bars ? Math.floor((px - m.l) / step) : Math.round((px - m.l) / (step || 1))));
      const head = `<strong>${esc(wdate(i, true))}</strong> <span>${esc(wnum(i))}${partial && i === n - 1 ? ', ' + L.progress : ''}</span>`;
      const body = bars
        ? ages.map((a, k) => [k, a[i]]).reverse().map(([k, v]) => `<span><i class="u-sw u-a${k + 1}"></i>${esc(L.ages[k])}: <b>${num(v)}</b></span>`).join('')
          + `<span>${L.total}: <b>${num(tot[i])}</b></span>`
        : `<span>${L.computers}: <b>${num(tot[i])}</b></span>`;
      tip.innerHTML = head + body;
      tip.hidden = false;
      guide.setAttribute('x1', f1(x(i)));
      guide.setAttribute('x2', f1(x(i)));
      guide.setAttribute('visibility', 'visible');
      const left = (x(i) / W) * r.width;
      tip.style.left = `${Math.min(Math.max(0, left - tip.offsetWidth / 2), r.width - tip.offsetWidth)}px`;
    });
  }
})();
