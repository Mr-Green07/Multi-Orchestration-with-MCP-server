"""scientific_llm/text.py
=======================
Text utilities shared by ingestion, indexing, retrieval and evaluation.

Everything here is deliberately dependency-free and deterministic: the whole
scientific stack has to run offline, produce identical scores on two machines, and
be unit-testable without a model download.
"""
from __future__ import annotations

import hashlib
import re

#: Stopwords tuned for scientific prose (kept small on purpose: over-filtering
#: hurts recall on short method names such as "in" or "out of distribution").
STOPWORDS = frozenset("""
a an the and or but if then than that this these those of for from with without within
into onto over under above below between among during before after while about against
is are was were be been being am do does did doing have has had having will would shall
should can could may might must ought i you he she it we they me him her us them my your
his its our their what which who whom whose when where why how all any both each few
more most other some such no nor not only own same so too very s t just also as at by
in on to up down out off again further once here there
""".split())

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_+.%]*")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Lower-case word tokens (hyphens kept: 'bi-encoder', 'multi-agent')."""
    tokens = [match.group(0).lower() for match in _TOKEN_RE.finditer(text or "")]
    tokens = [token.strip("-._") for token in tokens]
    tokens = [token for token in tokens if len(token) > 1 or token.isdigit()]
    if keep_stopwords:
        return tokens
    return [token for token in tokens if token not in STOPWORDS]


def stem(word: str) -> str:
    """Light suffix stripping that groups the inflections that matter in papers.

    Not a full Porter stemmer: the goal is that "retrieval"/"retrievers",
    "limitation"/"limitations" and "evaluate"/"evaluating"/"evaluated" collapse to
    the same term, while distinct technical words ("dataset" vs "data") do not.
    Deterministic and explainable, which matters when a score has to be justified.
    """
    word = word.lower()
    if len(word) <= 3:
        return word

    # 1. plural
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith(("sses", "shes", "ches", "xes", "zes")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]

    # 2. nominalisation, longest first
    for suffix, replacement in (
        ("ational", "ate"), ("izations", "ize"), ("ization", "ize"),
        ("ations", "ate"), ("ation", "ate"), ("itions", "ite"), ("ition", "ite"),
        ("ements", "ement"), ("ement", "e"), ("ities", "ity"), ("ness", ""),
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: len(word) - len(suffix)] + replacement
            break

    # 3. verb endings, restoring the 'e' that English drops before -ing/-ed
    for suffix in ("ingly", "edly", "ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: len(word) - len(suffix)]
            if suffix in {"ing", "ed"} and base.endswith(("at", "iz", "bl", "iv", "us")):
                base += "e"
            elif len(base) > 2 and base[-1] == base[-2] and base[-1] not in "aeiou":
                base = base[:-1]                     # running -> run
            word = base
            break

    # 4. adjectival endings that do not change meaning in a technical corpus
    for suffix in ("ical", "ive", "al"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: len(word) - len(suffix)]
            break

    if word.endswith("e") and len(word) > 4:
        word = word[:-1]                             # evaluate -> evaluat
    return word


def terms(text: str) -> list[str]:
    """Indexable terms: stopword-free, stemmed."""
    return [stem(token) for token in tokenize(text)]


def term_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for term in terms(text):
        counts[term] = counts.get(term, 0) + 1
    return counts


def sentences(text: str) -> list[str]:
    """Split prose into sentences, keeping short ones (they often carry numbers)."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    parts = _SENTENCE_SPLIT.split(cleaned)
    return [part.strip() for part in parts if part.strip()]


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", (text or "").replace("\r\n", "\n")).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def slugify(text: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_length].rstrip("-")


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def overlap_ratio(reference: set[str], candidate: set[str]) -> float:
    """How much of *reference* is covered by *candidate* (0-1)."""
    if not reference:
        return 0.0
    return len(reference & candidate) / len(reference)


def snippet(text: str, around: str, width: int = 220) -> str:
    """A short quotation from *text* centred on the first match for *around*."""
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return ""
    needle = (around or "").strip().lower()
    position = cleaned.lower().find(needle) if needle else -1
    if position < 0:
        return cleaned[:width].strip()
    start = max(0, position - width // 3)
    end = min(len(cleaned), start + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(cleaned) else ""
    return f"{prefix}{cleaned[start:end].strip()}{suffix}"
