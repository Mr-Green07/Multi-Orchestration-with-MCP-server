# pyrefly: ignore [missing-import]
from fastapi import APIRouter
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class CommandRequest(BaseModel):
    text: str
    
class CommandResponse(BaseModel):
    success: bool
    response_text: str

@router.post("/command", response_model=CommandResponse)
async def execute_text_command(payload: CommandRequest):
    """
    Text-only endpoint. Skips STT.
    Takes a raw text string, runs it through NLU -> Tasks -> LLM, 
    and returns the text response. 
    Useful for chat interfaces or testing.
    """
    logger.info(f"Received text command: {payload.text}")
    
    # Placeholder for wiring up NLU directly
    
    return CommandResponse(
        success=True,
        response_text=f"I received your command: {payload.text}. (This is a placeholder response)"
    )
