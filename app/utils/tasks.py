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
from typing import Optional
import asyncio
from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

from .core import username_lookup, logger
from .config import JOB_TIMEOUT

celery = Celery(
    __name__,
    broker=os.getenv("CELERY_BROKER_URL"),
    backend=os.getenv("CELERY_RESULT_BACKEND")
)

# Set the new broker connection retry setting
celery.conf.broker_connection_retry_on_startup = True

@celery.task(soft_time_limit=JOB_TIMEOUT, time_limit=(JOB_TIMEOUT+60))
def check_username(username: str) -> Optional[dict]:
    """
    Launch asynchronous task to lookup username
    """
    try:
        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(username_lookup(username))
        return results

    # Handle graceful timeout using SoftTimeLimitExceeded
    except SoftTimeLimitExceeded:
        logger.warning(f"Task for username '{username}' exceeded the soft time limit and was terminated gracefully.")
        return {"error": "Task timeout", "message": "The task took too long and was canceled."}

    except Exception as e:
        logger.error(f"Unknown error checking username: {e}")
        return None
