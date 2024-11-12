"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        api.py
Purpose:     CLI utility of WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
import time
import os
from typing import Optional
import requests

# Configure the API endpoint and default token environment variable
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").lower() == "true"
USER_ID = os.getenv("USER_ID", None)
SECRET = os.getenv("SECRET", None)
headers = {
    "Content-Type": "application/json"
}

def get_access_token(user_id: str, secret: str) -> Optional[str]:
    """
    Get an access token from the FastAPI backend by sending user_id and secret.

    Args:
        user_id (str): The user ID for authentication.
        secret (str): The secret key for authentication.

    Returns:
        Optional[str]: The access token if successful, None if failed.
    """
    # Create the payload for the request
    payload = {
        "user_id": user_id,
        "secret": secret
    }

    try:
        # Send the POST request to get the access token
        api_url = f"{API_BASE_URL}/api/v1/token"
        response = requests.post(api_url, json=payload)

        # Check if the response status is OK
        if response.status_code == 200:
            # Extract the access token from the response
            data = response.json()
            access_token = data.get("access_token")
            return access_token
        else:
            # Handle unsuccessful requests (authentication failure, etc.)
            print(f"Failed to get access token: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error while requesting access token: {e}")
        return None

def submit_username(username, token=None):
    """
    Submit a username to the API for processing.
    """
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/v1/lookup",
            json={"username": username},
            headers=headers
        )
        response.raise_for_status()
        job_id = response.json().get("job_id")
        print(f"Job submitted successfully! Job ID: {job_id}")
        return job_id
    except requests.RequestException as e:
        print(f"Error submitting username: {e}")
        return None

def check_job_status(job_id, token=None):
    """
    Check the status of a job and return the result if completed.
    """
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(f"{API_BASE_URL}/api/v1/status/{job_id}", headers=headers)
        response.raise_for_status()
        status_info = response.json()
        return status_info
    except requests.RequestException as e:
        print(f"Error checking job status: {e}")
        return None

def user_lookup(args):
    """
    Combine all api calls into single username lookup
    """

    username = args.username
    api_id = args.api_id or USER_ID
    api_secret = args.api_secret or SECRET

    # Check if authentication is required but credentials are missing
    if AUTH_REQUIRED and (not api_id or not api_secret):
        print("Error: API username and password are required but not provided.")
        return

    # Obtain access token if authentication is required
    token = None
    if AUTH_REQUIRED:
        token = get_access_token(api_id, api_secret)
        if not token:
            print("Failed to obtain access token. Exiting.")
            return

    # Submit username to the API
    job_id = submit_username(username, token)
    if not job_id:
        print("Failed to submit the username. Exiting.")
        return

    # Poll the job status until it completes
    status_check_frequency = 15
    while True:
        job_status = check_job_status(job_id, token)
        if not job_status:
            print("Error retrieving job status. Exiting.")
            return

        status = job_status.get("status")
        if status == "Job complete":
            print("Job complete. Results:")
            print(job_status["result"])
            break
        elif status == "Job failed":
            print("Job failed:", job_status.get("error"))
            break
        else:
            print(f"Job is still processing... checking again in {status_check_frequency} seconds.")
            time.sleep(status_check_frequency)
