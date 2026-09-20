"""Laufzeit-Einstellungen, in data/settings.json persistiert.

Die Werte aus `config.py` (bzw. der .env) sind nur die Startwerte: existiert
die JSON-Datei, gewinnt sie. Aenderungen wirken sofort beim naechsten Aufruf,
ohne Container-Neustart.
"""
import json
import logging
import threading
from pathlib import Path

from . import config

log = logging.getLogger("jarvis.settings")

PATH = config.DATA_DIR / "settings.json"
_lock = threading.Lock()

# Erlaubte Werte - alles andere wird beim Speichern abgelehnt (422 im API-Layer).
PROVIDERS = ("kokoro", "openrouter")

# OpenRouter/Fish-Audio-Stimmen, die wir anbieten (IDs aus dem README/Env).
OPENROUTER_VOICES = [
    {"id": "65c0b8155c464a648161af8877404f11", "label": "Brian British (male)"},
    {"id": "30c0f62e3e6d45d88387d1b8f84e1685", "label": "Liam - Calm British (male)"},
    {"id": "72324f5951924b2eb27faaf5630153b4", "label": "David - Storyteller (male)"},
]

# Hermes-Modelle, die wir anbieten. "-m/--model" wird pro Aufruf durchgereicht.
HERMES_MODELS = [
    {"id": "", "label": "Standard (config.yaml)"},
    {"id": "anthropic/claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
    {"id": "anthropic/claude-opus-4-6", "label": "Claude Opus 4.6"},
    {"id": "deepseek/deepseek-v4.1-flash", "label": "DeepSeek V4.1 Flash (schnell)"},
]


def defaults() -> dict:
    return {
        "tts_provider": config.TTS_PROVIDER,
        "kokoro_url": config.KOKORO_URL,
        "kokoro_voice": config.KOKORO_VOICE,
        "openrouter_model": config.TTS_MODEL,
        "openrouter_voice": config.TTS_VOICE,
        "hermes_model": "",
    }


_current: dict | None = None
_mtime: float | None = None


def current() -> dict:
    """Aktuelle Einstellungen; liest die Datei neu, wenn sie sich geaendert hat."""
    global _current, _mtime
    with _lock:
        if PATH.exists():
            mtime = PATH.stat().st_mtime
            if _current is None or _mtime != mtime:
                try:
                    data = json.loads(PATH.read_text())
                    merged = defaults()
                    merged.update({k: v for k, v in data.items() if k in merged})
                    _current, _mtime = merged, mtime
                except (json.JSONDecodeError, OSError) as e:
                    log.error("settings.json unlesbar (%s) - nutze Defaults", e)
                    _current, _mtime = defaults(), mtime
        if _current is None:
            _current = defaults()
        return dict(_current)


def save(patch: dict) -> dict:
    """Nur bekannte Schluessel uebernehmen, validieren, persistieren."""
    data = current()
    for key in defaults():
        if key not in patch or patch[key] is None:
            continue
        value = patch[key]
        if not isinstance(value, str):
            raise ValueError(f"{key} muss ein String sein.")
        value = value.strip()
        if key == "tts_provider" and value not in PROVIDERS:
            raise ValueError(f"Unbekannter TTS-Provider: {value!r} (erlaubt: {', '.join(PROVIDERS)})")
        data[key] = value

    with _lock:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.replace(PATH)  # atomar
        global _current, _mtime
        _current, _mtime = dict(data), PATH.stat().st_mtime
    log.info("Einstellungen gespeichert: %s", data)
    return dict(data)
