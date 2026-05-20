import uuid

_current_session = None

def current_session_id() -> str:

    #Returns current session ID.
    #If none exists, generates a new one.
    global _current_session

    if _current_session is None:
        _current_session = f"sess_{uuid.uuid4().hex[:12]}"

    return _current_session


def new_session():
    #Force-create a brand new session ID.
    #Useful when starting a new 'thought' or conversation.
    global _current_session
    _current_session = f"sess_{uuid.uuid4().hex[:12]}"
    return _current_session
