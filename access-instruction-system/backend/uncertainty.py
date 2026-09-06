import math
from datetime import datetime
from typing import Tuple

HALF_LIFE_DAYS = 30.0

def calculate_confidence(confirmation_count: int, contradiction_count: int, last_confirmed_at: datetime, current_time: datetime = None) -> float:
    """
    Calculates confidence score using Laplace-smoothed success rate and time decay.
    """
    if current_time is None:
        current_time = datetime.utcnow()
        
    # Laplace smoothing
    raw_confidence = (confirmation_count + 1) / (confirmation_count + contradiction_count + 2)
    
    # Time decay
    days_since_last_confirmed = max(0.0, (current_time - last_confirmed_at).total_seconds() / 86400.0)
    decay = math.exp(-days_since_last_confirmed / HALF_LIFE_DAYS)
    
    return raw_confidence * decay

def get_confidence_band(score: float) -> str:
    """
    Maps a confidence score (0.0 to 1.0) to a label band.
    """
    if score >= 0.7:
        return "High confidence — confirmed recently"
    elif score >= 0.4:
        return "Medium confidence — may be outdated"
    else:
        return "Low confidence / no verified note — attempt as new address"
