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
from utils.config import UsernameLookup, LoginRequest, RATE_LIMIT, CACHE_EXPIRATION, redis_url

# Initialize redis connection
redis_connection = redis.from_url(redis_url, encoding="utf8")

@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Initiate rate limiter
    """
    await FastAPILimiter.init(redis_connection)
    yield
    await FastAPILimiter.close()

# Initialize the FastAPI app and FastAPILimiter
app = FastAPI(lifespan=lifespan)

# Define the routes
@app.post("/api/v1/token")
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


@app.post("/api/v1/lookup", dependencies=[Depends(RateLimiter(times=RATE_LIMIT, seconds=60))])
async def submit_username(request: UsernameLookup, user: dict =  Depends(optional_auth_dependency())):
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
            # If cached, return the cached job_id
            logger.info(f"Cache hit for username: {username}, returning job_id: {cached_job_id}")
            return {"job_id": cached_job_id}

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


@app.get("/api/v1/status/{job_id}", dependencies=[Depends(RateLimiter(times=RATE_LIMIT, seconds=60))])
async def job_status(job_id: str, user: dict =  Depends(optional_auth_dependency())):
    """
    Check job status of username lookup
    """
    try:
        # Validate the job_id as a UUID
        if not re.match(r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$', job_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid job_id format. Must be a valid UUID."
            )

        logger.info(f"Received request to check status for job_id: {job_id}")
        task_result = AsyncResult(job_id)

        if task_result.state == 'PENDING':
            logger.debug(f"Job {job_id} is still processing")
            return {"status": "Job is still processing"}
        elif task_result.state == 'SUCCESS':
            logger.info(f"Job {job_id} completed successfully with result: {task_result.result}")
            return {"status": "Job complete", "result": task_result.result}
        elif task_result.state == 'FAILURE':
            logger.error(f"Job {job_id} failed with error: {task_result.info}")
            return {"status": "Job failed", "error": str(task_result.info)}
        else:
            logger.warning(f"Job {job_id} is in an unknown state: {task_result.state}")
            return {"status": "Unknown state", "state": task_result.state}

    except HTTPException as http_ex:
        
        # Handle specific HTTPException, 400 Bad Request
        if http_ex.status_code == status.HTTP_400_BAD_REQUEST:
            logger.error(f"Bad Request: {http_ex.detail}")
            raise http_ex

        raise http_ex

    except Exception as e:
        logger.error(f"Unexpected error while checking job status for job_id {job_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while checking job status."
        )


if __name__ == "__main__":
    uvicorn.run("main:app", port=8000, reload=True)
