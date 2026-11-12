// Insights (admin only): alerts, adoption, feature use, outcomes, cost and service health, from
// /api/admin/insights. Uses $, el, api, fail from the page script. Counts only: no names or text.
"use strict";

const INS_SVG = "http://www.w3.org/2000/svg";
const INS_CHART = { w: 320, h: 140, left: 30, right: 6, top: 10, bottom: 20 };
const INS_LEVELS = { critical: { icon: "▲", label: "Critical" }, warning: { icon: "●", label: "Warning" } };
let insDays = 7;

function insSvg(tag, attrs = {}, ...kids) {
  const node = document.createElementNS(INS_SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  for (const kid of kids) node.append(kid);
  return node;
}
const insNum = (v, unit = "") => (v == null ? "–" : `${Math.round(v * 10) / 10}${unit}`);
const insMoney = (v) => (v == null ? "–" : `$${v > 0 && v < 0.1 ? v.toFixed(4) : v.toFixed(2)}`);
const insMs = (v) => (v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`);
const insDay = (iso) => new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });

async function loadInsights() {
  $("insights").replaceChildren(el("p", { className: "muted", textContent: "Loading insights…" }));
  const data = await api(`/api/admin/insights?days=${insDays}`);
  renderInsights(data);
}

function renderInsights(d) {
  const b = d.business, e = d.engineering;
  const switcher = el("div", { className: "subtabs", role: "tablist", style: "margin:0" },
    ...[7, 30].map((n) => {
      const btn = el("button", { type: "button", role: "tab", textContent: `Last ${n} days` });
      btn.setAttribute("aria-selected", String(n === insDays));
      btn.addEventListener("click", () => { insDays = n; loadInsights().catch(fail); });
      return btn;
    }));
  const updated = new Date(d.generated_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  $("insights").replaceChildren(
    el("div", { className: "chart-head", style: "margin-bottom:12px" },
      el("div", {}, el("h2", { textContent: "Insights" }),
        el("p", { className: "lede", style: "margin:0", textContent: `What people do with Saarthi and how well it runs. Updated ${updated}. Your own activity is left out.` })),
      switcher),
    insAlerts(d.alerts),
    el("h3", { textContent: "Adoption" }),
    el("div", { className: "tiles" },
      insTile("Active people", insNum(b.active_users), `${b.weekly_active_users} in the last 7 days`),
      insTile("New", insNum(b.new_users), "first time in this period"),
      insTile("Returning", insNum(b.returning_users), "seen before this period"),
      insTile("Active on 2+ days", insNum(b.active_on_2plus_days_pct, "%"), "of active people"),
      insTile("Came back in week 2", insNum(b.second_week_return_pct, "%"),
        b.second_week_cohort ? `of ${b.second_week_cohort} who started 7+ days ago` : "not enough history yet")),
    el("div", { className: "charts" },
      insBarCard("Active people per day", "people", b.daily_active.map((p) => ({ label: insDay(p.day), value: p.users }))),
      insFunnel(b.funnel)),
    el("h3", { textContent: "What people use" }),
    el("div", { className: "charts" },
      insHBars("Feature use", b.features.map((f) => ({ label: f.feature, value: f.uses, note: f.users == null ? "" : `${f.users} people` }))),
      insTable("Most practised roleplays", ["Roleplay", "Calls", "Finished", "Avg score"],
        b.top_scenarios.map((s) => [s.scenario, s.calls, s.finished, insNum(s.avg_score, "%")]), "No calls in this period.")),
    el("h3", { textContent: "Are people getting better?" }),
    el("div", { className: "tiles" },
      insTile("First → fifth call", insChange(b.scores.first_to_fifth), `${b.scores.first_to_fifth_users} people with 5+ scored calls`),
      insTile("First → latest call", insChange(b.scores.first_to_latest), `${b.scores.first_to_latest_users} people with 2+ scored calls`),
      insTile("Cost in this period", insMoney(b.cost.total_usd), "model spend, everyone"),
      insTile("Per active person", insMoney(b.cost.per_active_user_usd), "model spend"),
      insTile("Per finished call", insMoney(b.cost.per_finished_call_usd), "model spend")),
    el("div", { className: "charts" },
      insBarCard("Average score by call number", "%", b.scores.by_call.map((c) => ({ label: `Call ${c.call}`, value: c.avg_score, tip: `${c.users} people` })), 100)),
    el("h3", { textContent: "Service health" }),
    el("div", { className: "tiles" },
      insTile("Requests", insNum(e.requests), `${e.errors} server errors`),
      insTile("Error rate", insNum(e.error_pct, "%"), "server errors (5xx)", (e.error_pct || 0) > 2),
      insTile("Customer reply", insMs(e.reply.p50_ms), `typical; 1 in 20 slower than ${insMs(e.reply.p95_ms)}`),
      insTile("Scorecard", insMs(e.scorecard.p50_ms), `typical; 1 in 20 slower than ${insMs(e.scorecard.p95_ms)}`),
      insTile("AI backup used", insNum(e.fallbacks.model_fallback_pct, "%"), `${e.fallbacks.model_fallbacks} of ${e.fallbacks.model_calls} model calls`, (e.fallbacks.model_fallback_pct || 0) > 10),
      insTile("Browser voice", insNum(e.voice_budget.browser_voice_pct, "%"), "of customer lines, instead of the human voice")),
    el("div", { className: "tiles" },
      insMeter("Spend today", e.spend.today_usd, e.spend.daily_cap_usd, (v) => insMoney(v)),
      insMeter("Human voice this month", e.voice_budget.chars_this_month, e.voice_budget.monthly_cap, (v) => `${v.toLocaleString()} chars`)),
    el("div", { className: "charts" },
      insBarCard("Requests per day", "requests", e.by_day.map((p) => ({ label: insDay(p.day), value: p.requests, tip: `${p.errors} errors` }))),
      insBarCard("Slowest customer replies per day (p95)", "s", e.by_day.map((p) => ({ label: insDay(p.day), value: p.reply_p95_ms == null ? null : p.reply_p95_ms / 1000 })))),
    el("div", { className: "charts" },
      insTable("Backups used", ["What", "Times"], e.fallbacks.by_name.map((f) => [f.name, f.count]), "No backups used."),
      insTable("Where errors happen", ["Route", "Errors"], e.error_routes.map((r) => [r.route, r.count]), "No server errors.")));
}

function insAlerts(alerts) {
  if (!alerts.length) {
    return el("div", { className: "card alert ok", id: "insights-alerts" },
      el("b", { textContent: "✓ All clear" }), el("span", { className: "muted", textContent: " No alerts right now." }));
  }
  return el("div", { id: "insights-alerts" }, ...alerts.map((a) => {
    const level = INS_LEVELS[a.level] || INS_LEVELS.warning;
    return el("div", { className: `card alert ${a.level}`, role: "alert" },
      el("b", {}, el("span", { ariaHidden: "true", textContent: level.icon + " " }), `${level.label}: ${a.title}`),
      el("p", { textContent: a.reason }));
  }));
}

function insTile(label, value, note, warn = false) {
  return el("div", { className: "card tile" + (warn ? " warn" : "") },
    el("span", { className: "muted", textContent: label }), el("b", { textContent: value }),
    el("span", { className: "muted", style: "font-size:13px", textContent: note }));
}

function insChange(v) { return v == null ? "–" : `${v > 0 ? "+" : ""}${v} pts`; }

function insMeter(label, value, cap, show) {
  const pct = cap ? Math.min(100, Math.round((100 * value) / cap)) : 0;
  const bar = el("div", { className: "bar", role: "meter", ariaValueMin: "0", ariaValueMax: "100", ariaValueNow: String(pct), ariaLabel: label });
  bar.append(el("i", { style: `width:${pct}%;background:${pct >= 80 ? "var(--bad)" : "var(--brand)"}` }));
  return el("div", { className: "card tile" }, el("span", { className: "muted", textContent: label }),
    el("b", { style: "font-size:22px", textContent: `${pct}%` }), bar,
    el("span", { className: "muted", style: "font-size:13px", textContent: `${show(value)} of ${show(cap)}` }));
}

// A card holding a chart, with a button that swaps it for the same numbers as a table.
function insCard(title, chart, rows, headers) {
  const card = el("div", { className: "card chart", style: "position:relative" });
  const toggle = el("button", { className: "ghost", type: "button", style: "padding:3px 10px;font-size:12px", textContent: "Table" });
  const table = el("table", { className: "hidden" }, el("tr", {}, ...headers.map((h) => el("th", { textContent: h }))),
    ...rows.map((r) => el("tr", {}, ...r.map((c) => el("td", { textContent: String(c) })))));
  toggle.addEventListener("click", () => {
    const showTable = table.classList.contains("hidden");
    table.classList.toggle("hidden", !showTable); chart.classList.toggle("hidden", showTable);
    toggle.textContent = showTable ? "Chart" : "Table";
  });
  card.append(el("div", { className: "chart-head" }, el("b", { textContent: title }), toggle), chart, table);
  return card;
}

function insBarCard(title, unit, points, fixedTop) {
  const values = points.map((p) => p.value).filter((v) => v != null);
  const shown = (v) => (v == null ? "no data" : unit === "%" ? `${insNum(v)}%` : unit === "s" ? `${insNum(v)} s` : `${insNum(v)} ${unit}`);
  const rows = points.map((p) => [p.label, shown(p.value), ...(p.tip ? [p.tip] : [])]);
  const headers = ["", title, ...(points.some((p) => p.tip) ? ["Note"] : [])];
  if (!values.length) return insCard(title, el("p", { className: "muted", textContent: "No data in this period yet." }), rows, headers);
  const top = fixedTop || Math.max(1, Math.ceil(Math.max(...values) * 1.15));
  const { w, h, left, right, top: pt, bottom } = INS_CHART;
  const slot = (w - left - right) / points.length;
  const barW = Math.max(3, Math.min(28, slot - 2));
  const y = (v) => pt + (1 - v / top) * (h - pt - bottom);
  const svg = insSvg("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": `${title}: ${rows.map((r) => `${r[0]} ${r[1]}`).join(", ")}` });
  svg.append(insSvg("line", { x1: left, x2: w - right, y1: h - bottom, y2: h - bottom, stroke: "var(--line)" }));
  svg.append(insSvg("text", { x: left - 6, y: pt + 4, "text-anchor": "end", class: "axis" }, shown(top).replace(" " + unit, "")));
  svg.append(insSvg("text", { x: left - 6, y: h - bottom + 4, "text-anchor": "end", class: "axis" }, "0"));
  const tip = el("div", { className: "tip hidden" });
  const card = insCard(title, el("div", {}, svg, tip), rows, headers);
  const every = Math.ceil(points.length / 7);
  points.forEach((p, i) => {
    const cx = left + slot * i + slot / 2;
    if (i % every === 0 || i === points.length - 1) {
      svg.append(insSvg("text", { x: cx, y: h - 6, "text-anchor": "middle", class: "axis" }, p.label));
    }
    if (p.value == null) return;
    const top0 = y(p.value), height = Math.max(0, h - bottom - top0);
    // Rounded top, square base: a 4px-radius rect with its bottom corners covered.
    svg.append(insSvg("rect", { x: cx - barW / 2, y: top0, width: barW, height, rx: Math.min(4, barW / 2), fill: "var(--brand)" }));
    if (height > 4) svg.append(insSvg("rect", { x: cx - barW / 2, y: h - bottom - 4, width: barW, height: 4, fill: "var(--brand)" }));
    const hit = insSvg("rect", { x: left + slot * i, y: pt, width: slot, height: h - pt - bottom, fill: "transparent" });
    hit.addEventListener("mouseenter", () => {
      const box = svg.getBoundingClientRect(), cardBox = card.getBoundingClientRect();
      tip.textContent = `${p.label} · ${shown(p.value)}${p.tip ? " · " + p.tip : ""}`;
      tip.style.left = `${box.left - cardBox.left + (cx / w) * box.width}px`;
      tip.style.top = `${box.top - cardBox.top + (top0 / h) * box.height}px`;
      tip.classList.remove("hidden");
    });
    hit.addEventListener("mouseleave", () => tip.classList.add("hidden"));
    svg.append(hit);
  });
  return card;
}

// Horizontal bars, labelled directly: for the funnel and feature use.
function insHBars(title, items, id) {
  const max = Math.max(1, ...items.map((i) => i.value));
  const list = el("div", { className: "hbars" }, ...items.map((i) => el("div", { className: "hbar" },
    el("div", { className: "hbar-label" }, el("span", { textContent: i.label }),
      el("b", { textContent: `${i.value}${i.note ? " · " + i.note : ""}` })),
    el("div", { className: "bar" }, el("i", { style: `width:${(100 * i.value) / max}%` })))));
  const card = insCard(title, list, items.map((i) => [i.label, i.value, i.note || ""]), ["", "Count", "Note"]);
  if (id) card.id = id;
  return card;
}

function insFunnel(funnel) {
  return insHBars("From sign-in to a second call", funnel.map((f) => ({ label: f.step, value: f.users, note: f.pct == null ? "" : `${f.pct}%` })), "insights-funnel");
}

function insTable(title, headers, rows, empty) {
  const table = el("table", {}, el("tr", {}, ...headers.map((h) => el("th", { textContent: h }))));
  if (!rows.length) table.append(el("tr", {}, el("td", { colSpan: headers.length, className: "muted", textContent: empty })));
  for (const r of rows) table.append(el("tr", {}, ...r.map((c) => el("td", { textContent: String(c) }))));
  return el("div", { className: "card" }, el("b", { textContent: title }), table);
}
