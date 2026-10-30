"""Pydantic schemas for the ASR REST API responses."""
from __future__ import annotations

from typing import List, Optional

# pyrefly: ignore [missing-import]
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "healthy"


class ModelInfoResponse(BaseModel):
    model_size: Optional[str] = None
    approximate_size: Optional[str] = None
    parameters: Optional[int] = 0
    device: Optional[str] = None
    language: Optional[str] = None
    model_dir: Optional[str] = None
    model_loaded: bool = False


class TranscriptionResponse(BaseModel):
    success: bool
    transcript: str
    language: Optional[str] = None
    duration: Optional[float] = None
    processing_time: Optional[float] = None
    timestamp: str


class StatusResponse(BaseModel):
    status: str
    model: ModelInfoResponse
    max_upload_mb: int


class FormatsResponse(BaseModel):
    formats: List[str]

class TranscribeRequest(BaseModel):
    """
    Payload for passing audio URLs or base64 data to the API.
    Used when audio is not uploaded as a raw multipart/form-data file.
    """
    audio_base64: Optional[str] = None
    audio_url: Optional[str] = None
    language: Optional[str] = "en"
