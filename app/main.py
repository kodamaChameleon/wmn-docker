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

@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Initiate rate limiter
    """
    await FastAPILimiter.init(redis_connection)
    yield
    await FastAPILimiter.close()

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
        if not re.match(r'^[a-zA-Z0-9:/?&=#._%+-]+$', username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username must contain only valid URL characters."
            )

        # Check if the username is in the cache
        cached_job_id = await redis_connection.get(username)
        if cached_job_id:
            logger.info(f"Cache hit for username: {username}, found cached job_id: {cached_job_id}")

            # Check the job status of the cached job ID
            task_result = AsyncResult(cached_job_id)

            # Job is still pending
            if task_result.state == 'PENDING':
                logger.debug(f"Cached job_id {cached_job_id} is still pending.")
                return {"job_id": cached_job_id}

            # Results were successful without errors and returned results
            elif task_result.state == 'SUCCESS' and task_result.result and 'error' not in task_result.result:
                logger.info(f"Cached job_id {cached_job_id} completed successfully with result: {task_result.result}")
                return {"job_id": cached_job_id}

            # If the job is in FAILURE or any other state, start a new job
            logger.warning(f"Cached job_id {cached_job_id} is no longer valid. Starting a new job.")

        task = check_username.delay(username)
        logger.info(f"Task created with job_id: {task.id} for lookup username: {username}")

        # Store the new job_id in the cache with an expiration time
        await redis_connection.setex(username, CACHE_EXPIRATION, task.id)

        return {"job_id": task.id}

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
            if not re.match(r'^[a-zA-Z0-9:/?&=#._%+-]+$', username):
                batch_results[username] = {"status": "error", "detail": "Invalid username format"}
                continue

            # Check cache for existing job ID
            cached_job_id = await redis_connection.get(username)
            if cached_job_id:
                cached_job_id = cached_job_id.decode('utf-8')  # Decode bytes to string
                logger.info(f"Cache hit for username: {username}, using cached job_id: {cached_job_id}")
                batch_results[username] = {"job_id": cached_job_id, "status": "cached"}
                continue

            # Create a new job for the username
            task = check_username.delay(username)
            logger.info(f"Task created with job_id: {task.id} for username: {username}")

            # Store job_id in cache
            await redis_connection.setex(username, CACHE_EXPIRATION, task.id)

            batch_results[username] = {"job_id": task.id, "status": "new"}

        # Store the master job in Redis, referencing individual jobs
        await redis_connection.setex(master_job_id, CACHE_EXPIRATION, json.dumps(batch_results))

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
        if not re.match(
                r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$',
                job_id
            ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid job_id format. Must be a valid UUID."
            )

        logger.info(f"Received request to check status for job_id: {job_id}")

        # Check if the job_id corresponds to a batch
        batch_data = await redis_connection.get(job_id)
        if batch_data:
            logger.info(f"Job ID {job_id} identified as a batch lookup.")
            batch_results = json.loads(batch_data)

            # Aggregate the status of all jobs in the batch
            aggregated_results = {}
            for username, job_info in batch_results.items():
                job_id = job_info.get("job_id")
                if not job_id:
                    aggregated_results[username] = {"status": "error", "detail": "Invalid job ID"}
                    continue

                task_result = AsyncResult(job_id)
                if task_result.state == 'PENDING':
                    aggregated_results[username] = {"status": "pending"}
                elif task_result.state == 'SUCCESS':
                    if task_result.result and 'error' not in task_result.result:
                        aggregated_results[username] = {
                            "status": "complete",
                            "results": task_result.result
                        }
                    else:
                        aggregated_results[username] = {
                            "status": "failed",
                            "error": task_result.result.get('error', 'Unknown error')
                        }
                elif task_result.state == 'FAILURE':
                    aggregated_results[username] = {
                        "status": "failed",
                        "error": str(task_result.info)
                    }
                else:
                    aggregated_results[username] = {
                        "status": "unknown",
                        "state": task_result.state
                    }

            return {"job_id": job_id, "type": "batch", "results": aggregated_results}

        # Handle single username lookup
        task_result = AsyncResult(job_id)
        if task_result.state == 'PENDING':
            logger.debug(f"Job {job_id} is still processing.")
            return {"job_id": job_id, "status": "pending", "type": "single"}

        if task_result.state == 'SUCCESS':
            logger.info(f"Job {job_id} completed successfully with results: {task_result.result}")
            if task_result.result and 'error' not in task_result.result:
                return {
                    "job_id": job_id,
                    "status": "complete",
                    "results": task_result.result,
                    "type": "single"
                }
            return {
                "job_id": job_id,
                "status": "failed",
                "error": task_result.result.get('error', 'Unknown error'),
                "type": "single"
            }

        if task_result.state == 'FAILURE':
            logger.error(f"Job {job_id} failed with error: {task_result.info}")
            return {
                "job_id": job_id,
                "status": "failed",
                "error": str(task_result.info),
                "type": "single"
            }

        logger.warning(f"Job {job_id} is in an unknown state: {task_result.state}")
        return {"job_id": job_id, "status": "unknown", "state": task_result.state, "type": "single"}

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
