# 🧩 Rubik's Cube Solver

A real-time **computer vision-based Rubik's Cube Solver** built using **Python**, **OpenCV**, and the **Kociemba Two-Phase Algorithm**.

The application scans a physical 3×3 Rubik's Cube using a webcam, reconstructs its state through HSV-based color segmentation, computes an efficient solution, and interactively guides the user through every move using visual overlays while simultaneously rendering the cube's state in a dedicated viewer.

---

## ✨ Features

- 📷 Real-time webcam-based cube scanning
- 🎨 HSV color segmentation for sticker classification
- ⚙️ Automatic cube state generation
- 🧠 Efficient solving using the Kociemba Two-Phase Algorithm
- 🖥️ Interactive move guidance using graphical arrow overlays
- 🔄 Real-time cube state simulation after every move
- 📡 Live communication between solver and viewer using sockets
- 🧩 Separate visualization window displaying the current cube state
- 🎯 HSV calibration utility for adapting to different cameras and lighting conditions

---

# Project Architecture

```
                  Webcam
                     │
                     ▼
         HSV Color Detection
                     │
                     ▼
        Cube State Reconstruction
                     │
                     ▼
       Kociemba Two-Phase Solver
                     │
                     ▼
        Move Interpretation Layer
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
 Arrow Overlay            Cube State Simulation
         │                       │
         └───────────┬───────────┘
                     ▼
          Socket Communication
                     ▼
          Cube State Viewer
```

---

# Folder Structure

```
Rubiks-Cube-Solver/

├── cube_solver.py
├── cube_viewer.py
├── hsv_calibrator.py
├── assets/
│   ├── arrows/
│   ├── stickers/
├── requirements.txt
└── README.md
```

---

# Technologies Used

| Category | Technologies |
|----------|--------------|
| Language | Python 3 |
| Computer Vision | OpenCV |
| Numerical Computing | NumPy |
| Cube Solving | Kociemba Two-Phase Algorithm |
| Communication | Socket Programming |
| Data Serialization | Pickle |
| Image Processing | HSV Color Segmentation |

---

# How It Works

## 1. Scan the Cube

The user scans each face of the cube using the webcam.

Each sticker is sampled from predefined locations and classified using HSV color thresholds.

---

## 2. Generate Cube State

After all six faces are scanned, the application reconstructs the cube into the notation required by the Kociemba solver.

Example:

```
UUUUUUUUU
RRRRRRRRR
FFFFFFFFF
DDDDDDDDD
LLLLLLLLL
BBBBBBBBB
```

---

## 3. Compute Solution

The generated cube state is passed to the Kociemba Two-Phase Algorithm, which computes an efficient solution sequence.

Example:

```
R U R' F2 D L2 ...
```

---

## 4. Interactive Solving

Instead of displaying all moves at once, the application guides the user one move at a time.

Each move is visualized using custom graphical overlays.

After the user performs a move, the internal cube state is updated and transmitted to the viewer.

---

## 5. Live Cube Visualization

A dedicated viewer continuously receives cube state updates through socket communication and renders the cube after every move.

This allows users to verify their progress throughout the solving process.

---

# HSV Calibration

Different cameras, Rubik's Cubes, and lighting conditions produce different HSV values.

This project includes an HSV calibration utility to simplify threshold selection.

## Calibration Steps

1. Run the calibration tool.

```
python hsv_calibrator.py
```

2. Adjust the HSV sliders until only the desired sticker color is detected.

3. Repeat for all six colors.

4. Update the thresholds inside:

```
classify_hue()
```

within

```
cube_solver.py
```

---

# Installation

Clone the repository

```bash
git clone https://github.com/<username>/Rubiks-Cube-Solver.git

cd Rubiks-Cube-Solver
```

Install dependencies

```bash
pip install -r requirements.txt
```

---

# Running the Project

Start the cube viewer

```bash
python cube_viewer.py
```

Open another terminal

Run the solver

```bash
python cube_solver.py
```

(Optional)

Run the calibration tool

```bash
python hsv_calibrator.py
```

---

# Controls

## During Cube Scanning

| Key | Action |
|-----|--------|
| U | Scan Up face |
| R | Scan Right face |
| F | Scan Front face |
| D | Scan Down face |
| L | Scan Left face |
| B | Scan Back face |
| ESC | Finish scanning |

---

## During Solving

| Key | Action |
|-----|--------|
| SPACE | Confirm current move |
| ESC | Exit application |

---

# Current Limitations

- Designed for standard **3×3×3 Rubik's Cubes**
- HSV thresholds require calibration for different environments
- Currently supports a single connected viewer
- Depends on adequate lighting for accurate color detection

---

# Future Improvements

- 📊 Save solve history and session statistics
- 🎨 Modern graphical user interface
- 🧠 Automatic HSV calibration
- 📈 Solve analytics and performance metrics
- 🧩 Support for additional cube sizes (2×2×2 and 4×4×4)
- 🌐 Cross-platform executable builds
- ⚡ Performance optimization and modular architecture
- 🤖 AI-assisted color detection for improved robustness

---

# Author

**Akash Srivastava**

Computer Science Undergraduate (2024-2028)
BITS Pilani, Hyderabad Campus

---

### ⭐ If you found this project interesting, consider starring the repository.
