"""The repair search: which 1 or 2 sticker changes make an unsolvable scan valid."""

from backend.core.cube import CubeState
from backend.core.repair import find_repairs
from tests.sessions import misread, readings_for, real_cube


def test_a_valid_cube_needs_no_repair():
    assert find_repairs(real_cube()).candidates == []


def test_one_misread_sticker_is_found():
    truth = real_cube()  # U2 (index 1) is red
    scan = misread(truth, {("U", 1): "O"})
    readings = readings_for(scan, {("U", 1): ("O", "R", 0.51, 0.48)})
    search = find_repairs(scan, readings)
    assert search.total == 1
    (change,) = search.candidates[0].changes
    assert (change.face, change.index, change.old, change.new) == ("U", 1, "O", "R")
    assert (change.old_confidence, change.new_confidence) == (0.51, 0.48)
    assert search.candidates[0].apply(scan) == truth


def test_two_misreads_that_keep_the_counts_are_ranked_by_doubt():
    truth = real_cube()  # U2 is red and U4 is yellow: the camera swapped them
    scan = misread(truth, {("U", 1): "Y", ("U", 3): "R"})
    assert scan.validate().codes() == ["parity"] and scan.color_counts() == truth.color_counts()
    readings = readings_for(scan, {("U", 1): ("Y", "R", 0.50, 0.46), ("U", 3): ("R", "Y", 0.53, 0.44)})
    search = find_repairs(scan, readings)
    assert search.total == 36  # 36 swaps make the cube valid; the camera's doubts pick the right one
    best = search.candidates[0]
    assert {(c.face, c.index, c.new) for c in best.changes} == {("U", 1, "R"), ("U", 3, "Y")}
    assert best.apply(scan) == truth
    assert [c.cost for c in search.candidates] == sorted(c.cost for c in search.candidates)


def test_centres_are_never_changed_and_three_changes_are_too_many():
    truth = real_cube()
    f = truth.facelets  # twist the U-R-F corner in place: 3 stickers move
    f["U"][8], f["R"][0], f["F"][2] = f["R"][0], f["F"][2], f["U"][8]
    search = find_repairs(CubeState(f))
    assert search.candidates == [] and search.checked > 0


def test_without_camera_readings_every_sticker_counts_the_same():
    scan = misread(real_cube(), {("U", 1): "O"})
    (change,) = find_repairs(scan).candidates[0].changes
    assert (change.old_confidence, change.new_confidence) == (1.0, 0.0)


def test_a_centre_problem_cannot_be_repaired_by_stickers():
    f = real_cube().facelets
    f["U"][4] = f["D"][4]  # two centres with the same colour
    assert find_repairs(CubeState(f)).candidates == []
