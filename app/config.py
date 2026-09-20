"""Alle Stellschrauben an einem Ort, per Environment überschreibbar."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
FILLER_DIR = DATA_DIR / "fillers"
REPLY_DIR = DATA_DIR / "replies"

# --- TTS Provider Selection ---
# "openrouter" (Fish Audio via OpenRouter) or "kokoro" (local Kokoro server)
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "openrouter")

# --- TTS: OpenRouter (Fish Audio) ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
TTS_URL = "https://openrouter.ai/api/v1/audio/speech"
# "fish-audio/s2.1-pro-free" (ohne Suffix) liefert 404 "No endpoints found".
# Der richtige OpenRouter-Slug fürs Gratis-Tier braucht ":free" als Suffix,
# nicht "-free" im Namen — verifiziert 2026-09-20 (200 OK, gültige MP3).
TTS_MODEL = os.environ.get("TTS_MODEL", "fish-audio/s2.1-pro-free:free")
# "Brian British" - ruhiger, tiefer britischer Männer-Voice. Auswahl siehe README.
TTS_VOICE = os.environ.get("TTS_VOICE", "65c0b8155c464a648161af8877404f11")
TTS_TIMEOUT = float(os.environ.get("TTS_TIMEOUT", "120"))

# --- TTS: Kokoro (local server) ---
# ACHTUNG: Port 8881 ist die DEUTSCHE Kokoro-Instanz (nur Voice "martin") —
# die nutzt Hermes selbst. Für Englisch läuft auf 8882 eine zweite Instanz mit
# dem offiziellen englischen Kokoro-v1.0-Modell (54 Stimmen, u.a. af_heart).
KOKORO_URL = os.environ.get(
    "KOKORO_URL", "http://host.docker.internal:8882/v1/audio/speech"
)
# af_heart = US-englische Frauenstimme (verifiziert: Whisper erkennt en, prob 1.00).
# Weitere: af_bella, af_nicole, af_sky, bf_emma (UK), am_michael, bm_george (UK male)
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
KOKORO_TIMEOUT = float(os.environ.get("KOKORO_TIMEOUT", "60"))

# --- STT (faster-whisper) ---
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")

# --- Hermes ---
# Direkter venv-Interpreter statt des hermes-Wrappers: ein Mount weniger und
# kein Verlass auf bash/PATH im Container. Siehe README.
# Wichtig: ~/.hermes wird im Container auf denselben absoluten Pfad wie auf dem
# Host gemountet, weil venv/bin/python ein ABSOLUTER Symlink auf den
# uv-CPython-3.11 ist und pyvenv.cfg denselben Pfad hart referenziert.
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
HERMES_PYTHON = os.environ.get(
    "HERMES_PYTHON", str(_HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python")
)
HERMES_SCRIPT = os.environ.get(
    "HERMES_SCRIPT", str(_HERMES_HOME / "hermes-agent" / "hermes")
)
HERMES_SESSION = os.environ.get("HERMES_SESSION", "jarvis-voice")
# Konstantes Arbeitsverzeichnis: --continue findet die Session nur im Workspace,
# in dem sie angelegt wurde.
HERMES_CWD = os.environ.get("HERMES_CWD", str(Path.home()))
HERMES_TIMEOUT = float(os.environ.get("HERMES_TIMEOUT", "300"))

# Hermes antwortet Bennet sonst auf Deutsch und in Fließtext mit Markdown.
# Beides geht hier nicht: die Stimme kann nur Englisch, und alles wird
# vorgelesen - eine Bildschirm-Antwort von 2 Minuten ist als Audio unbrauchbar.
VOICE_PREAMBLE = os.environ.get(
    "VOICE_PREAMBLE",
    "You are answering over a voice call and your reply will be read aloud by "
    "a text-to-speech voice. Rules for this reply, no exceptions:\n"
    "- Answer in ENGLISH, even if the question or your notes are in German.\n"
    "- Keep it to 1-3 short sentences. Lead with the answer, drop the preamble.\n"
    "- Speak plainly: no markdown, no bullet points, no headings, no code "
    "blocks, no URLs, no emoji. Write numbers and units as you would say them.\n"
    "- If the full answer is too long to speak, give the short version and "
    "offer to go deeper.\n"
    "Do your normal work (tools, memory, files) as usual - only the final "
    "reply is constrained.\n\n"
    "The spoken question was:\n",
)

FILLER_PHRASES = [
    "Okay, got it.",
    "I'm on it.",
    "Mhmm, let me have a look.",
    "Sure, one moment.",
    "Alright, working on that.",
    "Give me a second.",
    "Right, checking that now.",
    "Understood. Looking into it.",
    "Of course. Just a moment.",
    "Let me pull that up for you.",
]