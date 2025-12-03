# nodes/brainstem_4070/filter.py
from typing import Any, Dict


def basic_validation(payload: Dict[str, Any]) -> bool:
    """
    Very simple placeholder validation.
    Later this becomes:
    - safety checks
    - schema validation
    - anomaly detection
    """
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return False

    # Example future hooks:
    # - profanity / PII filters
    # - "ignore" patterns
    # - rate limiting context

    return True
