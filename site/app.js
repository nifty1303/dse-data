// DSE Signals front end: one timeframe, the next 2 weeks (10 trading days).
// Reads data/summary.json, data/track.json and data/stocks/<SYM>.json.
(function () {
  const S = { summary: null, track: null, bySym: {}, cache: {}, sort: { key: "rank", dir: 1 }, filters: {}, q: "", range: 500, side: "buy", sector: "" };
  const app = () => document.getElementById("app");
  const NON_SHARE = new Set(["Corporate Bond", "Debenture"]);

  // ---------- tiny DOM helper (text always goes through textContent)
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      const v = attrs[k];
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "style") e.style.cssText = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      e.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return e;
  }
  const pct = (x, d = 0) => (x == null ? "–" : (x * 100).toFixed(d) + "%");
  const spct = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x * 100).toFixed(d) + "%");
  const num = (x, d = 2) => (x == null ? "–" : Number(x).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const tk = x => (x == null ? "–" : "Tk " + num(x, x < 100 ? 2 : 1));
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const go = sym => { location.hash = "#s/" + encodeURIComponent(sym); };
  const HZ = () => S.summary.horizons.short;
  const store = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } };
  const load = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const ORDER = ["Strong Buy", "Buy", "Lean Buy", "Sell"];

  // ---------- building blocks
  function badge(v) {
    return h("span", { class: "verdict v-" + v.toLowerCase().replace(/ /g, "-") }, v);
  }
  function bs(o, big) {
    const b = o.dir ?? 0.5;
    return h("div", { class: "bs" + (big ? " big" : ""), role: "img", "aria-label": `Buy ${pct(b)}, Sell ${pct(1 - b)}` },
      h("div", { class: "bar" }, h("span", { class: "b", style: `width:${b * 100}%` }), h("span", { class: "s", style: `width:${(1 - b) * 100}%` })),
      h("div", { class: "lbl" }, h("span", { class: "gb" }, "Buy " + pct(b)), h("span", { class: "rs" }, "Sell " + pct(1 - b))));
  }
  function stat(label, value, frac, title) {
    return h("div", { class: "stat", title },
      h("b", null, value), h("span", null, label),
      frac == null ? null : h("div", { class: "meter" }, h("i", { style: `width:${Math.max(0, Math.min(1, frac)) * 100}%` })));
  }
  const moveStat = o => stat("move chance", pct(o.move), o.move, "Chance the price moves more than 3% either way in the next 2 weeks");
  const confStat = o => stat("confidence", o.conf, o.conf / 100, "How far to trust this: history, liquidity, cycle regularity, clarity");
  function expBlock(o) {
    const parts = [`from the odds ${spct(o.outlook)}`];
    if (o.tilt) parts.push(`cycle ${spct(o.tilt)}`);
    if (o.season) parts.push(`month ${spct(o.season)}`);
    if (o.weekday) parts.push(`weekday ${spct(o.weekday)}`);
    return h("div", { class: "expbox" },
      h("div", null, h("b", { class: o.exp >= 0.025 ? "up" : o.exp < 0 ? "down" : "" }, spct(o.exp)), " expected change in 2 weeks"),
      parts.length > 1 ? h("div", { class: "small muted" }, parts.join(" · ")) : null);
  }
  function gauge(r) {
    const b = r.band == null ? null : Math.max(-0.2, Math.min(1.2, r.band));
    const leg = r.leg === 1 ? "rising" : r.leg === -1 ? "falling" : null;
    const long = r.leg_typ && r.leg_days > 1.5 * r.leg_typ;
    return h("div", null,
      h("div", { class: "gauge", title: "Shaded = regular 2-year range (10th–90th percentile)" },
        h("div", { class: "reg" }), b == null ? null : h("div", { class: "pin", style: `left:${15 + b * 70}%` })),
      h("div", { class: "gauge-lbl" }, h("span", null, "2-yr low"),
        h("span", null, r.band == null ? "range not known yet" : `${pct(r.band)} up the regular range`), h("span", null, "2-yr high")),
      leg ? h("div", { class: "small muted" }, `Current swing: ${leg} for ${r.leg_days} days${long ? " (longer than usual)" : r.leg_typ ? `, typical ~${r.leg_typ}` : ""}`) : null);
  }
  function tags(r) {
    const junk = /junk/i.test(r.type);
    return [h("span", { class: junk ? "tag junk" : "tag" }, r.type),
      r.stage && r.stage !== "Quiet" ? h("span", { class: junk ? "tag junk" : "tag" }, r.stage + " stage") : null];
  }
  function move(o) {
    if (o.rank_prev == null) return h("small", { class: "muted" }, "new");
    const d = o.rank_prev - o.rank;
    if (!d) return h("small", { class: "muted" }, "same");
    return h("small", { class: d > 0 ? "up" : "down" }, (d > 0 ? "▲" : "▼") + Math.abs(d));
  }
  function moodBanner(md) {
    const icon = { Friendly: "●", Neutral: "◐", Caution: "▲", Hostile: "■" }[md.label];
    return h("div", { class: "mood " + md.label, role: "status" },
      h("div", { class: "icon", "aria-hidden": "true" }, icon),
      h("div", null,
        h("div", { class: "label" }, "Market mood: " + md.label),
        md.warning ? h("div", null, md.warning) : null,
        h("details", null, h("summary", null, "Why"), h("ul", null, md.reasons.map(t => h("li", null, t))))));
  }
  function timingTip() {
    const t = HZ().thursday;
    if (!t) return null;
    const sun = t.same_day.Sunday, thuNext = t.next_day_after.Thursday;
    if (sun == null || sun > -0.001) return null;
    return h("div", { class: "note", style: "margin-bottom:16px" },
      h("b", null, "Timing tip · Thursday → Sunday: "),
      `over the last two years the average share moved ${spct(sun, 2)} on Sundays, the first session after DSE's Friday–Saturday weekend ` +
      `(Thursday's close to Sunday's close: ${spct(thuNext, 2)}). If you plan to buy at Thursday's close, waiting until Sunday has saved about ` +
      `${Math.abs(thuNext * 100).toFixed(2)}% on average. Over the full 2 weeks the entry day made no reliable difference, so it doesn't change the verdicts.`);
  }
  function dist() {
    const v = HZ().verdicts, total = ORDER.reduce((a, k) => a + (v[k] || 0), 0);
    const col = { "Strong Buy": "--buy-strong", Buy: "--buy", "Lean Buy": "--buy-wash", Sell: "--sell" };
    return h("div", { class: "card", style: "padding:12px 16px;margin-bottom:16px" },
      h("div", { class: "small muted" }, `All ${total} shares today, next 2 weeks`),
      h("div", { class: "dist" }, ORDER.filter(k => v[k]).map(k => h("span", {
        style: `flex:${v[k]};background:var(${col[k]});color:${k === "Lean Buy" ? "var(--buy-ink)" : "#fff"}`, title: `${k}: ${v[k]}` },
        v[k] / total > 0.06 ? `${k} ${v[k]}` : ""))),
      h("div", { class: "chips small" }, ORDER.filter(k => v[k]).map(k => h("span", null, badge(k), " ", v[k]))));
  }

  function pickCard(r, pos, side) {
    const o = r.s;
    const lines = (side === "sell" ? o.caution : o.why).slice(0, 2);
    return h("div", { class: "pick", tabindex: 0, onclick: () => go(r.sym), onkeydown: e => e.key === "Enter" && go(r.sym) },
      h("div", { class: "top" },
        h("div", { class: "rank" }, pos, move(o)),
        h("div", { class: "name" }, h("div", null, h("span", { class: "sym" }, r.sym), " ", badge(o.verdict)),
          h("div", { class: "meta" }, `${r.sector} · Category ${r.cat}`), h("div", null, tags(r))),
        h("div", { class: "price" }, h("b", null, num(r.close)), h("span", { class: "small " + (r.chg >= 0 ? "up" : "down") }, spct(r.chg)))),
      expBlock(o),
      bs(o),
      h("div", { class: "nums" }, moveStat(o), confStat(o),
        stat("to regular high", spct(r.up_room, 0)), stat("to 2-yr low", spct(r.down_risk == null ? null : -r.down_risk, 0))),
      gauge(r),
      lines.length ? h("ul", { class: "why" }, lines.map(t => h("li", null, t))) : null,
      o.days_top > 1 && side !== "sell" ? h("div", { class: "other" }, `${o.days_top} days in the Top 20`) : null);
  }
  function miniRow(r) {
    const o = r.s;
    return h("div", { class: "mini", onclick: () => go(r.sym) },
      h("div", null, h("span", { class: "sym" }, r.sym), " ", h("span", { class: "muted small" }, `${num(r.close)} · expected ${spct(o.exp)}`)),
      badge(o.verdict), bs(o));
  }

  // ---------- Top picks
  function pickList(side, sector) {
    const by = side === "sell" ? "sscore" : "score";
    const pool = S.summary.stocks.filter(r => !NON_SHARE.has(r.sector) && (!sector || r.sector === sector))
      .sort((a, b) => b.s[by] - a.s[by]);
    if (sector) return pool.slice(0, 20);
    const out = [], count = {};
    for (const r of pool) {                       // at most 4 per sector when showing all sectors
      if (out.length >= 20) break;
      if ((count[r.sector] || 0) < 4) { out.push(r); count[r.sector] = (count[r.sector] || 0) + 1; }
    }
    return out;
  }
  function viewTop() {
    const s = S.summary, hz = HZ(), side = S.side, sector = S.sector;
    const list = pickList(side, sector);
    const sectors = [...new Set(s.stocks.map(r => r.sector))].filter(x => !NON_SHARE.has(x)).sort();
    const sideBtn = (v, label) => h("button", { class: side === v ? "on" : "", onclick: () => { S.side = v; route(); } }, label);
    const title = `Top ${list.length} to ${side === "sell" ? "sell or avoid" : "buy"}${sector ? " in " + sector : ""} · next 2 weeks`;
    const sub = side === "sell"
      ? "Lowest expected change over the next 10 trading days, including the highest odds of a 3%+ fall. Junk shares can still spike, so the risk runs both ways."
      : "Highest expected change over the next 10 trading days. Verdict: under +1% Sell, +1% to +2.5% Lean Buy, +2.5% to +4% Buy, +4% or more Strong Buy.";
    const showExtras = side === "buy" && !sector;
    const noneBuy = side === "buy" && list.length && list.every(r => r.s.verdict === "Sell");
    return h("div", null,
      moodBanner(s.mood),
      h("div", { class: "page-head" },
        h("div", null, h("h1", null, title), h("p", { class: "sub", style: "margin:0" }, sub + (sector ? "" : " At most 4 per sector.")))),
      h("div", { class: "filters" },
        h("div", { class: "seg", role: "tablist", "aria-label": "Buy or sell" }, sideBtn("buy", "Buy"), sideBtn("sell", "Sell")),
        h("select", { "aria-label": "Sector", onchange: e => { S.sector = e.target.value; route(); } },
          h("option", { value: "" }, "All sectors"), sectors.map(x => h("option", { value: x, selected: sector === x ? "" : null }, x)))),
      dist(),
      timingTip(),
      noneBuy ? h("div", { class: "note", style: "margin-bottom:12px" },
        "No share in this list reaches the +1% line, so every verdict is Sell. These are still the best-placed shares if you do buy.") : null,
      list.length ? h("div", { class: "picks" }, list.map((r, i) => pickCard(r, i + 1, side))) : h("div", { class: "empty" }, "No shares in this sector."),
      showExtras ? h("div", { class: "grid two", style: "margin-top:14px" },
        h("div", { class: "card" }, h("h3", null, "New in the Top 20 today"),
          hz.new_entries.length ? h("div", { class: "chips" }, hz.new_entries.map(x => h("button", { class: "chip", onclick: () => go(x) }, x)))
            : h("div", { class: "empty small" }, "No changes since yesterday")),
        h("div", { class: "card" }, h("h3", null, "Dropped out today"),
          hz.dropped.length ? h("div", { class: "chips" }, hz.dropped.map(x => h("button", { class: "chip", onclick: () => go(x) }, x)))
            : h("div", { class: "empty small" }, "No changes since yesterday"))) : null,
      showExtras && Object.keys(hz.also).length ? h("div", null,
        h("h2", null, "Also strong (left out only by the 4-per-sector cap)"),
        h("div", { class: "grid two" }, Object.entries(hz.also).map(([sec, l]) =>
          h("div", { class: "card" }, h("h3", null, sec), l.map(x => miniRow(S.bySym[x])))))) : null);
  }

  function viewSectors() {
    const hz = HZ();
    const secs = Object.entries(hz.sectors).sort((a, b) => b[1].avg_exp - a[1].avg_exp);
    return h("div", null,
      moodBanner(S.summary.mood),
      h("h1", null, "By sector"),
      h("p", { class: "sub" }, "Top 5 to buy and top 5 to sell in every sector for the next 2 weeks. Sectors are ordered by their average expected change."),
      h("div", { class: "grid two" }, secs.map(([name, v]) => h("div", { class: "card" },
        h("h3", { style: "display:flex;justify-content:space-between;gap:8px" }, h("span", null, name),
          h("span", { class: "small muted num" }, `${v.count} listed · avg expected ${spct(v.avg_exp)} · 4 wks ${spct(v.ret20)}`)),
        h("div", { class: "col-title" }, "Top buy"), v.buy.map(x => miniRow(S.bySym[x])),
        h("div", { class: "col-title" }, "Top sell"), v.sell.map(x => miniRow(S.bySym[x]))))));
  }

  // ---------- All shares: instant search cards + sortable table
  const COLS = [
    ["sym", "Share", r => r.sym, r => r.sym],
    ["sector", "Sector", r => r.sector, r => r.sector],
    ["close", "Price", r => num(r.close), r => r.close, "r"],
    ["chg", "Day", r => spct(r.chg), r => r.chg, "r"],
    ["rank", "Verdict", r => badge(r.s.verdict), r => r.s.rank],
    ["exp", "Expected 2 wks", r => spct(r.s.exp), r => r.s.exp, "r"],
    ["dir", "Buy", r => pct(r.s.dir), r => r.s.dir, "r g"],
    ["sell", "Sell", r => pct(1 - r.s.dir), r => 1 - r.s.dir, "r rd"],
    ["move", "Move chance", r => pct(r.s.move), r => r.s.move, "r"],
    ["conf", "Confidence", r => r.s.conf, r => r.s.conf, "r"],
    ["band", "2-yr range", r => pct(r.band), r => r.band, "r"],
    ["type", "Type", r => r.type, r => r.type],
  ];
  function quickCard(r) {
    const o = r.s;
    return h("div", { class: "qcard", onclick: () => go(r.sym) },
      h("div", { class: "head" }, h("div", null, h("b", { style: "font-size:16px" }, r.sym), " ", badge(o.verdict), " ",
        h("span", { class: "muted small" }, `${r.sector} · Cat ${r.cat}`)),
        h("div", { class: "num" }, h("b", null, num(r.close)), " ", h("span", { class: "small " + (r.chg >= 0 ? "up" : "down") }, spct(r.chg)))),
      bs(o),
      h("div", { class: "mv" }, h("b", { class: o.exp >= 0.025 ? "up" : o.exp < 0 ? "down" : "" }, `Expected ${spct(o.exp)}`),
        ` in 2 weeks · Move chance ${pct(o.move)} · Confidence ${o.conf}`));
  }
  function viewAll() {
    const s = S.summary, f = S.filters;
    const results = h("div", { class: "results", "aria-live": "polite" });
    const box = h("div", { class: "tbl-wrap" });
    const count = h("span", { class: "muted small" });
    const opts = key => [...new Set(s.stocks.map(r => r[key]))].sort();
    const sel = (key, label) => h("select", { onchange: e => { f[key] = e.target.value; render(); } },
      h("option", { value: "" }, "All " + label), opts(key).map(v => h("option", { value: v, selected: f[key] === v ? "" : null }, v)));
    function render() {
      const q = S.q.trim().toUpperCase();
      results.textContent = "";
      if (q) {
        const hits = s.stocks.filter(r => r.sym.includes(q))
          .sort((a, b) => (b.sym.startsWith(q) - a.sym.startsWith(q)) || a.sym.localeCompare(b.sym)).slice(0, 6);
        hits.length ? hits.forEach(r => results.appendChild(quickCard(r)))
          : results.appendChild(h("div", { class: "empty" }, `No share matches “${S.q}”`));
      }
      const col = COLS.find(c => c[0] === S.sort.key) || COLS[4];
      const rows = s.stocks.filter(r => (!q || r.sym.includes(q)) && ["sector", "type", "cat"].every(k => !f[k] || r[k] === f[k]))
        .sort((a, b) => {
          const x = col[3](a), y = col[3](b);
          if (x == null) return 1; if (y == null) return -1;
          return (x > y ? 1 : x < y ? -1 : 0) * S.sort.dir;
        });
      count.textContent = `${rows.length} of ${s.stocks.length} shares`;
      const table = h("table", null,
        h("thead", null, h("tr", null, COLS.map(([k, label, , , cls]) => h("th", {
          class: [cls, S.sort.key === k ? "sorted" : ""].join(" "),
          onclick: () => { S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : (cls && cls.startsWith("r") ? -1 : 1) }; render(); },
        }, label + (S.sort.key === k ? (S.sort.dir > 0 ? " ↑" : " ↓") : ""))))),
        h("tbody", null, rows.map(r => h("tr", { onclick: () => go(r.sym) }, COLS.map(([, , fn, , cls]) => h("td", { class: cls }, fn(r)))))));
      box.textContent = ""; box.appendChild(table);
    }
    const input = h("input", { type: "search", placeholder: "Type a share name, e.g. BRACBANK", value: S.q, autocomplete: "off",
      "aria-label": "Search shares", oninput: e => { S.q = e.target.value; render(); } });
    render();
    setTimeout(() => input.focus(), 0);
    return h("div", null,
      h("h1", null, "All shares"),
      h("p", { class: "sub" }, "Start typing to see a share's 2-week verdict instantly. Every listed instrument is here; click any row for the full picture."),
      h("div", { class: "search" }, h("span", { class: "ico", "aria-hidden": "true" }, "⌕"), input),
      results,
      h("div", { class: "filters" }, sel("sector", "sectors"), sel("type", "types"), sel("cat", "categories"), count),
      box);
  }

  // ---------- Track record
  function tile(label, value, note, cls) {
    return h("div", { class: "card tile" }, h("div", { class: "t-label" }, label),
      h("div", { class: "t-value " + (cls || "") }, value), note ? h("div", { class: "t-note" }, note) : null);
  }
  const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function viewTrack() {
    const t = S.track.short, s = t.summary, x = t.extra;
    const chart = h("div");
    const vsIdx = s.top20_total - s.market_total, vsAll = s.top20_total - s.all_total;
    const kept = [x.cycle_weight ? `cycle tilt (weight ${x.cycle_weight})` : null, x.use_month ? "month season" : null, x.use_weekday ? "weekday effect" : null].filter(Boolean);
    const out = h("div", null,
      h("h1", null, "Track record"),
      h("p", { class: "sub" }, `Every 2 weeks the Top 20 is bought in equal amounts and held for 10 trading days, paying 0.5% brokerage each way on the part of the list that changes. ` +
        `The model is retrained monthly on data available at the time, so these ${s.periods} periods (${Charts.fmtDate(s.start)} – ${Charts.fmtDate(s.end)}) are results it never saw while learning.`),
      h("div", { class: "grid tiles" },
        tile("Top 20 portfolio", spct(s.top20_total), "after costs, compounded", s.top20_total >= 0 ? "up" : "down"),
        tile("Market index", spct(s.market_total), "cap-weighted"),
        tile("All shares, equal amounts", spct(s.all_total), "buy everything"),
        tile("Periods beating the index", pct(s.beat_market), `${s.periods} two-week periods`),
        tile("Picks that rose", pct(s.avg_hit_rate), "average per period"),
        tile("Picks that gained >3%", pct(s.avg_target_rate), "the target")),
      h("h2", null, "Growth of Tk 100"),
      h("div", { class: "legend" },
        h("span", null, h("i", { style: `background:${css("--s1")}` }), "Top 20"),
        h("span", null, h("i", { style: `background:${css("--s2")}` }), "Market index"),
        h("span", null, h("i", { style: `background:${css("--s3")}` }), "All shares"),
        h("span", null, h("i", { style: `background:${css("--s4")}` }), "Sell list")),
      h("div", { class: "card" }, chart),
      h("div", { class: "note", style: "margin-top:12px" },
        `Reading this honestly: the Top 20 ${vsIdx >= 0 ? "beat" : "trailed"} the market index by ${Math.abs(vsIdx * 100).toFixed(1)} points and ` +
        `${vsAll >= 0 ? "beat" : "trailed"} an equal-weight basket of every share by ${Math.abs(vsAll * 100).toFixed(1)} points. ` +
        `On an average period ${pct(s.avg_hit_rate)} of the picks rose, while ${pct(s.avg_sell_fell)} of the sell list fell. ` +
        "The model is better at spotting shares likely to fall than shares about to rise, so treat the scores as odds, not certainties."),
      h("h2", null, "Does the expected change come true?"),
      h("p", { class: "sub" }, "Unseen predictions grouped by expected 2-week change, against what really happened."),
      h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Expected change", "Cases", "Avg expected", "Actual avg", "Actual median", "Rose >3%", "Fell >3%"]
          .map((c, i) => h("th", { class: i ? "r" : "" }, c)))),
        h("tbody", null, t.calibration.map(c => h("tr", { style: "cursor:default" }, h("td", null, c.bucket), h("td", { class: "r" }, (c.n || 0).toLocaleString()),
          h("td", { class: "r" }, spct(c.predicted)), h("td", { class: "r" }, spct(c.avg_return)), h("td", { class: "r" }, spct(c.median_return)),
          h("td", { class: "r g" }, pct(c.rose)), h("td", { class: "r rd" }, pct(c.fell))))))),
      h("h2", null, "Which add-ons earned their place?"),
      h("p", { class: "sub" }, `Each add-on is kept only if it helps on unseen periods. In use now: ${kept.length ? kept.join(", ") : "none — the odds alone did best"}.`),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("h3", null, "Cycle tilt (2-year range position)"),
          h("div", { class: "small muted", style: "margin-bottom:6px" }, "Judged on the Top 20's result"),
          h("div", { class: "kv" }, x.trials.flatMap(tr => [h("div", null, `Weight ${tr.w}${tr.w === x.cycle_weight ? " (used)" : ""}`),
            h("div", null, `${spct(tr.top20)} · beat index ${pct(tr.beat_market)}`)]))),
        h("div", { class: "card" }, h("h3", null, "Month season and weekday effect"),
          h("div", { class: "small muted", style: "margin-bottom:6px" }, "Judged on how close the expected 2-week move of the average share came to reality (lower error is better)"),
          h("div", { class: "kv" }, Object.entries(x.calendar_trials).flatMap(([k, v]) => [
            h("div", null, { none: "Neither", month: "Month season", weekday: "Weekday effect", both: "Both" }[k]),
            h("div", null, `error ${pct(v.rmse, 2)}`)])))),
      h("h2", null, "Calendar patterns in the data"),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("h3", null, "2-week return of the average share, by month"),
          h("div", { class: "kv" }, MONTHS.flatMap((mn, i) => {
            const v = x.month_raw[String(i + 1).padStart(2, "0")];
            return [h("div", null, mn), h("div", { class: v == null ? "" : v >= x.base ? "up" : "down" }, v == null ? "–" : spct(v))];
          })), h("div", { class: "small muted", style: "margin-top:6px" }, `Normal: ${spct(x.base)}. Only two years of history, so each month rests on one or two samples.`)),
        h("div", { class: "card" }, h("h3", null, "By weekday"),
          h("div", { class: "kv" }, [h("div", { class: "muted" }, "Day"), h("div", { class: "muted" }, "Same day · next 2 weeks")].concat(
            DAYS.flatMap(d => [h("div", null, d), h("div", null, `${spct(x.thursday.same_day[d], 2)} · ${spct(x.weekday_raw[d])}`)]))),
          h("div", { class: "small muted", style: "margin-top:6px" }, "Same day = average share's move that session. Next 2 weeks = average share's return over the 10 sessions after buying that day."))),
      h("h2", null, "Latest periods"),
      h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Start", "Top 20", "Index", "All shares", "Picks up", "Picks"].map((c, i) => h("th", { class: i && i < 5 ? "r" : "" }, c)))),
        h("tbody", null, t.periods.slice(-12).reverse().map(w => h("tr", { style: "cursor:default" }, h("td", null, Charts.fmtDate(w.date)),
          h("td", { class: "r " + (w.top20 >= 0 ? "up" : "down") }, spct(w.top20)), h("td", { class: "r" }, spct(w.market)),
          h("td", { class: "r" }, spct(w.all)), h("td", { class: "r" }, pct(w.hit)),
          h("td", { class: "small muted", style: "white-space:normal;min-width:320px" }, w.picks.join(", "))))))));
    requestAnimationFrame(() => {
      Charts.line(chart, {
        dates: t.periods.map(w => w.date), height: 280, label: "Track record", endLabels: true, yFormat: v => Math.round(v),
        series: [
          { name: "Top 20", values: t.curve.top20, color: css("--s1") }, { name: "Index", values: t.curve.market, color: css("--s2") },
          { name: "All shares", values: t.curve.all_stocks, color: css("--s3") }, { name: "Sell list", values: t.curve.sell20, color: css("--s4") },
        ].map(v => ({ ...v, fmt: n => n.toFixed(1) })),
      });
    });
    return out;
  }

  function viewHow() {
    const p = (...x) => h("p", null, ...x);
    return h("div", { class: "prose" },
      h("h1", null, "How the scores work"),
      p("Everything here comes only from DSE prices, volumes and trades plus the weekly company snapshot. No news, no opinions."),
      h("h2", null, "The question"),
      p("For every share: over the next 10 trading days (2 DSE weeks), how likely is it to gain more than 3%, or to lose more than 3%? 3% clears roughly 1% of round-trip brokerage with profit left."),
      h("h2", null, "What each number means"),
      h("ul", null,
        h("li", null, h("b", null, "Expected change: "), "the chance of a 3%+ rise times the average such rise, plus the chance of a 3%+ fall times the average such fall, plus the rest times the average small move. Add-ons (cycle tilt, month season, weekday effect) are included only when the backtest shows they help."),
        h("li", null, h("b", null, "Verdict: "), "under +1% expected = Sell (doesn't beat brokerage), +1% to +2.5% = Lean Buy, +2.5% to +4% = Buy, +4% or more = Strong Buy."),
        h("li", null, h("b", null, "Buy / Sell split (adds to 100%): "), "if the share does move more than 3%, how likely it is to be up (green) versus down (red)."),
        h("li", null, h("b", null, "Move chance: "), "how likely it is to move more than 3% at all. Low means it will probably just drift."),
        h("li", null, h("b", null, "Confidence (0–100): "), "how much history the share has, how liquid it is, how regular its cycles are, and how clear-cut today's split is. Junk shares are scaled down by a quarter, dead ones by half."),
        h("li", null, h("b", null, "Ranking: "), "the Top 20 ranks by expected change, at most 4 per sector when showing all sectors.")),
      h("h2", null, "Ranges"),
      h("ul", null,
        h("li", null, h("b", null, "Regular range: "), "the 10th to 90th percentile of all closing prices over the last 2 years."),
        h("li", null, h("b", null, "Outlier low / high: "), "the true lowest and highest close in those 2 years."),
        h("li", null, h("b", null, "Current swing: "), "the same percentiles over the last 3 months, a lighter band on the chart.")),
      h("h2", null, "What the model looks at"),
      p("Cycle position, trend & momentum (returns, moving averages, RSI), money flow (volume vs normal, up-day vs down-day volume, trade size), liquidity, risk (volatility, circuit hits, drawdown), relative strength vs market and sector, fundamentals (category, holdings, reserves), junk pattern (volume spikes, circuit runs, pumps, small paid-up capital) and similar past setups in the same share."),
      p("Market mood is shown as a banner but is not fed to the model: with two years of history the model would learn what the market happened to do rather than which shares beat others."),
      h("h2", null, "Calendar effects"),
      p("Month-of-year and weekday effects (including Thursday, the last session before DSE's weekend) are measured and tested. They are added to the expected change only if they make it more accurate on unseen periods; the Track record page shows the result. Right now the Sunday dip after the weekend shows up as a timing tip rather than a change to the verdicts."),
      h("h2", null, "How it stays honest"),
      p("A gradient-boosted decision-tree model is retrained monthly in the backtest using only data available at the time. Its odds are calibrated to match how often things actually happened over the full two years."),
      h("h2", null, "Bonus shares"),
      p("DSE caps daily moves at about 10%, so a larger overnight drop with an opening gap is treated as a record-date adjustment (bonus, dividend) and earlier prices are scaled so charts and ranges stay continuous."),
      h("h2", null, "Limits"),
      h("ul", null,
        h("li", null, "Only two years of data, so each calendar month and some cycles rest on very few samples."),
        h("li", null, "Fundamentals come from the latest weekly snapshot and are applied to the past as-is."),
        h("li", null, "It cannot see news, announcements or manipulation before it shows in the data."),
        h("li", null, "This is a research tool, not financial advice.")),
      h("h2", null, "Updates"),
      p("Twice each trading day (Sunday–Thursday): around 3:00 PM Dhaka (preliminary) and around 4:10 PM (final)."));
  }

  // ---------- Stock page
  async function viewStock(sym) {
    let d = S.cache[sym];
    if (!d) {
      const res = await fetch(`data/stocks/${encodeURIComponent(sym)}.json`, { cache: "no-cache" });
      if (!res.ok) return h("div", null, h("a", { class: "back", href: "#top" }, "← Back"), h("p", null, `No data for ${sym}.`));
      d = S.cache[sym] = await res.json();
    }
    const m = d.metrics, info = d.info, L = d.levels, o = d.s;
    const priceBox = h("div"), volBox = h("div"), histBox = h("div");
    const kv = pairs => h("div", { class: "kv" }, pairs.flatMap(([k, v]) => [h("div", null, k), h("div", null, v)]));
    const c = Object.entries(d.contrib.short).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    const mx = Math.max(4, ...c.map(x => Math.abs(x[1])));
    const rangeBtns = h("div", { class: "chips", style: "margin-bottom:8px" },
      [["3M", 63], ["6M", 125], ["1Y", 250], ["2Y", 500]].map(([lbl, n]) =>
        h("button", { class: "chip", style: n === S.range ? "border-color:var(--ink);font-weight:700" : "", onclick: () => { S.range = n; route(); } }, lbl)));
    const legTxt = d.leg === 1 ? "Rising" : d.leg === -1 ? "Falling" : "No clear swing";
    const out = h("div", null,
      h("a", { class: "back", href: "#top", onclick: e => { if (history.length > 1) { e.preventDefault(); history.back(); } } }, "← Back"),
      h("div", { class: "hero" },
        h("div", null, h("h1", null, d.sym), h("div", { class: "muted" }, `${d.sector} · Category ${d.cat}`), h("div", null, tags(d))),
        h("div", { style: "text-align:right" }, h("div", { class: "price num" }, num(d.close)), h("div", { class: d.chg >= 0 ? "up" : "down" }, spct(d.chg) + " today"))),
      h("div", { class: "grid two" },
        h("div", { class: "card decision" },
          h("div", { class: "dh" }, h("div", null, h("h3", null, "Next 2 weeks"), h("div", { class: "small muted" }, "10 trading days · target ±3%")), badge(o.verdict)),
          expBlock(o), bs(o, true),
          h("div", { style: "display:flex;gap:22px;flex-wrap:wrap" }, moveStat(o), confStat(o), stat("rank", `${o.rank} / ${S.summary.universe}`))),
        h("div", { class: "card decision" },
          o.why.length ? [h("h4", null, "Reasons to buy"), h("ul", { class: "why" }, o.why.map(x => h("li", null, x)))] : h("h4", null, "No strong reasons to buy"),
          o.caution.length ? [h("h4", null, "Reasons for caution"), h("ul", { class: "caution" }, o.caution.map(x => h("li", null, x)))] : null)),
      h("h2", null, "Price, regular range and swings"),
      rangeBtns,
      h("div", { class: "legend" },
        h("span", null, h("i", { style: `background:${css("--ink")}` }), "Close (adjusted for bonus shares)"),
        h("span", null, h("i", { class: "area", style: `background:${css("--range")};opacity:.28` }), "Regular range (2 yrs, 10th–90th pct)"),
        h("span", null, h("i", { class: "area", style: `background:${css("--s2")};opacity:.22` }), "Current swing (3 months)"),
        h("span", null, h("i", { style: `background:${css("--muted")}` }), "Outlier low / high (2 yrs)"),
        h("span", null, h("i", { class: "dot", style: `background:${css("--buy")}` }), "Swing low"),
        h("span", null, h("i", { class: "dot", style: `background:${css("--sell")}` }), "Swing high")),
      h("div", { class: "card" }, priceBox, h("div", { class: "small muted", style: "margin-top:10px" }, "Volume (green = up day, red = down day)"), volBox),
      h("div", { class: "grid two", style: "margin-top:12px" },
        h("div", { class: "card" }, h("h3", null, "The cycle"), kv([
          ["Regular range (2 yrs)", `${tk(L.p10_all)} – ${tk(L.p90_all)}`],
          ["Outlier low / high (2 yrs)", `${tk(L.min_all)} / ${tk(L.max_all)}`],
          ["Current swing range (3 months)", `${tk(L.p10_60)} – ${tk(L.p90_60)}`],
          ["Position in regular range", pct(m.band_all)],
          ["Room to regular high", spct(d.up_room)],
          ["Drop to 2-year low", spct(d.down_risk == null ? null : -d.down_risk)],
          ["Current swing", `${legTxt}${d.leg_days != null ? ", day " + d.leg_days : ""}`],
          ["Typical rise", m.up_len != null ? `${Math.round(m.up_len)} days, ${spct(m.up_pct, 0)}` : "–"],
          ["Typical fall", m.dn_len != null ? `${Math.round(m.dn_len)} days, ${spct(m.dn_pct, 0)}` : "–"],
          ["Completed swings / regularity", `${m.n_legs ?? "–"} / ${m.regularity != null ? pct(m.regularity) : "–"}`],
        ])),
        h("div", { class: "card" }, h("h3", null, "How the outlook changed"),
          h("div", { class: "small muted", style: "margin-bottom:4px" }, "Expected 2-week change over the last 3 months"),
          histBox)),
      h("div", { class: "grid two", style: "margin-top:12px" },
        h("div", { class: "card" }, h("h3", null, "What moved the score"),
          h("div", { class: "small muted", style: "margin-bottom:6px" }, "Points each angle adds towards Buy (green) or Sell (red)"),
          c.map(([a, v]) => h("div", { class: "contrib" }, h("div", null, a),
            h("div", { class: "bar" }, h("div", { class: "mid" }), h("span", { class: v >= 0 ? "pos" : "neg", style: `width:${(Math.abs(v) / mx) * 50}%` })),
            h("div", { class: "num small", style: "text-align:right" }, (v > 0 ? "+" : "") + v.toFixed(1))))),
        h("div", { class: "card" }, h("h3", null, "Money flow & risk"), kv([
          ["This week / 4 weeks", `${spct(m.ret5)} / ${spct(m.ret20)}`],
          ["Vs market / sector (4 wks)", `${spct(m.rel_mkt20)} / ${spct(m.rel_sec20)}`],
          ["Volume vs normal (5 days)", m.vol_ratio5 != null ? Math.exp(m.vol_ratio5).toFixed(1) + "×" : "–"],
          ["Up-day vs down-day volume", m.updown_vol != null ? Math.exp(m.updown_vol).toFixed(1) + "×" : "–"],
          ["Average trade size vs normal", m.trade_size != null ? Math.exp(m.trade_size).toFixed(1) + "×" : "–"],
          ["RSI (14)", m.rsi != null ? Math.round(m.rsi) : "–"],
          ["Daily swing (4 wks)", pct(m.vol20, 1)],
          ["Upper-circuit hits (4 wks)", m.uc_hits20 ?? "–"],
          ["Median turnover", d.liq != null ? `Tk ${num(d.liq, 1)} mn/day` : "–"],
          ["Junk score", pct(m.junk_score)],
        ]))),
      h("div", { class: "grid two", style: "margin-top:12px" },
        h("div", { class: "card" }, h("h3", null, "Similar past setups"),
          d.analogs.short.length ? h("div", null,
            h("div", { class: "small muted", style: "margin:4px 0" }, `The ${d.analogs.short.length} most similar earlier days in ${d.sym} and the 2 weeks after`),
            h("div", { class: "chips" }, d.analogs.short.map(a => h("span", { class: "chip", style: "cursor:default" }, Charts.fmtDate(a.date) + " ",
              h("b", { class: a.ret >= 0 ? "up" : "down" }, spct(a.ret))))),
            h("div", { class: "small", style: "margin-top:4px" }, `Average ${spct(m.analog_ret_short)}, ${pct(m.analog_win_short)} rose`))
            : h("div", { class: "empty small" }, "Not enough history yet")),
        h("div", { class: "card" }, h("h3", null, "Company snapshot"), kv([
          ["Category", info.market_category], ["Paid-up capital", `Tk ${num(info.paid_up_capital_mn, 0)} mn`],
          ["Market cap", `Tk ${num(info.market_cap_mn, 0)} mn`], ["Face value", num(info.face_value, 0)],
          ["Reserves", `Tk ${num(info.reserve_mn, 0)} mn`],
          ["Sponsor / Govt", `${num(info.sponsor_pct, 1)}% / ${num(info.govt_pct, 1)}%`],
          ["Institute / Foreign / Public", `${num(info.institute_pct, 1)}% / ${num(info.foreign_pct, 1)}% / ${num(info.public_pct, 1)}%`],
          ...d.actions.map(a => [`Bonus/dividend reset ${Charts.fmtDate(a.date)}`, `≈${a.pct}%`]),
        ]))));

    requestAnimationFrame(() => {
      const s = d.series, n = s.dates.length, from = Math.max(0, n - S.range);
      const cut = a => a.slice(from);
      const dates = cut(s.dates);
      const at = new Map(s.dates.map((x, i) => [x, i]));
      const markers = d.pivots.map(p => ({ i: at.get(p.date) - from, v: p.price, color: p.kind > 0 ? css("--sell") : css("--buy") })).filter(p => p.i >= 0);
      Charts.line(priceBox, {
        dates, height: 320, label: `${d.sym} price`, yFormat: v => num(v, v < 10 ? 2 : 1),
        bands: [
          { lo: cut(s.p10_all), hi: cut(s.p90_all), color: css("--range"), opacity: 0.16, name: "Regular range" },
          { lo: cut(s.p10_60), hi: cut(s.p90_60), color: css("--s2"), opacity: 0.12, name: "Current swing" },
        ],
        series: [
          { name: "Outlier high", values: cut(s.max_all), color: css("--muted"), width: 1, endLabel: false },
          { name: "Outlier low", values: cut(s.min_all), color: css("--muted"), width: 1, endLabel: false },
          { name: "Close", values: cut(s.close), color: css("--ink"), width: 2, endLabel: false },
        ],
        markers,
      });
      const cl = s.close;
      Charts.columns(volBox, {
        dates, height: 100, name: "Volume", color: css("--muted"), values: cut(s.volume), fmt: v => Math.round(v).toLocaleString(),
        yFormat: v => v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? Math.round(v / 1e3) + "K" : v,
        colors: cut(cl.map((x, i) => i && x < cl[i - 1] ? css("--sell") : css("--buy"))),
      });
      const hs = d.history.short;
      Charts.line(histBox, {
        dates: hs.dates, height: 200, label: "Outlook history", yFormat: v => spct(v),
        series: [{ name: "Expected 2-week change", values: hs.exp, color: css("--s1"), fmt: v => spct(v) }],
      });
    });
    return out;
  }

  // ---------- routing
  const TABS = [["top", "Top picks"], ["all", "All shares"], ["sectors", "Sectors"], ["track", "Track record"], ["how", "How it works"]];
  async function route() {
    const hash = decodeURIComponent(location.hash.slice(1)) || "top";
    const [view, arg] = hash.split("/");
    document.querySelectorAll("nav.tabs a").forEach(a => a.classList.toggle("on", a.dataset.v === view));
    let node;
    try {
      if (view === "s" && arg) node = await viewStock(arg);
      else if (view === "sectors") node = viewSectors();
      else if (view === "all") node = viewAll();
      else if (view === "track") node = viewTrack();
      else if (view === "how") node = viewHow();
      else node = viewTop();
    } catch (e) {
      console.error(e);
      node = h("div", { class: "note" }, "This page couldn't be shown. Please refresh (Ctrl+Shift+R on a computer). " +
        "If it keeps happening, the site may be mid-update; try again in a few minutes.");
    }
    const a = app(); a.textContent = ""; a.appendChild(node);
    if (S.lastHash !== hash) window.scrollTo(0, 0);
    S.lastHash = hash;
  }

  function setTheme(t) {
    if (t === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
    store("theme", t);
    document.getElementById("theme").textContent = { auto: "Theme: auto", light: "Theme: light", dark: "Theme: dark" }[t];
  }

  async function init() {
    setTheme(load("theme") || "auto");
    document.getElementById("theme").addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") || "auto";
      setTheme(cur === "auto" ? "light" : cur === "light" ? "dark" : "auto"); route();
    });
    const nav = document.querySelector("nav.tabs");
    TABS.forEach(([v, label]) => nav.appendChild(h("a", { href: "#" + v, "data-v": v }, label)));
    try {
      const [s, t] = await Promise.all([
        fetch("data/summary.json", { cache: "no-cache" }).then(r => r.json()),
        fetch("data/track.json", { cache: "no-cache" }).then(r => r.json()),
      ]);
      if (!s.horizons || !s.horizons.short || s.horizons.long) throw new Error("unexpected data format");
      S.summary = s; S.track = t;
      s.stocks.forEach(r => { S.bySym[r.sym] = r; });
      document.getElementById("asof").textContent =
        `Data to ${Charts.fmtDate(s.asof)} · ${s.run === "prelim" ? "preliminary (3 PM)" : "final"} · updated ${s.generated} Dhaka`;
    } catch (e) {
      app().textContent = "Could not load the data. Please refresh in a minute (Ctrl+Shift+R); the site may be mid-update.";
      return;
    }
    window.addEventListener("hashchange", route);
    let rt, lastW = window.innerWidth;
    window.addEventListener("resize", () => {
      if (window.innerWidth === lastW) return;   // ignore mobile address-bar height changes
      lastW = window.innerWidth; clearTimeout(rt); rt = setTimeout(route, 200);
    });
    route();
  }
  init();
})();
