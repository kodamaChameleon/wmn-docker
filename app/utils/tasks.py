"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        tasks.py
Purpose:     Manage username lookup tasks for WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
import os
import asyncio
from celery import Celery

from .core import username_lookup, logger

celery = Celery(
    __name__,
    broker=os.getenv("CELERY_BROKER_URL"),
    backend=os.getenv("CELERY_RESULT_BACKEND")
)

# Set the new broker connection retry setting
celery.conf.broker_connection_retry_on_startup = True

@celery.task
def check_username(username: str):
    """
    Launch asynchronous task to lookup username
    """
    try:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(username_lookup(username))
        return result

    except Exception as e:
        logger.error(f"Unknown error checking username: {e}")
        return None
