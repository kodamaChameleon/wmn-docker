"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        setup.py
Purpose:     Setup of WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
import os
import shutil
import subprocess
import sys
import base64

def install_dependencies():
    """
    Install python dependencies for app and client
    """
    subprocess.check_call(['pip', 'install', '-r', 'requirements.txt'])

def setup_environment_file():
    """
    Create a .env file from .env_sample if it doesn't already exist.
    """
    if os.path.exists('.env'):
        print(".env file already exists. Skipping copy.")
    else:
        shutil.copy('.env_sample', '.env')
        print("Copied .env_sample to .env. Please populate it with your secrets.")

def populate_env_with_secrets():
    """
    Populate the .env file with secure, randomly generated values for sensitive
    environment variables.
    """
    env_file = '.env'
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding="utf-8") as file:
            content = file.read()

        # Use Python's secrets module to generate a secure, random key
        secret_key = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8')

        # Replace placeholders with secure values
        content = content.replace('SECRET_KEY=your_secret_key_here', f'SECRET_KEY={secret_key}')

        with open(env_file, 'w', encoding="utf-8") as file:
            file.write(content)

        print("Updated .env with secure SECRET_KEY.")
    else:
        print(f"{env_file} does not exist. Ensure you have copied .env_sample to .env first.")

def build_docker_container():
    """
    Build a Docker container from a Dockerfile.
    """
    try:
        # Build the Docker container
        print("Building the Docker container from the Dockerfile...")
        subprocess.check_call(['docker-compose', 'build'])
        print("Docker container built successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to build the Docker container: {e}")
        sys.exit(1)

def start_docker_containers(context: str):
    """
    Start the Docker containers using docker-compose with the appropriate config file.
    
    :param context: The environment context, either 'dev' or 'prod'
    """
    try:
        if context == "dev":
            # Use the dev-specific docker-compose file
            subprocess.check_call(['docker-compose', '-f', 'docker-compose-dev.yml', 'up', '-d'])
            print("Spinning up containers in development mode.")
        elif context == "prod":
            # Use the prod-specific docker-compose file
            subprocess.check_call(['docker-compose', '-f', 'docker-compose.yml', 'up', '-d'])
            print("Spinning up containers in production mode.")
        else:
            raise ValueError("Unknown context. Please specify 'dev' or 'prod'.")

        # Wait for containers to initialize
        subprocess.call(['sleep', '5'])  
        print("Docker containers are up and running.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to launch docker-compose: {e}")
        sys.exit(1)

def start_setup(context: str):
    """
    Launch startup for prod or dev context
    """

    if not context or context == 'dev':
        install_dependencies()
        setup_environment_file()
        populate_env_with_secrets()
        build_docker_container()
        start_docker_containers('dev')
    elif context == 'prod':
        setup_environment_file()
        populate_env_with_secrets()
        start_docker_containers('prod')
    else:
        raise ValueError("Unknown build context")
