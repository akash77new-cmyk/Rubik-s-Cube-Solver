"""Guided scanning: guide steps, face identification and orientation repair (pure logic)."""

import random

import pytest

from backend.core.cube import DEFAULT_SCHEME, FACE_ORDER, CubeState, random_scramble
from backend.core.scanning import (
    IDENTITY_MAP,
    MIRROR_MAP,
    QUARTER_TURN_MAP,
    SCAN_ORDER,
    SCAN_STEPS,
    TOP_NEIGHBOUR,
    OrientationFix,
    banner_title,
    face_for_center,
    orientation_map,
    reorder,
    repair_orientation,
)


def faces_of(cube: CubeState):
    return {face: cube.face(face) for face in FACE_ORDER}


def test_guide_covers_every_face_once_with_the_right_top_colour():
    assert sorted(SCAN_ORDER) == sorted(FACE_ORDER)
    assert [step.text for step in SCAN_STEPS][:2] == [
        "Green facing the camera, white on top",
        "Red facing the camera, white on top",
    ]
    # Reading conventions of the cube model: sides with U on top, U with B, D with F.
    assert TOP_NEIGHBOUR == {"F": "U", "R": "U", "B": "U", "L": "U", "U": "B", "D": "F"}
    by_face = {step.face: step for step in SCAN_STEPS}
    assert (by_face["U"].center, by_face["U"].top) == ("W", "B")
    assert (by_face["D"].center, by_face["D"].top) == ("Y", "G")


def test_faces_are_recognised_by_their_centre_colour():
    for face, color in DEFAULT_SCHEME.items():
        assert face_for_center(color) == face
    assert face_for_center("X") is None


def test_banner_title_is_plain_ascii():
    title = banner_title("U")
    assert title == "Show WHITE, BLUE on top" and title.isascii()
    assert banner_title(None) == "All six sides captured"


def test_index_maps():
    letters = list("abcdefghi")
    assert reorder(letters, QUARTER_TURN_MAP) == list("gdahebifc")  # a quarter turn clockwise
    assert reorder(letters, MIRROR_MAP) == list("cbafedihg")
    assert orientation_map(4) == IDENTITY_MAP
    assert reorder(reorder(letters, MIRROR_MAP), MIRROR_MAP) == letters
    assert reorder(letters, orientation_map(1, mirrored=True)) == reorder(
        reorder(letters, MIRROR_MAP), QUARTER_TURN_MAP
    )


def test_valid_scans_and_misread_colours_are_not_touched():
    cube = CubeState.solved().apply_sequence(random_scramble(20, seed=1))
    assert repair_orientation(faces_of(cube)) is None  # nothing to repair
    faces = faces_of(cube)
    faces["F"][0] = next(c for c in "WYROGB" if c != faces["F"][0])  # a misread sticker
    assert repair_orientation(faces) is None  # rotations can't fix colours


def test_one_face_held_rotated_is_found_exactly():
    cube = CubeState.solved().apply_sequence(random_scramble(20, seed=2))
    faces = faces_of(cube)
    faces["U"] = reorder(faces["U"], orientation_map(1))  # the user held it a quarter turn off
    fix = repair_orientation(faces)
    assert fix is not None and not fix.mirrored and set(fix.rotations) == {"U"}
    repaired = {face: reorder(faces[face], fix.index_map(face)) for face in FACE_ORDER}
    assert repaired == faces_of(cube)
    assert fix.describe() == "Fixed automatically: the white side was held a quarter turn off."


def test_a_mirrored_camera_is_found_exactly():
    cube = CubeState.solved().apply_sequence(random_scramble(20, seed=3))
    faces = {face: reorder(colors, MIRROR_MAP) for face, colors in faces_of(cube).items()}
    fix = repair_orientation(faces)
    assert fix == OrientationFix({}, mirrored=True)
    assert {f: reorder(faces[f], fix.index_map(f)) for f in FACE_ORDER} == faces_of(cube)


def test_random_orientation_mistakes_are_repaired_exactly():
    """300 scans with up to 3 faces held wrong, 30% through a mirrored camera."""
    rng = random.Random(7)
    for _ in range(300):
        cube = CubeState.solved().apply_sequence(random_scramble(20, seed=rng.random()))
        mirrored = rng.random() < 0.3
        wrong = rng.sample(FACE_ORDER, rng.choice([1, 1, 2, 3]))
        faces = {}
        for face, colors in faces_of(cube).items():
            if face in wrong:
                colors = reorder(colors, orientation_map(rng.choice([1, 2, 3])))
            faces[face] = reorder(colors, MIRROR_MAP) if mirrored else colors
        fix = repair_orientation(faces)
        assert fix is not None
        assert {f: reorder(faces[f], fix.index_map(f)) for f in FACE_ORDER} == faces_of(cube)


def test_too_many_wrong_faces_give_up_instead_of_guessing():
    rng = random.Random(9)
    for _ in range(20):
        cube = CubeState.solved().apply_sequence(random_scramble(20, seed=rng.random()))
        faces = {f: reorder(c, orientation_map(rng.choice([1, 2, 3]))) for f, c in faces_of(cube).items()}
        fix = repair_orientation(faces)  # all six faces wrong: beyond the search limit
        if fix is not None:  # if anything is returned, it must be the truth
            assert {f: reorder(faces[f], fix.index_map(f)) for f in FACE_ORDER} == faces_of(cube)
