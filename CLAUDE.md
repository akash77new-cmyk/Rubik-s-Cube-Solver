# CLAUDE.md

Guide for Claude Code in this repository. Read it at the start of every session.

## 1. Project

**AI-Powered Rubik's Cube Solver & Tutor.** A web app that scans a physical 3×3 cube with a
camera (OpenCV), solves it (Kociemba two-phase), and is being extended phase by phase with AI
features: a tool-calling repair agent, an LLM tutor, a RAG coach and a trained colour classifier.

The owner, **Akash**, is a student who will present this project in internship interviews
(AI / ML / software engineering). So:

- **He must be able to explain every line.** Prefer clear code over clever code.
- **Explain your work in simple, direct English, step by step.** Short sentences; define any
  technical term in one line the first time you use it.
- **Everything shown must really work.** No fake data, no placeholder numbers in the UI, no
  mocked feature presented as real.

## 2. How to work here

1. **One phase at a time.** Each phase has a spec in `docs/phases/PHASE_<n>.md`. Read the whole
   spec before changing anything. Never start work that belongs to a later phase.
2. **Plan first.** List the files you will create or change and why, then implement in small steps.
3. **Don't break what works.** Scan, solve, playback, analytics, calibration, settings and logs
   must keep working. Change behaviour only where the spec says so.
4. **Test everything.** New logic gets `pytest` tests in `tests/`. Before finishing a task, run
   `pytest` and `python tools/verify.py`; both must pass.
5. **Follow the existing style:** type hints, dataclasses, small focused modules, docstrings that
   explain *why*, `logging` instead of `print` (except CLI banners).
6. **Configuration comes from environment variables**, read in `backend/config.py` and documented
   in `.env.example`. Never hard-code secrets. Never commit `.env`.
7. **Ask Akash first** before deleting files, adding a large dependency, or changing the
   architecture beyond the spec.
8. **Finish each phase by:** ticking its "Done when" checklist, updating the roadmap (section 8),
   and writing a short summary: what changed, why, and how to test it.
9. **Git:** work on the branch `phase-<n>-<name>`, with small commits and clear messages.

## 3. Architecture

```
browser  (React + TypeScript, frontend/)
   │  Socket.IO (WebSocket) · MJPEG stream · REST
   ▼
web server   (process 2)   backend/server/app.py     Flask + Flask-SocketIO, a pure relay
   │  TCP 127.0.0.1:9999, length-prefixed frames ('J' = JSON, 'F' = JPEG)
   ▼
vision engine (process 1)  backend/engine.py         single source of truth
   • SolveSession     backend/services/session.py   state machine: scan → solve → playback
   • CameraStream     backend/vision/camera.py      threaded webcam capture
   • FaceDetector     backend/vision/detector.py    HSV sampling, confidence, stability
   • OverlayRenderer  backend/vision/overlay.py     HUD drawn into frames
   • SolverEngine     backend/core/solver.py        Kociemba: C backend, else pure Python
   • cubie model      backend/core/cubie.py         piece model, twist / flip / parity, in_g1
   • issues           backend/core/validation.py    structured validation issues
   • scanning         backend/core/scanning.py      scan guide, centre-based face identity, orientation repair
   • DatasetStore     backend/services/dataset.py   confirmed scans → labelled crops
   • AIService        backend/ai/service.py         the AI assistant: Gemini, tools, traces (Phase 4)
   • stores           backend/services/settings.py, profiles.py, analytics.py
   │                  memory copy for reads, written through to the database
   ▼  SQLAlchemy (psycopg 3)
database   Neon PostgreSQL in production · SQLite file data/cube.db locally (DATABASE_URL)
           backend/db/: database.py (engine, transactions, status) · models.py (tables)
           · migrate.py + migrations/ (Alembic, applied by the engine at start-up)
```

- **Command flow:** the UI emits `command` with `{command, payload}` → the server relays it to the
  engine → `SolveSession.handle_command()` → `_dispatch()` → the session broadcasts a new `state`
  snapshot (plus narrower events: `detection`, `analytics`, `log`, `solver`).
- **Adding a feature** usually means: pure logic in `backend/core/` · a command in
  `SolveSession._dispatch()` · fields in `snapshot()` · types in `frontend/src/lib/types.ts` ·
  UI in `frontend/src/pages/` and `frontend/src/components/`.
- `backend/core/` stays pure: no OpenCV, no Flask, no sockets, no file or network I/O.
- **Persistence:** the database in `DATABASE_URL` (see section 3a). `ml/data/` (training scans)
  stays as files in git.
- **Production:** `python run.py --prod` runs the engine + gunicorn (`backend/server/wsgi.py`,
  `gunicorn.conf.py`) in one container (`Dockerfile`, `render.yaml`).

### 3a. Database rules (Phase 3)
- Only the **engine process** (and the CLI tools) open the database. The web server stays a pure
  relay and never imports `backend.db`.
- Stores keep a **memory copy** and write **through** to the database: database first, memory
  only after the commit succeeds. Reads never touch the network, so `snapshot()` and the frame
  thread never wait for Neon. No database call ever runs on the frame thread.
- Every read/write goes through `Database.transaction("what")`. A failure becomes a
  `StorageError` with a plain message; the session logs it, sends `storage:error` (a "Not saved"
  toast) and the Settings page shows it. Never swallow it silently.
- Schema changes: change `backend/db/models.py` **and** add a migration
  (`python -m alembic revision --autogenerate --rev-id 000N -m "..."`, then tidy it).
  `test_models_match_the_migrations` enforces this. Never edit a migration that has run on Neon.
- Migrations never import app code (UTCDateTime is written as `sa.DateTime(timezone=True)`).
- Timestamps are timezone-aware UTC (`UTCDateTime`); `SolveRecord` keeps Unix seconds for the UI.
- Never print or log `DATABASE_URL` (it contains a password). `Database.status()` and
  `public_error()` show only the database name and the host, with Neon's endpoint id hidden
  (the live site is public). Tests never use `.env`'s `DATABASE_URL`; Postgres tests need
  `CUBE_TEST_POSTGRES_URL` pointing at a throwaway server (never Neon).

### Cube conventions
- Faces in order `U R F D L B`. Each face stores 9 stickers in reading order; index 4 is the centre.
- Colour codes `W Y R O G B`. Centre colours define the scheme (default: U=W, R=R, F=G, D=Y, L=O, B=B).
- `CubeState.to_facelet_string()` maps colours to faces via the centres, giving Kociemba's 54-char
  `URFDLB` facelet string.
- `CubeState` is immutable: `apply()` returns a new state.
- `validate()` returns `ValidationResult.issues`. Each issue has a `code` (`IssueCode`), `message`,
  `stickers`, `pieces` and `details`. Code that reacts to problems (e.g. the Phase 5 agent) must use
  `code` and `details`, never parse `message`.
- Each camera-captured face in `_scanned` has `stickers`: what the detector saw (`color`,
  `confidence`, `alternatives` = best three, `hsv`, `uncertain`). `colors` holds the current,
  possibly corrected colours. Crops live only in `SolveSession._scan_crops` and on disk.
- Camera faces are stored as seen from outside, in the model's reading orientation (sides with U
  on top, U with B on top, D with F on top). A mirrored preview is un-mirrored in
  `capture_face()`. A face is identified by its centre colour (`face_for_center`).
- Capture is manual by default (`SolveSession._auto_capture = False`). Auto-capture waits until a
  side has been held still for `Settings.auto_capture_hold_ms` (default 1000). Tests that need
  auto-capture enable it with `scan.auto`, and replace `SolveSession._clock` with a fake clock.
- Moves are explained for a cube held with F facing the user and U on top, all seen from there
  (the cube is never turned around): `Move.arrow` (which way the layer moves; B spins
  counter-clockwise from the front for "B clockwise") and `Move.instruction` (plain English).
  Tests check both against the cube model; reuse them instead of writing new move descriptions.
- Playback starts with a "hold the cube like this" step: `playback.ready` is False until the
  first `next` or `play`; `prev` from move 1 goes back to it. Auto play shows each move for
  `Settings.autoplay_interval_ms` (default 8000), independent of `animation_speed`.

## 4. AI design rules (from Phase 4 on)
These rules are enforced by code and tests since Phase 4 (`backend/ai/`, see 4a).
1. The LLM never produces cube moves or cube state. Solvers produce moves; the validator decides validity.
2. Code computes; the LLM chooses, plans and explains. Every number shown to users is computed in code.
3. LLM output that drives the UI is structured JSON, validated in code before use.
4. Every AI feature has a non-AI fallback. The app must work with no API key or when the quota runs out.
5. AI code in `backend/ai/` receives what it needs as arguments: no global state.
6. Agents have a tool allowlist, a step limit and validated tool arguments, and every step is traced.
7. An AI suggestion that changes the user's cube needs the user's confirmation.
8. Privacy: never send full camera frames or personal data to external APIs (only sticker crops).
9. LLM calls never run on the camera/frame thread.
10. Tests never call real APIs; they use a fake LLM client.

### 4a. How the AI layer works (Phase 4)
- `AIService` (engine) runs each question in a background thread and publishes `ai:progress`,
  `ai:answer` and `ai:status`. The session only calls `ask()`; the UI page is `AssistantPage.tsx`.
- The agent loop (`agent.py`) uses Gemini's mode ANY: the model must call a tool every turn and
  answers by calling `final_answer`, whose arguments are checked against the answer schema.
  `final_answer` is refused if it comes in the same turn as other tools (read results first).
- A new tool = a `Tool(name, description, parameters, handler)` in the feature's registry, plus
  its name in the allowlist. Handlers return a JSON object; problems are `{"error": ...}`.
  Schemas use only the keywords in `schema.py`. Tools never change the cube (rule 7): a tool
  may return a *proposal*, which the UI applies only after the user confirms.
- Every model request goes through `BudgetedLLM` (per-minute and per-day limits, refilled from
  the trace table after a restart). Every run is traced in `ai_runs` / `ai_steps`.
- Any `LLMError` or `AgentStopped` becomes the feature's built-in answer, with the reason shown.
- Gemini 3 needs each model turn sent back unchanged (thought signatures): keep `Message.raw`.
- Never log or print `GEMINI_API_KEY`; it is sent only in the `x-goog-api-key` header.
- Tests: `ScriptedLLM` (`fake.py`) for unit tests; `tools/fake_gemini.py`, a local server as strict
  as Gemini 3 (key header, mode ANY, thought signatures), for end-to-end tests without a key.

## 5. Deployment constraints (Render free tier)
- **512 MB RAM, 0.1 CPU.** Phase 0 baseline is about 160 MB for all processes. Measure memory
  when adding heavy dependencies. Phase 3 (SQLAlchemy, Alembic, psycopg) adds about 50 MB to
  the engine.
- Sleeps after 15 min idle (about 1 min to wake). **The disk is temporary:** runtime files vanish
  on restart or redeploy.
- One gunicorn worker with threads: Socket.IO state lives in memory, so never add workers.
- Production solver: `kociemba` (C) from `requirements-prod.txt`. The pure-Python fallback needs
  large tables; don't rely on it in production.
- **Until Phase 9 the live site has one shared session for every visitor.**
- Keep per-frame server work light (0.1 CPU).
- Dataset collection is off in production (`CUBE_DATASET_ENABLED`); `ml/data/` is committed to git.
- **Database: Neon free tier** (Singapore, same region as Render). `DATABASE_URL` = the
  `production` branch's direct connection string (pooling off); it is required in production and
  set only in the Render dashboard. Neon sleeps after 5 idle minutes: the pool pings each
  connection before use, and start-up retries the first connection.
- **AI: Gemini free tier.** `GEMINI_API_KEY` is optional and set only in the Render dashboard.
  The app's own limits (`AI_REQUESTS_PER_MINUTE` / `AI_REQUESTS_PER_DAY`, default 10 / 200) stay
  below Google's (see AI Studio). Google may use free-tier prompts to improve its products, so
  send only cube data, never personal data.

## 6. Commands
| What | Command |
|---|---|
| Install app | `python -m pip install -r requirements.txt` |
| Install dev tools | `python -m pip install -r requirements-dev.txt` |
| Build UI | `cd frontend && npm ci && npm run build` |
| Run locally | `python run.py` |
| UI hot reload | `python run.py --dev` and `cd frontend && npm run dev` |
| Unit tests | `pytest` |
| Pipeline check | `python tools/verify.py` |
| Live check (app running) | `python tools/verify.py --live` (add `--expect-db postgresql` to require Postgres, `--expect-ai gemini` to require a real AI answer) |
| AI end to end, no key | `python tools/fake_gemini.py`; app with `GEMINI_API_KEY=test-key GEMINI_BASE_URL=http://127.0.0.1:8799/v1beta`; then `python tools/verify.py --live --expect-ai gemini` |
| DB tests on Postgres | `CUBE_TEST_POSTGRES_URL=postgresql://postgres:cube@127.0.0.1:5433/cube_test pytest` (Docker container `cube-pg`, see README) |
| Migrations | `python -m alembic current` · `python -m alembic upgrade head --sql` (print SQL) |
| Production mode (Linux) | `APP_ENV=production FLASK_SECRET_KEY=x python run.py --prod` |
| Docker | `docker build -t cube-solver .` then `docker run --rm -p 8000:8000 -e PORT=8000 -e FLASK_SECRET_KEY=dev -e DATABASE_URL=... cube-solver` |

`requirements-prod.txt` is for Linux/Docker only (kociemba needs a C compiler).

## 7. Files you should not touch without a reason
- `backend/core/cube.py` face-cycle tables (`_EDGE_CYCLES`): known correct, verified by tests.
- `backend/ipc/protocol.py` framing: the engine and the server both depend on it.
- `tools/verify.py`: the end-to-end smoke test; extend it, don't weaken it.
- `backend/db/migrations/versions/*`: a migration that has run on Neon is history; add a new one.

## 8. Roadmap
| Phase | Goal | Status |
|---|---|---|
| 0 | Foundation + first deploy | ✅ |
| 1 | Full cube validation: cubie model, twist / flip / parity, structured errors | ✅ |
| 2 | Per-sticker detection data + dataset collection | ✅ |
| 2B | Guided scanning: centre-based face identity, un-mirroring, orientation repair | ✅ |
| 3 | Database: Neon Postgres, SQLAlchemy, Alembic (pgvector available for Phase 7) | ✅ |
| 4 | AI foundation: LLM client, tool registry, tracing, fallbacks | ⬜ |
| 5 | Smart Repair Agent | ⬜ |
| 6 | Beginner (layer-by-layer) solver + solution stages | ⬜ |
| 7 | Lessons + RAG Coach | ⬜ |
| 8 | AI Tutor | ⬜ |
| 9 | Accounts + multi-user sessions | ⬜ |
| 10 | Browser camera | ⬜ |
| 11 | Trained colour classifier + vision-LLM fallback | ⬜ |
| 12 | Launch: tests, CI, eval report, security pass, docs | ⬜ |
| 13 | Stretch: Practice mode + Learning Path agent | ⬜ |
