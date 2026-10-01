"""Reading filings that are scans rather than text.

Some companies file results as images. HDFC Bank posts its statements that
way: the cover letter is born-digital and its text says "financial results", so
the document passes every text-based check, and then every statement page behind
it yields no characters at all. There was nothing to read and no way to say so -
the run reported only that no filing validated, which tells a reader nothing.

So the pages are rasterised and read optically. The result is deliberately
subject to the same rules as the text layer rather than a second, looser path:
the same arithmetic identities, the same refusal to publish a figure that does
not tie, the same withholding when a page cannot be corroborated. A bank read
this way is a bank whose numbers have been proven to add up, not a bank whose
figures were guessed from pixels.

What OCR costs is accuracy, and accuracy is spent where it matters:

- A misread label maps to no metric, so the figure is simply absent. Nothing
  false is produced; something true is missing.
- A misread digit produces a number that fails an identity, and the whole page
  is withheld.
- Anything the engine is unsure about is dropped rather than repaired.

Rendering and recognition are optional. A deployment without them still parses
every text filing, and reports a scan as a scan.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger("finora.india.ocr")


#: Raster scale. The text layer is exact, so this is only paid on scans, where
#: it is the difference between reading a row of six-digit figures and not.
#: 2.5x on an A4 page gives roughly 150 dpi, which is where small financial
#: digits stop losing their commas.
DEFAULT_SCALE = 2.5

#: Confidence below which a detected run of text is not trusted. Indian result
#: tables are dense, ruled and low-contrast; below this the recogniser is
#: inventing characters as often as reading them.
DEFAULT_MIN_CONFIDENCE = 0.5

#: A page rasterised beyond this many pixels is refused. OCR cost is linear in
#: area, and a hostile or merely enormous page should not be able to spend the
#: process's memory.
MAX_PIXELS = 24_000_000

_engine_lock = threading.Lock()
_engine: Any = None
_engine_failed = False


def available() -> bool:
    """True when both halves of the fallback are importable."""
    return _imports_ok()


def _imports_ok() -> bool:
    try:
        import numpy  # noqa: F401
        import pypdfium2  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _get_engine() -> Any:
    """Load the recognition model once, and remember if it will not load.

    Constructing the engine loads three ONNX models, which is far too expensive
    to repeat per page. A failure is cached too, so a deployment missing the
    dependency pays the import cost once rather than once per scanned page.
    """
    global _engine, _engine_failed
    if _engine is not None or _engine_failed:
        return _engine
    with _engine_lock:
        if _engine is not None or _engine_failed:
            return _engine
        try:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("[india.ocr] recognition engine unavailable: %s", exc)
            _engine_failed = True
    return _engine


def render_page(pdf: Any, index: int, scale: float = DEFAULT_SCALE) -> Optional[Any]:
    """Rasterise one page of an open pdfium document to a PIL image."""
    try:
        import pypdfium2 as pdfium
    except Exception:  # pragma: no cover - dependency is declared
        return None
    try:
        page = pdf[index]
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil().convert("RGB")
    except Exception as exc:
        logger.warning("[india.ocr] page %d could not be rendered: %s", index, exc)
        return None
    if image.width * image.height > MAX_PIXELS:
        logger.warning(
            "[india.ocr] page %d refused: %d pixels exceeds the limit",
            index, image.width * image.height,
        )
        return None
    return image


def read_words(image: Any, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> list[dict[str, Any]]:
    """Recognise a page image into positioned words.

    The boxes are returned in the same shape ``pdfplumber.extract_words``
    produces, which is what lets the OCR path and the text path share every
    decision made downstream of the words themselves.
    """
    engine = _get_engine()
    if engine is None:
        return []
    try:
        import numpy as np
    except Exception:  # pragma: no cover - dependency is declared
        return []

    try:
        result, _ = engine(np.array(image))
    except Exception as exc:
        logger.warning("[india.ocr] recognition failed: %s", exc)
        return []
    if not result:
        return []

    words: list[dict[str, Any]] = []
    for entry in result:
        try:
            box, text, confidence = entry[0], entry[1], entry[2]
        except (TypeError, IndexError, KeyError):
            continue
        text = (text or "").strip()
        if not text:
            continue
        # The confidence is a string in some engine builds, so it is coerced
        # before it is compared. A run whose confidence cannot be read is
        # treated as no confidence at all, and dropped.
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= confidence < 1.0) and confidence < 1.0:
            continue
        if confidence < min_confidence:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        if not xs or not ys:
            continue
        words.append({
            "text": text,
            "x0": min(xs), "x1": max(xs),
            "top": min(ys), "bottom": max(ys),
            "upright": True,
        })
    return words


def open_document(payload: bytes) -> Any:
    """Open a PDF for rasterisation, or return ``None`` if it cannot be opened."""
    try:
        import pypdfium2 as pdfium
    except Exception:  # pragma: no cover - dependency is declared
        return None
    try:
        return pdfium.PdfDocument(payload)
    except Exception as exc:
        logger.warning("[india.ocr] document could not be opened: %s", exc)
        return None


def read_document_pages(
    payload: bytes,
    page_numbers: list[int],
    *,
    scale: float = DEFAULT_SCALE,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> dict[int, tuple[list[dict[str, Any]], float, float]]:
    """Recognise the given 1-based page numbers.

    Each entry is ``(words, width, height)`` in *page* units - PDF points, the
    same units the text layer produces. Recognition works in image pixels, so
    every box is divided by the render scale on the way out. Keeping both
    readers in one set of units is what lets the column model, the row bands and
    the tolerances tuned for text all apply unchanged to a page that was read
    from an image.

    Pages that fail are simply absent. A missing page yields no metrics, which is
    the same outcome as a text page that could not be read, so a partial failure
    degrades to less data rather than to bad data.
    """
    out: dict[int, tuple[list[dict[str, Any]], float, float]] = {}
    if not page_numbers or not available():
        return out
    document = open_document(payload)
    if document is None:
        return out
    try:
        for number in page_numbers:
            image = render_page(document, number - 1, scale=scale)
            if image is None:
                continue
            words = read_words(image, min_confidence=min_confidence)
            if words:
                width, height = image.width / scale, image.height / scale
                for word in words:
                    for key in ("x0", "x1", "top", "bottom"):
                        word[key] /= scale
                out[number] = (words, width, height)
    finally:
        try:
            document.close()
        except Exception:
            pass
    return out
