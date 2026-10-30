"""Brain: STT → NLU → Tasks → LLM → TTS → Playback.

This module is the orchestrator of the entire voice assistant.
It loads all models at startup and chains them together sequentially 
when the user speaks.
"""
from __future__ import annotations

import logging
import numpy as np

log = logging.getLogger(__name__)

class Brain:
    """Wires speech recognition → language model → speech synthesis."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        
        log.info("Loading STT model…")
        self._stt = self._init_stt()
        
        log.info("Loading NLU engine…")
        self._preprocessor, self._classifier, self._extractor = self._init_nlu()
        
        log.info("Loading Task Executor…")
        self._task_executor = self._init_task_executor()

        log.info("Connecting to LLM…")
        self._llm = self._init_llm()

        log.info("Loading TTS engine…")
        self._tts = self._init_tts()
        
        log.info("Brain initialization complete! All systems go.")

    # ------------------------------------------------------------------
    def _init_stt(self):
        from src.asr.transcriber import Transcriber
        asr = self.cfg.get("asr", {})
        return Transcriber(
            model_name=asr.get("model", "base"),
            device=asr.get("device", "cpu"),
            language=asr.get("language", "en"),
        )
        
    def _init_nlu(self):
        from src.nlu.preprocessor import TextPreprocessor
        from src.nlu.intent_classifier import IntentClassifier
        from src.nlu.entity_extractor import EntityExtractor
        return TextPreprocessor(), IntentClassifier(), EntityExtractor()
        
    def _init_task_executor(self):
        from src.tasks.executor import TaskExecutor
        # Ensure handlers are imported so they register themselves
        import src.tasks.handlers
        return TaskExecutor()

    def _init_llm(self):
        from src.response_generation.llm_engine import LLMResponseGenerator
        # LLMResponseGenerator doesn't actually take self.cfg in our new implementation,
        # but we can pass it if we update it. We built it with default instantiation.
        return LLMResponseGenerator()

    def _init_tts(self):
        from src.tts.synthesizer import TTSSynthesizer
        return TTSSynthesizer(self.cfg)

    # ------------------------------------------------------------------
    def on_utterance(self, audio: np.ndarray, pipeline) -> None:
        """Called by the main loop with int16 mono audio captured at 16 kHz."""
        # 1. Normalise Audio
        audio_f32 = audio.astype(np.float32) / 32768.0

        # 2. STT (Speech to Text)
        try:
            result = self._stt.transcribe(audio_f32)
            raw_text = result.text.strip()
        except Exception as exc:
            log.error("STT failed: %s", exc)
            pipeline.playback.end_of_utterance()
            return

        log.info("🗣️ User: %r", raw_text)
        if not raw_text:
            pipeline.playback.end_of_utterance()
            return

        # 3. NLU (Understand what they want)
        try:
            normalized = self._preprocessor.process(raw_text)
            intent = self._classifier.classify(normalized)
            intent.raw_text = raw_text
            
            # Extract specific entities if the intent expects them
            expected = intent.entities if hasattr(intent, 'entities') else []
            extracted_entities = self._extractor.extract(normalized, expected)
            
            # Add extracted entities into the intent object for the task handler
            for k, v in extracted_entities.items():
                intent.entities[k] = v
                
            log.info(f"🧠 Intent: {intent.type.value} | Confidence: {intent.confidence:.2f}")
        except Exception as exc:
            log.error("NLU failed: %s", exc)
            pipeline.playback.end_of_utterance()
            return

        # 4. Tasks (Do the thing)
        try:
            task_result = self._task_executor.execute(intent)
            log.info(f"⚙️ Task Result: {task_result.get('status')}")
        except Exception as exc:
            log.error("Task Execution failed: %s", exc)
            task_result = {"status": "error", "message": str(exc)}

        # 5. LLM (Formulate a reply)
        try:
            # Our LLM engine takes the intent and the task result context
            response = self._llm.generate_response(intent, task_result, stream=False)
        except Exception as exc:
            log.error("LLM failed: %s", exc)
            pipeline.playback.end_of_utterance()
            return

        log.info("🤖 Assistant: %r", response[:120])
        if not response:
            pipeline.playback.end_of_utterance()
            return

        # 6. TTS → Playback (Speak it out loud)
        try:
            audio_out = self._tts.synthesize(response)
            if len(audio_out) > 0:
                pipeline.playback.enqueue(audio_out)
        except Exception as exc:
            log.error("TTS failed: %s", exc)

        pipeline.playback.end_of_utterance()
