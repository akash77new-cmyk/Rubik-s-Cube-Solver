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
```

- **Command flow:** the UI emits `command` with `{command, payload}` → the server relays it to the
  engine → `SolveSession.handle_command()` → `_dispatch()` → the session broadcasts a new `state`
  snapshot (plus narrower events: `detection`, `analytics`, `log`, `solver`).
- **Adding a feature** usually means: pure logic in `backend/core/` · a command in
  `SolveSession._dispatch()` · fields in `snapshot()` · types in `frontend/src/lib/types.ts` ·
  UI in `frontend/src/pages/` and `frontend/src/components/`.
- `backend/core/` stays pure: no OpenCV, no Flask, no sockets, no file or network I/O.
- **Persistence today:** JSON files in `data/` (moves to Postgres in Phase 3).
- **Production:** `python run.py --prod` runs the engine + gunicorn (`backend/server/wsgi.py`,
  `gunicorn.conf.py`) in one container (`Dockerfile`, `render.yaml`).

### Cube conventions
- Faces in order `U R F D L B`. Each face stores 9 stickers in reading order; index 4 is the centre.
- Colour codes `W Y R O G B`. Centre colours define the scheme (default: U=W, R=R, F=G, D=Y, L=O, B=B).
- `CubeState.to_facelet_string()` maps colours to faces via the centres, giving Kociemba's 54-char
  `URFDLB` facelet string.
- `CubeState` is immutable: `apply()` returns a new state.

## 4. AI design rules (from Phase 4 on)
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

## 5. Deployment constraints (Render free tier)
- **512 MB RAM, 0.1 CPU.** Phase 0 baseline is about 160 MB for all processes. Measure memory
  when adding heavy dependencies.
- Sleeps after 15 min idle (about 1 min to wake). **The disk is temporary:** runtime files vanish
  on restart or redeploy.
- One gunicorn worker with threads: Socket.IO state lives in memory, so never add workers.
- Production solver: `kociemba` (C) from `requirements-prod.txt`. The pure-Python fallback needs
  large tables; don't rely on it in production.
- **Until Phase 9 the live site has one shared session for every visitor.**
- Keep per-frame server work light (0.1 CPU).

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
| Live check (app running) | `python tools/verify.py --live` |
| Production mode (Linux) | `APP_ENV=production FLASK_SECRET_KEY=x python run.py --prod` |
| Docker | `docker build -t cube-solver .` then `docker run --rm -p 8000:8000 -e PORT=8000 -e FLASK_SECRET_KEY=dev cube-solver` |

`requirements-prod.txt` is for Linux/Docker only (kociemba needs a C compiler).

## 7. Files you should not touch without a reason
- `backend/core/cube.py` face-cycle tables (`_EDGE_CYCLES`): known correct, verified by tests.
- `backend/ipc/protocol.py` framing: the engine and the server both depend on it.
- `tools/verify.py`: the end-to-end smoke test; extend it, don't weaken it.

## 8. Roadmap
| Phase | Goal | Status |
|---|---|---|
| 0 | Foundation + first deploy | ✅ |
| 1 | Full cube validation: cubie model, twist / flip / parity, structured errors | ⬜ |
| 2 | Per-sticker detection data + dataset collection | ⬜ |
| 3 | Database: Neon Postgres, SQLAlchemy, Alembic, pgvector | ⬜ |
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
