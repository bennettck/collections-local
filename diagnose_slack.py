#!/usr/bin/env python3
"""
Diagnostic script to check Slack notification setup
"""

import os
import sys
from pathlib import Path

def load_env_file():
    """Load environment variables from .env file"""
    possible_paths = [
        Path.cwd() / '.env',
        Path.home() / '.env'
    ]
    
    for env_file in possible_paths:
        if env_file.exists():
            print(f"   Found .env file at: {env_file}")
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        if key not in os.environ:
                            os.environ[key] = value
            return str(env_file)
    return None

print("=== Slack Notification Setup Diagnostic ===\n")

# Check 1: Environment variable
print("1. Checking SLACK_WEBHOOK_URL environment variable...")

# Try loading from .env first
env_file_path = load_env_file()
if env_file_path:
    print(f"   Loaded from: {env_file_path}")

webhook_url = os.environ.get('SLACK_WEBHOOK_URL')

if webhook_url:
    print(f"   ✓ Found: {webhook_url[:50]}..." if len(webhook_url) > 50 else f"   ✓ Found: {webhook_url}")
    
    # Check if it looks valid
    if webhook_url.startswith('https://hooks.slack.com/services/'):
        print("   ✓ URL format looks correct")
    else:
        print("   ✗ WARNING: URL doesn't start with 'https://hooks.slack.com/services/'")
        print(f"     Your URL starts with: {webhook_url[:40]}...")
else:
    print("   ✗ NOT FOUND")
    print("\n   To fix this, you can either:\n")
    print("   Option 1 - Create a .env file:")
    print("   echo 'SLACK_WEBHOOK_URL=\"your-webhook-url\"' > ~/.env")
    print("   OR")
    print("   echo 'SLACK_WEBHOOK_URL=\"your-webhook-url\"' > .env  # in your project directory\n")
    print("   Option 2 - Use shell environment variables:")
    print("   For zsh (macOS default):")
    print("   echo 'export SLACK_WEBHOOK_URL=\"your-webhook-url\"' >> ~/.zshrc")
    print("   source ~/.zshrc\n")
    print("   For bash:")
    print("   echo 'export SLACK_WEBHOOK_URL=\"your-webhook-url\"' >> ~/.bashrc")
    print("   source ~/.bashrc\n")
    sys.exit(1)

# Check 2: Python version
print("\n2. Checking Python version...")
print(f"   ✓ Python {sys.version.split()[0]}")

# Check 3: Try to import required modules
print("\n3. Checking required Python modules...")
try:
    import json
    import urllib.request
    import urllib.error
    print("   ✓ All required modules available")
except ImportError as e:
    print(f"   ✗ Missing module: {e}")
    sys.exit(1)

# Check 4: Test connection
print("\n4. Testing connection to Slack...")
print("   Sending test notification...")

import json
from urllib import request, error

payload = {
    "text": "🧪 Test notification from diagnostic script - setup is working!"
}

try:
    req = request.Request(
        webhook_url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    with request.urlopen(req, timeout=10) as response:
        if response.status == 200:
            print("   ✓ SUCCESS! Notification sent to Slack")
            print("\n=== All checks passed! ===")
            print("Your setup is working correctly.")
            print("\nCheck your Slack channel for the test message.")
        else:
            print(f"   ✗ FAILED: Received status code {response.status}")
            print(f"   Response: {response.read().decode('utf-8')}")
            
except error.HTTPError as e:
    print(f"   ✗ HTTP Error: {e.code} - {e.reason}")
    if e.code == 404:
        print("   This usually means the webhook URL is incorrect or has been deleted.")
        print("   Please verify your webhook URL in the Slack app settings.")
    elif e.code == 400:
        print("   Bad request - the payload format might be wrong.")
    print(f"   Response: {e.read().decode('utf-8')}")
except error.URLError as e:
    print(f"   ✗ Connection Error: {e.reason}")
    print("   Check your internet connection.")
except Exception as e:
    print(f"   ✗ Unexpected error: {e}")

print("\n=== Diagnostic complete ===")