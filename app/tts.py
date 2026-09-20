"""Text-to-Speech über OpenRouter (Fish Audio) + Kokoro (lokal) + Filler-Cache."""
import asyncio
import logging

import httpx

from . import config, settings

log = logging.getLogger("jarvis.tts")


class TTSError(RuntimeError):
    pass


async def synthesize(text: str) -> bytes:
    """Text -> MP3-Bytes. Provider/Stimme kommen aus den Laufzeit-Einstellungen."""
    text = text.strip()
    if not text:
        raise TTSError("Leerer Text.")

    s = settings.current()
    if s["tts_provider"] == "kokoro":
        return await _synthesize_kokoro(text, url=s["kokoro_url"], voice=s["kokoro_voice"])
    return await _synthesize_openrouter(text, voice=s["openrouter_voice"])


async def _synthesize_openrouter(text: str, voice: str | None = None) -> bytes:
    """Text -> MP3-Bytes via OpenRouter Fish Audio."""
    if not config.OPENROUTER_API_KEY:
        raise TTSError("OPENROUTER_API_KEY ist nicht gesetzt (siehe README).")

    async with httpx.AsyncClient(timeout=config.TTS_TIMEOUT) as client:
        r = await client.post(
            config.TTS_URL,
            headers={
                "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.TTS_MODEL,
                "input": text,
                "voice": voice or config.TTS_VOICE,
                "response_format": "mp3",
            },
        )
    if r.status_code != 200 or r.headers.get("content-type", "").startswith(
        "application/json"
    ):
        raise TTSError(f"TTS fehlgeschlagen (HTTP {r.status_code}): {r.text[:300]}")
    if not r.content:
        raise TTSError("TTS lieferte 0 Bytes.")
    return r.content


async def _synthesize_kokoro(text: str, url: str | None = None, voice: str | None = None) -> bytes:
    """Text -> MP3-Bytes via Kokoro (lokal, englisch).
    Kokoro liefert WAV; wir konvertieren per ffmpeg nach MP3 (Fallback: WAV)."""
    import subprocess

    target = url or config.KOKORO_URL
    chosen = voice or config.KOKORO_VOICE

    async with httpx.AsyncClient(timeout=config.KOKORO_TIMEOUT) as client:
        r = await client.post(
            target,
            headers={"Content-Type": "application/json"},
            json={
                "model": "kokoro",
                "input": text,
                "voice": chosen,
                "response_format": "wav",
            },
        )
    if r.status_code != 200:
        raise TTSError(f"Kokoro TTS fehlgeschlagen (HTTP {r.status_code}): {r.text[:300]}")
    if not r.content:
        raise TTSError("Kokoro TTS lieferte 0 Bytes.")

    # WAV -> MP3 konvertieren via ffmpeg (falls verfügbar), sonst WAV zurückgeben
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", "pipe:0", "-f", "mp3", "-c:a", "libmp3lame", "-b:a", "128k", "pipe:1"],
            input=r.content,
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
        log.warning("ffmpeg rc=%s, nutze WAV-Fallback", result.returncode)
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        log.warning("ffmpeg nicht verfügbar (%s) - liefere WAV", e)

    return r.content


async def available_kokoro_voices() -> list[dict]:
    """Stimmenliste vom Kokoro-Service holen (für das Settings-UI)."""
    url = settings.current()["kokoro_url"]
    base = url.rsplit("/v1/", 1)[0]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/v1/audio/voices")
        r.raise_for_status()
        data = r.json()
        names = data.get("voices") or []
        return [{"id": n, "label": _voice_label(n)} for n in names]
    except Exception as e:
        log.warning("Kokoro-Stimmen nicht abrufbar (%s): %s", base, e)
        return []


def _voice_label(name: str) -> str:
    """af_heart -> 'af · heart (female)' - grobe Einordnung nach Kokoro-Konvention."""
    if "_" not in name:
        return name
    prefix, rest = name.split("_", 1)
    kind = {"af": "US female", "am": "US male", "bf": "UK female", "bm": "UK male"}.get(prefix, prefix)
    return f"{rest} ({kind})"



async def ensure_fillers() -> list[str]:
    """Generiert fehlende Filler-MP3s einmalig und gibt die Dateinamen zurück.

    ponytail: Cache-Key ist der Index, nicht ein Hash des Textes. Wer die
    Phrasenliste aendert, loescht data/fillers einmal von Hand.
    """
    config.FILLER_DIR.mkdir(parents=True, exist_ok=True)
    names = [f"{i:02d}.mp3" for i in range(len(config.FILLER_PHRASES))]
    missing = [
        (i, n) for i, n in enumerate(names) if not (config.FILLER_DIR / n).exists()
    ]
    if not missing:
        return names

    log.info("Generiere %d Filler-Audios ...", len(missing))
    for i, name in missing:
        phrase = config.FILLER_PHRASES[i]
        try:
            data = await synthesize(phrase)
        except TTSError as e:
            log.error("Filler %r fehlgeschlagen: %s", phrase, e)
            continue
        (config.FILLER_DIR / name).write_bytes(data)
        log.info("  %s  %-34s %6d bytes", name, phrase, len(data))
        await asyncio.sleep(0.2)  # der API gegenüber höflich bleiben

    return [n for n in names if (config.FILLER_DIR / n).exists()]


def available_fillers() -> list[str]:
    if not config.FILLER_DIR.exists():
        return []
    return sorted(p.name for p in config.FILLER_DIR.glob("*.mp3") if p.stat().st_size)


if __name__ == "__main__":
    # Setup-Skript: python -m app.tts
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    got = asyncio.run(ensure_fillers())
    print(f"\n{len(got)}/{len(config.FILLER_PHRASES)} Filler vorhanden in {config.FILLER_DIR}")
