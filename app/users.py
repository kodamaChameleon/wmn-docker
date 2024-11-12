"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        users.py
Purpose:     User management of WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
import argparse
import json
import os
import random
import string
from cryptography.fernet import Fernet

from utils.config import FERNET_KEY, DB_FILE, CREDENTIALS_BANNER, pwd_context, User, Users
from utils.core import logger

cipher_suite = Fernet(FERNET_KEY)

def generate_random_secret(length: int = 40, letters: bool = True, digits: bool = True) -> str:
    """
    Create a random string of defined character sets
    """
    # Add character sets based on the provided parameters
    characters = ''
    if letters:
        characters += string.ascii_letters
    if digits:
        characters += string.digits

    # Ensure there is at least one type of character to choose from
    if not characters:
        raise ValueError("At least one character set (letters, digits, or special) must be enabled.")

    # Generate the random secret
    return ''.join(random.choice(characters) for _ in range(length))

def save_user_data(users_data: Users):
    """
    Save user data to the database
    """
    users_dict = {user.user_id: user.model_dump() for user in users_data.users}
    users_json = json.dumps(users_dict)
    encrypted_data = cipher_suite.encrypt(users_json.encode())
    with open(DB_FILE, "wb") as f:
        f.write(encrypted_data)
    logger.debug(f"User data has been encrypted and saved to '{DB_FILE}'")

def load_user_data() -> Users:
    """
    Load user database
    """
    try:
        with open(DB_FILE, "rb") as f:
            encrypted_data = f.read()
        decrypted_data = cipher_suite.decrypt(encrypted_data)
        users_dict = json.loads(decrypted_data.decode("utf-8"))
        return Users(users=[User(**user_data) for user_data in users_dict.values()])
    except Exception as e:
        logger.error(f"Error loading encrypted user data: {e}")
        raise ValueError(f"Error loading encrypted user data: {e}")

# Core functions
def initialize_user_data():
    """
    Initialize a new user database
    """
    if not os.path.exists(DB_FILE):
        initial_id = generate_random_secret(10, letters=False)
        initial_secret = generate_random_secret()
        hashed_secret = pwd_context.hash(initial_secret)
        initial_user = User(user_id=initial_id, secret=hashed_secret, disabled=False)
        users = Users(users=[initial_user])
        save_user_data(users)
        print(CREDENTIALS_BANNER.replace("<user_id>", initial_id).replace("<secret>", initial_secret))
    else:
        raise ConnectionError(f"Database already exists. Did you mean 'python3 users.py add'? If the problem persist, delete {DB_FILE} and try again.")

def create_new_user(user_id: str = None, secret: str = None):
    """
    Create a new user in the database
    """
    # Load existing user data
    users_data = load_user_data()

    if user_id is None:
        # Generate a unique user_id
        existing_ids = {user.user_id for user in users_data.users}
        while True:
            user_id = generate_random_secret(10, letters=False)
            if user_id not in existing_ids:
                break

    if secret is None:
        secret = generate_random_secret()

    hashed_secret = pwd_context.hash(secret)
    new_user = User(user_id=user_id, secret=hashed_secret, disabled=False)

    users_data.users.append(new_user)
    save_user_data(users_data)

    # Print the CREDENTIALS_BANNER with the user_id and secret
    print(CREDENTIALS_BANNER.replace("<user_id>", user_id).replace("<secret>", secret))

    return new_user

def disable_user(user_id: str):
    """
    Disable a user by id
    """
    users_data = load_user_data()
    user = next((u for u in users_data.users if u.user_id == user_id), None)
    if user:
        user.disabled = True
        save_user_data(users_data)
        logger.info(f"User '{user_id}' has been disabled.")
    else:
        logger.error(f"User '{user_id}' not found.")

def enable_user(user_id: str):
    """
    Enable a user by id
    """
    users_data = load_user_data()
    user = next((u for u in users_data.users if u.user_id == user_id), None)
    if user:
        user.disabled = False
        save_user_data(users_data)
        logger.info(f"User '{user_id}' has been enabled.")
    else:
        logger.error(f"User '{user_id}' not found.")

def delete_user(user_id: str):
    """
    Delete a user by id
    """
    users_data = load_user_data()
    users_data.users = [u for u in users_data.users if u.user_id != user_id]
    save_user_data(users_data)
    logger.warning(f"User '{user_id}' has been deleted.")

def list_users():
    """
    List all user IDs and their enabled/disabled status.
    """
    users_data = load_user_data()
    print("User ID | Status")
    print("================")
    for user in users_data.users:
        status = "Disabled" if user.disabled else "Enabled"
        print(f"{user.user_id} | {status}")

# Argument parsing
def main():
    """
    Run user management from the command line
    """
    parser = argparse.ArgumentParser(description="User management for the application")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Initialize command
    subparsers.add_parser("initialize", help="Initialize user data with a default user")

    # Add user command
    add_user_parser = subparsers.add_parser("add", help="Add a new user")
    add_user_parser.add_argument("--user_id", type=str, help="User ID for the new user")
    add_user_parser.add_argument("--secret", type=str, help="Secret (password) for the new user")

    # Disable user command
    disable_user_parser = subparsers.add_parser("disable", help="Disable an existing user")
    disable_user_parser.add_argument("user_id", type=str, help="User ID to disable")

    # Enable user command
    enable_user_parser = subparsers.add_parser("enable", help="Enable a disabled user")
    enable_user_parser.add_argument("user_id", type=str, help="User ID to enable")

    # Delete user command
    delete_user_parser = subparsers.add_parser("delete", help="Delete an existing user")
    delete_user_parser.add_argument("user_id", type=str, help="User ID to delete")

    # List users command
    subparsers.add_parser("list", help="List all users and their status")

    args = parser.parse_args()

    if args.command == "initialize" or not os.path.exists(DB_FILE):
        initialize_user_data()
    elif args.command == "add":
        create_new_user(user_id=args.user_id, secret=args.secret)
    elif args.command == "disable":
        disable_user(user_id=args.user_id)
    elif args.command == "enable":
        enable_user(user_id=args.user_id)
    elif args.command == "delete":
        delete_user(user_id=args.user_id)
    elif args.command == "list":
        list_users()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
