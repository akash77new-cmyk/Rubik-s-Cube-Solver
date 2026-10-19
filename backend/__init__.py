"""Rubik's Cube Solver - backend package.

Layers
------
``backend.core``      Pure domain logic: cube state, move algebra, solver engine, colour model.
``backend.vision``    OpenCV camera capture, HSV sticker detection and frame overlays.
``backend.ipc``       Length-prefixed socket protocol used between the vision engine and the web server.
``backend.services``  Session orchestration, analytics and structured logging.
``backend.server``    Flask + Socket.IO application that serves the React frontend.

Nothing in ``core`` imports from ``server`` or ``vision`` - the domain layer stays
framework free and unit-testable on its own.
"""

__version__ = "2.0.0"
__all__ = ["__version__"]
