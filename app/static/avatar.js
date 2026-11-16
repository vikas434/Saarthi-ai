// The video customer: a real-time Anam avatar that says the customer's lines on a call.
// TalkWise decides every line; the avatar only speaks it. The agent's microphone is never sent to
// Anam (disableInputAudio). Anything going wrong returns false, and the page uses voice only.
"use strict";
(() => {
  const SDK_URL = (version) => `https://esm.sh/@anam-ai/js-sdk@${version}`;
  const CONNECT_MS = 15000;      // give up on video if it isn't playing by then
  const START_TALK_MS = 6000;    // the avatar must start speaking within this long
  const QUIET_MS = 900;          // this much silence after speech means the line is done
  const LOUD = 0.02;             // RMS level that counts as speech
  const POLL_MS = 100;

  let client = null, meter = null, audioCtx = null, onClosed = null, active = false;

  function videoEl() { return document.getElementById("avatar-video"); }

  function timeout(ms, what) {
    return new Promise((_, reject) => setTimeout(() => reject(new Error(what + " timed out")), ms));
  }

  // Loudness of the avatar's own audio track, to tell when a line has really finished.
  function startMeter(stream) {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      audioCtx.resume();
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      audioCtx.createMediaStreamSource(stream).connect(analyser);  // analysis only, not played twice
      const buf = new Float32Array(analyser.fftSize);
      meter = () => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += v * v;
        return Math.sqrt(sum / buf.length);
      };
    } catch { meter = null; }
  }

  async function start({ sessionId, sdk, headers, onClose }) {
    stop();
    onClosed = onClose;
    try {
      const res = await fetch(`/api/sessions/${sessionId}/avatar`, { method: "POST", headers });
      if (res.status !== 200) return false;
      const { session_token: token } = await res.json();
      const { createClient, AnamEvent } = await import(SDK_URL(sdk));
      client = createClient(token, { disableInputAudio: true });
      client.addListener(AnamEvent.CONNECTION_CLOSED, () => {
        const wasActive = active; active = false; client = null; meter = null;
        if (wasActive && onClosed) onClosed();
      });
      await Promise.race([client.streamToVideoElement("avatar-video"), timeout(CONNECT_MS, "video")]);
      const video = videoEl();
      video.muted = false;
      await video.play().catch(() => {});
      if (video.srcObject) startMeter(video.srcObject);
      active = true;
      return true;
    } catch (err) {
      console.warn("Video customer unavailable; continuing with voice.", err?.message || err);
      stop();
      return false;
    }
  }

  // Say one line; resolves true when the avatar has finished it, false if it couldn't speak.
  function say(text) {
    if (!active || !client || !text) return Promise.resolve(false);
    const words = text.split(/\s+/).length;
    const longest = (words / 2.2) * 1000 + 5000;
    return new Promise((resolve) => {
      const began = performance.now();
      let heard = false, lastLoud = 0, timer = null;
      const finish = (ok) => { clearInterval(timer); resolve(ok); };
      timer = setInterval(() => {
        const now = performance.now();
        if (!active) { finish(heard); return; }
        if (meter) {
          if (meter() > LOUD) { heard = true; lastLoud = now; }
          if (heard && now - lastLoud > QUIET_MS) { finish(true); return; }
          if (!heard && now - began > START_TALK_MS) { finish(false); return; }
        }
        if (now - began > longest) finish(heard || !meter);
      }, POLL_MS);
      client.talk(text).catch(() => finish(false));
    });
  }

  function stop() {
    active = false; meter = null;
    const c = client; client = null;
    if (c) c.stopStreaming().catch(() => {});
    const video = videoEl();
    if (video) video.srcObject = null;
  }

  window.SaarthiAvatar = { start, say, stop, get active() { return active; } };
})();
