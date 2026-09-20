# Feature-Spec: "Jarvis" Voice-Chat-App mit Hermes

Eine neue eigenständige Web-App (PWA), mit der Bennet per Sprache in Echtzeit
mit Hermes (seinem KI-Assistenten, volle Tools/Gedächtnis) reden kann — wie
ein Voice-Call, nicht wie ein klassisches Telefonat (kein echtes Telefonnetz).
Sprache rein -> Transkription -> an eine laufende Hermes-Session -> Antwort
-> Text-zu-Sprache mit einer ruhigen, "Jarvis/Friday aus Iron Man"-artigen
Stimme -> Wiedergabe im Browser. Englischsprachig (Nutzer spricht/hört
Englisch), auch wenn Bennet sonst Deutsch mit Hermes spricht.

## Architektur (verbindlich, bitte exakt so umsetzen)

```
Browser (iPhone/Desktop, PWA)
  -> MediaRecorder/Web Audio nimmt Sprache auf (Push-to-Talk: Button gedrückt
     halten oder toggle-Start/Stop; KEIN "immer offenes Mikro" wegen Privacy
     und Server-Last)
  -> POST Audio-Blob an Backend-Endpoint /api/transcribe
Backend (FastAPI, Python 3, neuer Service)
  -> lokales Whisper (faster-whisper, bereits als Modell im HF-Cache
     vorhanden: models--Systran--faster-whisper-base/small/medium — nutze
     "small" oder "medium" für brauchbare Genauigkeit bei akzeptabler
     Geschwindigkeit auf dieser CPU-only-Hardware, teste beide und entscheide)
     transkribiert den Ton zu englischem Text.
  -> Text wird an eine PERSISTENTE, laufende Hermes-Session weitergereicht
     via `hermes chat --continue -q "<text>"` (oder `--resume <session-id>`
     falls --continue sich als unzuverlässig erweist — teste beides,
     dokumentiere was funktioniert) durch `subprocess`/`asyncio.subprocess`,
     im selben Arbeitsverzeichnis bei jedem Aufruf, damit die Session-Historie
     erhalten bleibt. Wichtig: Hermes braucht ggf. deutlich länger als Sekunden
     für eine Antwort (Tool-Aufrufe etc.) — das ist beabsichtigt, siehe
     Filler-Sounds unten.
  -> Antworttext geht an /api/speak
  -> TTS via OpenRouter Fish Audio (Modell "fish-audio/s2.1-pro-free",
     KOSTENLOS, aber NUR ENGLISCH):
     POST https://openrouter.ai/api/v1/audio/speech
     Header: Authorization: Bearer $OPENROUTER_API_KEY, Content-Type: application/json
     Body: {"model":"fish-audio/s2.1-pro-free","input":"<text>","voice":"<voice-id>","response_format":"mp3"}
     Response: rohe Audiobytes (mp3), NICHT JSON — direkt in eine Datei
     schreiben bzw. als StreamingResponse durchreichen.
     OPENROUTER_API_KEY liegt bereits in ~/.hermes/.env als
     OPENROUTER_API_KEY=... — lies ihn NICHT direkt aus dieser Datei (Hermes-
     Credential-Store, geschützt), sondern übernimm ihn als normale
     Environment-Variable beim App-Start (z.B. eigene .env-Datei im
     Projektverzeichnis, die Bennet manuell befüllt, oder Docker-Compose
     env_file — dokumentiere das klar in der README statt es zu erraten).
  -> Browser spielt die Audio-Antwort ab.
```

## "Jarvis"-artige Stimme finden

Fish Audio s2.1-pro-free braucht eine `voice`-ID (Beispiel im Dokubeleg:
"b347db033a6549378b48d00acb0d06cd" — das ist nur ein Beispielwert aus der
Doku, KEIN garantiert funktionierender Voice-Slug für dieses Projekt).
Recherchiere über OpenRouter/Fish-Audio-Dokumentation oder über echte
Testaufrufe, welche verfügbaren Stimmen es gibt, und wähle eine ruhige,
britisch/neutral klingende männliche Stimme, die dem Jarvis/Friday-Vibe aus
Iron Man nahekommt (KEIN Voice-Cloning einer echten Filmstimme — das ist
weder technisch über diese API vorgesehen noch rechtlich sauber, nur der
generelle Charakter/Ton: ruhig, präzise, leicht formell, hilfsbereit).
Teste mindestens 2-3 verfügbare Stimmen mit einem kurzen Beispieltext und
entscheide dich hörbar/dokumentiert für eine.

## Filler-Sounds während Hermes antwortet

Da eine echte Hermes-Antwort (mit Tool-Nutzung) mehrere Sekunden bis über eine
Minute dauern kann, MUSS die App sofort nach der Transkription (BEVOR die
Hermes-Antwort da ist) einen kurzen, natürlich klingenden Zwischenkommentar
abspielen, damit sich die Wartezeit nicht tot anfühlt. Beispiele fürs Vibe
(nicht wörtlich vorgeschrieben, aber in diese Richtung, kurz und variiert):
"Okay, got it.", "I'm on it.", "Mhmm, let me have a look.", "Sure, one
moment.", "Alright, working on that.", "Give me a second."

- Baue eine Liste von ca. 8-12 solcher kurzen Filler-Phrasen.
- Generiere für jede Phrase EINMALIG beim ersten Serverstart (oder per
  Setup-Skript) ein Audiofile über dieselbe Fish-Audio-Stimme und cache es
  lokal (z.B. `data/fillers/<hash-oder-index>.mp3`) — NICHT bei jedem
  Request neu generieren (Kosten/Latenz sparen, auch wenn's aktuell
  kostenlos ist).
- Bei jedem Voice-Turn: sofort nach der Transkription EINEN zufälligen
  (nicht immer denselben) Filler aus dem Cache abspielen, während im
  Hintergrund parallel die Hermes-Anfrage + spätere TTS-Generierung der
  echten Antwort läuft. Wenn die echte Antwort fertig ist, wird sie
  nachgeschoben/abgespielt (Frontend muss das sauber sequenzieren: erst
  Filler zu Ende spielen lassen, dann echte Antwort, kein Überlappen/
  Abschneiden).

## Frontend (PWA, ähnlich Stil wie Bennets andere Projekte: modern,
iPhone-optimiert, Dark-Mode-fähig)

- Eine einzige Hauptansicht: großer Push-to-Talk-Button (z.B. Mikrofon-Icon
  als eigenes SVG, KEIN Emoji — falls du ein Icon-System brauchst, baue es
  analog zu simplen Inline-SVGs), Status-Anzeige (idle / recording /
  transcribing / thinking / speaking), ein scrollbarer Transkript-Verlauf
  (User-Text + Hermes-Text abwechselnd, wie ein Chat-Verlauf, damit man auch
  mitlesen kann was gerade gesagt wurde).
- Push-to-Talk-Interaktion: Button gedrückt halten zum Aufnehmen (oder Tap-
  to-start/Tap-to-stop als Fallback für Touch-Geräte, wo "gedrückt halten"
  unzuverlässig sein kann — deine Entscheidung, dokumentiere sie).
- PWA-Grundausstattung: manifest.json, viewport/apple-mobile-web-app Meta-
  Tags, kein Service-Worker-Zwang falls das für Audio-Aufnahme Probleme
  macht (Audio-APIs in SW sind heikel) — Service Worker ist optional/nice-to-
  have hier, nicht Kernanforderung.
- Sauberes Error-Handling: Mikrofon-Berechtigung verweigert, Backend nicht
  erreichbar, Hermes-Timeout — alles mit klarer Nutzermeldung, kein stiller
  Hänger.

## Deployment

- Port **8020** (verifiziert frei auf dem Server).
- Docker Compose Setup wie bei den anderen Projekten (rezeptplaner als
  Vorbild: `~/apps/rezeptplaner/Dockerfile` + `docker-compose.yml` anschauen
  für Konventionen), aber diesmal:
  - `hermes`-CLI wird gebraucht (analog zu `claude`-CLI-Mounting im
    rezeptplaner-Projekt). VERIFIZIERT auf diesem System: `which hermes` ->
    `/home/bennetgriese/.local/bin/hermes`, ein Wrapper-Skript das
    `unset PYTHONPATH; unset PYTHONHOME; exec
    "/home/bennetgriese/.hermes/hermes-agent/venv/bin/python"
    "/home/bennetgriese/.hermes/hermes-agent/hermes" "$@"` ausführt. Für den
    Container brauchst du also entweder: (a) das komplette venv unter
    `~/.hermes/hermes-agent/venv` UND das Wrapper-Skript UND `~/.hermes`
    (Config/Sessions/Auth) read-write gemountet, oder (b) einfacher: rufe
    direkt den venv-Python-Interpreter mit dem hermes-Skript-Pfad auf statt
    über den `hermes`-Wrapper, sofern das im Container-Kontext zuverlässiger
    ist. Teste beide Varianten, entscheide dich für die robustere, und
    dokumentiere in der README exakt welche Mounts/Pfade nötig sind.
  - faster-whisper Modell-Cache (HF_HOME) analog zum rezeptplaner-Bild-
    Feature mounten/persistieren, damit das Modell nicht bei jedem Container-
    Neustart neu geladen wird.
- Für Mikrofonzugriff im Browser braucht es HTTPS (außer localhost). Der
  Server hat bereits `tailscale serve` aktiv für andere Dienste (Container
  `tailscale`, `tailscale serve status` zeigt bestehende Proxies). Ergänze in
  der README eine klare Anleitung, wie Bennet selbst einen weiteren
  `tailscale serve`-Eintrag für Port 8020 einrichtet (z.B.
  `docker exec tailscale tailscale serve --bg 8020` o.ä. — recherchiere die
  exakte aktuelle Syntax, IMPLEMENTIERE DAS NICHT SELBST als echten
  Tailscale-Config-Change, nur dokumentieren, da das eine Netzwerk-
  Änderung ist, die der Nutzer bewusst freigeben soll).

## Nicht-Ziele
- Kein echtes Telefonnetz (kein Twilio, keine Rufnummer).
- Kein perfektes "sich gegenseitig ins Wort fallen" wie ein echtes Telefonat
  — Push-to-Talk-Turns reichen.
- Keine Stimmklonung einer echten Filmfigur.
- Kein Multi-User/Login — Single-User für Bennet.
- Keine Persistenz des Sprach-Chatverlaufs über Server-Neustarts hinaus ist
  zwingend erforderlich (nice-to-have wenn easy, aber kein Muss — die
  Hermes-Session selbst bleibt ja über deren eigene Persistenz erhalten).

## Qualitätsanforderungen
- Teste ECHT: einen echten `hermes chat --continue -q "..."`-Aufruf und
  bestätige, dass er tatsächlich antwortet (nicht nur dass der Prozess
  startet). Teste einen echten Fish-Audio-TTS-Call und bestätige, dass eine
  abspielbare Audiodatei zurückkommt (Dateigröße > 0, gültiges MP3-Format
  prüfen, z.B. via `file`-Befehl). Teste faster-whisper mit einer echten
  kurzen Audio-Aufnahme (kannst du z.B. mit `espeak`/`say`/einer
  vorhandenen Audiodatei/synthetisch erzeugen, falls kein echtes Mikrofon im
  Sandbox-Kontext verfügbar ist — dokumentiere den Testweg ehrlich).
- Berichte ehrlich, welche Stimme du gewählt hast und warum, welche Whisper-
  Modellgröße du gewählt hast und mit welcher gemessenen Transkriptionszeit,
  und was du NICHT im Sandbox-Kontext testen konntest (z.B. echtes Browser-
  Mikrofon, echtes iPhone).
- KEINE Emojis irgendwo im Code/UI.
- Committe NICHTS, pushe NICHTS zu Git, deploye NICHT selbst per Docker,
  richte KEINE echten Tailscale-Serve-Einträge ein — das entscheidet und
  macht der Nutzer/eine andere Instanz danach selbst, dokumentiere nur wie.
- Erstelle eine README.md mit: Architekturüberblick, exaktem Setup (inkl.
  wie der OpenRouter-Key reingegeben wird, wie Hermes im Container verfügbar
  gemacht wird, wie tailscale serve einzurichten ist), bekannten Grenzen.
