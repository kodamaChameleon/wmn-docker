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
from aiohttp import TCPConnector, ClientSession, ClientError, ClientTimeout

from .config import (
    LOG_DIR,
    LOG_FILE,
    WMN_HEADERS,
    WMN_URL,
    SSL_WEBSITE_ENUMERATION,
    CHECK_SITE_TIMEOUT
)

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

    async with ClientSession() as session:
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
        found_sites, stats = await check_username_existence(username, data)
        return {"username": username, "websites": found_sites, "stats": stats}

    logger.warning(f"No data found in WMN lookup for username: {username}")


async def check_site(session, site, username):
    """Checks if the username exists on a specific site."""
    timeout = ClientTimeout(total=CHECK_SITE_TIMEOUT)
    try:
        async with session.get(
            site["uri_check"].format(account=username),
            headers=WMN_HEADERS,
            timeout=timeout
        ) as response:
            text = await response.text()
            if response.status == site["e_code"] and site["e_string"] in text:
                return site["name"], site["uri_check"].format(account=username)

    except asyncio.TimeoutError:
        logger.error(f"Timeout error checking {site['name']}")
        return "error", site["name"]

    except ClientError as e:
        logger.error(f"Client error checking {site['name']}: {e}")
        return "error", site["name"]

    except Exception as e:
        logger.error(f"Unexpected error checking {site['name']}: {e}")
        return "error", site["name"]

    return None


async def check_username_existence(username, data):
    """Checks multiple sites for the existence of a username."""
    # Configure SSL certificate verification
    connector = TCPConnector(ssl=SSL_WEBSITE_ENUMERATION)

    found_sites = []
    checked_count = 0
    error_count = 0

    async with ClientSession(connector=connector) as session:
        tasks = [check_site(session, site, username) for site in data["sites"]]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Iterate over results to count successes and errors
        for result in results:
            checked_count += 1
            if result:
                if result[0] == "error":
                    error_count += 1
                elif result is not None:
                    found_sites.append(result)

    # Return statistics alongside found sites
    stats = {
        "websites_checked": checked_count,
        "profiles_found": len(found_sites),
        "errors": error_count,
    }

    return found_sites, stats
