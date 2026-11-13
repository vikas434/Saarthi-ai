// Voice for practice calls: a phone ring, the customer's voice, and listening to the agent.
// Uses only the browser (Web Audio, speechSynthesis, Chrome's SpeechRecognition): no keys, no cost.
"use strict";
(() => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const LANG = "en-IN";
  const SILENCE_MS = 1600; // a pause this long after speech ends the agent's turn
  const NO_SPEECH_MS = 15000; // stop listening if nothing is said for this long
  const RING_TONES = 2;

  let audio = null;
  // Call from a click handler: browsers only allow sound after a user gesture.
  function unlockAudio() {
    try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); audio.resume(); } catch { audio = null; }
  }

  function ring() {
    if (!audio) return Promise.resolve();
    const start = audio.currentTime + 0.05;
    for (let i = 0; i < RING_TONES; i += 1) {
      const t = start + i * 1.6;
      const gain = audio.createGain();
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.12, t + 0.03);
      gain.gain.setValueAtTime(0.12, t + 0.9);
      gain.gain.linearRampToValueAtTime(0, t + 1.0);
      gain.connect(audio.destination);
      for (const freq of [440, 480]) {
        const osc = audio.createOscillator();
        osc.frequency.value = freq; osc.connect(gain); osc.start(t); osc.stop(t + 1.0);
      }
    }
    return new Promise((resolve) => setTimeout(resolve, RING_TONES * 1600 + 200));
  }

  // Speak text aloud; resolves when done. Chrome sometimes never fires onend on long text,
  // so a timer based on the length resolves it anyway.
  function say(text) {
    const synth = window.speechSynthesis;
    if (!synth || !text) return Promise.resolve();
    synth.cancel();
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = LANG; u.rate = 1.02;
      const words = text.split(/\s+/).length;
      const guard = setTimeout(resolve, (words / 2.3) * 1000 + 3000);
      const done = () => { clearTimeout(guard); resolve(); };
      u.onend = done; u.onerror = done;
      synth.speak(u);
    });
  }

  function stopSpeaking() { window.speechSynthesis?.cancel(); }

  // Listen for one reply. onText(text) gets the words so far; onDone({text, seconds}) fires once,
  // when the agent pauses, presses stop, or says nothing (text "").
  function listen({ onText, onDone }) {
    if (!Recognition) { onDone({ text: "", seconds: null }); return { stop() {}, cancel() {} }; }
    const rec = new Recognition();
    rec.lang = LANG; rec.interimResults = true; rec.continuous = true;
    let text = "", firstSpeech = null, lastSpeech = null, finished = false, cancelled = false;
    let silenceTimer = null;
    const noSpeechTimer = setTimeout(() => stop(), NO_SPEECH_MS);
    function finish() {
      if (finished) return;
      finished = true; clearTimeout(silenceTimer); clearTimeout(noSpeechTimer);
      if (cancelled) return;
      const seconds = firstSpeech && lastSpeech ? Math.round((lastSpeech - firstSpeech) / 100) / 10 : null;
      onDone({ text: text.trim(), seconds: text.trim() ? Math.max(seconds || 0, 0.5) : null });
    }
    function stop() { try { rec.stop(); } catch { finish(); } }
    rec.onresult = (e) => {
      const now = performance.now();
      firstSpeech = firstSpeech ?? now; lastSpeech = now;
      text = Array.from(e.results).map((r) => r[0].transcript).join(" ");
      onText(text);
      clearTimeout(noSpeechTimer); clearTimeout(silenceTimer);
      silenceTimer = setTimeout(stop, SILENCE_MS);
    };
    rec.onend = finish;
    rec.onerror = finish;
    try { rec.start(); } catch { finish(); }
    return { stop, cancel() { cancelled = true; stop(); } };
  }

  // Human voice: play MP3 bytes from the server (ElevenLabs).
  let player = null;
  // Resolves true when the line was played, false when there was no human voice to play (no
  // audio from the server, an error, or playback blocked). It never falls back to a robotic voice.
  async function sayHuman(fetchAudio) {
    try {
      const res = await fetchAudio();
      if (res.status !== 200) return false;
      const url = URL.createObjectURL(await res.blob());
      stopSpeaking();
      player = new Audio(url);
      return await new Promise((resolve) => {
        const done = () => { URL.revokeObjectURL(url); resolve(true); };
        player.onended = done; player.onerror = done; player.onpause = done;
        player.play().catch(() => { URL.revokeObjectURL(url); resolve(false); });
      });
    } catch { return false; }
  }
  function stopAll() { window.speechSynthesis?.cancel(); if (player) { player.pause(); player = null; } }

  window.SaarthiVoice = {
    canListen: Boolean(Recognition),
    canSpeak: Boolean(window.speechSynthesis),
    unlockAudio, ring, say, sayHuman, stopSpeaking: stopAll, listen,
  };
})();
