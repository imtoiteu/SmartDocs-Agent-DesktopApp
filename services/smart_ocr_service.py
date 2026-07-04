"""
SmartDocs Platform — Smart OCR Service
======================================
Standard OCR remains the canonical PaddleOCR path.
Smart OCR runs the same PaddleOCR pass first, then optionally post-processes
the extracted text lines with the local Qwen model.
"""

import json
import copy
import logging
import re
import time
from typing import List

from services import ai_rewrite_service, ocr_service

logger = logging.getLogger(__name__)

_BATCH_SIZE = 4
_MAX_BATCH_CHARS = 520
_RAW_LOG_CHARS = 1200


def run_standard_ocr(image_path: str, engine_name: str | None = None) -> dict:
    """Run OCR with the selected engine."""
    result = ocr_service.run_ocr(image_path, engine_name=engine_name)
    result["ai_enhancement"] = False
    result["smart_applied"] = False
    result["smart_flow"] = "standard_only"
    return result


def _build_correction_messages(lines: List[str]) -> list:
    payload = json.dumps(lines, ensure_ascii=False)
    return [
        {
            "role": "system",
            "content": (
                "Bạn là bộ hậu xử lý OCR cho tiếng Việt và tiếng Anh. "
                "Nhiệm vụ duy nhất là sửa lỗi OCR rõ ràng: dấu tiếng Việt, ký tự sai, khoảng trắng, dấu câu, viết hoa đầu câu khi hiển nhiên. "
                "Giữ nguyên ý nghĩa, số dòng và thứ tự. "
                "Giữ nguyên tên riêng, số, ngày tháng, mã điều luật, mã hồ sơ, URL, email, số tài khoản, biển số, số tiền và các chuỗi kỹ thuật nếu không chắc chắn. "
                "Không thêm nội dung mới. Không diễn giải. Không tóm tắt. Không dịch. Không markdown. "
                "Nếu không chắc thì giữ nguyên dòng gốc. "
                "Chỉ trả về đúng một JSON array gồm cùng số lượng chuỗi như đầu vào."
            ),
        },
        {
            "role": "user",
            "content": (
                "Hãy sửa từng dòng OCR dưới đây.\n"
                "Ví dụ:\n"
                "- \"Cong hoa xa hoi chu nghia Viet Nam\" -> \"Cộng hòa xã hội chủ nghĩa Việt Nam\"\n"
                "- \"Dieu 12 . Nghia vu cua ben A\" -> \"Điều 12. Nghĩa vụ của bên A\"\n"
                "- \"Ngay 01/02/2024\" -> giữ nguyên định dạng ngày nếu đã đúng\n"
                "- \"NGUYEN VAN A\" -> giữ nguyên tên riêng nếu không chắc về dấu\n\n"
                f"INPUT_LINES = {payload}"
            ),
        },
    ]


def _build_single_line_messages(line: str) -> list:
    return [
        {
            "role": "system",
            "content": (
                "Bạn là bộ sửa lỗi OCR một dòng cho tiếng Việt và tiếng Anh. "
                "Chỉ sửa lỗi OCR rõ ràng về dấu, ký tự, khoảng trắng và dấu câu. "
                "Không thêm nội dung mới. Không giải thích. Không markdown. "
                "Giữ nguyên số, mã, tên riêng và dữ liệu nhạy cảm nếu không chắc chắn. "
                "Chỉ trả về đúng một dòng văn bản đã sửa."
            ),
        },
        {
            "role": "user",
            "content": f"Sửa dòng OCR sau nếu có lỗi, nếu không chắc thì giữ nguyên:\n{line}",
        },
    ]


def _preview(text: str, limit: int = _RAW_LOG_CHARS) -> str:
    text = (text or "").replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _extract_json_array(raw: str):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON array found in model output")
    return json.loads(raw[start : end + 1])


def _extract_single_line(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:text|json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except Exception:
            pass
    return raw.splitlines()[0].strip() if raw else ""


def _digit_signature(text: str) -> List[str]:
    return re.findall(r"\d+", text)


def _normalized_compare(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _change_stats(original: str, corrected: str) -> tuple[int, int]:
    line_changed = int(_normalized_compare(original) != _normalized_compare(corrected))
    char_changed = sum(1 for a, b in zip(original, corrected) if a != b) + abs(len(original) - len(corrected))
    return line_changed, char_changed


def _letters_only(text: str) -> str:
    return re.sub(r"[^A-Za-zÀ-ỹà-ỹ]", "", text or "")


def _looks_sensitive(original: str) -> bool:
    text = original or ""
    if len(_digit_signature(text)) >= 3:
        return True
    if re.search(r"(điều|khoản|mục|qđ|qd|cv|hđ|hd|mst|msdn)\s*\d+", text, re.I):
        return True
    if re.search(r"[A-Z]{2,}\d{2,}|[A-Z0-9]{6,}", text):
        return True
    if re.search(r"https?://|www\.|@", text):
        return True
    return False


def _is_safe_line_update(original: str, corrected: str) -> bool:
    if not isinstance(corrected, str):
        return False

    original = original or ""
    corrected = corrected.strip()

    if not corrected:
        return False
    if _digit_signature(original) != _digit_signature(corrected):
        return False
    if _looks_sensitive(original) and _letters_only(original).lower() != _letters_only(corrected).lower():
        return False

    max_len = max(len(original) * 3 + 20, 160)
    min_len = max(1, len(original) // 5)
    if len(corrected) > max_len or len(corrected) < min_len:
        return False

    return True


def _chunk_lines(lines: List[str]) -> List[List[str]]:
    batches = []
    current = []
    current_chars = 0

    for line in lines:
        line = line[:240]
        projected = current_chars + len(line)
        if current and (len(current) >= _BATCH_SIZE or projected > _MAX_BATCH_CHARS):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(line)
        current_chars += len(line)

    if current:
        batches.append(current)
    return batches


def _batch_token_budget(batch: List[str]) -> int:
    chars = sum(len(x) for x in batch)
    return min(180, max(48, chars // 5))


def _run_qwen_batch(batch: List[str], batch_idx: int) -> tuple[List[str], int]:
    messages = _build_correction_messages(batch)
    logger.info(
        "[SmartOCR] Qwen correction prompt batch=%s lines=%s payload=%s",
        batch_idx,
        len(batch),
        _preview(messages[-1]["content"]),
    )
    t0 = time.time()
    raw, _engine = ai_rewrite_service.run_local_messages(
        messages,
        max_new_tokens=_batch_token_budget(batch),
        max_input_tokens=1200,
        temperature=0.0,
        do_sample=False,
        repetition_penalty=1.02,
    )
    latency_ms = round((time.time() - t0) * 1000)
    logger.info(
        "[SmartOCR] Raw Qwen output batch=%s engine=%s latency_ms=%s output=%s",
        batch_idx,
        _engine,
        latency_ms,
        _preview(raw),
    )
    parsed = _extract_json_array(raw)
    if not isinstance(parsed, list) or len(parsed) != len(batch):
        raise ValueError("Model returned an invalid line count")
    return parsed, latency_ms


def _run_qwen_single_line(line: str, line_idx: int) -> tuple[str, int]:
    messages = _build_single_line_messages(line)
    t0 = time.time()
    raw, _engine = ai_rewrite_service.run_local_messages(
        messages,
        max_new_tokens=min(96, max(24, len(line) // 4 + 16)),
        max_input_tokens=512,
        temperature=0.0,
        do_sample=False,
        repetition_penalty=1.01,
    )
    latency_ms = round((time.time() - t0) * 1000)
    logger.info(
        "[SmartOCR] Raw Qwen single-line output line=%s engine=%s latency_ms=%s output=%s",
        line_idx,
        _engine,
        latency_ms,
        _preview(raw, 320),
    )
    return _extract_single_line(raw), latency_ms


def _correct_lines_with_qwen(lines: List[str]) -> tuple[List[str], int, bool]:
    corrected_all = []
    total_latency_ms = 0
    parser_fallback = False

    for batch_idx, batch in enumerate(_chunk_lines(lines), start=1):
        try:
            parsed, latency_ms = _run_qwen_batch(batch, batch_idx)
            corrected_all.extend(parsed)
            total_latency_ms += latency_ms
        except Exception as batch_err:
            parser_fallback = True
            logger.warning(
                "[SmartOCR] Batch parse/correction fallback batch=%s err=%s; switching to single-line mode",
                batch_idx,
                batch_err,
            )
            for offset, line in enumerate(batch, start=1):
                corrected, latency_ms = _run_qwen_single_line(line, (batch_idx - 1) * _BATCH_SIZE + offset)
                corrected_all.append(corrected or line)
                total_latency_ms += latency_ms

    if len(corrected_all) != len(lines):
        raise ValueError("Corrected output length mismatch")
    return corrected_all, total_latency_ms, parser_fallback


def _apply_ai_enhancement(result: dict) -> bool:
    items = result.get("results") or []
    if not items:
        result["smart_engine"] = "standard_no_text"
        return False

    status = ai_rewrite_service.get_ai_status()
    if not status.get("local"):
        reason = "warming_up" if status.get("local_loading") else "unavailable"
        result["smart_engine"] = f"fallback:{reason}"
        result["smart_fallback_reason"] = reason
        return False

    original_lines = [str(item.get("text") or "") for item in items]
    if not any(line.strip() for line in original_lines):
        result["smart_engine"] = "standard_empty_text"
        return False

    try:
        corrected_lines, qwen_latency_ms, parser_fallback = _correct_lines_with_qwen(original_lines)
    except Exception as e:
        logger.warning("[SmartOCR] Parser/model fallback to original text: %s", e)
        result["smart_parser_fallback"] = True
        raise

    result["smart_parser_fallback"] = parser_fallback
    result["qwen_latency_ms"] = qwen_latency_ms

    changed = False
    changed_lines = 0
    changed_chars = 0
    rejected_lines = 0
    for item, original, corrected in zip(items, original_lines, corrected_lines):
        line_changed, char_delta = _change_stats(original, corrected)
        if not _is_safe_line_update(original, corrected):
            if line_changed:
                rejected_lines += 1
                logger.info(
                    "[SmartOCR] Rejected correction original=%s corrected=%s",
                    _preview(original, 220),
                    _preview(corrected, 220),
                )
            continue
        corrected = corrected.strip()
        if corrected != original:
            item["text"] = corrected
            changed = True
            changed_lines += line_changed
            changed_chars += char_delta
            logger.info(
                "[SmartOCR] Accepted correction original=%s corrected=%s chars_changed=%s",
                _preview(original, 220),
                _preview(corrected, 220),
                char_delta,
            )

    if changed:
        local_path = status.get("local_path") or status.get("local_model") or "local-qwen"
        result["smart_engine"] = f"qwen_local:{local_path}"
    else:
        result["smart_engine"] = "qwen_local:no_changes"
    result["smart_changed_lines"] = changed_lines
    result["smart_changed_chars"] = changed_chars
    result["smart_rejected_lines"] = rejected_lines
    return changed


def run_smart_ocr_from_standard_result(standard_result: dict, flow: str = "reuse_standard_output") -> dict:
    """Run Smart OCR starting from an existing Standard OCR result."""
    t0 = time.time()
    result = copy.deepcopy(standard_result)
    result["ai_enhancement"] = True
    result["smart_applied"] = False
    result["smart_flow"] = flow

    try:
        applied = _apply_ai_enhancement(result)
        result["smart_applied"] = applied
        logger.info(
            "[SmartOCR] mode=smart flow=%s engine=%s applied=%s fallback=%s changed_lines=%s changed_chars=%s rejected_lines=%s parser_fallback=%s qwen_latency_ms=%s",
            result.get("smart_flow", "unknown"),
            result.get("smart_engine", "unknown"),
            applied,
            result.get("smart_fallback_reason", "-"),
            result.get("smart_changed_lines", 0),
            result.get("smart_changed_chars", 0),
            result.get("smart_rejected_lines", 0),
            result.get("smart_parser_fallback", False),
            result.get("qwen_latency_ms", 0),
        )
    except Exception as e:
        logger.warning(f"[SmartOCR] AI enhancement failed, using standard result: {e}")
        result["smart_applied"] = False
        result["smart_engine"] = "fallback:error"
        result["smart_fallback_reason"] = "error"
        result.setdefault("smart_parser_fallback", True)
        result.setdefault("qwen_latency_ms", 0)

    result["elapsed_ms"] = round((time.time() - t0) * 1000)
    return result


def run_ocr_pipeline(
    image_path: str,
    engine_name: str | None = None,
    apply_ai: bool = False,
    standard_result: dict | None = None,
) -> dict:
    """Dispatch to the requested OCR pipeline."""
    if apply_ai:
        if standard_result is not None:
            return run_smart_ocr_from_standard_result(standard_result, flow="reuse_standard_output")
        standard_result = run_standard_ocr(image_path, engine_name=engine_name)
        return run_smart_ocr_from_standard_result(standard_result, flow="full_pipeline")
    return run_standard_ocr(image_path, engine_name=engine_name)
