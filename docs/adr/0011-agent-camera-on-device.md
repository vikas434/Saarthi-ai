# 0011: The agent's camera, analysed on the device

- Status: accepted
- Date: 2026-11-13

## Context
The owner wants practice calls to feel like a real video call: the agent turns on their camera and gets feedback on how they come across (eye contact, smiling, looking tense, staying in view), as Yoodli does. Video of the agent is sensitive, and the enterprise goal is that no data leaves the company.

## Decision
- "My camera" is opt-in on the Practice screen and remembered in the browser. During a call the agent sees a mirrored self-view; with the video customer on, it sits in the corner of the customer's video.
- Face tracking runs in the browser with MediaPipe Face Landmarker (`@mediapipe/tasks-vision` 1.1.1 from jsDelivr; the model file from Google's model storage). About 8 frames a second are read for:
  - face in frame;
  - eye contact: head turned less than 22° and tilted less than 20°, and the eyes not looking hard away; reading the screen counts as eye contact;
  - smiling (mouth-smile blendshapes);
  - a tense expression (brow-down blendshapes).
- **No image or video leaves the device.** Each reply sends only five numbers with the turn (`frames`, `face_pct`, `eye_contact_pct`, `smile_pct`, `tense_pct`). They are validated and stored in `turns.camera` (migration 0009); any other field is dropped.
- The scorecard's Analytics tab gets an "On camera" section, weighted by frames: eye contact (and the reply where the agent looked away most), smiling, tense expression, and face in frame. It is shown only for calls with the camera on.
- `Permissions-Policy` allows the camera for this site only. The CSP adds jsDelivr (script and WebAssembly, with `'wasm-unsafe-eval'`) and Google's model storage.

## Consequences
- No new cost. Tracking uses some CPU or GPU on the agent's laptop.
- The script, WebAssembly and model come from public CDNs. For an enterprise deployment, serve them from our own origin (about 13 MB of WebAssembly and 4 MB of model).
- Eye contact is approximate: the camera usually sits above the screen, so looking at the screen counts as eye contact.
- The AI customer does not react to the agent's face. That could be a later step.
