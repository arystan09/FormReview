import pytest

pytest_plugins = ["pytester"]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        categories = [
            name for name in ("unit", "integration", "e2e") if item.get_closest_marker(name)
        ]
        if len(categories) != 1:
            raise pytest.UsageError(f"{item.nodeid} must have exactly one test category marker")
