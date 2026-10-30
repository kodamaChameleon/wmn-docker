"""Unit tests for app/users.py (user database and CLI)."""
import os
import string
import sys

import pytest
from cryptography.fernet import Fernet

import users
from helpers import ACTIVE_USER_ID, DISABLED_USER_ID
from utils.models import User, Users


def user_ids():
    return [u.user_id for u in users.load_user_data().users]


def get_user(user_id):
    return next(u for u in users.load_user_data().users if u.user_id == user_id)


# generate_random_secret

@pytest.mark.parametrize("length", [0, 1, 10, 40, 200])
def test_secret_length(length):
    assert len(users.generate_random_secret(length)) == length


def test_secret_defaults():
    secret = users.generate_random_secret()

    assert len(secret) == 40
    assert set(secret) <= set(string.ascii_letters + string.digits)


def test_secret_digits_only():
    assert users.generate_random_secret(200, letters=False).isdigit()


def test_secret_letters_only():
    assert users.generate_random_secret(200, digits=False).isalpha()


def test_secret_requires_a_character_set():
    with pytest.raises(ValueError):
        users.generate_random_secret(letters=False, digits=False)


def test_secrets_are_not_repeated():
    assert len({users.generate_random_secret() for _ in range(50)}) == 50


# save / load

def test_save_load_round_trip(isolated_db):
    data = Users(users=[User(user_id="a", secret="h1"), User(user_id="b", secret="h2", disabled=True)])

    users.save_user_data(data)

    assert users.load_user_data() == data


def test_database_is_encrypted_on_disk(user_db):
    with open(user_db, "rb") as f:
        raw = f.read()

    assert ACTIVE_USER_ID.encode() not in raw
    assert b"secret" not in raw


def test_load_missing_database_raises_value_error():
    with pytest.raises(ValueError, match="Error loading encrypted user data"):
        users.load_user_data()


def test_load_corrupt_database_raises_value_error(isolated_db):
    with open(isolated_db, "wb") as f:
        f.write(b"garbage")

    with pytest.raises(ValueError):
        users.load_user_data()


def test_load_with_wrong_key_raises_value_error(user_db, monkeypatch):
    monkeypatch.setattr(users, "cipher_suite", Fernet(Fernet.generate_key()))

    with pytest.raises(ValueError):
        users.load_user_data()


def test_duplicate_user_ids_collapse_on_save(isolated_db):
    users.save_user_data(Users(users=[User(user_id="a", secret="1"), User(user_id="a", secret="2")]))

    loaded = users.load_user_data().users
    assert len(loaded) == 1
    assert loaded[0].secret == "2"


# initialize_user_data

def test_initialize_creates_one_enabled_user(isolated_db, capsys, fast_hashing):
    users.initialize_user_data()

    loaded = users.load_user_data().users
    assert len(loaded) == 1
    user = loaded[0]
    assert user.disabled is False
    assert len(user.user_id) == 10 and user.user_id.isdigit()

    out = capsys.readouterr().out
    assert f"User created: {user.user_id}" in out
    printed_secret = out.split("Secret: ")[1].split("\n")[0]
    assert fast_hashing.verify(printed_secret, user.secret)
    assert user.secret != printed_secret


def test_initialize_refuses_to_overwrite(user_db):
    with pytest.raises(ConnectionError):
        users.initialize_user_data()

    assert set(user_ids()) == {ACTIVE_USER_ID, DISABLED_USER_ID}


# create_new_user

def test_create_user_with_explicit_credentials(user_db, capsys, fast_hashing):
    new_user = users.create_new_user(user_id="alice", secret="s3cret")

    assert new_user.user_id == "alice"
    assert fast_hashing.verify("s3cret", get_user("alice").secret)
    assert "s3cret" not in open(user_db, "rb").read().decode(errors="ignore")
    assert "Secret: s3cret" in capsys.readouterr().out


def test_create_user_generates_credentials(user_db, capsys):
    new_user = users.create_new_user()

    assert new_user.user_id.isdigit() and len(new_user.user_id) == 10
    assert new_user.user_id in user_ids()
    assert len(user_ids()) == 3


def test_create_user_avoids_existing_ids(user_db, monkeypatch, capsys):
    generated = iter([ACTIVE_USER_ID, DISABLED_USER_ID, "5555555555", "secret-value"])
    monkeypatch.setattr(users, "generate_random_secret", lambda *a, **k: next(generated))

    new_user = users.create_new_user()

    assert new_user.user_id == "5555555555"


def test_created_user_can_authenticate(user_db, capsys):
    from utils.authentication import authenticate_user
    users.create_new_user(user_id="alice", secret="s3cret")

    assert authenticate_user("alice", "s3cret").user_id == "alice"


def test_create_user_requires_database(capsys):
    with pytest.raises(ValueError):
        users.create_new_user(user_id="alice", secret="x")


# disable / enable / delete / list

def test_disable_user(user_db):
    users.disable_user(ACTIVE_USER_ID)
    assert get_user(ACTIVE_USER_ID).disabled is True


def test_enable_user(user_db):
    users.enable_user(DISABLED_USER_ID)
    assert get_user(DISABLED_USER_ID).disabled is False


@pytest.mark.parametrize("action", [users.disable_user, users.enable_user])
def test_toggle_unknown_user_leaves_db_unchanged(user_db, action):
    before = users.load_user_data()

    action("nobody")

    assert users.load_user_data() == before


def test_disable_is_idempotent(user_db):
    users.disable_user(DISABLED_USER_ID)
    assert get_user(DISABLED_USER_ID).disabled is True


def test_delete_user(user_db):
    users.delete_user(ACTIVE_USER_ID)
    assert user_ids() == [DISABLED_USER_ID]


def test_delete_unknown_user_is_noop(user_db):
    users.delete_user("nobody")
    assert set(user_ids()) == {ACTIVE_USER_ID, DISABLED_USER_ID}


def test_list_users(user_db, capsys):
    users.list_users()

    out = capsys.readouterr().out
    assert f"{ACTIVE_USER_ID} | Enabled" in out
    assert f"{DISABLED_USER_ID} | Disabled" in out


# CLI

def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["users.py", *args])
    users.main()


def test_cli_initialize(isolated_db, monkeypatch, capsys):
    run_cli(monkeypatch, "initialize")

    assert os.path.exists(isolated_db)
    assert "User created:" in capsys.readouterr().out


def test_cli_any_command_initializes_missing_db(isolated_db, monkeypatch, capsys):
    run_cli(monkeypatch, "list")

    assert os.path.exists(isolated_db)
    assert "User created:" in capsys.readouterr().out


def test_cli_add(user_db, monkeypatch, capsys):
    run_cli(monkeypatch, "add", "--user_id", "alice", "--secret", "pw")
    assert "alice" in user_ids()


@pytest.mark.parametrize("command, user_id, check", [
    ("disable", ACTIVE_USER_ID, lambda: get_user(ACTIVE_USER_ID).disabled is True),
    ("enable", DISABLED_USER_ID, lambda: get_user(DISABLED_USER_ID).disabled is False),
    ("delete", ACTIVE_USER_ID, lambda: ACTIVE_USER_ID not in user_ids()),
])
def test_cli_user_commands(user_db, monkeypatch, command, user_id, check):
    run_cli(monkeypatch, command, user_id)
    assert check()


def test_cli_list(user_db, monkeypatch, capsys):
    run_cli(monkeypatch, "list")
    assert "User ID | Status" in capsys.readouterr().out


def test_cli_no_command_prints_help(user_db, monkeypatch, capsys):
    run_cli(monkeypatch)
    assert "usage:" in capsys.readouterr().out


def test_cli_missing_positional_exits(user_db, monkeypatch):
    with pytest.raises(SystemExit):
        run_cli(monkeypatch, "disable")
