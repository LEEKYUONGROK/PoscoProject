"""Run on Jetson: send a JSON event with bounded retries."""
import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--url', required=True, help='HTTPS tunnel origin')
parser.add_argument('--token-file', required=True)
parser.add_argument('--event-file', required=True)
args = parser.parse_args()
event = json.loads(Path(args.event_file).read_text())
body = json.dumps(event).encode()
token = Path(args.token_file).read_text().strip()
for attempt in range(4):
    request = Request(args.url.rstrip('/') + '/events', data=body,
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    try:
        with urlopen(request, timeout=15) as response:
            print(response.read().decode())
        break
    except HTTPError as exc:
        if exc.code < 500 or attempt == 3:
            raise SystemExit(f'HTTP {exc.code}: {exc.read().decode()}')
    except (URLError, TimeoutError):
        if attempt == 3:
            raise SystemExit('Delivery failed; preserve this event and retry with the same event_id.')
    time.sleep(2 ** attempt)
