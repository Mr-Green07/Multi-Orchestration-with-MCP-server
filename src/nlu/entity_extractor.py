"""Rule-based entity extraction from transcribed text.

Uses regex patterns and keyword lookups defined in
`models/entities/patterns.json` to pull structured values (time, date,
duration, location, etc.) out of raw or preprocessed text.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable

from src.nlu.exceptions import EntityExtractionError
from src.utils.helpers import safe_read_json
from src.core.constants import ROOT_DIR

logger = logging.getLogger(__name__)

_DEFAULT_PATTERNS_PATH = ROOT_DIR / "src" / "nlu" / "models" / "entities" / "patterns.json"


class EntityExtractor:
    """Extracts named entities (time, date, duration, location, device, ...)
    from text using the regex/keyword patterns configured in
    `models/entities/patterns.json`.
    """

    def __init__(self, patterns_path: str | None = None) -> None:
        path = patterns_path or _DEFAULT_PATTERNS_PATH
        data = safe_read_json(path)
        self.patterns: Dict[str, Any] = data.get("patterns", {})

        # Pre-compile regexes per entity type for speed.
        self._compiled: Dict[str, list[re.Pattern]] = {}
        for entity_type, definition in self.patterns.items():
            regexes = definition.get("regex", [])
            self._compiled[entity_type] = [
                re.compile(pattern, re.IGNORECASE) for pattern in regexes
            ]

    # ------------------------------------------------------------------
    def extract(self, text: str, entity_types: Iterable[str]) -> Dict[str, Any]:
        """Extract only the requested entity types from *text*.

        :param text: Raw or preprocessed transcript.
        :param entity_types: Entity type names to look for (e.g. ["time", "date"]),
            typically the `entities` list declared on the matched intent.
        :return: Mapping of entity_type -> extracted value. Missing/unmatched
            entity types are simply absent from the result.
        """
        if not text:
            return {}

        try:
            results: Dict[str, Any] = {}
            lowered = text.lower()

            for entity_type in entity_types:
                definition = self.patterns.get(entity_type)
                if not definition:
                    continue

                value = self._extract_one(entity_type, text, lowered, definition)
                if value is not None:
                    results[entity_type] = value

            return results
        except Exception as exc:
            logger.error("Entity extraction failed for %r: %s", text, exc)
            raise EntityExtractionError(f"Error during entity extraction: {exc}") from exc

    def extract_all(self, text: str) -> Dict[str, Any]:
        """Extract every entity type known to the pattern file (no filtering)."""
        return self.extract(text, self.patterns.keys())

    # ------------------------------------------------------------------
    def _extract_one(
        self, entity_type: str, text: str, lowered: str, definition: Dict[str, Any]
    ) -> Any:
        # 1. Regex patterns take priority (more specific / structured).
        for regex in self._compiled.get(entity_type, []):
            match = regex.search(text)
            if match:
                return match.group(0).strip()

        # 2. Fall back to whole-word keyword lookup.
        keywords = definition.get("keywords", {})
        for keyword, mapped_value in keywords.items():
            if self._contains_word(lowered, keyword.lower()):
                return mapped_value

        # 3. word_to_number tables (used by the "number" entity type).
        word_to_number = definition.get("word_to_number")
        if word_to_number:
            for word, number in word_to_number.items():
                if self._contains_word(lowered, word.lower()):
                    return number

        return None

    @staticmethod
    def _contains_word(haystack: str, needle: str) -> bool:
        """Whole-word/phrase containment check (avoids matching inside other words)."""
        return re.search(r"\b" + re.escape(needle) + r"\b", haystack) is not None
