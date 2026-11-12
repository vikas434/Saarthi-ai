// The dashboard: streak and stats, plain insights, up to four focus metrics over time against a
// target, and for the admin a team table. Uses $, el, api, fail, cfg from the page script.
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const CHART = { w: 300, h: 120, left: 30, right: 36, top: 12, bottom: 18 };
const MAX_FOCUS_PICK = 4;
let dashData = null;

function svgEl(tag, attrs = {}, ...kids) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  for (const kid of kids) node.append(kid);
  return node;
}
function fmt(value, unit) { return `${Math.round(value * 10) / 10}${unit}`; }
function shortDate(iso) { return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }); }

async function loadDashboard() {
  dashData = await api("/api/dashboard");
  renderDashboard();
  if (cfg.role === "admin") loadTeam().catch(fail);
}

function renderDashboard() {
  const d = dashData;
  const stat = (label, value, note) => el("div", { className: "card tile stat" },
    el("span", { className: "muted", textContent: label }), el("b", { textContent: value }), el("span", { className: "muted", textContent: note }));
  const stats = el("div", { className: "tiles" },
    stat("Practice streak", `${d.streak} day${d.streak === 1 ? "" : "s"}`, d.streak ? "keep it going" : "practise today to start one"),
    stat("Calls this week", String(d.calls_this_week), "scored roleplays"),
    stat("Scored calls", String(d.calls), "in your trends"));
  const insights = el("div", { className: "card", style: "margin-bottom:16px" }, el("h3", { textContent: "Insights" }),
    el("ul", { style: "margin:0;padding-left:18px" }, ...d.insights.map((x) => el("li", { textContent: x }))));
  const byId = Object.fromEntries(d.catalog.map((m) => [m.id, m]));
  const choose = el("button", { className: "ghost", type: "button", id: "choose-focus", textContent: "Choose focus" });
  choose.addEventListener("click", () => toggleFocusPicker(byId));
  const charts = el("div", { className: "charts", id: "focus-charts" },
    ...d.focus.map((id) => focusChart(byId[id], d.series[id] || [])));
  $("dashboard").replaceChildren(stats, insights,
    el("div", { className: "chart-head", style: "margin-bottom:8px" }, el("h3", { textContent: "Your focus" }), choose),
    el("div", { id: "focus-picker" }), charts);
}

function toggleFocusPicker(byId) {
  const box = $("focus-picker");
  if (box.childElementCount) { box.replaceChildren(); return; }
  const chosen = new Set(dashData.focus);
  const note = el("span", { className: "muted" });
  const boxes = dashData.catalog.map((m) => {
    const input = el("input", { type: "checkbox", value: m.id, checked: chosen.has(m.id) });
    input.addEventListener("change", () => {
      const picked = boxes.filter((b) => b.querySelector("input").checked).length;
      note.textContent = picked > MAX_FOCUS_PICK ? `Pick up to ${MAX_FOCUS_PICK}.` : "";
    });
    return el("label", {}, input, " " + m.name);
  });
  const save = el("button", { className: "primary", type: "button", id: "save-focus", textContent: "Save focus" });
  save.addEventListener("click", async () => {
    const metrics = boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    try {
      const r = await api("/api/dashboard/focus", { method: "PUT", body: JSON.stringify({ metrics }) });
      dashData = { ...dashData, focus: r.focus }; renderDashboard();
    } catch (err) { fail(err); }
  });
  box.replaceChildren(el("div", { className: "card", style: "margin-bottom:16px" },
    el("p", { className: "muted", style: "margin:0", textContent: `Pick up to ${MAX_FOCUS_PICK} metrics to follow.` }),
    el("div", { className: "focus-pick" }, ...boxes), el("div", { className: "row" }, save, note)));
}

const PACE_BAND = 30;  // words per minute either side of the pace target counts as on target
function onTarget(metric, v) {
  if (metric.better === "lower") return v <= metric.target;
  if (metric.better === "range") return Math.abs(v - metric.target) <= PACE_BAND;
  return v >= metric.target;
}
function improved(metric, first, last) {
  if (metric.better === "lower") return last < first;
  if (metric.better === "range") return Math.abs(last - metric.target) < Math.abs(first - metric.target);
  return last > first;
}

function focusChart(metric, points) {
  const card = el("div", { className: "card chart", style: "position:relative" });
  const head = el("div", { className: "chart-head" }, el("b", { textContent: metric.name }));
  if (points.length) {
    const first = points[0].value, last = points[points.length - 1].value;
    const now = el("span", { className: "now", textContent: fmt(last, metric.unit) });
    head.append(now);
    let note = null;
    if (onTarget(metric, last)) note = ["up", `On target (${fmt(metric.target, metric.unit)})`];
    else if (points.length > 1 && first !== last) {
      const good = improved(metric, first, last);
      note = [good ? "up" : "down", `${good ? "Better" : "Worse"} than your first call (${fmt(first, metric.unit)})`];
    }
    card.append(head);
    if (note) card.append(el("div", { className: note[0], style: "font-size:13px", textContent: note[1] }));
  } else card.append(head);
  card.append(points.length ? lineChart(metric, points, card)
    : el("p", { className: "muted", textContent: "No data yet. Finish a call" + (metric.id === "pace" ? " with hands-free voice" : "") + " to see this." }));
  return card;
}

function lineChart(metric, points, card) {
  const values = points.map((p) => p.value);
  const percent = metric.unit === "%";
  const top = percent ? 100 : Math.ceil(Math.max(...values, metric.target) * 1.2) || 1;
  const { w, h, left, right, top: pt, bottom } = CHART;
  const x = (i) => left + (points.length === 1 ? (w - left - right) / 2 : (i * (w - left - right)) / (points.length - 1));
  const y = (v) => pt + (1 - Math.min(v, top) / top) * (h - pt - bottom);
  const label = `${metric.name}: ${values.map((v) => fmt(v, metric.unit)).join(", ")}; target ${fmt(metric.target, metric.unit)}`;
  const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": label });
  svg.append(svgEl("line", { x1: left, x2: w - right, y1: h - bottom, y2: h - bottom, stroke: "var(--line)", "stroke-width": 1 }));
  svg.append(svgEl("text", { x: left - 6, y: y(top) + 4, "text-anchor": "end", class: "axis" }, fmt(top, percent ? "%" : "")));
  svg.append(svgEl("text", { x: left - 6, y: h - bottom + 4, "text-anchor": "end", class: "axis" }, "0"));
  const ty = y(metric.target);
  svg.append(svgEl("line", { x1: left, x2: w - right, y1: ty, y2: ty, stroke: "var(--muted)", "stroke-width": 1, "stroke-dasharray": "4 4" }));
  svg.append(svgEl("text", { x: w - right + 4, y: ty + 4, class: "axis" }, "target"));
  svg.append(svgEl("text", { x: left, y: h - 4, class: "axis" }, shortDate(points[0].at)));
  if (points.length > 1) svg.append(svgEl("text", { x: w - right, y: h - 4, "text-anchor": "end", class: "axis" }, shortDate(points[points.length - 1].at)));
  if (points.length > 1) svg.append(svgEl("polyline", { points: points.map((p, i) => `${x(i)},${y(p.value)}`).join(" "),
    fill: "none", stroke: "var(--brand)", "stroke-width": 2, "stroke-linejoin": "round" }));
  const tip = el("div", { className: "tip hidden" });
  points.forEach((p, i) => {
    svg.append(svgEl("circle", { cx: x(i), cy: y(p.value), r: 4, fill: "var(--brand)", stroke: "#fff", "stroke-width": 2 }));
    const hit = svgEl("circle", { cx: x(i), cy: y(p.value), r: 12, fill: "transparent" },
      svgEl("title", {}, `${shortDate(p.at)}: ${fmt(p.value, metric.unit)}`));
    hit.addEventListener("mouseenter", () => {
      const box = svg.getBoundingClientRect(), cardBox = card.getBoundingClientRect();
      tip.textContent = `${shortDate(p.at)} · ${fmt(p.value, metric.unit)}`;
      tip.style.left = `${box.left - cardBox.left + (x(i) / w) * box.width}px`;
      tip.style.top = `${box.top - cardBox.top + (y(p.value) / h) * box.height}px`;
      tip.classList.remove("hidden");
    });
    hit.addEventListener("mouseleave", () => tip.classList.add("hidden"));
    svg.append(hit);
  });
  return el("div", {}, svg, tip);
}

async function loadTeam() {
  const rows = await api("/api/team");
  const table = el("table", { id: "team-table" },
    el("tr", {}, ...["Person", "Calls", "Last practice", "Average", "First → latest"].map((t) => el("th", { textContent: t }))));
  if (!rows.length) table.append(el("tr", {}, el("td", { colSpan: 5, className: "muted", textContent: "No scored calls yet." })));
  for (const r of rows) {
    const move = r.change == null ? "–" : `${r.first}% → ${r.latest}%`;
    const cls = r.change > 0 ? "up" : r.change < 0 ? "down" : "";
    table.append(el("tr", {}, el("td", { textContent: r.name }), el("td", { textContent: String(r.calls) }),
      el("td", { textContent: new Date(r.last_active).toLocaleDateString() }),
      el("td", { textContent: r.average == null ? "–" : r.average + "%" }), el("td", { className: cls, textContent: move })));
  }
  const box = $("team");
  box.replaceChildren(el("h3", { textContent: "Team" }),
    el("div", { className: "card", style: "margin-bottom:16px" },
      el("p", { className: "muted", style: "margin-top:0", textContent: "Everyone's scored calls, most active first. Overall score is the average of all markers." }), table));
  box.classList.remove("hidden");
}
