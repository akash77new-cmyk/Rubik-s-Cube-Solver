# AI evaluation: offline

Run 2026-10-23 12:23 on commit `50e47c4`, with no API key (test embeddings and scripted models).
Made by `python tools/eval_ai.py`; CI runs it on every push. All gates: pass.

## 1. Retrieval (RAG search)

15 labelled questions over 37 lesson sections. Gate: recall@3 >= 13 for both (pass).

| Search | recall@1 | recall@3 | MRR |
| --- | --- | --- | --- |
| Keywords (BM25) | 13/15 | 14/15 | 0.91 |
| Test embeddings (word hashing) | 14/15 | 14/15 | 0.933 |

Missed at 3: How does the Kociemba solver find a solution?.

## 2. Repair search (misread stickers)

Simulated scans of real cubes with misread stickers. The camera's evidence on a misread sticker: *unsure* (51%, the true colour its 2nd guess), *fairly sure* (80%, the true colour a weak 2nd guess) or *sure* (90%, the true colour not among its guesses). Gate: the true fix is always found, and the built-in pick is right in >= 95% of the unsure cases (pass).

| Misread | Cases | True fix found | Only one valid fix | Built-in pick right: unsure / fairly sure / sure |
| --- | --- | --- | --- | --- |
| one sticker | 10 | 10 | 10 | 10 / 10 / 10 |
| two stickers | 10 | 10 | 10 | 10 / 10 / 10 |
| two, ambiguous | 10 | 10 | 0 | 10 / 10 / 3 |

The cube's invariants are strict: one or two misread stickers almost always leave exactly one valid fix. Only in the rare ambiguous cases does the camera's evidence decide, and with no evidence the built-in search can pick a wrong fix; the agent may ask for a rescan instead (see the live report).

## 3. Beginner method (Solve & Learn)

Gate: every cube solved, stages in order, at most 3 algorithms per yellow stage (pass).

| Cubes | Solved | Stages in order | Moves (min / median / max) | Max algorithms per yellow stage | Slowest step |
| --- | --- | --- | --- | --- | --- |
| 100 | 100 | 100 | 90 / 134 / 185 | 3 | 20.9 ms |

## 4. Guardrails

Misbehaving model answers; code must catch each one. 12/12 caught (pass).

| Case | Result |
| --- | --- |
| repair: a fix id the search never returned | pass |
| repair: a rescan without a side | pass |
| repair: a real fix id is accepted | pass |
| coach: a citation the search didn't return | pass |
| coach: a covered answer with no citation | pass |
| tutor: moves in hint 1 | pass |
| tutor: a made-up move sequence | pass |
| tutor: a lesson algorithm is accepted | pass |
| agent: an unknown tool gets an error, then the answer counts | pass |
| agent: final_answer next to another tool is refused | pass |
| agent: an answer that breaks the schema is sent back | pass |
| agent: a model that never answers is stopped | pass |

## 5. Fallbacks (AI off)

With no API key, every feature must still answer (pass).

| Feature | Valid built-in answer |
| --- | --- |
| assistant | pass |
| repair agent | pass |
| coach | pass |
| tutor | pass |
