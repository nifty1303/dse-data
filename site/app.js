// DSE Signals front end. Reads data/summary.json, data/track.json, data/stocks/<SYM>.json.
(function () {
  const S = { summary: null, track: null, bySym: {}, cache: {}, hz: "short", sort: { key: "s_rank", dir: 1 }, filters: {}, q: "", range: 500 };
  const app = () => document.getElementById("app");
  const K = { short: "s", long: "l" };

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
  const hzInfo = key => S.summary.horizons[key];
  const other = key => (key === "short" ? "long" : "short");
  const hzName = key => (key === "short" ? "Short term" : "Long term");
  const store = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } };
  const load = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };

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
  const moveStat = o => stat("move chance", pct(o.move), o.move, "Chance the price moves past the target either way in this timeframe");
  const confStat = o => stat("confidence", o.conf, o.conf / 100, "How far to trust this split: history, liquidity, cycle regularity, clarity");
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
  function hzSwitch() {
    const opt = (key, sub) => h("button", { class: S.hz === key ? "on" : "", onclick: () => { S.hz = key; store("hz", key); route(); } },
      hzName(key), h("small", null, sub));
    return h("div", { class: "seg", role: "tablist", "aria-label": "Timeframe" },
      opt("short", "1 week · target +2%"), opt("long", "2 months · target +10%"));
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
  function dist(key) {
    const order = ["Strong Buy", "Buy", "Lean Buy", "Lean Sell", "Sell", "Strong Sell"];
    const col = { "Strong Buy": "--buy-strong", Buy: "--buy", "Lean Buy": "--buy-wash", "Lean Sell": "--sell-wash", Sell: "--sell", "Strong Sell": "--sell-strong" };
    const ink = { "Lean Buy": "--buy-ink", "Lean Sell": "--sell-ink" };
    const v = hzInfo(key).verdicts, total = order.reduce((a, k) => a + (v[k] || 0), 0);
    return h("div", { class: "card", style: "padding:12px 16px;margin-bottom:16px" },
      h("div", { class: "small muted" }, `All ${total} shares today, ${hzName(key).toLowerCase()}`),
      h("div", { class: "dist" }, order.filter(k => v[k]).map(k => h("span", {
        style: `flex:${v[k]};background:var(${col[k]});color:${ink[k] ? `var(${ink[k]})` : "#fff"}`, title: `${k}: ${v[k]}` }, v[k] / total > 0.06 ? `${k} ${v[k]}` : ""))),
      h("div", { class: "chips small" }, order.filter(k => v[k]).map(k => h("span", null, badge(k), " ", v[k]))));
  }

  function expBlock(o) {
    if (o.exp == null) return null;
    const pre = o.verdict_pre && o.verdict_pre !== o.verdict ? ` Without the seasonal adjustment: ${o.verdict_pre}.` : "";
    return h("div", { class: "expbox" },
      h("div", null, h("b", { class: o.exp >= 0.05 ? "up" : o.exp < 0 ? "down" : "" }, spct(o.exp)), " expected 2-month change"),
      h("div", { class: "small muted" }, `Outlook ${spct(o.outlook)} · cycle ${spct(o.tilt)} · season ${spct(o.season)}.${pre}`));
  }
  function pickCard(r, pos, key, side) {
    const o = r[K[key]], oo = r[K[other(key)]];
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
      h("div", { class: "other" }, `${hzName(other(key))}:`, badge(oo.verdict), oo.exp != null ? `expected ${spct(oo.exp)}` : `Buy ${pct(oo.dir)} · move ${pct(oo.move)}`,
        o.days_top > 1 && side !== "sell" ? h("span", null, ` · ${o.days_top} days in this list`) : null));
  }
  function miniRow(r, key) {
    const o = r[K[key]];
    return h("div", { class: "mini", onclick: () => go(r.sym) },
      h("div", null, h("span", { class: "sym" }, r.sym), " ", h("span", { class: "muted small" },
        `${num(r.close)} · ${o.exp != null ? "expected " + spct(o.exp) : "move " + pct(o.move)}`)),
      badge(o.verdict), bs(o));
  }

  // ---------- views
  const NON_SHARE = new Set(["Corporate Bond", "Debenture"]);
  function pickList(key, side, sector) {
    const k = K[key], by = side === "sell" ? "sscore" : "score";
    const pool = S.summary.stocks.filter(r => !NON_SHARE.has(r.sector) && (!sector || r.sector === sector))
      .sort((a, b) => b[k][by] - a[k][by]);
    if (sector) return pool.slice(0, 20);
    const out = [], count = {};
    for (const r of pool) {                       // at most 4 per sector when showing all sectors
      if (out.length >= 20) break;
      if ((count[r.sector] || 0) < 4) { out.push(r); count[r.sector] = (count[r.sector] || 0) + 1; }
    }
    return out;
  }
  function seasonNote(key) {
    const x = hzInfo(key);
    if (key !== "long" || x.season_adj == null || Math.abs(x.season_adj) < 0.01) return null;
    const mName = new Date(2000, +x.month - 1, 1).toLocaleString("en-US", { month: "long" });
    const avg = x.season_by_month[x.month];
    return h("div", { class: "mood " + (x.season_adj < 0 ? "Caution" : "Friendly"), role: "note" },
      h("div", { class: "icon", "aria-hidden": "true" }, "◷"),
      h("div", null, h("div", { class: "label" }, `Seasonal ${x.season_adj < 0 ? "headwind" : "tailwind"}: ${spct(x.season_adj)} applied to every share`),
        h("div", null, `In the last two years, 2-month periods centred on ${mName} returned ${spct(avg)} for the average share, against ${spct(x.base)} normally` +
          (x.season_adj < 0 ? " (Q4 is DSE's dry season: turnover runs at about 60–75% of normal). " : ". ") +
          "Half of that difference is applied, since there are only two years of history. Each card shows what its verdict would be without it.")));
  }
  function viewTop() {
    const s = S.summary, key = S.hz, hzd = hzInfo(key), side = S.side || "buy", sector = S.sector || "";
    const list = pickList(key, side, sector);
    const sectors = [...new Set(s.stocks.map(r => r.sector))].filter(x => !NON_SHARE.has(x)).sort();
    const sideBtn = (v, label) => h("button", { class: side === v ? "on" : "", onclick: () => { S.side = v; route(); } }, label);
    const title = `Top ${list.length} to ${side === "sell" ? "sell or avoid" : "buy"}${sector ? " in " + sector : ""} · ${hzName(key).toLowerCase()}`;
    const sub = side === "sell"
      ? (key === "short" ? "Highest odds of falling more than 2% over the next 7 days." : "Lowest expected change over the next 60 days, including the highest odds of a 10%+ fall.") +
        " Junk shares can still spike, so the risk runs both ways."
      : (key === "short" ? "Shares most likely to gain more than 2% over the next 7 days rather than lose 2%."
        : "Shares with the highest expected change over the next 60 days. Verdict: under +5% Sell, +5% to +15% Lean Buy, +15% or more Strong Buy.");
    const showExtras = side === "buy" && !sector;
    const noneClear = side === "buy" && key === "long" && list.length && list.every(r => r.l.verdict === "Sell");
    return h("div", null,
      moodBanner(s.mood),
      seasonNote(key),
      h("div", { class: "page-head" },
        h("div", null, h("h1", null, title), h("p", { class: "sub", style: "margin:0" }, sub + (sector ? "" : " At most 4 per sector."))),
        hzSwitch()),
      h("div", { class: "filters" },
        h("div", { class: "seg", role: "tablist", "aria-label": "Buy or sell" }, sideBtn("buy", "Buy"), sideBtn("sell", "Sell")),
        h("select", { "aria-label": "Sector", onchange: e => { S.sector = e.target.value; route(); } },
          h("option", { value: "" }, "All sectors"), sectors.map(x => h("option", { value: x, selected: sector === x ? "" : null }, x)))),
      dist(key),
      noneClear ? h("div", { class: "note", style: "margin-bottom:12px" },
        "No share reaches the +5% Lean Buy line after the seasonal adjustment today, so every verdict is Sell. " +
        "These are still the best-placed shares if you do buy; each card shows its verdict without the seasonal dip.") : null,
      list.length ? h("div", { class: "picks" }, list.map((r, i) => pickCard(r, i + 1, key, side))) : h("div", { class: "empty" }, "No shares in this sector."),
      showExtras ? h("div", { class: "grid two", style: "margin-top:14px" },
        h("div", { class: "card" }, h("h3", null, "New in the list today"),
          hzd.new_entries.length ? h("div", { class: "chips" }, hzd.new_entries.map(x => h("button", { class: "chip", onclick: () => go(x) }, x)))
            : h("div", { class: "empty small" }, "No changes since yesterday")),
        h("div", { class: "card" }, h("h3", null, "Dropped out today"),
          hzd.dropped.length ? h("div", { class: "chips" }, hzd.dropped.map(x => h("button", { class: "chip", onclick: () => go(x) }, x)))
            : h("div", { class: "empty small" }, "No changes since yesterday"))) : null,
      showExtras && Object.keys(hzd.also).length ? h("div", null,
        h("h2", null, "Also strong (left out only by the 4-per-sector cap)"),
        h("div", { class: "grid two" }, Object.entries(hzd.also).map(([sec, list]) =>
          h("div", { class: "card" }, h("h3", null, sec), list.map(x => miniRow(S.bySym[x], key)))))) : null);
  }

  function viewSectors() {
    const s = S.summary, key = S.hz, hzd = hzInfo(key);
    const long = key === "long";
    const secs = Object.entries(hzd.sectors).sort((a, b) => long ? b[1].avg_exp - a[1].avg_exp : b[1].avg_dir - a[1].avg_dir);
    return h("div", null,
      moodBanner(s.mood),
      h("div", { class: "page-head" },
        h("div", null, h("h1", null, "By sector"), h("p", { class: "sub", style: "margin:0" },
          `Top 5 to buy and top 5 to sell in every sector. Sectors are ordered by their average ${long ? "expected 2-month change" : "Buy share"}.`)), hzSwitch()),
      seasonNote(key),
      h("div", { class: "grid two" }, secs.map(([name, v]) => h("div", { class: "card" },
        h("h3", { style: "display:flex;justify-content:space-between;gap:8px" }, h("span", null, name),
          h("span", { class: "small muted num" }, `${v.count} listed · ${long ? "avg expected " + spct(v.avg_exp) : "avg Buy " + pct(v.avg_dir)} · 4 wks ${spct(v.ret20)}`)),
        h("div", { class: "col-title" }, "Top buy"), v.buy.map(x => miniRow(S.bySym[x], key)),
        h("div", { class: "col-title" }, "Top sell"), v.sell.map(x => miniRow(S.bySym[x], key))))));
  }

  // ----- All shares: instant search cards + sortable table
  const COLS = [
    ["sym", "Share", r => r.sym, r => r.sym],
    ["sector", "Sector", r => r.sector, r => r.sector],
    ["close", "Price", r => num(r.close), r => r.close, "r"],
    ["chg", "Day", r => spct(r.chg), r => r.chg, "r"],
    ["s_rank", "Short verdict", r => badge(r.s.verdict), r => r.s.rank],
    ["s_dir", "Buy", r => pct(r.s.dir), r => r.s.dir, "r g"],
    ["s_sell", "Sell", r => pct(1 - r.s.dir), r => 1 - r.s.dir, "r rd"],
    ["s_move", "Move", r => pct(r.s.move), r => r.s.move, "r"],
    ["l_rank", "Long verdict", r => badge(r.l.verdict), r => r.l.rank],
    ["l_exp", "Expected", r => spct(r.l.exp), r => r.l.exp, "r"],
    ["l_dir", "Buy", r => pct(r.l.dir), r => r.l.dir, "r g"],
    ["l_sell", "Sell", r => pct(1 - r.l.dir), r => 1 - r.l.dir, "r rd"],
    ["band", "2-yr range", r => pct(r.band), r => r.band, "r"],
    ["type", "Type", r => r.type, r => r.type],
  ];
  function quickCard(r) {
    const half = key => {
      const o = r[K[key]];
      return h("div", null, h("h4", null, h("span", null, hzName(key)), badge(o.verdict)), bs(o),
        h("div", { class: "mv" }, (o.exp != null ? `Expected ${spct(o.exp)} · ` : "") + `Move chance ${pct(o.move)} · Confidence ${o.conf}`));
    };
    return h("div", { class: "qcard", onclick: () => go(r.sym) },
      h("div", { class: "head" }, h("div", null, h("b", { style: "font-size:16px" }, r.sym), " ", h("span", { class: "muted small" }, `${r.sector} · Cat ${r.cat}`)),
        h("div", { class: "num" }, h("b", null, num(r.close)), " ", h("span", { class: "small " + (r.chg >= 0 ? "up" : "down") }, spct(r.chg)))),
      h("div", { class: "hz" }, half("short"), half("long")));
  }
  function viewAll() {
    const s = S.summary, f = S.filters;
    const results = h("div", { class: "results", "aria-live": "polite" });
    const box = h("div", { class: "tbl-wrap" });
    const count = h("span", { class: "muted small" });
    const opts = key => [...new Set(s.stocks.map(r => r[key]))].sort();
    const sel = (key, label) => h("select", { onchange: e => { f[key] = e.target.value; render(); } },
      h("option", { value: "" }, "All " + label), opts(key).map(v => h("option", { value: v, selected: f[key] === v ? "" : null }, v)));
    function matches() {
      const q = S.q.trim().toUpperCase();
      return s.stocks.filter(r => (!q || r.sym.includes(q)) && ["sector", "type", "cat"].every(k => !f[k] || r[k] === f[k]));
    }
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
      const rows = matches().slice().sort((a, b) => {
        const x = col[3](a), y = col[3](b);
        if (x == null) return 1; if (y == null) return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * S.sort.dir;
      });
      count.textContent = `${rows.length} of ${s.stocks.length} shares`;
      const table = h("table", null,
        h("thead", null,
          h("tr", null, h("th", { class: "grp", colspan: 4 }), h("th", { class: "grp", colspan: 4 }, "Short term · 1 week"),
            h("th", { class: "grp", colspan: 4 }, "Long term · 2 months"), h("th", { class: "grp", colspan: 2 })),
          h("tr", null, COLS.map(([k, label, , , cls]) => h("th", {
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
      h("p", { class: "sub" }, "Start typing to see a share's verdict for both timeframes instantly. Every listed instrument is here; click any row for the full picture."),
      h("div", { class: "search" }, h("span", { class: "ico", "aria-hidden": "true" }, "⌕"), input),
      results,
      h("div", { class: "filters" }, sel("sector", "sectors"), sel("type", "types"), sel("cat", "categories"), count),
      box);
  }

  // ----- Track record
  function tile(label, value, note, cls) {
    return h("div", { class: "card tile" }, h("div", { class: "t-label" }, label),
      h("div", { class: "t-value " + (cls || "") }, value), note ? h("div", { class: "t-note" }, note) : null);
  }
  function viewTrack() {
    const key = S.hz, t = S.track[key], s = t.summary, hzd = hzInfo(key);
    const chart = h("div");
    const short = key === "short";
    const per = short ? "week" : "2-month hold";
    const tiles = short ? [
      tile("Top 20 portfolio", spct(s.top20_total), "after costs, compounded", s.top20_total >= 0 ? "up" : "down"),
      tile("Market index", spct(s.market_total), "cap-weighted"),
      tile("All shares, equal amounts", spct(s.all_total), "buy everything"),
      tile("Weeks beating the index", pct(s.beat_market), `${s.periods} weeks`),
      tile("Picks that rose", pct(s.avg_hit_rate), "average per week"),
      tile("Picks that gained >2%", pct(s.avg_target_rate), "the short-term target"),
    ] : [
      tile("Top 20, average 2-month result", spct(s.top20_total), "after costs", s.top20_total >= 0 ? "up" : "down"),
      tile("Market index", spct(s.market_total), "same periods"),
      tile("All shares, equal amounts", spct(s.all_total), "same periods"),
      tile("Periods beating the index", pct(s.beat_market), `${s.periods} weekly start dates`),
      tile("Picks that rose", pct(s.avg_hit_rate), "after 2 months"),
      tile("Picks that gained >10%", pct(s.avg_target_rate), "the long-term target"),
    ];
    const vsIdx = s.top20_total - s.market_total, vsAll = s.top20_total - s.all_total;
    const note = `Reading this honestly: the model is better at spotting shares likely to fall than shares about to rise. ` +
      `The Top 20 ${vsIdx >= 0 ? "beat" : "trailed"} the market index by ${Math.abs(vsIdx * 100).toFixed(1)} points ` +
      `and ${vsAll >= 0 ? "beat" : "trailed"} an equal-weight basket of every share by ${Math.abs(vsAll * 100).toFixed(1)} points ` +
      `(${short ? "compounded over the period" : "average per 2-month hold"}). ` +
      `On an average ${per}, ${pct(s.avg_hit_rate)} of the picks rose while ${pct(s.avg_sell_fell)} of the sell list fell. ` +
      (short ? "" : `Long-term results overlap (a new 2-month hold starts every week), so treat them as a rough guide from only about ${Math.max(1, Math.round(s.periods * 5 / hzd.days))} independent periods. `) +
      "Use the scores as odds, not certainties.";
    const out = h("div", null,
      h("div", { class: "page-head" },
        h("div", null, h("h1", null, "Track record"),
          h("p", { class: "sub", style: "margin:0" }, `Every week the Top 20 is bought in equal amounts and held for ${hzd.label}, paying 0.5% brokerage each way. ` +
            `The model is retrained monthly on data available at the time, so these results (${Charts.fmtDate(s.start)} – ${Charts.fmtDate(s.end)}) are periods it never saw while learning.`)),
        hzSwitch()),
      h("div", { class: "grid tiles" }, tiles),
      h("h2", null, short ? "Growth of Tk 100" : "2-month result by start week"),
      h("div", { class: "legend" },
        h("span", null, h("i", { style: `background:${css("--s1")}` }), "Top 20"),
        h("span", null, h("i", { style: `background:${css("--s2")}` }), "Market index"),
        h("span", null, h("i", { style: `background:${css("--s3")}` }), "All shares"),
        h("span", null, h("i", { style: `background:${css("--s4")}` }), "Sell list")),
      h("div", { class: "card" }, chart),
      h("div", { class: "note", style: "margin-top:12px" }, note),
      short ? [
        h("h2", null, "Do the Buy / Sell splits come true?"),
        h("p", { class: "sub" }, `Unseen predictions grouped by their Buy share, against how often the share really rose or fell more than ${pct(hzd.thr)}.`),
        h("div", { class: "tbl-wrap" }, h("table", null,
          h("thead", null, h("tr", null, ["Predicted", "Cases", "Avg Buy share", `Rose >${pct(hzd.thr)}`, `Fell >${pct(hzd.thr)}`, "Actual Buy share", "Avg return"]
            .map((x, i) => h("th", { class: i ? "r" : "" }, x)))),
          h("tbody", null, t.calibration.map(c => h("tr", { style: "cursor:default" }, h("td", null, c.bucket), h("td", { class: "r" }, (c.n || 0).toLocaleString()),
            h("td", { class: "r" }, pct(c.predicted)), h("td", { class: "r g" }, pct(c.rose)), h("td", { class: "r rd" }, pct(c.fell)),
            h("td", { class: "r" }, pct(c.realized_split)), h("td", { class: "r" }, spct(c.avg_return, 2))))))),
      ] : [
        h("h2", null, "Does the expected change come true?"),
        h("p", { class: "sub" }, "Unseen predictions grouped by expected 2-month change, against what really happened. The test months were a rally, so actual returns run higher than expected across the board; the order is what matters."),
        h("div", { class: "tbl-wrap" }, h("table", null,
          h("thead", null, h("tr", null, ["Expected change", "Cases", "Avg expected", "Actual avg", "Actual median", "Rose >10%", "Fell >10%"]
            .map((x, i) => h("th", { class: i ? "r" : "" }, x)))),
          h("tbody", null, t.calibration.map(c => h("tr", { style: "cursor:default" }, h("td", null, c.bucket), h("td", { class: "r" }, (c.n || 0).toLocaleString()),
            h("td", { class: "r" }, spct(c.predicted)), h("td", { class: "r" }, spct(c.avg_return)), h("td", { class: "r" }, spct(c.median_return)),
            h("td", { class: "r g" }, pct(c.rose)), h("td", { class: "r rd" }, pct(c.fell))))))),
        h("h2", null, "Does the 2-year cycle position help?"),
        h("p", { class: "sub" }, `Each weight adds the cycle tilt (average excess return seen in each zone of the 2-year range, learned only from past data) on top of the odds. A weight is used only if it beats the odds alone. Chosen weight: ${t.extra.cycle_weight}.`),
        h("div", { class: "tbl-wrap" }, h("table", null,
          h("thead", null, h("tr", null, ["Cycle weight", "Top 20 avg per 2 months", "All shares", "Periods beating index"].map((x, i) => h("th", { class: i ? "r" : "" }, x)))),
          h("tbody", null, t.extra.trials.map(x => h("tr", { style: "cursor:default" + (x.w === t.extra.cycle_weight ? ";font-weight:700" : "") },
            h("td", null, x.w + (x.w === t.extra.cycle_weight ? " (used)" : "")), h("td", { class: "r" }, spct(x.top20)),
            h("td", { class: "r" }, spct(x.all)), h("td", { class: "r" }, pct(x.beat_market))))))),
        h("h2", null, "Seasonality"),
        h("p", { class: "sub" }, `Average 2-month return of the average share by the month the period is centred on, over the last two years (normal: ${spct(t.extra.base)}). Half of each month's difference from normal is applied to every share's expected change.`),
        h("div", { class: "tbl-wrap" }, h("table", null,
          h("thead", null, h("tr", null, ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].map(x => h("th", { class: "r" }, x)))),
          h("tbody", null, h("tr", { style: "cursor:default" }, ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"].map(mm => {
            const v = t.extra.season_by_month[mm];
            return h("td", { class: "r " + (v == null ? "" : v >= t.extra.base ? "up" : "down") + (mm === t.extra.month ? "" : ""), style: mm === t.extra.month ? "font-weight:800" : "" }, v == null ? "–" : spct(v));
          }))))),
      ],
      h("h2", null, `Latest ${short ? "weeks" : "start weeks"}`),
      h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Start", "Top 20", "Index", "All shares", "Picks up", "Picks"].map((x, i) => h("th", { class: i && i < 5 ? "r" : "" }, x)))),
        h("tbody", null, t.periods.slice(-12).reverse().map(w => h("tr", { style: "cursor:default" }, h("td", null, Charts.fmtDate(w.date)),
          h("td", { class: "r " + (w.top20 >= 0 ? "up" : "down") }, spct(w.top20)), h("td", { class: "r" }, spct(w.market)),
          h("td", { class: "r" }, spct(w.all)), h("td", { class: "r" }, pct(w.hit)),
          h("td", { class: "small muted", style: "white-space:normal;min-width:320px" }, w.picks.join(", "))))))));
    requestAnimationFrame(() => {
      const dates = t.periods.map(w => w.date);
      const series = short ? [
        { name: "Top 20", values: t.curve.top20, color: css("--s1") }, { name: "Index", values: t.curve.market, color: css("--s2") },
        { name: "All shares", values: t.curve.all_stocks, color: css("--s3") }, { name: "Sell list", values: t.curve.sell20, color: css("--s4") },
      ].map(x => ({ ...x, fmt: v => v.toFixed(1) })) : [
        { name: "Top 20", values: t.periods.map(w => w.top20), color: css("--s1") }, { name: "Index", values: t.periods.map(w => w.market), color: css("--s2") },
        { name: "All shares", values: t.periods.map(w => w.all), color: css("--s3") }, { name: "Sell list", values: t.periods.map(w => w.sell20), color: css("--s4") },
      ].map(x => ({ ...x, fmt: v => spct(v) }));
      Charts.line(chart, { dates, height: 280, label: "Track record", endLabels: true, series,
        yFormat: short ? v => Math.round(v) : v => Math.round(v * 100) + "%" });
    });
    return out;
  }

  function viewHow() {
    const p = (...x) => h("p", null, ...x);
    return h("div", { class: "prose" },
      h("h1", null, "How the scores work"),
      p("Everything here comes only from DSE prices, volumes and trades plus the weekly company snapshot. No news, no opinions."),
      h("h2", null, "Two timeframes"),
      h("ul", null,
        h("li", null, h("b", null, "Short term (1 week): "), "will the share gain more than 2% over the next 5 trading days (≈7 days), or lose more than 2%?"),
        h("li", null, h("b", null, "Long term (2 months): "), "what price change to expect over the next 40 trading days (≈60 days), and the odds of a 10%+ rise or fall.")),
      h("h2", null, "The long-term expected change"),
      p("Expected change = outlook from the odds + cycle tilt + seasonal adjustment."),
      h("ul", null,
        h("li", null, h("b", null, "Outlook: "), "the calibrated chance of a 10%+ rise times the average such rise, plus the chance of a 10%+ fall times the average such fall, plus the rest times the average small move."),
        h("li", null, h("b", null, "Cycle tilt: "), "the extra return seen in each zone of the 2-year range, learned only from past data. The backtest tests several weights and keeps one only if it improves the Top 20 (see Track record)."),
        h("li", null, h("b", null, "Seasonal adjustment: "), "how 2-month periods centred on the coming month did for the average share versus normal, halved because there are only two years of history. Q4 is DSE's dry season (turnover about 60–75% of normal)."),
        h("li", null, h("b", null, "Long-term verdict: "), "under +5% = Sell, +5% to +15% = Lean Buy, +15% or more = Strong Buy.")),
      h("h2", null, "What each number means"),
      h("ul", null,
        h("li", null, h("b", null, "Buy / Sell split (adds to 100%): "), "if the share does make a big move, how likely it is to be up (green) versus down (red)."),
        h("li", null, h("b", null, "Move chance: "), "how likely it is to move past the target at all. A low move chance means the share will probably just drift, even if the split looks good."),
        h("li", null, h("b", null, "Short-term verdict: "), "Strong Buy (Buy share 72%+), Buy (58%+), Lean Buy (50%+), Lean Sell (42%+), Sell (28%+), Strong Sell (below 28%)."),
        h("li", null, h("b", null, "Confidence (0–100): "), "how much history the share has, how liquid it is, how regular its cycles are, and how clear-cut today's split is. Junk shares are scaled down by a quarter, dead ones by half."),
        h("li", null, h("b", null, "Ranking: "), "the Top 20 ranks by the odds of the gain minus the odds of the loss, at most 4 shares per sector. Backtests showed ranking on gain odds alone just picked volatile junk.")),
      h("h2", null, "Ranges"),
      h("ul", null,
        h("li", null, h("b", null, "Regular range: "), "the 10th to 90th percentile of all closing prices over the last 2 years (everything available so far)."),
        h("li", null, h("b", null, "Outlier low / high: "), "the true lowest and highest close in those 2 years."),
        h("li", null, h("b", null, "Current swing: "), "the same percentiles over the last 3 months, a lighter band on the chart. Swings (rises and falls) are found automatically with a threshold scaled to each share's volatility.")),
      h("h2", null, "The angles the model looks at"),
      p("Cycle position, trend & momentum (returns, moving averages, RSI), money flow (volume vs normal, up-day vs down-day volume, trade size), liquidity, risk (volatility, circuit hits, drawdown), relative strength vs market and sector, fundamentals (category, holdings, reserves), junk pattern (volume spikes, circuit runs, pumps, small paid-up capital) and similar past setups in the same share."),
      p("Market mood is shown as a banner but is not fed to the model: with only two years of history the model would learn what the market happened to do rather than which shares beat others."),
      h("h2", null, "How it learns and stays honest"),
      p("A gradient-boosted decision-tree model learns from every share and day. It is retrained monthly in the backtest using only data available at the time. Its odds are calibrated so they match how often things actually happened over the full two years, not just the recent months."),
      h("h2", null, "Bonus shares"),
      p("DSE caps daily moves at about 10%, so a larger overnight drop with an opening gap is treated as a record-date adjustment (bonus, dividend) and earlier prices are scaled so charts and ranges stay continuous."),
      h("h2", null, "Limits"),
      h("ul", null,
        h("li", null, "Only two years of data, so slow cyclers have only a few complete cycles, and long-term results rest on few independent periods."),
        h("li", null, "Fundamentals come from the latest weekly snapshot and are applied to the past as-is."),
        h("li", null, "It cannot see news, announcements or manipulation before it shows in the data."),
        h("li", null, "This is a research tool, not financial advice.")),
      h("h2", null, "Updates"),
      p("Twice each trading day (Sunday–Thursday): around 3:00 PM Dhaka (preliminary) and around 4:10 PM (final)."));
  }

  // ----- Stock page
  async function viewStock(sym) {
    let d = S.cache[sym];
    if (!d) {
      const res = await fetch(`data/stocks/${encodeURIComponent(sym)}.json`, { cache: "no-cache" });
      if (!res.ok) return h("div", null, h("a", { class: "back", href: "#top" }, "← Back"), h("p", null, `No data for ${sym}.`));
      d = S.cache[sym] = await res.json();
    }
    const m = d.metrics, info = d.info, L = d.levels;
    const priceBox = h("div"), volBox = h("div"), histBox = h("div");
    const kv = pairs => h("div", { class: "kv" }, pairs.flatMap(([k, v]) => [h("div", null, k), h("div", null, v)]));
    const decision = key => {
      const o = d[K[key]], hzd = hzInfo(key);
      return h("div", { class: "card decision" },
        h("div", { class: "dh" }, h("div", null, h("h3", null, hzName(key)), h("div", { class: "small muted" }, `${hzd.long_label} · target ±${pct(hzd.thr)}`)), badge(o.verdict)),
        expBlock(o),
        bs(o, true),
        h("div", { style: "display:flex;gap:22px;flex-wrap:wrap" }, moveStat(o), confStat(o),
          stat("rank", `${o.rank} / ${S.summary.universe}`)),
        o.why.length ? [h("h4", null, "Reasons to buy"), h("ul", { class: "why" }, o.why.map(x => h("li", null, x)))] : null,
        o.caution.length ? [h("h4", null, "Reasons for caution"), h("ul", { class: "caution" }, o.caution.map(x => h("li", null, x)))] : null);
    };
    const contrib = key => {
      const c = Object.entries(d.contrib[key]).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
      const mx = Math.max(4, ...c.map(x => Math.abs(x[1])));
      return h("div", { class: "card" }, h("h3", null, `What moved the ${hzName(key).toLowerCase()} score`),
        h("div", { class: "small muted", style: "margin-bottom:6px" }, "Points each angle adds towards Buy (green) or Sell (red)"),
        c.map(([a, v]) => h("div", { class: "contrib" }, h("div", null, a),
          h("div", { class: "bar" }, h("div", { class: "mid" }), h("span", { class: v >= 0 ? "pos" : "neg", style: `width:${(Math.abs(v) / mx) * 50}%` })),
          h("div", { class: "num small", style: "text-align:right" }, (v > 0 ? "+" : "") + v.toFixed(1)))));
    };
    const rangeBtns = h("div", { class: "chips", style: "margin-bottom:8px" },
      [["3M", 63], ["6M", 125], ["1Y", 250], ["2Y", 500]].map(([lbl, n]) =>
        h("button", { class: "chip", style: n === S.range ? "border-color:var(--ink);font-weight:700" : "", onclick: () => { S.range = n; route(); } }, lbl)));
    const legTxt = d.leg === 1 ? "Rising" : d.leg === -1 ? "Falling" : "No clear swing";
    const out = h("div", null,
      h("a", { class: "back", href: "#top", onclick: e => { if (history.length > 1) { e.preventDefault(); history.back(); } } }, "← Back"),
      h("div", { class: "hero" },
        h("div", null, h("h1", null, d.sym), h("div", { class: "muted" }, `${d.sector} · Category ${d.cat}`), h("div", null, tags(d))),
        h("div", { style: "text-align:right" }, h("div", { class: "price num" }, num(d.close)), h("div", { class: d.chg >= 0 ? "up" : "down" }, spct(d.chg) + " today"))),
      h("div", { class: "grid two" }, decision("short"), decision("long")),
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
        h("div", { class: "card" }, h("h3", null, "How the odds changed"),
          h("div", { class: "legend" },
            h("span", null, h("i", { style: `background:${css("--s1")}` }), "Short-term Buy share"),
            h("span", null, h("i", { style: `background:${css("--s2")}` }), "Long-term Buy share"),
            h("span", null, h("i", { style: `background:${css("--muted")}` }), "Short-term move chance")),
          histBox)),
      h("div", { class: "grid two", style: "margin-top:12px" }, contrib("short"), contrib("long")),
      h("div", { class: "grid two", style: "margin-top:12px" },
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
        ])),
        h("div", { class: "card" }, h("h3", null, "Similar past setups"),
          ["short", "long"].map(key => d.analogs[key].length ? h("div", { style: "margin-bottom:10px" },
            h("div", { class: "small muted", style: "margin:4px 0" }, `${hzName(key)}: the ${d.analogs[key].length} most similar earlier days and the ${hzInfo(key).label} after`),
            h("div", { class: "chips" }, d.analogs[key].map(a => h("span", { class: "chip", style: "cursor:default" }, Charts.fmtDate(a.date) + " ",
              h("b", { class: a.ret >= 0 ? "up" : "down" }, spct(a.ret))))),
            h("div", { class: "small", style: "margin-top:4px" }, `Average ${spct(m["analog_ret_" + key])}, ${pct(m["analog_win_" + key])} rose`))
            : h("div", { class: "empty small" }, `${hzName(key)}: not enough history yet`)))),
      h("div", { class: "grid two", style: "margin-top:12px" },
        h("div", { class: "card" }, h("h3", null, "Company snapshot"), kv([
          ["Category", info.market_category], ["Paid-up capital", `Tk ${num(info.paid_up_capital_mn, 0)} mn`],
          ["Market cap", `Tk ${num(info.market_cap_mn, 0)} mn`], ["Face value", num(info.face_value, 0)],
          ["Reserves", `Tk ${num(info.reserve_mn, 0)} mn`],
          ["Sponsor / Govt", `${num(info.sponsor_pct, 1)}% / ${num(info.govt_pct, 1)}%`],
          ["Institute / Foreign / Public", `${num(info.institute_pct, 1)}% / ${num(info.foreign_pct, 1)}% / ${num(info.public_pct, 1)}%`],
        ])),
        h("div", { class: "card" }, h("h3", null, "Bonus / dividend adjustments"),
          d.actions.length ? kv(d.actions.map(a => [Charts.fmtDate(a.date), `≈${a.pct}% price reset`]))
            : h("div", { class: "empty small" }, "None detected in the last two years"))));

    requestAnimationFrame(() => {
      const s = d.series, n = s.dates.length, from = Math.max(0, n - S.range);
      const cut = a => a.slice(from);
      const dates = cut(s.dates);
      const at = new Map(s.dates.map((x, i) => [x, i]));
      const markers = d.pivots.map(p => ({ i: at.get(p.date) - from, v: p.price, color: p.kind > 0 ? css("--sell") : css("--buy") })).filter(p => p.i >= 0);
      const f2 = v => num(v, v < 10 ? 2 : 1);
      Charts.line(priceBox, {
        dates, height: 320, label: `${d.sym} price`, yFormat: f2,
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
      const c = s.close;
      Charts.columns(volBox, {
        dates, height: 100, name: "Volume", color: css("--muted"), values: cut(s.volume), fmt: v => Math.round(v).toLocaleString(),
        yFormat: v => v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? Math.round(v / 1e3) + "K" : v,
        colors: cut(c.map((x, i) => i && x < c[i - 1] ? css("--sell") : css("--buy"))),
      });
      const hs = d.history.short, hl = d.history.long;
      const lmap = new Map(hl.dates.map((x, i) => [x, hl.dir[i]]));
      Charts.line(histBox, {
        dates: hs.dates, height: 200, label: "Odds history", yFormat: v => Math.round(v * 100) + "%",
        series: [
          { name: "Short-term Buy share", values: hs.dir, color: css("--s1"), fmt: v => pct(v) },
          { name: "Long-term Buy share", values: hs.dates.map(x => lmap.get(x)), color: css("--s2"), fmt: v => pct(v) },
          { name: "Short-term move chance", values: hs.move, color: css("--muted"), width: 1.5, fmt: v => pct(v) },
        ],
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
    S.hz = load("hz") === "long" ? "long" : "short";
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
      if (!s.horizons) throw new Error("old data format");
      S.summary = s; S.track = t;
      s.stocks.forEach(r => { S.bySym[r.sym] = r; });
      document.getElementById("asof").textContent =
        `Data to ${Charts.fmtDate(s.asof)} · ${s.run === "prelim" ? "preliminary (3 PM)" : "final"} · updated ${s.generated} Dhaka`;
    } catch (e) {
      app().textContent = "Could not load the data files. If you opened index.html directly, serve the folder over HTTP instead.";
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
