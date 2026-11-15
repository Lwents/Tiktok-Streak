"""Wake at the next local midnight, with periodic checks while the tool is awake."""
import math
import time


def next_check_delay(midnight, now=None):
    now = time.time() if now is None else now
    if not isinstance(midnight, (int, float)) or not math.isfinite(midnight) or midnight <= 0:
        return 60
    return min(60, max(0, midnight - now))
