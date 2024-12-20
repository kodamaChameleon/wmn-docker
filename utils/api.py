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
from dotenv import load_dotenv
import colorama
from colorama import Fore, Style

# Initialize env and colorama
load_dotenv(override=True)
colorama.init(autoreset=True)

banner = Fore.GREEN + f"""\
 _    _ _           _       ___  ___      _   _                            ______           _             
| |  | | |         | |      |  \/  |     | \ | |                           |  _  \         | |            
| |  | | |__   __ _| |_ ___ | .  . |_   _|  \| | __ _ _ __ ___   ___ ______| | | |___   ___| | _____ _ __ 
| |/\| | '_ \ / _` | __/ __|| |\/| | | | | . ` |/ _` | '_ ` _ \ / _ \______| | | / _ \ / __| |/ / _ \ '__|
\  /\  / | | | (_| | |_\__ \| |  | | |_| | |\  | (_| | | | | | |  __/      | |/ / (_) | (__|   <  __/ |   
 \/  \/|_| |_|\__,_|\__|___/\_|  |_/\__, \_| \_/\__,_|_| |_| |_|\___|      |___/ \___/ \___|_|\_\___|_|
                                     __/ |                                                                
                                    |___/                        by Kodama Chameleon | with {Fore.RED}❤️{Fore.GREEN} WebBreacher  
""" + Style.RESET_ALL

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
        response = requests.post(api_url, json=payload, headers=headers)

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
            headers=headers,
            timeout=15
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
        response = requests.get(
            f"{API_BASE_URL}/api/v1/status/{job_id}",
            headers=headers,
            timeout=15
        )
        response.raise_for_status()
        status_info = response.json()
        return status_info
    except requests.RequestException as e:
        print(f"Error checking job status: {e}")
        return None

def user_lookup(args):
    """
    Combine all API calls into a single username lookup.
    """
    print(banner)

    username = args.username
    api_id = args.api_id or USER_ID
    api_secret = args.api_secret or SECRET

    # Check if authentication is required but credentials are missing
    if AUTH_REQUIRED and (not api_id or not api_secret):
        print(Fore.RED + "Error: API username and password are required but not provided." + Style.RESET_ALL)
        return

    # Obtain access token if authentication is required
    token = None
    if AUTH_REQUIRED:
        token = get_access_token(api_id, api_secret)
        if not token:
            print(Fore.RED + "Failed to obtain access token. Exiting." + Style.RESET_ALL)
            return

    # Submit username to the API
    job_id = submit_username(username, token)
    if not job_id:
        print(Fore.RED + "Failed to submit the username. Exiting." + Style.RESET_ALL)
        return

    # Poll the job status until it completes
    status_check_frequency = 10
    while True:
        job_status = check_job_status(job_id, token)
        if not job_status:
            print(Fore.RED + "Error retrieving job status. Exiting." + Style.RESET_ALL)
            return

        status = job_status.get("status")
        if status == "Job complete":
            print(f"Job ID {job_id} complete!!")
            display_results(job_status["result"])
            break

        if status == "Job failed":
            print(f"{Fore.RED}\nJob failed:{Style.RESET_ALL}\n{job_status.get('error')}")
            break

        # Countdown timer for status check
        max_length = 0
        for remaining in range(status_check_frequency, 0, -1):
            message = f"{Fore.YELLOW}Job Pending: Checking again in {Style.RESET_ALL}{remaining}"
            
            # Pad the message before printing
            if len(message) > max_length:
                max_length = len(message)
            message = message + " "*(max_length - len(message))
            
            print(message, end="\r")
            time.sleep(1)
        
        # Clear the line after the countdown
        print(" " * max_length, end="\r")

def display_results(result):
    """
    Display the job results in a formatted manner.
    """

    websites = result.get("websites", [])
    stats = result.get("stats", {})

    # Print each found website
    if websites:
        print(f"{Fore.CYAN}\nFound Profiles:{Style.RESET_ALL}")
        for site in websites:
            site_name, site_url = site
            print(f"  {Fore.GREEN}{site_name}:{Style.RESET_ALL} {site_url}")
    else:
        print(f"{Fore.YELLOW}No profiles found.{Style.RESET_ALL}")

    # Print statistics
    print(f"\n{Fore.MAGENTA}Statistics:{Style.RESET_ALL}")
    print(f"  {Fore.BLUE}Websites Checked:{Style.RESET_ALL} {stats.get('websites_checked', 0)}")
    print(f"  {Fore.BLUE}Profiles Found:{Style.RESET_ALL} {stats.get('profiles_found', 0)}")
    print(f"  {Fore.BLUE}Errors Encountered:{Style.RESET_ALL} {stats.get('errors', 0)}")
