from datetime import datetime, timezone

def now_timestamp():    
    #Returns UNIX timestamp as float.   
    return datetime.now(timezone.utc).timestamp()


def now_iso():    
    #Returns ISO8601 timestamp ("2025-12-03T01:23:45.123Z")
    return datetime.now(timezone.utc).isoformat()
