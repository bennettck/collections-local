import os
import base64
import json
from dotenv import load_dotenv

# Load environment variables before initializing clients
load_dotenv()

from anthropic import Anthropic
from langfuse import Langfuse, observe, get_client

# Initialize clients
langfuse = Langfuse()
anthropic = Anthropic()


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


@observe(name="analyze_image")
def analyze_image(image_path: str, model: str = "claude-sonnet-4-20250514") -> dict:
    """
    Analyze an image using Claude vision via Langfuse tracing.

    Args:
        image_path: Path to the image file
        model: Anthropic model to use

    Returns:
        dict with the full LLM analysis response
    """
    # Load and encode image
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # Determine media type
    media_type = get_media_type(image_path)

    # Get prompt from Langfuse
    system_prompt = get_prompt("collections/image-analysis")

    # Call Anthropic
    response = anthropic.messages.create(
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

    # Parse response
    result_text = response.content[0].text

    # Handle potential JSON wrapped in markdown code blocks
    if result_text.startswith("```"):
        # Remove markdown code block wrapper
        lines = result_text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        result_text = "\n".join(lines[1:-1])

    return json.loads(result_text)


def get_trace_id() -> str | None:
    """Get the current Langfuse trace ID."""
    try:
        client = get_client()
        # In Langfuse 3.x, trace ID is available from the current observation context
        # This will return None if not in an observed context
        return None  # Trace ID capture requires more complex setup in v3
    except Exception:
        return None
