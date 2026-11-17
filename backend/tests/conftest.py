from datetime import datetime, timezone

import pytest


@pytest.fixture
def now():
    return datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def pytest_collection_modifyitems(items):
    for item in items:
        tests_root = item.config.rootpath / "tests"
        if not item.path.is_relative_to(tests_root):
            continue
        parts = item.path.relative_to(tests_root).parts
        if parts[0] in {"unit", "integration"}:
            item.add_marker(getattr(pytest.mark, parts[0]))
