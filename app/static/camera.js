// The agent's own camera on a call: a mirrored self-view, and face tracking that runs entirely in
// this browser (MediaPipe Face Landmarker). No image or video ever leaves the device: each reply
// sends only percentages (face in frame, eye contact, smiling, tense expression).
"use strict";
(() => {
  const VERSION = "1.1.1";
  const BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION}`;
  const MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
  const FRAME_MS = 120;          // about 8 checks a second is plenty and keeps the laptop cool
  const MAX_YAW = 22, MAX_PITCH = 20;  // degrees: still facing the screen
  const GAZE_AWAY = 0.55;        // eyes turned hard left, right or up
  const LOOK_DOWN = 0.75;        // reading the screen is fine; staring at the desk is not
  const SMILE = 0.35, TENSE = 0.45;

  let stream = null, landmarker = null, timer = null, onLive = null;
  let tally = null;

  const fresh = () => ({ frames: 0, face: 0, eye: 0, smile: 0, tense: 0 });

  async function loadLandmarker() {
    if (landmarker) return landmarker;
    const { FilesetResolver, FaceLandmarker } = await import(`${BASE}/vision_bundle.mjs`);
    const files = await FilesetResolver.forVisionTasks(`${BASE}/wasm`);
    const options = (delegate) => ({
      baseOptions: { modelAssetPath: MODEL, delegate }, runningMode: "VIDEO", numFaces: 1,
      outputFaceBlendshapes: true, outputFacialTransformationMatrixes: true,
    });
    try { landmarker = await FaceLandmarker.createFromOptions(files, options("GPU")); }
    catch { landmarker = await FaceLandmarker.createFromOptions(files, options("CPU")); }
    return landmarker;
  }

  // Head turn from the face's transformation matrix (column-major 4x4), in degrees.
  function headAngles(matrix) {
    const d = matrix?.data;
    if (!d || d.length < 11) return { yaw: 0, pitch: 0 };
    const deg = 180 / Math.PI;
    return { yaw: Math.asin(Math.max(-1, Math.min(1, -d[2]))) * deg, pitch: Math.atan2(d[6], d[10]) * deg };
  }

  function read(result) {
    const face = Boolean(result?.faceLandmarks?.length);
    if (!face) return { face: false, eye: false, smile: false, tense: false };
    const scores = {};
    for (const c of result.faceBlendshapes?.[0]?.categories || []) scores[c.categoryName] = c.score;
    const s = (name) => scores[name] || 0;
    const { yaw, pitch } = headAngles(result.facialTransformationMatrixes?.[0]);
    const away = Math.max(s("eyeLookOutLeft"), s("eyeLookOutRight"), s("eyeLookInLeft"), s("eyeLookInRight"),
      s("eyeLookUpLeft"), s("eyeLookUpRight"));
    const down = Math.min(s("eyeLookDownLeft"), s("eyeLookDownRight"));
    const eye = Math.abs(yaw) < MAX_YAW && Math.abs(pitch) < MAX_PITCH && away < GAZE_AWAY && down < LOOK_DOWN;
    return {
      face, eye,
      smile: (s("mouthSmileLeft") + s("mouthSmileRight")) / 2 > SMILE,
      tense: (s("browDownLeft") + s("browDownRight")) / 2 > TENSE,
    };
  }

  function tick(video) {
    if (!stream) return;
    if (video.readyState >= 2 && landmarker) {
      try {
        const seen = read(landmarker.detectForVideo(video, performance.now()));
        tally.frames += 1;
        for (const k of ["face", "eye", "smile", "tense"]) if (seen[k]) tally[k] += 1;
        onLive?.(seen);
      } catch { /* a dropped frame is not worth stopping for */ }
    }
    timer = setTimeout(() => tick(video), FRAME_MS);
  }

  // Turn the camera on into `video`; resolves to "on", "blocked" (no permission) or "failed".
  async function start(video, live) {
    stop();
    onLive = live;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: "user" }, audio: false });
    } catch (err) {
      stream = null;
      return err?.name === "NotAllowedError" ? "blocked" : "failed";
    }
    video.srcObject = stream;
    await video.play().catch(() => {});
    tally = fresh();
    try { await loadLandmarker(); } catch (err) {
      console.warn("Face tracking unavailable; the camera stays on without analytics.", err?.message || err);
    }
    tick(video);
    return "on";
  }

  // The numbers since the last call to take(), then start counting afresh.
  function take() {
    if (!tally || !tally.frames || !landmarker) { tally = fresh(); return null; }
    const pct = (n) => Math.round((1000 * n) / tally.frames) / 10;
    const out = { frames: tally.frames, face_pct: pct(tally.face), eye_contact_pct: pct(tally.eye),
      smile_pct: pct(tally.smile), tense_pct: pct(tally.tense) };
    tally = fresh();
    return out;
  }

  function stop() {
    clearTimeout(timer); timer = null; onLive = null;
    if (stream) for (const track of stream.getTracks()) track.stop();
    stream = null; tally = null;
  }

  window.SaarthiCamera = {
    supported: Boolean(navigator.mediaDevices?.getUserMedia),
    start, take, stop, get on() { return Boolean(stream); },
  };
})();
