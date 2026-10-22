# How the app's solver works

Why the app's solutions are short, and why they are not a human method.

## Kociemba's two-phase algorithm

The app uses Herbert Kociemba's two-phase algorithm. Phase one turns the cube into a special
group of positions that can be solved using only U, D and half turns of the other sides. Phase
two then solves it inside that group. Large precomputed tables tell the search how far away
the goal is, so it can skip hopeless branches.

## About 20 moves

The solutions are usually around 20 moves, close to the shortest possible. That is much shorter
than the beginner method, which takes over 100 moves. The app checks every solution by applying
it to the scanned cube and making sure the result is solved.

## Why it is hard to learn from

A computer solution does not build anything you can see step by step: the cube looks scrambled
until the last few moves. That is why the app shows each move with a plain-English instruction,
and why a person learns a layer-by-layer method instead.

## Why the cube must be valid first

The solver can only solve a real cube. If the scan breaks a rule, such as the colour counts or
the corner twist, no solution exists, so the app checks the cube first and helps you repair it.
