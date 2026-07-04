"""Text correction: fix OCR errors, spelling, spacing, punctuation."""
import re

# Lazy module-level singleton for the English speller. Building Speller(lang='en')
# loads its word-frequency dictionary, so we construct it once and reuse it across
# requests instead of rebuilding it on every /api/correct call (F4).
_SPELLER = None
_SPELLER_FAILED = False


def _get_speller():
    global _SPELLER, _SPELLER_FAILED
    if _SPELLER is not None or _SPELLER_FAILED:
        return _SPELLER
    try:
        from autocorrect import Speller
        _SPELLER = Speller(lang='en')
    except Exception:
        _SPELLER_FAILED = True
    return _SPELLER

def _basic_clean(text):
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' ([,\.!?;:])', r'\1', text)
    text = re.sub(r'([,\.!?;:])([^\s\d"\'])', r'\1 \2', text)
    text = re.sub(r'\.{4,}', '...', text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line[0].isupper() and lines and lines[-1].endswith('.'):
            line = line[0].upper() + line[1:]
        lines.append(line)
    return "\n".join(lines).strip()

def correct(text: str) -> dict:
    import time
    t0 = time.time()
    original = text
    result = _basic_clean(text)

    # Try autocorrect for obvious misspellings (English only).
    # Uses the cached module-level speller so the dictionary is built once.
    spell = _get_speller()
    if spell is not None:
        try:
            corrected_words = []
            for word in result.split(' '):
                # Only fix purely alpha words to avoid corrupting proper nouns
                if word.isalpha() and word.islower() and len(word) > 3:
                    corrected_words.append(spell(word))
                else:
                    corrected_words.append(word)
            result = ' '.join(corrected_words)
        except Exception:
            pass

    ms = round((time.time() - t0) * 1000)
    changes = sum(1 for a, b in zip(original.split(), result.split()) if a != b)
    return {"corrected": result, "changes": changes, "elapsed_ms": ms}
