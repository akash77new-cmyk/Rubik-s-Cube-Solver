# Sticker colour classifier: test report

Trained 2026-10-24 17:48 UTC on commit `2657d84` by `python ml/train.py` (PyTorch 2.14.1). Made by the script; never edit the numbers by hand.

## Data

8 scans (432 stickers) to train, 2 other scans (108 stickers) to test. Split by scan, so the test lights and camera positions were never seen in training.

## Result

| Model | Correct on the test scans | Accuracy |
| --- | --- | --- |
| CNN | 105/108 | 97.2% |
| HSV detector (baseline) | 108/108 | 100.0% |

The CNN fixed 0 HSV mistake(s) and made 3 new one(s). Average confidence: 94%. It is less accurate than HSV, so the app keeps HSV (CUBE_COLOR_MODEL=auto).

| Test scan | Lighting | CNN | HSV |
| --- | --- | --- | --- |
| `20261024-170715-561a80` | glare | 53/54 | 54/54 |
| `20261024-171129-99637a` | dim | 52/54 | 54/54 |

## Per colour (CNN)

| Colour | Accuracy |
| --- | --- |
| White | 100.0% |
| Yellow | 100.0% |
| Red | 88.9% |
| Orange | 100.0% |
| Green | 100.0% |
| Blue | 94.4% |

## Confusion matrix (CNN; rows: true colour, columns: predicted)

| | W | Y | R | O | G | B |
|---|---|---|---|---|---|---|
| **W** | 18 | 0 | 0 | 0 | 0 | 0 |
| **Y** | 0 | 18 | 0 | 0 | 0 | 0 |
| **R** | 0 | 0 | 16 | 2 | 0 | 0 |
| **O** | 0 | 0 | 0 | 18 | 0 | 0 |
| **G** | 0 | 0 | 0 | 0 | 18 | 0 |
| **B** | 1 | 0 | 0 | 0 | 0 | 17 |

## Model

24,198 parameters, 40 epochs, input 32 x 32 BGR, ONNX file 98,316 bytes. OpenCV and PyTorch agree to within 2.4e-07 on the test crops. Training took 18 s.

With only a few test scans, one sticker moves the accuracy by about 1%: treat it as a rough number, and add scans in new lights to make it firmer.
