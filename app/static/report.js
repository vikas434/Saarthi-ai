// The scorecard after a call: score banner, then Coaching and Analytics tabs.
// Uses $ and el from the page script; loaded before it, called after it.
"use strict";

const ANALYTICS_GROUPS = [
  ["word_choice", "Word choice"],
  ["listening", "Listening"],
  ["delivery", "Delivery"],
  ["camera", "On camera"],
];

function markerValue(m) {
  if (m.type === "survey") return m.score == null ? "–" : `${m.score} / ${m.max}`;
  if (m.type === "checklist") return m.applicable ? `${m.passed} / ${m.applicable}` : "–";
  return m.percent == null ? "–" : m.percent + "%";
}

function barRow(score, max) {
  const bar = el("div", { className: "bar" }); const fill = el("i");
  fill.style.width = (max ? (100 * (score || 0)) / max : 0) + "%"; bar.append(fill); return bar;
}

function reportBanner(s, onAgain) {
  const r = s.report;
  const again = el("button", { className: "primary", textContent: "Practise again" });
  again.addEventListener("click", onAgain);
  const score = r.overall == null ? "" : `Your score was ${r.overall}%`;
  const meta = `Scored by ${r.scored_by} · ${r.agent_turns} replies`
    + (typeof s.cost_usd === "number" ? ` · Model cost $${s.cost_usd.toFixed(4)}` : "");
  return el("div", { className: "card banner" },
    el("div", {}, el("h2", { textContent: "Call complete" }),
      el("p", { className: "big", textContent: score }), el("p", { className: "muted", textContent: meta })),
    again);
}

function scoreTiles(r) {
  const tiles = el("div", { className: "tiles" });
  for (const m of r.markers) {
    const warn = m.type === "checklist" && m.critical_missed.length;
    tiles.append(el("div", { className: "card tile" + (warn ? " warn" : "") },
      el("span", { className: "muted", textContent: m.name }), el("b", { textContent: markerValue(m) }),
      el("span", { className: "muted", textContent: m.type === "survey" ? "customer's answer"
        : m.type === "checklist" ? (warn ? "critical item missed" : "items done") : "coach score" })));
  }
  return tiles;
}

function listCard(title, items) {
  const ul = el("ul", { style: "margin:0;padding-left:18px" });
  items.forEach((x) => ul.append(el("li", { textContent: x })));
  return el("div", { className: "card" }, el("h3", { textContent: title }), ul);
}

function markerCard(m) {
  const card = el("div", { className: "card", style: "margin-bottom:16px" },
    el("h3", { textContent: `${m.name} · ${markerValue(m)}` }));
  if (m.type === "survey") {
    card.append(el("p", { className: "muted", textContent: m.question }));
    if (m.reason && m.answered_by === "offline") card.append(el("p", { className: "muted", textContent: m.reason }));
    else if (m.reason) card.append(el("p", {}, "The customer said: ", el("q", { textContent: m.reason })));
    if (m.drivers.length) {
      card.append(el("p", { className: "muted", textContent: "Behaviours that drive this marker:" }));
      for (const d of m.drivers)
        card.append(el("div", { textContent: `${d.name}: ${d.score == null ? "not observed" : d.score + " / 5"}` }), barRow(d.score, 5));
    }
  } else if (m.type === "checklist") {
    for (const item of m.items) {
      const mark = { yes: "✓ Yes", no: "✗ No", na: "– n/a" }[item.result];
      const row = el("div", { className: "beh" }, el("span", { className: item.result, textContent: mark }),
        " · " + item.text + (item.critical ? " (critical)" : ""));
      if (item.evidence) row.append(el("div", { className: "muted", textContent: item.evidence }));
      card.append(row);
    }
  } else {
    for (const b of m.behaviors) {
      const row = el("div", { className: "beh" },
        el("div", {}, el("b", { textContent: b.name }), ` · ${b.score == null ? "not observed" : b.score + " / 5"}`), barRow(b.score, 5));
      if (b.evidence) row.append(el("div", {}, "You said: ", el("q", { textContent: b.evidence })));
      if (b.good) row.append(el("div", { textContent: "Good: " + b.good }));
      if (b.improve) row.append(el("div", { textContent: "Improve: " + b.improve }));
      if (b.say_instead) row.append(el("div", { className: "say", textContent: "Say instead: " + b.say_instead }));
      card.append(row);
    }
  }
  return card;
}

function transcriptCard(s) {
  const tips = new Map((s.report.lines || []).map((t) => [t.reply, t.better]));
  const box = el("details", { className: "card", open: tips.size > 0 },
    el("summary", { textContent: tips.size ? "Transcript with better lines" : "Transcript with coach notes" }));
  let reply = 0;
  for (const t of s.turns) {
    if (t.agent_text) {
      reply += 1;
      box.append(el("p", {}, el("b", { textContent: "You: " }), t.agent_text));
      if (tips.has(reply)) box.append(el("div", { className: "say", textContent: "Say it better: " + tips.get(reply) }));
    }
    if (t.coach) box.append(el("p", { className: "muted",
      textContent: `Coach (${t.coach.verdict}${t.coach.fallback ? ", backup" : ""}): ${t.coach.note}` }));
    box.append(el("p", {}, el("b", { textContent: "Customer: " }), t.customer_text));
  }
  return box;
}

function coachingTab(s) {
  const r = s.report, tab = el("div");
  const head = el("div", { className: "card", style: "margin-bottom:16px" },
    el("p", { textContent: r.summary }), el("p", {}, el("b", { textContent: "Next drill: " }), r.next_drill));
  if (r.fallback) head.append(el("p", { className: "error",
    textContent: "Some scores on this card are rule-of-thumb estimates: the model's answer could not be used. Treat them as rough." }));
  const lists = el("div", { className: "grid", style: "margin-bottom:16px" },
    listCard("What went well", r.strengths), listCard("What to work on", r.growth));
  if (r.follow_up_questions?.length) lists.append(listCard("Questions to prepare for", r.follow_up_questions));
  tab.append(head, scoreTiles(r), lists, ...r.markers.map(markerCard), transcriptCard(s));
  return tab;
}

function metricRow(m) {
  const tag = el("span", { className: "verdict " + m.verdict, textContent: m.verdict === "good" ? "Good" : "Work on" });
  return el("div", { className: "beh metric" },
    el("div", { className: "metric-head" }, el("b", { textContent: m.name }), el("span", { textContent: m.value }), tag),
    el("div", { className: "muted", textContent: m.detail }));
}

function analyticsTab(r) {
  const tab = el("div");
  if (!r.analytics) {
    tab.append(el("p", { className: "muted", textContent: "Analytics are available for calls scored from now on." }));
    return tab;
  }
  for (const [group, title] of ANALYTICS_GROUPS) {
    const rows = r.analytics.metrics.filter((m) => m.group === group);
    if (group === "camera" && !rows.length) continue;  // only for calls with the camera on
    const card = el("div", { className: "card", style: "margin-bottom:16px" }, el("h3", { textContent: title }));
    rows.forEach((m) => card.append(metricRow(m)));
    if (group === "delivery" && !rows.length)
      card.append(el("p", { className: "muted", textContent: "Speak your replies with hands-free voice to see your pace." }));
    tab.append(card);
  }
  return tab;
}

function showReport(s) {
  const box = $("report"); box.replaceChildren();
  $("call").classList.add("hidden"); $("pick").classList.add("hidden"); box.classList.remove("hidden");
  const onAgain = () => { box.classList.add("hidden"); $("pick").classList.remove("hidden"); };
  const panes = { coaching: coachingTab(s), analytics: analyticsTab(s.report) };
  const tabs = el("div", { className: "subtabs", role: "tablist" });
  for (const [name, label] of [["coaching", "Coaching"], ["analytics", "Analytics"]]) {
    const b = el("button", { type: "button", role: "tab", textContent: label, id: "report-tab-" + name });
    b.addEventListener("click", () => {
      tabs.querySelectorAll("button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      for (const [k, pane] of Object.entries(panes)) pane.classList.toggle("hidden", k !== name);
    });
    b.setAttribute("aria-selected", String(name === "coaching"));
    tabs.append(b);
  }
  panes.analytics.classList.add("hidden");
  box.append(reportBanner(s, onAgain), tabs, panes.coaching, panes.analytics);
  window.scrollTo(0, 0);
}
