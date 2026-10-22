# Why a scanned cube can be unsolvable

The rules every real cube follows, and what breaks them.

## Nine of each colour

A real cube has exactly 9 stickers of each colour. If the scan shows 10 yellow and 8 white
stickers, at least one sticker was misread. This is the simplest check, and the most common
problem.

## Real pieces only

Every edge and corner must be a piece that exists. An edge with two opposite colours, like red
and orange, cannot exist. Each of the 12 edges and 8 corners must appear exactly once, so two
identical corners also mean a misread.

## Twist, flip and parity

Face turns can never twist a single corner in place, flip a single edge in place, or swap just
two pieces. So the total corner twist must be a multiple of 3, the total edge flip must be even,
and the corner and edge swaps must match (parity). Only 1 in 12 ways of putting the pieces
together can be solved. A cube that was taken apart and rebuilt wrongly can break these rules
too.

## How the app finds the misread stickers

The Smart repair search tries every change of one sticker, then of two stickers, and keeps only
the changes that make the cube valid. It ranks them by how unsure the camera was about those
stickers. The repair agent then proposes the best one, and nothing changes until you press
Apply.
