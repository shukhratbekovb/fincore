"""Prevent a green CI run when service-backed tests silently skipped."""

import sys
from pathlib import Path
from xml.etree import ElementTree


def main() -> int:
    report = ElementTree.parse(Path(sys.argv[1])).getroot()
    cases = list(report.iter("testcase"))
    if not cases:
        print("No tests were reported.", file=sys.stderr)
        return 1
    unsuccessful = [
        case for case in cases
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error"))
    ]
    if unsuccessful:
        for case in unsuccessful:
            print(f"Test did not pass: {case.get('classname')}.{case.get('name')}", file=sys.stderr)
        return 1
    print(f"All {len(cases)} tests ran and passed; no skipped integrations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
