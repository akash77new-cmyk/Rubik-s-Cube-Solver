"""Shared test setup.

backend.config reads environment variables at import time, so they are set here,
before any test module imports the backend. Tests must never touch the real data/
folder, so CUBE_DATA_DIR points at a throwaway temp folder.
"""

import os
import tempfile

os.environ["APP_ENV"] = "development"
os.environ["CUBE_DATA_DIR"] = tempfile.mkdtemp(prefix="cube-test-data-")
