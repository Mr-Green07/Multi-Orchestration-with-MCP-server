"""Rule-based intent classification (Phase 1 NLU).

Loads intent catalogs from `models/intents/*.json` and thresholds/priorities
from `models/nlu_config.json`, then scores a preprocessed transcript against
every enabled intent using keyword overlap + example similarity. No ML model
is involved -- this is a deterministic, fully-offline classifier meant to
handle common commands (weather, timers, music, device control) before
falling back to the LLM for anything else.

Usage:
    classifier = IntentClassifier()
    intent = classifier.classify("set a timer for 5 minutes")
    if intent.is_reliable:
        task_executor.run(intent)
    else:
        llm.generate_response(intent.raw_text)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from src.nlu.entity_extractor import EntityExtractor
from src.nlu.exceptions import ClassificationError
from src.nlu.intent import Intent, IntentType
from src.nlu.preprocessor import TextPreprocessor
from src.utils.helpers import safe_read_json
from src.core.constants import ROOT_DIR

logger = logging.getLogger(__name__)

_DEFAULT_INTENTS_DIR = ROOT_DIR / "src" / "nlu" / "models" / "intents"
_DEFAULT_CONFIG_PATH = ROOT_DIR / "src" / "nlu" / "models" / "nlu_config.json"

# Weight given to keyword-overlap score vs. example-similarity score when
# combining them into the final per-intent score.
_KEYWORD_WEIGHT = 0.4
_EXAMPLE_WEIGHT = 0.6


class IntentClassifier:
    """Scores a transcript against every enabled intent and returns the best
    match as an `Intent`, or the configured fallback intent if nothing clears
    the confidence threshold.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        intents_dir: str | Path | None = None,
        preprocessor: TextPreprocessor | None = None,
        entity_extractor: EntityExtractor | None = None,
    ) -> None:
        self.config = safe_read_json(config_path or _DEFAULT_CONFIG_PATH)

        thresholds = self.config.get("thresholds", {})
        self.confidence_min: float = thresholds.get("confidence_min", 0.45)
        self.ambiguity_gap: float = thresholds.get("ambiguity_gap", 0.15)

        self.enabled_intents: List[str] = self.config.get("enabled_intents", [])
        self.fallback_intent: str = self.config.get("fallback_intent", "chitchat")
        self.intent_priority: Dict[str, int] = self.config.get("intent_priority", {})

        self.preprocessor = preprocessor or TextPreprocessor()
        self.entity_extractor = entity_extractor or EntityExtractor()

        self._catalog: Dict[str, Dict[str, Any]] = self._load_intent_catalog(
            intents_dir or _DEFAULT_INTENTS_DIR
        )

    # ------------------------------------------------------------------
    def _load_intent_catalog(self, intents_dir: str | Path) -> Dict[str, Dict[str, Any]]:
        """Merge every models/intents/*.json file into one name -> definition map."""
        catalog: Dict[str, Dict[str, Any]] = {}
        directory = Path(intents_dir)

        if not directory.exists():
            logger.warning("Intents directory not found: %s", directory)
            return catalog

        for json_file in sorted(directory.glob("*.json")):
            data = safe_read_json(json_file)
            for intent_def in data.get("intents", []):
                name = intent_def.get("name")
                if not name:
                    continue
                if name in catalog:
                    logger.warning(
                        "Duplicate intent '%s' found in %s; overwriting", name, json_file
                    )
                catalog[name] = intent_def

        logger.info("Loaded %d intent definitions from %s", len(catalog), directory)
        return catalog

    # ------------------------------------------------------------------
    def classify(self, text: str) -> Intent:
        """Classify raw transcript text into an `Intent`.

        :param text: Raw transcript from the STT engine.
        :raises ClassificationError: If classification fails unexpectedly.
        """
        if not text or not text.strip():
            return Intent(type=IntentType.UNKNOWN, confidence=0.0, raw_text=text or "")

        try:
            normalized = self.preprocessor.normalize(text)
            scores = self._score_all_intents(normalized)

            best_name, best_score = self._pick_winner(scores)

            if best_name is None or best_score < self.confidence_min:
                logger.debug(
                    "No intent cleared confidence_min=%.2f (best=%.2f); falling back to %s",
                    self.confidence_min, best_score, self.fallback_intent,
                )
                intent_type = self._to_intent_type(self.fallback_intent)
                return Intent(type=intent_type, confidence=best_score, raw_text=text)

            intent_type = self._to_intent_type(best_name)
            entities = self._extract_entities(best_name, normalized)

            logger.info("Classified %r -> %s (confidence=%.2f)", text, best_name, best_score)
            return Intent(
                type=intent_type,
                confidence=best_score,
                raw_text=text,
                entities=entities,
            )
        except Exception as exc:
            logger.error("Intent classification failed for %r: %s", text, exc)
            raise ClassificationError(f"Error during intent classification: {exc}") from exc

    # ------------------------------------------------------------------
    def _score_all_intents(self, normalized_text: str) -> Dict[str, float]:
        words = set(normalized_text.split())
        scores: Dict[str, float] = {}

        for name in self.enabled_intents:
            definition = self._catalog.get(name)
            if not definition:
                continue
            scores[name] = self._score_intent(normalized_text, words, definition)

        return scores

    def _score_intent(
        self, normalized_text: str, words: set[str], definition: Dict[str, Any]
    ) -> float:
        keyword_score = self._keyword_score(normalized_text, definition.get("keywords", []))
        example_score = self._example_score(normalized_text, words, definition.get("examples", []))

        if not definition.get("keywords"):
            # No keywords defined (e.g. chitchat) -- rely entirely on examples.
            return example_score
        if not definition.get("examples"):
            return keyword_score

        return _KEYWORD_WEIGHT * keyword_score + _EXAMPLE_WEIGHT * example_score

    @staticmethod
    def _keyword_score(normalized_text: str, keywords: List[str]) -> float:
        if not keywords:
            return 0.0
        hits = sum(
            1 for kw in keywords
            if re.search(r"\b" + re.escape(kw.lower()) + r"\b", normalized_text)
        )
        return hits / len(keywords)

    @staticmethod
    def _example_score(normalized_text: str, words: set[str], examples: List[str]) -> float:
        if not examples or not words:
            return 0.0
        best = 0.0
        for example in examples:
            example_norm = re.sub(r"[^\w\s]", "", example.lower())
            example_words = set(example_norm.split())
            if not example_words:
                continue
            intersection = words & example_words
            union = words | example_words
            jaccard = len(intersection) / len(union) if union else 0.0
            # Exact phrase containment (whole-word) is a very strong signal.
            if re.search(r"\b" + re.escape(example_norm) + r"\b", normalized_text):
                jaccard = max(jaccard, 0.95)
            best = max(best, jaccard)
        return best

    # ------------------------------------------------------------------
    def _pick_winner(self, scores: Dict[str, float]) -> tuple[str | None, float]:
        if not scores:
            return None, 0.0

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_name, best_score = ranked[0]

        if len(ranked) > 1:
            second_name, second_score = ranked[1]
            # If the top two are within the ambiguity gap, let configured
            # intent_priority break the tie.
            if best_score - second_score <= self.ambiguity_gap:
                p_best = self.intent_priority.get(best_name, 0)
                p_second = self.intent_priority.get(second_name, 0)
                if p_second > p_best:
                    best_name, best_score = second_name, second_score

        return best_name, best_score

    def _extract_entities(self, intent_name: str, normalized_text: str) -> Dict[str, Any]:
        definition = self._catalog.get(intent_name, {})
        entity_types = definition.get("entities", [])
        if not entity_types:
            return {}
        return self.entity_extractor.extract(normalized_text, entity_types)

    @staticmethod
    def _to_intent_type(name: str) -> IntentType:
        try:
            return IntentType(name)
        except ValueError:
            logger.warning("Unknown intent name '%s' -- mapping to UNKNOWN", name)
            return IntentType.UNKNOWN
