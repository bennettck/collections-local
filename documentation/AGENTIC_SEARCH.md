# Agentic Search - Comprehensive Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Configuration](#configuration)
4. [Prompt Engineering](#prompt-engineering)
5. [Debugging](#debugging)
6. [Best Practices](#best-practices)
7. [Common Patterns](#common-patterns)
8. [Performance Tuning](#performance-tuning)
9. [Troubleshooting](#troubleshooting)
10. [Examples](#examples)

---

## Overview

### What is Agentic Search?

Agentic search is an advanced retrieval system that uses Large Language Model (LLM) agents to intelligently search and refine queries. Unlike traditional "single-shot" retrieval methods (BM25, Vector, or Hybrid search), agentic search employs an autonomous agent that can:

- **Reason about queries**: Understand user intent and extract key concepts
- **Iteratively refine**: Adjust search strategies based on result quality
- **Orchestrate tools**: Call search functions multiple times with different parameters
- **Explain decisions**: Provide transparent reasoning about search choices

**Key Insight:** The agent acts as an intelligent search assistant that doesn't just execute a query—it thinks about the best way to find what you're looking for.

### When to Use Agentic Search

**Use agentic search when:**

- Queries are complex with multiple parts ("Find affordable Japanese perfumes OR beauty products")
- User intent is ambiguous ("luxury items" could mean many categories)
- Results may need refinement (broad query like "perfume" needs narrowing)
- Comparative analysis is needed ("Compare Tokyo vs Kyoto restaurants")
- Exploratory search is desired ("What interesting food items do I have?")
- You want transparency in how results were found

**Don't use agentic search when:**

- Query is simple and specific ("Tokyo Tower")
- Speed is critical (<100ms requirement)
- High-volume batch processing
- Exact keyword match is needed
- Cost sensitivity (uses 2-5 LLM calls per query)

### Core Concepts

**ReAct Pattern (Reasoning + Acting)**

Agentic search uses the ReAct pattern where the agent alternates between:

1. **Thought**: Reasoning about the current state
2. **Action**: Calling a tool (search)
3. **Observation**: Examining tool results
4. **Repeat or Answer**: Continue refining or provide final answer

**Example Flow:**

```
User Query: "Find affordable perfumes from Japan"

Iteration 1:
  Thought: "I need to search for perfumes that are both affordable and Japanese"
  Action: search_collections(query="affordable Japanese perfume", top_k=10)
  Observation: "Found 3 items, all J-Scent perfumes priced around ¥5000"

Iteration 2:
  Thought: "Results are good, ¥5000 (~$33) is affordable for niche perfumes"
  Final Answer: "I found J-Scent perfumes [Item 1] at ¥4,950..."
```

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Endpoint                      │
│              POST /search (search_type="agentic")        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                  Agent Executor                          │
│        • Manages agent lifecycle                         │
│        • Controls iteration limits                       │
│        • Tracks intermediate steps                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              LangChain ReAct Agent                       │
│        Claude Sonnet 4.5 (Temperature=0.0)               │
│        • Analyzes user query                             │
│        • Plans search strategy                           │
│        • Evaluates results                               │
│        • Decides to refine or answer                     │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Search Collections Tool                     │
│        Wrapper around Hybrid-LC Search                   │
│        • Accepts: query, top_k, category_filter          │
│        • Returns: structured results with metadata       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│           Hybrid Search (BM25 + Vector)                  │
│        Reciprocal Rank Fusion                            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Search Results                              │
│        • Items with scores                               │
│        • Metadata and summaries                          │
│        • Category information                            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│          Agent Response Synthesis                        │
│        • Final answer with citations                     │
│        • Agent reasoning explanation                     │
│        • Tools used log                                  │
└─────────────────────────────────────────────────────────┘
```

### Code Architecture

**File Structure:**

```
/workspaces/collections-local/
├── config/
│   └── agent_config.py          # Agent configuration
├── retrieval/
│   ├── langchain_retrievers.py  # Hybrid search implementation
│   └── agentic_search.py        # Agentic search implementation
├── main.py                       # API endpoint handlers
└── documentation/
    └── AGENTIC_SEARCH.md        # This file
```

**Key Classes:**

1. **AgentExecutor** (LangChain)
   - Manages agent execution lifecycle
   - Controls iteration limits (max 5)
   - Tracks intermediate steps for debugging
   - Handles early stopping

2. **ReAct Agent** (LangChain)
   - Implements Thought → Action → Observation loop
   - Uses Claude Sonnet 4.5 for reasoning
   - Follows system prompt instructions
   - Generates final answers with citations

3. **Search Tool** (Custom)
   - Wraps hybrid search functionality
   - Formats results for agent consumption
   - Handles errors gracefully
   - Tracks search parameters

### Data Flow

**Request → Response Flow:**

```python
# 1. API receives request
POST /search {
  "query": "Find affordable Japanese perfumes",
  "search_type": "agentic",
  "top_k": 10
}

# 2. Agent Executor initialized
agent_executor = AgentExecutor(
    agent=react_agent,
    tools=[search_tool],
    max_iterations=5,
    return_intermediate_steps=True
)

# 3. Agent reasoning begins
result = agent_executor.invoke({
    "input": "Find affordable Japanese perfumes"
})

# 4. Agent uses search tool
tool_result = search_collections(
    query="affordable Japanese perfume",
    top_k=10
)

# 5. Agent evaluates results
# (Good results → Final answer)
# (Poor results → Refine query → Search again)

# 6. Response returned
{
  "query": "Find affordable Japanese perfumes",
  "search_type": "agentic",
  "results": [...],
  "answer": "I found J-Scent...",
  "agent_reasoning": "I interpreted 'affordable'...",
  "tools_used": [
    {
      "tool": "search_collections",
      "query": "affordable Japanese perfume",
      "results_count": 5
    }
  ]
}
```

---

## Configuration

### Agent Configuration File

**Location:** `/workspaces/collections-local/config/agent_config.py`

```python
"""Configuration for agentic search with LangChain agents."""

# Agent model configuration
AGENT_MODEL = "claude-sonnet-4-5"
AGENT_TEMPERATURE = 0.0  # Deterministic for consistent search behavior
AGENT_MAX_TOKENS = 2048

# Agent behavior configuration
AGENT_MAX_ITERATIONS = 5  # Maximum number of tool calls before stopping
AGENT_EARLY_STOPPING_METHOD = "generate"  # Return final answer on max iterations

# System message for the agent
AGENT_SYSTEM_MESSAGE = """You are a specialized search assistant helping users find items in their personal image collection.

Your task is to:
1. Understand the user's search intent
2. Use the search_collections tool to find relevant items
3. Analyze the results to determine if they answer the user's query
4. If results are insufficient, try refining your search approach (different keywords, broader/narrower terms)

Guidelines:
- Focus on the user's actual intent, not just literal keywords
- Consider semantic meaning and context
- If initial results are poor, explain what you're adjusting and try again
- Provide a clear, concise summary of findings
- Be honest if results don't fully match the query

You have access to a hybrid search tool that combines keyword matching and semantic search.
"""

# Tool configuration
SEARCH_TOOL_NAME = "search_collections"
SEARCH_TOOL_DESCRIPTION = """Search the personal image collection using hybrid search (BM25 + vector similarity).

Args:
    query: The search query string
    top_k: Number of results to return (default: 10)
    category_filter: Optional category to filter by (e.g., 'Food', 'Travel', 'Beauty')

Returns:
    List of relevant items with their metadata, scores, and descriptions.
"""

# Agent prompt configuration
AGENT_PROMPT_TEMPLATE = """You are a helpful search assistant for a personal image collection.

Current user query: {input}

Use the search_collections tool to find relevant items. You can call it multiple times with different queries if needed to get better results.

{agent_scratchpad}"""
```

### Configuration Parameters Explained

#### AGENT_MODEL

**Purpose:** Specifies which LLM to use for agent reasoning.

**Options:**
- `"claude-sonnet-4-5"` (default, recommended)
- `"claude-opus-4"` (more capable but slower)
- `"gpt-4o"` (OpenAI alternative)

**Considerations:**
- Claude Sonnet 4.5: Best balance of speed, quality, and cost
- Claude Opus 4: Use for very complex queries requiring deep reasoning
- GPT-4o: Comparable performance, different reasoning style

#### AGENT_TEMPERATURE

**Purpose:** Controls randomness in agent responses.

**Value:** `0.0` (deterministic)

**Why 0.0?**
- Search should be consistent and reproducible
- Users expect same query → same results
- Debugging is easier with deterministic behavior
- No need for creative responses in search

**When to increase:**
- Never for production search
- Could use 0.3-0.5 for exploratory experiments

#### AGENT_MAX_ITERATIONS

**Purpose:** Limits how many times the agent can call tools.

**Value:** `5` iterations

**Iteration Budget:**
- Iteration 1: Initial search
- Iterations 2-4: Refinements if needed
- Iteration 5: Emergency fallback / final answer

**Why limit iterations?**
- Prevents infinite loops
- Controls latency (each iteration ~1-2 seconds)
- Manages API costs
- Forces agent to be efficient

**When to adjust:**
- Increase to 7-10 for very complex queries
- Decrease to 3 for faster responses
- Monitor via `tools_used` field to see if limit is hit

#### AGENT_EARLY_STOPPING_METHOD

**Purpose:** Defines behavior when max iterations is reached.

**Value:** `"generate"` (generate final answer with available data)

**Options:**
- `"generate"`: Best answer possible with current results
- `"force"`: Stop immediately, may not return answer

**Why "generate"?**
- Ensures user always gets a response
- Agent acknowledges limitations in answer
- Better UX than error message

---

## Prompt Engineering

### Agent System Message

The system message defines the agent's role and behavior. It's critical for:
- Setting the agent's purpose and constraints
- Guiding reasoning and tool use
- Ensuring helpful, accurate responses

**Current System Message:**

```
You are a specialized search assistant helping users find items in their personal image collection.

Your task is to:
1. Understand the user's search intent
2. Use the search_collections tool to find relevant items
3. Analyze the results to determine if they answer the user's query
4. If results are insufficient, try refining your search approach (different keywords, broader/narrower terms)

Guidelines:
- Focus on the user's actual intent, not just literal keywords
- Consider semantic meaning and context
- If initial results are poor, explain what you're adjusting and try again
- Provide a clear, concise summary of findings
- Be honest if results don't fully match the query

You have access to a hybrid search tool that combines keyword matching and semantic search.
```

### Prompt Design Principles

**1. Clear Role Definition**

✅ Good: "You are a specialized search assistant helping users find items in their personal image collection."

❌ Bad: "You are a helpful AI assistant."

**Why:** Specific role focuses agent behavior on search tasks.

**2. Explicit Task Breakdown**

✅ Good: "Your task is to: 1. Understand... 2. Use the tool... 3. Analyze... 4. Refine if needed"

❌ Bad: "Help the user find what they're looking for."

**Why:** Step-by-step tasks guide agent reasoning process.

**3. Behavioral Guidelines**

✅ Good: "Focus on the user's actual intent, not just literal keywords"

❌ Bad: "Search for what the user says"

**Why:** Guidelines shape agent decision-making and refinement strategies.

**4. Transparency Expectations**

✅ Good: "If initial results are poor, explain what you're adjusting and try again"

❌ Bad: "Keep searching until you find results"

**Why:** Encourages agent to explain reasoning, building user trust.

**5. Honesty and Limitations**

✅ Good: "Be honest if results don't fully match the query"

❌ Bad: "Always provide a confident answer"

**Why:** Better to acknowledge gaps than hallucinate or mislead.

### Tool Description

The tool description tells the agent what the `search_collections` tool does and how to use it.

**Current Tool Description:**

```
Search the personal image collection using hybrid search (BM25 + vector similarity).

Args:
    query: The search query string
    top_k: Number of results to return (default: 10)
    category_filter: Optional category to filter by (e.g., 'Food', 'Travel', 'Beauty')

Returns:
    List of relevant items with their metadata, scores, and descriptions.
```

**Best Practices:**

1. **Clear functionality**: "Search the personal image collection using hybrid search"
2. **Parameter details**: List all args with types and defaults
3. **Examples**: Show example values (e.g., 'Food', 'Travel', 'Beauty')
4. **Return format**: Describe what the tool returns

### Prompt Template

The prompt template structures each agent invocation.

**Current Template:**

```python
AGENT_PROMPT_TEMPLATE = """You are a helpful search assistant for a personal image collection.

Current user query: {input}

Use the search_collections tool to find relevant items. You can call it multiple times with different queries if needed to get better results.

{agent_scratchpad}"""
```

**Template Variables:**

- `{input}`: The user's query (injected at runtime)
- `{agent_scratchpad}`: Agent's running thoughts and observations (managed by LangChain)

**Why This Structure:**

1. Reiterates role for context
2. Shows the current query being processed
3. Explicitly permits multiple tool calls ("call it multiple times")
4. Reserves space for agent's reasoning (`agent_scratchpad`)

### Customizing Prompts

**Example: Domain-Specific Prompt**

If you only want to search beauty products:

```python
AGENT_SYSTEM_MESSAGE = """You are a beauty product search specialist.

Your task is to help users find beauty, skincare, and cosmetic items in their collection.

When searching:
- Always use category_filter="Beauty" unless user specifies otherwise
- Pay special attention to product names, brands, and price mentions
- Identify if user wants makeup, skincare, fragrance, or haircare
- If results span multiple beauty categories, organize answer by category

Be specific about product details like brands, prices, and descriptions when available.
"""
```

**Example: Research-Focused Prompt**

For analytical queries:

```python
AGENT_SYSTEM_MESSAGE = """You are a research assistant analyzing a personal image collection.

Your task is to help users discover patterns, trends, and insights in their saved images.

When searching:
- Look for thematic connections across results
- Identify recurring locations, brands, or topics
- Suggest related queries the user might find interesting
- Provide analytical summaries, not just lists

Always explain the "why" behind your search strategy.
"""
```

---

## Debugging

### Observability Tools

Agentic search provides rich debugging information through multiple channels.

#### 1. Response Fields

**agent_reasoning** (string)

Contains the agent's explanation of its search strategy.

**Example:**

```json
"agent_reasoning": "I interpreted 'affordable' as budget-conscious pricing and 'Japanese beauty products' with emphasis on 'perfumes'. Initial search for 'affordable Japanese perfume' returned excellent matches. The J-Scent items clearly met all criteria (Japanese brand, perfume category, explicit pricing indicating affordability at ¥4,950). No refinement needed as results directly answered the query with high confidence."
```

**What to Look For:**
- Did the agent understand the query correctly?
- What assumptions did it make?
- Why did it choose this search strategy?
- Did it refine or stick with initial search?

**tools_used** (array)

Lists every tool call made by the agent.

**Example:**

```json
"tools_used": [
  {
    "tool": "search_collections",
    "query": "affordable Japanese perfume beauty products",
    "top_k": 10,
    "category_filter": null,
    "results_count": 5
  }
]
```

**What to Look For:**
- How many searches did the agent perform?
- What queries did it try?
- Did it adjust parameters (top_k, category_filter)?
- How many results did each search return?

**Multiple Iterations Example:**

```json
"tools_used": [
  {
    "tool": "search_collections",
    "query": "luxury France",
    "results_count": 2
  },
  {
    "tool": "search_collections",
    "query": "French luxury perfume fashion beauty",
    "results_count": 5
  }
]
```

This shows the agent:
1. Tried broad query "luxury France" → Only 2 results
2. Refined to specific categories "French luxury perfume fashion beauty" → 5 results

#### 2. LangSmith Tracing

**What is LangSmith?**

LangSmith is LangChain's observability platform for debugging agent applications.

**Setup:**

```bash
# Set environment variables
export LANGCHAIN_TRACING_V2="true"
export LANGCHAIN_API_KEY="your-langsmith-api-key"
export LANGCHAIN_PROJECT="collections-local-agentic-search"
```

**What LangSmith Shows:**

1. **Complete execution trace**
   - Every LLM call with input/output
   - Tool calls with arguments and results
   - Timing for each step
   - Token usage per LLM call

2. **Agent reasoning steps**
   - Thought process (internal monologue)
   - Action decisions
   - Observations from tools
   - Final answer generation

3. **Performance metrics**
   - Total execution time
   - LLM latency per call
   - Token usage and costs
   - Success/failure rates

**Accessing Traces:**

1. Go to https://smith.langchain.com
2. Select your project (e.g., "collections-local-agentic-search")
3. View recent traces
4. Click on a trace to see detailed execution flow

**Example Trace View:**

```
Run: agentic_search
├─ LLM Call 1: Query Understanding
│  ├─ Input: "Find affordable Japanese perfumes"
│  ├─ Output: Thought: "I should search for perfumes that are affordable and Japanese..."
│  └─ Tokens: 456 (input: 234, output: 222)
│
├─ Tool Call 1: search_collections
│  ├─ Args: {"query": "affordable Japanese perfume", "top_k": 10}
│  ├─ Result: 5 items found
│  └─ Duration: 125ms
│
├─ LLM Call 2: Result Evaluation
│  ├─ Input: "I found 5 items... Should I refine?"
│  ├─ Output: Final Answer: "I found J-Scent perfumes..."
│  └─ Tokens: 678 (input: 445, output: 233)
│
└─ Total Duration: 3241ms
```

#### 3. Server Logs

**Verbose Mode:**

Enable verbose logging in agent executor:

```python
agent_executor = AgentExecutor(
    agent=agent,
    tools=[search_tool],
    verbose=True  # Prints reasoning to console
)
```

**Log Output Example:**

```
> Entering new AgentExecutor chain...

Thought: I need to search for affordable Japanese perfumes in the collection. I'll use the search_collections tool with a query that captures both "affordable" and "Japanese perfume".

Action: search_collections
Action Input: {"query": "affordable Japanese perfume", "top_k": 10}

Observation: Found 5 items:
1. J-Scent fragrance (¥4,950) - Beauty category
2. J-Scent Hisui (¥4,950) - Beauty category
...

Thought: These results are excellent. All items are Japanese perfumes with explicit pricing around ¥5000, which is affordable for niche fragrances. I have enough information to provide a comprehensive answer.

Final Answer: I found several affordable Japanese beauty products...

> Finished chain.
```

### Debugging Scenarios

#### Scenario 1: Agent Doesn't Refine Poor Results

**Problem:** Initial search returns weak results, but agent doesn't try a second search.

**Debug Steps:**

1. Check `tools_used` count
   - Expected: 2+ searches
   - Actual: 1 search

2. Review `agent_reasoning`
   - Look for evaluation of result quality
   - Check if agent considered refinement

3. Review LangSmith trace
   - Did agent recognize results were poor?
   - What was the thought before final answer?

**Possible Causes:**

- System prompt doesn't emphasize refinement
- Agent is too easily satisfied
- Max iterations set too low
- Temperature too low (agent too conservative)

**Solution:**

Update system message to be more demanding:

```python
AGENT_SYSTEM_MESSAGE = """...
Guidelines:
- **Be critical of initial results.** If fewer than 3 high-quality matches, try refining your query.
- Try different keyword combinations, synonyms, or broader/narrower terms.
- Explain what you're adjusting and why in your reasoning.
..."""
```

#### Scenario 2: Agent Hits Max Iterations

**Problem:** Agent keeps searching and hits the 5-iteration limit without a good answer.

**Debug Steps:**

1. Check `tools_used` length
   - If length = 5, max iterations was hit

2. Review search queries tried
   - Are they getting more specific?
   - Are they wildly different?
   - Are they repetitive?

3. Check LangSmith trace
   - What was the agent's thought process?
   - Did results improve over iterations?

**Possible Causes:**

- Query is genuinely difficult (no good matches exist)
- Agent is stuck in a refinement loop
- Search tool isn't returning useful results
- Agent doesn't know when to stop

**Solution:**

Add early stopping logic to system prompt:

```python
AGENT_SYSTEM_MESSAGE = """...
Guidelines:
- Maximum 2-3 search refinements. If results don't improve, provide best available answer.
- If no relevant items exist, acknowledge this instead of endless searching.
..."""
```

Or increase max iterations:

```python
AGENT_MAX_ITERATIONS = 7  # Allow more attempts for complex queries
```

#### Scenario 3: Unexpected Query Interpretation

**Problem:** Agent interprets query differently than expected.

**Example:**
- User query: "cheap perfume"
- Agent searches: "budget-friendly fragrance"

**Debug Steps:**

1. Review `agent_reasoning`
   - What did agent think "cheap" meant?
   - Why did it choose "budget-friendly fragrance"?

2. Check `tools_used[0].query`
   - What was the actual search query?

**Possible Causes:**

- Agent is paraphrasing too much
- Agent prefers certain terminology
- System prompt encourages synonym usage

**Solution:**

If literal interpretation is important:

```python
AGENT_SYSTEM_MESSAGE = """...
Guidelines:
- Preserve user's exact keywords in your search queries when possible
- Only use synonyms if initial search with exact terms fails
..."""
```

If agent interpretation is fine:

No action needed. This is actually a feature—agent semantic understanding can improve results.

#### Scenario 4: Slow Response Time

**Problem:** Agentic search takes >10 seconds.

**Debug Steps:**

1. Check `answer_time_ms` and `retrieval_time_ms`
   - Are they both high?
   - Is answer time the bottleneck?

2. Check `tools_used` count
   - How many searches were performed?
   - More searches = more time

3. Review LangSmith trace
   - Which LLM calls took longest?
   - Is there a specific slow step?

**Possible Causes:**

- Too many iterations (4-5 searches)
- Large `top_k` values (more data to process)
- LLM API latency spikes
- Complex reasoning requiring long LLM responses

**Solutions:**

Reduce max iterations:

```python
AGENT_MAX_ITERATIONS = 3  # Faster but less refinement
```

Encourage faster decisions in prompt:

```python
AGENT_SYSTEM_MESSAGE = """...
Guidelines:
- Prefer a good answer quickly over a perfect answer slowly
- Maximum 1-2 search refinements for most queries
..."""
```

Use faster model (trade-off quality):

```python
AGENT_MODEL = "claude-sonnet-4"  # Slightly faster than 4.5
```

---

## Best Practices

### 1. Start Simple, Add Complexity

**Don't:** Begin with complex multi-step reasoning prompts.

**Do:** Start with basic system message and iterate based on real usage.

```python
# Start here
AGENT_SYSTEM_MESSAGE = """You are a search assistant.
Use search_collections to find items.
Refine if results are poor."""

# Evolve to this after testing
AGENT_SYSTEM_MESSAGE = """You are a search assistant...
[Detailed guidelines based on observed agent behavior]"""
```

### 2. Monitor Agent Behavior

**Track metrics:**

- Average iterations per query
- Success rate (did agent find relevant results?)
- Query interpretation accuracy
- Response time (p50, p95, p99)

**Log analysis:**

```python
# Pseudo-code for logging
def log_agentic_search(query, response):
    log_entry = {
        "query": query,
        "iterations": len(response["tools_used"]),
        "success": response["total_results"] > 0,
        "time_ms": response["answer_time_ms"],
        "reasoning": response["agent_reasoning"]
    }
    save_to_analytics(log_entry)
```

**Review patterns:**

- Which queries require the most iterations?
- Where does the agent struggle?
- Are there common misinterpretations?

### 3. Test Edge Cases

**Empty Results:**

```bash
curl -X POST http://localhost:8000/search \
  -d '{"query": "flying cars", "search_type": "agentic"}'
```

Expected: Agent should acknowledge no results exist and explain search attempts.

**Ambiguous Queries:**

```bash
curl -X POST http://localhost:8000/search \
  -d '{"query": "Tokyo", "search_type": "agentic"}'
```

Expected: Agent should recognize ambiguity (food? travel? beauty from Tokyo?) and perhaps search multiple categories.

**Comparative Queries:**

```bash
curl -X POST http://localhost:8000/search \
  -d '{"query": "Compare Tokyo and Kyoto restaurants", "search_type": "agentic"}'
```

Expected: Agent should perform two searches (Tokyo restaurants, Kyoto restaurants) and synthesize comparison.

**Long, Complex Queries:**

```bash
curl -X POST http://localhost:8000/search \
  -d '{"query": "Find affordable Japanese beauty products, especially perfumes or skincare, but not makeup", "search_type": "agentic"}'
```

Expected: Agent should parse multiple constraints and refine search accordingly.

### 4. Prompt Iteration Process

**Establish baseline:**

1. Start with minimal system message
2. Run 20-30 test queries
3. Record agent behavior (reasoning, iterations, results)

**Identify gaps:**

- Where does agent fail?
- What misinterpretations occur?
- Are refinements helpful or harmful?

**Update prompt:**

- Add specific guidelines for observed gaps
- Test same queries again
- Measure improvement

**Example Iteration:**

**Before:**

```
System: "You are a search assistant. Find items matching the query."
```

**Observed Problem:** Agent doesn't refine poor results.

**After:**

```
System: "You are a search assistant. If initial results are weak (<3 items or low relevance), try refining with synonyms or broader/narrower terms."
```

**Result:** Agent now refines more often.

### 5. Balance Speed vs Quality

**Fast Mode (1-2 iterations):**

```python
AGENT_MAX_ITERATIONS = 2
AGENT_SYSTEM_MESSAGE = """...Be decisive. Prefer a good answer quickly over a perfect answer slowly..."""
```

**Quality Mode (5-7 iterations):**

```python
AGENT_MAX_ITERATIONS = 7
AGENT_SYSTEM_MESSAGE = """...Be thorough. Explore multiple search strategies to find the best results..."""
```

**Adaptive Mode:**

Use query complexity to decide:

```python
def get_agent_config(query):
    if len(query.split()) <= 3:
        # Simple query: fast mode
        return {"max_iterations": 2}
    elif "compare" in query.lower() or "or" in query:
        # Complex query: quality mode
        return {"max_iterations": 7}
    else:
        # Default: balanced
        return {"max_iterations": 5}
```

### 6. Handle Costs

Agentic search uses 2-5 LLM API calls per query.

**Cost Tracking:**

```python
# Track tokens used
def calculate_cost(tokens_used, model="claude-sonnet-4-5"):
    # Claude Sonnet 4.5 pricing (example)
    input_cost_per_1k = 0.003
    output_cost_per_1k = 0.015

    total_cost = (
        (tokens_used["input"] / 1000) * input_cost_per_1k +
        (tokens_used["output"] / 1000) * output_cost_per_1k
    )
    return total_cost
```

**Cost Optimization:**

- Use temperature=0.0 (no wasted tokens on randomness)
- Set max_tokens=2048 (prevent runaway generation)
- Limit max_iterations=5 (cap total LLM calls)
- Consider caching for repeated queries

### 7. Combine with Other Search Types

Don't use agentic search for everything.

**Decision Tree:**

```
Is query complex, ambiguous, or exploratory?
├─ NO → Use Hybrid-LC (fast, good enough)
└─ YES → Is latency critical?
           ├─ YES → Use Hybrid-LC (sacrifice quality for speed)
           └─ NO → Use Agentic (best quality, slower)
```

**Example Routing Logic:**

```python
def route_search(query, user_preferences):
    # Check for complexity indicators
    complexity_markers = ["compare", "or", "and", "find", "best"]
    is_complex = any(marker in query.lower() for marker in complexity_markers)

    # Check query length (long queries are often complex)
    is_long = len(query.split()) > 10

    # Check user preferences
    wants_speed = user_preferences.get("speed_priority", False)

    if wants_speed:
        return "hybrid-lc"
    elif is_complex or is_long:
        return "agentic"
    else:
        return "hybrid-lc"
```

---

## Common Patterns

### Pattern 1: Query Refinement

**Scenario:** Initial query is too broad, agent narrows it down.

**Example:**

```
User Query: "perfume"

Agent Thought: "Too broad. Let me check what perfume-related items exist."

Search 1: "perfume" → 15 results across Beauty, Travel, Fashion

Agent Thought: "Results span multiple categories. Most are in Beauty. Let me focus there."

Search 2: "perfume", category_filter="Beauty" → 8 high-quality results

Final Answer: "I found 8 perfume items in your Beauty collection, including J-Scent..."
```

**When to Use:**

- User provides single-word or vague queries
- Initial results are numerous but unfocused
- You want agent to find the most relevant subset

**Prompt Guidance:**

```python
AGENT_SYSTEM_MESSAGE = """...
If initial search returns many results (>10) across different categories:
- Identify the dominant category
- Refine search with category filter
- Provide focused results from most relevant category
..."""
```

### Pattern 2: Multi-Category Exploration

**Scenario:** Query could apply to multiple categories, agent searches each.

**Example:**

```
User Query: "luxury items"

Agent Thought: "Luxury could mean Beauty, Fashion, or Travel. Let me explore."

Search 1: "luxury", category_filter="Beauty" → 3 results (perfumes)
Search 2: "luxury", category_filter="Fashion" → 2 results (clothing)
Search 3: "luxury", category_filter="Travel" → 4 results (hotels)

Final Answer: "I found luxury items across three categories:
- Beauty: J-Scent and Chanel perfumes [Items 1, 2, 3]
- Fashion: Designer clothing [Items 4, 5]
- Travel: High-end hotels in Tokyo [Items 6-9]"
```

**When to Use:**

- Queries with broad concepts (luxury, affordable, Japanese, etc.)
- User wants comprehensive view across categories
- Exploratory search

**Prompt Guidance:**

```python
AGENT_SYSTEM_MESSAGE = """...
If a query could apply to multiple categories:
- Search each relevant category separately
- Present results grouped by category
- Highlight which category has the most results
..."""
```

### Pattern 3: Synonym Expansion

**Scenario:** Exact keywords don't match, agent tries synonyms.

**Example:**

```
User Query: "cheap perfume"

Agent Thought: "'Cheap' might not appear in descriptions. Try 'affordable' or 'budget'."

Search 1: "cheap perfume" → 0 results

Agent Thought: "No exact matches. Let me try 'affordable perfume'."

Search 2: "affordable perfume" → 5 results

Final Answer: "I didn't find items with 'cheap' but found 5 affordable perfumes..."
```

**When to Use:**

- Keyword-based searches fail
- User uses informal language
- You want robust semantic matching

**Prompt Guidance:**

```python
AGENT_SYSTEM_MESSAGE = """...
If a search returns no results:
- Try synonyms or related terms
- Examples: "cheap" → "affordable", "budget-friendly"
- Explain in your reasoning what synonym you tried and why
..."""
```

### Pattern 4: Comparative Analysis

**Scenario:** User wants to compare two entities.

**Example:**

```
User Query: "Compare Tokyo and Kyoto restaurants"

Agent Thought: "I need to search for Tokyo restaurants and Kyoto restaurants separately, then compare."

Search 1: "Tokyo restaurants", category_filter="Food" → 5 results
Search 2: "Kyoto restaurants", category_filter="Food" → 3 results

Final Answer: "Here's a comparison of restaurants in your collection:

**Tokyo (5 items):**
- Mix of traditional and modern
- Higher price points
- Tofuya Ukai, [others]...

**Kyoto (3 items):**
- Primarily traditional kaiseki
- More affordable
- [Items...]

Tokyo has more variety while Kyoto focuses on traditional dining."
```

**When to Use:**

- Explicit comparison requests ("compare X and Y")
- User wants to see differences/similarities
- Analytical queries

**Prompt Guidance:**

```python
AGENT_SYSTEM_MESSAGE = """...
For comparison queries ("compare X and Y"):
- Search for X and Y separately
- Present results side-by-side
- Highlight key differences and similarities
- Provide a brief comparative summary
..."""
```

### Pattern 5: Negative Filtering

**Scenario:** User specifies what they DON'T want.

**Example:**

```
User Query: "Japanese beauty products but not makeup"

Agent Thought: "Search for Japanese beauty products, then filter out makeup items."

Search 1: "Japanese beauty products" → 10 results

Agent Evaluation: "Results include makeup (5 items), perfume (3), skincare (2). User wants perfume and skincare only."

Final Answer: "I found 5 Japanese beauty products excluding makeup:
- 3 perfumes: J-Scent...
- 2 skincare items: ..."
```

**When to Use:**

- Queries with "but not", "except", "without"
- User wants to exclude specific types
- Refinement of search scope

**Current Limitation:** Agent must filter results post-search (no native exclusion in search tool).

**Prompt Guidance:**

```python
AGENT_SYSTEM_MESSAGE = """...
For queries with exclusions ("but not X", "except X"):
- Search for the main topic first
- Manually filter out excluded items from results
- Explain in your answer what was excluded and why
..."""
```

---

## Performance Tuning

### Latency Optimization

**Problem:** Agentic search takes 8-10 seconds.

**Optimization Strategies:**

**1. Reduce Max Iterations**

```python
AGENT_MAX_ITERATIONS = 3  # Down from 5

# Impact:
# - Faster: ~4-6 seconds instead of 8-10
# - Trade-off: Less refinement opportunity
```

**2. Optimize System Prompt**

Encourage faster decisions:

```python
AGENT_SYSTEM_MESSAGE = """...
Be decisive:
- Aim for 1-2 searches maximum
- Provide a good answer quickly rather than a perfect answer slowly
- Only refine if initial results are very poor (<2 items)
..."""
```

**3. Reduce max_tokens**

```python
AGENT_MAX_TOKENS = 1024  # Down from 2048

# Impact:
# - Slightly faster LLM responses
# - Trade-off: Shorter agent reasoning, may truncate long answers
```

**4. Parallel Tool Calls (Future Enhancement)**

Allow agent to call multiple searches in parallel:

```python
# Not yet supported in LangChain, but conceptually:
Search("Tokyo restaurants") + Search("Kyoto restaurants") in parallel
# vs.
Search("Tokyo restaurants") → wait → Search("Kyoto restaurants")
```

**5. Cache Results**

For repeated queries, cache agent responses:

```python
# Simple caching
cache = {}

def agentic_search_with_cache(query):
    if query in cache:
        return cache[query]

    result = agentic_search(query)
    cache[query] = result
    return result
```

### Quality Optimization

**Problem:** Agent often returns poor results or doesn't refine enough.

**Optimization Strategies:**

**1. Increase Max Iterations**

```python
AGENT_MAX_ITERATIONS = 7  # Up from 5

# Impact:
# - Better results: More opportunity to refine
# - Trade-off: Slower (potentially 10+ seconds)
```

**2. Use More Capable Model**

```python
AGENT_MODEL = "claude-opus-4"  # Up from claude-sonnet-4-5

# Impact:
# - Better reasoning and refinement strategies
# - Trade-off: Slower and more expensive
```

**3. Enhance System Prompt**

Add specific quality guidelines:

```python
AGENT_SYSTEM_MESSAGE = """...
Quality standards:
- Aim for at least 5 high-quality results
- Results should directly match user intent
- If results are weak (vague summaries, poor relevance), try alternative queries
- Be critical: Only accept results with clear relevance to the query
..."""
```

**4. Add Few-Shot Examples**

Show agent examples of good refinement:

```python
AGENT_SYSTEM_MESSAGE = """...
Example refinement strategy:

Query: "perfume"
Search 1: "perfume" → 15 results, too broad
Refinement: "Japanese perfume", category_filter="Beauty" → 5 focused results ✓

Query: "cheap hotels"
Search 1: "cheap hotels" → 0 results
Refinement: "budget hotels" OR "affordable accommodation" → 3 results ✓
..."""
```

### Token Usage Optimization

**Problem:** High API costs due to large token usage.

**Optimization Strategies:**

**1. Reduce Tool Result Verbosity**

Return only essential fields to agent:

```python
def search_collections_minimal(query, top_k=10):
    results = hybrid_search(query, top_k)

    # Return minimal data to agent
    return {
        "count": len(results),
        "items": [
            {
                "headline": r["headline"],
                "category": r["category"],
                "summary": r["summary"][:200]  # Truncate summaries
            }
            for r in results
        ]
    }
```

**2. Use Shorter System Prompts**

```python
# Verbose (high tokens)
AGENT_SYSTEM_MESSAGE = """You are a specialized search assistant helping users find items in their personal image collection. Your task is to understand the user's search intent, use the search_collections tool to find relevant items, analyze the results to determine if they answer the user's query, and if results are insufficient, try refining your search approach with different keywords, broader or narrower terms..."""

# Concise (lower tokens)
AGENT_SYSTEM_MESSAGE = """You are a search assistant. Use search_collections to find items. Refine if results are poor. Be concise."""
```

**3. Limit Reasoning Output**

Encourage brief reasoning:

```python
AGENT_SYSTEM_MESSAGE = """...
Keep your internal reasoning brief and focused.
..."""
```

**4. Set Lower max_tokens**

```python
AGENT_MAX_TOKENS = 1024  # Prevents long outputs
```

### Accuracy Optimization

**Problem:** Agent misinterprets queries or returns irrelevant results.

**Optimization Strategies:**

**1. Add Domain Knowledge**

Include context about collection content:

```python
AGENT_SYSTEM_MESSAGE = """...
Collection context:
- Primarily Japanese travel, food, and beauty items
- Many items from Tokyo, Kyoto, and other Japanese cities
- Beauty items include perfumes (J-Scent brand common), skincare, cosmetics
- Food items are mostly restaurants, cafes, and specific dishes
..."""
```

**2. Provide Category Definitions**

Clarify what each category means:

```python
AGENT_SYSTEM_MESSAGE = """...
Category definitions:
- Beauty: Perfumes, skincare, cosmetics, haircare
- Food: Restaurants, cafes, specific dishes, recipes
- Travel: Destinations, hotels, attractions, shopping streets
- Fashion: Clothing, accessories, shoes
..."""
```

**3. Add Query Interpretation Examples**

Show agent how to interpret common query patterns:

```python
AGENT_SYSTEM_MESSAGE = """...
Query interpretation guide:
- "affordable" / "cheap" → Look for price mentions, budget-friendly descriptions
- "luxury" / "high-end" → Premium brands, expensive items, upscale descriptions
- "traditional" → Cultural, authentic, historical context
- "local" → Neighborhood spots, non-touristy, local recommendations
..."""
```

---

## Troubleshooting

### Issue: Agent Returns Empty Results

**Symptoms:**
- `total_results: 0`
- Agent didn't try alternative queries

**Diagnosis:**

1. Check `tools_used`:
   - Did agent only try one search?
   - What query did it use?

2. Review `agent_reasoning`:
   - Did agent recognize results were empty?
   - Did it consider refinement?

**Solutions:**

**Solution 1:** Update prompt to require refinement on empty results

```python
AGENT_SYSTEM_MESSAGE = """...
If a search returns 0 results:
- ALWAYS try at least one alternative query
- Use synonyms, broader terms, or different phrasing
- Explain what you tried and why
..."""
```

**Solution 2:** Test the search tool directly

```bash
# Does the underlying search work?
curl -X POST http://localhost:8000/search \
  -d '{"query": "YOUR_QUERY", "search_type": "hybrid-lc"}'
```

If direct search also returns 0 results, the issue is data/index, not the agent.

### Issue: Agent Hits Max Iterations Without Good Results

**Symptoms:**
- `tools_used` length = 5 (or your max_iterations value)
- Results are still poor
- Agent reasoning mentions "tried multiple approaches"

**Diagnosis:**

1. Review all `tools_used` queries:
   - Are they getting more specific or just different?
   - Do they show a refinement strategy?

2. Check LangSmith trace:
   - What was agent thinking at each step?
   - Were results improving over iterations?

**Solutions:**

**Solution 1:** Increase max iterations (if results are improving)

```python
AGENT_MAX_ITERATIONS = 7  # Give agent more chances
```

**Solution 2:** Add early stopping guidance (if agent is stuck in loop)

```python
AGENT_SYSTEM_MESSAGE = """...
Stopping criteria:
- After 2 unsuccessful refinements, acknowledge that results may not exist
- Provide best available answer rather than continuing to search
..."""
```

**Solution 3:** Improve refinement strategy in prompt

```python
AGENT_SYSTEM_MESSAGE = """...
Refinement strategy:
- Iteration 1: Exact query
- Iteration 2: Synonyms or broader terms
- Iteration 3: Different category or perspective
- Iteration 4+: Acknowledge limitations and provide partial answer
..."""
```

### Issue: Slow Response Time (>10 seconds)

**Symptoms:**
- `answer_time_ms` > 10000
- Users complain about latency

**Diagnosis:**

1. Check where time is spent:
   - `retrieval_time_ms`: Search execution
   - `answer_time_ms`: Total including LLM calls

2. Review `tools_used` count:
   - How many searches?
   - More searches = more time

3. Check LangSmith trace:
   - Which LLM call is slowest?
   - Is there a pattern?

**Solutions:**

**Solution 1:** Reduce max iterations

```python
AGENT_MAX_ITERATIONS = 3
```

**Solution 2:** Optimize prompt for faster decisions

```python
AGENT_SYSTEM_MESSAGE = """...
Be fast:
- Limit to 1-2 searches
- Accept good results quickly
- Don't over-refine
..."""
```

**Solution 3:** Use streaming (if available)

```python
agent_executor = AgentExecutor(
    agent=agent,
    tools=[search_tool],
    streaming=True  # Stream responses as they're generated
)
```

**Solution 4:** Set timeout

```python
import asyncio

async def agentic_search_with_timeout(query, timeout=8):
    try:
        result = await asyncio.wait_for(
            agentic_search_async(query),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        # Fallback to hybrid search
        return hybrid_search(query)
```

### Issue: High API Costs

**Symptoms:**
- Unexpected high Anthropic/OpenAI bills
- Each query costs $0.05-0.10

**Diagnosis:**

1. Check token usage in LangSmith
2. Calculate cost per query
3. Identify high-token steps

**Solutions:**

**Solution 1:** Reduce max iterations

```python
AGENT_MAX_ITERATIONS = 3  # Fewer LLM calls
```

**Solution 2:** Use cheaper model

```python
AGENT_MODEL = "claude-sonnet-4"  # Cheaper than 4.5
# Or
AGENT_MODEL = "gpt-4o-mini"  # Even cheaper
```

**Solution 3:** Implement caching

```python
# Cache agent responses for repeated queries
from functools import lru_cache

@lru_cache(maxsize=1000)
def agentic_search_cached(query):
    return agentic_search(query)
```

**Solution 4:** Route simple queries to cheaper search

```python
def smart_route(query):
    if len(query.split()) <= 3:
        # Simple query: use fast hybrid search
        return hybrid_search(query)
    else:
        # Complex query: use agentic search
        return agentic_search(query)
```

### Issue: Agent Misinterprets Query

**Symptoms:**
- Results don't match user intent
- Agent reasoning shows wrong interpretation

**Example:**
- Query: "perfume stores"
- Agent interpretation: "perfume" (misses "stores" aspect)

**Diagnosis:**

1. Review `agent_reasoning`
   - What did agent think query meant?

2. Check `tools_used[0].query`
   - What query did agent construct?

**Solutions:**

**Solution 1:** Add interpretation guidelines

```python
AGENT_SYSTEM_MESSAGE = """...
Query interpretation:
- Preserve all key terms from user query
- "stores" / "shops" → Focus on retail locations, not products
- "restaurant" → Dining establishment, not food items
..."""
```

**Solution 2:** Use few-shot examples

```python
AGENT_SYSTEM_MESSAGE = """...
Examples:
- "perfume stores" → Search for "perfume shop" OR "fragrance store"
- "Tokyo restaurants" → Search category="Food" with "Tokyo"
- "affordable beauty" → Search category="Beauty" with "affordable"
..."""
```

**Solution 3:** Add clarification step

```python
AGENT_SYSTEM_MESSAGE = """...
Before searching:
1. Identify the main topic (perfume, restaurant, hotel, etc.)
2. Identify qualifiers (affordable, luxury, Tokyo, etc.)
3. Identify the type of result wanted (products, stores, experiences, etc.)
4. Construct query accordingly
..."""
```

### Issue: Unhelpful agent_reasoning

**Symptoms:**
- `agent_reasoning` is vague or generic
- Doesn't explain why agent made certain decisions

**Example:**
```json
"agent_reasoning": "I searched and found results."
```

**Diagnosis:**

Check if system prompt encourages detailed reasoning.

**Solutions:**

**Solution 1:** Explicitly request detailed reasoning

```python
AGENT_SYSTEM_MESSAGE = """...
Transparency requirement:
- Explain WHY you chose specific search terms
- Describe HOW you interpreted the user's query
- If you refined, explain WHAT you changed and WHY
- Be specific about your decision-making process
..."""
```

**Solution 2:** Add reasoning template

```python
AGENT_SYSTEM_MESSAGE = """...
Reasoning format:
1. Query interpretation: [What did I understand the user wants?]
2. Search strategy: [What query will I try and why?]
3. Result evaluation: [Are results good? Why or why not?]
4. Refinement (if needed): [What am I changing and why?]
..."""
```

---

## Examples

### Example 1: Simple Query (No Refinement)

**User Query:** "J-Scent perfume"

**Agent Flow:**

```
Thought: User is looking for J-Scent perfume specifically. This is a clear, specific query.

Action: search_collections
Action Input: {"query": "J-Scent perfume", "top_k": 10, "category_filter": "Beauty"}

Observation: Found 3 items:
1. J-Scent fragrance review (¥4,950)
2. J-Scent Hisui review (¥4,950)
3. J-Scent Sumo Wrestler review (¥4,950)

Thought: Perfect! All results are exactly what the user asked for—J-Scent perfumes with pricing information. No need to refine.

Final Answer: I found 3 J-Scent perfumes in your collection, all priced at ¥4,950 (~$33):
1. J-Scent fragrance review highlighting Wood Flake, Hisui, and Sumo picks
2. J-Scent Hisui - specific fragrance review
3. J-Scent Sumo Wrestler - specific fragrance review

All are from the affordable Japanese perfume house J-Scent, offering unique scents inspired by Japanese culture.
```

**Response:**

```json
{
  "query": "J-Scent perfume",
  "search_type": "agentic",
  "total_results": 3,
  "answer": "I found 3 J-Scent perfumes in your collection...",
  "agent_reasoning": "User asked for J-Scent perfume specifically. Added category_filter='Beauty' for precision. Initial search returned 3 exact matches with all relevant details (brand, pricing, descriptions). No refinement needed as results perfectly matched the specific query.",
  "tools_used": [
    {
      "tool": "search_collections",
      "query": "J-Scent perfume",
      "top_k": 10,
      "category_filter": "Beauty",
      "results_count": 3
    }
  ],
  "retrieval_time_ms": 118.5,
  "answer_time_ms": 2891.3
}
```

**Lessons:**

- Single iteration sufficient for specific queries
- Agent added category filter for precision (good!)
- Clear reasoning explains why no refinement needed

---

### Example 2: Query Refinement (Synonym)

**User Query:** "cheap perfume"

**Agent Flow:**

```
Thought: User wants affordable perfumes. "Cheap" might not appear in descriptions, but "affordable" or price mentions might.

Action: search_collections
Action Input: {"query": "cheap perfume", "top_k": 10}

Observation: Found 0 items.

Thought: No exact matches for "cheap perfume". Let me try "affordable perfume" as a synonym.

Action: search_collections
Action Input: {"query": "affordable perfume", "top_k": 10}

Observation: Found 3 items:
1. J-Scent perfumes (¥4,950)
2. Budget fragrance options
3. Affordable Japanese perfumes

Thought: Great! "Affordable" found relevant results. These are budget-friendly perfumes around $30-40, which matches the intent of "cheap".

Final Answer: I didn't find items described as "cheap," but I found 3 affordable perfume options:
1. **J-Scent perfumes** at ¥4,950 (~$33) - Japanese niche fragrances at budget-friendly prices
2. Budget fragrance recommendations
3. Collection of affordable Japanese perfumes

These represent good value for quality perfumes.
```

**Response:**

```json
{
  "query": "cheap perfume",
  "search_type": "agentic",
  "total_results": 3,
  "answer": "I didn't find items described as 'cheap,' but I found 3 affordable perfume options...",
  "agent_reasoning": "Initial search for 'cheap perfume' returned 0 results. Recognized that 'cheap' is informal language that may not appear in item descriptions. Tried synonym 'affordable perfume' which successfully found 3 relevant items with explicit pricing around ¥5000 (~$33), representing budget-friendly options. This matched the user's intent of finding inexpensive perfumes.",
  "tools_used": [
    {
      "tool": "search_collections",
      "query": "cheap perfume",
      "results_count": 0
    },
    {
      "tool": "search_collections",
      "query": "affordable perfume",
      "results_count": 3
    }
  ],
  "retrieval_time_ms": 245.8,
  "answer_time_ms": 4102.7
}
```

**Lessons:**

- Agent recognized language mismatch ("cheap" vs formal descriptions)
- Successfully used synonym strategy
- Explained both attempts in reasoning
- Acknowledged the substitution in final answer

---

### Example 3: Multi-Part Query

**User Query:** "Find affordable Japanese perfumes or beauty products"

**Agent Flow:**

```
Thought: User wants Japanese beauty items with emphasis on perfumes, and they should be affordable. I'll search for Japanese perfumes first, then expand to beauty products if needed.

Action: search_collections
Action Input: {"query": "affordable Japanese perfume", "top_k": 10}

Observation: Found 5 items:
1. J-Scent perfumes (¥4,950)
2. J-Scent Hisui (¥4,950)
3. J-Scent Sumo (¥4,950)
4. Japanese fragrance brands
5. Budget Japanese perfumes

Thought: Excellent! Found 5 perfume items, all affordable and Japanese. User also mentioned "or beauty products" so let me check if there are other beauty items beyond perfume.

Action: search_collections
Action Input: {"query": "affordable Japanese beauty", "category_filter": "Beauty", "top_k": 10}

Observation: Found 7 items (includes the 5 perfumes plus):
6. Japanese skincare routine
7. Affordable Japanese cosmetics

Thought: Good. The broader search confirms perfumes are the main affordable Japanese beauty items, with a couple skincare/cosmetics items too. I have comprehensive results.

Final Answer: I found several affordable Japanese beauty products in your collection, with a focus on perfumes as you mentioned:

**Perfumes (5 items):**
- **J-Scent** perfume house with multiple fragrances at ¥4,950 (~$33) [Items 1, 2, 3]
- Other budget-friendly Japanese perfume options [Items 4, 5]

**Other Beauty Products (2 items):**
- Japanese skincare routine guide [Item 6]
- Affordable Japanese cosmetics overview [Item 7]

The J-Scent perfumes stand out as excellent affordable options from a Japanese perfume house, offering unique scents like Wood Flake, Hisui, and Sumo Wrestler.
```

**Response:**

```json
{
  "query": "Find affordable Japanese perfumes or beauty products",
  "search_type": "agentic",
  "total_results": 7,
  "answer": "I found several affordable Japanese beauty products in your collection...",
  "agent_reasoning": "Parsed query into two parts: 'affordable Japanese perfumes' (primary) and 'beauty products' (secondary/broader). First search targeted perfumes specifically and found 5 excellent matches (J-Scent brand at ¥4,950). Second search expanded to all beauty products to ensure comprehensive coverage, finding 2 additional items (skincare, cosmetics). Combined results provide complete answer to multi-part query.",
  "tools_used": [
    {
      "tool": "search_collections",
      "query": "affordable Japanese perfume",
      "results_count": 5
    },
    {
      "tool": "search_collections",
      "query": "affordable Japanese beauty",
      "category_filter": "Beauty",
      "results_count": 7
    }
  ],
  "retrieval_time_ms": 267.4,
  "answer_time_ms": 5234.1
}
```

**Lessons:**

- Agent decomposed multi-part query ("perfumes OR beauty products")
- Searched specific first, then broader
- Organized answer by category
- Highlighted the primary result (perfumes) while including secondary (other beauty)

---

### Example 4: Comparative Query

**User Query:** "Compare Tokyo and Kyoto restaurants"

**Agent Flow:**

```
Thought: User wants a comparison between Tokyo and Kyoto restaurants. I need to search for each city separately and then synthesize a comparison.

Action: search_collections
Action Input: {"query": "Tokyo restaurants", "category_filter": "Food", "top_k": 10}

Observation: Found 5 items:
1. Tofuya Ukai (traditional, expensive)
2. Modern Tokyo dining
3. Shibuya ramen shop
4. Ginza sushi restaurant
5. Tokyo fusion cuisine

Thought: Good Tokyo results showing variety. Now let me search for Kyoto restaurants.

Action: search_collections
Action Input: {"query": "Kyoto restaurants", "category_filter": "Food", "top_k": 10}

Observation: Found 3 items:
1. Traditional kaiseki restaurant
2. Kyoto temple area cafe
3. Historic tea house dining

Thought: Perfect. I have results for both cities. Let me compare them.

Final Answer: Here's a comparison of Tokyo and Kyoto restaurants in your collection:

**Tokyo (5 restaurants):**
- **Style:** Mix of traditional (Tofuya Ukai) and modern/fusion cuisine
- **Price Range:** Varies from budget ramen to expensive fine dining
- **Atmosphere:** Urban, diverse, trendy
- **Examples:** Tofuya Ukai (traditional beneath Tokyo Tower), Shibuya ramen, Ginza sushi

**Kyoto (3 restaurants):**
- **Style:** Predominantly traditional kaiseki and tea house dining
- **Price Range:** More consistent, traditional pricing
- **Atmosphere:** Historic, serene, cultural
- **Examples:** Traditional kaiseki, temple area cafe, historic tea house

**Key Differences:**
- Tokyo offers more variety (traditional to modern fusion)
- Kyoto focuses on traditional Japanese dining experiences
- Tokyo has more restaurants in collection (5 vs 3)
- Kyoto emphasizes cultural and historical dining settings
```

**Response:**

```json
{
  "query": "Compare Tokyo and Kyoto restaurants",
  "search_type": "agentic",
  "total_results": 8,
  "answer": "Here's a comparison of Tokyo and Kyoto restaurants...",
  "agent_reasoning": "Recognized comparative query requiring two separate searches. First searched 'Tokyo restaurants' with Food category filter, finding 5 diverse results. Then searched 'Kyoto restaurants' with same parameters, finding 3 traditional-focused results. Synthesized comparison highlighting style, price, atmosphere, and key differences. Tokyo shows more variety (traditional to modern), while Kyoto emphasizes traditional/cultural dining.",
  "tools_used": [
    {
      "tool": "search_collections",
      "query": "Tokyo restaurants",
      "category_filter": "Food",
      "results_count": 5
    },
    {
      "tool": "search_collections",
      "query": "Kyoto restaurants",
      "category_filter": "Food",
      "results_count": 3
    }
  ],
  "retrieval_time_ms": 289.2,
  "answer_time_ms": 6124.8
}
```

**Lessons:**

- Agent recognized need for two separate searches
- Used same parameters (category_filter) for fair comparison
- Structured answer with clear sections for each city
- Provided analytical synthesis, not just lists

---

### Example 5: Zero Results Handled Gracefully

**User Query:** "flying cars"

**Agent Flow:**

```
Thought: User is looking for flying cars. This seems unlikely to exist in an image collection of travel/food/beauty items, but let me search.

Action: search_collections
Action Input: {"query": "flying cars", "top_k": 10}

Observation: Found 0 items.

Thought: No results as expected. Let me try broader terms like "futuristic" or "vehicles" in case there's something related.

Action: search_collections
Action Input: {"query": "futuristic vehicles", "top_k": 10}

Observation: Found 0 items.

Thought: Still no results. Let me try just "transportation" to see if there are any vehicle-related items.

Action: search_collections
Action Input: {"query": "transportation", "top_k": 10}

Observation: Found 2 items:
1. Tokyo subway system
2. Japan rail pass information

Thought: Found transportation items but nothing related to flying cars. I should acknowledge that flying cars don't exist in the collection but offer these transportation-related items.

Final Answer: I couldn't find any items about flying cars in your collection. After searching multiple variations ("flying cars", "futuristic vehicles", "transportation"), the closest matches are:

1. Tokyo subway system information
2. Japan rail pass details

These are the only transportation-related items I found. Your collection seems focused on travel, food, and beauty items, and doesn't include futuristic vehicle content. Would you like me to search for something else?
```

**Response:**

```json
{
  "query": "flying cars",
  "search_type": "agentic",
  "total_results": 2,
  "answer": "I couldn't find any items about flying cars in your collection...",
  "agent_reasoning": "Searched for 'flying cars' with 0 results (expected, as collection focuses on travel/food/beauty). Attempted refinement with 'futuristic vehicles' (0 results) and broader 'transportation' (2 results: Tokyo subway, Japan rail). None match the specific query for flying cars. Honestly acknowledged the gap and offered the closest available items as alternatives. Suggested user might want to search for something else.",
  "tools_used": [
    {
      "tool": "search_collections",
      "query": "flying cars",
      "results_count": 0
    },
    {
      "tool": "search_collections",
      "query": "futuristic vehicles",
      "results_count": 0
    },
    {
      "tool": "search_collections",
      "query": "transportation",
      "results_count": 2
    }
  ],
  "retrieval_time_ms": 342.7,
  "answer_time_ms": 5891.4
}
```

**Lessons:**

- Agent tried multiple refinement strategies
- Honestly acknowledged when query can't be satisfied
- Offered closest available alternatives
- Maintained helpful tone despite no exact matches
- Suggested next steps to user

---

## Conclusion

Agentic search represents a powerful paradigm for complex information retrieval tasks. By combining LLM reasoning with search tools, it enables:

- **Intelligent query understanding**: Goes beyond literal keywords
- **Iterative refinement**: Adjusts strategy based on result quality
- **Transparent reasoning**: Explains search decisions to users
- **Adaptive behavior**: Handles diverse query types effectively

**When to use agentic search:**
- Complex, multi-part queries
- Ambiguous or exploratory searches
- Comparative analysis
- When transparency and explainability matter

**When to use simpler search:**
- Simple, specific queries
- High-volume or latency-sensitive applications
- Cost-sensitive scenarios

**Key success factors:**
1. Well-crafted system prompts
2. Appropriate iteration limits
3. Quality observability (LangSmith)
4. Continuous monitoring and prompt tuning

With proper configuration and ongoing refinement, agentic search can significantly improve search quality for complex information needs while maintaining transparency and user trust.

---

## Appendix: Configuration Quick Reference

```python
# Recommended starting configuration
AGENT_MODEL = "claude-sonnet-4-5"
AGENT_TEMPERATURE = 0.0
AGENT_MAX_TOKENS = 2048
AGENT_MAX_ITERATIONS = 5
AGENT_EARLY_STOPPING_METHOD = "generate"

# Fast mode (prioritize speed)
AGENT_MAX_ITERATIONS = 2
AGENT_MAX_TOKENS = 1024

# Quality mode (prioritize results)
AGENT_MAX_ITERATIONS = 7
AGENT_MODEL = "claude-opus-4"
AGENT_MAX_TOKENS = 2048

# Budget mode (minimize costs)
AGENT_MODEL = "claude-sonnet-4"
AGENT_MAX_ITERATIONS = 3
AGENT_MAX_TOKENS = 1024
```

---

**Document Version:** 1.0
**Last Updated:** 2025-12-23
**Author:** Collections Local Team
