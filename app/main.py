"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        main.py
Purpose:     FastAPI routes of WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
import re
import json
from typing import Optional
from uuid import uuid4
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status, Depends
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter
from celery.result import AsyncResult
import redis.asyncio as redis
import uvicorn

from utils.tasks import check_username
from utils.authentication import authenticate_user, create_access_token, optional_auth_dependency
from utils.core import logger
from utils.config import RATE_LIMIT, CACHE_EXPIRATION, REDIS_URL
from utils.models import UsernameLookup, BatchLookup, LoginRequest

# Initialize redis connection
redis_connection = redis.from_url(REDIS_URL, encoding="utf8")

# Validation patterns (used with fullmatch so a trailing newline can't slip past)
USERNAME_PATTERN = re.compile(r'[a-zA-Z0-9:/?&=#._%+-]+')
JOB_ID_PATTERN = re.compile(r'[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}')

def username_cache_key(username: str) -> str:
    """
    Redis key caching the lookup job for a username
    """
    return f"wmn:username:{username}"

def batch_cache_key(master_job_id: str) -> str:
    """
    Redis key holding the sub-jobs of a batch lookup
    """
    return f"wmn:batch:{master_job_id}"

def has_valid_result(result) -> bool:
    """
    True if a finished task returned usable lookup results
    """
    return isinstance(result, dict) and bool(result) and 'error' not in result

async def get_reusable_job(username: str) -> Optional[str]:
    """
    Return the cached job_id for a username if that job is pending or succeeded,
    otherwise None so a new job is started.
    """
    cached_job_id = await redis_connection.get(username_cache_key(username))
    if not cached_job_id:
        return None

    cached_job_id = cached_job_id.decode('utf-8')
    logger.info(f"Cache hit for username: {username}, found cached job_id: {cached_job_id}")
    task_result = AsyncResult(cached_job_id)

    # Job is still pending
    if task_result.state == 'PENDING':
        logger.debug(f"Cached job_id {cached_job_id} is still pending.")
        return cached_job_id

    # Results were successful without errors and returned results
    if task_result.state == 'SUCCESS' and has_valid_result(task_result.result):
        logger.info(f"Cached job_id {cached_job_id} completed successfully.")
        return cached_job_id

    # If the job is in FAILURE or any other state, start a new job
    logger.warning(f"Cached job_id {cached_job_id} is no longer valid. Starting a new job.")
    return None

async def start_job(username: str) -> str:
    """
    Start a lookup task for a username and cache its job_id
    """
    task = check_username.delay(username)
    logger.info(f"Task created with job_id: {task.id} for lookup username: {username}")

    # Store the new job_id in the cache with an expiration time
    await redis_connection.setex(username_cache_key(username), CACHE_EXPIRATION, task.id)
    return task.id

def summarize_task(task_result) -> dict:
    """
    Describe the state of a lookup task for status responses
    """
    if task_result.state == 'PENDING':
        return {"status": "pending"}

    if task_result.state == 'SUCCESS':
        result = task_result.result
        if has_valid_result(result):
            return {"status": "complete", "results": result}
        error = result.get('error', 'Unknown error') if isinstance(result, dict) else 'Unknown error'
        return {"status": "failed", "error": error}

    if task_result.state == 'FAILURE':
        return {"status": "failed", "error": str(task_result.info)}

    return {"status": "unknown", "state": task_result.state}

@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Initiate rate limiter
    """
    await FastAPILimiter.init(redis_connection)
    yield
    # FastAPILimiter.close() uses redis' deprecated close(); close the connection directly
    await redis_connection.aclose()

# Initialize the FastAPI app and FastAPILimiter
description = """
## 💎 About

[WhatsMyName (WMN)](https://github.com/WebBreacher/WhatsMyName) by [Micah "WebBreacher" Hoffman](https://webbreacher.com/) was created in 2015 with the goal of discovering usernames on a given website. WMN-Docker creates an API wrapper in a containerized Docker environment around WMN for integration, modularity, and scalability with other OSINT tooling.

## ✨ Features

WMN-Docker offers straightforward functionality to compliment the original intent of WMN while ensuring a basic level of security and bonus features.

- JWT Authentication
- Username Lookup
- Batch Username Lookup
- Job Results

## 📬 Contact
**On the Web**: [KodamaChameleon.com](https://kodamachameleon.com/community)  
**Email**: [contact@kodamachameleon.com](mailto:contact%40kodamachameleon.com?subject=WhatsMyName-Docker)

## 📜 License

![Creative Commons](https://img.shields.io/badge/Creative_Commons-4.0-white.svg?logo=creativecommons)

[Creative Commons Attribution-ShareAlike 4.0 International License](http://creativecommons.org/licenses/by-sa/4.0/).
"""

tags_metadata = [
    {
        "name": "auth",
        "description": "Authentication using using basic JSON Web Tokens (JWT)",
    },
    {
        "name": "lookups",
        "description": "Initiate a celery task to lookup usernames individually or in batch",
    },
    {
      "name": "results",
      "description": "Check the results status for a given job (single or batch)"  
    },
]

app = FastAPI(
    title="WhatsMyName-Docker",
    description=description,
    version="1.1.0",
    openapi_tags=tags_metadata,
    openapi_url="/api/v1/schema.json",
    lifespan=lifespan
)

# Define the routes
@app.post("/api/v1/token", tags=["auth"])
async def login_for_access_token(login_request: LoginRequest):
    """
    Authenticate the user by user_id and secret, and return a JWT token.
    """
    # Authenticate the user using user_id and secret from the Pydantic model
    user = authenticate_user(login_request.user_id, login_request.secret)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect user ID or secret")

    # Create JWT token with user_id in the payload ('sub' claim)
    token_data = {"sub": user.user_id}  # 'sub' is the subject claim in JWT
    access_token = create_access_token(token_data)

    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/api/v1/lookup", dependencies=[Depends(RateLimiter(times=RATE_LIMIT, seconds=60))], tags=["lookups"])
async def submit_username(request: UsernameLookup, user: dict =  Depends(optional_auth_dependency())) -> dict:
    """
    Initiate task to lookup username
    """
    try:
        # Validate the username
        username = request.username
        if not USERNAME_PATTERN.fullmatch(username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username must contain only valid URL characters."
            )

        # Reuse a cached job if it is still useful
        cached_job_id = await get_reusable_job(username)
        if cached_job_id:
            return {"job_id": cached_job_id}

        return {"job_id": await start_job(username)}

    except HTTPException as http_ex:

        # Handle specific HTTPException, 400 Bad Request
        if http_ex.status_code == status.HTTP_400_BAD_REQUEST:
            logger.error(f"Bad Request: {http_ex.detail}")
            raise http_ex

        raise http_ex

    # Handle unknown error
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred."
        )


@app.post("/api/v1/batch", dependencies=[Depends(RateLimiter(times=RATE_LIMIT, seconds=60))], tags=["lookups"])
async def submit_batch_usernames(request: BatchLookup, user: dict = Depends(optional_auth_dependency())) -> dict:
    """
    Submit multiple usernames for lookup as a batch.
    """
    try:
        # Validate and process the input usernames
        usernames = request.usernames

        logger.info(f"Received batch lookup request for {len(usernames)} usernames.")

        # Initialize results for the batch
        master_job_id = str(uuid4())
        batch_results = {}

        for username in usernames:
            # Validate the username format
            if not USERNAME_PATTERN.fullmatch(username):
                batch_results[username] = {"status": "error", "detail": "Invalid username format"}
                continue

            # Reuse a cached job if it is still useful
            cached_job_id = await get_reusable_job(username)
            if cached_job_id:
                batch_results[username] = {"job_id": cached_job_id, "status": "cached"}
                continue

            # Create a new job for the username
            batch_results[username] = {"job_id": await start_job(username), "status": "new"}

        # Store the master job in Redis, referencing individual jobs
        await redis_connection.setex(
            batch_cache_key(master_job_id), CACHE_EXPIRATION, json.dumps(batch_results)
        )

        return {"master_job_id": master_job_id, "jobs": batch_results}

    except HTTPException as http_ex:
        logger.error(f"Batch submission error: {http_ex.detail}")
        raise http_ex

    except Exception as e:
        logger.error(f"Unexpected error during batch submission: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during batch submission."
        )


@app.get("/api/v1/status/{job_id}", dependencies=[Depends(RateLimiter(times=RATE_LIMIT, seconds=60))], tags=["results"])
async def job_status(job_id: str, user: dict = Depends(optional_auth_dependency())) -> dict:
    """
    Check job status of username lookup or batch lookup.
    """
    try:
        # Validate the job_id format
        if not JOB_ID_PATTERN.fullmatch(job_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid job_id format. Must be a valid UUID."
            )

        logger.info(f"Received request to check status for job_id: {job_id}")

        # Check if the job_id corresponds to a batch
        batch_data = await redis_connection.get(batch_cache_key(job_id))
        if batch_data:
            logger.info(f"Job ID {job_id} identified as a batch lookup.")
            batch_results = json.loads(batch_data)

            # Aggregate the status of all jobs in the batch
            aggregated_results = {}
            for username, job_info in batch_results.items():
                sub_job_id = job_info.get("job_id")
                if not sub_job_id:
                    aggregated_results[username] = {"status": "error", "detail": "Invalid job ID"}
                    continue

                aggregated_results[username] = summarize_task(AsyncResult(sub_job_id))

            return {"job_id": job_id, "type": "batch", "results": aggregated_results}

        # Handle single username lookup
        summary = summarize_task(AsyncResult(job_id))
        if summary["status"] == "failed":
            logger.error(f"Job {job_id} failed with error: {summary['error']}")
        elif summary["status"] == "unknown":
            logger.warning(f"Job {job_id} is in an unknown state: {summary['state']}")
        else:
            logger.debug(f"Job {job_id} status: {summary['status']}")

        return {"job_id": job_id, **summary, "type": "single"}

    except HTTPException as http_ex:
        logger.error(f"Error while checking job status for job_id {job_id}: {http_ex.detail}")
        raise http_ex

    except Exception as e:
        logger.error(f"Unexpected error while checking job status for job_id {job_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while checking job status."
        )


if __name__ == "__main__":
    uvicorn.run("main:app", port=8000, reload=True)
