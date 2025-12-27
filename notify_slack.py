#!/usr/bin/env python3
"""
Slack Notification Script for Claude Code

Usage:
    python notify_slack.py "Your message here"
    python notify_slack.py "Your message" --type question
    python notify_slack.py "Task completed" --type success
    
Environment variable required:
    SLACK_WEBHOOK_URL - Your Slack incoming webhook URL
"""

import os
import sys
import json
import argparse
from datetime import datetime
from urllib import request, error
from pathlib import Path

# Emoji prefixes for different notification types
NOTIFICATION_TYPES = {
    'question': '❓',
    'error': '🚨',
    'warning': '⚠️',
    'success': '✅',
    'info': 'ℹ️',
    'task_complete': '🎉',
    'waiting': '⏳'
}

def load_env_file(env_path=None):
    """
    Load environment variables from a .env file
    
    Args:
        env_path: Path to .env file. If None, searches in current dir, then home dir
    """
    if env_path is None:
        # Search for .env in current directory, then home directory
        possible_paths = [
            Path.cwd() / '.env',
            Path.home() / '.env'
        ]
    else:
        possible_paths = [Path(env_path)]
    
    for env_file in possible_paths:
        if env_file.exists():
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse KEY=VALUE or KEY="VALUE" or KEY='VALUE'
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        
                        # Only set if not already in environment
                        if key not in os.environ:
                            os.environ[key] = value
            
            return str(env_file)
    
    return None

def send_slack_notification(message, notification_type='info', context=None):
    """
    Send a notification to Slack via webhook
    
    Args:
        message: The main message to send
        notification_type: Type of notification (question, error, warning, success, info, task_complete, waiting)
        context: Optional dict with additional context (task, file, details, etc.)
    """
    # Try to load from .env file if SLACK_WEBHOOK_URL not already set
    if 'SLACK_WEBHOOK_URL' not in os.environ:
        env_file = load_env_file()
        if env_file and 'SLACK_WEBHOOK_URL' in os.environ:
            print(f"Loaded SLACK_WEBHOOK_URL from {env_file}")
    
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    
    if not webhook_url:
        print("Error: SLACK_WEBHOOK_URL environment variable not set", file=sys.stderr)
        print("Please either:", file=sys.stderr)
        print("  1. Add SLACK_WEBHOOK_URL to a .env file in current or home directory", file=sys.stderr)
        print("  2. Set it with: export SLACK_WEBHOOK_URL='your-webhook-url'", file=sys.stderr)
        sys.exit(1)
    
    # Get emoji for notification type
    emoji = NOTIFICATION_TYPES.get(notification_type, 'ℹ️')
    
    # Build the message blocks
    blocks = []
    
    # Main message block
    main_text = f"{emoji} *Claude Code Notification*\n{message}"
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": main_text
        }
    })
    
    # Add context block if provided
    if context:
        context_elements = []
        
        if 'task' in context:
            context_elements.append(f"*Task:* {context['task']}")
        if 'file' in context:
            context_elements.append(f"*File:* `{context['file']}`")
        if 'details' in context:
            context_elements.append(f"*Details:* {context['details']}")
        
        if context_elements:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(context_elements)
                }
            })
    
    # Add timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"🕐 {timestamp}"
            }
        ]
    })
    
    # Prepare the payload
    payload = {
        "blocks": blocks,
        "text": f"{emoji} Claude Code: {message}"  # Fallback text for notifications
    }
    
    # Send the request
    try:
        req = request.Request(
            webhook_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        
        with request.urlopen(req) as response:
            if response.status == 200:
                print(f"✓ Notification sent successfully to Slack")
                return True
            else:
                print(f"✗ Failed to send notification. Status code: {response.status}", file=sys.stderr)
                return False
                
    except error.URLError as e:
        print(f"✗ Error sending notification: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Send notifications to Slack from Claude Code',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "Need your input on API design"
  %(prog)s "Should I use REST or GraphQL?" --type question
  %(prog)s "Tests are failing" --type error --task "Running test suite"
  %(prog)s "Deployment complete!" --type success
  %(prog)s "Waiting for API key" --type waiting --details "Need OPENAI_API_KEY"
  %(prog)s "Task done" --env-file /path/to/.env
        """
    )
    
    parser.add_argument('message', help='The notification message')
    parser.add_argument(
        '--type', '-t',
        choices=list(NOTIFICATION_TYPES.keys()),
        default='info',
        help='Type of notification (default: info)'
    )
    parser.add_argument('--task', help='Current task context')
    parser.add_argument('--file', help='File being worked on')
    parser.add_argument('--details', help='Additional details')
    parser.add_argument(
        '--env-file',
        help='Path to .env file (default: searches current dir, then home dir)'
    )
    
    args = parser.parse_args()
    
    # Load .env file if specified
    if args.env_file:
        loaded = load_env_file(args.env_file)
        if not loaded:
            print(f"Warning: Could not find .env file at {args.env_file}", file=sys.stderr)
    
    # Build context dict
    context = {}
    if args.task:
        context['task'] = args.task
    if args.file:
        context['file'] = args.file
    if args.details:
        context['details'] = args.details
    
    # Send notification
    success = send_slack_notification(
        args.message,
        args.type,
        context if context else None
    )
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()