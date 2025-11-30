from dotenv import load_dotenv
from langfuse import Langfuse

# Load environment variables from .env file
load_dotenv()

# Initialize Langfuse client (uses LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_HOST from env)
langfuse = Langfuse()

# Get prompt by label
prompt = langfuse.get_prompt("collections/image-analysis", label="latest")

print(prompt.compile())
