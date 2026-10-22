"""Solve & Learn (Phase 8): one learner solving their own cube with the beginner method.

The learner scans once, then solves their real cube stage by stage. The app can't see
the cube after the scan, so the learner taps every move they make on the real cube
(the move pad), or follows the moves the app shows ("Show me"). Either way this class
knows the exact cube at every moment:

    cube now = the scanned cube + every action so far (a move, or turning the cube over)

Code decides everything about the cube (AI rule 1): the stage, whether a stage is done,
the next step and its moves (``backend/core/beginner.py``). The AI tutor only explains:
its hints and answers are stored here as text (``set_hint``, ``set_answer``, ``set_recap``).

Pure state, no I/O and no threads: the session calls it under its lock.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.core import beginner
from backend.core.beginner import STAGES, Step, current_stage, next_step
from backend.core.cube import CubeState
from backend.core.moves import Move, invert_sequence

TURN_OVER = "turn_over"
#: Hints come in three levels: 1 what to look at, 2 which algorithm, 3 the exact moves.
MAX_HINT = 3


class LearnError(ValueError):
    """A learn command that can't be done right now (the message is for the user)."""


class LearnSession:
    def __init__(self, cube: CubeState, clock: Callable[[], float] = time.monotonic) -> None:
        if not cube.validate().ok:
            raise LearnError("Scan a valid cube first")
        self.id = uuid.uuid4().hex[:10]
        self._clock = clock
        self._states: List[str] = [cube.to_color_string()]  # the cube after each action
        self._actions: List[str] = []
        self._completed: List[List[int]] = []  # the stages each action finished (Undo un-finishes them)
        #: Counts every change (moves, undo, turning over), so the UI animates each move once.
        self.version = 0
        self._animate: Optional[str] = None  # the move just made, for the 3D turn (None after undo)
        self.ready = False  # True once the learner confirms how they hold the cube
        self._guide: List[str] = []  # moves still to do from "Show me" (or hint 3)
        self._guide_all: List[str] = []  # all the moves that were shown
        self._guide_task = ""  # what those moves do
        self._guide_stage = 0  # the stage those moves finish: the guide stops once it is done
        self._hint_level = 0
        self._hint_texts: Dict[int, Dict[str, Any]] = {}  # level -> {"text", "source", "model"}
        self._hint_key: Optional[Tuple[Any, ...]] = None
        start_stage = current_stage(self.state)
        self._stats: Dict[int, Dict[str, Any]] = {
            stage.number: {"hints": 0, "shown": 0, "moves": 0, "seconds": 0.0,
                           "done": stage.number < start_stage, "alone": True}
            for stage in STAGES
        }
        self._stage = start_stage
        self._stage_started = clock()
        self.note: Optional[str] = None  # a comment on the last move, from code
        self.just_done: Optional[int] = None  # the stage the last action finished
        self.answer: Optional[Dict[str, Any]] = None  # the tutor's latest answer to a question
        self.recap: Optional[Dict[str, Any]] = None
        self.tutor_busy = False
        self._step_cache: Tuple[str, Optional[Step]] = ("", None)
        self._reset_hints()

    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._states[-1]

    @property
    def start_cube(self) -> CubeState:
        """The cube as scanned (for Restart)."""
        return CubeState.from_color_string(self._states[0])

    @property
    def stage(self) -> int:
        return self._stage

    @property
    def solved(self) -> bool:
        return self._stage == 8

    @property
    def working_stage(self) -> int:
        """The stage the learner is working on: the first one not finished yet (8 = all done).

        ``stage`` is what the stickers show right now, and it drops for a moment in the
        middle of most algorithms (the white layer comes apart, then back). The stage
        bar, the page title and the stats follow this one instead, so they don't jump back.
        """
        return next((s.number for s in STAGES if not self._stats[s.number]["done"]), 8)

    def step(self) -> Optional[Step]:
        """The next step for the cube as it is now (computed once per cube)."""
        if self._step_cache[0] != self.state:
            step = next_step(self.state)
            if step is not None and step.kind == "turn_over" and self.state[4] == "Y":
                step = self._undo_step() or step
            self._step_cache = (self.state, step)
        return self._step_cache[1]

    def _undo_step(self) -> Optional[Step]:
        """The white layer came apart after turning over: undo back to where it was whole.

        The method never turns the cube back, so instead of "turn it over" the step is the
        exact moves that undo everything since the white layer was last complete.
        """
        for index in range(len(self._states) - 1, -1, -1):
            state = self._states[index]
            if state[4] == "Y" and current_stage(state) >= 3:
                since = self._actions[index:]
                if not since or TURN_OVER in since:
                    return None
                moves = beginner.simplify([m.notation for m in invert_sequence(Move.parse(a) for a in since)])
                stage = current_stage(self.state)
                return Step(
                    stage, "moves", tuple(moves),
                    task=(f"Your white layer came apart. Undo the last {len(since)} move(s) to get it back, "
                          "then carry on."),
                    look="The white layer is at the bottom now. It was complete before your last moves.",
                    how=f"Undo them in reverse order: {' '.join(moves)}. Or press Undo {len(since)} time(s).",
                    focus=tuple(f"D{i}" for i in range(9)),
                )
        return None

    @property
    def hint_level(self) -> int:
        return self._hint_level

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def set_ready(self) -> None:
        self.ready = True

    def move(self, name: str) -> None:
        """The learner turned their real cube (move pad, keyboard, or the next guided move)."""
        if name not in beginner.MOVE_NAMES:
            raise LearnError(f"Unknown move: {name}")
        self._need_ready()
        if self.solved:
            raise LearnError("The cube is solved")
        if self._guide and self._guide[0] == name:
            self._guide.pop(0)
            following = True
        else:
            self._guide = []  # the learner went their own way: stop guiding
            following = False
        self._stats[min(self.working_stage, 7)]["moves"] += 1
        self._push(name, beginner.turn(self.state, [name]))
        broke = self._after_change()
        if following and self._guide and self._stage > self._guide_stage:
            # The shown moves finished their stage (or solved the cube) before their end:
            # the corner trick's last D, for example. Stop here instead of asking for
            # moves that are no longer needed.
            self._guide = []
            self._reset_hints()
        if broke is not None and not following:
            self.note = (f"That move broke your {broke.lower()}. Press Undo, or keep going if you are in "
                         "the middle of an algorithm.")

    def turn_over(self) -> None:
        """The learner turned the whole cube over (asked for between stages 2 and 3)."""
        self._need_ready()
        if self._guide:
            raise LearnError("Finish the moves shown first")
        step = self.step()
        if step is None or step.kind != "turn_over":
            raise LearnError("Keep holding the cube this way for now")
        self._guide = []
        self._push(TURN_OVER, beginner.turn_over(self.state))
        self._after_change()

    def undo(self) -> None:
        if not self._actions:
            raise LearnError("Nothing to undo")
        self._actions.pop()
        self._states.pop()
        for number in self._completed.pop():  # the stages that action finished are not done any more
            self._stats[number]["done"] = False
        self.version += 1
        self._animate = None
        self._guide = []
        self._after_change(undo=True)

    def show(self) -> None:
        """'Show me': reveal the step's moves and guide the learner through them."""
        step = self._current_moves_step()
        self._hint_level = MAX_HINT
        self._start_guide(step)
        self._stats[min(self.working_stage, 7)]["shown"] += 1
        self._stats[min(self.working_stage, 7)]["alone"] = False

    def hint(self) -> int:
        """The next hint level (1-3). Level 3 shows the moves, like 'Show me'."""
        step = self._current_moves_step()
        if self._hint_level >= MAX_HINT:
            return MAX_HINT
        self._hint_level += 1
        self._stats[min(self.working_stage, 7)]["hints"] += 1
        self._stats[min(self.working_stage, 7)]["alone"] = False
        if self._hint_level == MAX_HINT:
            self._start_guide(step)
        else:  # the built-in text at once; the tutor's words replace it when they arrive
            text = step.look if self._hint_level == 1 else step.how
            self._hint_texts[self._hint_level] = {"text": text, "source": "built-in", "model": None}
        return self._hint_level

    def set_hint(self, level: int, step_key: Tuple[Any, ...], text: str, source: str, model: Optional[str]) -> bool:
        """Store the tutor's hint, unless the learner has moved on to another step meanwhile."""
        if step_key != self._hint_key or level > self._hint_level:
            return False
        self._hint_texts[level] = {"text": text, "source": source, "model": model}
        return True

    def set_answer(self, answer: Dict[str, Any]) -> None:
        self.answer = answer

    def set_recap(self, recap: Dict[str, Any]) -> None:
        self.recap = recap

    # ------------------------------------------------------------------
    def step_key(self) -> Tuple[Any, ...]:
        """What the current hints are about: the stage and the piece (or algorithm)."""
        step = self.step()
        if step is None:
            return (8,)
        return (step.stage, step.kind, step.piece or step.algorithm)

    def _current_moves_step(self) -> Step:
        self._need_ready()
        step = self.step()
        if step is None:
            raise LearnError("The cube is solved")
        if step.kind != "moves":
            raise LearnError("Turn the cube over first")
        return step

    def _start_guide(self, step: Step) -> None:
        """Show the step's moves one at a time ("Show me", or hint 3)."""
        self._guide = list(step.moves)
        self._guide_all = list(step.moves)
        self._guide_task = step.task
        # The stage these moves finish. With yellow on top, a stage 1-2 step can only be the
        # "undo these moves" step: it is done when the white layer is whole again (stage 3).
        self._guide_stage = 2 if self.state[4] == "Y" and step.stage < 3 else step.stage

    def _need_ready(self) -> None:
        if not self.ready:
            raise LearnError("First hold the cube as shown, then press the button below it")

    def _push(self, action: str, state: str) -> None:
        self._actions.append(action)
        self._states.append(state)
        self.version += 1
        self._animate = action if action != TURN_OVER else None

    def _after_change(self, undo: bool = False) -> Optional[str]:
        """Update the stage after an action. Returns the name of a stage it broke, if any."""
        self.note = None
        self.just_done = None
        new = current_stage(self.state)
        broke = None
        finished: List[int] = []
        if new > self._stage:
            now = self._clock()
            for number in range(self._stage, new):
                stats = self._stats[number]
                if not stats["done"]:
                    stats["done"] = True
                    stats["seconds"] = round(stats["seconds"] + now - self._stage_started, 1)
                    self.just_done = number
                    finished.append(number)
            self._stage_started = now
        elif new < self._stage and not undo:
            broke = STAGES[new - 1].name
        if not undo:
            self._completed.append(finished)
        self._stage = new
        # While the learner follows shown moves, the step stays the same. Otherwise a new
        # step, or the end of the shown moves, starts the hints again from level 0.
        if not self._guide and (self.step_key() != self._hint_key or self._hint_level == MAX_HINT):
            self._reset_hints()
        return broke

    def _reset_hints(self) -> None:
        self._hint_key = self.step_key()
        self._hint_level = 0
        self._hint_texts = {}

    # ------------------------------------------------------------------
    # For the tutor (facts it may use) and the UI (the snapshot's "learn" key)
    # ------------------------------------------------------------------
    def facts(self, kind: str) -> Dict[str, Any]:
        """What the tutor is told: only what this kind of request may reveal."""
        step = self.step()
        stage = STAGES[min(self._stage, 7) - 1]
        facts: Dict[str, Any] = {
            "stage": {"number": stage.number, "name": stage.name, "goal": stage.goal},
            "stagesDone": [s.name for s in STAGES if self._stats[s.number]["done"]],
            "solved": self.solved,
            "recentMoves": self._actions[-8:],
            "hintLevel": self._hint_level,
        }
        if step is not None:
            facts["step"] = {"task": step.task, "look": step.look}
            if kind != "hint" or self._hint_level >= 2:
                facts["step"]["how"] = step.how
                if step.algorithm:
                    facts["step"]["algorithm"] = beginner.ALGORITHMS[step.algorithm][0]
                    facts["step"]["algorithmMoves"] = " ".join(step.algorithm_moves)
            if self._hint_level >= MAX_HINT:
                facts["step"]["moves"] = " ".join(step.moves)
        if self.note:
            facts["note"] = self.note
        if kind == "recap":
            facts["stats"] = self.stats()
        return facts

    def allowed_sequences(self, kind: str) -> List[List[str]]:
        """Move sequences the tutor may write (AI rule 1: moves come from code or the lessons)."""
        step = self.step()
        allowed: List[List[str]] = []
        if kind == "hint" and self._hint_level < 2:
            return allowed  # hint 1 says what to look at, never which moves to make
        if step is not None and step.algorithm:
            allowed.append(list(step.algorithm_moves))
        if kind in ("question", "recap"):
            allowed += [beginner.parse_names(notation) for _, notation in beginner.ALGORITHMS.values()]
        if kind == "hint" and step is not None and step.algorithm:
            allowed.append(beginner.parse_names(beginner.ALGORITHMS[step.algorithm][1]))
        if step is not None and self._hint_level >= MAX_HINT:
            allowed.append(list(step.moves))
        return allowed

    def stats(self) -> Dict[str, Any]:
        moves = sum(1 for action in self._actions if action != TURN_OVER)
        helped = [s for s in STAGES if self._stats[s.number]["done"] and not self._stats[s.number]["alone"]]
        most = max(helped, key=lambda s: self._stats[s.number]["hints"] + self._stats[s.number]["shown"], default=None)
        return {
            "moves": moves,
            "stagesAlone": [s.name for s in STAGES if self._stats[s.number]["done"] and self._stats[s.number]["alone"]],
            "stagesWithHelp": [s.name for s in STAGES if self._stats[s.number]["done"] and not self._stats[s.number]["alone"]],
            "hints": sum(stats["hints"] for stats in self._stats.values()),
            "shown": sum(stats["shown"] for stats in self._stats.values()),
            "seconds": round(sum(stats["seconds"] for stats in self._stats.values()), 1),
            "practise": most.name if most else None,  # the stage that needed the most help
        }

    def to_dict(self) -> Dict[str, Any]:
        step = self.step()
        last = self._actions[-1] if self._actions else None
        animate = self._animate
        step_data: Optional[Dict[str, Any]] = None
        if step is not None:
            full = step.to_dict()
            step_data = {key: full[key] for key in ("stage", "kind", "task", "piece", "focus")}
            if step.kind == "turn_over":
                step_data["how"] = step.how
            if self._hint_level >= 2:
                step_data.update(algorithm=full["algorithm"], algorithmNotation=full["algorithmNotation"])
            if self._hint_level >= MAX_HINT:
                step_data.update(moves=full["moves"], notation=full["notation"])
        working = self.working_stage
        return {
            "id": self.id,
            "ready": self.ready,
            "stage": self._stage,
            "working": working,
            "solved": self.solved,
            "top": self.state[4],
            "front": self.state[22],
            "cube": CubeState.from_color_string(self.state).facelets,
            "version": self.version,
            "previous": CubeState.from_color_string(self._states[-2]).facelets if animate else None,
            "lastMove": Move.parse(animate).to_dict() if animate else None,
            "lastAction": last,
            "moveCount": sum(1 for action in self._actions if action != TURN_OVER),
            "history": self._actions[-14:],
            "stages": [
                {**stage.to_dict(), "done": self._stats[stage.number]["done"],
                 "current": stage.number == working, "hints": self._stats[stage.number]["hints"],
                 "shown": self._stats[stage.number]["shown"], "moves": self._stats[stage.number]["moves"],
                 "alone": self._stats[stage.number]["alone"]}
                for stage in STAGES
            ],
            "step": step_data,
            "hintLevel": self._hint_level,
            "hints": [{"level": level, **self._hint_texts[level]} for level in sorted(self._hint_texts)],
            "guide": [Move.parse(name).to_dict() for name in self._guide],
            "guideAll": [Move.parse(name).to_dict() for name in self._guide_all] if self._guide else [],
            "guideTask": self._guide_task if self._guide else None,
            "note": self.note,
            "justDone": STAGES[self.just_done - 1].to_dict() if self.just_done else None,
            "answer": self.answer,
            "recap": self.recap,
            "stats": self.stats(),
            "tutorBusy": self.tutor_busy,
        }
