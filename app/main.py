"""Jarvis Voice - Sprache rein, Hermes denkt, Jarvis antwortet."""
import asyncio
import logging
import random
import tempfile
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, hermes, settings, tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jarvis")

STATIC = Path(__file__).resolve().parent.parent / "static"

_model = None
_model_lock = asyncio.Lock()

# job_id -> {"task": Task, "user": str, "reply": str|None, "audio": bytes|None, "error": str|None}
# ponytail: In-Memory, letzte 20 Turns. Kein Verlauf über Neustarts (laut Spec kein Muss).
JOBS: OrderedDict[str, dict] = OrderedDict()
MAX_JOBS = 20


async def _get_model():
    """faster-whisper lazy laden - hält den Serverstart schnell."""
    global _model
    async with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            t = time.monotonic()
            log.info("Lade Whisper-Modell %r (%s) ...", config.WHISPER_MODEL, config.WHISPER_COMPUTE)
            _model = await asyncio.to_thread(
                WhisperModel,
                config.WHISPER_MODEL,
                device="cpu",
                compute_type=config.WHISPER_COMPUTE,
            )
            log.info("Whisper geladen in %.1fs", time.monotonic() - t)
    return _model


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.REPLY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        got = await tts.ensure_fillers()
        log.info("Filler-Cache: %d/%d bereit", len(got), len(config.FILLER_PHRASES))
    except Exception as e:  # Server soll auch ohne TTS-Key hochkommen
        log.error("Filler-Generierung fehlgeschlagen: %s", e)
    yield


app = FastAPI(title="Jarvis Voice", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/manifest.json")
async def manifest():
    return RedirectResponse("/static/manifest.json")


@app.get("/api/health")
async def health():
    s = settings.current()
    return {
        "ok": True,
        "whisper_model": config.WHISPER_MODEL,
        "whisper_loaded": _model is not None,
        "tts_provider": s["tts_provider"],
        "tts_voice": s["kokoro_voice"] if s["tts_provider"] == "kokoro" else s["openrouter_voice"],
        "tts_model": config.TTS_MODEL,
        "tts_key_present": bool(config.OPENROUTER_API_KEY),
        "hermes_session": config.HERMES_SESSION,
        "hermes_model": s.get("hermes_model") or "(Standard)",
        "fillers": len(tts.available_fillers()),
    }


# --------------------------------------------------------------------------
# Einstellungen (Laufzeit, persistent in data/settings.json)
# --------------------------------------------------------------------------


class SettingsIn(BaseModel):
    tts_provider: str | None = None
    kokoro_url: str | None = None
    kokoro_voice: str | None = None
    openrouter_model: str | None = None
    openrouter_voice: str | None = None
    hermes_model: str | None = None
    hermes_tools: str | None = None


@app.get("/api/settings")
async def get_settings():
    """Aktuelle Einstellungen plus die Auswahlmöglichkeiten fürs UI."""
    return {
        "settings": settings.current(),
        "options": {
            "providers": [
                {"id": "kokoro", "label": "Kokoro (lokal, Englisch, kostenlos)"},
                {"id": "openrouter", "label": "OpenRouter · Fish Audio"},
            ],
            "kokoro_voices": await tts.available_kokoro_voices(),
            "openrouter_voices": settings.OPENROUTER_VOICES,
            "hermes_models": settings.HERMES_MODELS,
            "tool_modes": settings.TOOL_MODES,
        },
    }


@app.put("/api/settings")
async def put_settings(body: SettingsIn):
    try:
        updated = settings.save(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "settings": updated}


# --------------------------------------------------------------------------
# Turn-Pipeline
# --------------------------------------------------------------------------


async def _run_turn(job: dict, text: str) -> None:
    """Hintergrund: Hermes fragen, Antwort vertonen."""
    try:
        t = time.monotonic()
        reply = await hermes.ask(text)
        log.info("Hermes antwortete nach %.1fs (%d Zeichen)", time.monotonic() - t, len(reply))
        job["reply"] = reply
        job["audio"] = await tts.synthesize(reply)
    except (hermes.HermesError, tts.TTSError) as e:
        log.error("Turn fehlgeschlagen: %s", e)
        job["error"] = str(e)
        # Antworttext ohne Audio ist immer noch besser als nichts.
    except Exception as e:
        log.exception("Unerwarteter Fehler im Turn")
        job["error"] = f"Interner Fehler: {e}"


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile):
    """Audio -> Text. Startet sofort den Hermes-Turn und nennt einen Filler."""
    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "Leere Audio-Datei.")

    suffix = Path(audio.filename or "rec.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(raw)
        tmp = Path(fh.name)

    try:
        model = await _get_model()
        t = time.monotonic()

        def run():
            segments, info = model.transcribe(
                str(tmp), language="en", beam_size=1, vad_filter=True
            )
            return "".join(s.text for s in segments).strip(), info.duration

        text, audio_secs = await asyncio.to_thread(run)
        took = time.monotonic() - t
        log.info("Transkription: %.2fs für %.1fs Audio -> %r", took, audio_secs, text)
    except Exception as e:
        log.exception("Transkription fehlgeschlagen")
        raise HTTPException(500, f"Transkription fehlgeschlagen: {e}")
    finally:
        tmp.unlink(missing_ok=True)

    if not text:
        raise HTTPException(422, "Nichts verstanden - bitte nochmal sprechen.")

    job_id = uuid.uuid4().hex
    job: dict = {"user": text, "reply": None, "audio": None, "error": None}
    job["task"] = asyncio.create_task(_run_turn(job, text))
    JOBS[job_id] = job
    while len(JOBS) > MAX_JOBS:
        JOBS.popitem(last=False)

    fillers = tts.available_fillers()
    return {
        "text": text,
        "job_id": job_id,
        "filler": f"/api/fillers/{random.choice(fillers)}" if fillers else None,
        "transcribe_seconds": round(took, 2),
    }


@app.get("/api/reply/{job_id}")
async def reply(job_id: str, wait: float = 25.0):
    """Long-Poll auf die Hermes-Antwort. `pending` -> Client fragt erneut."""
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unbekannter oder abgelaufener Turn.")

    try:
        await asyncio.wait_for(asyncio.shield(job["task"]), timeout=max(1.0, min(wait, 60.0)))
    except asyncio.TimeoutError:
        return {"status": "pending"}

    if job["error"] and not job["reply"]:
        return {"status": "error", "error": job["error"]}
    return {
        "status": "done",
        "text": job["reply"],
        "audio": f"/api/audio/{job_id}" if job["audio"] else None,
        # Text da, Audio nicht: mitlesen geht, vorlesen nicht.
        "error": job["error"],
    }


@app.get("/api/audio/{job_id}")
async def audio(job_id: str):
    job = JOBS.get(job_id)
    if job is None or not job.get("audio"):
        raise HTTPException(404, "Kein Audio für diesen Turn.")
    return Response(job["audio"], media_type="audio/mpeg")


class SpeakIn(BaseModel):
    text: str


@app.post("/api/speak")
async def speak(body: SpeakIn):
    """Text -> MP3. Eigenständig nutzbar; die Turn-Pipeline ruft tts.synthesize direkt."""
    try:
        return Response(await tts.synthesize(body.text), media_type="audio/mpeg")
    except tts.TTSError as e:
        raise HTTPException(502, str(e))


@app.get("/api/fillers/{name}")
async def filler(name: str):
    # Unterstütze sowohl "0" als auch "00.mp3" etc.
    if name.isdigit() and len(name) == 1:
        name = f"{int(name):02d}.mp3"
    elif not name.endswith(".mp3"):
        name = f"{name}.mp3"
    path = config.FILLER_DIR / Path(name).name  # kein Pfad-Ausbruch
    if not path.is_file():
        raise HTTPException(404, "Filler nicht gefunden.")
    return FileResponse(path, media_type="audio/mpeg")
