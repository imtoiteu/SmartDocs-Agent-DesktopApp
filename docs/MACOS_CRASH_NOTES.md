# macOS crash notes — Paddle + Torch signal-handler SIGSEGV

Analysis of the crash report `Python-2026-07-04-145305.ips` (kept out of the repo).
Recorded here so future MacBook validation has a reference. **No user data is in
this file.**

## What crashed

| Field | Value |
|---|---|
| Process | Homebrew **Python 3.10.17** (`/opt/homebrew/.../Python.framework/Versions/3.10`) |
| Launched by | **Electron** (the desktop wrapper) → `responsibleProc: Electron` |
| Signal | **SIGSEGV** (segmentation fault 11), `EXC_CRASH` |
| Faulting thread | a **PaddlePaddle worker thread** parked in `EventCount::Park` / `ThreadPoolTempl::WaitForWork` (`libpaddle.so`) |
| Main thread (T0) | inside `libpaddle.so google::FailureSignalHandler → SymbolizeAndDemangle → DumpStackFrameInfo` |
| Native libs loaded in the same process | `libpaddle.so`, `libtorch*.dylib`, `onnxruntime`, `cv2` — all from the **main SmartDocs venv** |

## Root cause (not the diagnostics)

PaddlePaddle installs a **Google-glog `FailureSignalHandler`** that hijacks
`SIGSEGV`/`SIGABRT`. In this process **PaddlePaddle and PyTorch are loaded
together** (the main venv runs Flask + Paddle OCR + the Torch-based Qwen/chat
models in one process). When a fault occurs on a Paddle threadpool worker, Paddle's
own handler runs and tries to symbolize a stack — turning a condition that Python
would otherwise handle into a fatal crash dump.

This is **not** caused by `scripts/check_offline.sh` or
`config.check_offline_readiness()` — those only inspect the filesystem and never
import Paddle/Torch or load a model. The crash is the **running app** (Paddle+Torch
coexistence under Electron).

The GLM three-venv split is unaffected and correct:
- main venv → Flask + VietOCR + Paddle + Torch chat/rewrite
- `GLM-OCR/.venv-mlx` → MLX server
- `GLM-OCR/.venv-sdk` → glmocr CLI / layout

The Paddle+Torch coexistence is inside the **main venv**, independent of GLM.

## Mitigation applied in this change

`tools/setup_offline.py` loads Torch (Qwen download) and then PaddleOCR in one
process — the exact fragile combination. It now calls
`paddle.disable_signal_handler()` before initialising PaddleOCR (best-effort), so
Paddle no longer hijacks signals during setup. The default-LLM change to
**Qwen 2.5 1.5B on CPU** also lowers MPS memory pressure, which is aligned with the
policy that this MacBook should not run larger Qwen models on MPS.

## App-runtime guard (APPLIED — "Guard Paddle signal handler on macOS")

The same `paddle.disable_signal_handler()` guard is now applied in the **app
runtime**, before every Paddle initialisation. A single idempotent helper —
`services/ocr_engines/_paddle_guard.py` → `disable_paddle_signal_handler()` — is
called at each lazy Paddle init site:

- `services/ocr_engines/paddle_adapter.py` → `_get_ocr()` (Legacy PP-OCRv5)
- `services/ocr_engines/paddle_modern_adapter.py` → `_get_pipe()` (PP-StructureV3)
- `services/ocr_engines/vietocr_adapter.py` → `_get_detector()` (Paddle detector for VietOCR)

The helper imports `paddle` only where it is already about to be used, calls
`disable_signal_handler()` only when the attribute exists and is callable, runs at
most once per process, and never raises — so an older Paddle without the API, or a
machine without paddle, degrades silently. `tools/setup_offline.py` keeps its own
inline guard (it loads Torch + Paddle in one setup process too).

Behaviour is otherwise unchanged: Legacy/Modern Paddle OCR, VietOCR and GLM OCR all
work as before, and the main venv keeps `Pillow==10.2.0`.

## MacBook validation still needed

1. Reproduce (pre-fix): run the desktop (Electron) app, then trigger **Paddle/Modern
   OCR** on a document while a Torch chat/rewrite model is loaded.
2. With this guard, re-test the same flow and confirm the segfault no longer occurs
   and OCR results are unchanged.
3. Confirm the default local LLM is **Qwen 2.5 1.5B** end-to-end:
   `scripts/check_offline.sh` shows a single `Local LLM (chat/rewrite/agent)` row,
   chat + AI rewrite + agent all respond, and **no 3B download** happens.
4. Capture any new `.ips` if it still crashes and attach the faulting-thread
   backtrace.
