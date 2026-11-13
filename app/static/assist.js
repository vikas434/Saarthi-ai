// Live coach assist: the "Next move" card in the coach panel. It asks the server for the agent's
// next move as soon as the customer's reply arrives, so it is ready while the customer speaks.
// The sample line stays hidden until the agent asks for it, so they think first. A failed hint
// just hides the card: it must never get in the way of the call.
"use strict";
(() => {
  const STAGES = { opening: "Opening", discovery: "Discovery", value: "Value", objection: "Objection", close: "Close" };
  let ticket = 0;  // only the latest request may fill the card

  const $ = (id) => document.getElementById(id);

  function hide() {
    ticket += 1;
    $("assist")?.classList.add("hidden");
  }

  function fill(move) {
    $("assist-stage").textContent = STAGES[move.stage] || "";
    $("assist-move").textContent = move.move;
    $("assist-avoid").textContent = move.avoid ? "Avoid: " + move.avoid : "";
    $("assist-avoid").classList.toggle("hidden", !move.avoid);
    $("assist-line").textContent = move.line || "";
    $("assist-line").classList.add("hidden");
    $("assist-show").classList.toggle("hidden", !move.line);
    $("assist").classList.remove("loading");
  }

  // fetchMove: () => Promise of {stage, move, avoid, line}.
  async function show(fetchMove) {
    const mine = ++ticket;
    const card = $("assist");
    if (!card) return;
    card.classList.remove("hidden"); card.classList.add("loading");
    $("assist-stage").textContent = "";
    $("assist-move").textContent = "Working out your next move…";
    for (const id of ["assist-avoid", "assist-line", "assist-show"]) $(id).classList.add("hidden");
    try {
      const move = await fetchMove();
      if (mine === ticket && move?.move) fill(move); else if (mine === ticket) hide();
    } catch (err) {
      if (mine === ticket) hide();
      console.warn("Next move unavailable.", err?.message || err);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("assist-show")?.addEventListener("click", () => {
      $("assist-line").classList.remove("hidden");
      $("assist-show").classList.add("hidden");
    });
  });

  window.SaarthiAssist = { show, hide };
})();
