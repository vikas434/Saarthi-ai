// Tutor mode: learn the product facts for a roleplay, answer three check questions, then practise.
// Uses $, el, api, fail, clearError, cfg, showCallsLeft, startCall and SaarthiVoice from the page.
"use strict";

let tutorState = null;  // { scenario, lesson, index, right }

function tutorBox() { return $("tutor"); }
function showTutorOnly() {
  for (const id of ["pick", "call", "report"]) $(id).classList.add("hidden");
  tutorBox().classList.remove("hidden"); window.scrollTo(0, 0);
}
function backToCustomers() { tutorBox().classList.add("hidden"); $("pick").classList.remove("hidden"); window.SaarthiVoice.stopSpeaking(); }

async function startTutor(scenario) {
  clearError(); window.SaarthiVoice.unlockAudio();
  showTutorOnly();
  tutorBox().replaceChildren(el("div", { className: "card" }, el("p", { className: "muted", textContent: "Preparing your lesson…" })));
  let lesson;
  try { lesson = await api("/api/tutor", { method: "POST", body: JSON.stringify({ scenario_id: scenario.id }) }); }
  catch (err) { backToCustomers(); throw err; }
  cfg = { ...cfg, calls_left: Math.max(0, cfg.calls_left - 1) }; showCallsLeft();
  tutorState = { scenario, lesson, index: 0, right: 0 };
  renderLesson();
}

function renderLesson() {
  const { scenario, lesson } = tutorState;
  const read = el("button", { className: "ghost", type: "button", textContent: "🔊 Read aloud" });
  read.addEventListener("click", () => window.SaarthiVoice.say([lesson.intro, ...lesson.points.map((p) => `${p.title}. ${p.explain}`)].join(" ")));
  const ready = el("button", { className: "primary", type: "button", id: "tutor-ready", textContent: "I'm ready for the questions" });
  ready.addEventListener("click", () => { window.SaarthiVoice.stopSpeaking(); renderQuestion(); });
  const back = el("button", { className: "ghost", type: "button", textContent: "Back" });
  back.addEventListener("click", backToCustomers);
  tutorBox().replaceChildren(
    el("h2", { textContent: "Learn first: " + scenario.title }),
    el("p", { className: "lede", textContent: lesson.intro }),
    el("div", { className: "card", style: "margin-bottom:16px" },
      ...lesson.points.map((p) => el("div", { className: "lesson-point" }, el("b", { textContent: p.title }), el("span", { textContent: p.explain })))),
    el("p", { className: "muted", textContent: `Then ${lesson.questions.length} quick questions, the kind ${scenario.customer_name} may ask.` }),
    el("div", { className: "row" }, ready, read, back));
}

function renderQuestion() {
  const { lesson, index } = tutorState;
  const answer = el("textarea", { id: "tutor-answer", rows: 3, placeholder: "Answer as you would on the call" });
  const send = el("button", { className: "primary", type: "button", id: "tutor-send", textContent: "Check my answer" });
  const mic = el("button", { className: "ghost mic", type: "button", textContent: "🎤 Speak", disabled: !window.SaarthiVoice.canListen });
  const result = el("div", { id: "tutor-result" });
  let listening = null;
  mic.addEventListener("click", () => {
    if (listening) { listening.stop(); return; }
    mic.textContent = "■ Done"; mic.classList.add("on");
    listening = window.SaarthiVoice.listen({
      onText: (t) => { answer.value = t; },
      onDone: () => { listening = null; mic.textContent = "🎤 Speak"; mic.classList.remove("on"); },
    });
  });
  send.addEventListener("click", () => checkAnswer(answer, send, mic, result).catch(fail));
  tutorBox().replaceChildren(
    el("h2", { textContent: `Question ${index + 1} of ${lesson.questions.length}` }),
    el("div", { className: "card" }, el("p", { textContent: lesson.questions[index] }), answer,
      el("div", { className: "row" }, send, mic), result));
  answer.focus();
}

async function checkAnswer(answer, send, mic, result) {
  const text = answer.value.trim();
  if (!text) { answer.focus(); return; }
  clearError(); send.disabled = true; mic.disabled = true; answer.disabled = true;
  const { lesson, index } = tutorState;
  const r = await api(`/api/tutor/${lesson.id}/answers`, { method: "POST", body: JSON.stringify({ index, text }) });
  tutorState = { ...tutorState, right: tutorState.right + (r.correct ? 1 : 0) };
  const last = index + 1 >= lesson.questions.length;
  const next = el("button", { className: "primary", type: "button", id: "tutor-next", textContent: last ? "See my result" : "Next question" });
  next.addEventListener("click", () => {
    if (last) finishTutor().catch(fail);
    else { tutorState = { ...tutorState, index: index + 1 }; renderQuestion(); }
  });
  result.replaceChildren(el("div", { className: "answer-result " + (r.correct ? "right" : "wrong") },
    el("b", { textContent: r.correct ? "✓ Right" : "✗ Not quite" }), el("div", { textContent: r.feedback }),
    el("div", { className: "muted", style: "margin-top:6px", textContent: "Model answer: " + r.ideal })),
  el("div", { className: "row" }, next));
}

async function finishTutor() {
  const { scenario, lesson } = tutorState;
  const r = await api(`/api/tutor/${lesson.id}/end`, { method: "POST" });
  const practise = el("button", { className: "primary", type: "button", id: "tutor-practise", textContent: "Start the roleplay" });
  practise.addEventListener("click", () => startCall(scenario.id).catch(fail));
  const again = el("button", { className: "ghost", type: "button", textContent: "Back to customers" });
  again.addEventListener("click", backToCustomers);
  tutorBox().replaceChildren(el("div", { className: "card banner" },
    el("div", {}, el("h2", { textContent: "Quiz complete" }),
      el("p", { className: "big", id: "tutor-score", textContent: `${r.score} / ${r.total} right` }),
      el("p", { textContent: r.message })),
    el("div", { className: "row", style: "margin:0" }, practise, again)));
}
