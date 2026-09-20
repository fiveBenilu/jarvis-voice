/* Jarvis Voice - Push-to-Talk (Tap to start / tap to stop).
 *
 * Warum Toggle statt "gedrückt halten": auf iOS Safari kollidiert ein langer
 * Druck mit Text-Selektion, Callout-Menü und Scroll-Gesten; ein sauberes
 * pointerup kommt dort nicht zuverlässig an. Tap/Tap ist auf allen Geräten
 * identisch und verliert keine Aufnahme.
 */
"use strict";

const micBtn = document.getElementById("mic");
const micLabel = document.getElementById("mic-label");
const statusEl = document.getElementById("status");
const transcriptEl = document.getElementById("transcript");
const hintEl = document.getElementById("hint");
const errorEl = document.getElementById("error");

// Ein einziges Audio-Element für alles: einmal per Nutzergeste entsperrt,
// bleibt es entsperrt. Neue Sounds nur über .src nachladen - sonst blockt
// iOS die Wiedergabe, die erst nach dem await des Uploads passiert.
const player = new Audio();
player.preload = "auto";
let unlocked = false;

const SILENCE =
  "data:audio/mpeg;base64,//uQxAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAACcQCA" +
  "gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgID/////////////////////////" +
  "//////////////////////8AAAA5TEFNRTMuOTlyAc0AAAAAAAAAABSAJAJAQgAAgAAAAnGM" +
  "PAAAAAAAAAAAAAAAAAAAAAA=";

function unlockAudio() {
  if (unlocked) return;
  unlocked = true;
  player.src = SILENCE;
  player.play().catch(() => {}); // stiller Fehlschlag ist ok, wir versuchen es trotzdem
}

let state = "idle";
const LABELS = {
  idle: "Idle",
  recording: "Recording",
  transcribing: "Transcribing",
  thinking: "Thinking",
  speaking: "Speaking",
};

function setState(next) {
  state = next;
  statusEl.textContent = LABELS[next] || next;
  statusEl.dataset.state = next;
  micBtn.dataset.state =
    next === "recording" ? "recording" : next === "idle" ? "idle" : "busy";
  micBtn.disabled = next !== "idle" && next !== "recording";
  micBtn.setAttribute(
    "aria-label",
    next === "recording" ? "Stop recording" : "Start recording"
  );
  micLabel.textContent =
    next === "recording" ? "Tap to send" : next === "idle" ? "Tap to speak" : LABELS[next];
}

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.hidden = false;
}
function clearError() {
  errorEl.hidden = true;
}

function addMessage(who, text, pending) {
  if (hintEl) hintEl.remove();
  const el = document.createElement("div");
  el.className = "msg " + who + (pending ? " pending" : "");
  el.textContent = text;
  if (pending) el.classList.add("dots");
  transcriptEl.append(el);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
  return el;
}

/** Spielt eine URL zu Ende ab. Löst auch bei Fehlern auf - ein stummer
 *  Filler darf den echten Antwort-Turn nicht blockieren. */
function play(url) {
  return new Promise((resolve) => {
    if (!url) return resolve();
    const done = () => {
      player.removeEventListener("ended", done);
      player.removeEventListener("error", done);
      resolve();
    };
    player.addEventListener("ended", done);
    player.addEventListener("error", done);
    player.src = url;
    player.play().catch(done);
  });
}

// --- Aufnahme ---------------------------------------------------------------

let recorder = null;
let chunks = [];
let stream = null;

function pickMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4", // Safari / iOS
    "audio/ogg;codecs=opus",
  ];
  return candidates.find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    showError("This browser cannot record audio. Use a recent Safari or Chrome over HTTPS.");
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (e) {
    showError(
      e && e.name === "NotAllowedError"
        ? "Microphone permission denied. Allow microphone access in your browser settings and reload."
        : "Could not access the microphone: " + (e?.message || e)
    );
    return;
  }

  clearError();
  chunks = [];
  const mimeType = pickMimeType();
  recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.start();
  setState("recording");
}

function stopRecording() {
  return new Promise((resolve) => {
    if (!recorder || recorder.state === "inactive") return resolve(null);
    recorder.onstop = () => {
      stream?.getTracks().forEach((t) => t.stop());
      stream = null;
      resolve(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
    };
    recorder.stop();
  });
}

// --- Turn ------------------------------------------------------------------

async function postAudio(blob) {
  const ext = (blob.type || "").includes("mp4") ? "mp4" : (blob.type || "").includes("ogg") ? "ogg" : "webm";
  const fd = new FormData();
  fd.append("audio", blob, "recording." + ext);
  const r = await fetch("/api/transcribe", { method: "POST", body: fd });
  if (!r.ok) throw new Error(await readError(r));
  return r.json();
}

async function readError(r) {
  try {
    const j = await r.json();
    return j.detail || j.error || `Server error (HTTP ${r.status})`;
  } catch {
    return `Server error (HTTP ${r.status})`;
  }
}

/** Long-Poll bis Hermes fertig ist. */
async function waitForReply(jobId) {
  for (;;) {
    let r;
    try {
      r = await fetch(`/api/reply/${jobId}?wait=25`);
    } catch {
      throw new Error("Lost connection to the server while waiting for Hermes.");
    }
    if (!r.ok) throw new Error(await readError(r));
    const data = await r.json();
    if (data.status === "pending") continue;
    if (data.status === "error") throw new Error(data.error);
    return data;
  }
}

async function runTurn(blob) {
  setState("transcribing");
  const { text, job_id, filler } = await postAudio(blob);
  addMessage("user", text);

  setState("thinking");
  const placeholder = addMessage("bot", "Thinking", true);

  // Filler sofort anspielen, Hermes läuft parallel weiter.
  const fillerDone = play(filler);

  let reply;
  try {
    reply = await waitForReply(job_id);
  } finally {
    // Filler immer sauber auslaufen lassen, nie abschneiden.
    await fillerDone;
  }

  placeholder.classList.remove("pending", "dots");
  placeholder.textContent = reply.text;
  transcriptEl.scrollTop = transcriptEl.scrollHeight;

  if (reply.audio) {
    setState("speaking");
    await play(reply.audio);
  } else if (reply.error) {
    showError("Answer received, but speech synthesis failed: " + reply.error);
  }
}

micBtn.addEventListener("click", async () => {
  unlockAudio(); // muss in der Geste passieren, sonst blockt iOS spätere play()-Aufrufe

  if (state === "idle") {
    await startRecording();
    return;
  }
  if (state !== "recording") return;

  const blob = await stopRecording();
  if (!blob || blob.size < 1200) {
    setState("idle");
    showError("That recording was too short. Hold on a moment longer before tapping again.");
    return;
  }

  try {
    await runTurn(blob);
    clearError();
  } catch (e) {
    showError(e?.message || String(e));
    document.querySelectorAll(".msg.bot.pending").forEach((el) => el.remove());
  } finally {
    setState("idle");
  }
});

setState("idle");
