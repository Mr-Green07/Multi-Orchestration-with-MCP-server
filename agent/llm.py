"""agent/llm.py
============
Thin wrapper around llama.cpp with three properties that matter:

* **lazy import** - ``llama_cpp`` is imported only when a model is actually
  loaded, so the whole test suite, the doctor command and every read-only tool
  work on a machine that has no model at all;
* **lazy load** - the GGUF file is memory-mapped on first use, not at import;
* **graceful absence** - a missing runtime or model raises :class:`LLMUnavailable`
  with an actionable message instead of a traceback.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import config

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """Raised when no usable local model can be loaded."""


class LLM(Protocol):
    """Anything that can turn a message list into a JSON string."""

    name: str

    def complete(self, messages: Sequence[dict[str, str]],
                 schema: dict[str, Any] | None = None) -> str: ...


class LocalLLM:
    """A llama.cpp chat model, loaded on first use."""

    name = "llama.cpp"

    def __init__(
        self,
        model_path: Path | str | None = None,
        n_ctx: int | None = None,
        n_batch: int | None = None,
        n_gpu_layers: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        verbose: bool = False,
    ) -> None:
        self.model_path = Path(model_path or config.MODEL_PATH)
        self.n_ctx = n_ctx or config.LLM_N_CTX
        self.n_batch = n_batch or config.LLM_N_BATCH
        self.n_gpu_layers = config.LLM_GPU_LAYERS if n_gpu_layers is None else n_gpu_layers
        self.temperature = config.LLM_TEMPERATURE if temperature is None else temperature
        self.max_tokens = max_tokens or config.LLM_MAX_TOKENS
        self.verbose = verbose
        self._llm: Any = None

    # ------------------------------------------------------------------ loading
    @property
    def loaded(self) -> bool:
        return self._llm is not None

    def load(self):
        if self._llm is not None:
            return self._llm
        if not self.model_path.exists():
            raise LLMUnavailable(
                f"No GGUF model found at {self.model_path}.\n"
                "Place a quantised model there (Qwen3-4B Q4_K_M works well), or set "
                "AGENT_MODEL_PATH to its location. Read-only tools and the doctor "
                "command work without a model."
            )
        try:
            from llama_cpp import Llama  # imported here on purpose
        except ImportError as exc:
            raise LLMUnavailable(
                "The llama.cpp Python bindings are not installed. Install them with\n"
                "    pip install llama-cpp-python\n"
                "(or use the prebuilt wheel that matches your CUDA/CPU setup)."
            ) from exc

        logger.info("loading model %s (n_ctx=%s)", self.model_path.name, self.n_ctx)
        self._llm = Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_batch=self.n_batch,
            n_gpu_layers=self.n_gpu_layers,
            use_mmap=True,
            verbose=self.verbose,
        )
        return self._llm

    # ------------------------------------------------------------------ inference
    def complete(self, messages: Sequence[dict[str, str]],
                 schema: dict[str, Any] | None = None) -> str:
        llm = self.load()
        response_format: dict[str, Any] = {"type": "json_object"}
        if schema:
            response_format["schema"] = schema
        try:
            response = llm.create_chat_completion(
                messages=list(messages),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format=response_format,
            )
        except TypeError:
            # older llama.cpp builds do not accept a schema key
            response = llm.create_chat_completion(
                messages=list(messages),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
        return response["choices"][0]["message"]["content"] or ""


class ScriptedLLM:
    """Deterministic stand-in used by tests and by ``--offline-demo``."""

    name = "scripted"

    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages, schema=None) -> str:      # noqa: D401
        self.calls.append(list(messages))
        if not self.responses:
            return json.dumps({"action": "final", "answer": "no more scripted responses"})
        return self.responses.pop(0)


def load_default_llm() -> LLM:
    """Return the configured model, raising :class:`LLMUnavailable` if unusable."""
    llm = LocalLLM()
    llm.load()
    return llm


def llm_status() -> dict[str, Any]:
    """Non-fatal report used by ``agent doctor``."""
    import importlib.util

    runtime = importlib.util.find_spec("llama_cpp") is not None
    return {
        "model_path": str(config.MODEL_PATH),
        "model_present": Path(config.MODEL_PATH).exists(),
        "runtime_installed": runtime,
        "n_ctx": config.LLM_N_CTX,
        "gpu_layers": config.LLM_GPU_LAYERS,
        "usable": runtime and Path(config.MODEL_PATH).exists(),
    }
