import os
import base64
import json
import logging
from typing import Literal, Optional

# Load environment variables (skip in Lambda - use environment variables directly)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not available (Lambda environment) - use system environment variables
    pass

from anthropic import Anthropic
from openai import OpenAI
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable, get_current_run_tree, Client as LangSmithClient

# Initialize legacy clients (kept for backward compatibility if needed)
anthropic_client = Anthropic()
openai_client = OpenAI()

# Setup logging
logger = logging.getLogger(__name__)

# Default models for each provider
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o",
}

# Default provider
DEFAULT_PROVIDER = "anthropic"


def get_prompt(name: str) -> str:
    """
    Get system prompt for image analysis from LangSmith Hub.

    Falls back to embedded prompt if LangSmith fetch fails.
    Prompt name is configured via LANGSMITH_PROMPT_NAME environment variable.

    Args:
        name: Prompt identifier (currently unused, uses env var)

    Returns:
        System prompt string
    """
    # Get prompt name from environment
    prompt_name = os.getenv("LANGSMITH_PROMPT_NAME", "collections-app-initial")

    # Try to fetch from LangSmith Hub
    try:
        client = LangSmithClient()
        prompt_template = client.pull_prompt(prompt_name)

        # PromptTemplate has a .template attribute with the prompt text
        if hasattr(prompt_template, 'template'):
            logger.info(f"Successfully loaded prompt '{prompt_name}' from LangSmith Hub")
            return prompt_template.template
        else:
            logger.warning(f"Prompt template missing 'template' attribute, using fallback")
            raise AttributeError("No template attribute")

    except Exception as e:
        logger.warning(f"Failed to fetch prompt from LangSmith Hub: {e}. Using fallback prompt.")

        # Fallback system prompt for image analysis
        return """You are an AI assistant that analyzes images from a personal photo collection.

Analyze the provided image and return a JSON object with the following structure:
{
  "category": "Primary category (e.g., Travel, Food, Beauty, etc.)",
  "subcategories": ["list", "of", "relevant", "subcategories"],
  "headline": "A brief, descriptive title for the image",
  "summary": "A concise 2-3 sentence description of what's in the image",
  "image_details": {
    "extracted_text": "Any visible text in the image",
    "objects": ["list", "of", "notable", "objects"],
    "themes": ["list", "of", "themes"],
    "emotions": ["list", "of", "emotions/vibes"],
    "vibes": ["overall", "vibe", "keywords"]
  }
}

Be specific and accurate. Focus on what's actually visible in the image."""


def get_media_type(image_path: str) -> str:
    """Determine media type from file extension."""
    lower_path = image_path.lower()
    if lower_path.endswith(".jpg") or lower_path.endswith(".jpeg"):
        return "image/jpeg"
    elif lower_path.endswith(".webp"):
        return "image/webp"
    elif lower_path.endswith(".gif"):
        return "image/gif"
    else:
        return "image/png"


def _analyze_with_anthropic(image_data: str, media_type: str, model: str, system_prompt: str, metadata: dict = None) -> str:
    """Call Anthropic API for image analysis using LangChain (tracks tokens/cost)."""
    # Log metadata if provided (for debugging)
    if metadata:
        logger.debug(f"Analyzing with Anthropic - metadata: {metadata}")

    # Use LangChain's ChatAnthropic for automatic token tracking
    llm = ChatAnthropic(model=model, max_tokens=1024)

    # Create messages with system prompt and image
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{image_data}"
                    }
                },
                {
                    "type": "text",
                    "text": "Analyze this image and categorize it for my collection."
                }
            ]
        )
    ]

    # Invoke and get response
    response = llm.invoke(messages)
    return response.content


def _analyze_with_openai(image_data: str, media_type: str, model: str, system_prompt: str, metadata: dict = None) -> str:
    """Call OpenAI API for image analysis using LangChain (tracks tokens/cost)."""
    # Log metadata if provided (for debugging)
    if metadata:
        logger.debug(f"Analyzing with OpenAI - metadata: {metadata}")

    # Use LangChain's ChatOpenAI for automatic token tracking
    # GPT-5, o1, o3 are reasoning models that use max_completion_tokens
    if model.startswith("gpt-5") or model.startswith("o1") or model.startswith("o3"):
        llm = ChatOpenAI(model=model, max_completion_tokens=8000)
    else:
        llm = ChatOpenAI(model=model, max_tokens=1024)

    # Create messages with system prompt and image
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{image_data}"
                    }
                },
                {
                    "type": "text",
                    "text": "Analyze this image and categorize it for my collection."
                }
            ]
        )
    ]

    # Invoke and get response
    response = llm.invoke(messages)
    return response.content


@traceable(name="analyze_image", run_type="chain")
def analyze_image(
    image_path: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    metadata: Optional[dict] = None
) -> tuple[dict, Optional[str]]:
    """
    Analyze an image using AI vision via LangSmith tracing.

    Args:
        image_path: Path to the image file
        provider: Provider to use ("anthropic" or "openai"). Defaults to "anthropic".
        model: Model to use. Defaults to provider's default model.
        metadata: Additional metadata for tracing

    Returns:
        Tuple of (analysis result dict, trace_id)
    """
    # Resolve provider and model defaults
    resolved_provider = provider or DEFAULT_PROVIDER
    resolved_model = model or DEFAULT_MODELS[resolved_provider]

    # Load and encode image
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # Determine media type
    media_type = get_media_type(image_path)

    # Get prompt from LangSmith Hub
    system_prompt = get_prompt("collections/image-analysis")

    # Call appropriate provider
    # Note: We keep direct API calls to ensure no regression in image handling
    # The @traceable decorator ensures full tracing in LangSmith
    if resolved_provider == "openai":
        result_text = _analyze_with_openai(image_data, media_type, resolved_model, system_prompt, metadata)
    else:
        result_text = _analyze_with_anthropic(image_data, media_type, resolved_model, system_prompt, metadata)

    # Handle potential JSON wrapped in markdown code blocks
    if result_text and result_text.startswith("```"):
        # Remove markdown code block wrapper
        lines = result_text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        result_text = "\n".join(lines[1:-1])

    # Capture trace ID from within the traced context
    trace_id = None
    try:
        run_tree = get_current_run_tree()
        trace_id = str(run_tree.id) if run_tree else None
    except Exception as e:
        logger.debug(f"Could not get trace ID within analyze_image: {e}")

    return json.loads(result_text), trace_id


def get_resolved_provider_and_model(
    provider: Optional[str] = None,
    model: Optional[str] = None
) -> tuple[str, str]:
    """
    Resolve provider and model to their actual values.

    Returns:
        Tuple of (resolved_provider, resolved_model)
    """
    resolved_provider = provider or DEFAULT_PROVIDER
    resolved_model = model or DEFAULT_MODELS[resolved_provider]
    return resolved_provider, resolved_model


def get_trace_id() -> str | None:
    """Get the current LangSmith trace/run ID."""
    try:
        run_tree = get_current_run_tree()
        return str(run_tree.id) if run_tree else None
    except Exception as e:
        logger.debug(f"Could not get trace ID: {e}")
        return None
