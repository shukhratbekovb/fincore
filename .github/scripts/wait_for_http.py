"""Bounded readiness polling for CI processes, without printing response bodies."""

import argparse
import sys
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def wait_for_http(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=min(2, max(0.01, deadline - time.monotonic()))) as response:
                if response.status == 200:
                    return True
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--timeout', type=int, default=90, choices=range(1, 301), metavar='1..300')
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        parser.error('Use an HTTP(S) readiness URL without credentials')
    if wait_for_http(args.url, args.timeout):
        print('HTTP readiness check passed.')
        return 0
    print('HTTP readiness check timed out.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
