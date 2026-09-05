"""Bounded read-only traffic over NADOC's existing authenticated Alpine session."""
import json
import time
import urllib.request
from datetime import datetime, timezone
for _ in range(240):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/cluster/probe?name=os', timeout=25) as response:
            result = json.load(response)
        print(datetime.now(timezone.utc).isoformat(), 'remote_rc', result.get('rc'), flush=True)
    except Exception as exc:
        print(datetime.now(timezone.utc).isoformat(), type(exc).__name__, str(exc), flush=True)
        break
    time.sleep(60)
