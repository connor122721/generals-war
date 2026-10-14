/* Small dependency-free interactive scatterplot on <canvas>.
 * Hover for a tooltip, click a point to select it, drag a box to zoom (mouse),
 * double-click or "Reset zoom" to zoom back out. Colors come from CSS tokens.
 */
(function () {
  "use strict";

  const css = (el, name) => getComputedStyle(el).getPropertyValue(name).trim();

  function niceTicks(lo, hi, count) {
    if (!(hi > lo)) return [lo];
    const step0 = (hi - lo) / count;
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const err = step0 / mag;
    const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  function logTicks(lo, hi) {
    const out = [];
    const a = Math.floor(Math.log10(lo)), b = Math.ceil(Math.log10(hi));
    const span = b - a;
    const mults = span > 4 ? [1] : span > 2 ? [1, 3] : [1, 2, 5];
    for (let e = a; e <= b; e++) for (const m of mults) {
      const v = m * Math.pow(10, e);
      if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v);
    }
    return out;
  }

  class Scatter {
    constructor(root, opts = {}) {
      this.root = root;
      this.opts = opts;
      root.classList.add("sc");
      root.innerHTML = `<div class="sc-legend"></div><div class="sc-stage"><canvas></canvas>
        <div class="sc-tip" hidden></div><div class="sc-box" hidden></div>
        <button type="button" class="sc-reset" hidden>Reset zoom</button></div>`;
      this.legendEl = root.querySelector(".sc-legend");
      this.stage = root.querySelector(".sc-stage");
      this.canvas = root.querySelector("canvas");
      this.tip = root.querySelector(".sc-tip");
      this.box = root.querySelector(".sc-box");
      this.resetBtn = root.querySelector(".sc-reset");
      this.ctx = this.canvas.getContext("2d");
      this.points = [];
      this.view = null; // zoomed domain or null
      this.hover = null;
      this.cfg = {};
      this._bind();
      if (window.ResizeObserver) new ResizeObserver(() => this.draw()).observe(this.stage);
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      mq.addEventListener && mq.addEventListener("change", () => this.draw());
    }

    /* points: [{x, y, id, cls, label?, ring?, dim?}]
       cfg: {xLabel, yLabel, xLog, yLog, xFmt, yFmt, height, legend:[{cls,label,shape}], labelTop, keepView} */
    set(points, cfg) {
      const sameAxes = this.cfg.xLabel === cfg.xLabel && this.cfg.yLabel === cfg.yLabel && this.cfg.xLog === cfg.xLog && this.cfg.yLog === cfg.yLog;
      this.points = points.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y) && (!cfg.xLog || p.x > 0) && (!cfg.yLog || p.y > 0));
      this.cfg = cfg;
      if (!sameAxes || !cfg.keepView) this.view = null;
      this.legendEl.innerHTML = (cfg.legend || []).map((l) =>
        `<span><i class="sc-key ${l.cls}${l.shape === "ring" ? " ring" : ""}"></i>${l.label}</span>`).join("")
        + (cfg.note ? `<span class="sc-note">${cfg.note}</span>` : "");
      this.draw();
    }

    _domain() {
      const c = this.cfg, pts = this.points;
      if (this.view) return this.view;
      if (!pts.length) return { x0: 0, x1: 1, y0: 0, y1: 1 };
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const p of pts) { x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); y0 = Math.min(y0, p.y); y1 = Math.max(y1, p.y); }
      const pad = (a, b, log) => {
        if (log) return [a / 1.25, b * 1.25];
        const d = (b - a) || 20;
        return [a - d * 0.05, b + d * 0.05];
      };
      [x0, x1] = pad(x0, x1, c.xLog); [y0, y1] = pad(y0, y1, c.yLog);
      if (c.yMin != null) y0 = Math.min(y0, c.yMin);
      if (c.yMax != null) y1 = Math.max(y1, c.yMax);
      return { x0, x1, y0, y1 };
    }

    _scales() {
      const d = this._domain(), c = this.cfg;
      const W = this.w, H = this.h, m = this.m;
      const lin = (a, b, r0, r1) => (v) => r0 + ((v - a) / (b - a)) * (r1 - r0);
      const lg = (a, b, r0, r1) => (v) => r0 + ((Math.log(v) - Math.log(a)) / (Math.log(b) - Math.log(a))) * (r1 - r0);
      const sx = (c.xLog ? lg : lin)(d.x0, d.x1, m.l, W - m.r);
      const sy = (c.yLog ? lg : lin)(d.y0, d.y1, H - m.b, m.t);
      const ix = c.xLog ? (px) => Math.exp(Math.log(d.x0) + ((px - m.l) / (W - m.r - m.l)) * (Math.log(d.x1) - Math.log(d.x0)))
        : (px) => d.x0 + ((px - m.l) / (W - m.r - m.l)) * (d.x1 - d.x0);
      const iy = c.yLog ? (py) => Math.exp(Math.log(d.y0) + ((H - m.b - py) / (H - m.b - m.t)) * (Math.log(d.y1) - Math.log(d.y0)))
        : (py) => d.y0 + ((H - m.b - py) / (H - m.b - m.t)) * (d.y1 - d.y0);
      return { d, sx, sy, ix, iy };
    }

    draw() {
      const W = this.stage.clientWidth || 600;
      const H = this.cfg.height || Math.max(320, Math.min(480, Math.round(W * 0.66)));
      const dpr = window.devicePixelRatio || 1;
      this.w = W; this.h = H;
      this.m = { l: 52, r: 14, t: 12, b: 42 };
      this.canvas.width = W * dpr; this.canvas.height = H * dpr;
      this.canvas.style.height = H + "px";
      const g = this.ctx; g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, W, H);
      const col = {
        ink: css(this.root, "--ink"), ink2: css(this.root, "--ink-2"), line: css(this.root, "--line"),
        surface: css(this.root, "--paper"), pos: css(this.root, "--mk-pos"), neg: css(this.root, "--mk-neg"),
        draw: css(this.root, "--mk-draw"), sel: css(this.root, "--ink"),
      };
      this.col = col;
      const c = this.cfg, m = this.m;
      const { d, sx, sy } = this._scales();
      this.resetBtn.hidden = !this.view;

      // grid + axes
      g.font = "500 11px " + (css(this.root, "--display") || "sans-serif");
      g.lineWidth = 1;
      const xt = c.xLog ? logTicks(d.x0, d.x1) : niceTicks(d.x0, d.x1, Math.max(3, Math.floor((W - 80) / 90)));
      const yt = c.yLog ? logTicks(d.y0, d.y1) : niceTicks(d.y0, d.y1, Math.max(3, Math.floor(H / 70)));
      g.strokeStyle = col.line; g.fillStyle = col.ink2; g.globalAlpha = 0.55;
      g.beginPath();
      for (const t of yt) { const y = Math.round(sy(t)) + 0.5; g.moveTo(m.l, y); g.lineTo(W - m.r, y); }
      for (const t of xt) { const x = Math.round(sx(t)) + 0.5; g.moveTo(x, m.t); g.lineTo(x, H - m.b); }
      g.stroke(); g.globalAlpha = 1;
      g.textAlign = "right"; g.textBaseline = "middle";
      for (const t of yt) g.fillText((c.yFmt || String)(t), m.l - 6, sy(t));
      g.textAlign = "center"; g.textBaseline = "top";
      for (const t of xt) g.fillText((c.xFmt || String)(t), sx(t), H - m.b + 6);
      // zero / reference line
      if (c.yRef != null && d.y0 < c.yRef && d.y1 > c.yRef) {
        g.strokeStyle = col.ink2; g.setLineDash([4, 3]); g.beginPath();
        const y = Math.round(sy(c.yRef)) + 0.5; g.moveTo(m.l, y); g.lineTo(W - m.r, y); g.stroke(); g.setLineDash([]);
      }
      // y = x reference (e.g. win rate vs expected win rate)
      if (c.diag) {
        const lo = Math.max(d.x0, d.y0), hi = Math.min(d.x1, d.y1);
        if (hi > lo) {
          g.strokeStyle = col.ink2; g.setLineDash([4, 3]); g.beginPath();
          g.moveTo(sx(lo), sy(lo)); g.lineTo(sx(hi), sy(hi)); g.stroke(); g.setLineDash([]);
          g.fillStyle = col.ink2; g.textAlign = "right"; g.textBaseline = "bottom";
          g.fillText("as expected", sx(hi) - 4, sy(hi) - 2);
        }
      }
      // axis titles
      g.fillStyle = col.ink2; g.font = "600 12px " + (css(this.root, "--display") || "sans-serif");
      g.textAlign = "center"; g.textBaseline = "bottom";
      g.fillText(c.xLabel || "", m.l + (W - m.l - m.r) / 2, H - 4);
      g.save(); g.translate(12, m.t + (H - m.t - m.b) / 2); g.rotate(-Math.PI / 2);
      g.textBaseline = "middle"; g.fillText(c.yLabel || "", 0, 0); g.restore();

      // points
      g.save();
      g.beginPath(); g.rect(m.l, m.t, W - m.l - m.r, H - m.t - m.b); g.clip();
      const r = this.points.length > 3000 ? 3 : 4;
      this.r = r;
      const order = this.points.slice().sort((a, b) => (a.ring ? 1 : 0) - (b.ring ? 1 : 0) || (a.dim ? -1 : 0) - (b.dim ? -1 : 0));
      for (const p of order) {
        p.px = sx(p.x); p.py = sy(p.y);
        const color = col[p.cls] || col.ink2;
        g.globalAlpha = p.dim ? 0.18 : 0.85;
        g.beginPath(); g.arc(p.px, p.py, r, 0, Math.PI * 2);
        if (p.shape === "ring") { g.strokeStyle = color; g.lineWidth = 2; g.stroke(); }
        else { g.fillStyle = color; g.fill(); g.strokeStyle = col.surface; g.lineWidth = 1; g.stroke(); }
      }
      g.globalAlpha = 1;
      // selected / highlighted rings + direct labels
      const labelled = this.points.filter((p) => p.ring || p.label);
      const boxes = [];
      g.font = "600 12px " + (css(this.root, "--display") || "sans-serif");
      g.textBaseline = "middle"; g.textAlign = "left";
      for (const p of labelled) {
        if (p.ring) {
          g.strokeStyle = col.sel; g.lineWidth = 2;
          g.beginPath(); g.arc(p.px, p.py, r + 4, 0, Math.PI * 2); g.stroke();
        }
        const text = p.name || "";
        if (!text) continue;
        const tw = g.measureText(text).width;
        let x = p.px + r + 6; if (x + tw > W - m.r) x = p.px - r - 6 - tw;
        x = Math.max(m.l + 2, Math.min(x, W - m.r - tw));
        const bx = { x0: x - 2, x1: x + tw + 2, y0: p.py - 8, y1: p.py + 8 };
        if (!p.ring && boxes.some((b) => !(bx.x1 < b.x0 || bx.x0 > b.x1 || bx.y1 < b.y0 || bx.y0 > b.y1))) continue;
        boxes.push(bx);
        g.lineWidth = 3; g.strokeStyle = col.surface; g.strokeText(text, x, p.py);
        g.fillStyle = col.ink; g.fillText(text, x, p.py);
      }
      g.restore();
      if (this.hover) this._showTip(this.hover);
      if (!this.points.length) {
        g.fillStyle = col.ink2; g.font = "500 14px " + (css(this.root, "--body") || "sans-serif");
        g.textAlign = "center"; g.fillText(c.empty || "Nothing to plot for these filters.", W / 2, H / 2);
      }
    }

    _nearest(mx, my) {
      let best = null, bd = 16 * 16;
      for (const p of this.points) {
        if (p.px == null || p.dim) continue;
        const dx = p.px - mx, dy = p.py - my, d2 = dx * dx + dy * dy;
        if (d2 < bd) { bd = d2; best = p; }
      }
      return best;
    }

    _showTip(p) {
      const html = this.opts.tooltip ? this.opts.tooltip(p) : `${p.x}, ${p.y}`;
      this.tip.innerHTML = html; this.tip.hidden = false;
      const tw = this.tip.offsetWidth, th = this.tip.offsetHeight;
      let x = p.px + 12, y = p.py - th - 10;
      if (x + tw > this.w) x = p.px - tw - 12;
      if (y < 0) y = p.py + 12;
      this.tip.style.left = Math.max(0, x) + "px"; this.tip.style.top = y + "px";
      // hover ring
      const g = this.ctx;
      g.strokeStyle = this.col.sel; g.lineWidth = 2;
      g.beginPath(); g.arc(p.px, p.py, (this.r || 4) + 3, 0, Math.PI * 2); g.stroke();
    }

    _bind() {
      const pos = (ev) => { const r = this.canvas.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
      let drag = null;
      this.canvas.addEventListener("pointerdown", (ev) => {
        if (ev.pointerType !== "mouse" || ev.button !== 0) return;
        drag = { start: pos(ev), moved: false };
      });
      this.canvas.addEventListener("pointermove", (ev) => {
        const [mx, my] = pos(ev);
        if (drag) {
          const [sx, sy] = drag.start;
          if (Math.abs(mx - sx) + Math.abs(my - sy) > 6) drag.moved = true;
          if (drag.moved) {
            Object.assign(this.box.style, { left: Math.min(sx, mx) + "px", top: Math.min(sy, my) + "px",
              width: Math.abs(mx - sx) + "px", height: Math.abs(my - sy) + "px" });
            this.box.hidden = false; this.tip.hidden = true;
            return;
          }
        }
        const p = this._nearest(mx, my);
        if (p !== this.hover) { this.hover = p; this.tip.hidden = !p; this.draw(); }
        this.canvas.style.cursor = p ? "pointer" : "crosshair";
      });
      window.addEventListener("pointerup", (ev) => {
        if (!drag) return;
        const d = drag; drag = null; this.box.hidden = true;
        if (!d.moved) return;
        const [ax, ay] = d.start, [bx, by] = pos(ev);
        const { ix, iy } = this._scales();
        const x0 = ix(Math.min(ax, bx)), x1 = ix(Math.max(ax, bx)), y0 = iy(Math.max(ay, by)), y1 = iy(Math.min(ay, by));
        if (x1 > x0 && y1 > y0) { this.view = { x0, x1, y0, y1 }; this.hover = null; this.tip.hidden = true; this.draw(); }
        this._suppressClick = true;
      });
      this.canvas.addEventListener("pointerleave", () => { if (!drag) { this.hover = null; this.tip.hidden = true; this.draw(); } });
      this.canvas.addEventListener("click", (ev) => {
        if (this._suppressClick) { this._suppressClick = false; return; }
        const [mx, my] = pos(ev);
        const p = this._nearest(mx, my);
        if (p && this.opts.onClick) this.opts.onClick(p);
        else if (p) { this.hover = p; this.draw(); }
      });
      this.canvas.addEventListener("dblclick", () => this.resetZoom());
      this.resetBtn.addEventListener("click", () => this.resetZoom());
    }

    resetZoom() { this.view = null; this.draw(); }
  }

  window.Scatter = Scatter;
})();
