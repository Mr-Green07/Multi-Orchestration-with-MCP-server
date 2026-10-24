import secrets 
import time 
from typing import Any 


# In-memory store: {token: {"action": str, "payload": dict, "expires_at": float}}
_PENDING_CONFIRMATIONS: dict[str, dict[str, Any]] = {}
TOKEN_TTL_SECONDS = 120  # Tokens expire after 2 minutes

def create_confirmation_token(action: str, payload: dict[str, Any]) -> str:
    """Create a short-lived one-time token for a Tier 3 destructive action."""
    # Purge expired tokens first
    now = time.time()
    expired = [k for k, v in _PENDING_CONFIRMATIONS.items() if v["expires_at"] < now]
    for k in expired:
        del _PENDING_CONFIRMATIONS[k]

    token = secrets.token_hex(8)
    _PENDING_CONFIRMATIONS[token] = {
        "action": action,
        "payload": payload,
        "expires_at": now + TOKEN_TTL_SECONDS
    }
    return token

def verify_and_consume_token(token: str, expected_action: str) -> dict[str, Any] | None:
    """Verify a token is valid, matches the action, and consume it so it cannot be reused."""
    record = _PENDING_CONFIRMATIONS.pop(token, None)
    if not record:
        return None
    if time.time() > record["expires_at"] or record["action"] != expected_action:
        return None
    return record["payload"]