"""Run the ASR Voice Console as a DESKTOP APPLICATION (Gradio edition).

    python frontend/desktop.py

What it does:
  Launches the Gradio-based ASR frontend. The Gradio app calls the
  Whisper model directly (in-process), so no separate FastAPI server is
  needed for the UI.

  If you need the REST API as well, run `python server.py` separately.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make project root importable regardless of where this is launched from
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from frontend.gradio_app import launch  # noqa: E402


def main() -> None:
    print("Starting ASR Voice Console (Gradio) …", flush=True)
    launch(inbrowser=False)


if __name__ == "__main__":
    main()
