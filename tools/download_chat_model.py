#!/usr/bin/env python3
"""
SmartDocs Platform — Download the configured AI Chat model
==========================================================
Downloads whatever CHAT_MODEL resolves to (default: the local LLM
Qwen/Qwen2.5-1.5B-Instruct). Use this to OPT INTO a larger chat model: set
CHAT_MODEL=Qwen/Qwen2.5-3B-Instruct (or another id) in .env first, then run this.
For the standard 1.5B default, `tools/setup_offline.py` already downloads it.
The model is cached in models/huggingface/hub/ (same project-local cache as
every other model — never in ~/.cache/huggingface).

Usage:
    source .venv/bin/activate  (or your venv)
    # optional: export CHAT_MODEL=Qwen/Qwen2.5-3B-Instruct   # opt into a bigger model
    python tools/download_chat_model.py

Requirements:
    pip install transformers huggingface_hub
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import cfg

# Allow downloads for this script only
import os
os.environ.pop("HF_HUB_OFFLINE",       None)
os.environ.pop("TRANSFORMERS_OFFLINE",  None)

MODEL_ID = cfg.CHAT_MODEL  # default Qwen/Qwen2.5-1.5B-Instruct; larger models opt-in via .env

def check_exists(model_id: str) -> bool:
    # Project-local cache only (hub layout first, then legacy flat layout).
    return cfg.hf_snapshot_dir(model_id) is not None


def main():
    print("=" * 60)
    print("  SmartDocs AI Chat — Model Downloader")
    print("=" * 60)
    print(f"  Model      : {MODEL_ID}")
    print(f"  Cache dir  : {cfg.HF_HUB_DIR}")
    print(f"  Approx size: ~3 GB (1.5B) / ~6–7 GB (3B)")
    print()

    if check_exists(MODEL_ID):
        print(f"✅ {MODEL_ID} already downloaded — nothing to do.")
        return

    # Also check fallback
    fallback_id = cfg.FALLBACK_CHAT_MODEL
    if check_exists(fallback_id):
        print(f"ℹ️  Fallback model {fallback_id} already present.")
    else:
        print(f"⚠️  Fallback model {fallback_id} not found either.")
        print(f"   Run scripts/setup_offline.sh to download the 1.5B model.")

    print(f"\n⬇️  Downloading {MODEL_ID}...")
    print("   This may take 10–30 minutes depending on your internet speed.\n")

    try:
        from transformers import AutoTokenizer, AutoModelForCausalLM
        import torch

        t0 = time.time()

        print("  [1/2] Downloading tokenizer…")
        tok = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=str(cfg.HF_HUB_DIR))
        print("  [1/2] Tokenizer done.")

        print(f"  [2/2] Downloading model weights (dtype=float32 for CPU)…")
        mdl = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            torch_dtype=torch.float32,
            device_map=None,
            cache_dir=str(cfg.HF_HUB_DIR),
        )
        elapsed = round(time.time() - t0, 1)
        print(f"\n✅ {MODEL_ID} downloaded in {elapsed}s")
        print(f"   Cached at: {cfg.HF_HUB_DIR}")

        # Quick sanity test
        print("\n  Running quick inference test…")
        mdl.eval()
        msgs = [
            {"role": "system",  "content": "You are a helpful assistant."},
            {"role": "user",    "content": "Say 'SmartDocs AI ready' in one sentence."},
        ]
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = tok(prompt, return_tensors="pt", max_length=128, truncation=True)
        with torch.no_grad():
            out = mdl.generate(**inputs, max_new_tokens=30, do_sample=False, pad_token_id=tok.eos_token_id)
        answer = tok.decode(out[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
        print(f"  Model says: {answer}")
        print("\n✅ Model verified and ready for SmartDocs AI Chat!")

    except Exception as e:
        print(f"\n❌ Download failed: {e}")
        print("   Check your internet connection and try again.")
        print(f"   Fallback model ({fallback_id}) will be used if available.")
        sys.exit(1)


if __name__ == "__main__":
    main()
