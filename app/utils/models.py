"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        config.py
Purpose:     Models for WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
from typing import List
from pydantic import BaseModel

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
    users: List[User]

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

class BatchLookup(BaseModel):
    """
    Define data structure for username lookup
    """
    username: List[str]

class LoginRequest(BaseModel):
    """
    Define data structure for login requests
    """
    user_id: str
    secret: str
