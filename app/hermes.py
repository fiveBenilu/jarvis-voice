"""Bridge zur persistenten Hermes-Session.

Jeder Turn ist ein eigener Prozess, aber immer dieselbe benannte Session
(`--continue <name> --create-if-missing`) im selben Arbeitsverzeichnis --
damit bleibt die Historie erhalten. Verifiziert: ein zweiter Prozess erinnert
sich an das, was dem ersten gesagt wurde.
"""
import asyncio
import logging
import os

from . import config, settings

log = logging.getLogger("jarvis.hermes")


class HermesError(RuntimeError):
    pass


def _build_cmd() -> list[str]:
    cmd = [
        config.HERMES_PYTHON,
        config.HERMES_SCRIPT,
        "chat",
        "--continue",
        config.HERMES_SESSION,
        "--create-if-missing",
    ]
    # Modell pro Aufruf umstellbar (verifiziert: `hermes chat` kennt -m/--model).
    model = settings.current().get("hermes_model") or ""
    if model:
        cmd += ["--model", model]
    cmd += [
        "-Q",  # nur die finale Antwort auf stdout, kein Banner/Spinner
        "--query-file",
        "-",  # Query über stdin: nichts wird von der Shell interpretiert
    ]
    return cmd


async def ask(text: str) -> str:
    """Schickt Text an die Hermes-Session und gibt den Antworttext zurück."""
    # Der hermes-Wrapper macht genau das; wir rufen den venv-Python direkt auf.
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}

    prompt = config.VOICE_PREAMBLE + text

    proc = await asyncio.create_subprocess_exec(
        *_build_cmd(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=config.HERMES_CWD,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(prompt.encode()), timeout=config.HERMES_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HermesError(
            f"Hermes hat nach {config.HERMES_TIMEOUT:.0f}s nicht geantwortet."
        )

    stderr = err.decode(errors="replace").strip()
    if proc.returncode != 0:
        log.error("hermes rc=%s stderr=%s", proc.returncode, stderr[-2000:])
        raise HermesError(f"Hermes-Aufruf fehlgeschlagen (rc={proc.returncode}).")

    reply = out.decode(errors="replace").strip()
    if not reply:
        log.error("hermes lieferte leere Antwort, stderr=%s", stderr[-2000:])
        raise HermesError("Hermes lieferte eine leere Antwort.")
    return reply
