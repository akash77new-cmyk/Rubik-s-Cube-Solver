<div align="center">

<img src="assets/brand/logo.svg" width="92" alt="CubeSolver logo" />

# Real-Time Rubik's Cube Solver

**An end-to-end computer-vision pipeline that scans a physical 3×3 Rubik's Cube with a webcam
and solves it with the Kociemba two-phase algorithm — wrapped in a real desktop-class UI.**

`Python` · `OpenCV` · `NumPy` · `React` · `TypeScript` · `Socket programming`

</div>

---

## What it does

Point a webcam at each face of a scrambled cube. The vision pipeline segments the stickers by
HSV colour, builds a validated 54-facelet cube state, feeds it to the Kociemba two-phase
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
| **Kociemba two-phase solver** | Pluggable backend: the native C extension when installed, otherwise Kociemba's own pure-Python implementation. Solutions are ≤ 20 moves, found in single-digit milliseconds. |
| **Socket-based IPC** | The vision engine runs as its **own OS process** and publishes state and JPEG frames over a length-prefixed TCP protocol. The web server is a pure relay. |
| **Real-time synchronisation** | One Socket.IO connection mirrors the engine snapshot into React. Every page reads the same state; every action is a single command going the other way. |
| **Analytics** | Persisted solve history: move counts, search times, execution times, move distribution and running detection accuracy. |

---

## Quick start

```bash
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
Six faces captured in `U → R → F → D → L → B` order. Auto-capture fires when a read is stable
across consecutive frames. Each face tile fills in as it lands, and a colour census verifies
nine of every colour before the solver is allowed to run.

![Scanner](docs/screenshots/03-scanner.png)

### 4 · Cube State Visualizer
A real 3×3×3 stack of 26 CSS-3D cubies — drag to orbit, scroll to zoom, hover a face to
highlight it — beside the unfolded net. Switch to **Edit** to repaint any sticker that was read
under a glare, or apply turns manually to exercise the move simulation.

![Cube Viewer](docs/screenshots/04-cube-viewer.png)

### 5 · Solution Visualizer
Current / previous / next move, the full sequence as clickable badges, play · pause · step ·
restart · speed, and the 3D cube **animating the actual layer turn** after every move.
"Camera guidance" overlays the rotation arrow onto the live feed instead.

![Solution](docs/screenshots/05-solution.png)

### 6 · Analytics
Solution time, move count, average solve time, total cubes solved, current solver backend and
detection accuracy. Plus the solve timeline, move distribution per face, turn-type split and a
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
speed, theme and the cube palette. Everything persists to `data/settings.json` and applies to
the running engine immediately.

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
  config.py            paths + persisted settings
  core/                pure domain logic — no OpenCV, no Flask, no sockets
    cube.py            CubeState: 54 facelets, move simulation, validation
    moves.py           Singmaster notation, metadata, physical-turn expansion
    solver.py          SolverEngine + pluggable Kociemba backends
    color.py           HSV boxes, classification with confidence, profiles
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
    analytics.py       solve history + aggregate statistics
    logbus.py          structured ring-buffer log stream
  server/app.py        Flask + Socket.IO + MJPEG

frontend/src/
  state/AppStore.tsx   one socket → React state, one command channel back
  components/          cube (3D + net), move glyphs, charts, ui primitives
  pages/               the nine screens

tools/
  generate_assets.py   generates every SVG in assets/
  rasterize.mjs        SVG → high-resolution PNG (sharp)
  screenshots.mjs      captures docs/screenshots (puppeteer)
  verify.py            end-to-end check of the whole pipeline

python code files/     original CLI entry points, now thin wrappers over backend/
```

---

## Command-line tools

The original terminal workflow still works and now shares all its logic with the web app:

```bash
python "python code files/cube_solver.py"      # scan + solve in an OpenCV window
python "python code files/cube_viewer.py"      # net viewer, subscribes to the engine
python "python code files/hsv_calibrator.py"   # trackbar calibration, saves real profiles
```

---

## Verifying it works

```bash
python tools/verify.py
```

Runs the whole stack headlessly and checks: cube-model correctness over random scrambles,
solver output verified by replaying it, socket framing across split TCP chunks, HSV
classification on a synthetic cube face, and a full scramble → solve → playback → analytics
round trip over Socket.IO.

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

| File | Contents |
|---|---|
| `data/settings.json` | camera, detection, overlay, playback, theme |
| `data/hsv_profiles.json` | user-saved HSV profiles |
| `data/solve_history.json` | persisted solve records |
| `.cache/twophase/` | generated pruning tables (safe to delete; rebuilt on demand) |

Ports are overridable with `CUBE_WEB_PORT`, `CUBE_ENGINE_PORT`, `CUBE_ENGINE_HOST`.

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `1` … `9` | jump to a page |
| `Space` | play / pause solution playback |
| `←` `→` | step one move |
