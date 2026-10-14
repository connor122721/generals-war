(() => {
  "use strict";

  const ERAS = [
    { id: "all", label: "All eras", sub: "every battle", from: null, to: null },
    { id: "ancient", label: "Ancient", sub: "to 499", from: -5000, to: 499 },
    { id: "medieval", label: "Medieval", sub: "500–1499", from: 500, to: 1499 },
    { id: "early", label: "Early modern", sub: "1500–1799", from: 1500, to: 1799 },
    { id: "c19", label: "Long 19th c.", sub: "1800–1913", from: 1800, to: 1913 },
    { id: "ww", label: "World wars", sub: "1914–1945", from: 1914, to: 1945 },
    { id: "modern", label: "Since 1945", sub: "1946–today", from: 1946, to: 9999 },
  ];
  // The timeline gives each era an equal slice so ancient history isn't squashed.
  const SEGMENTS = [[-1000, 500], [500, 1500], [1500, 1800], [1800, 1914], [1914, 1946], [1946, 2030]];
  const KIND_LABELS = ["Battles", "Sieges", "Naval", "Operations", "Campaigns"];
  const THUMB = "https://upload.wikimedia.org/wikipedia/";
  const PAGE = 50;

  const state = { era: "all", from: null, to: null, kinds: new Set([0, 1, 2, 3, 4]), min: 2,
                  credit: "full", sort: "war", q: "", sel: null, shown: PAGE,
                  view: "rank", sx: "n", sy: "war", dchart: "career" };
  let B = [], G = [], META = {}, byGeneral = [], ranked = [], eligible = [], stats = new Map();
  let mainPlot = null;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const wiki = (t) => "https://en.wikipedia.org/wiki/" + encodeURIComponent(t.replace(/ /g, "_"));
  const year = (y) => (y == null ? "?" : y < 0 ? `${-y} BC` : `${y}`);
  const signed = (v, d = 2) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
  const fmtN = (n) => (n == null ? "?" : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n));

  // ------------------------------------------------------------------ load
  Promise.all(["battles", "generals", "meta"].map((f) => fetch(`data/${f}.json`).then((r) => {
    if (!r.ok) throw new Error(`${f}.json: HTTP ${r.status}`);
    return r.json();
  }))).then(([b, g, m]) => {
    B = b.rows; G = g.rows; META = m;
    byGeneral = G.map(() => []);
    B.forEach((row, i) => { for (const id of row[7]) byGeneral[id].push(i); for (const id of row[8]) byGeneral[id].push(i); });
    readHash();
    setupControls();
    renderMethod();
    $("stamp").innerHTML = (META.source && /preview/i.test(META.source) ? `<span class="preview">${esc(META.source)}.</span> ` : "")
      + `${META.battles.toLocaleString()} battles, ${META.generals.toLocaleString()} commanders. Updated ${esc(META.updated)}.`;
    update();
    setView(state.view);
    if (state.sel != null) showDetail(state.sel, false);
  }).catch((e) => {
    $("stamp").textContent = `Couldn't load the rankings data (${e.message}). Run the scraper to create site/data, then reload.`;
  });

  // -------------------------------------------------------------- filters
  function inRange(y) {
    if (state.from == null && state.to == null) return true;
    if (y == null) return false;
    return (state.from == null || y >= state.from) && (state.to == null || y <= state.to);
  }
  const passes = (b) => state.kinds.has(b[2]) && inRange(b[1]);

  function compute() {
    stats = new Map();
    const shared = state.credit === "shared";
    for (const b of B) {
      if (!passes(b)) continue;
      const o1 = b[3], p1 = b[4];
      for (const [ids, o, p] of [[b[7], o1, p1], [b[8], 1 - o1, 1 - p1]]) {
        if (!ids.length) continue;
        const w = (o - p) / (shared ? ids.length : 1);
        for (const id of ids) {
          let s = stats.get(id);
          if (!s) stats.set(id, (s = { n: 0, w: 0, l: 0, d: 0, war: 0, first: b[1], last: b[1],
                                       psum: 0, ysum: 0, yn: 0, lsz: 0, nsz: 0, lrat: 0, nrat: 0 }));
          s.n++; s.war += w; s.psum += p;
          const own = ids === b[7] ? b[5] : b[6], foe = ids === b[7] ? b[6] : b[5];
          if (own) { s.lsz += Math.log(own); s.nsz++; }
          if (own && foe) { s.lrat += Math.log(own / foe); s.nrat++; }
          if (b[1] != null) { s.ysum += b[1]; s.yn++; }
          if (o === 1) s.w++; else if (o === 0) s.l++; else s.d++;
          if (b[1] != null) {
            if (s.first == null || b[1] < s.first) s.first = b[1];
            if (s.last == null || b[1] > s.last) s.last = b[1];
          }
        }
      }
    }
    const q = state.q.trim().toLowerCase();
    let ids = [...stats.keys()].filter((id) => stats.get(id).n >= state.min);
    const key = { war: (s) => -s.war, worst: (s) => s.war, avg: (s) => -s.war / s.n, n: (s) => -s.n - s.war / 1000 }[state.sort];
    ids.sort((a, b) => key(stats.get(a)) - key(stats.get(b)));
    ranked = ids.map((id, i) => ({ id, rank: i + 1 }));
    eligible = ranked;
    if (q) ranked = ranked.filter((r) => G[r.id][0].toLowerCase().includes(q));
  }

  // ------------------------------------------------------------- rendering
  function update(keepShown) {
    if (!keepShown) state.shown = PAGE;
    compute();
    renderList();
    renderHist();
    if (state.view === "scatter") renderScatter();
    writeHash();
    if (state.sel != null) showDetail(state.sel, false);
  }

  function renderList() {
    const list = $("list");
    const rows = ranked.slice(0, state.shown);
    const value = (s) => (state.sort === "avg" ? s.war / s.n : s.war);
    const max = Math.max(1e-9, ...rows.map((r) => Math.abs(value(stats.get(r.id)))));
    list.innerHTML = rows.map(({ id, rank }) => {
      const s = stats.get(id), g = G[id], v = value(s);
      const pct = Math.min(50, (Math.abs(v) / max) * 50);
      const cls = v >= 0 ? "pos" : "neg";
      const span = s.first == null ? "" : s.first === s.last ? year(s.first) : `${year(s.first)}–${year(s.last)}`;
      const rec = `${s.w}–${s.l}${s.d ? "–" + s.d : ""}`;
      return `<li><button class="row" data-id="${id}" ${state.sel === id ? 'aria-current="true"' : ""}>
        <span class="rank">${rank}</span>
        <span class="who"><b>${esc(g[0])}</b><small>${esc(span)}<span class="r"> · ${rec}</span>${g[1] ? " · " + esc(g[1]) : ""}</small></span>
        <span class="rec" title="wins–losses–draws">${rec}</span>
        <span class="meter" aria-label="${state.sort === "avg" ? "WAR per battle" : "WAR"} ${signed(v)}"><span class="axis"></span>
          <span class="fill ${cls}" style="width:${pct}%"></span><span class="val ${cls}">${signed(v)}</span></span>
      </button></li>`;
    }).join("");
    $("more").hidden = ranked.length <= state.shown;
    $("more").textContent = `Show ${Math.min(PAGE, ranked.length - state.shown)} more of ${(ranked.length - state.shown).toLocaleString()}`;
    $("empty").hidden = ranked.length > 0;
  }


  // ------------------------------------------------------------- scatter
  const pct = (v) => Math.round(v * 100) + "%";
  const AXES = {
    n: { label: "Battles fought", log: true, get: (s) => s.n, fmt: (v) => String(Math.round(v)) },
    war: { label: "Total WAR", get: (s) => s.war, fmt: (v) => signed(v, Math.abs(v) < 10 ? 1 : 0), ref: 0 },
    avg: { label: "WAR per battle", get: (s) => s.war / s.n, fmt: (v) => signed(v, 2), ref: 0 },
    win: { label: "Win rate (draws count half)", get: (s) => (s.w + s.d / 2) / s.n, fmt: pct, ref: 0.5 },
    odds: { label: "Average general's win chance", get: (s) => s.psum / s.n, fmt: pct, ref: 0.5 },
    year: { label: "Career midpoint (year)", get: (s) => (s.yn ? s.ysum / s.yn : NaN), fmt: (v) => year(Math.round(v)) },
    size: { label: "Typical army size", log: true, get: (s) => (s.nsz ? Math.exp(s.lsz / s.nsz) : NaN), fmt: fmtN },
    ratio: { label: "Typical force ratio (own ÷ enemy)", log: true, get: (s) => (s.nrat ? Math.exp(s.lrat / s.nrat) : NaN),
             fmt: (v) => (v >= 1 ? (v < 10 ? v.toFixed(1) : Math.round(v)) + "×" : "1:" + (1 / v < 10 ? (1 / v).toFixed(1) : Math.round(1 / v))), ref: 1 },
  };
  const PRESETS = [
    { id: "exp", label: "Score vs experience", x: "n", y: "war" },
    { id: "odds", label: "Beating the odds", x: "odds", y: "win" },
    { id: "hist", label: "Across history", x: "year", y: "war" },
    { id: "size", label: "Outnumbered or not", x: "ratio", y: "avg" },
  ];

  function renderScatter() {
    if (!mainPlot) {
      mainPlot = new window.Scatter($("plot"), {
        tooltip: (p) => generalTip(p.id),
        onClick: (p) => { showDetail(p.id); renderScatter(); },
      });
    }
    const ax = AXES[state.sx], ay = AXES[state.sy];
    const q = state.q.trim().toLowerCase();
    const pts = [];
    for (const { id } of eligible) {
      const s = stats.get(id);
      const x = ax.get(s), y = ay.get(s);
      const match = !q || G[id][0].toLowerCase().includes(q);
      // spread whole-number battle counts a little so stacked dots stay visible
      const jit = (k) => (k === "n" ? 1 + (((id * 2654435761) % 1000) / 1000 - 0.5) * 0.12 : 1);
      pts.push({ id, x: x * jit(state.sx), y: y * jit(state.sy), cls: s.war > 0.0001 ? "pos" : s.war < -0.0001 ? "neg" : "draw", dim: !match,
                 ring: id === state.sel, name: G[id][0] });
    }
    const missing = pts.filter((p) => !Number.isFinite(p.x) || !Number.isFinite(p.y)).length;
    // Direct-label a handful of standouts: highest and lowest on the y axis, plus search hits.
    const ok = pts.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y) && !p.dim);
    const byY = ok.slice().sort((a, b) => b.y - a.y);
    const lab = new Set([...byY.slice(0, 6), ...byY.slice(-2)]);
    if (q && ok.length <= 8) ok.forEach((p) => lab.add(p));
    lab.forEach((p) => { p.label = true; });
    pts.forEach((p) => { if (!p.label && !p.ring) p.name = ""; });
    mainPlot.set(pts, {
      xLabel: ax.label, yLabel: ay.label, xLog: ax.log, yLog: ay.log, xFmt: ax.fmt, yFmt: ay.fmt, yRef: ay.ref,
      diag: (state.sx === "odds" && state.sy === "win") || (state.sx === "win" && state.sy === "odds"),
      keepView: true,
      legend: [{ cls: "pos", label: "Positive WAR" }, { cls: "neg", label: "Negative WAR" }],
      note: `${ok.length.toLocaleString()} commanders with ${state.min}+ battles${missing ? `; ${missing.toLocaleString()} without troop numbers not shown` : ""}. ${matchMedia("(hover: hover)").matches ? " Drag to zoom." : " Tap a dot to open it."}`,
    });
    document.querySelectorAll("#presets button").forEach((b) => {
      const p = PRESETS.find((x) => x.id === b.dataset.p);
      b.setAttribute("aria-pressed", String(p.x === state.sx && p.y === state.sy));
    });
  }

  function generalTip(id) {
    const s = stats.get(id), g = G[id];
    if (!s) return esc(g[0]);
    const span = s.first == null ? "" : s.first === s.last ? year(s.first) : `${year(s.first)}–${year(s.last)}`;
    const extra = [state.sx, state.sy].filter((k) => !["war", "n"].includes(k))
      .map((k) => { const v = AXES[k].get(s); return Number.isFinite(v) ? `<span>${AXES[k].label}: <b>${AXES[k].fmt(v)}</b></span>` : ""; }).join("");
    return `<strong>${esc(g[0])}</strong><span>${esc(span)}</span>
      <span>WAR <b>${signed(s.war)}</b> over ${s.n} battle${s.n > 1 ? "s" : ""} (${s.w}–${s.l}${s.d ? "–" + s.d : ""})</span>${extra}`;
  }

  function setView(v) {
    state.view = v;
    document.querySelectorAll("#views button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.v === v)));
    $("rank-view").hidden = v !== "rank";
    $("scatter-view").hidden = v !== "scatter";
    if (v === "scatter") renderScatter();
    writeHash();
  }

  function xOf(y) {
    const w = 600 / SEGMENTS.length;
    let i = SEGMENTS.findIndex(([a, b]) => y < b);
    if (i < 0) i = SEGMENTS.length - 1;
    const [a, b] = SEGMENTS[i];
    return i * w + (Math.max(a, Math.min(b, y)) - a) / (b - a) * w;
  }

  function renderHist() {
    const per = 30, w = 600 / SEGMENTS.length, bw = w / per;
    const counts = new Array(SEGMENTS.length * per).fill(0);
    for (const b of B) {
      if (b[1] == null || !state.kinds.has(b[2])) continue;
      counts[Math.min(counts.length - 1, Math.floor(xOf(b[1]) / bw))]++;
    }
    const max = Math.max(1, ...counts);
    let svg = "";
    counts.forEach((c, i) => {
      if (!c) return;
      const h = 4 + 56 * Math.sqrt(c / max);
      const seg = SEGMENTS[Math.floor(i / per)];
      const y0 = seg[0] + ((i % per) / per) * (seg[1] - seg[0]);
      const on = state.from == null && state.to == null ? true : inRange(Math.round(y0 + (seg[1] - seg[0]) / per / 2));
      svg += `<rect class="bar${on ? " on" : ""}" x="${(i * bw + 0.3).toFixed(1)}" y="${(64 - h).toFixed(1)}" width="${(bw - 0.6).toFixed(2)}" height="${h.toFixed(1)}"></rect>`;
    });
    for (let i = 1; i < SEGMENTS.length; i++) svg += `<line class="sep" x1="${i * w}" x2="${i * w}" y1="0" y2="64"></line>`;
    $("hist").innerHTML = svg;
  }

  function showDetail(id, scroll = true) {
    state.sel = id;
    const g = G[id], el = $("detail");
    const all = byGeneral[id].slice().sort((a, b) => (B[a][1] ?? 1e9) - (B[b][1] ?? 1e9));
    const shared = state.credit === "shared";
    let cum = 0, w = 0, l = 0, d = 0, n = 0;
    const pts = [], odds = [];
    const items = all.map((i) => {
      const b = B[i];
      const side = b[7].includes(id) ? 0 : 1;
      const mine = side ? b[8] : b[7], theirs = side ? b[7] : b[8];
      const o = side ? 1 - b[3] : b[3], p = side ? 1 - b[4] : b[4];
      const v = (o - p) / (shared ? mine.length : 1);
      const ok = passes(b);
      if (ok) {
        cum += v; n++;
        if (o === 1) w++; else if (o === 0) l++; else d++;
        pts.push({ v: cum, o });
        if (b[1] != null) odds.push({ id: i, x: b[1], y: p, cls: o === 1 ? "pos" : o === 0 ? "neg" : "draw",
                                       shape: o === 0.5 ? "ring" : "dot", v, theirs, name: "" });
      }
      const res = o === 1 ? "W" : o === 0 ? "L" : "D";
      const vs = theirs.length ? "vs " + theirs.slice(0, 4).map((t) => `<button data-id="${t}">${esc(G[t][0])}</button>`).join(", ") + (theirs.length > 4 ? ` +${theirs.length - 4}` : "") : "";
      const troops = b[5] && b[6] ? `${fmtN(side ? b[6] : b[5])} vs ${fmtN(side ? b[5] : b[6])} troops · ` : "";
      return `<li class="${ok ? "" : "out"}"><span class="by">${year(b[1])}</span>
        <span class="bt"><span class="tag ${res}">${res}</span><a href="${wiki(b[0])}" target="_blank" rel="noopener">${esc(b[0])}</a>
          <span class="vs">${vs}</span><span class="odds">${troops}average general wins ${Math.round(p * 100)}%</span></span>
        <span class="bw ${v >= 0 ? "pos" : "neg"}">${signed(v)}</span></li>`;
    });
    const thumb = g[2] ? `<img class="portrait" src="${g[2].startsWith("http") ? esc(g[2]) : THUMB + esc(g[2])}" alt="">`
      : `<span class="portrait" aria-hidden="true">${esc(g[0].split(/\s+/).filter((s) => /^[A-Z\u00C0-\u00DD]/.test(s)).slice(0, 2).map((s) => s[0]).join(""))}</span>`;
    const outside = all.length - n;
    el.innerHTML = `<button type="button" class="back" id="back">Back to rankings</button><div class="d-top">${thumb}<div><h2>${esc(g[0])}</h2>
        <p>${esc(g[1] || "")}${g[3] && !(g[1] || "").includes(g[3]) ? " (" + esc(g[3]) + ")" : ""}</p>
        <p><a href="${wiki(g[0])}" target="_blank" rel="noopener">Wikipedia article</a></p></div></div>
      <div class="stats"><div><b>${signed(cum)}</b><span>WAR</span></div><div><b>${n ? signed(cum / n) : "–"}</b><span>per battle</span></div>
        <div><b>${w}–${l}${d ? "–" + d : ""}</b><span>won–lost${d ? "–drawn" : ""}</span></div><div><b>${n}</b><span>battles</span></div></div>
      <div class="dtabs" role="tablist" aria-label="Career chart">
        <button type="button" role="tab" data-c="career" aria-selected="${state.dchart === "career"}">Running total</button>
        <button type="button" role="tab" data-c="odds" aria-selected="${state.dchart === "odds"}">Odds faced</button></div>
      ${state.dchart === "career" ? career(pts) : '<div id="dplot" class="dplot"></div>'}
      <p class="cap">${state.dchart === "career" ? "Running total of WAR, one point per battle in the selected period"
        : "Each battle by year and the chance an average general would have won it. Wins low on the chart are upsets"}${outside ? `; ${outside} battle${outside > 1 ? "s" : ""} outside the period are dimmed below` : ""}.</p>
      <ol class="battles">${items.join("")}</ol>`;
    if (state.dchart === "odds") {
      const plot = new window.Scatter($("dplot"), {
        tooltip: (p) => `<strong>${esc(B[p.id][0])}</strong><span>${year(B[p.id][1])} · ${p.cls === "pos" ? "won" : p.cls === "neg" ? "lost" : "drawn"}</span>
          ${p.theirs.length ? `<span>vs ${p.theirs.slice(0, 3).map((t) => esc(G[t][0])).join(", ")}</span>` : ""}
          <span>Average general wins ${pct(p.y)} · WAR <b>${signed(p.v)}</b></span>`,
        onClick: (p) => window.open(wiki(B[p.id][0]), "_blank", "noopener"),
      });
      plot.set(odds, { xLabel: "Year", yLabel: "Avg. general's chance", xFmt: (v) => year(Math.round(v)),
        yFmt: pct, yRef: 0.5, yMin: 0.45, yMax: 0.55, height: 230, empty: "No dated battles in this period.",
        legend: [{ cls: "pos", label: "Won" }, { cls: "neg", label: "Lost" }, { cls: "draw", label: "Drawn", shape: "ring" }],
      });
    }
    document.querySelectorAll(".row").forEach((r) => r.toggleAttribute("aria-current", +r.dataset.id === id));
    writeHash();
    if (scroll && window.matchMedia("(max-width: 860px)").matches) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function career(pts) {
    if (!pts.length) return "";
    const W = 400, H = 150, pad = 8;
    const vals = [0, ...pts.map((p) => p.v)];
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const x = (i) => pad + (i / Math.max(1, pts.length)) * (W - 2 * pad);
    const y = (v) => pad + (1 - (v - lo) / span) * (H - 2 * pad - 12);
    let d = `M${x(0)},${y(0)}`;
    pts.forEach((p, i) => { d += ` L${x(i + 1)},${y(p.v)}`; });
    const r = pts.length > 60 ? 1.6 : 3;
    const dots = pts.map((p, i) => `<circle class="dot ${p.o === 1 ? "pos" : p.o === 0 ? "neg" : "draw"}" cx="${x(i + 1)}" cy="${y(p.v)}" r="${r}"></circle>`).join("");
    return `<svg class="career" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Cumulative WAR across career">
      <line class="zero" x1="${pad}" x2="${W - pad}" y1="${y(0)}" y2="${y(0)}"></line>
      <path class="path" d="${d}"></path>${dots}
      <text x="${pad}" y="${H - 2}">first battle</text><text x="${W - pad}" y="${H - 2}" text-anchor="end">last</text></svg>`;
  }

  function renderMethod() {
    const m = META.model || {};
    const p2 = m.b != null ? Math.round(100 / (1 + Math.exp(-m.b * Math.log(2)))) : null;
    const rows = (m.calibration || []).map((c) => `<tr><td>${esc(c.ratio)}</td><td>${c.n.toLocaleString()}</td><td>${Math.round(c.observed * 100)}%</td><td>${Math.round(c.model * 100)}%</td></tr>`).join("");
    $("method-body").innerHTML = `
      <p>Baseball's <em>wins above replacement</em> asks how many more games a team won with a player than it would have with an ordinary substitute. Here the substitute is an average general handed the same army.</p>
      <p>For each battle the scraper reads the Wikipedia infobox: who fought, how many troops each side had, and who won. The chance that an average general wins is modelled from the force ratio alone:</p>
      <p class="formula">P(win) = 1 / (1 + (enemy ÷ own)<sup>b</sup>) &nbsp;&nbsp; WAR = result − P(win)</p>
      <p>A win counts 1, a draw ½, a loss 0. If either side's strength is missing, the average general is given even odds. Career WAR is the sum over battles; “split among co-commanders” divides each side's credit by the number of commanders listed.</p>
      ${m.b != null ? `<p>Fitted on ${m.n.toLocaleString()} battles with both strengths known, b = ${m.b} (±${m.se}). Doubling your army only lifts an average general's chances to about ${p2}%. Bigger armies win less often than you'd think, largely because outnumbered generals usually choose to fight only when they have some other edge.</p>` : ""}
      ${rows ? `<table class="calib"><thead><tr><th>Larger side's advantage</th><th>Battles</th><th>Larger side won</th><th>Model</th></tr></thead><tbody>${rows}</tbody></table>` : ""}
      <p>Known gaps: commanders without a Wikipedia article are skipped; infobox results like “Coalition victory” are matched to a side automatically and occasionally wrongly; wars and long campaigns with dozens of commanders are excluded; and strategy, logistics and politics are invisible to this score.</p>`;
  }

  // -------------------------------------------------------------- controls
  function setEra(id, from, to) {
    state.era = id;
    const e = ERAS.find((x) => x.id === id);
    state.from = e ? e.from : from; state.to = e ? e.to : to;
    document.querySelectorAll("#eras button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.era === id)));
    $("all-eras").hidden = id === "all";
    $("from").value = state.from != null && id !== "all" ? Math.max(state.from, -3000) : "";
    $("to").value = state.to != null && id !== "all" ? Math.min(state.to, new Date().getFullYear()) : "";
    update();
  }

  function setupControls() {
    $("eras").innerHTML = ERAS.filter((e) => e.id !== "all").map((e) => `<button type="button" data-era="${e.id}" aria-pressed="${e.id === state.era}">${e.label}<small>${e.sub}</small></button>`).join("");
    $("eras").addEventListener("click", (ev) => {
      const b = ev.target.closest("button");
      if (b) setEra(state.era === b.dataset.era ? "all" : b.dataset.era);   // click again to clear
    });
    $("all-eras").addEventListener("click", () => setEra("all"));
    $("hist").addEventListener("click", (ev) => {
      const r = $("hist").getBoundingClientRect();
      const seg = Math.min(SEGMENTS.length - 1, Math.floor(((ev.clientX - r.left) / r.width) * SEGMENTS.length));
      setEra(state.era === ERAS[seg + 1].id ? "all" : ERAS[seg + 1].id);
    });
    $("custom").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const f = $("from").value === "" ? null : +$("from").value, t = $("to").value === "" ? null : +$("to").value;
      setEra(f == null && t == null ? "all" : "custom", f, t);
    });
    $("kinds").innerHTML += KIND_LABELS.map((k, i) => `<label><input type="checkbox" value="${i}" ${state.kinds.has(i) ? "checked" : ""}>${k}</label>`).join("");
    $("kinds").addEventListener("change", (ev) => {
      const v = +ev.target.value; ev.target.checked ? state.kinds.add(v) : state.kinds.delete(v); update();
    });
    $("q").addEventListener("input", (ev) => { state.q = ev.target.value; update(); });
    for (const [elId, key, num] of [["sort", "sort"], ["min", "min", true], ["credit", "credit"]]) {
      $(elId).value = String(state[key]);
      $(elId).addEventListener("change", (ev) => { state[key] = num ? +ev.target.value : ev.target.value; update(); });
    }
    $("views").addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (b) setView(b.dataset.v); });
    const axOpts = Object.entries(AXES).map(([k, a]) => `<option value="${k}">${a.label}</option>`).join("");
    for (const [elId, key] of [["ax-x", "sx"], ["ax-y", "sy"]]) {
      $(elId).innerHTML = axOpts; $(elId).value = state[key];
      $(elId).addEventListener("change", (ev) => { state[key] = ev.target.value; renderScatter(); });
    }
    $("presets").innerHTML = PRESETS.map((p) => `<button type="button" data-p="${p.id}">${p.label}</button>`).join("");
    $("presets").addEventListener("click", (ev) => {
      const b = ev.target.closest("button"); if (!b) return;
      const p = PRESETS.find((x) => x.id === b.dataset.p);
      state.sx = p.x; state.sy = p.y; $("ax-x").value = p.x; $("ax-y").value = p.y; renderScatter();
    });
    $("swap").addEventListener("click", () => {
      [state.sx, state.sy] = [state.sy, state.sx]; $("ax-x").value = state.sx; $("ax-y").value = state.sy; renderScatter();
    });
    $("list").addEventListener("click", (ev) => { const b = ev.target.closest(".row"); if (b) showDetail(+b.dataset.id); });
    $("detail").addEventListener("click", (ev) => {
      const tab = ev.target.closest(".dtabs button");
      if (tab) { state.dchart = tab.dataset.c; showDetail(state.sel, false); return; }
      if (ev.target.id === "back") { const cur = document.querySelector('.row[aria-current="true"]') || $("list"); cur.scrollIntoView({ block: "center" }); return; }
      const b = ev.target.closest("button[data-id]"); if (b) showDetail(+b.dataset.id); });
    $("more").addEventListener("click", () => { state.shown += PAGE; renderList(); });
    document.querySelectorAll("#eras button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.era === state.era)));
    $("all-eras").hidden = state.era === "all";
    if (state.era === "custom") { $("from").value = state.from ?? ""; $("to").value = state.to ?? ""; }
  }

  // --------------------------------------------------------------- url hash
  function writeHash() {
    const p = new URLSearchParams();
    if (state.era !== "all") p.set("era", state.era === "custom" ? `${state.from ?? ""}..${state.to ?? ""}` : state.era);
    if (state.sel != null) p.set("g", G[state.sel][0]);
    if (state.credit !== "full") p.set("credit", state.credit);
    if (state.sort !== "war") p.set("sort", state.sort);
    if (state.view === "scatter") p.set("view", `${state.sx}-${state.sy}`);
    const h = p.toString();
    try { history.replaceState(null, "", h ? "#" + h : location.pathname + location.search); } catch (e) { /* sandboxed preview */ }
  }

  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const era = p.get("era");
    if (era) {
      const e = ERAS.find((x) => x.id === era);
      if (e) { state.era = e.id; state.from = e.from; state.to = e.to; }
      else if (era.includes("..")) {
        const [f, t] = era.split("..");
        state.era = "custom"; state.from = f === "" ? null : +f; state.to = t === "" ? null : +t;
      }
    }
    if (p.get("credit") === "shared") state.credit = "shared";
    if (["avg", "n", "worst"].includes(p.get("sort"))) state.sort = p.get("sort");
    const v = p.get("view");
    if (v) { const [x, y] = v.split("-"); if (AXES[x] && AXES[y]) { state.view = "scatter"; state.sx = x; state.sy = y; } }
    const g = p.get("g");
    if (g) { const i = G.findIndex((r) => r[0] === g); if (i >= 0) state.sel = i; }
  }
})();
