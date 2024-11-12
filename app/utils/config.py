"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        config.py
Purpose:     Configuration settings for WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
import os
from pydantic import BaseModel
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer

# Logging
LOG_DIR = "/var/log/wmn-docker"
LOG_FILE = "wmn.log"

# App Specific
DB_FILE = "/home/kodama/wmn.db"
WMN_URL = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
WMN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
RATE_LIMIT = os.getenv("RATE_LIMIT", 20)
CACHE_EXPIRATION = int(os.getenv("CACHE_EXPIRATION", 3600))

# Security
SECRET_KEY = os.getenv("SECRET_KEY", None)
FERNET_KEY = SECRET_KEY.encode('utf-8')
ALGORITHM = "HS256"
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").lower() == "true"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

CREDENTIALS_BANNER = """\
=======================================================
User created: <user_id>
Secret: <secret>
Be sure to save this secret somewhere safe!
(WMN-Docker does not store plaintext secrets.)
=======================================================
"""

# Ensure SECRET_KEY exists and is properly formatted
if not SECRET_KEY:
    raise ValueError("SECRET KEY required")

# Define the request models
class User(BaseModel):
    """
    Define User Data Structure
    """
    user_id: str
    secret: str
    disabled: bool = False

class Users(BaseModel):
    """
    Define Users as list of User
    """
    users: list[User]

    class Config:
        """
        Manage encoders
        """
        json_encoders = {
            str: lambda v: v
        }

class UsernameLookup(BaseModel):
    """
    Define data structure for username lookup
    """
    username: str

class LoginRequest(BaseModel):
    """
    Define data structure for login requests
    """
    user_id: str
    secret: str
