"""Full cube validation: structured issues, the three invariants, and agreement
with Kociemba's reference implementation (RubikTwoPhase).
"""

import json
import random

import pytest
import twophase.face as ref_face  # Kociemba's own Python implementation (RubikTwoPhase)

from backend.core.cube import DEFAULT_SCHEME, CubeState, InvalidCubeError, random_scramble
from backend.core.cubie import (
    CENTER_FACELETS,
    CORNER_FACELETS,
    EDGE_FACELETS,
    FACES,
    CubieCube,
    sticker_ref,
)
from backend.core.solver import SolveFailedError, SolverEngine

PIECE_CODES = {
    "impossible_corner", "impossible_edge", "duplicate_corner", "missing_corner",
    "duplicate_edge", "missing_edge", "corner_twist", "edge_flip", "parity",
}


def cube_from_facelets(facelets: str) -> CubeState:
    """URFDLB letters -> a CubeState in the default colour scheme."""
    return CubeState.from_color_string("".join(DEFAULT_SCHEME[f] for f in facelets))


def cube_from_cubie(cubie: CubieCube) -> CubeState:
    return cube_from_facelets(cubie.to_facelet_string())


def reference_check(facelets: str):
    """(ok, cubie) according to Kociemba's reference parser. cubie is None when not ok.

    Note: the reference returns True on success and an error *string* on failure.
    """
    face_cube = ref_face.FaceCube()
    if face_cube.from_string(facelets) is not True:
        return False, None
    cc = face_cube.to_cubie_cube()
    if cc.verify() is not True:
        return False, None
    return True, CubieCube(
        tuple(int(x) for x in cc.cp), tuple(cc.co), tuple(int(x) for x in cc.ep), tuple(cc.eo)
    )


def corrupt(facelets: str, rng: random.Random) -> str:
    """Apply 1-3 random scan-like mistakes to a valid facelet string."""
    f = list(facelets)
    non_centre = [i for i in range(54) if i not in CENTER_FACELETS]
    for _ in range(rng.randint(1, 3)):
        kind = rng.choice(["recolor", "swap", "twist", "flip", "swap_corners", "swap_edges"])
        if kind == "recolor":
            i = rng.choice(non_centre)
            f[i] = rng.choice([c for c in FACES if c != f[i]])
        elif kind == "swap":
            i, j = rng.sample(non_centre, 2)
            f[i], f[j] = f[j], f[i]
        elif kind == "twist":
            a, b, c = rng.choice(CORNER_FACELETS)
            f[a], f[b], f[c] = f[c], f[a], f[b]
        elif kind == "flip":
            a, b = rng.choice(EDGE_FACELETS)
            f[a], f[b] = f[b], f[a]
        elif kind == "swap_corners":
            x, y = rng.sample(CORNER_FACELETS, 2)
            for i, j in zip(x, y):
                f[i], f[j] = f[j], f[i]
        else:
            x, y = rng.sample(EDGE_FACELETS, 2)
            for i, j in zip(x, y):
                f[i], f[j] = f[j], f[i]
    return "".join(f)


def scrambled_facelets(seed: int) -> str:
    return CubeState.solved().apply_sequence(random_scramble(seed=seed)).to_facelet_string()


SOLVED = CubieCube.solved()


# ---- Real cubes ---------------------------------------------------------------------


def test_solved_and_200_scrambles_are_valid():
    """Anything reachable by face turns passes, with no issues at all."""
    assert CubeState.solved().validate().codes() == []
    for seed in range(200):
        cube = CubeState.solved().apply_sequence(random_scramble(seed=seed))
        assert cube.validate().codes() == [], f"seed {seed}"


# ---- The three invariants -------------------------------------------------------


@pytest.mark.parametrize("twist", [1, 2])
def test_one_twisted_corner_is_a_corner_twist(twist):
    """One corner twisted clockwise or anticlockwise: total twist is not 0 mod 3."""
    cubie = CubieCube(SOLVED.cp, (twist,) + (0,) * 7, SOLVED.ep, SOLVED.eo)
    assert cube_from_cubie(cubie).validate().codes() == ["corner_twist"]


def test_one_flipped_edge_is_an_edge_flip():
    """One edge flipped: total flip is odd."""
    cubie = CubieCube(SOLVED.cp, SOLVED.co, SOLVED.ep, (1,) + (0,) * 11)
    assert cube_from_cubie(cubie).validate().codes() == ["edge_flip"]


@pytest.mark.parametrize(
    "cubie",
    [
        CubieCube(SOLVED.cp, SOLVED.co, (1, 0) + tuple(range(2, 12)), SOLVED.eo),
        CubieCube((1, 0) + tuple(range(2, 8)), SOLVED.co, SOLVED.ep, SOLVED.eo),
    ],
    ids=["two-edges-swapped", "two-corners-swapped"],
)
def test_two_swapped_pieces_are_a_parity_error(cubie):
    """Swapping just two pieces makes corner and edge parity differ."""
    assert cube_from_cubie(cubie).validate().codes() == ["parity"]


def test_two_corners_and_two_edges_swapped_is_valid():
    """Both parities odd, so they match - like a real T-perm."""
    cubie = CubieCube(
        (1, 0) + tuple(range(2, 8)), SOLVED.co, (1, 0) + tuple(range(2, 12)), SOLVED.eo
    )
    assert cube_from_cubie(cubie).validate().ok


# ---- Scan-like sticker mistakes -------------------------------------------------


def test_swapping_the_two_stickers_of_an_edge_is_an_edge_flip():
    """Reading an edge back to front flips it in place."""
    f = list(scrambled_facelets(7))
    a, b = EDGE_FACELETS[4]
    f[a], f[b] = f[b], f[a]
    assert cube_from_facelets("".join(f)).validate().codes() == ["edge_flip"]


def test_rotating_the_three_stickers_of_a_corner_is_a_corner_twist():
    """Rotating a corner's stickers in place twists it."""
    f = list(scrambled_facelets(7))
    a, b, c = CORNER_FACELETS[3]
    f[a], f[b], f[c] = f[c], f[a], f[b]
    assert cube_from_facelets("".join(f)).validate().codes() == ["corner_twist"]


def test_swapping_two_stickers_inside_a_corner_is_a_mirror_image():
    """Colour counts stay right, but no real corner has that mirror-image order."""
    f = list(scrambled_facelets(7))
    _, b, c = CORNER_FACELETS[5]
    f[b], f[c] = f[c], f[b]
    result = cube_from_facelets("".join(f)).validate()
    assert result.codes() == ["impossible_corner", "missing_corner"]
    assert result.issues[0].details["reason"] == "mirrored"
    assert result.issues[0].pieces == ("DLF",)


def test_an_edge_with_two_opposite_colours_is_impossible():
    """F2 yellow and D2 green (counts unchanged): edge UF shows white and yellow."""
    facelets = CubeState.solved().facelets
    facelets["F"][1], facelets["D"][1] = "Y", "G"
    issues = CubeState(facelets).validate().issues
    opposite = [i for i in issues if i.code == "impossible_edge" and i.details["reason"] == "opposite"]
    assert [i.pieces for i in opposite] == [("UF",)]


def test_an_edge_with_the_same_colour_twice_is_impossible():
    """U8 green makes edge UF green + green."""
    facelets = CubeState.solved().facelets
    facelets["U"][7] = "G"
    issues = CubeState(facelets).validate().issues
    repeated = [i for i in issues if i.code == "impossible_edge" and i.details["reason"] == "repeated"]
    assert [i.pieces for i in repeated] == [("UF",)]


def test_copying_an_edge_onto_another_gives_duplicate_and_missing():
    """Edge UR copied onto the UF position: UR twice, UF nowhere."""
    f = list(CubieCube.solved().to_facelet_string())
    (ur_a, ur_b), (uf_a, uf_b) = EDGE_FACELETS[0], EDGE_FACELETS[1]
    f[uf_a], f[uf_b] = f[ur_a], f[ur_b]
    codes = cube_from_facelets("".join(f)).validate().codes()
    assert "duplicate_edge" in codes
    assert "missing_edge" in codes


def test_one_misread_sticker_is_always_caught_and_located():
    """200 scrambles, one random sticker read wrong: invalid, and that sticker is flagged."""
    rng = random.Random(1)
    for seed in range(200):
        f = list(scrambled_facelets(seed))
        i = rng.choice([k for k in range(54) if k not in CENTER_FACELETS])
        f[i] = rng.choice([c for c in FACES if c != f[i]])
        result = cube_from_facelets("".join(f)).validate()
        assert not result.ok, f"seed {seed}"
        flagged = {sticker for issue in result.issues for sticker in issue.stickers}
        assert sticker_ref(i) in flagged, f"seed {seed}: {sticker_ref(i)} not in any issue"


# ---- Colour-level problems ------------------------------------------------------


def test_duplicate_centres_skip_the_piece_checks():
    """F centre white like U: the centres can't define a scheme, so no piece issues."""
    facelets = CubeState.solved().facelets
    facelets["F"][4] = "W"
    result = CubeState(facelets).validate()
    assert result.codes() == ["duplicate_centers", "color_count", "color_count"]
    assert result.issues[0].stickers == (("U", 4), ("F", 4))


def test_unknown_colour_code_is_reported_first_and_skips_piece_checks():
    """An 'X' sticker is named, located, and stops the piece checks."""
    facelets = CubeState.solved().facelets
    facelets["R"][2] = "X"
    result = CubeState(facelets).validate()
    assert result.codes()[0] == "invalid_color"
    assert result.issues[0].stickers == (("R", 2),)
    assert not PIECE_CODES & set(result.codes())


# ---- Why the stricter check matters -----------------------------------------------


def test_white_yellow_swap_between_corners_fools_the_reference_parser_but_not_us():
    """Swap white U9 (corner URF) and yellow D3 (corner DFR).

    Kociemba's parser identifies a corner by only two of its three colours, so it
    accepts this cube (and the C solver returns a "solution" for it). Both corners
    are mirror images of real corners, so our validator rejects it.
    """
    f = list(CubieCube.solved().to_facelet_string())
    f[8], f[29] = f[29], f[8]  # U[8] <-> D[2]
    facelets = "".join(f)
    assert reference_check(facelets)[0] is True
    codes = cube_from_facelets(facelets).validate().codes()
    assert codes.count("impossible_corner") == 2


def test_3000_corruptions_agree_with_the_reference():
    """Our verdict == "reference accepts it AND its pieces rebuild the same stickers"."""
    rng = random.Random(2026)
    bases = [scrambled_facelets(seed) for seed in range(300)]
    valid = 0
    for n in range(3000):
        facelets = corrupt(bases[n % len(bases)], rng)
        ref_ok, ref_cubie = reference_check(facelets)
        expected = ref_ok and ref_cubie.to_facelet_string() == facelets
        ok = cube_from_facelets(facelets).validate().ok
        assert ok == expected, f"case {n}: ours={ok}, reference={expected}, {facelets}"
        valid += ok
    assert 0 < valid < 3000, "the corruptions should produce both valid and invalid cubes"


# ---- Output shape and helpers -----------------------------------------------------


def test_to_dict_is_json_and_consistent():
    """The UI payload serialises, and errors/issues/stickers line up."""
    facelets = CubeState.solved().facelets
    facelets["U"][0] = "R"
    payload = CubeState(facelets).validate().to_dict()
    json.dumps(payload)
    assert payload["ok"] is False
    assert payload["errors"] == [issue["message"] for issue in payload["issues"]]
    stickers = [s for issue in payload["issues"] for s in issue["stickers"]]
    assert stickers, "expected at least one located issue"
    for sticker in stickers:
        assert sticker["face"] in "URFDLB" and 0 <= sticker["index"] <= 8


def test_to_cubie():
    """Valid cube -> pieces; invalid cube -> InvalidCubeError."""
    assert CubeState.solved().to_cubie() == CubieCube.solved()
    facelets = CubeState.solved().facelets
    facelets["U"][0] = "R"
    with pytest.raises(InvalidCubeError):
        CubeState(facelets).to_cubie()


def test_solver_rejects_an_impossible_cube_before_searching():
    """Validation fails first, so a fresh engine never needs to warm up."""
    twisted = cube_from_cubie(CubieCube(SOLVED.cp, (1,) + (0,) * 7, SOLVED.ep, SOLVED.eo))
    with pytest.raises(SolveFailedError, match="twisted"):
        SolverEngine().solve(twisted)
