# AI evaluation: live (real Gemini)

Run 2026-10-24 23:27 on commit `9495ed8` with `gemini-3.5-flash-lite` and `gemini-embedding-001`.
Made by `python tools/eval_ai.py --live` (by hand: it uses the real API).

## Retrieval with real embeddings

| recall@1 | recall@3 | MRR |
| --- | --- | --- |
| 15/15 | 15/15 | 1.0 |

## Coach (RAG answers)

| Questions | Answered by Gemini | Cites the expected section | Accepted first try | Out-of-scope refused | p50 / p95 |
| --- | --- | --- | --- | --- | --- |
| 15 | 15 | 15 | 15 | 3/3 | 9.8 s / 28.2 s |

Every accepted citation is one the search returned in that run: code rejects any other.
Times are the model's own: the run's pacing waits (to stay under the free limits) are left out.

## Repair agent vs the built-in search

Per kind of camera evidence: 1 case with one misread sticker and 2 ambiguous cases (two misread stickers, more than one valid fix).

| Camera evidence | Cases | Agent picked the true fix | Agent asked for a rescan | Agent picked a wrong fix | Built-in pick right |
| --- | --- | --- | --- | --- | --- |
| unsure | 3 | 3 | 0 | 0 | 3 |
| fairly sure | 3 | 3 | 0 | 0 | 3 |
| sure (no hint) | 3 | 1 | 0 | 2 | 1 |

9 of 9 proposals came from Gemini (the rest: the built-in search after a timeout or a limit). A wrong fix is the costly mistake; a rescan is the safe one.

## Repair agent with the vision check (Phase 11)

The 6 ambiguous misreads again, now with 32 x 32 images of the stickers (simulated daylight, warm bulb and dim light), so the agent can call look_at_stickers.

| Cases | Answered by Gemini | Agent looked | Agent picked the true fix | Agent asked for a rescan | Agent picked a wrong fix |
| --- | --- | --- | --- | --- | --- |
| 6 | 6 | 6 | 5 | 1 | 0 |

Without the images (the table above), the agent picked the true fix in 4 of these 6 cases.

## Tutor hints

| Hints | Answered by Gemini | Accepted first try | Hint 1 with moves | Median words | p50 / p95 |
| --- | --- | --- | --- | --- | --- |
| 12 | 12 | 12 | 0 | 33 | 7.7 s / 11.5 s |

"Accepted first try" = code's checks passed on the model's first answer (a lesson search before it is a normal step); otherwise the model fixed it after the rejection. Hint 1 can never show moves: code rejects them.
