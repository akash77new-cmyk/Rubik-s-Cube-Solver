"""The beginner method (Phase 8): solve a cube the way a person learns to, in 7 stages.

Kociemba's solver finds about 20 moves, but no person could learn to find them. The
beginner method is what people learn: one layer at a time, a few short algorithms.

    1 white cross     2 white corners   (white on top)
    ── turn the cube over: yellow on top, the same colour facing you ──
    3 middle layer    4 yellow cross    5 yellow face    6 yellow corners    7 yellow edges

This module is the "code knows the cube" half of the AI Tutor (AI rule 1):

- ``current_stage()`` checks which stages are done, from the stickers alone;
- ``next_step()`` finds the next step of the current stage: which piece, where it is,
  where it goes, and the exact moves (always checked by simulating them);
- the texts it returns (``look``, ``how``) are the built-in hints, and the facts the
  tutor's model is given.

Everything is seen from the person holding the cube (the "learner frame"): U is the
side on top *as they hold it*. Turning the cube over (``turn_over``) is the only
whole-cube rotation the learner makes; the moves never assume any other.

Pure module: no I/O. Cube states are 54-letter colour strings here (``U R F D L B``
order, as ``CubeState.to_color_string()``) because a string is about ten times faster
to turn than a ``CubeState``, and the searches below try many sequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.core.cube import COLOR_NAMES, FACE_ORDER, CubeState
from backend.core.cubie import CORNER_FACELETS, CORNER_NAMES, EDGE_FACELETS, EDGE_NAMES
from backend.core.moves import Move, parse_sequence

MOVE_NAMES: Tuple[str, ...] = tuple(face + mod for face in "URFDLB" for mod in ("", "'", "2"))

# --------------------------------------------------------------------------------------
# Fast turning: each move is a fixed reordering of the 54 stickers
# --------------------------------------------------------------------------------------


def _move_permutations() -> Dict[str, Tuple[int, ...]]:
    """For each move, which old sticker ends up at each of the 54 places.

    Built from ``CubeState.apply`` (the tested cube model), so it can't disagree with it.
    """
    labels = CubeState({face: [f"{face}{i}" for i in range(9)] for face in FACE_ORDER})
    order = [sticker for face in FACE_ORDER for sticker in labels.face(face)]
    index = {sticker: i for i, sticker in enumerate(order)}
    permutations = {}
    for name in MOVE_NAMES:
        turned = labels.apply(name)
        permutations[name] = tuple(index[s] for face in FACE_ORDER for s in turned.face(face))
    return permutations


_PERM = _move_permutations()


def turn(state: str, moves: Iterable[str]) -> str:
    """The colour string after ``moves`` (move names like "R'")."""
    for name in moves:
        permutation = _PERM[name]
        state = "".join([state[i] for i in permutation])
    return state


def _face_of(index: int) -> str:
    return FACE_ORDER[index // 9]


def _center(state: str, face: str) -> str:
    return state[FACE_ORDER.index(face) * 9 + 4]


# --------------------------------------------------------------------------------------
# Whole-cube rotations (turning the cube over, and looking at a slot "from the front")
# --------------------------------------------------------------------------------------

Vec = Tuple[int, int, int]

#: The outward direction of each face. Axes as in the 3D view (frontend cube.tsx):
#: +x to the right, +y down, +z towards the person holding the cube.
_NORMALS: Dict[str, Vec] = {
    "U": (0, -1, 0), "D": (0, 1, 0), "R": (1, 0, 0), "L": (-1, 0, 0), "F": (0, 0, 1), "B": (0, 0, -1),
}


def _sticker_index(face: str, x: int, y: int, z: int) -> int:
    """Which of a face's 9 stickers a cubie at (x, y, z) shows (same as cube.tsx)."""
    return {
        "F": (y + 1) * 3 + (x + 1),
        "B": (y + 1) * 3 + (1 - x),
        "R": (y + 1) * 3 + (1 - z),
        "L": (y + 1) * 3 + (z + 1),
        "U": (z + 1) * 3 + (x + 1),
        "D": (1 - z) * 3 + (x + 1),
    }[face]


def _stickers_3d() -> List[Tuple[int, Vec, Vec]]:
    """(colour-string index, cubie position, outward direction) for all 54 stickers."""
    found = []
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            for z in (-1, 0, 1):
                for face, normal in _NORMALS.items():
                    if all(n == 0 or n == c for n, c in zip(normal, (x, y, z))):
                        index = FACE_ORDER.index(face) * 9 + _sticker_index(face, x, y, z)
                        found.append((index, (x, y, z), normal))
    return found


_STICKERS_3D = _stickers_3d()


def _rotation(rotate: Callable[[Vec], Vec]) -> Tuple[Tuple[int, ...], Dict[str, str]]:
    """A whole-cube rotation as (sticker reordering, face map).

    The face map says where each face goes: after the rotation, a move of face X
    becomes a move of face ``face_map[X]`` (tests check this for all 18 moves).
    """
    where = {(position, normal): index for index, position, normal in _STICKERS_3D}
    permutation = [0] * 54
    for index, position, normal in _STICKERS_3D:
        permutation[where[(rotate(position), rotate(normal))]] = index
    by_normal = {normal: face for face, normal in _NORMALS.items()}
    face_map = {face: by_normal[rotate(normal)] for face, normal in _NORMALS.items()}
    return tuple(permutation), face_map


#: Turning the cube over: the front stays in front, top and bottom swap, left and right swap.
_TURN_OVER, TURN_OVER_FACES = _rotation(lambda v: (-v[0], -v[1], v[2]))
#: A quarter turn of the whole cube about the vertical axis: front -> right -> back -> left.
_QUARTER, _QUARTER_FACES = _rotation(lambda v: (-v[2], v[1], v[0]))


def turn_over(state: str) -> str:
    """The cube as seen after turning it over (top to bottom, the front still in front)."""
    return "".join([state[i] for i in _TURN_OVER])


def _rotate_quarter(state: str, times: int) -> str:
    for _ in range(times % 4):
        state = "".join([state[i] for i in _QUARTER])
    return state


def _relabel(moves: Sequence[str], times: int) -> List[str]:
    """Moves made in a cube view rotated ``times`` quarters, as moves in the real view.

    If ``view = _rotate_quarter(state, times)``, then doing ``moves`` on the view is the
    same as doing ``_relabel(moves, times)`` on the real cube.
    """
    back = {face: face for face in "URFDLB"}
    for _ in range(times % 4):
        back = {face: next(f for f, g in _QUARTER_FACES.items() if g == back[face]) for face in back}
    return [back[name[0]] + name[1:] for name in moves]


# --------------------------------------------------------------------------------------
# Pieces
# --------------------------------------------------------------------------------------

#: Each edge and corner place as its colour-string indices (Kociemba's order: the U/D
#: sticker first). The same numbering as cubie.py, where it is tested.
EDGE_SLOTS: Tuple[Tuple[int, ...], ...] = EDGE_FACELETS
CORNER_SLOTS: Tuple[Tuple[int, ...], ...] = CORNER_FACELETS
SLOT_NAMES: Dict[Tuple[int, ...], str] = {
    **{slot: name for slot, name in zip(EDGE_SLOTS, EDGE_NAMES)},
    **{slot: name for slot, name in zip(CORNER_SLOTS, CORNER_NAMES)},
}


def _colors(state: str, slot: Sequence[int]) -> Tuple[str, ...]:
    return tuple(state[i] for i in slot)


def find_piece(state: str, colors: Iterable[str]) -> Tuple[int, ...]:
    """The slot holding the piece with these colours (any order)."""
    wanted = sorted(colors)
    for slot in (EDGE_SLOTS if len(wanted) == 2 else CORNER_SLOTS):
        if sorted(_colors(state, slot)) == wanted:
            return slot
    raise ValueError(f"No piece with colours {wanted}")


def is_home(state: str, slot: Sequence[int]) -> bool:
    """True if every sticker of this slot matches the centre of its side."""
    return all(state[i] == _center(state, _face_of(i)) for i in slot)


def _home_slot(state: str, colors: Sequence[str], slots: Sequence[Tuple[int, ...]]) -> Tuple[int, ...]:
    """Where a piece with these colours belongs: the slot whose centres have its colours."""
    wanted = sorted(colors)
    for slot in slots:
        if sorted(_center(state, _face_of(i)) for i in slot) == wanted:
            return slot
    raise ValueError(f"No home for {wanted}")


def _pieces(state: str, slots: Sequence[Tuple[int, ...]], test: Callable[[Tuple[str, ...]], bool]) -> List[Tuple[str, ...]]:
    """The colours of every piece (edges or corners) that passes ``test``, in a fixed order."""
    found = [_colors(state, slot) for slot in slots]
    return [colors for colors in found if test(colors)]


def white_edges(state: str) -> List[Tuple[str, ...]]:
    return _pieces(state, EDGE_SLOTS, lambda c: "W" in c)


def white_corners(state: str) -> List[Tuple[str, ...]]:
    return _pieces(state, CORNER_SLOTS, lambda c: "W" in c)


def middle_edges(state: str) -> List[Tuple[str, ...]]:
    return _pieces(state, EDGE_SLOTS, lambda c: "W" not in c and "Y" not in c)


def yellow_edges(state: str) -> List[Tuple[str, ...]]:
    return _pieces(state, EDGE_SLOTS, lambda c: "Y" in c)


def yellow_corners(state: str) -> List[Tuple[str, ...]]:
    return _pieces(state, CORNER_SLOTS, lambda c: "Y" in c)


def _all_home(state: str, pieces: Sequence[Tuple[str, ...]]) -> bool:
    return all(is_home(state, find_piece(state, colors)) for colors in pieces)


def _yellow_on_yellow_side(state: str, pieces: Sequence[Tuple[str, ...]]) -> bool:
    """Each piece's yellow sticker is on the side with the yellow centre."""
    for colors in pieces:
        slot = find_piece(state, colors)
        index = next(i for i in slot if state[i] == "Y")
        if _center(state, _face_of(index)) != "Y":
            return False
    return True


# --------------------------------------------------------------------------------------
# The stages
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    number: int
    name: str
    goal: str  # what the stage must achieve, in plain English
    learned: str  # shown when the stage is done
    top: str  # the colour on top while doing this stage: "W" or "Y"
    lesson: str  # the lesson section that teaches it (Phase 7 id)

    def to_dict(self) -> Dict[str, object]:
        return {"number": self.number, "name": self.name, "goal": self.goal, "learned": self.learned,
                "top": self.top, "lesson": self.lesson}


_LESSON = "05-beginner-method#"
STAGES: Tuple[Stage, ...] = (
    Stage(1, "White cross", "Make a white cross on top: the four white edges around the white centre, "
          "each with its other colour matching the centre of its side.",
          "You can move one edge into place without breaking the ones already there.", "W",
          _LESSON + "stage-1-the-white-cross"),
    Stage(2, "White corners", "Put the four white corners in place, so the whole white layer is solved.",
          "One short algorithm, repeated, solves any corner.", "W", _LESSON + "stage-2-the-white-corners"),
    Stage(3, "Middle layer", "Put the four middle-layer edges in place, between the side centres.",
          "You can insert an edge to the left or right without breaking the white layer.", "Y",
          _LESSON + "stage-3-the-middle-layer"),
    Stage(4, "Yellow cross", "Make a yellow cross on top (the edges' side colours don't matter yet).",
          "One algorithm turns a dot into an L, an L into a line, and a line into a cross.", "Y",
          _LESSON + "stage-4-the-yellow-cross"),
    Stage(5, "Yellow face", "Make the whole top yellow.",
          "The Sune turns the top corners until the whole face is yellow.", "Y", _LESSON + "stage-5-the-yellow-face"),
    Stage(6, "Yellow corners", "Put the four yellow corners in their places (their side colours match).",
          "The headlights algorithm swaps corners without spoiling the yellow face.", "Y",
          _LESSON + "stage-6-the-yellow-corners"),
    Stage(7, "Yellow edges", "Put the last edges in place: the cube is solved.",
          "You solved the whole cube with the beginner method.", "Y", _LESSON + "stage-7-the-yellow-edges"),
)

#: The algorithms of the method, written for the front-right (or front) as usual.
ALGORITHMS: Dict[str, Tuple[str, str]] = {
    "corner": ("the corner trick", "R' D' R D"),
    "right": ("the right insert", "U R U' R' U' F' U F"),
    "left": ("the left insert", "U' L' U L U F U' F'"),
    "cross": ("the yellow-cross algorithm", "F R U R' U' F'"),
    "sune": ("the Sune", "R U R' U R U2 R'"),
    "headlights": ("the headlights algorithm", "R' F R' B2 R F' R' B2 R2"),
    "edges": ("the edge cycle", "R U' R U R U R U' R' U' R2"),
}


def stage_checks(state: str) -> List[bool]:
    """Whether each stage's goal is met right now (index 0 = stage 1)."""
    return [
        _all_home(state, white_edges(state)),
        _all_home(state, white_corners(state)),
        _all_home(state, middle_edges(state)),
        _yellow_on_yellow_side(state, yellow_edges(state)),
        _yellow_on_yellow_side(state, yellow_edges(state) + yellow_corners(state)),
        _all_home(state, yellow_corners(state)),
        _all_home(state, yellow_edges(state)),
    ]


def current_stage(state: str) -> int:
    """The first stage whose goal is not met (1..7), or 8 when the cube is solved.

    A later stage only counts once every earlier one is done, as in the method.
    """
    for number, done in enumerate(stage_checks(state), start=1):
        if not done:
            return number
    return 8


# --------------------------------------------------------------------------------------
# Words: where a piece is, as the learner sees it
# --------------------------------------------------------------------------------------

SIDE_WORDS = {"U": "top", "D": "bottom", "F": "front", "B": "back", "R": "right", "L": "left"}
FACING_WORDS = {"U": "up", "D": "down", "F": "towards you", "B": "away from you", "R": "to the right",
                "L": "to the left"}


def color_word(code: str) -> str:
    return COLOR_NAMES[code].lower()


def piece_name(colors: Sequence[str]) -> str:
    """e.g. "the white-blue edge" or "the white-red-green corner"."""
    ordered = sorted(colors, key=lambda c: "WYGBRO".index(c))
    kind = "edge" if len(colors) == 2 else "corner"
    return f"the {'-'.join(color_word(c) for c in ordered)} {kind}"


def place_words(slot: Sequence[int]) -> str:
    """e.g. "the bottom layer, at the front-right" or "the middle layer, at the back-left"."""
    faces = [_face_of(i) for i in slot]
    layer = "top" if "U" in faces else "bottom" if "D" in faces else "middle"
    sides = [f for f in ("F", "B") if f in faces] + [f for f in ("R", "L") if f in faces]
    return f"the {layer} layer, at the {'-'.join(SIDE_WORDS[f] for f in sides)}"


def facing(state: str, slot: Sequence[int], color: str) -> str:
    """Which way the sticker of this colour on the piece points, e.g. "down"."""
    index = next(i for i in slot if state[i] == color)
    return FACING_WORDS[_face_of(index)]


def sticker_keys(slot: Sequence[int]) -> List[str]:
    """UI keys of a slot's stickers, e.g. ["U7", "F1"] (face + 0-based index)."""
    return [f"{_face_of(i)}{i % 9}" for i in slot]



# --------------------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """The next thing to do. The moves always come from code, checked by simulation.

    The texts are what the learner sees, in order: ``task`` at once, ``look`` as hint 1,
    ``how`` as hint 2, and ``moves`` as hint 3 (or when they press "Show me").
    """

    stage: int
    kind: str  # "moves", or "turn_over" (turn the whole cube over first)
    moves: Tuple[str, ...]
    task: str  # what to do now, on this cube
    look: str  # hint 1: what to look at
    how: str  # hint 2: which algorithm or idea
    algorithm: Optional[str] = None  # key of ALGORITHMS, if the step uses one
    algorithm_moves: Tuple[str, ...] = ()  # that algorithm as done here (for the side it's done at)
    piece: Tuple[str, ...] = ()  # colours of the piece being placed, if any
    focus: Tuple[str, ...] = field(default_factory=tuple)  # sticker keys to highlight

    def to_dict(self) -> Dict[str, object]:
        return {
            "stage": self.stage,
            "kind": self.kind,
            "task": self.task,
            "look": self.look,
            "how": self.how,
            "moves": [Move.parse(m).to_dict() for m in self.moves],
            "notation": " ".join(self.moves),
            "algorithm": ALGORITHMS[self.algorithm][0] if self.algorithm else None,
            "algorithmNotation": " ".join(self.algorithm_moves) or None,
            "piece": piece_name(self.piece) if self.piece else None,
            "focus": list(self.focus),
        }


def simplify(moves: Sequence[str]) -> List[str]:
    """Join turns of the same side that follow each other (U U -> U2, U U' -> nothing)."""
    result: List[Tuple[str, int]] = []
    for name in moves:
        face, quarters = name[0], Move.parse(name).quarter_turns
        if result and result[-1][0] == face:
            total = (result[-1][1] + quarters) % 4
            result.pop()
            if total:
                result.append((face, total))
        else:
            result.append((face, quarters))
    return [face + {1: "", 2: "2", 3: "'"}[q] for face, q in result]


def parse_names(notation: str) -> List[str]:
    """ "R U R'" -> ["R", "U", "R'"] (checked notation)."""
    return [move.notation for move in parse_sequence(notation)]


def _layer_ok(state: str, upto: int) -> bool:
    """Stages 1..upto are all done."""
    return all(stage_checks(state)[:upto])


def _faces(slot: Sequence[int]) -> List[str]:
    return [_face_of(i) for i in slot]


def _view_for(state: str, home: Sequence[int], front_slot: Tuple[int, ...]) -> int:
    """How many quarter turns of the view bring the place ``home`` to ``front_slot``."""
    colors = sorted(_center(state, _face_of(i)) for i in home)
    for times in range(4):
        view = _rotate_quarter(state, times)
        if sorted(_center(view, _face_of(i)) for i in front_slot) == colors:
            return times
    raise ValueError("no view puts this place at the front")


_UF = EDGE_SLOTS[EDGE_NAMES.index("UF")]
_URF = CORNER_SLOTS[CORNER_NAMES.index("URF")]

# ---- Stage 1: the white cross --------------------------------------------------------

#: The white-cross cases with white on top, for the edge whose place is the top front
#: (UF): where the edge is (its place, and 0 if its white sticker is on the place's
#: first side, the top/bottom or front/back one) -> the shortest moves that put it in
#: place and keep the other three top edges where they are. Found by a breadth-first
#: search; tests replay every case. Other places use the same moves, seen from that side.
CROSS_CASES: Dict[Tuple[str, int], Tuple[str, ...]] = {
    ("UF", 1): ("F", "U'", "R", "U"),
    ("FR", 0): ("U'", "R", "U"),
    ("FR", 1): ("F'",),
    ("FL", 0): ("U", "L'", "U'"),
    ("FL", 1): ("F",),
    ("BR", 0): ("U'", "R'", "U"),
    ("BR", 1): ("U2", "B", "U2"),
    ("BL", 0): ("U", "L", "U'"),
    ("BL", 1): ("U2", "B'", "U2"),
    ("DF", 0): ("F2",),
    ("DF", 1): ("F'", "U'", "R", "U"),
    ("DR", 0): ("D'", "F2"),
    ("DR", 1): ("R", "F'", "R'"),
    ("DL", 0): ("D", "F2"),
    ("DL", 1): ("L'", "F", "L"),
    ("DB", 0): ("D2", "F2"),
    ("DB", 1): ("D'", "R", "F'", "R'"),
}

#: An edge in another edge's top place comes out first: turn that side twice.
_TAKE_OUT = {"UR": "R2", "UB": "B2", "UL": "L2"}


def _edge_place(state: str, colors: Sequence[str]) -> Tuple[str, int]:
    """(place name, flip) of a white edge; flip 0 when white is on the place's first side."""
    slot = find_piece(state, colors)
    return SLOT_NAMES[slot], 0 if state[slot[0]] == "W" else 1


def _cross_moves(state: str, colors: Tuple[str, ...]) -> List[str]:
    """Moves that put one white edge in place and keep the other top edges (white on top)."""
    home = _home_slot(state, colors, EDGE_SLOTS)
    times = _view_for(state, home, _UF)
    view = _rotate_quarter(state, times)  # the edge's place is now the top front
    place, flip = _edge_place(view, colors)
    moves: List[str] = []
    if place in _TAKE_OUT:
        moves.append(_TAKE_OUT[place])
        place, flip = _edge_place(turn(view, moves), colors)
    if (place, flip) != ("UF", 0):
        moves += CROSS_CASES[(place, flip)]
    return _relabel(moves, times)


def _cross_step(state: str) -> Step:
    edges = white_edges(state)
    todo = [c for c in edges if not is_home(state, find_piece(state, c))]
    # the easiest edge first, as a person would
    colors = min(todo, key=lambda c: (len(_cross_moves(state, c)), edges.index(c)))
    moves = _cross_moves(state, colors)
    slot, home = find_piece(state, colors), _home_slot(state, colors, EDGE_SLOTS)
    other = color_word(next(c for c in colors if c != "W"))
    white = facing(state, slot, "W")
    faces = _faces(slot)
    if slot == home:
        how = "It's in its place but flipped: take it out with a side turn and put it back the other way round."
    elif "U" in faces:
        how = ("It's in the top layer at the wrong place: turn that side twice to take it down to the bottom, "
               f"then bring it under the {other} centre and turn that side twice.")
    elif "D" in faces and white == "down":
        how = (f"Turn the bottom layer until the edge is right under the {other} centre, then turn that side "
               "twice: white comes up on top.")
    elif "D" in faces:
        how = ("Its white sticker faces out, so two turns would put it in upside down. Lift it with a side "
               "turn instead, and put back any cross edge that moved.")
    else:
        how = ("It's in the middle layer: one turn of a side lifts it next to the white centre. If that would "
               "move a cross edge, turn the top first and turn it back afterwards.")
    return Step(
        1, "moves", tuple(moves),
        task=f"Put {piece_name(colors)} on top, above the {other} centre. It's in {place_words(slot)}.",
        look=(f"Look at its white sticker: it faces {white}. In the end white must face up, and the {other} "
              f"sticker must sit above the {other} centre."),
        how=how, piece=colors, focus=tuple(sticker_keys(slot)),
    )


# ---- Stage 2: the white corners -----------------------------------------------------


def _corner_trick_at(state: str, slot: Tuple[int, ...]) -> List[str]:
    """The corner trick (R' D' R D) done at the top corner place ``slot`` (white on top)."""
    return _relabel(parse_names(ALGORITHMS["corner"][1]), _view_for(state, slot, _URF))


def _corner_moves(state: str, colors: Tuple[str, ...]) -> Tuple[List[str], List[str]]:
    """(moves, the corner trick at its place) that solve one white corner."""
    home = _home_slot(state, colors, CORNER_SLOTS)
    trick = _corner_trick_at(state, home)
    slot = find_piece(state, colors)
    moves: List[str] = []
    if "U" in _faces(slot):  # in the top layer (wrong place, or twisted in its place): bring it down
        moves += _corner_trick_at(state, slot)
    current = turn(state, moves)
    below = next(s for s in CORNER_SLOTS if "D" in _faces(s) and set(_faces(s)) - {"D"} == set(_faces(home)) - {"U"})
    for bottom_turn in ([], ["D"], ["D2"], ["D'"]):  # turn the bottom until it's under its place
        if find_piece(turn(current, bottom_turn), colors) == below:
            moves += bottom_turn
            current = turn(current, bottom_turn)
            break
    while not is_home(current, home):  # then the trick until it's solved: 1, 3 or 5 times
        moves += trick
        current = turn(current, trick)
    return simplify(moves), trick


def _corner_step(state: str) -> Step:
    corners = white_corners(state)
    todo = [c for c in corners if not is_home(state, find_piece(state, c))]
    colors = min(todo, key=lambda c: (len(_corner_moves(state, c)[0]), corners.index(c)))
    moves, trick = _corner_moves(state, colors)
    slot, home = find_piece(state, colors), _home_slot(state, colors, CORNER_SLOTS)
    sides = [color_word(c) for c in colors if c != "W"]
    if slot == home:
        first = f"It's in its place but twisted: do {' '.join(trick)} once to bring it down. "
    elif "U" in _faces(slot):
        first = (f"It's in the top layer at the wrong place: do {' '.join(_corner_trick_at(state, slot))} there "
                 "once to bring it down. ")
    else:
        first = ""
    return Step(
        2, "moves", tuple(moves),
        task=(f"Put {piece_name(colors)} in {place_words(home)}, between {sides[0]} and {sides[1]}. "
              f"It's in {place_words(slot)}."),
        look=(f"Its white sticker faces {facing(state, slot, 'W')}. Work on it from the bottom layer, right "
              "under its place; white ends up facing up."),
        how=(first + "Turn the bottom until the corner is right under its place, then repeat "
             f"{' '.join(trick)} (the corner trick, done at that corner) until it is solved: 1, 3 or 5 times."),
        algorithm="corner", algorithm_moves=tuple(trick), piece=colors, focus=tuple(sticker_keys(slot)),
    )


# ---- Stage 3: the middle layer --------------------------------------------------------

_AUF: Tuple[List[str], ...] = ([], ["U"], ["U'"], ["U2"])


def _variants(name: str) -> List[Tuple[str, List[str]]]:
    """An algorithm done at each of the four sides: (the side it is done from, moves)."""
    base = parse_names(ALGORITHMS[name][1])
    return [(SIDE_WORDS[_relabel(["F"], times)[0]], _relabel(base, times)) for times in range(4)]


Macro = Tuple[str, List[str]]  # (label, moves)


def _search(state: str, macros: Sequence[Macro], goal: Callable[[str], bool], depth: int) -> Optional[List[Macro]]:
    """The fewest macros (then the fewest moves) that reach ``goal``, trying every combination."""
    level: List[Tuple[str, List[Macro]]] = [(state, [])]
    for _ in range(depth):
        best: Optional[List[Macro]] = None
        next_level = []
        for current, path in level:
            for macro in macros:
                after, candidate = turn(current, macro[1]), path + [macro]
                if goal(after) and (best is None or sum(len(m[1]) for m in candidate) < sum(len(m[1]) for m in best)):
                    best = candidate
                next_level.append((after, candidate))
        if best is not None:
            return best
        level = next_level
    return None


def _middle_step(state: str) -> Step:
    edges = middle_edges(state)
    solved = [c for c in edges if is_home(state, find_piece(state, c))]
    todo = [c for c in edges if c not in solved]

    def keeps(after: str) -> bool:
        return _layer_ok(after, 2) and all(is_home(after, find_piece(after, c)) for c in solved)

    inserts = [(f"{name}:{side}", moves) for name in ("right", "left") for side, moves in _variants(name)]
    with_turn = [(label, auf + moves) for auf in _AUF for label, moves in inserts]
    best: Optional[Tuple[Tuple[str, ...], Macro]] = None
    for colors in todo:  # an edge one insert can solve, fewest moves first
        found = _search(state, with_turn, lambda a, c=colors: keeps(a) and is_home(a, find_piece(a, c)), 1)
        if found and (best is None or len(found[0][1]) < len(best[1][1])):
            best = (colors, found[0])
    if best is not None:
        colors, (label, moves) = best
        name, side = label.split(":")
        alg = moves[len(moves) - 8:]  # both inserts are 8 moves; before them, the top turn
        slot, home = find_piece(state, colors), _home_slot(state, colors, EDGE_SLOTS)
        side_color = next(state[i] for i in slot if _face_of(i) != "U")
        return Step(
            3, "moves", tuple(simplify(moves)),
            task=(f"Put {piece_name(colors)} in {place_words(home)}, between {color_word(colors[0])} and "
                  f"{color_word(colors[1])}. It's in {place_words(slot)}."),
            look=(f"Look at its side sticker ({color_word(side_color)}): turn the top until it sits above the "
                  f"{color_word(side_color)} centre. The top sticker's colour says which way it goes."),
            how=(f"Then do {ALGORITHMS[name][0]}, done from the {side}: {' '.join(alg)}."),
            algorithm=name, algorithm_moves=tuple(alg), piece=colors, focus=tuple(sticker_keys(slot)),
        )
    # every edge left is stuck in the middle layer: an insert at its place pushes it out
    colors = todo[0]
    slot = find_piece(state, colors)
    found = _search(state, inserts, lambda a: keeps(a) and "U" in _faces(find_piece(a, colors)), 1)
    assert found is not None, "an insert can always push a middle edge out"
    label, moves = found[0]
    name, side = label.split(":")
    return Step(
        3, "moves", tuple(moves),
        task=f"Take {piece_name(colors)} out of {place_words(slot)}: it's in the wrong place or flipped.",
        look="No edge in the top layer belongs in the middle any more, so this stuck edge has to come out first.",
        how=(f"Do {ALGORITHMS[name][0]} from the {side} at its place, with any top edge: that pushes it up into "
             "the top layer. Then insert it properly."),
        algorithm=name, algorithm_moves=tuple(moves), piece=colors, focus=tuple(sticker_keys(slot)),
    )


# ---- Stages 4-7: the yellow layer -----------------------------------------------------
# Each stage follows the rule a person learns: turn the top to a set position, do the
# stage's algorithm, and repeat. Tests check on many random cubes that every rule
# finishes its stage within three algorithms.

_TOP = tuple(f"U{i}" for i in range(9))
_STICKER = {name: FACE_ORDER.index(name[0]) * 9 + int(name[1]) for name in (
    "U1", "U3", "U5", "U7", "U0", "U2", "U6", "U8", "F0", "L2", "B1")}


def _yellow(state: str, *names: str) -> bool:
    return all(state[_STICKER[name]] == "Y" for name in names)


def _first_turn(state: str, test: Callable[[str], bool]) -> List[str]:
    """The top turn (none, U, U' or U2) after which ``test`` holds."""
    return next(auf for auf in _AUF if test(turn(state, auf)))


def _algorithm_step(stage: int, setup: List[str], name: str, task: str, look: str, how: str,
                    after: Sequence[str] = ()) -> Step:
    alg = parse_names(ALGORITHMS[name][1])
    return Step(stage, "moves", tuple(simplify(list(setup) + alg + list(after))), task=task, look=look, how=how,
                algorithm=name, algorithm_moves=tuple(alg), focus=_TOP)


def _yellow_cross_step(state: str) -> Step:
    back, left, right, front = (_yellow(state, n) for n in ("U1", "U3", "U5", "U7"))
    count = sum((back, left, right, front))
    if count == 0:
        shape, setup = "a dot (only the centre is yellow)", []
    elif (back and front) or (left and right):
        shape, setup = "a line", _first_turn(state, lambda s: _yellow(s, "U3", "U5"))
    else:
        shape, setup = "an L", _first_turn(state, lambda s: _yellow(s, "U1", "U3"))
    return _algorithm_step(
        4, setup, "cross",
        task="Make a yellow cross on top. Only the yellow stickers on top matter now.",
        look=f"Look at the top: the yellow edge stickers make {shape}.",
        how=("Turn the top so an L is at the back-left, or a line goes from left to right (a dot needs no turn), "
             "then do F R U R' U' F'. Repeat until you see the cross."),
    )


def _yellow_face_step(state: str) -> Step:
    up = sum(1 for n in ("U0", "U2", "U6", "U8") if _yellow(state, n))
    if up == 1:
        setup = _first_turn(state, lambda s: _yellow(s, "U6"))
    elif up == 0:
        setup = _first_turn(state, lambda s: _yellow(s, "L2"))
    else:
        setup = _first_turn(state, lambda s: _yellow(s, "F0"))
    return _algorithm_step(
        5, setup, "sune",
        task="Make the whole top yellow.",
        look=f"Count the yellow corners facing up: {up} of 4.",
        how=("Turn the top first: with one yellow corner up, put it at the front-left; with none, until the "
             "front-left corner's yellow faces left; with two, until it faces you. Then do the Sune: "
             "R U R' U R U2 R'. Repeat until the top is yellow."),
    )


def _corners_in_order(state: str) -> bool:
    return any(_layer_ok(turn(state, auf), 6) for auf in _AUF)


def _lights(state: str, face: str) -> bool:
    base = FACE_ORDER.index(face) * 9
    return state[base] == state[base + 2]


def _yellow_corners_step(state: str) -> Step:
    task = "Put the four yellow corners in their places, so their side colours match the centres."
    if _corners_in_order(state):  # the corners are right; only the top is turned
        return Step(6, "moves", tuple(_first_turn(state, lambda s: _layer_ok(s, 6))), task=task,
                    look="The corners are already in the right order: the top layer is just turned.",
                    how="Turn the top until each corner's side colours match the centres below it.", focus=_TOP)
    sides = [SIDE_WORDS[f] for f in "FRBL" if _lights(state, f)]
    setup = _first_turn(state, lambda s: _lights(s, "B")) if sides else []
    return _algorithm_step(
        6, setup, "headlights", task=task,
        look=("Look for headlights: two top corners on one side with the same side colour. "
              + (f"You have them at the {sides[0]}." if sides else "There are none yet.")),
        how=("Turn the top so the headlights are at the back (with none, start anywhere), then do the "
             "headlights algorithm: R' F R' B2 R F' R' B2 R2. Repeat until the corners can line up."),
    )


def _yellow_edges_step(state: str) -> Step:
    solved = [f for f in "FRBL" if state[FACE_ORDER.index(f) * 9 + 1] == _center(state, f)]
    task = "Put the last yellow edges in place to finish the cube."
    if solved:  # turn the top so the solved edge is at the back, do the cycle, turn the top back
        edge = state[FACE_ORDER.index(solved[0]) * 9 + 1]
        setup = _first_turn(state, lambda s: s[_STICKER["B1"]] == edge)
        back = [Move.parse(m).inverse().notation for m in reversed(setup)]
        look = f"The {SIDE_WORDS[solved[0]]} side's top edge already matches its centre."
    else:
        setup, back = [], []
        look = "No side's top edge matches its centre yet."
    return _algorithm_step(
        7, setup, "edges", after=back, task=task, look=look,
        how=("Turn the top so the solved edge is at the back (with none, start anywhere), do the edge cycle: "
             "R U' R U R U R U' R' U' R2, then turn the top back. If the edges went round the wrong way, "
             "do it again."),
    )


_STEP_FINDERS: Dict[int, Callable[[str], Step]] = {
    1: _cross_step,
    2: _corner_step,
    3: _middle_step,
    4: _yellow_cross_step,
    5: _yellow_face_step,
    6: _yellow_corners_step,
    7: _yellow_edges_step,
}


def next_step(state: str) -> Optional[Step]:
    """The next step of the current stage, or None when the cube is solved."""
    stage = current_stage(state)
    if stage == 8:
        return None
    top = STAGES[stage - 1].top
    if _center(state, "U") != top:
        other = "yellow" if top == "W" else "white"
        return Step(
            stage, "turn_over", (),
            task=f"Turn the cube over: stage {stage} is done with {color_word(top)} on top.",
            look=f"Right now {other} is on top.",
            how=(f"Turn the whole cube over so {color_word(top)} is on top. Keep the same colour facing you: "
                 "left and right swap sides."),
        )
    return _STEP_FINDERS[stage](state)


def solve_all(state: str, limit: int = 120) -> Tuple[List[str], List[int]]:
    """Every action from ``state`` to solved, following the method step by step.

    Returns (actions, stage of each action); an action is a move name or "turn_over".
    Tests use it: every random cube must end solved, with the stages in order.
    """
    actions: List[str] = []
    stages: List[int] = []
    for _ in range(limit):
        step = next_step(state)
        if step is None:
            return actions, stages
        if step.kind == "turn_over":
            state = turn_over(state)
            actions.append("turn_over")
            stages.append(step.stage)
            continue
        assert step.moves, f"stage {step.stage} gave an empty step"
        state = turn(state, step.moves)
        actions += step.moves
        stages += [step.stage] * len(step.moves)
    raise AssertionError("the beginner method did not finish")
