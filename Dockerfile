# syntax=docker/dockerfile:1
# Production image: React UI + vision engine + web server in one container.
#   docker build -t cube-solver .
#   docker run --rm -p 8000:8000 -e PORT=8000 -e FLASK_SECRET_KEY=dev cube-solver

# ---- 1. Build the React frontend -----------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Build Python wheels (kociemba is compiled from C source) ---------
FROM python:3.12-slim-bookworm AS wheels
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt requirements-prod.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-prod.txt

# ---- 3. Runtime image ------------------------------------------------------
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production

# opencv-python needs these system libraries on a slim Debian image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-prod.txt ./
COPY --from=wheels /wheels /wheels
RUN pip install --no-index --find-links=/wheels -r requirements-prod.txt \
 && rm -rf /wheels

# Fail the build early if a native library is broken, and pre-build the C
# solver's tables now (as root) so the first solve at runtime is instant.
RUN python -c "import cv2; print('OpenCV', cv2.__version__)" \
 && python -c "from kociemba.ckociembawrapper import lib; import kociemba; print(kociemba.solve('DRLUUBFBRBLURRLRUBLRDDFDLFUFUFFDBRDUBRUFLLFDDBFLUBLRBD'))"

COPY backend/ backend/
COPY assets/ assets/
COPY tools/ tools/
COPY run.py gunicorn.conf.py ./
COPY --from=frontend /build/frontend/dist frontend/dist

# Run as a normal user, not root.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 10000
CMD ["python", "run.py", "--prod"]
