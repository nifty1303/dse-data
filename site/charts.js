// Small SVG chart helpers: line (with bands + markers), columns, stacked share, sparkline.
// Every chart gets a crosshair tooltip listing all series at the hovered date.
(function () {
  const NS = "http://www.w3.org/2000/svg";

  function el(tag, attrs) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function niceTicks(min, max, n) {
    if (!isFinite(min) || !isFinite(max)) return [];
    if (min === max) { min -= 1; max += 1; }
    const span = max - min, step0 = span / n;
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || 10 * mag;
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }
  function fmtDate(d) {
    const [y, m, day] = d.split("-");
    return `${+day} ${"JanFebMarAprMayJunJulAugSepOctNovDec".substr((+m - 1) * 3, 3)} ${y.slice(2)}`;
  }

  function tooltip(box) {
    let tt = box.querySelector(".tt");
    if (!tt) { tt = document.createElement("div"); tt.className = "tt"; box.appendChild(tt); }
    return tt;
  }
  function fillTip(tt, date, rows) {
    tt.textContent = "";
    const d = document.createElement("div"); d.className = "d"; d.textContent = fmtDate(date); tt.appendChild(d);
    for (const r of rows) {
      const row = document.createElement("div"); row.className = "r";
      const ln = document.createElement("span"); ln.className = "ln"; ln.style.background = r.color;
      const b = document.createElement("b"); b.textContent = r.value;
      const n = document.createElement("span"); n.textContent = r.name;
      row.append(ln, b, n); tt.appendChild(row);
    }
  }

  // Shared frame: x = index into dates, y = linear.
  function frame(box, opts) {
    box.classList.add("chart");
    box.querySelector("svg")?.remove();
    const W = Math.max(280, box.clientWidth || 600), H = opts.height || 240;
    const m = { l: 48, r: opts.rightPad ?? 64, t: 10, b: 24 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": opts.label || "chart" });
    box.prepend(svg);
    const n = opts.dates.length;
    const x = i => m.l + (n <= 1 ? 0 : (i / (n - 1)) * (W - m.l - m.r));
    const y = v => m.t + (1 - (v - opts.ymin) / (opts.ymax - opts.ymin || 1)) * (H - m.t - m.b);
    const g = el("g", {}); svg.appendChild(g);
    for (const t of niceTicks(opts.ymin, opts.ymax, opts.ticks || 4)) {
      g.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: css("--grid"), "stroke-width": 1 }));
      const tx = el("text", { x: m.l - 6, y: y(t) + 4, fill: css("--muted"), "font-size": 11, "text-anchor": "end" });
      tx.textContent = opts.yFormat ? opts.yFormat(t) : t; g.appendChild(tx);
    }
    // x labels: first, middle, last month boundaries
    const idx = [0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => a.indexOf(v) === i);
    for (const i of idx) {
      const tx = el("text", { x: x(i), y: H - 6, fill: css("--muted"), "font-size": 11,
        "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" });
      tx.textContent = fmtDate(opts.dates[i]); g.appendChild(tx);
    }
    return { svg, W, H, m, x, y, n };
  }

  function crosshair(box, f, dates, rowsAt) {
    const tt = tooltip(box);
    const line = el("line", { y1: f.m.t, y2: f.H - f.m.b, stroke: css("--axis"), "stroke-width": 1, visibility: "hidden" });
    f.svg.appendChild(line);
    const hit = el("rect", { x: f.m.l, y: 0, width: f.W - f.m.l - f.m.r, height: f.H, fill: "transparent" });
    f.svg.appendChild(hit);
    function show(ev) {
      const r = f.svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (f.W / r.width);
      const i = Math.max(0, Math.min(f.n - 1, Math.round(((px - f.m.l) / (f.W - f.m.l - f.m.r)) * (f.n - 1))));
      line.setAttribute("x1", f.x(i)); line.setAttribute("x2", f.x(i)); line.setAttribute("visibility", "visible");
      fillTip(tt, dates[i], rowsAt(i));
      tt.style.display = "block";
      const left = (f.x(i) / f.W) * r.width;
      tt.style.left = Math.min(left + 12, r.width - tt.offsetWidth - 4) + "px";
      tt.style.top = "8px";
    }
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerleave", () => { tt.style.display = "none"; line.setAttribute("visibility", "hidden"); });
  }

  function path(values, x, y) {
    let d = "", pen = false;
    values.forEach((v, i) => {
      if (v == null || !isFinite(v)) { pen = false; return; }
      d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); pen = true;
    });
    return d;
  }

  // opts: {dates, series:[{name,values,color,width,dash,fmt}], band:{lo,hi,color,name}, markers:[{i,v,color,label}], yFormat, height}
  function line(box, opts) {
    const all = [];
    opts.series.forEach(s => s.values.forEach(v => v != null && isFinite(v) && all.push(v)));
    if (opts.band) [opts.band.lo, opts.band.hi].forEach(a => a.forEach(v => v != null && all.push(v)));
    let ymin = Math.min(...all), ymax = Math.max(...all);
    const pad = (ymax - ymin) * 0.06 || 1; ymin -= pad; ymax += pad;
    if (opts.zero) ymin = Math.min(ymin, 0);
    const f = frame(box, { ...opts, ymin, ymax });
    if (opts.band) {
      const { lo, hi } = opts.band;
      let d = "", started = false;
      const idx = lo.map((v, i) => i).filter(i => lo[i] != null && hi[i] != null);
      idx.forEach((i, k) => { d += (k ? "L" : "M") + f.x(i).toFixed(1) + "," + f.y(hi[i]).toFixed(1); started = true; });
      idx.slice().reverse().forEach(i => { d += "L" + f.x(i).toFixed(1) + "," + f.y(lo[i]).toFixed(1); });
      if (started) f.svg.appendChild(el("path", { d: d + "Z", fill: opts.band.color, opacity: 0.12 }));
    }
    for (const s of opts.series) {
      f.svg.appendChild(el("path", { d: path(s.values, f.x, f.y), fill: "none", stroke: s.color,
        "stroke-width": s.width || 2, "stroke-linejoin": "round", "stroke-linecap": "round",
        ...(s.dash ? { "stroke-dasharray": s.dash } : {}) }));
    }
    for (const mk of opts.markers || []) {
      f.svg.appendChild(el("circle", { cx: f.x(mk.i), cy: f.y(mk.v), r: 4, fill: mk.color, stroke: css("--surface"), "stroke-width": 2 }));
    }
    if (opts.endLabels) {
      const used = [];
      for (const s of opts.series.filter(s => s.endLabel !== false)) {
        const i = s.values.length - 1; const v = s.values[i]; if (v == null) continue;
        let yy = f.y(v) + 4;
        if (used.some(u => Math.abs(u - yy) < 12)) continue;
        used.push(yy);
        const t = el("text", { x: f.x(i) + 6, y: yy, "font-size": 11, fill: css("--ink-2") });
        t.textContent = s.label || s.name; f.svg.appendChild(t);
      }
    }
    crosshair(box, f, opts.dates, i => {
      const rows = opts.series.filter(s => s.tip !== false).map(s => ({ name: s.name, color: s.color,
        value: s.values[i] == null ? "–" : (s.fmt || opts.yFormat || (v => v))(s.values[i]) }));
      if (opts.band && opts.band.lo[i] != null) rows.push({ name: opts.band.name, color: opts.band.color,
        value: `${(opts.yFormat || (v => v))(opts.band.lo[i])}–${(opts.yFormat || (v => v))(opts.band.hi[i])}` });
      return rows;
    });
    return f;
  }

  // Thin columns (volume). opts: {dates, values, color, fmt, height}
  function columns(box, opts) {
    const ymax = Math.max(...opts.values.filter(v => v != null)) * 1.05 || 1;
    const f = frame(box, { ...opts, ymin: 0, ymax, ticks: 3 });
    const bw = Math.max(1, Math.min(24, (f.W - f.m.l - f.m.r) / f.n - 1));
    opts.values.forEach((v, i) => {
      if (!v) return;
      const h = f.y(0) - f.y(v);
      f.svg.appendChild(el("rect", { x: f.x(i) - bw / 2, y: f.y(v), width: bw, height: Math.max(0.5, h),
        fill: (opts.colors && opts.colors[i]) || opts.color, rx: bw >= 6 ? 2 : 0 }));
    });
    crosshair(box, f, opts.dates, i => [{ name: opts.name, color: (opts.colors && opts.colors[i]) || opts.color,
      value: opts.values[i] == null ? "–" : opts.fmt(opts.values[i]) }]);
    return f;
  }

  // Stacked shares (0..1) as areas. opts: {dates, layers:[{name, values, color}]}
  function stack(box, opts) {
    const f = frame(box, { ...opts, ymin: 0, ymax: 1, ticks: 4, yFormat: v => Math.round(v * 100) + "%" });
    const n = opts.dates.length; let base = new Array(n).fill(0);
    for (const L of opts.layers) {
      const top = base.map((b, i) => b + (L.values[i] || 0));
      let d = "";
      for (let i = 0; i < n; i++) d += (i ? "L" : "M") + f.x(i).toFixed(1) + "," + f.y(top[i]).toFixed(1);
      for (let i = n - 1; i >= 0; i--) d += "L" + f.x(i).toFixed(1) + "," + f.y(base[i]).toFixed(1);
      f.svg.appendChild(el("path", { d: d + "Z", fill: L.color, stroke: css("--surface"), "stroke-width": 1 }));
      base = top;
    }
    crosshair(box, f, opts.dates, i => opts.layers.slice().reverse().map(L => ({ name: L.name, color: L.color,
      value: Math.round((L.values[i] || 0) * 100) + "%" })));
    return f;
  }

  function spark(values, w = 90, h = 26) {
    const v = values.filter(x => x != null);
    const svg = el("svg", { width: w, height: h, viewBox: `0 0 ${w} ${h}`, "aria-hidden": "true" });
    if (v.length < 2) return svg;
    const lo = Math.min(...v), hi = Math.max(...v);
    const x = i => 1 + (i / (values.length - 1)) * (w - 6);
    const y = val => 3 + (1 - (val - lo) / (hi - lo || 1)) * (h - 6);
    svg.appendChild(el("path", { d: path(values, x, y), fill: "none", stroke: css("--muted"), "stroke-width": 1.5, "stroke-linejoin": "round" }));
    const last = values.length - 1;
    const up = values[last] >= values[0];
    svg.appendChild(el("circle", { cx: x(last), cy: y(values[last]), r: 2.5, fill: up ? css("--buy") : css("--sell") }));
    return svg;
  }

  window.Charts = { line, columns, stack, spark, fmtDate };
})();
