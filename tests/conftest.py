"""Pytest configuration: project root on path via pytest.ini pythonpath = ."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT
