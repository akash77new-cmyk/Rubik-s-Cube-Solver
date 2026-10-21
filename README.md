<div align="center">

<img src="assets/brand/logo.svg" width="92" alt="CubeSolver logo" />

# Real-Time Rubik's Cube Solver

**An end-to-end computer-vision pipeline that scans a physical 3×3 Rubik's Cube with a webcam
and solves it with the Kociemba two-phase algorithm — wrapped in a real desktop-class UI.**

`Python` · `OpenCV` · `NumPy` · `PostgreSQL` · `SQLAlchemy` · `React` · `TypeScript` · `Socket programming`

</div>

---

## What it does

Point a webcam at each face of a scrambled cube. The vision pipeline segments the stickers by
HSV colour, builds a fully validated cube state (every piece identified; twist, flip and parity
checked), feeds it to the Kociemba two-phase
solver, and walks you through the solution move by move — with a synchronised 3D cube, graphical
rotation arrows drawn over the live feed, and an analytics dashboard tracking every run.

![Dashboard](docs/screenshots/01-dashboard.png)

---

## Highlights

| | |
|---|---|
| **Computer-vision pipeline** | Threaded OpenCV capture → bilateral denoise → HSV → 3×3 patch sampling with a *circular-median* hue (survives the red 179/0 wrap) → per-sticker confidence. |
| **HSV colour segmentation** | Six tunable HSV boxes with hue wrap-around, scored by how centrally a sample sits inside its box. Built-in `default` / `low-light` / `legacy` presets plus user profiles. |
| **Cube state & move simulation** | Immutable 54-facelet model. Every turn returns a *new* state, so solution playback scrubs forwards and backwards instantly. |
| **Full validation** | Every corner and edge is identified and the three invariants (twist, flip, parity) are checked. Only 1 in 12 ways of assembling a cube is solvable. Each problem is reported with the exact stickers involved. Cross-checked against Kociemba's reference implementation. |
| **Kociemba two-phase solver** | Pluggable backend: the native C extension when installed, otherwise Kociemba's own pure-Python implementation. Solutions are ≤ 20 moves, found in single-digit milliseconds. |
| **Socket-based IPC** | The vision engine runs as its **own OS process** and publishes state and JPEG frames over a length-prefixed TCP protocol. The web server is a pure relay. |
| **Real-time synchronisation** | One Socket.IO connection mirrors the engine snapshot into React. Every page reads the same state; every action is a single command going the other way. |
| **Analytics** | Solve history in PostgreSQL: move counts, search times, execution times, move distribution and running average sticker confidence. |
| **Database** | PostgreSQL (Neon) in production, SQLite locally, through SQLAlchemy. Alembic migrations run automatically at start-up. Reads are served from memory, so the camera loop never waits for the network; writes go to the database first. |
| **Guided scanning** | Colour-only step guide; faces identified by their centre colour (no duplicates, any order); mirrored previews un-mirrored; orientation mistakes repaired by a smallest-change search that only applies unique fixes. |
| **Plain-English moves** | A "hold the cube like this" step comes first; then every move says which way to turn, seen from where you are ("Turn the top layer to the left."), including back-layer moves. Arrows and instructions are checked against the cube model by tests. |
| **Training-data collection** | Every sticker keeps its reading: colour, confidence, the best three colours, and whether the detector was unsure. Confirmed scans are saved as 54 labelled 32×32 sticker crops (`ml/data/`), balanced by design and with corrected stickers marked as hard examples. |

---

## Quick start

```bash
# 0. Local settings (optional for local development - the defaults just work)
cp .env.example .env

# 1. Python dependencies
python -m pip install -r requirements.txt

# 2. Frontend (one-time build)
cd frontend && npm install && npm run build && cd ..

# 3. Run everything
python run.py
```

`run.py` spawns the vision engine process, starts the web server, and opens
<http://127.0.0.1:8000>.

> **First run takes a few minutes.** `RubikTwoPhase` builds ~70 MB of pruning tables into
> `.cache/twophase/`. This happens in a background thread — the UI stays responsive and shows
> `Solver: warming`. Every later start loads the tables in ~0.1 s.
>
> Prefer to skip the wait? Install the C extension instead (needs a C toolchain):
> `pip install kociemba`. The solver engine detects and prefers it automatically.

**No webcam?** The whole app is still demoable: **Demo scramble** on the dashboard generates a
random cube, and everything downstream — solving, 3D playback, analytics — works from there.

### Other ways to run

```bash
python run.py --dev          # frontend served by Vite (npm run dev) with HMR
python run.py --no-engine    # attach to an engine started elsewhere
python -m backend.engine     # run just the vision engine
python -m backend.server.app # run just the web server
```

---

## The nine screens

### 1 · Dashboard
Animated hero cube, live system status for every stage, session statistics and quick actions.

![Dashboard](docs/screenshots/01-dashboard.png)

### 2 · Live Camera
The MJPEG feed with the detection HUD drawn **into the frame by OpenCV**: rounded sticker chips
in the detected colour, per-sticker confidence bars, a corner reticle that turns green when the
read locks, and the cube contour. Beside it: live HSV values and confidence per sticker.

![Live Camera](docs/screenshots/02-camera.png)

### 3 · Scanning Pipeline
A scan guide shows each step with colours only: green facing the camera with white on top,
then red, blue and orange, then white (blue on top) and yellow (green on top). Each side is
recognised by its centre colour, so it is captured once, in any order. A mirrored camera
preview is handled, and a side held the wrong way up is repaired automatically when the fix is
unique. The guide sits beside the camera, with its one action right under the current step
(Start scanning, then Capture). Capture is manual by default: the button names the side it will
store and turns on only for a steady, confident read of a side that still needs scanning. In Auto mode a side is captured once it has been held still for a moment (1 s by
default, adjustable in Settings), and a "Hold still" bar shows the progress.

Each face tile fills in as it lands, and full validation (colours, pieces, twist, flip, parity)
runs before the solver is allowed to start, and the stickers behind each problem are outlined on
the net. Unsure stickers get a dashed amber outline, and hovering a sticker shows what the camera
saw. After a valid scan, the Training data card saves it to the dataset.

![Scanner](docs/screenshots/03-scanner.png)

### 4 · Cube State Visualizer
A real 3×3×3 stack of 26 CSS-3D cubies — drag to orbit, scroll to zoom, hover a face to
highlight it — beside the unfolded net. Switch to **Edit** to repaint any sticker that was read
under a glare, or apply turns manually to exercise the move simulation.

![Cube Viewer](docs/screenshots/04-cube-viewer.png)

### 5 · Solution Visualizer
Current / previous / next move, the full sequence as clickable badges, play · pause · step ·
restart · speed, and the 3D cube **animating the actual layer turn** after every move. Before
the first move, a picture shows how to hold the cube (green facing you, white on top); every
instruction is from that position, and the cube is never turned around. Each move is written in
plain English, e.g. *R: "Turn the right side up, away from you."* and *B: "Turn the back layer,
the side facing away from you: its top moves to the left."* Auto play shows each move for 8 s
(adjustable), with a time bar and timer that restart for every move. A solved cube glows and
gets a burst of cube-coloured confetti. "Camera guidance" overlays the hold picture, then each arrow and instruction, onto
the live feed instead.

![Solution](docs/screenshots/05-solution.png)

### 6 · Analytics
Solution time, move count, average solve time, total cubes solved, current solver backend and
average sticker confidence. Plus the solve timeline, move distribution per face, turn-type split and a
full history table.

![Analytics](docs/screenshots/06-analytics.png)

### 7 · HSV Calibration
Live mask preview showing exactly which pixels the current box accepts, six sliders per colour,
a hue histogram of saturated pixels, sample-and-auto-fit, and named profiles you can switch
between for different lighting.

![Calibration](docs/screenshots/07-calibration.png)

### 8 · Logs
Colour-coded, filterable event stream from the vision engine — camera started, face detected,
solving, solution generated, move executed, completed.

![Logs](docs/screenshots/08-logs.png)

### 9 · Settings
Camera device, resolution, FPS, detection geometry, overlay visibility, arrow style, playback
speed, theme and the cube palette. Everything is saved in the database and applies to the
running engine immediately. The Storage card shows which database is in use and whether it is
reachable; if a change cannot be saved, a "Not saved" message says why.

![Settings](docs/screenshots/09-settings.png)

### Themes
Three of them, switchable from the **Appearance** picker on the dashboard, the header button
(which cycles) or Settings. Every surface, ink and chart colour has a counterpart in each.

**Midnight** — true black for OLED panels and dim rooms. Surfaces drop to near-zero so the
accents become the only light in the frame, which is what lets the glow read as glow.

![Midnight theme](docs/screenshots/11-midnight-theme.png)

**Light** — for well-lit rooms.

![Light theme](docs/screenshots/10-light-theme.png)

---

## Architecture

```
                    ┌──────────────────────────────┐
   webcam ─────────►│  Vision engine   (process 1) │
                    │  backend/engine.py           │
                    │   • CameraStream (threaded)  │
                    │   • FaceDetector  (HSV)      │
                    │   • OverlayRenderer          │
                    │   • SolveSession  (state)    │
                    │   • SolverEngine  (Kociemba) │
                    └──────────────┬───────────────┘
                                   │ TCP :9999
                                   │ length-prefixed frames
                                   │  'J' JSON  ·  'F' JPEG
                    ┌──────────────▼───────────────┐
                    │  Web server      (process 2) │
                    │  backend/server/app.py       │
                    │   • Socket.IO relay          │
                    │   • /api/stream.mjpg         │
                    │   • serves frontend/dist     │
                    └──────────────┬───────────────┘
                                   │ WebSocket + MJPEG
                    ┌──────────────▼───────────────┐
                    │  React + TypeScript UI       │
                    │  frontend/src                │
                    └──────────────────────────────┘
```

The engine is the **single source of truth**. The web server holds no cube state — it forwards
browser commands down the socket and engine events back up. A blocking OpenCV capture loop can
therefore never stall an HTTP request, and the same engine could feed a native client or a
second machine unchanged.

### Layout

```
backend/
  config.py            paths, environment variables, the Settings model
  core/                pure domain logic — no OpenCV, no Flask, no sockets
    cube.py            CubeState: 54 facelets, move simulation, validation
    cubie.py           8 corners + 12 edges, twist / flip / parity, G1 check
    validation.py      structured validation issues
    moves.py           Singmaster notation, metadata, plain-English instructions, physical turns
    scanning.py        scan guide, face identification, orientation repair
    solver.py          SolverEngine + pluggable Kociemba backends
    color.py           HSV boxes, classification with confidence, built-in presets
  db/
    database.py        engine, transactions, connection status (no secrets shown)
    models.py          the tables: app_settings, color_profiles, solves
    migrate.py         runs Alembic migrations at start-up, retries while Neon wakes
    migrations/        Alembic: env.py + versions/0001_initial_schema.py
  vision/
    camera.py          threaded capture, FPS, device enumeration
    detector.py        the HSV segmentation pipeline
    overlay.py         the OpenCV HUD (drawn procedurally, never blitted PNGs)
  ipc/
    protocol.py        length-prefixed framing
    server.py          engine-side TCP server + broadcast
    client.py          web-server-side client with auto-reconnect
  services/
    session.py         the state machine every UI page mirrors
    settings.py        settings store (memory copy, written through to the database)
    profiles.py        HSV profile store: built-in presets + user profiles
    analytics.py       solve history + aggregate statistics
    legacy_import.py   one-time import of the pre-Phase-3 JSON files
    dataset.py         training-data collection (scans → labelled crops)
    logbus.py          structured ring-buffer log stream
  server/app.py        Flask + Socket.IO + MJPEG

frontend/src/
  state/AppStore.tsx   one socket → React state, one command channel back
  components/          cube (3D + net), move glyphs, charts, ui primitives
  pages/               the nine screens

ml/data/               sticker colour dataset (see ml/data/README.md)

tools/
  generate_assets.py   generates every SVG in assets/
  rasterize.mjs        SVG → high-resolution PNG (sharp)
  screenshots.mjs      captures docs/screenshots (puppeteer)
  verify.py            end-to-end check of the whole pipeline

python code files/     original CLI entry points, now thin wrappers over backend/

alembic.ini            the alembic command line (the app itself does not need it)
```

---

## Command-line tools

The original terminal workflow still works and now shares all its logic with the web app:

```bash
python "python code files/cube_solver.py"      # scan + solve in an OpenCV window
python "python code files/cube_viewer.py"      # net viewer, subscribes to the engine
python "python code files/hsv_calibrator.py"   # trackbar calibration, saves real profiles
```

The legacy CLI scanner does not have guided scanning (scan guide, centre-based face identity,
mirror handling, orientation repair). The web app is the supported scanner.

---

## Development

```bash
python -m pip install -r requirements-dev.txt   # app + pytest + Socket.IO client

pytest                          # unit tests (about 40 s: scanning tests run the real detector)
pytest -m "not slow"            # skip the solver tests
python tools/verify.py          # end-to-end pipeline check (13 offline checks)
python tools/verify.py --live   # + 7 checks against a running app (python run.py --headless)
```

The unit tests live in `tests/`. They never touch your real `data/` folder or a real database:
`tests/conftest.py` points `CUBE_DATA_DIR` at a throwaway temp folder and ignores `DATABASE_URL`.

Database tests run on SQLite. To run them on PostgreSQL as well, start a throwaway server in
Docker and point `CUBE_TEST_POSTGRES_URL` at it (tests delete this app's tables there):

```bash
docker run -d --name cube-pg -p 5433:5432 -e POSTGRES_PASSWORD=cube pgvector/pgvector:pg17
docker exec cube-pg psql -U postgres -c "CREATE DATABASE cube_test"
CUBE_TEST_POSTGRES_URL=postgresql://postgres:cube@127.0.0.1:5433/cube_test pytest
```

### Database migrations

The schema is versioned with Alembic. The engine applies new migrations when it starts, so
there is nothing to run by hand. To change a table:

1. change the class in `backend/db/models.py`;
2. `python -m alembic revision --autogenerate --rev-id 0002 -m "what changed"`, then read and
   tidy the generated file in `backend/db/migrations/versions/`;
3. run `pytest`: `test_models_match_the_migrations` fails if the two disagree.

Never edit a migration that has already run on Neon; add a new one.

---

## Verifying it works

```bash
python tools/verify.py
```

Runs the whole stack headlessly and checks: cube-model correctness over random scrambles,
solver output verified by replaying it, socket framing across split TCP chunks, HSV
classification on a synthetic cube face, database migrations and data surviving a restart,
and a full scramble → solve → playback → analytics round trip over Socket.IO.
`--live --expect-db postgresql` fails unless the running app uses PostgreSQL.

Regenerate art and screenshots:

```bash
python tools/generate_assets.py --png     # 26 SVGs + 512 px PNGs
npm install && npm run screenshots        # requires the app to be running
```

---

## Assets

Every piece of art is generated from `tools/generate_assets.py` — 19 move arrows (six faces ×
clockwise / counter-clockwise / 180°, plus the whole-cube "turn back" hint), six sticker
swatches and the logo — as **SVG**, with 512 px PNGs rasterised alongside them.

<div align="center">
<img src="assets/arrows/R.svg" width="86" alt="R" />
<img src="assets/arrows/Up.svg" width="86" alt="U prime" />
<img src="assets/arrows/F2.svg" width="86" alt="F2" />
<img src="assets/arrows/TURN_BACK.svg" width="86" alt="Turn cube" />
</div>

The on-camera arrows are a separate path: `backend/vision/overlay.py` draws them procedurally
with anti-aliased OpenCV primitives, so the HUD stays crisp at any capture resolution instead
of blitting a fixed-size bitmap.

---

## Notes on the solver backends

| Backend | Install | Warm-up | Solve |
|---|---|---|---|
| `kociemba` (C) | needs a C toolchain (MSVC Build Tools on Windows) | instant | < 1 ms |
| `RubikTwoPhase` (pure Python) | `pip install RubikTwoPhase` — works everywhere | ~70 MB of tables built once, then ~0.1 s | 3–200 ms |

Both implement Herbert Kociemba's two-phase algorithm; `RubikTwoPhase` is by Kociemba himself.
The engine picks the fastest available at runtime and reports which one is active on the
Analytics page. This is why the project has no hard dependency on a compiler.

---

## Configuration

| Where | Contents |
|---|---|
| table `app_settings` | camera, detection, overlay, playback, theme |
| table `color_profiles` | user-saved HSV profiles |
| table `solves` | solve history |
| `ml/data/scans/` | saved training scans (committed) |
| `.cache/twophase/` | generated pruning tables (safe to delete; rebuilt on demand) |

The database is `DATABASE_URL`: Neon PostgreSQL in production, and a local SQLite file
(`data/cube.db`) when it is not set. The Settings page shows which one is in use. On the first
start after Phase 3, the old `data/*.json` files are imported once and kept as `*.imported`.

Ports, hosts, the secret key and the data folder come from environment variables - see
[Environment variables](#environment-variables).

---

## Deployment

In production the app runs as one container with two processes: the vision engine and the web
server (gunicorn).

### Production mode (Linux / macOS / WSL)

```bash
python -m pip install -r requirements-prod.txt   # adds the C solver (needs gcc) + gunicorn
APP_ENV=production FLASK_SECRET_KEY=change-me DATABASE_URL='postgresql://...' python run.py --prod
```

`run.py --prod` starts the engine and gunicorn (one worker with threads, see `gunicorn.conf.py`)
and supervises both: if either one exits, the other is stopped and the process exits non-zero so
the platform restarts it. gunicorn does not run on Windows - use Docker or WSL there.

### Docker

```bash
docker build -t cube-solver .
docker run --rm -p 8000:8000 -e PORT=8000 -e FLASK_SECRET_KEY=dev \
  -e DATABASE_URL='postgresql://user:password@host/db' cube-solver
```

Then open <http://127.0.0.1:8000>. The multi-stage build compiles the C solver in a build stage,
so the final image contains only what runs. Production refuses to start without `DATABASE_URL`:
the container's disk is temporary, so a local file would silently lose all history.

### Render

`render.yaml` is a Render Blueprint: one free Docker web service with a health check on
`/api/health`. In Render choose **New → Blueprint**, pick this repository and click **Apply**.
Render generates `FLASK_SECRET_KEY` and sets `PORT`. `DATABASE_URL` is a secret: add it in the
service's **Environment** page (the Neon connection string of the `production` branch, with
connection pooling off).

The live demo has no webcam (use **Demo scramble**) and sleeps after 15 minutes without traffic.
Its disk is temporary, but settings, profiles and solve history are in Neon, so they survive
every deploy. Neon's free database also sleeps after 5 idle minutes; the first query after that
wakes it in about a second, and the engine retries while it does.

### Environment variables

Locally they can live in a `.env` file (copy `.env.example`); real environment variables always
win over it.

| Variable | Development default | Production |
|---|---|---|
| `APP_ENV` | `development` | `production` (set in the Dockerfile) |
| `FLASK_SECRET_KEY` | insecure dev key | required (Render generates it) |
| `CUBE_WEB_HOST` | `127.0.0.1` | `0.0.0.0` |
| `CUBE_WEB_PORT` | `$PORT`, else `8000` | Render sets `PORT` |
| `CUBE_ENGINE_HOST` / `CUBE_ENGINE_PORT` | `127.0.0.1` / `9999` | same |
| `CUBE_ALLOWED_ORIGINS` | `*` | `*` (tightened in Phase 12) |
| `DATABASE_URL` | not set: SQLite file `data/cube.db` | required: Neon connection string |
| `CUBE_DATA_DIR` | `./data` | `./data` |
| `CUBE_DATASET_ENABLED` | on | off |
| `CUBE_DATASET_DIR` | `./ml/data` | `./ml/data` |

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `1` … `9` | jump to a page |
| `Space` | play / pause solution playback |
| `←` `→` | step one move |
