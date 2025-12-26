"""Configuration for multi-turn agentic chat."""

import os

# Conversation persistence
CONVERSATION_DB_PATH = os.getenv("CONVERSATION_DB_PATH", "./data/conversations.db")
CONVERSATION_TTL_HOURS = int(os.getenv("CONVERSATION_TTL_HOURS", "4"))
MAX_CONVERSATIONS = int(os.getenv("MAX_CONVERSATIONS", "100"))
CLEANUP_ON_STARTUP = os.getenv("CLEANUP_ON_STARTUP", "true").lower() == "true"

# Chat agent configuration
CHAT_MODEL = os.getenv("CHAT_MODEL", "claude-sonnet-4-5")
CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.1"))
CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "2048"))
CHAT_MAX_ITERATIONS = int(os.getenv("CHAT_MAX_ITERATIONS", "3"))

# System message for conversational context
CHAT_SYSTEM_MESSAGE = """You are a helpful assistant for searching and discussing a personal image collection.

You have access to the conversation history and can reference previous exchanges.
When the user says things like "show me more", "what about...", or "filter those by...",
use the conversation context to understand their intent.

Available tools:
- search_collections: Search the image collection using hybrid search (keyword + semantic)

Guidelines:
- Reference previous search results when relevant
- If the user's request is unclear, ask a clarifying question
- Provide concise, helpful responses
- Remember context from earlier in the conversation
- When showing results, highlight what's new vs. what was shown before

Search behavior:
- The search tool uses semantic understanding - synonyms and related terms are matched automatically
- Only refine searches if results are clearly inadequate (< 3 results or completely off-topic)
- For follow-up queries like "show me more" or "what else", try different search terms based on context
"""
