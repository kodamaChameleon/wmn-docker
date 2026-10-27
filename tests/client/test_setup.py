"""Light tests for the setup helpers in utils/setup.py."""
import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def compose(setup_module, monkeypatch):
    monkeypatch.setattr(setup_module, "_compose_cmd", None)
    return setup_module


def test_compose_v1_detected(compose, monkeypatch):
    monkeypatch.setattr(compose.shutil, "which", lambda name: "/usr/bin/docker-compose")
    assert compose._get_compose_cmd() == ["docker-compose"]


def test_compose_v2_fallback(compose, monkeypatch):
    monkeypatch.setattr(compose.shutil, "which", lambda name: None)
    assert compose._get_compose_cmd() == ["docker", "compose"]


def test_compose_detection_is_cached(compose, monkeypatch):
    calls = []
    monkeypatch.setattr(compose.shutil, "which", lambda name: calls.append(name))

    compose._get_compose_cmd()
    compose._get_compose_cmd()

    assert len(calls) == 1


def test_start_setup_unknown_context(setup_module):
    with pytest.raises(ValueError):
        setup_module.start_setup("staging")


def test_start_docker_containers_unknown_context(setup_module):
    with pytest.raises(ValueError):
        setup_module.start_docker_containers("staging")


def test_populate_env_generates_valid_secret_key(setup_module, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("VERBOSE=False\nSECRET_KEY=your_secret_key_here\n")

    setup_module.populate_env_with_secrets()

    content = (tmp_path / ".env").read_text()
    assert "your_secret_key_here" not in content
    key = content.split("SECRET_KEY=")[1].strip()
    Fernet(key)  # the app uses SECRET_KEY as a Fernet key, so it must be valid
    assert "VERBOSE=False" in content


def test_populate_env_without_file(setup_module, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    setup_module.populate_env_with_secrets()

    assert "does not exist" in capsys.readouterr().out


def test_setup_environment_file_copies_sample_once(setup_module, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env_sample").write_text("A=1\n")

    setup_module.setup_environment_file()
    (tmp_path / ".env").write_text("A=changed\n")
    setup_module.setup_environment_file()

    assert (tmp_path / ".env").read_text() == "A=changed\n"
