// DSE Signals front end: one plan, the next month (buy now, sell at the share's own take-profit (+5% or more), at its own stop, or on the sell-by date).
// Reads data/summary.json, data/track.json and data/stocks/<SYM>.json.
(function () {
  const S = { summary: null, track: null, bySym: {}, cache: {}, sort: { key: "rank", dir: 1 }, filters: {}, q: "", range: 125, side: "buy", sector: "", phase: "" };
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
  const ORDER = ["Buy", "Neutral", "Sell"];
  const GOAL = () => HZ().goal || 0.05;
  const SELLBY = () => Charts.fmtDate(HZ().sell_by);

  // ---------- My stocks: watchlist, holdings and settings, saved in this browser only
  const MY_KEY = "dse-my-v1";
  function myLoad() {
    try {
      const x = JSON.parse(load(MY_KEY) || "{}");
      return { watch: x.watch || {}, holdings: x.holdings || [], capital: x.capital || 500000, risk: x.risk || 1,
        seen: x.seen || null, changes: x.changes || null };
    } catch (e) { return { watch: {}, holdings: [], capital: 500000, risk: 1, seen: null, changes: null }; }
  }
  let MY = myLoad();
  const mySave = () => { store(MY_KEY, JSON.stringify(MY)); navCount(); };
  function navCount() {
    const a = document.querySelector('nav.tabs a[data-v="mine"]');
    if (a) a.textContent = `My stocks${Object.keys(MY.watch).length + MY.holdings.length ? ` (${Object.keys(MY.watch).length + MY.holdings.length})` : ""}`;
  }
  function starBtn(sym) {
    const on = !!MY.watch[sym];
    return h("button", { class: "star" + (on ? " on" : ""), type: "button", title: on ? "Remove from watchlist" : "Add to watchlist",
      "aria-label": on ? `Remove ${sym} from watchlist` : `Add ${sym} to watchlist`, "aria-pressed": String(on),
      onclick: e => {
        e.stopPropagation();
        if (MY.watch[sym]) delete MY.watch[sym];
        else MY.watch[sym] = { added: S.summary.asof, tag: S.bySym[sym] ? S.bySym[sym].s.verdict : null };
        mySave();
        const b = e.currentTarget, now = !!MY.watch[sym];
        b.classList.toggle("on", now); b.textContent = now ? "★" : "☆"; b.setAttribute("aria-pressed", String(now));
      } }, on ? "★" : "☆");
  }
  function sizing(r) {
    const p = r.s.plan, price = r.close;
    const perShare = Math.max(price - p.stop, 0.01);
    let qty = Math.floor(MY.capital * MY.risk / 100 / perShare);
    const limits = [];
    const capAlloc = Math.floor(MY.capital * 0.15 / price);
    if (capAlloc < qty) { qty = capAlloc; limits.push("15% of your capital in one share"); }
    const capLiq = p.liq ? Math.floor(p.liq * 1e6 * 0.10 / price) : qty;
    if (capLiq < qty) { qty = capLiq; limits.push("10% of its average daily turnover, so you can get out"); }
    qty = Math.max(qty, 0);
    return { qty, cost: qty * price, loss: qty * perShare, limits };
  }
  const PHASE_ICON = { Bottoming: "↺", "Early rise": "↗", "Mid rise": "↗", "Late rise": "⤴", Topping: "↻", "Early fall": "↘", "Mid fall": "↘", "Late fall": "⤵", Sideways: "→" };
  const upPhase = p => /rise|Bottoming/.test(p);

  // ---------- building blocks
  function badge(v) {
    return h("span", { class: "verdict v-" + v.toLowerCase().replace(/ /g, "-") }, v);
  }
  function bs(o, big) {
    const t = o.hit ?? 0, st = o.stop_p ?? 0, n = Math.max(0, 1 - t - st), g = pct(o.target_dist ?? GOAL(), 1);
    return h("div", { class: "bs" + (big ? " big" : ""), role: "img", "aria-label": `+${g} first ${pct(t)}, neither ${pct(n)}, stop first ${pct(st)}` },
      h("div", { class: "bar" }, h("span", { class: "b", style: `width:${t * 100}%` }), h("span", { class: "n", style: `width:${n * 100}%` }),
        h("span", { class: "s", style: `width:${st * 100}%` })),
      h("div", { class: "lbl" }, h("span", { class: "gb" }, `+${g} first ${pct(t)}`), h("span", { class: "muted" }, `neither ${pct(n)}`),
        h("span", { class: "rs" }, `stop first ${pct(st)}`)));
  }
  function stat(label, value, frac, title) {
    return h("div", { class: "stat", title },
      h("b", null, value), h("span", null, label),
      frac == null ? null : h("div", { class: "meter" }, h("i", { style: `width:${Math.max(0, Math.min(1, frac)) * 100}%` })));
  }
  const moveStat = o => stat("lead", `${((o.hit - o.stop_p) * 100).toFixed(0)} pts`, Math.max(0, Math.min(1, 0.5 + (o.hit - o.stop_p))),
    "Chance of the take-profit first minus chance of the stop first. Buy needs +15 or more (+25 for junk shares), a price below its usual level, a journey other than Topping / Mid fall, no drastic fall, and a turn-up sign if it has been falling");
  const devText = r => r.dev2y == null ? null : h("div", { class: "small" }, `Price Tk ${num(r.close)} is `,
    h("b", { class: r.dev2y >= 0 ? "up" : "down" }, spct(r.dev2y)), ` vs its usual price level, the ${r.fair_basis || "2-year"} average (Tk ${num(r.avg2y)})`,
    r.fair_basis === "1-year" ? h("span", { class: "muted" }, " · it moved to a new price range in the last year, so the 2-year average would mislead") : null);
  const confStat = o => stat("confidence", o.conf, o.conf / 100, "How far to trust this: history, liquidity, cycle regularity, clarity");
  function expBlock(o, r) {
    const p = o.plan;
    return h("div", { class: "expbox odds" },
      h("div", { class: "oddrow" },
        h("div", null, h("b", { class: "up" }, pct(o.hit)), h("span", null, ` reach take-profit Tk ${num(p.take_profit)} (${spct(p.reward_pct)}) by ${SELLBY()}`)),
        h("div", null, h("b", { class: "down" }, pct(o.stop_p)), h("span", null, ` hit stop first (Tk ${num(p.stop)}, ${spct(-p.risk_pct)})`))),
      r ? devText(r) : null);
  }
  const pl = (label, value, sub, cls) => h("div", { class: "pl" }, h("span", null, label), h("b", null, value),
    sub ? h("small", { class: cls || "" }, sub) : null);
  function planLine(r) {
    const o = r.s, p = o.plan;
    if (o.verdict === "Sell") return h("div", { class: "plan sellplan small" }, h("b", null, "Plan: "), `avoid buying; if you hold it, consider selling (more likely to drop to Tk ${num(p.stop)}, ${spct(-p.risk_pct)}, than reach Tk ${num(p.take_profit)}).`);
    return h("div", { class: "plan small" }, h("b", null, "Plan: "),
      `buy Tk ${num(p.entry_lo)}–${num(p.entry_hi)} · take profit Tk ${num(p.take_profit)} (${spct(p.reward_pct)}) as soon as it closes there · stop Tk ${num(p.stop)} (${spct(-p.risk_pct)}) · else sell by ${p.sell_by}`);
  }
  function planCard(r) {
    const o = r.s, p = o.plan;
    if (o.verdict === "Sell") {
      return h("div", { class: "card plan-card" }, h("h3", null, "Trade plan"),
        h("p", null, h("b", null, "Avoid buying. "), `If you already hold ${r.sym}, consider selling, or at least exit if it closes at or below Tk ${num(p.stop)} (${spct(-p.risk_pct)}; ${p.stop_basis}).`),
        rationaleBlock(o));
    }
    const sz = sizing(r);
    const capIn = h("input", { type: "number", min: "1000", step: "1000", value: MY.capital, "aria-label": "Your capital in Taka" });
    const riskIn = h("input", { type: "number", min: "0.1", max: "10", step: "0.1", value: MY.risk, "aria-label": "Risk per trade in percent" });
    const onChange = () => { MY.capital = Math.max(1000, +capIn.value || 0); MY.risk = Math.min(10, Math.max(0.1, +riskIn.value || 1)); mySave(); route(); };
    capIn.addEventListener("change", onChange); riskIn.addEventListener("change", onChange);
    return h("div", { class: "card plan-card" },
      h("h3", null, `1-month plan · until ${p.sell_by}`),
      o.verdict === "Neutral" ? h("p", { class: "note", style: "margin-top:0" },
        `${r.sym} is Neutral: there's no fresh Buy signal. The levels below are for reference, e.g. if you already hold it or want to wait for a Buy.`) : null,
      h("div", { class: "plan-row" },
        pl("Buy zone", `Tk ${num(p.entry_lo)} – ${num(p.entry_hi)}`, "don't chase above the top"),
        pl("Take profit", `Tk ${num(p.take_profit)}`, spct(p.reward_pct), "up"),
        pl("Stop-loss", `Tk ${num(p.stop)}`, spct(-p.risk_pct), "down"),
        pl("Reward : risk", `${num(p.rr, 1)} : 1`, p.rr_label, "rr rr-" + p.rr_label.split(" ")[0].toLowerCase()),
        pl("Sell by", p.sell_by, "latest exit")),
      h("p", { class: "small" }, h("b", null, "Rules: "), `place a sell order at Tk ${num(p.take_profit)} (${spct(p.reward_pct)}; ${p.tp_basis}); it fills as soon as the day's high reaches it, any day, no need to wait for the month end. ` +
        `Exit if a close falls to Tk ${num(p.stop)} or lower. If neither happens, sell by ${p.sell_by}.`),
      rationaleBlock(o),
      h("div", { class: "sizer" },
        h("label", null, "Your capital (Tk) ", capIn), h("label", null, "Risk per trade (%) ", riskIn)),
      h("p", null, sz.qty
        ? [h("b", null, `Buy about ${sz.qty.toLocaleString()} shares (≈ Tk ${Math.round(sz.cost).toLocaleString()}).`),
          ` If the stop-loss is hit you'd lose about Tk ${Math.round(sz.loss).toLocaleString()} (${pct(sz.loss / MY.capital, 1)} of your capital).`,
          sz.limits.length ? h("span", { class: "muted" }, ` Capped at ${sz.limits.join(" and ")}.`) : null]
        : "Your capital is too small for even one share at this risk level."),
      h("div", { class: "chips" },
        h("button", { class: "chip", type: "button", onclick: () => { addHolding(r.sym, sz.qty || 1, r.close); location.hash = "#mine"; } }, "＋ Add to my holdings at today's price"),
        h("button", { class: "chip", type: "button", onclick: () => { if (!MY.watch[r.sym]) { MY.watch[r.sym] = { added: S.summary.asof, tag: o.verdict }; mySave(); } location.hash = "#mine"; } }, "☆ Watch it")));
  }
  function rationaleBlock(o) {
    return h("div", null,
      o.rationale && o.rationale.length ? [h("h4", null, "Why this plan"), h("ul", { class: "why" }, o.rationale.map(x => h("li", null, x)))] : null,
      o.changes && o.changes.length ? [h("h4", null, "What changed since the last session"), h("ul", { class: "chg" }, o.changes.map(x => h("li", null, x)))] : null);
  }
  function tagPanel(o) {
    const vc = (HZ().verdict_check || []).find(v => v.verdict === o.verdict);
    const rules = o.verdict === "Sell" ? [["Sell conditions", o.rule_sell]] : o.verdict === "Buy" ? [["Buy conditions", o.rule_buy]]
      : [["Buy conditions", o.rule_buy], ["Sell conditions", o.rule_sell]];
    return h("div", { class: "card decision" },
      h("div", { class: "dh" }, h("h3", null, "Why this tag"), badge(o.verdict)),
      h("p", { style: "margin:0" }, o.tag_why),
      rules.map(([name, checks]) => h("div", { class: "rule" }, h("div", { class: "small muted" }, name + (name.startsWith("Buy") ? " (all must hold)" : " (either one is enough)")),
        checks.map(c => h("div", { class: "check " + (c.ok ? "ok" : "no") }, h("span", { class: "mark", "aria-hidden": "true" }, c.ok ? "✓" : "✗"), h("span", null, (c.ok ? "" : "Not met: ") + c.text))))),
      h("div", { class: "small" }, o.tag_days >= 60 ? `Tagged ${o.verdict} for 60+ trading days.`
        : `Tagged ${o.verdict} for ${o.tag_days} trading day${o.tag_days === 1 ? "" : "s"} (since ${Charts.fmtDate(o.tag_since)}).`),
      vc ? h("div", { class: "small muted" }, `Track record: on unseen days, shares tagged ${o.verdict} reached their take-profit first ${pct(vc.target)} of the time and hit their stop first ${pct(vc.stop)} ` +
        `(average trade ${spct(vc.net, 2)} after costs).`) : null,
      o.why.length ? [h("h4", null, "What supports it"), h("ul", { class: "why" }, o.why.map(x => h("li", null, x)))] : null,
      o.caution.length ? [h("h4", null, "What argues against"), h("ul", { class: "caution" }, o.caution.map(x => h("li", null, x)))] : null);
  }
  function phaseChip(o) {
    return h("span", { class: "phase " + (upPhase(o.phase) ? "p-up" : o.phase === "Sideways" ? "" : "p-down"), title: o.journey },
      h("span", { "aria-hidden": "true" }, PHASE_ICON[o.phase] || "·"), " ", o.phase);
  }
  function pathChart(r) {
    const o = r.s;
    const color = o.verdict === "Sell" ? css("--sell") : css("--buy");
    const last = r.spark[r.spark.length - 1];
    const p = o.plan;
    const pr = last != null ? { steps: 20, from: last, mid: last, lo: last * (1 - p.risk_pct), hi: last * (1 + p.reward_pct), color } : null;
    return h("div", { class: "pathbox", title: "Last 40 sessions, then the plan's take-profit and stop levels over the next month" },
      Charts.sparkPath(r.spark, pr));
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
      `${Math.abs(thuNext * 100).toFixed(2)}% on average. Over a full month the entry day makes little difference, so it doesn't change the verdicts.`);
  }
  function dist() {
    const v = HZ().verdicts, total = ORDER.reduce((a, k) => a + (v[k] || 0), 0);
    const col = { Buy: "--buy-strong", Neutral: "--neutral", Sell: "--sell-strong" };
    return h("div", { class: "card", style: "padding:12px 16px;margin-bottom:16px" },
      h("div", { class: "small muted" }, `All ${total} shares today · 1-month plan until ${SELLBY()}`),
      h("div", { class: "dist" }, ORDER.filter(k => v[k]).map(k => h("span", {
        style: `flex:${v[k]};background:var(${col[k]});color:#fff`, title: `${k}: ${v[k]}` },
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
          h("div", { class: "meta" }, `${r.sector} · Category ${r.cat}`), h("div", null, phaseChip(o), " ", tags(r))),
        h("div", { class: "price" }, h("b", null, num(r.close)), h("span", { class: "small " + (r.chg >= 0 ? "up" : "down") }, spct(r.chg))),
        starBtn(r.sym)),
      pathChart(r),
      expBlock(o, r),
      h("div", { class: "tagwhy small" }, o.tag_why),
      planLine(r),
      h("div", { class: "nums" }, moveStat(o), confStat(o), stat("tagged for", o.tag_days >= 60 ? "60+ d" : `${o.tag_days}d`)),
      lines.length ? h("ul", { class: "why" }, lines.map(t => h("li", null, t))) : null);
  }
  function miniRow(r) {
    const o = r.s;
    return h("div", { class: "mini", onclick: () => go(r.sym) },
      h("div", null, h("span", { class: "sym" }, r.sym), " ", h("span", { class: "muted small" }, `${num(r.close)} · TP ${pct(o.hit)} / stop ${pct(o.stop_p)} · ${o.phase}`)),
      badge(o.verdict), bs(o));
  }

  // ---------- Top picks
  function pickList(side, sector, phase) {
    const by = side === "sell" ? "sscore" : "score";
    const pool = S.summary.stocks.filter(r => !NON_SHARE.has(r.sector) && (!sector || r.sector === sector) && (!phase || r.s.phase === phase))
      .sort((a, b) => b.s[by] - a.s[by]);
    if (sector || phase) return pool.slice(0, 20);
    const out = [], count = {};
    for (const r of pool) {                       // at most 4 per sector when showing all sectors
      if (out.length >= 20) break;
      if ((count[r.sector] || 0) < 4) { out.push(r); count[r.sector] = (count[r.sector] || 0) + 1; }
    }
    return out;
  }
  function searchBox() {
    const results = h("div", { class: "results", "aria-live": "polite" });
    const render = q => {
      results.textContent = "";
      q = q.trim().toUpperCase();
      if (!q) return;
      const hits = S.summary.stocks.filter(r => r.sym.includes(q))
        .sort((a, b) => (b.sym.startsWith(q) - a.sym.startsWith(q)) || a.sym.localeCompare(b.sym)).slice(0, 4);
      hits.length ? hits.forEach(r => results.appendChild(quickCard(r))) : results.appendChild(h("div", { class: "empty" }, `No share matches “${q}”`));
    };
    const input = h("input", { type: "search", placeholder: "Search any share, e.g. BRACBANK", autocomplete: "off", value: S.topQ || "",
      "aria-label": "Search shares", oninput: e => { S.topQ = e.target.value; render(e.target.value); } });
    if (S.topQ) render(S.topQ);
    return h("div", null, h("div", { class: "search" }, h("span", { class: "ico", "aria-hidden": "true" }, "⌕"), input), results);
  }
  function viewTop() {
    const s = S.summary, hz = HZ(), side = S.side, sector = S.sector, phase = S.phase || "";
    const list = pickList(side, sector, phase);
    const phases = Object.keys(hz.phases || {}).sort((a, b) => hz.phases[b] - hz.phases[a]);
    const sectors = [...new Set(s.stocks.map(r => r.sector))].filter(x => !NON_SHARE.has(x)).sort();
    const sideBtn = (v, label) => h("button", { class: side === v ? "on" : "", onclick: () => { S.side = v; route(); } }, label);
    const title = `Top ${list.length} to ${side === "sell" ? "sell or avoid" : "buy"}${sector ? " in " + sector : ""}${phase ? " · " + phase.toLowerCase() : ""}`;
    const sub = side === "sell"
      ? `Sell = more likely to hit its stop than its take-profit while not cheap, or stretched 20%+ above its usual price level without upside odds. Worst first.`
      : `Buy = take-profit first beats stop first by 15+ points, the price is below its usual level, the share is not Topping or in a Mid fall, not falling hard, and a falling share shows a turn-up sign.`;
    const showExtras = side === "buy" && !sector && !phase;
    const wrongSide = list.filter(r => r.s.verdict !== (side === "buy" ? "Buy" : "Sell")).length;
    return h("div", null,
      moodBanner(s.mood),
      searchBox(),
      h("div", { class: "page-head" },
        h("div", null, h("h1", null, title), h("p", { class: "sub", style: "margin:0" }, sub + (sector ? "" : " At most 4 per sector.")))),
      h("div", { class: "filters" },
        h("div", { class: "seg", role: "tablist", "aria-label": "Buy or sell" }, sideBtn("buy", "Buy"), sideBtn("sell", "Sell")),
        h("select", { "aria-label": "Sector", onchange: e => { S.sector = e.target.value; route(); } },
          h("option", { value: "" }, "All sectors"), sectors.map(x => h("option", { value: x, selected: sector === x ? "" : null }, x))),
        h("select", { "aria-label": "Journey", onchange: e => { S.phase = e.target.value; route(); } },
          h("option", { value: "" }, "Any journey"), phases.map(x => h("option", { value: x, selected: phase === x ? "" : null }, `${PHASE_ICON[x] || ""} ${x} (${hz.phases[x]})`)))),
      dist(),
      timingTip(),
      wrongSide ? h("div", { class: "note", style: "margin-bottom:12px" },
        `${wrongSide} share(s) in this list are Neutral: there aren't ${list.length} ${side === "buy" ? "Buys" : "Sells"} with these filters, so the next best are shown.`) : null,
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
      h("p", { class: "sub" }, `Top 5 to buy and top 5 to sell in every sector for the 1-month plan (until ${SELLBY()}). Sectors are ordered by their average lead (take-profit chance minus stop chance).`),
      h("div", { class: "grid two" }, secs.map(([name, v]) => h("div", { class: "card" },
        h("h3", { style: "display:flex;justify-content:space-between;gap:8px" }, h("span", null, name),
          h("span", { class: "small muted num" }, `${v.count} listed · avg lead ${(v.avg_exp * 100).toFixed(0)} pts · last 4 wks ${spct(v.ret20)}`)),
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
    ["lead", "Lead", r => `${(r.s.lead * 100).toFixed(0)}`, r => r.s.lead, "r"],
    ["target_dist", "Take-profit", r => spct(r.s.target_dist), r => r.s.target_dist, "r"],
    ["hit", "TP first", r => pct(r.s.hit), r => r.s.hit, "r g"],
    ["stop_p", "Stop first", r => pct(r.s.stop_p), r => r.s.stop_p, "r rd"],
    ["stop_dist", "Stop", r => spct(-r.s.stop_dist), r => r.s.stop_dist, "r"],
    ["dev2y", "vs usual level", r => spct(r.dev2y), r => r.dev2y, "r"],
    ["phase", "Journey", r => r.s.phase, r => r.s.phase],
    ["conf", "Confidence", r => r.s.conf, r => r.s.conf, "r"],
    ["band", "2-yr range", r => pct(r.band), r => r.band, "r"],
    ["type", "Type", r => r.type, r => r.type],
  ];
  function quickCard(r) {
    const o = r.s;
    return h("div", { class: "qcard", onclick: () => go(r.sym) },
      h("div", { class: "head" }, h("div", null, h("b", { style: "font-size:16px" }, r.sym), " ", badge(o.verdict), " ",
        h("span", { class: "muted small" }, `${r.sector} · Cat ${r.cat}`)),
        h("div", { class: "num", style: "display:flex;align-items:center;gap:8px" }, h("b", null, num(r.close)), h("span", { class: "small " + (r.chg >= 0 ? "up" : "down") }, spct(r.chg)), starBtn(r.sym))),
      h("div", { class: "qgrid" },
        h("div", null, bs(o),
          h("div", { class: "mv" }, h("b", null, `TP ${spct(o.target_dist)} ${pct(o.hit)} · stop ${pct(o.stop_p)}`), ` · ${spct(r.dev2y)} vs usual level`,
            ` · ${o.phase} · Confidence ${o.conf}`),
          h("div", { class: "tagwhy small" }, o.tag_why), planLine(r)),
        pathChart(r)));
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
      h("p", { class: "sub" }, "Start typing to see a share's 1-month verdict instantly. Every listed instrument is here; click any row for the full picture."),
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
    const out = h("div", null,
      h("h1", null, "Track record"),
      h("p", { class: "sub" }, `Every month the Top 20 is bought in equal amounts and each share is sold at its own take-profit (+5% or more) or its own stop-loss (whichever comes first: the day's high reaching the take-profit, or a close at the stop) or after 20 trading days, paying 0.5% brokerage each way on the part of the list that changes. All shares and the Sell list are traded the same way. ` +
        `The model is retrained monthly on data available at the time, so these ${s.periods} periods (${Charts.fmtDate(s.start)} – ${Charts.fmtDate(s.end)}) are results it never saw while learning.`),
      h("div", { class: "grid tiles" },
        tile("Top 20 portfolio", spct(s.top20_total), "after costs, compounded", s.top20_total >= 0 ? "up" : "down"),
        tile("Market index", spct(s.market_total), "cap-weighted"),
        tile("All shares, same plan", spct(s.all_total), "buy everything"),
        tile("Months beating the index", pct(s.beat_market), `${s.periods} one-month periods`),
        tile("Picks that hit take-profit", pct(s.avg_target_rate), "average per month"),
        tile("Picks stopped out", pct(s.avg_stop_rate), `Sell list: ${pct(s.avg_sell_stop)}`)),
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
        `Only ${s.periods} months could be tested, so this curve is noisy; the table below uses every unseen day and is the fairer test. ` +
        "Treat the scores as odds, not certainties: the edge is real but thin after costs."),
      h("h2", null, "Does a bigger edge really win more often?"),
      h("p", { class: "sub" }, "Every unseen day, shares split into 10 equal groups by lead (chance of the take-profit first minus chance of the stop first), against what really happened with the plan (own take-profit / own stop / 1 month)."),
      h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Group", "Cases", "Avg lead", "TP first", "Stop first", "Avg trade", "After ~1% costs"]
          .map((c, i) => h("th", { class: i ? "r" : "" }, c)))),
        h("tbody", null, (x.deciles || []).map(g => h("tr", { style: "cursor:default" },
          h("td", null, g.group === 10 ? "10 (best, ≈ Buy)" : g.group === 1 ? "1 (worst, Sell)" : String(g.group)), h("td", { class: "r" }, g.n.toLocaleString()),
          h("td", { class: "r" }, `${(g.edge * 100).toFixed(0)} pts`), h("td", { class: "r g" }, pct(g.target)), h("td", { class: "r rd" }, pct(g.stop)),
          h("td", { class: "r" }, spct(g.gross, 2)), h("td", { class: "r " + (g.net >= 0 ? "up" : "down") }, spct(g.net, 2))))))),
      h("h2", null, "Does a bigger lead come true?"),
      h("p", { class: "sub" }, "Unseen predictions at the monthly buy dates, grouped by lead, against the real trade result (before costs)."),
      h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Lead", "Cases", "Avg lead", "Actual avg", "Actual median", "Gained 5%+", "Lost 5%+"]
          .map((c, i) => h("th", { class: i ? "r" : "" }, c)))),
        h("tbody", null, t.calibration.map(c => h("tr", { style: "cursor:default" }, h("td", null, c.bucket), h("td", { class: "r" }, (c.n || 0).toLocaleString()),
          h("td", { class: "r" }, `${(c.predicted * 100).toFixed(0)} pts`), h("td", { class: "r" }, spct(c.avg_return)), h("td", { class: "r" }, spct(c.median_return)),
          h("td", { class: "r g" }, pct(c.rose)), h("td", { class: "r rd" }, pct(c.fell))))))),
      h("h2", null, "Does each verdict come true?"),
      h("p", { class: "sub" }, "Every unseen day and share, grouped by the verdict it had, against what happened with the plan (own take-profit / own stop / 1 month)."),
      h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Verdict", "Share of cases", "TP first", "Stop first", "Neither", "Avg trade", "After ~1% costs"]
          .map((c, i) => h("th", { class: i ? "r" : "" }, c)))),
        h("tbody", null, x.verdict_check.map(v => h("tr", { style: "cursor:default" }, h("td", null, badge(v.verdict)),
          h("td", { class: "r" }, pct(v.share)), h("td", { class: "r g" }, pct(v.target)), h("td", { class: "r rd" }, pct(v.stop)),
          h("td", { class: "r" }, pct(v.neither)), h("td", { class: "r" }, spct(v.gross, 2)), h("td", { class: "r " + (v.net >= 0 ? "up" : "down") }, spct(v.net, 2))))))),
      h("p", { class: "small muted", style: "margin-top:6px" }, `For comparison, a random share reaches its take-profit first ${pct(x.base_target)} of the time and its stop first ${pct(x.base_stop)}.`),
      h("h2", null, "Calendar patterns in the data"),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("h3", null, "1-month return of the average share, by month"),
          h("div", { class: "kv" }, MONTHS.flatMap((mn, i) => {
            const v = x.month_raw[String(i + 1).padStart(2, "0")];
            return [h("div", null, mn), h("div", { class: v == null ? "" : v >= x.base ? "up" : "down" }, v == null ? "–" : spct(v))];
          })), h("div", { class: "small muted", style: "margin-top:6px" }, `Normal: ${spct(x.base)}. Only two years of history, so each month rests on one or two samples.`)),
        h("div", { class: "card" }, h("h3", null, "By weekday"),
          h("div", { class: "kv" }, [h("div", { class: "muted" }, "Day"), h("div", { class: "muted" }, "Same day · next month")].concat(
            DAYS.flatMap(d => [h("div", null, d), h("div", null, `${spct(x.thursday.same_day[d], 2)} · ${spct(x.weekday_raw[d])}`)]))),
          h("div", { class: "small muted", style: "margin-top:6px" }, "Same day = average share's move that session. Next month = average share's return over the 20 sessions after buying that day."))),
      h("h2", null, "Latest periods"),
      h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Start", "Top 20", "Index", "All shares", "Picks at TP", "Picks"].map((c, i) => h("th", { class: i && i < 5 ? "r" : "" }, c)))),
        h("tbody", null, t.periods.slice(-12).reverse().map(w => h("tr", { style: "cursor:default" }, h("td", null, Charts.fmtDate(w.date)),
          h("td", { class: "r " + (w.top20 >= 0 ? "up" : "down") }, spct(w.top20)), h("td", { class: "r" }, spct(w.market)),
          h("td", { class: "r" }, spct(w.all)), h("td", { class: "r" }, pct(w.target)),
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
      h("h2", null, "The plan"),
      p("Your goal: at least +5% within the next month. Buy today (or at the next session) and keep a sell order at the share's take-profit (it fills when the day's high gets there, any day), or exit on a close at its own stop-loss. If neither is reached, sell by the sell-by date one month later."),
      h("h2", null, "Take-profit: set per share, never below +5%"),
      h("ul", null,
        h("li", null, "Just under the nearest resistance above the price: its 3-month high, its usual price level, or the top of its 2-year regular range."),
        h("li", null, "Used only if it is at least 5% away and within what the share usually moves in a month (1.2 × daily swing × √20, at most 15%). Otherwise the take-profit is the +5% minimum.")),
      h("h2", null, "Stop-loss: set per share"),
      h("ul", null,
        h("li", null, h("b", null, "Support first: "), "just under the lowest close of the last 20 sessions, less half a normal day's move as a buffer, if that is between max(3%, 1.2 normal days) and 12% below the price."),
        h("li", null, h("b", null, "Then the 3-month low: "), "the same rule using the lowest close of the last 3 months."),
        h("li", null, h("b", null, "Otherwise volatility: "), "the share's usual 2-week swing, kept between 4% and 12%.")),
      h("h2", null, "How the verdict is decided"),
      h("ul", null,
        h("li", null, h("b", null, "The odds: "), "a model trained walk-forward on two years of DSE data (cycle position, price vs its usual level, journey, trend, money flow, liquidity, risk, relative strength, fundamentals, junk pattern, similar past setups, and the take-profit and stop distances) estimates the chance that the take-profit comes first, that the stop comes first, or neither."),
        h("li", null, h("b", null, "Lead: "), "chance of the take-profit first minus chance of the stop first, in points."),
        h("li", null, h("b", null, "Buy (all must hold): "), "lead of +15 points or more (+25 for operator / junk shares); price below its usual level; journey not Topping or Mid fall; not in a drastic fall (10%+ down in a week, a limit-down day in 4 weeks, or RSI below 35); and if it has been falling (Early / Late fall, or 5%+ down in a week), a sign of a turn: a higher 10-day low, the 5-day average back above the 10-day, or 3%+ off its 10-day low. These are fixed levels: a share isn't compared with other shares."),
        h("li", null, h("b", null, "Sell (either one): "), "the stop is more likely to come first than the take-profit while the price is at or above its usual level; or the price is more than 20% above its usual level without a +15 lead."),
        h("li", null, h("b", null, "Neutral: "), "everything else. Each share's page lists every condition it met or missed, the reasoning behind its plan, and what changed since the previous session."),
        h("li", null, h("b", null, "Usual price level: "), "the share's 2-year average, unless the share has moved to a new price range (last year's average 30%+ away from the year before's, like PENINSULA going from about Tk 11 to Tk 20–25). Then the old range would mislead, so last year's average is used."),
        h("li", null, h("b", null, "Why it matters: "), "on unseen days, shares with a +15 lead that were below their usual level did much better (about +0.9% per trade before costs) than those above it (about +0.2%), and shares 20%+ above their usual level lost about 1.3% per trade after costs."),
        h("li", null, h("b", null, "Honest check: "), "on unseen days, Buys reached their take-profit first about 60% of the time and hit their stop first about 17% (a random share: about 51% and 26%), about +0.9% per trade after ~1% costs. Sells hit their stop first 29% of the time and lost about 0.2% per trade after costs."),
        h("li", null, h("b", null, "Confidence (0–100): "), "history, liquidity, cycle regularity and how clear-cut the odds are. Junk shares are scaled down by a quarter, dead ones by half."),
        h("li", null, h("b", null, "Ranking: "), "Buys first, then Neutral, each ordered by lead; at most 4 per sector when showing all sectors.")),
      h("h2", null, "Trade plans"),
      h("ul", null,
        h("li", null, h("b", null, "Buy zone: "), "from about one normal day's move below today's price to half a day's move above it. Buying above the zone is chasing."),
        h("li", null, h("b", null, "Reward : risk: "), "take-profit distance ÷ stop distance. Each plan shows the win rate needed to break even next to this share's odds."),
        h("li", null, h("b", null, "Position size: "), "shares so that hitting the stop costs your chosen % of capital (default 1%), capped at 15% of capital per share and 10% of its daily turnover.")),
      h("h2", null, "My stocks"),
      p("Star any share to watch it, and add what you own with your buy price. After each update the My stocks page lists tag changes, watched Buys inside their buy zone, and holdings near their stop-loss or tagged Sell. It is saved only in your browser; use Export / Import to back it up or move it."),
      h("h2", null, "Ranges"),
      h("ul", null,
        h("li", null, h("b", null, "Regular range: "), "the 10th to 90th percentile of all closing prices over the last 2 years."),
        h("li", null, h("b", null, "Outlier low / high: "), "the true lowest and highest close in those 2 years."),
        h("li", null, h("b", null, "Current swing: "), "the same percentiles over the last 3 months, a lighter band on the chart.")),
      h("h2", null, "What the model looks at"),
      p("Cycle position, trend & momentum (returns, moving averages, RSI), money flow (volume vs normal, up-day vs down-day volume, trade size), liquidity, risk (volatility, circuit hits, drawdown), relative strength vs market and sector, fundamentals (category, holdings, reserves), junk pattern (volume spikes, circuit runs, pumps, small paid-up capital) and similar past setups in the same share."),
      p("Market mood is shown as a banner but is not fed to the model: with two years of history the model would learn what the market happened to do rather than which shares beat others."),
      h("h2", null, "Calendar effects"),
      p("Month-of-year effects, weekday effects (including Thursday, the last session before DSE's weekend) and a 2-year-cycle tilt were all tested as add-ons to the expected move. None made it more accurate on unseen periods, so they are shown for reference on the Track record page. The Sunday dip after the weekend appears as a timing tip."),
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
        h("div", null, h("h1", null, d.sym, " ", starBtn(d.sym)), h("div", { class: "muted" }, `${d.sector} · Category ${d.cat}`), h("div", null, tags(d))),
        h("div", { style: "text-align:right" }, h("div", { class: "price num" }, num(d.close)), h("div", { class: d.chg >= 0 ? "up" : "down" }, spct(d.chg) + " today"))),
      h("div", { class: "grid two" },
        h("div", { class: "card decision" },
          h("div", { class: "dh" }, h("div", null, h("h3", null, `Next month · until ${SELLBY()}`), h("div", { class: "small muted" }, `Take-profit ${spct(o.target_dist)} · stop ${spct(-o.stop_dist)} · up to 20 trading days`)), badge(o.verdict)),
          expBlock(o, d),
          h("div", null, phaseChip(o)), h("div", { class: "journey" }, o.journey),
          bs(o, true),
          h("div", { style: "display:flex;gap:22px;flex-wrap:wrap" }, moveStat(o), confStat(o), stat("rank", `${o.rank} / ${S.summary.universe}`))),
        tagPanel(o)),
      h("div", { style: "margin-top:12px" }, planCard(d)),
      h("h2", null, "The journey so far, and the expected path"),
      rangeBtns,
      h("div", { class: "legend" },
        h("span", null, h("i", { style: `background:${css("--ink")}` }), "Close (adjusted for bonus shares)"),
        h("span", null, h("i", { class: "area", style: `background:${css("--range")};opacity:.28` }), "Regular range (2 yrs, 10th–90th pct)"),
        h("span", null, h("i", { class: "area", style: `background:${css("--s2")};opacity:.22` }), "Current swing (3 months)"),
        h("span", null, h("i", { style: `background:${css("--muted")}` }), "Outlier low / high (2 yrs)"),
        h("span", null, h("i", { class: "dot", style: `background:${css("--buy")}` }), "Swing low"),
        h("span", null, h("i", { class: "dot", style: `background:${css("--sell")}` }), "Swing high"),
        h("span", null, h("i", { class: "area", style: `background:${o.verdict === "Sell" ? css("--sell") : css("--buy")};opacity:.3` }), "Plan: take-profit and stop-loss until " + SELLBY())),
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
          h("div", { class: "small muted", style: "margin-bottom:4px" }, "Lead (take-profit chance minus stop chance, points) over the last 3 months"),
          histBox,
          h("div", { class: "chips small", style: "margin-top:6px" }, (() => {
            const hv = d.history.short, out = [];
            for (let i = 0; i < hv.dates.length; i++) if (!i || hv.verdict[i] !== hv.verdict[i - 1]) out.push([hv.dates[i], hv.verdict[i]]);
            return out.slice(-4).map(([dt, v]) => h("span", null, Charts.fmtDate(dt), " ", badge(v)));
          })()))),
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
          ["Usual reach of the day's high (4 wks)", m.reach20 != null ? "+" + pct(m.reach20, 1) : "–"],
          ["Days the high reached +5% (4 wks)", m.reach5_hits20 ?? "–"],
          ["Upper-circuit hits (4 wks)", m.uc_hits20 ?? "–"],
          ["Median turnover", d.liq != null ? `Tk ${num(d.liq, 1)} mn/day` : "–"],
          ["Junk score", pct(m.junk_score)],
        ]))),
      h("div", { class: "grid two", style: "margin-top:12px" },
        h("div", { class: "card" }, h("h3", null, "Similar past setups"),
          d.analogs.short.length ? h("div", null,
            h("div", { class: "small muted", style: "margin:4px 0" }, `The ${d.analogs.short.length} most similar earlier days in ${d.sym} and the month after`),
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
        projection: { steps: 20, from: s.close[n - 1], mid: s.close[n - 1],
          lo: s.close[n - 1] * (1 - o.plan.risk_pct), hi: s.close[n - 1] * (1 + o.plan.reward_pct),
          color: o.verdict === "Sell" ? css("--sell") : css("--buy"), label: SELLBY(), text: `TP Tk ${num(o.plan.take_profit)}` },
      });
      const cl = s.close;
      Charts.columns(volBox, {
        dates, height: 100, name: "Volume", color: css("--muted"), values: cut(s.volume), fmt: v => Math.round(v).toLocaleString(),
        yFormat: v => v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? Math.round(v / 1e3) + "K" : v,
        colors: cut(cl.map((x, i) => i && x < cl[i - 1] ? css("--sell") : css("--buy"))),
      });
      const hs = d.history.short;
      Charts.line(histBox, {
        dates: hs.dates, height: 200, label: "Outlook history", yFormat: v => Math.round(v),
        series: [{ name: "Lead (points)", values: hs.exp.map(v => v == null ? null : v * 100), color: css("--s1"), fmt: v => v.toFixed(0) }],
      });
    });
    return out;
  }

  // ---------- My stocks
  function addHolding(sym, qty, price) {
    MY.holdings.push({ sym, qty: Math.max(1, Math.round(qty)), price: +price, date: S.summary.asof });
    mySave();
  }
  function holdingAdvice(hd, r) {
    const o = r.s, p = o.plan, pnl = r.close / hd.price - 1;
    const tp = Math.max(hd.price * (1 + GOAL()), p.take_profit), sl = p.stop;
    if (r.close >= tp) return ["good", `Up ${spct(pnl)}: take-profit reached (Tk ${num(tp)}). Sell`];
    if (r.close <= sl * 1.01) return ["bad", `At or near its stop-loss (Tk ${num(sl)}). Exit`];
    if (o.verdict === "Sell") return ["bad", `Sell: more likely to fall to its stop (Tk ${num(sl)}) than reach its take-profit first (${pct(o.stop_p)} vs ${pct(o.hit)})`];
    if (o.verdict === "Buy") return ["good", `Hold: still a Buy. Take profit at Tk ${num(tp)}, stop Tk ${num(sl)}`];
    return ["info", `Hold: Neutral. Take profit at Tk ${num(tp)} (at least +5% on your price), stop Tk ${num(sl)}`];
  }
  function changes() {
    const asof = S.summary.asof;
    const syms = [...new Set([...Object.keys(MY.watch), ...MY.holdings.map(x => x.sym)])].filter(x => S.bySym[x]);
    let stored = [];
    if (MY.changes && MY.changes.asof === asof) stored = MY.changes.items;
    else {
      const prev = (MY.seen && MY.seen.tags) || {};
      for (const sym of syms) {
        const t = S.bySym[sym].s.verdict;
        if (prev[sym] && prev[sym] !== t) stored.push({ sym, kind: t === "Buy" ? "good" : t === "Sell" ? "bad" : "info", text: `tag changed ${prev[sym]} → ${t}` });
      }
      MY.seen = { asof, tags: Object.fromEntries(syms.map(x => [x, S.bySym[x].s.verdict])) };
      MY.changes = { asof, items: stored };
      store(MY_KEY, JSON.stringify(MY));
    }
    const live = [];
    for (const sym of Object.keys(MY.watch)) {
      const r = S.bySym[sym]; if (!r) continue;
      const p = r.s.plan;
      if (r.s.verdict === "Buy" && r.close >= p.entry_lo && r.close <= p.entry_hi) live.push({ sym, kind: "good", text: `is a Buy and inside its buy zone (Tk ${num(p.entry_lo)}–${num(p.entry_hi)})` });
    }
    for (const hd of MY.holdings) {
      const r = S.bySym[hd.sym]; if (!r) continue;
      const [kind, text] = holdingAdvice(hd, r);
      if (kind === "bad") live.push({ sym: hd.sym, kind, text: text.charAt(0).toLowerCase() + text.slice(1) });
    }
    return stored.concat(live);
  }
  function viewMine() {
    const s = S.summary;
    const alerts = changes();
    const watch = Object.entries(MY.watch).filter(([x]) => S.bySym[x]);
    const symIn = h("input", { list: "symlist", placeholder: "Symbol", "aria-label": "Symbol", style: "width:140px;text-transform:uppercase" });
    const qtyIn = h("input", { type: "number", min: "1", placeholder: "Shares", "aria-label": "Number of shares", style: "width:110px" });
    const priceIn = h("input", { type: "number", min: "0", step: "0.1", placeholder: "Buy price", "aria-label": "Buy price", style: "width:120px" });
    const msg = h("span", { class: "small muted" });
    const add = () => {
      const sym = symIn.value.trim().toUpperCase();
      if (!S.bySym[sym]) { msg.textContent = `“${sym}” isn't a listed share.`; return; }
      if (!(+qtyIn.value > 0) || !(+priceIn.value > 0)) { msg.textContent = "Enter the number of shares and your buy price."; return; }
      addHolding(sym, +qtyIn.value, +priceIn.value); route();
    };
    symIn.addEventListener("change", () => { const r = S.bySym[symIn.value.trim().toUpperCase()]; if (r && !priceIn.value) priceIn.value = r.close; });
    const capIn = h("input", { type: "number", min: "1000", step: "1000", value: MY.capital, "aria-label": "Your capital in Taka" });
    const riskIn = h("input", { type: "number", min: "0.1", max: "10", step: "0.1", value: MY.risk, "aria-label": "Risk per trade in percent" });
    const saveSettings = () => { MY.capital = Math.max(1000, +capIn.value || 0); MY.risk = Math.min(10, Math.max(0.1, +riskIn.value || 1)); mySave(); };
    capIn.addEventListener("change", saveSettings); riskIn.addEventListener("change", saveSettings);
    let invested = 0, value = 0;
    MY.holdings.forEach(hd => { const r = S.bySym[hd.sym]; invested += hd.qty * hd.price; value += hd.qty * (r ? r.close : hd.price); });
    const fileIn = h("input", { type: "file", accept: "application/json", style: "display:none", onchange: e => {
      const f = e.target.files[0]; if (!f) return;
      f.text().then(t => { const x = JSON.parse(t); MY = { ...MY, watch: x.watch || {}, holdings: x.holdings || [], capital: x.capital || MY.capital, risk: x.risk || MY.risk }; mySave(); route(); })
        .catch(() => { msg.textContent = "That file couldn't be read."; });
    } });
    return h("div", null,
      h("h1", null, "My stocks"),
      h("p", { class: "sub" }, "Your watchlist and holdings, checked against today's tags and trade plans. Saved in this browser only: use Export to keep a backup or move to another device."),
      h("div", { class: "card", style: "margin-bottom:12px" }, h("h3", null, "What changed · data to " + Charts.fmtDate(s.asof)),
        alerts.length ? h("ul", { class: "alerts" }, alerts.map(a => h("li", { class: "al-" + a.kind, onclick: () => go(a.sym) }, h("b", null, a.sym), " ", a.text)))
          : h("div", { class: "empty small" }, watch.length || MY.holdings.length ? "Nothing new since your last visit." : "Star shares (☆) or add holdings below, and changes will show up here after each update.")),
      h("h2", null, `Holdings (${MY.holdings.length})`),
      MY.holdings.length ? h("div", { class: "grid tiles", style: "margin-bottom:10px" },
        tile("Invested", `Tk ${Math.round(invested).toLocaleString()}`), tile("Value now", `Tk ${Math.round(value).toLocaleString()}`),
        tile("Profit / loss", `${value >= invested ? "+" : "−"}Tk ${Math.abs(Math.round(value - invested)).toLocaleString()}`, spct(invested ? value / invested - 1 : 0), value >= invested ? "up" : "down")) : null,
      h("div", { class: "filters" }, symIn, qtyIn, priceIn, h("button", { class: "chip", type: "button", onclick: add }, "＋ Add holding"), msg,
        h("datalist", { id: "symlist" }, s.stocks.map(r => h("option", { value: r.sym })))),
      MY.holdings.length ? h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Share", "Shares", "Bought at", "Now", "P/L", "Tag", "What to do", ""].map((c, i) => h("th", { class: i >= 1 && i <= 4 ? "r" : "" }, c)))),
        h("tbody", null, MY.holdings.map((hd, i) => {
          const r = S.bySym[hd.sym];
          if (!r) return h("tr", null, h("td", null, hd.sym), h("td", { colspan: 7, class: "muted" }, "No longer listed"));
          const pnl = r.close / hd.price - 1, [kind, adv] = holdingAdvice(hd, r);
          return h("tr", { onclick: () => go(hd.sym) }, h("td", null, h("b", null, hd.sym)), h("td", { class: "r" }, hd.qty.toLocaleString()),
            h("td", { class: "r" }, num(hd.price)), h("td", { class: "r" }, num(r.close)),
            h("td", { class: "r " + (pnl >= 0 ? "up" : "down") }, `${spct(pnl)} (Tk ${Math.round((r.close - hd.price) * hd.qty).toLocaleString()})`),
            h("td", null, badge(r.s.verdict)), h("td", { class: "adv adv-" + kind, style: "white-space:normal;min-width:260px" }, adv),
            h("td", null, h("button", { class: "chip", type: "button", title: "Remove", onclick: e => { e.stopPropagation(); MY.holdings.splice(i, 1); mySave(); route(); } }, "✕")));
        })))) : h("div", { class: "empty small" }, "No holdings yet."),
      h("h2", null, `Watchlist (${watch.length})`),
      watch.length ? h("div", { class: "tbl-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Share", "Price", "Tag", "TP / stop odds", "Journey", "Plan", "Since you added", ""].map((c, i) => h("th", { class: i === 1 || i === 3 ? "r" : "" }, c)))),
        h("tbody", null, watch.map(([sym, w]) => {
          const r = S.bySym[sym], o = r.s, p = o.plan;
          return h("tr", { onclick: () => go(sym) }, h("td", null, h("b", null, sym)), h("td", { class: "r" }, num(r.close)),
            h("td", null, badge(o.verdict)), h("td", { class: "r" }, `${pct(o.hit)} / ${pct(o.stop_p)}`), h("td", null, o.phase),
            h("td", { class: "small", style: "white-space:normal;min-width:220px" }, o.verdict === "Sell" ? "Avoid" : `Buy ${num(p.entry_lo)}–${num(p.entry_hi)}, sell at ${num(p.take_profit)} or ${num(p.stop)}, else by ${p.sell_by}`),
            h("td", { class: "small muted" }, w.tag && w.tag !== o.verdict ? `${w.tag} → ${o.verdict}` : `added ${Charts.fmtDate(w.added)}`),
            h("td", null, starBtn(sym)));
        })))) : h("div", { class: "empty small" }, "Tap ☆ on any share to watch it."),
      h("h2", null, "Position sizing"),
      h("div", { class: "card" },
        h("div", { class: "sizer" }, h("label", null, "Your capital (Tk) ", capIn), h("label", null, "Risk per trade (%) ", riskIn)),
        h("p", { class: "small muted", style: "margin-bottom:0" }, "Each trade plan sizes the position so that hitting the stop-loss costs about this % of your capital, capped at 15% of capital per share and 10% of the share's daily turnover. 1% is a common, cautious choice.")),
      h("h2", null, "Backup"),
      h("div", { class: "chips" },
        h("button", { class: "chip", type: "button", onclick: () => {
          const blob = new Blob([JSON.stringify({ watch: MY.watch, holdings: MY.holdings, capital: MY.capital, risk: MY.risk }, null, 2)], { type: "application/json" });
          const a = h("a", { href: URL.createObjectURL(blob), download: `dse-my-stocks-${s.asof}.json` }); document.body.appendChild(a); a.click(); a.remove();
        } }, "⤓ Export"),
        h("button", { class: "chip", type: "button", onclick: () => fileIn.click() }, "⤒ Import"), fileIn));
  }

  // ---------- routing
  const TABS = [["top", "Top picks"], ["mine", "My stocks"], ["all", "All shares"], ["sectors", "Sectors"], ["track", "Track record"], ["how", "How it works"]];
  async function route() {
    const hash = decodeURIComponent(location.hash.slice(1)) || "top";
    const [view, arg] = hash.split("/");
    document.querySelectorAll("nav.tabs a").forEach(a => a.classList.toggle("on", a.dataset.v === view));
    let node;
    try {
      if (view === "s" && arg) node = await viewStock(arg);
      else if (view === "sectors") node = viewSectors();
      else if (view === "mine") node = viewMine();
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
    const btn = document.getElementById("theme");
    btn.textContent = { auto: "◐ Auto", light: "☀ Light", dark: "☾ Dark" }[t];
    btn.setAttribute("aria-label", `Theme: ${t} (click to change)`);
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
    navCount();
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
