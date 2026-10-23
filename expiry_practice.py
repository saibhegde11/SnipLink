import time

def current_timestamp() -> float : 
    return time.time()

def calculate_expiry(
    expires_in : int | None,
    now : float
) -> float | None : 
    if expires_in is None : 
        return None
    return now + expires_in

def is_expired(
    expires_at : float | None,
    now : float
) -> bool : 
    if expires_at is None : 
        return False
    return now >= expires_at