"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        authentication.py
Purpose:     Manage authentication for WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import HTTPException, Depends, status

from users import load_user_data
from .config import (
    SECRET_KEY,
    ALGORITHM,
    AUTH_REQUIRED,
    pwd_context,
    oauth2_scheme,
    ACCESS_TOKEN_EXPIRATION,
    User
)
from .core import logger

def authenticate_user(user_id: str, secret: str) -> User:
    """
    Authenticates the user by checking:
    - If the user exists
    - If the user is disabled
    - If the secret matches
    
    Returns the User instance if authentication is successful, otherwise False.
    """
    try:
        # Load the user data into a Users Pydantic model
        users_data = load_user_data()

        # Look up the user by user_id
        user = next((user for user in users_data.users if user.user_id == user_id), None)

        # If the user is not found or any condition fails (secret mismatch, disabled user), return False
        if not user or not pwd_context.verify(secret, user.secret) or user.disabled:
            return False

        # Return the User instance if authentication is successful
        return user

    except Exception as e:
        logger.error(f"Unknown error while authenticating user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Unknown error during authentication")

# Token generation function
def create_access_token(data: dict):
    """
    Creates a JWT token using the provided data (e.g., user ID).
    """
    to_encode = data.copy()
    if ACCESS_TOKEN_EXPIRATION > 0:
        expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRATION)
        to_encode.update({"exp": expire})
    else:
        to_encode.update({"exp": None})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Dependency for extracting and verifying JWT token
def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Extracts and verifies the JWT token, returns the user ID from the payload.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        exp: datetime = payload.get("exp")

        # Non-existant user
        if user_id is None:
            logger.error(f"No user found for token: '{token}'")
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")

        # Check if the token has expired
        if exp and datetime.now(timezone.utc) > datetime.fromtimestamp(exp, tz=timezone.utc):
            logger.error(f"Token has expired: '{token}'")
            raise HTTPException(status_code=401, detail="Token has expired")

        token_data = {"user_id": user_id}

    # Invalid token
    except jwt.ExpiredSignatureError:
        logger.error(f"Token has expired: '{token}'")
        raise HTTPException(status_code=401, detail="Token has expired")

    except jwt.InvalidTokenError:
        logger.error(f"Invalid token '{token}'")
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

    # Unknown error
    except Exception as e:
        logger.error(f"Unknown authentication error :{e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication error"
        )

    logger.info(f"Successful login for user {user_id}")
    return token_data

# Optional authentication dependency based on environment variable
def optional_auth_dependency():
    """
    If the environment variable AUTH_REQUIRED is set to "true", authentication is required.
    Otherwise, authentication is optional.
    """
    if AUTH_REQUIRED:
        return get_current_user
    return lambda: None
