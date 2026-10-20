"""Shared test setup.

backend.config reads environment variables at import time, so they are set here,
before any test module imports the backend. Tests must never touch the real data/
folder or the committed ml/data/ dataset, so CUBE_DATA_DIR and CUBE_DATASET_DIR
point at throwaway temp folders.
"""

import os
import tempfile

os.environ["APP_ENV"] = "development"
os.environ["CUBE_DATA_DIR"] = tempfile.mkdtemp(prefix="cube-test-data-")
os.environ["CUBE_DATASET_DIR"] = tempfile.mkdtemp(prefix="cube-test-dataset-")
