"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        core.py
Purpose:     Core utilities for WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
import os
import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import aiohttp

from .config import LOG_DIR, LOG_FILE, WMN_HEADERS, WMN_URL

# Configure logging with rotation
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, LOG_FILE)
handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5)
logging.basicConfig(
    level=logging.INFO,
    handlers=[handler],
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("wmn-docker")

async def username_lookup(username: str):
    """
    Main lookup function for finding a username on various platforms.
    
    Args:
        username (str): The username to lookup.

    Returns:
        list: A list of found sites with the username.
    """
    logger.info(f"Looking up username: {username}")
    data = None
    async with aiohttp.ClientSession() as session:
        try:
            response = await session.get(WMN_URL, headers=WMN_HEADERS)
            if response.content_type != 'application/json':
                data_content = await response.text()
                data = json.loads(data_content)
            else:
                data = await response.json()

        except Exception as e:
            logger.error(f"Error fetching WMN data: {e}")
            return []

    if data:
        found_sites = await check_username_existence(username, data)
        return found_sites
    else:
        logger.warning(f"No data found in WMN lookup for username: {username}")


async def check_site(session, site, username):
    """Checks if the username exists on a specific site."""
    try:
        async with session.get(site["uri_check"].format(account=username), headers=WMN_HEADERS) as response:
            text = await response.text()
            if response.status == site["e_code"] and site["e_string"] in text:
                return site["name"], site["uri_check"].format(account=username)
    except asyncio.TimeoutError:
        logger.error(f"Timeout error checking {site['name']}")
    except aiohttp.ClientError as e:
        logger.error(f"Client error checking {site['name']}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error checking {site['name']}: {e}")
    return None


async def check_username_existence(username, data):
    """Checks multiple sites for the existence of a username."""
    found_sites = []
    async with aiohttp.ClientSession() as session:
        tasks = [check_site(session, site, username) for site in data["sites"]]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        found_sites.extend([res for res in results if res is not None])
    return found_sites
