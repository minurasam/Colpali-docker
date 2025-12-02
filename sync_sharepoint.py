#!/usr/bin/env python3
"""
Main entry point for SharePoint to Blob Storage sync.
Run this script to sync files from FortiMind SharePoint to Azure Blob Storage.

Usage:
    python sync_sharepoint.py
"""

from utils.sharepoint_sync import main

if __name__ == "__main__":
    main()
