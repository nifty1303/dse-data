// DSE Signals front end. Reads data/summary.json, data/track.json, data/stocks/<SYM>.json.
(function () {
  const S = { summary: null, track: null, bySym: {}, stockCache: {}, sort: { key: "rank", dir: 1 }, filters: {} };
  const app = () => document.getElementById("app");

  // ---------- tiny DOM helper (text is always set via textContent)
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
  const spct = (x, d = 1) => (x == null ? "–" : (x > 0 ? "+" : "") + (x * 100).toFixed(d) + "%");
  const num = (x, d = 2) => (x == null ? "–" : Number(x).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const go = sym => { location.hash = "#s/" + encodeURIComponent(sym); };

  // ---------- shared pieces
  function bhs(r, big) {
    return h("div", { class: big ? "bigbhs" : "c-bhs" },
      h("div", { class: "bhs", role: "img", "aria-label": `Buy ${pct(r.buy)}, Hold ${pct(r.hold)}, Sell ${pct(r.sell)}` },
        h("span", { class: "b", style: `width:${r.buy * 100}%` }),
        h("span", { class: "h", style: `width:${r.hold * 100}%` }),
        h("span", { class: "s", style: `width:${r.sell * 100}%` })),
      h("div", { class: "bhs-num" },
        h("span", null, "Buy ", h("b", null, pct(r.buy))),
        h("span", null, "Hold ", h("b", null, pct(r.hold))),
        h("span", null, "Sell ", h("b", null, pct(r.sell)))));
  }
  function gauge(r) {
    const b = r.band == null ? null : Math.max(-0.33, Math.min(1.33, r.band));
    const leg = r.leg === 1 ? "rising" : r.leg === -1 ? "falling" : "";
    const long = r.leg_typ && r.leg_days > 3 * r.leg_typ;
    const legTxt = leg ? `${leg} · day ${r.leg_days ?? "?"}${long ? " (long run)" : r.leg_typ ? " of ~" + r.leg_typ : ""}` : "no clear leg";
    return h("div", { class: "c-gauge" },
      h("div", { class: "gauge", title: "Shaded = regular low-to-high range (last 60 days)" },
        h("div", { class: "reg" }),
        b == null ? null : h("div", { class: "pin", style: `left:${20 + b * 60}%` })),
      h("div", { class: "gauge-lbl" }, h("span", null, "low"), h("span", null, "high")),
      h("div", { class: "small muted" }, legTxt));
  }
  function tags(r) {
    const cls = /junk/i.test(r.type) ? "tag junk" : /Dead/.test(r.type) ? "tag dead" : "tag";
    return [h("span", { class: cls }, r.type),
      r.stage && r.stage !== "Quiet" ? h("span", { class: /junk/i.test(r.type) ? "tag junk" : "tag" }, r.stage) : null,
      h("span", { class: "tag" }, "Cat " + r.cat)];
  }
  function move(r) {
    if (r.rank_prev == null) return h("span", { class: "move muted" }, "new");
    const d = r.rank_prev - r.rank;
    if (d === 0) return h("span", { class: "move muted" }, "–");
    return h("span", { class: "move " + (d > 0 ? "up" : "down") }, (d > 0 ? "▲" : "▼") + Math.abs(d));
  }
  function row(r, pos, side) {
    const reasons = side === "sell" ? (r.sell_reasons || []) : r.reasons;
    return h("div", { class: "row", onclick: () => go(r.sym), tabindex: 0, onkeydown: e => e.key === "Enter" && go(r.sym) },
      h("div", null, h("span", { class: "rank" }, pos), move(r)),
      h("div", null, h("div", { class: "sym" }, r.sym), h("div", { class: "meta" }, r.sector), h("div", null, tags(r))),
      h("div", { class: "num" },
        h("div", { style: "font-weight:600" }, num(r.close)),
        h("div", { class: r.chg >= 0 ? "up small" : "down small" }, spct(r.chg)),
        r.days_top > 1 && side !== "sell" ? h("div", { class: "small muted" }, `${r.days_top} days in list`) : null),
      bhs(r),
      h("div", { class: "conf c-conf" }, r.conf, h("small", null, "confidence")),
      gauge(r),
      h("div", { class: "c-reasons" }, reasons.length ? h("ul", { class: "reasons" }, reasons.map(t => h("li", null, t)))
        : h("span", { class: "small muted" }, "No single strong reason")));
  }
  function head() {
    return h("div", { class: "row head" }, h("div", null, "#"), h("div", null, "Share"), h("div", null, "Price"),
      h("div", null, h("span", { class: "key b" }), "Buy ", h("span", { class: "key h" }), "Hold ", h("span", { class: "key s" }), "Sell (next week)"),
      h("div", null, "Conf."), h("div", null, "Cycle position"), h("div", null, "Why"));
  }
  function moodBanner(md) {
    const icon = { Friendly: "●", Neutral: "◐", Caution: "▲", Hostile: "■" }[md.label];
    return h("div", { class: "mood " + md.label, role: "status" },
      h("div", { class: "icon", "aria-hidden": "true" }, icon),
      h("div", null,
        h("div", { class: "label" }, "Market mood: " + md.label),
        md.warning ? h("div", { class: "warn" }, md.warning) : null,
        h("ul", { class: "small" }, md.reasons.map(t => h("li", null, t)))));
  }

  // ---------- views
  function viewTop() {
    const s = S.summary;
    const top = s.top.map(x => S.bySym[x]);
    const sells = s.sell_top.map(x => S.bySym[x]);
    return h("div", null,
      moodBanner(s.mood),
      h("h1", null, "Top 20 to buy this week"),
      h("p", { class: "sub" }, `Ranked by the odds of rising more than ${pct(s.buy_threshold)} minus the odds of falling more than ${pct(-s.sell_threshold)} over the next ${s.horizon_days} trading days. At most 4 per sector. Click any share for its full picture.`),
      h("div", { class: "rows" }, head(), top.map((r, i) => row(r, i + 1, "buy"))),
      h("div", { class: "grid two", style: "margin-top:16px" },
        h("div", { class: "card" }, h("h3", null, "New in the list today"),
          s.new_entries.length ? h("div", { class: "chips" }, s.new_entries.map(x => h("button", { class: "chip", onclick: () => go(x) }, x)))
            : h("div", { class: "muted small" }, "No changes since yesterday")),
        h("div", { class: "card" }, h("h3", null, "Dropped out today"),
          s.dropped.length ? h("div", { class: "chips" }, s.dropped.map(x => h("button", { class: "chip", onclick: () => go(x) }, x)))
            : h("div", { class: "muted small" }, "No changes since yesterday"))),
      Object.keys(s.also).length ? h("div", null,
        h("h2", null, "Also strong (left out by the 4-per-sector cap)"),
        h("div", { class: "grid two" }, Object.entries(s.also).map(([sec, list]) =>
          h("div", { class: "card" }, h("h3", null, sec), list.map(x => miniRow(S.bySym[x], "buy")))))) : null,
      h("h2", null, "Top 20 to sell or avoid"),
      h("p", { class: "sub" }, "Highest odds of falling more than 2% next week relative to rising. Junk shares here can still spike, which is why the risk is high both ways."),
      h("div", { class: "rows" }, head(), sells.map((r, i) => row(r, i + 1, "sell"))));
  }

  function miniRow(r, side) {
    return h("div", { class: "mini", onclick: () => go(r.sym) },
      h("div", null, h("b", null, r.sym), " ", h("span", { class: "muted small" }, r.type)),
      h("div", null, h("div", { class: "bhs", style: "height:8px" },
        h("span", { class: "b", style: `width:${r.buy * 100}%` }), h("span", { class: "h", style: `width:${r.hold * 100}%` }),
        h("span", { class: "s", style: `width:${r.sell * 100}%` }))),
      h("div", { class: "num small", style: "text-align:right" }, side === "buy" ? pct(r.buy) : pct(r.sell)));
  }

  function viewSectors() {
    const s = S.summary;
    const secs = Object.entries(s.sectors).sort((a, b) => (b[1].avg_buy - b[1].avg_sell) - (a[1].avg_buy - a[1].avg_sell));
    return h("div", null,
      moodBanner(s.mood),
      h("h1", null, "By sector"),
      h("p", { class: "sub" }, "Top 5 to buy and top 5 to sell in every sector (from the company fundamentals). Sectors ordered by their average Buy minus Sell odds."),
      h("div", { class: "grid two" }, secs.map(([name, v]) => h("div", { class: "card sector" },
        h("h3", null, h("span", null, name), h("span", { class: "small muted num" }, `${v.count} listed · 4 wks ${spct(v.ret20)}`)),
        h("div", { class: "col-title" }, "Top buy"), v.buy.map(x => miniRow(S.bySym[x], "buy")),
        h("div", { class: "col-title" }, "Top sell"), v.sell.map(x => miniRow(S.bySym[x], "sell"))))));
  }

  const COLS = [
    ["rank", "Rank", r => r.rank, "r"], ["sym", "Share", r => r.sym], ["sector", "Sector", r => r.sector],
    ["cat", "Cat", r => r.cat], ["type", "Type", r => r.type], ["stage", "Stage", r => r.stage],
    ["close", "Price", r => num(r.close), "r"], ["chg", "Day", r => spct(r.chg), "r"],
    ["buy", "Buy", r => pct(r.buy), "r"], ["hold", "Hold", r => pct(r.hold), "r"], ["sell", "Sell", r => pct(r.sell), "r"],
    ["conf", "Conf", r => r.conf, "r"], ["band", "Band pos.", r => pct(r.band), "r"],
    ["up_room", "To reg. high", r => spct(r.up_room, 0), "r"], ["down_risk", "To outlier low", r => spct(r.down_risk == null ? null : -r.down_risk, 0), "r"],
    ["liq", "Tk mn/day", r => num(r.liq, 1), "r"], ["junk", "Junk", r => pct(r.junk), "r"],
  ];
  function viewAll() {
    const s = S.summary, f = S.filters;
    const opts = key => [...new Set(s.stocks.map(r => r[key]))].sort();
    const sel = (key, label) => h("select", { onchange: e => { f[key] = e.target.value; renderTable(); } },
      h("option", { value: "" }, "All " + label), opts(key).map(v => h("option", { value: v, selected: f[key] === v ? "" : null }, v)));
    const box = h("div", { class: "tbl-wrap" });
    const count = h("span", { class: "muted small", style: "align-self:center" });
    function renderTable() {
      const q = (f.q || "").toUpperCase();
      let rows = s.stocks.filter(r => (!q || r.sym.includes(q)) && ["sector", "type", "cat", "stage"].every(k => !f[k] || r[k] === f[k]));
      const { key, dir } = S.sort;
      rows = rows.slice().sort((a, b) => {
        const x = a[key], y = b[key];
        if (x == null) return 1; if (y == null) return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * dir;
      });
      count.textContent = `${rows.length} of ${s.stocks.length}`;
      const table = h("table", null,
        h("thead", null, h("tr", null, COLS.map(([k, label, , cls]) => h("th", {
          class: [cls, S.sort.key === k ? "sorted" : ""].join(" "),
          onclick: () => { S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : (cls === "r" && k !== "rank" ? -1 : 1) }; renderTable(); },
        }, label + (S.sort.key === k ? (S.sort.dir > 0 ? " ↑" : " ↓") : ""))))),
        h("tbody", null, rows.map(r => h("tr", { onclick: () => go(r.sym) }, COLS.map(([k, , fn, cls]) => h("td", { class: cls }, fn(r)))))));
      box.textContent = ""; box.appendChild(table);
    }
    renderTable();
    return h("div", null,
      h("h1", null, "All shares"),
      h("p", { class: "sub" }, "Every listed instrument, nothing filtered out. Click a column to sort, a row to open the share."),
      h("div", { class: "filters" },
        h("input", { type: "search", placeholder: "Search symbol", value: f.q || "", oninput: e => { f.q = e.target.value; renderTable(); } }),
        sel("sector", "sectors"), sel("type", "types"), sel("stage", "stages"), sel("cat", "categories"), count),
      box);
  }

  function tile(label, value, note, cls) {
    return h("div", { class: "card tile" }, h("div", { class: "t-label" }, label),
      h("div", { class: "t-value " + (cls || "") }, value), note ? h("div", { class: "t-note" }, note) : null);
  }
  function honestNote(s) {
    const vsIdx = s.top20_total - s.market_total, vsAll = s.top20_total - s.all_total;
    return "Reading this honestly: the model is better at spotting shares likely to fall than shares about to rise. " +
      `Over these weeks the Top 20 ${vsIdx >= 0 ? "beat" : "trailed"} the cap-weighted index by ${Math.abs(vsIdx * 100).toFixed(1)} points and ` +
      `${vsAll >= 0 ? "beat" : "trailed"} an equal-weight basket of every share by ${Math.abs(vsAll * 100).toFixed(1)} points. ` +
      `On an average week ${Math.round(s.avg_hit_rate * 100)}% of Top 20 picks rose, while ${Math.round(s.avg_sell_fell * 100)}% of sell-list shares fell. ` +
      (s.sell20_total > s.all_total ? "The sell list's average return still looks good because it is full of volatile junk shares whose occasional spikes lift the average. " : "") +
      "Use the scores as odds, not certainties.";
  }
  function viewTrack() {
    const t = S.track, s = t.summary;
    const chart = h("div");
    const cal = t.calibration;
    const weeks = t.weeks.slice(-12).reverse();
    const out = h("div", null,
      h("h1", null, "Track record"),
      h("p", { class: "sub" }, `Pretend portfolio: every week buy the Top 20 (equal amounts), hold 5 trading days, pay 0.5% brokerage each way on the part that changes. The model is retrained monthly using only data available at the time, so these ${s.weeks} weeks (${Charts.fmtDate(s.start)} – ${Charts.fmtDate(s.end)}) are results it never saw while learning.`),
      h("div", { class: "grid tiles" },
        tile("Top 20 portfolio", spct(s.top20_total), "after costs", s.top20_total >= 0 ? "up" : "down"),
        tile("Market index", spct(s.market_total), "cap-weighted, shares only"),
        tile("All shares, equal amounts", spct(s.all_total), "buy everything"),
        tile("Weeks beating the index", pct(s.beat_market_weeks), `${s.weeks} weeks`),
        tile("Picks that rose", pct(s.avg_hit_rate), "average per week"),
        tile("Weekly turnover", pct(s.avg_turnover), "share of list replaced")),
      h("h2", null, "Growth of Tk 100"),
      h("div", { class: "legend" },
        h("span", null, h("i", { style: `background:${css("--s1")}` }), "Top 20 (after costs)"),
        h("span", null, h("i", { style: `background:${css("--s2")}` }), "Market index"),
        h("span", null, h("i", { style: `background:${css("--s3")}` }), "All shares equal-weight"),
        h("span", null, h("i", { style: `background:${css("--s4")}` }), "Top 20 sell list")),
      h("div", { class: "card" }, chart),
      h("div", { class: "note", style: "margin-top:12px" }, honestNote(s)),
      h("h2", null, "Are the percentages honest?"),
      h("p", { class: "sub" }, "Unseen weeks grouped by the model's raw Buy estimate, against how often the share really rose more than 2%. The raw estimates run too high, so the site shows calibrated odds that match the “Actually rose” column, not the raw ones."),
      h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Raw Buy estimate", "Cases", "Average estimate", "Actually rose >2%", "Average return"].map((x, i) => h("th", { class: i ? "r" : "" }, x)))),
        h("tbody", null, cal.map(c => h("tr", null, h("td", null, c.bucket), h("td", { class: "r" }, c.n.toLocaleString()),
          h("td", { class: "r" }, pct(c.predicted)), h("td", { class: "r" }, pct(c.realized)), h("td", { class: "r" }, spct(c.avg_return, 2))))))),
      h("h2", null, "Last 12 weeks"),
      h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Week from", "Top 20", "Index", "All shares", "Picks up", "Picks"].map((x, i) => h("th", { class: i && i < 5 ? "r" : "" }, x)))),
        h("tbody", null, weeks.map(w => h("tr", { style: "cursor:default" }, h("td", null, Charts.fmtDate(w.date)),
          h("td", { class: "r " + (w.top20 >= 0 ? "up" : "down") }, spct(w.top20)), h("td", { class: "r" }, spct(w.market)),
          h("td", { class: "r" }, spct(w.all)), h("td", { class: "r" }, pct(w.hit)),
          h("td", { class: "small muted", style: "white-space:normal;min-width:320px" }, w.picks.join(", "))))))));
    requestAnimationFrame(() => {
      const d = t.weeks.map(w => w.date);
      Charts.line(chart, {
        dates: d, height: 280, label: "Growth of Tk 100", yFormat: v => Math.round(v), endLabels: true,
        series: [
          { name: "Top 20", label: "Top 20", values: t.weeks.map(w => w.top_curve), color: css("--s1"), fmt: v => v.toFixed(1) },
          { name: "Index", label: "Index", values: t.weeks.map(w => w.mkt_curve), color: css("--s2"), fmt: v => v.toFixed(1) },
          { name: "All shares", label: "All", values: t.weeks.map(w => w.all_curve), color: css("--s3"), fmt: v => v.toFixed(1) },
          { name: "Sell list", label: "Sell list", values: t.weeks.map(w => w.sell_curve), color: css("--s4"), fmt: v => v.toFixed(1) },
        ],
      });
    });
    return out;
  }

  function viewHow() {
    const s = S.summary;
    const p = (...x) => h("p", null, ...x);
    return h("div", { class: "prose" },
      h("h1", null, "How the scores work"),
      p("Everything here comes only from DSE price, volume and trade data plus the weekly company snapshot. No news, no opinions."),
      h("h2", null, "The question the model answers"),
      p(`For each share: over the next ${s.horizon_days} trading days, what are the odds it rises more than 2% (Buy), falls more than 2% (Sell), or stays in between (Hold)? The three add up to 100%. 2% is roughly what a round trip costs in brokerage plus a little profit.`),
      h("h2", null, "The angles it looks at"),
      h("ul", null,
        h("li", null, h("b", null, "Cycle position: "), "where the price sits between its regular low and regular high (10th–90th percentile of the last 60 and 120 days), whether it is in a rising or falling leg, and how far into a typical leg it is. Swings are found automatically with a threshold scaled to each share's volatility."),
        h("li", null, h("b", null, "Trend & momentum: "), "1, 2, 4 and 12-week returns, distance from moving averages, RSI, higher lows."),
        h("li", null, h("b", null, "Money flow: "), "volume vs normal, volume on up days vs down days, average trade size (big players), where the price closes within the day's range, price/volume divergence."),
        h("li", null, h("b", null, "Liquidity: "), "median daily turnover, days with no trades."),
        h("li", null, h("b", null, "Risk: "), "volatility, circuit-limit hits, gaps, drawdown from the 6-month high."),
        h("li", null, h("b", null, "Relative strength: "), "vs the market index and vs the share's own sector."),
        h("li", null, h("b", null, "Market mood: "), "index trend, breadth, advancers vs decliners, turnover trend."),
        h("li", null, h("b", null, "Fundamentals: "), "category, sponsor / institute / foreign holding, size, reserves, price vs face value."),
        h("li", null, h("b", null, "Junk pattern: "), "volume spikes, upper-circuit runs, past pumps, small paid-up capital, Z category. Each share gets a behaviour type (steady cycler, trender, operator/junk, dead/illiquid, mixed) and junk shares get a stage: accumulation, markup, distribution or dump."),
        h("li", null, h("b", null, "Similar setups: "), "the 7 most similar earlier days in the same share, and what happened the week after.")),
      h("h2", null, "How it learns"),
      p("A gradient-boosted decision-tree model learns from every share and every day of the last two years. Its raw odds are then calibrated against out-of-sample history so a displayed 30% means it really happened about 30% of the time. The Top 20 ranks by Buy minus Sell, because backtests showed ranking on Buy alone just picked the most volatile junk."),
      h("h2", null, "Confidence"),
      p("A separate 0–100 score: how much history the share has, how liquid it is, how regular its cycles are, and how clear-cut today's split is. Junk shares are scaled down by a quarter, dead ones by half."),
      h("h2", null, "Bonus shares"),
      p("DSE caps daily moves at about 10%, so a larger overnight drop with an opening gap is treated as a record-date adjustment (bonus, dividend) and earlier prices are scaled so charts and cycles stay continuous."),
      h("h2", null, "Limits"),
      h("ul", null,
        h("li", null, "Only two years of data, so slow cyclers have only a few complete cycles."),
        h("li", null, "Fundamentals come from the latest weekly snapshot and are applied to the past as-is."),
        h("li", null, "It cannot see news, announcements or manipulation before it shows in the data."),
        h("li", null, "This is a research tool, not financial advice.")),
      h("h2", null, "Updates"),
      p("Twice each trading day (Sunday–Thursday): around 3:00 PM Dhaka with the day's first data (marked preliminary) and around 4:10 PM with the final day-end data."));
  }

  // ---------- stock page
  async function viewStock(sym) {
    let d = S.stockCache[sym];
    if (!d) {
      const res = await fetch(`data/stocks/${encodeURIComponent(sym)}.json`, { cache: "no-cache" });
      if (!res.ok) return h("div", null, h("a", { class: "back", href: "#top" }, "← Back"), h("p", null, `No data for ${sym}.`));
      d = S.stockCache[sym] = await res.json();
    }
    const m = d.metrics, info = d.info;
    const priceBox = h("div"), volBox = h("div"), scoreBox = h("div");
    let range = S.range || 250;
    const rangeBtns = h("div", { class: "chips", style: "margin-bottom:8px" },
      [["3M", 63], ["6M", 125], ["1Y", 250], ["All", 10000]].map(([lbl, n]) =>
        h("button", { class: "chip", style: n === range ? "border-color:var(--ink);font-weight:600" : "", onclick: () => { S.range = n; route(); } }, lbl)));
    const contrib = Object.entries(d.contrib).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    const maxC = Math.max(4, ...contrib.map(c => Math.abs(c[1])));
    const kv = pairs => h("div", { class: "kv" }, pairs.flatMap(([k, v]) => [h("div", null, k), h("div", null, v)]));
    const legTxt = d.leg === 1 ? "Rising" : d.leg === -1 ? "Falling" : "Unclear";
    const out = h("div", null,
      h("a", { class: "back", href: "#top" }, "← Back"),
      h("div", { class: "hero" },
        h("div", null, h("h1", null, d.sym), h("div", { class: "meta" }, `${d.sector} · rank ${d.rank} of ${S.summary.universe}`), h("div", null, tags(d))),
        h("div", null, h("div", { class: "price num" }, num(d.close)), h("div", { class: d.chg >= 0 ? "up" : "down" }, spct(d.chg) + " today")),
        bhs(d, true),
        h("div", { class: "conf", style: "font-size:24px" }, d.conf, h("small", null, "confidence / 100"))),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("h3", null, "Reasons to buy"),
          d.reasons.length ? h("ul", { class: "reasons" }, d.reasons.map(x => h("li", null, x))) : h("div", { class: "muted small" }, "Nothing stands out")),
        h("div", { class: "card" }, h("h3", null, "Reasons for caution"),
          (d.sell_reasons || []).length ? h("ul", { class: "reasons" }, d.sell_reasons.map(x => h("li", null, x))) : h("div", { class: "muted small" }, "Nothing stands out"))),
      h("h2", null, "Price, regular range and swings"),
      rangeBtns,
      h("div", { class: "legend" },
        h("span", null, h("i", { style: `background:${css("--ink")}` }), "Close (adjusted for bonus shares)"),
        h("span", null, h("i", { class: "area", style: `background:${css("--buy")};opacity:.25` }), "Regular range (60 days)"),
        h("span", null, h("i", { style: `background:${css("--muted")};height:1px` }), "Outlier low / high (120 days)"),
        h("span", null, h("i", { class: "dot", style: `background:${css("--buy")}` }), "Swing low"),
        h("span", null, h("i", { class: "dot", style: `background:${css("--sell")}` }), "Swing high")),
      h("div", { class: "card" }, priceBox, h("div", { style: "margin-top:8px" }, h("div", { class: "small muted" }, "Volume (blue = up day, red = down day)"), volBox)),
      h("div", { class: "grid two", style: "margin-top:12px" },
        h("div", { class: "card" }, h("h3", null, "The cycle"), kv([
          ["Current leg", `${legTxt}${d.leg_days != null ? ", day " + d.leg_days : ""}${d.leg_typ && d.leg_days > 3 * d.leg_typ ? " (unusually long; typical " + d.leg_typ + ")" : d.leg_typ ? " of a typical " + d.leg_typ : ""}`],
          ["Typical rise", m.up_len != null ? `${Math.round(m.up_len)} days, ${spct(m.up_pct, 0)}` : "–"],
          ["Typical fall", m.dn_len != null ? `${Math.round(m.dn_len)} days, ${spct(m.dn_pct, 0)}` : "–"],
          ["Completed swings (2 yrs)", m.n_legs ?? "–"],
          ["Cycle regularity", m.regularity != null ? pct(m.regularity) : "–"],
          ["Position in regular range", pct(m.band60)],
          ["Room to regular high", spct(m.up_room, 1)],
          ["Drop to outlier low", spct(m.down_risk == null ? null : -m.down_risk, 1)],
        ])),
        h("div", { class: "card" }, h("h3", null, "What moved the score"),
          h("div", { class: "small muted", style: "margin-bottom:6px" }, "Points of (Buy − Sell) each angle adds (blue) or removes (red)"),
          contrib.map(([a, v]) => h("div", { class: "contrib" }, h("div", null, a),
            h("div", { class: "bar" }, h("div", { class: "mid" }),
              h("span", { class: v >= 0 ? "pos" : "neg", style: `width:${(Math.abs(v) / maxC) * 50}%` })),
            h("div", { class: "num small", style: "text-align:right" }, (v > 0 ? "+" : "") + v.toFixed(1)))))),
      h("h2", null, "Score history"),
      h("div", { class: "legend" },
        h("span", null, h("i", { class: "area", style: `background:${css("--buy")}` }), "Buy"),
        h("span", null, h("i", { class: "area", style: `background:${css("--hold")}` }), "Hold"),
        h("span", null, h("i", { class: "area", style: `background:${css("--sell")}` }), "Sell")),
      h("div", { class: "card" }, scoreBox),
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
          ["Median trades / day", m.med_trades != null ? Math.round(m.med_trades) : "–"],
          ["Junk score", pct(m.junk_score)],
        ])),
        h("div", { class: "card" }, h("h3", null, "Similar past setups"),
          d.analogs.length ? h("div", null,
            h("div", { class: "small muted", style: "margin-bottom:6px" }, `The ${d.analogs.length} most similar earlier days in ${d.sym}, and the next week's move`),
            kv(d.analogs.map(a => [Charts.fmtDate(a.date), h("span", { class: a.ret >= 0 ? "up" : "down" }, spct(a.ret))])),
            h("div", { class: "small", style: "margin-top:6px" }, `Average ${spct(m.analog_ret)}, ${pct(m.analog_win)} rose`))
            : h("div", { class: "muted small" }, "Not enough history yet"))),
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
            : h("div", { class: "muted small" }, "None detected in the last two years"))));

    requestAnimationFrame(() => {
      const s = d.series, n = s.dates.length, from = Math.max(0, n - range);
      const cut = a => a.slice(from);
      const dates = cut(s.dates);
      const pivotIdx = new Map(s.dates.map((x, i) => [x, i]));
      const markers = d.pivots.map(p => ({ i: pivotIdx.get(p.date) - from, v: p.price, color: p.kind > 0 ? css("--sell") : css("--buy") }))
        .filter(p => p.i >= 0);
      const f2 = v => num(v, v < 10 ? 2 : 1);
      Charts.line(priceBox, {
        dates, height: 300, label: `${d.sym} price`, yFormat: f2,
        band: { lo: cut(s.p10), hi: cut(s.p90), color: css("--buy"), name: "Regular range" },
        series: [
          { name: "Outlier high", values: cut(s.max120), color: css("--muted"), width: 1, endLabel: false },
          { name: "Outlier low", values: cut(s.min120), color: css("--muted"), width: 1, endLabel: false },
          { name: "Close", values: cut(s.close), color: css("--ink"), width: 2, endLabel: false },
        ],
        markers,
      });
      const closes = s.close;
      Charts.columns(volBox, {
        dates, height: 110, name: "Volume", color: css("--muted"), values: cut(s.volume), fmt: v => Math.round(v).toLocaleString(),
        yFormat: v => v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? Math.round(v / 1e3) + "K" : v,
        colors: cut(closes.map((c, i) => i && c < closes[i - 1] ? css("--sell") : css("--buy"))),
      });
      const sc = d.scores;
      Charts.stack(scoreBox, {
        dates: sc.dates, height: 180, label: "Score history",
        layers: [{ name: "Sell", values: sc.sell, color: css("--sell") }, { name: "Hold", values: sc.hold, color: css("--hold") },
          { name: "Buy", values: sc.buy, color: css("--buy") }],
      });
    });
    return out;
  }

  // ---------- routing
  const TABS = [["top", "Top 20"], ["sectors", "Sectors"], ["all", "All shares"], ["track", "Track record"], ["how", "How it works"]];
  async function route() {
    const hash = decodeURIComponent(location.hash.slice(1)) || "top";
    const [view, arg] = hash.split("/");
    document.querySelectorAll("nav.tabs a").forEach(a => a.classList.toggle("on", a.dataset.v === view));
    let node;
    if (view === "s" && arg) node = await viewStock(arg);
    else if (view === "sectors") node = viewSectors();
    else if (view === "all") node = viewAll();
    else if (view === "track") node = viewTrack();
    else if (view === "how") node = viewHow();
    else node = viewTop();
    const a = app(); a.textContent = ""; a.appendChild(node);
    if (S.lastHash !== hash) window.scrollTo(0, 0);
    S.lastHash = hash;
  }

  function setTheme(t) {
    if (t === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("theme", t); } catch (e) { /* storage blocked */ }
    document.getElementById("theme").textContent = { auto: "Theme: auto", light: "Theme: light", dark: "Theme: dark" }[t];
  }

  async function init() {
    let theme = "auto";
    try { theme = localStorage.getItem("theme") || "auto"; } catch (e) { /* storage blocked */ }
    setTheme(theme);
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
