"""Cubie model: facelet tables, sticker <-> piece conversion, invariants and G1.

Kociemba's own Python implementation (RubikTwoPhase) is the reference: our
pieces must equal the ones it computes, for scrambles and for single moves.
"""

import pytest
import twophase.cubie as ref_cubie
import twophase.face as ref_face  # Kociemba's own Python implementation (RubikTwoPhase)

from backend.core.cube import CubeState, random_scramble
from backend.core.cubie import (
    CENTER_FACELETS,
    CORNER_FACELETS,
    EDGE_FACELETS,
    CubieCube,
    analyse_facelets,
    in_g1,
    permutation_parity,
    sticker_label,
    sticker_ref,
)


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


def scrambled_facelets(seed: int) -> str:
    return CubeState.solved().apply_sequence(random_scramble(seed=seed)).to_facelet_string()


def test_facelet_tables_cover_every_sticker_exactly_once():
    """Corner + edge + centre facelets are the numbers 0..53, each exactly once."""
    used = [i for slots in CORNER_FACELETS for i in slots]
    used += [i for slots in EDGE_FACELETS for i in slots]
    used += list(CENTER_FACELETS)
    assert sorted(used) == list(range(54))


def test_solved_cubie_round_trips():
    """The solved piece cube gives the solved facelet string, and back."""
    facelets = CubieCube.solved().to_facelet_string()
    assert facelets == "U" * 9 + "R" * 9 + "F" * 9 + "D" * 9 + "L" * 9 + "B" * 9
    assert analyse_facelets(facelets).cubie == CubieCube.solved()


def test_300_scrambles_round_trip_through_pieces():
    """Stickers -> pieces -> stickers gives back exactly the same stickers."""
    for seed in range(300):
        facelets = scrambled_facelets(seed)
        analysis = analyse_facelets(facelets)
        assert analysis.issues == [], f"seed {seed}: {analysis.issues}"
        assert analysis.cubie.to_facelet_string() == facelets, f"seed {seed}"


def test_300_scrambles_match_the_reference_pieces():
    """Our piece positions and orientations equal Kociemba's, scramble by scramble."""
    for seed in range(300):
        facelets = scrambled_facelets(seed)
        ok, reference = reference_check(facelets)
        assert ok, f"seed {seed}: reference rejected a real scramble"
        assert analyse_facelets(facelets).cubie == reference, f"seed {seed}"


@pytest.mark.parametrize("face", list("URFDLB"))
def test_each_face_turn_matches_the_reference_move(face):
    """Our sticker move tables and Kociemba's piece move definitions agree."""
    ref = ref_cubie.basicMoveCube["URFDLB".index(face)]
    expected = CubieCube(
        tuple(int(x) for x in ref.cp), tuple(ref.co), tuple(int(x) for x in ref.ep), tuple(ref.eo)
    )
    assert CubeState.solved().apply(face).to_cubie() == expected


def test_permutation_parity():
    """Identity is even, one swap is odd, a 3-cycle (two swaps) is even."""
    assert permutation_parity([0, 1, 2]) == 0
    assert permutation_parity([1, 0, 2]) == 1
    assert permutation_parity([1, 2, 0]) == 0


@pytest.mark.parametrize(
    "moves, expected",
    [
        ("", True),
        ("U", True),
        ("U R2 F2 D' L2 B2", True),
        ("R", False),
        ("F", False),
        ("R U", False),
    ],
)
def test_in_g1(moves, expected):
    """Only U, D and half turns keep the cube in G1 = <U, D, R2, L2, F2, B2>."""
    cube = CubeState.solved().apply_sequence(moves).to_cubie()
    assert in_g1(cube) is expected


def test_sticker_labels():
    """Facelet index -> (face, index) and Kociemba's 1-based label."""
    assert sticker_ref(8) == ("U", 8)
    assert sticker_label(8) == "U9"
    assert sticker_label(53) == "B9"
