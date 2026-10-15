"""
model_loader.py
===============
Loads the fine-tuned Llama 3.2 1B model completely offline.

  * Base model      : local ``models/llama-3.2-1b-instruct``
  * LoRA/QLoRA      : local ``adapters/llama-3.2-1b-qlora`` (attached via PEFT)
  * Quantization    : 4-bit NF4 + double quantization (bitsandbytes, CUDA)
  * Compute dtype   : BF16 when supported, otherwise FP16
  * Offline         : ``local_files_only=True`` everywhere; no network calls
  * Low memory      : ``low_cpu_mem_usage=True`` + device_map + 4-bit weights

All heavy imports are done inside the functions, so importing this module is
cheap (useful for tests that never touch the real model).

``build_generate_fn`` returns a ``generate(messages) -> str`` callable that the
agent controller uses. Injecting this callable keeps the controller testable
with a fake model (see tests/).
"""

from __future__ import annotations

import os
from pathlib import Path

import security

# Offline hardening: make absolutely sure nothing phones home even if some
# transitive code ignores local_files_only.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

DEFAULT_MODEL_DIR = str(security.MODELS_DIR / "llama-3.2-1b-instruct")
DEFAULT_ADAPTER_DIR = str(security.ADAPTERS_DIR / "llama-3.2-1b-qlora")


class ModelLoadError(Exception):
    pass


def _pick_compute_dtype():
    """BF16 if the GPU supports it, else FP16 on CUDA, else FP32 on CPU."""
    import torch
    if torch.cuda.is_available():
        try:
            if torch.cuda.is_bf16_supported():
                return torch.bfloat16
        except Exception:
            pass
        return torch.float16
    return torch.float32


def _dir_has_files(path: str) -> bool:
    p = Path(path)
    if not p.is_dir():
        return False
    return any(child.name != ".gitkeep" for child in p.iterdir())


def load_model_and_tokenizer(
    model_dir: str = DEFAULT_MODEL_DIR,
    adapter_dir: str | None = DEFAULT_ADAPTER_DIR,
    use_quant: bool = True,
    device_map: str = "auto",
):
    """Load the (quantized) base model + LoRA adapter + tokenizer, offline.

    Returns ``(model, tokenizer)``.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not _dir_has_files(model_dir):
        raise ModelLoadError(
            f"Base model directory '{model_dir}' is empty. "
            "Download the model first (see README > Model download)."
        )

    compute_dtype = _pick_compute_dtype()
    cuda = torch.cuda.is_available()

    # ---- tokenizer ----
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    except Exception as exc:
        raise ModelLoadError(f"Failed to load tokenizer from '{model_dir}': {exc}")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    # ---- base model ----
    model_kwargs = dict(local_files_only=True, low_cpu_mem_usage=True)
    if use_quant and cuda:
        model_kwargs.update(
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=compute_dtype,
            ),
            device_map=device_map,
            torch_dtype=compute_dtype,
        )
    else:
        # CPU (or --no-quant): bitsandbytes 4-bit needs CUDA, so skip it.
        model_kwargs.update(torch_dtype=compute_dtype)
        if cuda:
            model_kwargs.update(device_map=device_map)

    try:
        model = AutoModelForCausalLM.from_pretrained(model_dir, **model_kwargs)
    except Exception as exc:
        raise ModelLoadError(f"Failed to load base model from '{model_dir}': {exc}")

    if not cuda:
        model = model.to("cpu")

    # ---- LoRA / QLoRA adapter ----
    if adapter_dir and _dir_has_files(adapter_dir):
        try:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter_dir, local_files_only=True)
        except Exception as exc:
            raise ModelLoadError(f"Failed to attach LoRA adapter from '{adapter_dir}': {exc}")
    else:
        # Not fatal: run the base model so the pipeline still works.
        if adapter_dir:
            print(f"[model_loader] WARNING: no adapter files in '{adapter_dir}'. "
                  "Running the base model without the fine-tuned adapter.")

    model.eval()
    return model, tokenizer


def build_generate_fn(model, tokenizer, max_new_tokens: int = security.MAX_MODEL_NEW_TOKENS,
                      temperature: float = 0.0):
    """Return ``generate(messages) -> str`` using the Llama chat template.

    Deterministic (greedy) by default -- best for strict JSON output.
    """
    import torch

    # Resolve stop tokens (Llama 3.x uses <|eot_id|>).
    eos_ids = []
    if tokenizer.eos_token_id is not None:
        eos_ids.append(tokenizer.eos_token_id)
    try:
        eot = tokenizer.convert_tokens_to_ids("<|eot_id|>")
        if isinstance(eot, int) and eot >= 0 and eot not in eos_ids:
            eos_ids.append(eot)
    except Exception:
        pass
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id

    def generate(messages) -> str:
        input_ids = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt",
        )
        input_ids = input_ids.to(model.device)
        gen_kwargs = dict(
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0.0,
            eos_token_id=eos_ids or None,
            pad_token_id=pad_id,
            repetition_penalty=1.05,
        )
        if temperature > 0.0:
            gen_kwargs.update(temperature=temperature, top_p=0.9)
        with torch.no_grad():
            output = model.generate(input_ids, **gen_kwargs)
        new_tokens = output[0][input_ids.shape[-1]:]
        return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    return generate


def report_memory() -> dict:
    """Best-effort GPU memory report (for benchmarking / the CLI banner)."""
    try:
        import torch
        if not torch.cuda.is_available():
            return {"device": "cpu"}
        return {
            "device": torch.cuda.get_device_name(0),
            "allocated_mb": round(torch.cuda.memory_allocated() / 1e6, 1),
            "reserved_mb": round(torch.cuda.memory_reserved() / 1e6, 1),
        }
    except Exception:
        return {"device": "unknown"}
