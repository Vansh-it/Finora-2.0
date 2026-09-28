"""Answer-completeness validator and repair.

Detects truncated / incomplete LLM output and attempts one continuation
repair pass. Signals checked:
  - provider finish_reason == "length"
  - unfinished markdown emphasis (**Operating  -> unclosed **)
  - unclosed code fence
  - abrupt sentence ending (no terminal punctuation on last line)
  - trailing heading/colon with no content
  - empty response

Repair is attempted at most MAX_REPAIR_PASSES times; never loops forever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_REPAIR_PASSES = 1

# Odd-but-plausible word fragments (e.g. "**Operating") are allowed to be
# "completed" only via a continuation call, never guessed locally.
_TRUNCATED_TAIL_RE = re.compile(r"(\*\*[^*\s][^*]{0,60})$", re.MULTILINE)


@dataclass
class ValidationResult:
    complete: bool
    reasons: list[str] = field(default_factory=list)
    finish_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.complete


def validate_answer(text: str, finish_reason: str = "") -> ValidationResult:
    """Heuristically validate that an answer is complete."""
    reasons: list[str] = []

    if not text or not text.strip():
        return ValidationResult(False, ["empty_response"], finish_reason)

    if finish_reason == "length":
        reasons.append("finish_reason=length")

    stripped = text.rstrip()

    # Unclosed code fence
    if stripped.count("```") % 2 == 1:
        reasons.append("unclosed_code_fence")

    # Unfinished bold emphasis: odd number of ** markers
    if stripped.count("**") % 2 == 1:
        reasons.append("unclosed_bold")

    # Unclosed italic marker (single asterisk) — only when odd count overall
    if stripped.count("*") % 2 == 1 and "**" not in stripped:
        reasons.append("unclosed_italic")

    # Last non-empty line checks
    lines = [l for l in stripped.split("\n") if l.strip()]
    if lines:
        last = lines[-1].strip()
        # Heading with no content beneath (multi-word headings count too)
        if re.match(r"^#{1,6}\s+\S", last):
            reasons.append("dangling_heading")
        # Trailing colon promising content
        elif last.endswith(":"):
            reasons.append("trailing_colon")
        elif last.endswith("**:"):
            reasons.append("trailing_colon")
        # Sentence ending abruptly — no terminal punctuation, not list/table
        elif not re.search(r"[.!?:\)\]\*`\"”】]$", last) and not re.match(
                r"^(\s*[-*•]|\s*\d+\.|\s*\||#)", lines[-1]):
            reasons.append("abrupt_sentence_end")
        # Money value cut before its decimals: "...dropped 38.5% to $4."
        if re.search(r"\$[\d,]+\.$", last):
            reasons.append("truncated_number")
        # Ends mid-word with a bold fragment like "**Operating" — only
        # meaningful when bold markers are unbalanced; a balanced "**x**【id】y"
        # tail must not be flagged (citation markers after closing ** are fine).
        if (stripped.count("**") % 2 == 1 and _TRUNCATED_TAIL_RE.search(last)
                and not last.rstrip().endswith("**")):
            reasons.append("dangling_bold_fragment")

    return ValidationResult(len(reasons) == 0, reasons, finish_reason or "stop")


def build_continuation_messages(original_messages: list[dict],
                                partial_answer: str) -> list[dict]:
    """Build messages asking the model to continue exactly where it stopped."""
    msgs = list(original_messages)
    msgs.append({"role": "assistant",
                 "content": partial_answer[-1200:]})
    msgs.append({
        "role": "user",
        "content": (
            "Your previous answer was cut off mid-sentence. Continue it seamlessly. "
            "Do NOT repeat any text already written. Do NOT add introductions, "
            "apologies, or phrases like 'continuing' — output ONLY the continuation "
            "text that directly follows where you stopped. "
            "Do not narrate, plan, or explain your process — output only the answer text."
        ),
    })
    return msgs


def looks_like_reasoning_leak(text: str) -> bool:
    """True when the response looks like leaked chain-of-thought."""
    lower = (text or "").lower()
    indicators = [
        "thinking process", "chain of thought", "chain-of-thought",
        "analyze user input", "check provided research data",
        "let me analyze", "let me draft", "scratchpad",
        # Reasoner planning phrases observed leaking from fallback models
        "we need to answer", "we must cite", "we must not claim",
        "we need to explain", "provide explanation using", "use evidence:",
        "the evidence includes", "that's q2", "actually says",
        # Repair-continuation self-talk observed leaking (live run)
        "okay, the user", "the user is pointing", "the user says",
        "the user insists", "let me check", "looking back", "hmm,",
        "wait,", "my previous answer", "the previous answer",
        "previous text", "already written", "i should output",
        "alternative interpretation", "i recall", "to comply",
        "i must obey", "we must not repeat", "do not repeat any text",
    ]
    return sum(1 for i in indicators if i in lower) >= 2
