"""LLM-based answer generation from retrieved search results."""

import re
from typing import List, Dict, Optional, Any
from anthropic import Anthropic
from openai import OpenAI

# Initialize clients (reusing from llm.py pattern)
anthropic_client = Anthropic()
openai_client = OpenAI()


def format_results_for_llm(results: List[Dict[str, Any]]) -> str:
    """
    Format search results into context string for LLM.

    Args:
        results: List of search result dictionaries

    Returns:
        Formatted string with item details
    """
    if not results:
        return "No relevant items found."

    context_parts = []
    for i, result in enumerate(results, 1):
        context_parts.append(f"""
Item {i} (Relevance Score: {abs(result.get('score', 0)):.2f}):
Category: {result.get('category', 'Unknown')}
Title: {result.get('headline', 'No title')}
Description: {result.get('summary', 'No description')}
---""")

    return "\n".join(context_parts)


def _extract_citations(answer: str, num_results: int) -> List[str]:
    """
    Extract item citations from answer text.

    Looks for patterns like [Item 1], [Item 2], etc.

    Args:
        answer: Generated answer text
        num_results: Total number of results available

    Returns:
        List of cited item indices
    """
    citations = set()
    pattern = r'\[Item (\d+)\]'
    matches = re.findall(pattern, answer)

    for match in matches:
        item_num = int(match)
        if 1 <= item_num <= num_results:
            citations.add(str(item_num))

    return sorted(list(citations))


def generate_answer(
    query: str,
    results: List[Dict[str, Any]],
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate natural language answer from search results using LLM.

    Args:
        query: User's search query
        results: List of search result dictionaries
        model: Optional model name (defaults to claude-sonnet-4-5)

    Returns:
        Dict with answer, citations, and confidence
    """
    if not results:
        return {
            "answer": "I couldn't find any relevant items for your query.",
            "citations": [],
            "confidence": 0.0,
            "num_sources": 0
        }

    # Format results for context
    formatted_results = format_results_for_llm(results)

    # Create prompt
    prompt = f"""You are answering questions about a personal image collection.

User Question: {query}

Retrieved Items from Collection:
{formatted_results}

Provide a natural, conversational answer to the user's question based on the retrieved items above.

Guidelines:
- Be specific and cite details from the results
- Reference items using [Item X] notation when mentioning specific items
- If multiple items are relevant, summarize the key themes or patterns
- If the results don't fully answer the question, acknowledge the limitations
- Keep responses concise but informative (2-4 sentences for simple queries, more for complex)
- Focus on answering the specific question asked

Answer:"""

    # Use Claude Sonnet 4.5 by default (or specified model)
    resolved_model = model or "claude-sonnet-4-5"

    # Determine provider based on model name
    if resolved_model.startswith("gpt") or resolved_model.startswith("o1") or resolved_model.startswith("o3"):
        # Use OpenAI
        if resolved_model.startswith("gpt-5") or resolved_model.startswith("o1") or resolved_model.startswith("o3"):
            token_param = {"max_completion_tokens": 4000}
        else:
            token_param = {"max_tokens": 1024}

        response = openai_client.chat.completions.create(
            model=resolved_model,
            **token_param,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        answer = response.choices[0].message.content or ""
    else:
        # Use Anthropic (default)
        response = anthropic_client.messages.create(
            model=resolved_model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        answer = response.content[0].text

    # Extract citations
    citations = _extract_citations(answer, len(results))

    # Calculate confidence based on BM25 scores
    # Higher scores (less negative) indicate better matches
    avg_score = sum(abs(r.get('score', 0)) for r in results) / len(results) if results else 0
    # Normalize confidence to 0-1 range (BM25 scores are typically 0 to -10+)
    # Lower (more negative) scores are better, so we invert and normalize
    confidence = min(1.0, avg_score / 10.0) if avg_score > 0 else 0.5

    return {
        "answer": answer,
        "citations": citations,
        "confidence": confidence,
        "num_sources": len(results)
    }
