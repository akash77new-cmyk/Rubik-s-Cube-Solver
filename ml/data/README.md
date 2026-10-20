# Sticker colour dataset

Labelled images of Rubik's Cube stickers, collected with this app's scanner. The Phase 11
colour classifier is trained and evaluated on this data.

## What one example is

A **32 × 32 pixel colour image of one sticker** (PNG, as the camera saw it), with its
**true colour** (`W Y R O G B`) as the label.

## How it is collected

1. The scanner captures all six faces of a real cube with the camera.
2. Full validation (pieces, twist, flip, parity) must pass. Any sticker the camera got
   wrong is fixed by hand in the Cube Viewer first.
3. The user checks that the net matches the real cube, picks the lighting, and saves.

So every label is the **confirmed** colour, not the detector's guess.

## Layout

```
ml/data/scans/<scan id>/          one folder per saved scan (id = UTC time + random suffix)
    scan.json                     all labels and metadata for this scan
    U0.png ... B8.png             54 crops: face letter + sticker index 0-8 in reading order
```

## `scan.json` fields

| Field | Meaning |
|---|---|
| `schema` | Layout version (1) |
| `id`, `createdAt` | Scan id and UTC time |
| `lighting` | `daylight`, `warm`, `cool`, `dim`, `glare` or `other` |
| `profile` | HSV profile the detector used |
| `camera`, `detector` | Camera index/resolution/mirror; grid spacing, sample radius, crop size |
| `centers` | Centre colour of each face |
| `counts` | Stickers, corrected stickers, uncertain stickers |
| `stickers[]` | Per crop: `file`, `face`, `index`, `label` (true colour), `predicted` (HSV detector's colour), `corrected` (label ≠ predicted), `confidence`, `alternatives` (best 3 colours), `hsv`, `uncertain` (`null`, `no_range` or `two_ranges`) |

## Properties

- **Balanced:** every scan has exactly 9 stickers of each colour.
- **Hard examples marked:** `corrected: true` where the HSV detector was wrong.
- **Split by scan, not by sticker:** stickers from one scan share lighting and camera
  settings. Train/validation/test splits must keep whole scans together, otherwise the
  test score leaks and looks better than it really is.
- **Privacy:** only small sticker crops are stored, never full camera frames.
