"""Smoke tests for project scaffolding."""

from tearsheet import __version__
from tearsheet.config import PROJECT_ROOT, database_url, ensure_data_dirs


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_project_root_exists() -> None:
    assert PROJECT_ROOT.is_dir()


def test_database_url_defaults_to_sqlite() -> None:
    assert database_url().startswith("sqlite:///")
