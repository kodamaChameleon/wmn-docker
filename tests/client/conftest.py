"""
Loaders for the client-side modules in the repo-root utils/ directory.

That directory shares the `utils` package name with app/utils (which is on
sys.path for the API tests), so load the files by path under unique names.
"""
import importlib.util
import pathlib

import dotenv
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_module(name, relative_path, monkeypatch):
    # utils/api.py calls load_dotenv(override=True) on import; keep the real .env out of tests
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def api(monkeypatch):
    module = load_module("wmn_client_api", "utils/api.py", monkeypatch)
    monkeypatch.setattr(module, "API_BASE_URL", "http://api.test")
    return module


@pytest.fixture
def setup_module(monkeypatch):
    return load_module("wmn_client_setup", "utils/setup.py", monkeypatch)
