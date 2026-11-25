"""Agent-side feedback client. Only the shared development mailbox is needed."""
import argparse
import json
from pathlib import Path
import time
import uuid


def query(choice, exchange, timeout=90):
    exchange = Path(exchange)
    exchange.mkdir(exist_ok=True)
    token = uuid.uuid4().hex
    pending = exchange / (token + '.tmp')
    pending.write_text(json.dumps(choice, allow_nan=False))
    pending.replace(exchange / (token + '.request.json'))
    reply = exchange / (token + '.reply.json')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if reply.is_file():
            result = json.loads(reply.read_text())
            if 'error' in result:
                raise ValueError(result['error'])
            return result
        time.sleep(.15)
    raise TimeoutError('no development reply; check that the owner started serve-dev for this mailbox')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('choice', type=Path)
    parser.add_argument('--exchange', type=Path, default=Path('dev'))
    parser.add_argument('--timeout', type=float, default=90, help='seconds to wait for an owner reply')
    args = parser.parse_args()
    print(json.dumps(query(json.loads(args.choice.read_text()), args.exchange, timeout=args.timeout), allow_nan=False))
