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
import json
from typing import Optional
import requests
from dotenv import load_dotenv
from colorama import Fore, Style, init

# Initialize env and colorama
load_dotenv(override=True)
init(autoreset=True)

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
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=15
        )

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

def submit_username(username: str, token=None) -> Optional[str]:
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

def submit_batch_usernames(usernames: list, token=None) -> Optional[str]:
    """
    Submit a batch of usernames to the API for processing.
    """
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/v1/batch",
            json={"usernames": usernames},
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        master_job_id = data.get("master_job_id")
        jobs = data.get("jobs", {})
        print(f"Batch job submitted successfully! Master Job ID: {master_job_id}")

        # Print each job's status
        for username, job_info in jobs.items():
            print(f"{Fore.CYAN}{username}{Style.RESET_ALL}: {job_info.get('status')} (Job ID: {job_info.get('job_id')})")

        return master_job_id

    except requests.RequestException as e:
        print(f"Error submitting batch usernames: {e}")
        return None

def check_job_status(job_id: str, token=None) -> Optional[dict]:
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

def poll_job_status(
        job_id: str,
        batch: bool,
        token: str=None,
        output_file: str=None,
        username: str=None
    ):
    """
    Poll the job status until it completes.
    """
    if token:
        headers["Authorization"] = f"Bearer {token}"

    status_check_frequency = 10
    while True:
        try:
            response = requests.get(
                f"{API_BASE_URL}/api/v1/status/{job_id}",
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
            job_status = response.json()
        except requests.RequestException as e:
            print(f"{Fore.RED}Error checking job status: {e}{Style.RESET_ALL}")
            return

        # Get job status
        if batch:

            # Continue for loop until all are complete
            for _, result in job_status.get("results").items():
                status = result.get("status")
                if result.get("status") == "error":
                    raise ValueError(result.get("detail"))
                elif result.get("status") != "complete":
                    break
        else:
            status = job_status.get("status")

        if status == "complete":
            print(f"Job ID {job_id} complete!")
            results = job_status.get("results", {})

            if batch:
                for sub_username, subtask in results.items():
                    print(f"\n{Fore.MAGENTA}RESULTS FOR {Fore.CYAN}{sub_username.upper()}{Style.RESET_ALL}:")
                    display_results(subtask.get("results", {}))
            else:
                try:
                    print(f"\n{Fore.MAGENTA}RESULTS FOR {Fore.CYAN}{username.upper()}{Style.RESET_ALL}:")
                except Exception as e:
                    print(Fore.RED + "Error determining username." + Style.RESET_ALL)

                display_results(results)

            # If output file is specified, save results as json
            if output_file:
                with open(output_file, 'w') as f:
                    json.dump(results, f, indent=2)
                print(f"\nResults saved to {output_file}")

            break

        if status == "failed":
            print(f"{Fore.RED}Job failed:{Style.RESET_ALL}\n{job_status.get('error')}")
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

def user_lookup(args):
    """
    Combine all API calls into a single username or batch lookup.
    """
    print(banner)

    usernames = args.username.split(",")  # Split comma-separated usernames into a list
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

    if len(usernames) > 1:
        # Handle batch submission
        job_id = submit_batch_usernames(usernames, token)
        batch = True
        username = None
    else:
        # Single username submission
        job_id = submit_username(usernames[0], token)
        batch = False
        username = usernames[0]
        if not job_id:
            print(Fore.RED + "Failed to submit the username. Exiting." + Style.RESET_ALL)
            return

    poll_job_status(job_id, batch, token, output_file=args.output, username=username)

def display_results(result):
    """
    Display the job results in a formatted manner.
    """

    websites = result.get("websites", [])
    stats = result.get("stats", {})

    # Print each found website
    if websites:
        print(f"{Fore.MAGENTA}\nFound Profiles:{Style.RESET_ALL}")
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
