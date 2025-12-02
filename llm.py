import os
import base64
import json
from typing import Literal, Optional
from dotenv import load_dotenv

# Load environment variables before initializing clients
load_dotenv()

from anthropic import Anthropic
from openai import OpenAI
from langfuse import Langfuse, observe, get_client

# Initialize clients
langfuse = Langfuse()
anthropic_client = Anthropic()
openai_client = OpenAI()

# Default models for each provider
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o",
}

# Default provider
DEFAULT_PROVIDER = "anthropic"


def get_prompt(name: str) -> str:
    """Fetch prompt from Langfuse by name."""
    prompt = langfuse.get_prompt(name, label="latest")
    return prompt.compile()


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


def _analyze_with_anthropic(image_data: str, media_type: str, model: str, system_prompt: str) -> str:
    """Call Anthropic API for image analysis."""
    response = anthropic_client.messages.create(
        model=model,
        max_tokens=1024,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Analyze this image and categorize it for my collection."
                    }
                ],
            }
        ],
    )
    return response.content[0].text


def _analyze_with_openai(image_data: str, media_type: str, model: str, system_prompt: str) -> str:
    """Call OpenAI API for image analysis."""
    response = openai_client.chat.completions.create(
        model=model,
        max_tokens=1024,
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": [
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
                ],
            }
        ],
    )
    return response.choices[0].message.content


@observe(name="analyze_image")
def analyze_image(
    image_path: str,
    provider: Optional[str] = None,
    model: Optional[str] = None
) -> dict:
    """
    Analyze an image using AI vision via Langfuse tracing.

    Args:
        image_path: Path to the image file
        provider: Provider to use ("anthropic" or "openai"). Defaults to "anthropic".
        model: Model to use. Defaults to provider's default model.

    Returns:
        dict with the full LLM analysis response
    """
    # Resolve provider and model defaults
    resolved_provider = provider or DEFAULT_PROVIDER
    resolved_model = model or DEFAULT_MODELS[resolved_provider]

    # Load and encode image
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # Determine media type
    media_type = get_media_type(image_path)

    # Get prompt from Langfuse
    system_prompt = get_prompt("collections/image-analysis")

    # Call appropriate provider
    if resolved_provider == "openai":
        result_text = _analyze_with_openai(image_data, media_type, resolved_model, system_prompt)
    else:
        result_text = _analyze_with_anthropic(image_data, media_type, resolved_model, system_prompt)

    # Handle potential JSON wrapped in markdown code blocks
    if result_text.startswith("```"):
        # Remove markdown code block wrapper
        lines = result_text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        result_text = "\n".join(lines[1:-1])

    return json.loads(result_text)


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
    """Get the current Langfuse trace ID."""
    try:
        client = get_client()
        # In Langfuse 3.x, trace ID is available from the current observation context
        # This will return None if not in an observed context
        return None  # Trace ID capture requires more complex setup in v3
    except Exception:
        return None
