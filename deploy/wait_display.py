"""Wait briefly for the private X server before launching a browser client."""
import socket
import time

for _ in range(100):
    try:
        with socket.socket(socket.AF_UNIX) as probe:
            probe.connect('/tmp/.X11-unix/X99')
        break
    except OSError:
        time.sleep(.1)
else:
    raise SystemExit('Virtual display did not become ready.')
