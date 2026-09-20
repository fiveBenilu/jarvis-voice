# Jarvis Voice

Sprach-Chat mit Hermes im Browser. Push-to-Talk aufnehmen, lokales Whisper
transkribiert, eine persistente Hermes-Session antwortet, Fish Audio liest die
Antwort mit ruhiger britischer Stimme vor. Englisch gesprochen, Single-User,
PWA-tauglich auf dem iPhone.

## Architektur

```
Browser (PWA)  --MediaRecorder-->  POST /api/transcribe   (webm/opus bzw. mp4 auf iOS)
                                        |
                                        |-- faster-whisper "small", CPU, int8  -> englischer Text
                                        |-- startet den Turn im Hintergrund, antwortet SOFORT mit
                                        |   { text, job_id, filler }
                                        v
Browser spielt Filler ab  <-------  GET /api/fillers/NN.mp3   (vorgeneriert, gecacht)
                                        |
   parallel im Backend:                 |
     hermes chat --continue jarvis-voice --create-if-missing -Q --query-file -
     -> Antworttext -> Fish Audio TTS -> MP3 im Job
                                        |
Browser long-polled  <------------  GET /api/reply/{job_id}?wait=25  -> {text, audio}
Browser spielt Antwort  <---------  GET /api/audio/{job_id}
```

Der Filler läuft **immer zu Ende**, bevor die echte Antwort startet - das
Frontend wartet auf beides (`await fillerDone` vor der Wiedergabe), es wird
nichts überlappt oder abgeschnitten.

### Endpoints

| Methode | Pfad | Zweck |
|---|---|---|
| `POST` | `/api/transcribe` | Audio-Blob rein, Text + `job_id` + Filler-URL raus. Startet den Hermes-Turn. |
| `GET` | `/api/reply/{job_id}?wait=25` | Long-Poll. `pending` -> erneut fragen. |
| `GET` | `/api/audio/{job_id}` | MP3 der Antwort. |
| `POST` | `/api/speak` | `{"text": "..."}` -> MP3. Eigenständig, z.B. zum Stimmen-Testen. |
| `GET` | `/api/fillers/{name}` | Gecachte Filler-MP3. |
| `GET` | `/api/health` | Modell, Stimme, Key vorhanden, Anzahl Filler. |

## Setup

### 1. OpenRouter-Key

Die App liest `~/.hermes/.env` **nicht** - das ist der Hermes-Credential-Store.
Der Key wird als normale Environment-Variable übergeben:

```bash
cp .env.example .env
# OPENROUTER_API_KEY=... eintragen (Wert steht in ~/.hermes/.env)
```

`docker-compose.yml` zieht die Datei über `env_file: .env`. Ohne Key startet der
Server trotzdem, kann aber keine Filler generieren und nichts vorlesen
(`/api/health` zeigt `tts_key_present: false`).

### 2. Filler-Audios

Passiert automatisch beim ersten Serverstart (ca. 14s für 10 Phrasen), danach
liegen sie in `data/fillers/` und werden nie wieder neu erzeugt. Manuell:

```bash
python -m app.tts
```

Wer die Phrasenliste in `app/config.py` ändert: `data/fillers/` einmal leeren.

### 3. Hermes im Container

Hermes wird pro Turn als Subprozess aufgerufen. Nicht offensichtlich, aber
entscheidend:

> `~/.hermes/hermes-agent/venv/bin/python` ist ein **absoluter Symlink** auf
> `~/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11`,
> und `pyvenv.cfg` referenziert denselben Pfad hart.

Daraus folgen zwei Dinge:

1. `~/.hermes` muss im Container auf **denselben absoluten Pfad** wie auf dem
   Host gemountet werden (`/home/bennetgriese/.hermes`), nicht auf `/home/app`.
   Deshalb setzt das Dockerfile `HOME=/home/bennetgriese`.
2. Das uv-CPython-3.11 muss **zusätzlich** gemountet werden. Ohne diesen Mount
   startet Hermes nicht, weil der Symlink ins Leere zeigt.

Beide Mounts stehen bereits in `docker-compose.yml`. `~/.hermes` ist bewusst
**nicht** read-only: Hermes schreibt dort Sessions, State und Token-Refreshes.

**Getestet wurden beide Varianten aus der Spec, beide funktionieren:**

| Variante | Ergebnis |
|---|---|
| (a) `hermes`-Wrapper nach `/usr/local/bin/hermes` mounten | funktioniert, braucht aber einen Mount mehr und eine `bash` im Image |
| (b) venv-Python direkt aufrufen | funktioniert, **gewählt** |

Variante (b) ist im Einsatz: ein Mount weniger, keine Shell-Abhängigkeit, und
das `unset PYTHONPATH/PYTHONHOME` des Wrappers erledigt `app/hermes.py` selbst.

Verifiziert: ein Container-Aufruf hat die Session fortgesetzt, die vorher auf
dem Host angelegt wurde (`Resumed session ... 12 total messages`).

### 4. Session-Kontinuität

`hermes chat --continue jarvis-voice --create-if-missing` - getestet und
zuverlässig. `--create-if-missing` legt die Session beim allerersten Aufruf an,
danach wird sie fortgeführt. `--resume <session-id>` war nicht nötig, weil das
eine ID erfordern würde, die man erst kennt, nachdem die Session existiert.

Wichtig: `--continue <name>` findet die Session nur in dem Workspace, in dem sie
angelegt wurde. Das Arbeitsverzeichnis ist deshalb fest auf `/workspace`
(gemountet von `./data/workspace`) genagelt.

Die Query geht über **stdin** (`--query-file -`) statt `-q`: so wird am
transkribierten Text nichts von der Shell interpretiert.

### 5. Whisper-Modelle

`HF_HOME` zeigt im Container auf `/hf-cache`, gemountet von
`~/.cache/huggingface`. Dort liegen `models--Systran--faster-whisper-{base,small,medium}`
bereits, es wird beim Start nichts nachgeladen.

### 6. Starten

```bash
export UID GID          # damit der Container als du läuft und an ~/.hermes darf
docker compose up -d --build
curl localhost:8020/api/health
```

### 7. HTTPS über Tailscale (macht Bennet selbst)

Mikrofonzugriff braucht HTTPS, außer auf `localhost`. Der `tailscale`-Container
läuft mit `network_mode: host`, erreicht `127.0.0.1:8020` also direkt.

Belegt sind aktuell `443` (-> 18789), `8443` (-> 8090) und `8444` (-> 3011).
`8445` ist frei:

```bash
docker exec tailscale tailscale serve --bg --https=8445 8020
docker exec tailscale tailscale serve status
```

Danach erreichbar unter `https://mediaserver.tailbc1ecb.ts.net:8445`.
Rückgängig: `docker exec tailscale tailscale serve --https=8445 off`.

Das ist **nicht** eingerichtet worden - bewusst, weil es eine Netzwerkänderung
ist. Die Syntax ist gegen die installierte Tailscale-Version 1.102.3 geprüft.

## Entscheidungen

### Stimme: "Brian British" (`65c0b8155c464a648161af8877404f11`)

Die Voice-ID aus der Spec-Doku (`b347db03...`) ist nur ein Beispielwert; gemessen
liegt sie bei ~158 Hz Grundfrequenz, also deutlich zu hoch für den gewünschten
Charakter. Getestet wurden fünf Stimmen aus der Fish-Audio-Bibliothek mit
identischem Beispielsatz:

| Stimme | Grundfrequenz | Tempo | Tonhöhen-Spanne |
|---|---|---|---|
| **Brian British (gewählt)** | 82 Hz | 169 wpm | 28 Hz |
| Liam - Calm British Voice | 86 Hz | 174 wpm | 27 Hz |
| David - British Storyteller | 101 Hz | 156 wpm | 62 Hz |
| british male calm voice | 92 Hz | 160 wpm | 22 Hz |
| Doku-Beispiel `b347db03...` | 158 Hz | 127 wpm | 31 Hz |

Gewählt wurde Brian: tiefste männliche Lage bei gleichzeitig enger
Tonhöhen-Spanne - also ruhig und kontrolliert, ohne ins Monotone zu kippen
(`british male calm voice` mit 22 Hz war messbar flacher) und ohne die
theatralische Modulation des Storytellers (62 Hz). Kein Voice-Cloning: das ist
eine generische Bibliotheks-Stimme, keine Filmfigur.

**Ehrliche Einschränkung:** ich habe die Samples nicht *gehört*. Die Auswahl
beruht auf gemessener Grundfrequenz, Sprechtempo und Intonationsbreite, nicht
auf Klangfarbe oder Akzent-Qualität. Zum Nachhören per Ohr:

```bash
curl -X POST localhost:8020/api/speak -H 'Content-Type: application/json' \
  -d '{"text":"Good evening. All systems are online."}' -o probe.mp3
```

Umstellen ohne Code-Änderung über `TTS_VOICE` in `.env`, Alternativen stehen
dort als Kommentar.

### TTS-Modell: `fish-audio/s2.1-pro` statt `s2.1-pro-free`

Das in der Spec genannte `fish-audio/s2.1-pro-free` existiert auf OpenRouter
nicht mehr:

```
HTTP 404  {"error":{"message":"No endpoints found for fish-audio/s2.1-pro-free."}}
```

Die verfügbare Variante ist `fish-audio/s2.1-pro`. Die ist **nicht kostenlos**,
aber sehr günstig: 0,000015 $ pro Token, eine typische Antwort von ~300 Zeichen
kostet rund 0,005 $. Die Filler kosten einmalig ein paar Cent. Über `TTS_MODEL`
umstellbar, falls die Free-Variante zurückkommt.

### Whisper: `small`

Gemessen auf dieser CPU (6 Kerne, int8), 6,9 s Audio:

| Modell | Ladezeit | Transkription | Ergebnis |
|---|---|---|---|
| **small (gewählt)** | 2,0 s | **1,44 s** | wortgenau |
| medium | 5,2 s | 3,92 s | wortgenau |

Auch mit künstlichem Rauschen (rosa Rauschen, halbe Lautstärke, 20 kbit/s Opus,
Bandpass 120-6000 Hz) lagen beide bei 100 % Wortübereinstimmung. `medium` war
also 2,7x langsamer ohne messbaren Gewinn - bei einer Sprach-App zählt Latenz
mehr. Umstellbar über `WHISPER_MODEL=medium`.

### Push-to-Talk: Tap-to-start / Tap-to-stop

Statt "gedrückt halten". Auf iOS Safari kollidiert ein langer Druck mit
Text-Selektion, Callout-Menü und Scroll-Gesten, und ein sauberes `pointerup`
kommt dort nicht zuverlässig an - eine verlorene Aufnahme ist schlimmer als ein
zweiter Tap. Tap/Tap verhält sich auf allen Geräten gleich.

### Antwort-Preamble

Hermes antwortet Bennet von sich aus auf Deutsch und in langem Markdown-Fließtext.
Beides ist hier unbrauchbar: die Stimme kann nur Englisch, und alles wird
vorgelesen. Ein echter Testlauf ergab **117 Sekunden** deutsches Audio.

`app/config.py:VOICE_PREAMBLE` stellt der Frage deshalb eine Anweisung voran
(Englisch, 1-3 Sätze, kein Markdown, bei Bedarf Kurzfassung plus Nachfrage).
Dieselbe Frage lieferte danach **19 Sekunden**. Tools und Gedächtnis bleiben
unangetastet, nur die finale Antwort ist eingeschränkt. Anpassbar über
`VOICE_PREAMBLE`.

## Getestet

Alles echt gelaufen, nichts simuliert:

- **Hermes**: `hermes chat --continue` antwortet wirklich; eine Folge-Frage in
  einem *neuen* Prozess erinnerte sich an den vorherigen Turn (Antwort "Teal.").
  Ein echter Turn mit Tool-Nutzung (docker, git) brauchte ~50 s - genau der Fall,
  für den die Filler da sind.
- **TTS**: `file` bestätigt `MPEG ADTS, layer III, v1, 128 kbps, 44.1 kHz,
  Monaural`, `ffprobe` eine Dauer von 19,3 s. Alle 10 Filler erzeugt, 13-35 KB,
  ~1,4 s Länge.
- **Whisper**: Testaudio per Fish-Audio-TTS erzeugt (kein Mikrofon in der
  Sandbox), mit `ffmpeg` nach webm/opus konvertiert - also dasselbe Format, das
  der Browser schickt. Transkript wortgenau gegen den bekannten Ausgangstext.
- **Kompletter Turn im echten Browser**: Chromium via Playwright mit
  `--use-file-for-fake-audio-capture`, iPhone-Viewport. Ablauf beobachtet:
  `idle -> recording -> transcribing -> thinking -> speaking`, User- und
  Bot-Bubble korrekt gefüllt, Antwort-MP3 abgespielt, keine JS- oder
  Konsolenfehler.
- **Fehlerpfade**: leerer Upload -> 400, Stille -> 422 mit Klartextmeldung im
  UI, unbekannte `job_id` -> 404, `../`-Versuch auf `/api/fillers/` -> 404.
- **Container**: Hermes im Container gestartet und dieselbe Session fortgesetzt,
  die vorher auf dem Host lief. Beide Mount-Varianten geprüft.

## Nicht getestet

- **Echtes iPhone, echtes Mikrofon, echtes Safari.** Der Browser-Test lief in
  headless Chromium mit eingespeister Audiodatei. Ungeprüft bleiben damit vor
  allem: `audio/mp4` als MediaRecorder-Format (Safari kann kein webm/opus), das
  Autoplay-Entsperren des Audio-Elements auf iOS, und das Verhalten im
  Homescreen-Standalone-Modus.
- **Klang der Stimme.** Siehe oben - ausgewählt nach Messwerten, nicht nach Gehör.
- **Docker-Build und -Deployment.** `Dockerfile` und `docker-compose.yml` sind
  nicht gebaut worden (bewusst, laut Auftrag). Die Hermes-Mount-Logik wurde
  separat in einem Wegwerf-Container verifiziert, die Python-Abhängigkeiten aus
  `requirements.txt` sind es nicht. Der erste `docker compose up --build` ist
  also der erste echte Build.
- **Lange Hermes-Antworten über 300 s** (`HERMES_TIMEOUT`) - der Timeout-Pfad ist
  implementiert, aber nie ausgelöst worden.

## Grenzen

- **Kein Verlauf über Neustarts.** Die letzten 20 Turns liegen im RAM; die
  Hermes-Session selbst bleibt natürlich erhalten. Laut Spec kein Muss.
- **Single-User, kein Login.** Wer den Port erreicht, redet mit Hermes - und
  Hermes hat volle Tools. Nicht ins öffentliche Internet hängen; `tailscale
  serve` (tailnet only) statt `tailscale funnel`.
- **Ein Turn nach dem anderen.** Kein Ins-Wort-Fallen, kein Barge-in.
- **Kein Service Worker.** Wäre für Audio-Aufnahme eher Risiko als Nutzen, und
  laut Spec optional. Manifest und Meta-Tags sind da, die App ist
  installierbar - offline funktioniert sie nicht.
- **TTS nur Englisch.** Deutsche Antworten würden von der Stimme falsch
  ausgesprochen; deshalb der Preamble oben.
