"""FastAPI backend server for the Offline ASR system.

Run:
    python server.py            # starts on http://localhost:8000

Endpoints (all JSON):
    GET  /health                     liveness probe
    GET  /api/v1/status              system + model status
    GET  /api/v1/model-info          Whisper model details
    GET  /api/v1/supported-formats   allowed audio extensions
    GET  /api/v1/languages           common language codes
    POST /api/v1/transcribe          multipart audio upload -> transcript

Also serves the glass-design frontend from ./frontend at "/".

Design notes:
  * The Whisper model comes from models.py (WhisperModelManager) and is
    loaded lazily on the first transcription request, so startup is instant.
  * If FastAPI/uvicorn are not installed, a minimal stdlib fallback server
    provides the same endpoints so the frontend keeps working (useful on
    machines where dependencies are not set up yet). Install the real stack
    with:  pip install fastapi uvicorn python-multipart
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8001"))
API_PREFIX = os.getenv("API_PREFIX", "/api/v1")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_SIZE", "500"))

SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}
LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "hi": "Hindi", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
    "ru": "Russian", "ar": "Arabic", "pt": "Portuguese", "it": "Italian",
}

# ---------------------------------------------------------------- model glue
try:
    # models.py imports `whisper` at module level; guard so the API can still
    # boot (and report a clear error) when Whisper is not installed yet.
    # pyrefly: ignore [missing-import]
    from models import get_model_manager  # noqa: E402
    _MODELS_AVAILABLE = True
except Exception as _exc:  # pragma: no cover
    _MODELS_AVAILABLE = False
    _MODELS_ERROR = str(_exc)


def model_info() -> dict:
    if not _MODELS_AVAILABLE:
        return {
            "model_size": os.getenv("MODEL_SIZE", "small"),
            "device": os.getenv("DEVICE", "cpu"),
            "language": os.getenv("LANGUAGE", "en"),
            "model_loaded": False,
            "error": f"whisper not installed: {_MODELS_ERROR}",
        }
    return get_model_manager().get_model_info()


def run_transcription(tmp_path: str, language: str | None) -> dict:
    """Shared by both server implementations: file path -> response dict."""
    started = time.perf_counter()
    if _MODELS_AVAILABLE:
        manager = get_model_manager()
        model = manager.load_model()
        result = model.transcribe(
            tmp_path, language=language or manager.language or None
        )
        text = (result.get("text") or "").strip()
        detected = result.get("language", language or "unknown")
        segments = result.get("segments") or []
        duration = float(segments[-1]["end"]) if segments else 0.0
    else:
        size_kb = Path(tmp_path).stat().st_size / 1024
        text = (
            f"[stub] received {size_kb:.1f} KB of audio. Install openai-whisper "
            "(pip install -r requirement.txt) for real transcription."
        )
        detected, duration = language or "en", 0.0
    return {
        "success": True,
        "transcript": text,
        "language": detected,
        "duration": round(duration, 2),
        "processing_time": round(time.perf_counter() - started, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ================================================================= FastAPI
def build_fastapi_app():
    # pyrefly: ignore [missing-import]
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    # pyrefly: ignore [missing-import]
    from fastapi.middleware.cors import CORSMiddleware
    # pyrefly: ignore [missing-import]
    from fastapi.responses import JSONResponse
    # pyrefly: ignore [missing-import]
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(
        title="Offline Speech Recognition System (ASR)",
        description="Local Whisper transcription over a REST API.",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.get(f"{API_PREFIX}/status")
    def status():
        return {"status": "ok", "model": model_info(), "max_upload_mb": MAX_UPLOAD_MB}

    @app.get(f"{API_PREFIX}/model-info")
    def get_model_info_route():
        return model_info()

    @app.get(f"{API_PREFIX}/supported-formats")
    def supported_formats():
        return {"formats": sorted(f.lstrip(".") for f in SUPPORTED_FORMATS)}

    @app.get(f"{API_PREFIX}/languages")
    def languages():
        return {"languages": LANGUAGES, "auto_detect": True}

    @app.post(f"{API_PREFIX}/transcribe")
    async def transcribe(file: UploadFile = File(...), language: str = Form(default="")):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED_FORMATS:
            raise HTTPException(400, f"Unsupported format '{suffix}'. "
                                     f"Allowed: {sorted(SUPPORTED_FORMATS)}")
        data = await file.read()
        if not data:
            raise HTTPException(400, "Empty file")
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, "File too large")

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            return JSONResponse(run_transcription(tmp_path, language or None))
        except Exception as exc:
            raise HTTPException(500, f"Transcription failed: {exc}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")
    return app


# ====================================================== stdlib fallback
def run_fallback_server() -> None:
    """Minimal http.server implementation of the same API (no dependencies).

    Lets the frontend run before FastAPI is installed. Multipart parsing here
    is intentionally simple: it extracts the first file part of the request.
    """
    import re
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path):
            f = (FRONTEND_DIR / (path.lstrip("/") or "index.html")).resolve()
            if not str(f).startswith(str(FRONTEND_DIR)) or not f.is_file():
                self.send_error(404)
                return
            ctype = {"html": "text/html", "css": "text/css", "js": "text/javascript"}\
                .get(f.suffix.lstrip("."), "application/octet-stream")
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self._json({"status": "healthy"})
            elif self.path == f"{API_PREFIX}/status":
                self._json({"status": "ok", "model": model_info(),
                            "max_upload_mb": MAX_UPLOAD_MB})
            elif self.path == f"{API_PREFIX}/model-info":
                self._json(model_info())
            elif self.path == f"{API_PREFIX}/supported-formats":
                self._json({"formats": sorted(f.lstrip(".") for f in SUPPORTED_FORMATS)})
            elif self.path == f"{API_PREFIX}/languages":
                self._json({"languages": LANGUAGES, "auto_detect": True})
            else:
                self._static(self.path)

        def do_POST(self):
            if self.path != f"{API_PREFIX}/transcribe":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            ctype = self.headers.get("Content-Type", "")
            m = re.search(r'boundary=([^;]+)', ctype)
            if not m:
                self._json({"detail": "expected multipart/form-data"}, 400)
                return
            boundary = m.group(1).strip('"').encode()
            filename, payload = "upload.wav", b""
            for part in body.split(b"--" + boundary):
                if b"filename=" in part:
                    head, _, content = part.partition(b"\r\n\r\n")
                    fm = re.search(rb'filename="([^"]*)"', head)
                    if fm:
                        filename = fm.group(1).decode(errors="replace")
                    payload = content.rstrip(b"\r\n-")
                    break
            suffix = Path(filename).suffix.lower() or ".wav"
            if suffix not in SUPPORTED_FORMATS:
                self._json({"detail": f"Unsupported format '{suffix}'"}, 400)
                return
            if not payload:
                self._json({"detail": "Empty file"}, 400)
                return
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(payload)
                tmp_path = tmp.name
            try:
                self._json(run_transcription(tmp_path, None))
            except Exception as exc:
                self._json({"detail": str(exc)}, 500)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        # pyrefly: ignore [bad-override-param-name]
        def log_message(self, fmt, *args):  # quieter default logging
            print("[api]", fmt % args)

    print(f"! FastAPI/uvicorn not installed -- running stdlib fallback server")
    print(f"  (full API + docs: pip install fastapi uvicorn python-multipart)")
    print(f"* Serving on http://localhost:{API_PORT}  (UI at /, API at {API_PREFIX})")
    ThreadingHTTPServer((API_HOST, API_PORT), Handler).serve_forever()


# ================================================================== entry
def _port_in_use(host: str, port: int) -> bool:
    """Return True if *port* is already bound on *host*."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host if host != "0.0.0.0" else "127.0.0.1", port))
        except OSError:
            return True
    return False


def main() -> None:
    if _port_in_use(API_HOST, API_PORT):
        print(
            f"! Port {API_PORT} is already in use — the backend is probably "
            f"running already (started by desktop.py?).\n"
            f"  Open http://localhost:{API_PORT} in your browser or run "
            f"'python frontend/desktop.py' instead."
        )
        return
    try:
        # pyrefly: ignore [missing-import]
        import uvicorn
        app = build_fastapi_app()
        print(f"* FastAPI server on http://localhost:{API_PORT}  (docs at /docs)")
        uvicorn.run(app, host=API_HOST, port=API_PORT)
    except ImportError:
        run_fallback_server()


if __name__ == "__main__":
    main()
