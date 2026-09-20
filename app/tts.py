"""Text-to-Speech über OpenRouter (Fish Audio) + Kokoro (lokal) + Filler-Cache."""
import asyncio
import logging

import httpx

from . import config

log = logging.getLogger("jarvis.tts")


class TTSError(RuntimeError):
    pass


async def synthesize(text: str) -> bytes:
    """Text -> MP3-Bytes. Wählt Provider basierend auf TTS_PROVIDER."""
    text = text.strip()
    if not text:
        raise TTSError("Leerer Text.")

    if config.TTS_PROVIDER == "kokoro":
        return await _synthesize_kokoro(text)
    else:
        return await _synthesize_openrouter(text)


async def _synthesize_openrouter(text: str) -> bytes:
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
                "voice": config.TTS_VOICE,
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


async def _synthesize_kokoro(text: str) -> bytes:
    """Text -> MP3-Bytes via lokaler Kokoro-Server (OpenAI-kompatibel).
    Kokoro gibt WAV zurück, wir konvertieren zu MP3 via ffmpeg falls verfügbar,
    sonst geben wir WAV zurück (Frontend muss beide Formate können)."""
    import subprocess

    async with httpx.AsyncClient(timeout=config.KOKORO_TIMEOUT) as client:
        r = await client.post(
            config.KOKORO_URL,
            headers={"Content-Type": "application/json"},
            json={
                "model": "kokoro",
                "input": text,
                "voice": config.KOKORO_VOICE,
                "response_format": "wav",  # Kokoro liefert WAV, konvertieren wir
            },
        )
    if r.status_code != 200:
        raise TTSError(f"Kokoro TTS fehlgeschlagen (HTTP {r.status_code}): {r.text[:300]}")
    if not r.content:
        raise TTSError("Kokoro TTS lieferte 0 Bytes.")

    # WAV -> MP3 konvertieren via ffmpeg (falls verfügbar), sonst WAV zurückgeben
    log.info("Kokoro TTS: WAV empfangen (%d bytes), konvertiere zu MP3...", len(r.content))
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", "pipe:0", "-f", "mp3", "-c:a", "libmp3lame", "-b:a", "128k", "pipe:1"],
            input=r.content,
            capture_output=True,
            timeout=30,
        )
        log.info("ffmpeg returncode: %d, stdout: %d bytes, stderr: %s", 
                 result.returncode, len(result.stdout), result.stderr[:200] if result.stderr else "none")
        if result.returncode == 0 and result.stdout:
            log.info("ffmpeg konvertierung erfolgreich: %d bytes MP3", len(result.stdout))
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        log.warning("ffmpeg konvertierung fehlgeschlagen: %s", e)
        pass  # ffmpeg nicht verfügbar oder Fehler

    # Fallback: WAV zurückgeben (Frontend muss beide Formate können)
    log.warning("Fallback: WAV wird zurückgegeben (Frontend muss WAV unterstützen)")
    return r.content


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
