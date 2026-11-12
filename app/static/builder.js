// The Build tab: describe a roleplay or pick a template, edit it, save it (private), practise it.
// The admin can also publish a saved roleplay to everyone. Uses $, el, api, fail, cfg,
// loadConfig, showTab and startCall from the page script.
"use strict";

const MAX_GOALS = 6;
const MAX_OBJECTIONS = 15;
let builderData = { templates: [], personas: [] };

async function loadBuilder() {
  const [templates, personas] = await Promise.all([api("/api/roleplays/templates"), api("/api/personas")]);
  builderData = { templates, personas };
  renderBuilderHome();
}

function field(label, input) { return el("div", {}, el("label", { textContent: label }), input); }
function textInput(id, value, attrs = {}) { return el("input", { type: "text", id, value: value ?? "", ...attrs }); }
function textArea(id, value, rows = 3, attrs = {}) { return el("textarea", { id, rows, value: value ?? "", ...attrs }); }

// Home: describe or template, your roleplays, personas.

function renderBuilderHome() {
  const box = $("builder");
  const describe = textArea("rp-describe", "", 3,
    { placeholder: "e.g. A clinic owner who keeps accounts on paper and is worried her staff can't learn new software" });
  const create = el("button", { className: "primary", id: "rp-create", textContent: "Create with AI" });
  const status = el("span", { className: "muted", id: "rp-create-status" });
  create.addEventListener("click", () => draftFromDescription(describe.value, create, status));
  const chips = el("div", { className: "chips" });
  for (const t of builderData.templates) {
    const chip = el("button", { className: "chip", type: "button", textContent: t.title });
    chip.addEventListener("click", () => { const { template_id, ...body } = t; renderEditor(body, null); });
    chips.append(chip);
  }
  box.replaceChildren(
    el("h2", { textContent: "What's your roleplay about?" }),
    el("p", { className: "lede", textContent: "Describe the customer and the call. Saarthi drafts the persona, context, goals and hidden objections; you review and edit before saving." }),
    el("div", { className: "card", style: "margin-bottom:16px" }, describe,
      el("div", { className: "row" }, create, status),
      el("p", { className: "muted", style: "margin:14px 0 8px", textContent: "Or start with a template:" }), chips),
    roleplayList(), personaCard());
}

async function draftFromDescription(text, button, status) {
  if (text.trim().length < 5) { status.textContent = "Describe it in a few more words."; return; }
  clearError(); button.disabled = true; status.textContent = "Drafting…";
  try { renderEditor(await api("/api/roleplays/draft", { method: "POST", body: JSON.stringify({ description: text }) }), null); }
  catch (err) { fail(err); status.textContent = ""; }
  finally { button.disabled = false; }
}

function roleplayList() {
  const admin = cfg.role === "admin";
  const rows = cfg.scenarios.filter((s) => s.mine || (admin && s.published && !s.built_in));
  const table = el("table", { id: "rp-list" },
    el("tr", {}, ...["Roleplay", "Customer", "Shared", ""].map((h) => el("th", { textContent: h }))));
  if (!rows.length) table.append(el("tr", {}, el("td", { colSpan: 4, className: "muted", textContent: "Nothing saved yet. Describe one above or pick a template." })));
  for (const s of rows) {
    const actions = el("td", { className: "row", style: "margin:0" });
    const action = (label, fn) => { const b = el("button", { className: "ghost", type: "button", textContent: label }); b.addEventListener("click", () => fn().catch(fail)); actions.append(b); };
    action("Practise", async () => { showTab("practice"); await startCall(s.id); });
    action("Edit", async () => renderEditor(await api(`/api/roleplays/${s.id}`), s.id));
    if (admin) action(s.published ? "Unpublish" : "Publish", async () => {
      await api(`/api/roleplays/${s.id}/publish`, { method: "POST", body: JSON.stringify({ published: !s.published }) });
      await loadConfig(); renderBuilderHome();
    });
    action("Delete", async () => {
      if (!confirm(`Delete "${s.title}"? This cannot be undone.`)) return;
      await api(`/api/roleplays/${s.id}`, { method: "DELETE" }); await loadConfig(); renderBuilderHome();
    });
    table.append(el("tr", {}, el("td", { textContent: s.title }), el("td", { textContent: s.customer_name }),
      el("td", { textContent: s.published ? (s.mine ? "Everyone" : "Everyone (team)") : "Only you" }), actions));
  }
  const help = admin ? "Your roleplays are private until you publish them. You also see the team's published ones."
    : "Your roleplays are private: only you can see and practise them.";
  return el("div", { className: "card", style: "margin-bottom:16px" },
    el("h3", { textContent: admin ? "Roleplays you manage" : "Your roleplays" }), el("p", { className: "muted", textContent: help }), table);
}

function personaCard() {
  const chips = el("div", { className: "chips" });
  for (const p of builderData.personas) {
    const chip = el("span", { className: "chip", title: p.background, textContent: `${p.name} · ${p.role}${p.mood ? " · " + p.mood : ""}` });
    if (!p.built_in) {
      const x = el("button", { className: "ghost", type: "button", textContent: "×", title: "Delete persona", style: "padding:0 6px;margin-left:6px;border:0" });
      x.addEventListener("click", async () => {
        try { await api(`/api/personas/${p.id}`, { method: "DELETE" }); await loadBuilder(); } catch (err) { fail(err); }
      });
      chip.append(x);
    }
    chips.append(chip);
  }
  return el("div", { className: "card" }, el("h3", { textContent: "Personas" }),
    el("p", { className: "muted", textContent: "The people you practise with. Pick one in the editor, or save a new one from a roleplay." }), chips);
}

// Editor

function goalRow(goal = { name: "", description: "", weight: 1 }) {
  const weight = el("select", { "aria-label": "Weight" });
  for (let w = 1; w <= 5; w += 1) weight.append(el("option", { value: String(w), textContent: `Weight ${w}`, selected: w === goal.weight }));
  const remove = el("button", { className: "ghost", type: "button", textContent: "Remove" });
  const row = el("div", { className: "goal-row" },
    el("input", { type: "text", className: "goal-name", value: goal.name, placeholder: "Goal, e.g. Book a demo" }),
    el("input", { type: "text", className: "goal-desc", value: goal.description || "", placeholder: "What good looks like" }),
    weight, remove);
  weight.classList.add("goal-weight");
  remove.addEventListener("click", () => row.remove());
  return row;
}

function personaPicker() {
  const pick = el("select", { id: "rp-persona-pick" }, el("option", { value: "", textContent: "Fill from a persona…" }));
  builderData.personas.forEach((p, i) => pick.append(el("option", { value: String(i), textContent: `${p.name} · ${p.role}` })));
  pick.addEventListener("change", () => {
    const p = builderData.personas[Number(pick.value)];
    if (!p) return;
    $("rp-name").value = p.name; $("rp-role").value = p.role || ""; $("rp-mood").value = p.mood || ""; $("rp-persona").value = p.background || "";
  });
  return pick;
}

function renderEditor(body, id) {
  const c = body.customer || {};
  const difficulty = el("select", { id: "rp-difficulty" });
  for (const d of ["Easy", "Medium", "Hard"]) difficulty.append(el("option", { value: d, textContent: d, selected: d === (body.difficulty || "Medium") }));
  const goals = el("div", { id: "rp-goals" }, ...(body.goals || []).map(goalRow));
  const addGoal = el("button", { className: "ghost", type: "button", textContent: "+ Add goal" });
  addGoal.addEventListener("click", () => { if (goals.children.length < MAX_GOALS) goals.append(goalRow()); });
  const save = el("button", { className: "primary", type: "button", id: "rp-save", textContent: "Save" });
  const savePractise = el("button", { className: "ghost", type: "button", id: "rp-save-practise", textContent: "Save and practise" });
  const cancel = el("button", { className: "ghost", type: "button", textContent: "Cancel" });
  save.addEventListener("click", () => saveRoleplay(id, false));
  savePractise.addEventListener("click", () => saveRoleplay(id, true));
  cancel.addEventListener("click", renderBuilderHome);
  const section = (title, help, ...kids) => el("section", { className: "card" }, el("h3", { textContent: title }),
    help ? el("p", { className: "muted", style: "margin:0", textContent: help }) : "", ...kids);
  $("builder").replaceChildren(el("div", { className: "editor" },
    el("h2", { textContent: id ? "Edit roleplay" : "New roleplay" }),
    el("p", { className: "lede", textContent: "Review every section, then save. Only you can see it until the admin publishes it." }),
    section("Description", "What the person practising sees before the call.",
      el("div", { className: "two" }, field("Title", textInput("rp-title", body.title)), field("Difficulty", difficulty)),
      field("Brief for the agent", textArea("rp-brief", body.public_brief, 2))),
    section("Persona", "Who the AI plays.", el("div", { style: "margin-top:10px" }, personaPicker()),
      el("div", { className: "two" }, field("Name", textInput("rp-name", c.name)), field("Role", textInput("rp-role", c.role))),
      el("div", { className: "two" }, field("Temperament", textInput("rp-mood", c.mood, { placeholder: "Skeptical, rushed, friendly…" })),
        el("div", {}, el("label", {}, el("input", { type: "checkbox", id: "rp-save-persona" }), " Save this persona to my library"))),
      field("Background", textArea("rp-persona", c.persona, 2))),
    section("Context", "Directions for the AI customer: their situation, and what moves them.",
      field("Situation", textArea("rp-situation", c.situation, 3)),
      el("div", { className: "two" }, field("Warms up when", textArea("rp-wins", c.wins_if, 2)),
        field("Walks away when", textArea("rp-walks", c.walks_away_if, 2)))),
    section("Goals", `What this roleplay is scored on, up to ${MAX_GOALS}. Higher weight counts more.`,
      el("div", { style: "margin-top:10px" }, goals), addGoal),
    section("Hidden objections", `One per line, up to ${MAX_OBJECTIONS}. The customer raises them only when the conversation reaches them. Never shown to the person practising.`,
      textArea("rp-objections", (c.hidden_objections || []).join("\n"), 4)),
    section("Conversation", "",
      field("The customer's first words", textInput("rp-opening", body.opening_line)),
      field("Time limit (minutes, 2 to 20)", el("input", { type: "number", id: "rp-minutes", min: 2, max: 20, value: body.minutes || 6, style: "max-width:120px" }))),
    el("div", { className: "row" }, save, savePractise, cancel)));
  window.scrollTo(0, 0);
}

function collectRoleplay() {
  const goals = [...document.querySelectorAll("#rp-goals .goal-row")].map((r) => ({
    name: r.querySelector(".goal-name").value.trim(),
    description: r.querySelector(".goal-desc").value.trim(),
    weight: Number(r.querySelector(".goal-weight").value),
  })).filter((g) => g.name);
  return {
    title: $("rp-title").value.trim(), difficulty: $("rp-difficulty").value, public_brief: $("rp-brief").value.trim(),
    customer: {
      name: $("rp-name").value.trim(), role: $("rp-role").value.trim(), mood: $("rp-mood").value.trim(),
      persona: $("rp-persona").value.trim(), situation: $("rp-situation").value.trim(),
      wins_if: $("rp-wins").value.trim(), walks_away_if: $("rp-walks").value.trim(),
      hidden_objections: $("rp-objections").value.split("\n").map((x) => x.trim()).filter(Boolean),
    },
    opening_line: $("rp-opening").value.trim(), minutes: Number($("rp-minutes").value) || 6, goals,
  };
}

async function saveRoleplay(id, practise) {
  clearError();
  const body = collectRoleplay();
  try {
    if ($("rp-save-persona").checked) {
      const c = body.customer;
      await api("/api/personas", { method: "POST", body: JSON.stringify({ name: c.name, role: c.role, mood: c.mood, background: c.persona }) });
    }
    const saved = await api(id ? `/api/roleplays/${id}` : "/api/roleplays",
      { method: id ? "PUT" : "POST", body: JSON.stringify(body) });
    await loadConfig();
    if (practise) { showTab("practice"); await startCall(saved.id); return; }
    await loadBuilder();
  } catch (err) { fail(err); window.scrollTo(0, 0); }
}
