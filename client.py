"""
!/usr/bin/env python3
-*- coding: utf-8 -*-
Name:        client.py
Purpose:     Setup and testing of WhatsMyName Docker API
Author:      Kodama Chameleon <contact@kodamachameleon.com>
Created:     11/11/2024
Copyright:   (c) Kodama Chameleon 2024
Licence:     CC BY 4.0
"""
import argparse
import os

def parse_arguments():
    """
    Define command line arguments
    """
    parser = argparse.ArgumentParser(description="CLI client for the WMN API")

    # For API usage
    parser.add_argument("-u", "--username", help="Username(s) to lookup, comma separated")
    parser.add_argument("-I", "--api_id", help="API user ID for authentication (optional)")
    parser.add_argument("-S", "--api_secret", help="API secret for authentication (optional)")
    parser.add_argument("-o", "--output", help="Specify a file output (json)")

    # Configure setup arguments
    parser.add_argument(
        "-s", "--setup", 
        nargs='?',
        const='prod',
        choices=["dev", "prod"],
        help="Set up configuration (options: 'dev' or 'prod')."
    )

    return parser.parse_args()

def main():
    """
    Run client from command line
    """
    args = parse_arguments()

    if not os.path.exists(".env") or args.setup:
        from utils.setup import start_setup
        start_setup(args.setup)

    elif args.username:
        from utils.api import user_lookup
        user_lookup(args)

    else:
        raise ValueError("No arguments specified")

if __name__ == "__main__":
    main()
