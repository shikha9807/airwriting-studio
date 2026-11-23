# Air Writing Studio

A local-first air-writing app with FastAPI, SQLite/SQLAlchemy persistence, OpenCV PNG export, hand tracking, undo/redo, and downloadable database requirements/schema.

## Install and run the web app

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r dev-requirements.txt
python -m uvicorn airwriting.main:app --reload
```

Open http://127.0.0.1:8000. Camera capture needs browser permission and works on localhost or HTTPS. Pointer and touch drawing work without camera access. Webcam video stays in the browser and is not uploaded.

## Run the OpenCV desktop HUD

```sh
python run_camera.py
```

Press `q` or Escape to quit, `c` to clear, `u` to undo. The runner uses MediaPipe Tasks HandLandmarker (21 landmarks) and the local `models/hand_landmarker.task` asset (Google-hosted official model: https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task). It reconnects after camera read failures and always closes the landmarker, camera, and OpenCV windows on exit. Set `AIRWRITING_HAND_MODEL` to override the model path.

## Configuration

- `AIRWRITING_DATABASE_URL`: SQLAlchemy connection URL. Default: project-local `data/airwriting.db`.
- `AIRWRITING_EXPORTS_DIR`: export directory. Default: project-local `exports/`.
- `AIRWRITING_CAMERA_INDEX`: camera index for `run_camera.py` (default `0`).
- `AIRWRITING_RECONNECT_ATTEMPTS`: camera retry limit; `0` retries until the user quits.

Run the API with `python run_server.py [--host 127.0.0.1 --port 8000 --reload]` or `python -m uvicorn airwriting.main:app`. The API binds to localhost by default; configure an authenticated reverse proxy before exposing it publicly.

## Browser ML dependencies and offline fallback

Pointer/touch drawing is bundled and needs no external script. On camera start, the dashboard checks the local optional vendor path `airwriting/static/vendor/hands/hands.js` and then the MediaPipe Hands CDN. If both fail, the camera preview remains available, a visible message explains that tracking is unavailable, and pointer drawing remains usable. For offline deployments, put the MediaPipe Hands browser package and its matching runtime assets under `airwriting/static/vendor/hands/`.

OCR is opt-in. On save, the app checks `airwriting/static/vendor/tesseract/tesseract.min.js` and then Tesseract.js CDN. If OCR script, worker, or language resources fail, it reports the error and saves without recognized text. Offline deployments must vendor the matching Tesseract worker, WASM core, and English trained data under `airwriting/static/vendor/tesseract/`. The database API does not depend on browser ML libraries.

## API

- `GET /api/health`
- `POST /api/sessions`, `GET /api/sessions`, `GET /api/sessions/{id}`, `DELETE /api/sessions/{id}`
- `POST /api/export/png`, `GET /api/sessions/{id}/png`
- `GET /api/database/requirements/download`: ZIP of Markdown requirements, JSON metadata, and SQL schema with attachment headers.
- `POST /api/database/requirements/export`: atomically writes the same package to the configured exports directory. FastAPI runs the synchronous handler in its worker pool, outside realtime camera processing.

Session saves use one SQLAlchemy transaction and rollback on failure. SQLite connections enforce foreign keys and a busy timeout. Export filenames are fixed and validated, paths are resolved, package writes use a temporary file and atomic replacement, and PNG dimensions/brush properties are bounded.

## Tests

```sh
python -m pytest
```

The suite covers imports/table creation, session CRUD, PNG generation, requirements download/export, invalid inputs, path-shaped IDs, and MediaPipe model initialization/teardown.

## Project Overview
Air Writing Studio is an interactive computer vision and full-stack application that tracks real-time hand and index-finger movement to draw strokes on a virtual canvas[cite: 1, 2, 3, 5]. It combines an OpenCV and MediaPipe (`HandLandmarker`) tracking pipeline[cite: 1, 2, 5] with a FastAPI web dashboard, SQLAlchemy persistence, PNG and database requirements exports (Markdown, SQL, JSON), and automated tests[cite: 4, 5].

## System Architecture
- **Computer Vision & Stroke Engine (`OpenCV`, `MediaPipe` `HandLandmarker`, `NumPy`):** Captures live webcam frames, detects hand landmarks, tracks index-finger coordinates, maps points onto a canvas, maintains continuous strokes while writing, and separates strokes when lifting the finger or jumping across frames[cite: 1, 2, 5].
- **Reliability & Safeguards:** Includes automatic camera reconnection after read failures, clean release of camera and landmark resources on exit, prevention of accidental connecting lines across stroke jumps, transactional database saves, and atomic requirement export writes[cite: 4, 5].
- **Backend API & Persistence (`FastAPI`, `Uvicorn`, `SQLAlchemy`):** Serves the web dashboard and API endpoints, persists drawing/session data, generates PNG exports, and packages downloadable database requirements bundles in Markdown, SQL, and JSON formats[cite: 4, 5].
- **Frontend & Verification (`HTML/JS`, `pytest`):** Provides browser webcam/OCR support with local-first asset fallbacks and a pointer-drawing fallback[cite: 4, 5], paired with automated `pytest` tests and live endpoint checks[cite: 4, 5].
