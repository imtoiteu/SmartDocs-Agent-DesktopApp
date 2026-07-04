from __future__ import annotations

from abc import ABC, abstractmethod


class OCREngine(ABC):
    """Common interface for OCR engine adapters."""

    engine_name = "base"

    @abstractmethod
    def run(self, image_path: str) -> dict:
        """Run OCR on an image path and return the standard SmartDocs shape."""

