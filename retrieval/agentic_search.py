"""Agentic search orchestrator using LangGraph with Claude Sonnet 4.5."""

import logging
from typing import List, Dict, Any, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from langsmith import traceable

from retrieval.langchain_retrievers import HybridLangChainRetriever
from config.agent_config import (
    AGENT_MODEL,
    AGENT_TEMPERATURE,
    AGENT_MAX_TOKENS,
    AGENT_MAX_ITERATIONS,
    AGENT_SYSTEM_MESSAGE,
    SEARCH_TOOL_NAME,
    SEARCH_TOOL_DESCRIPTION,
)

logger = logging.getLogger(__name__)


class AgenticSearchOrchestrator:
    """Orchestrates agentic search using LangChain agents and tools.

    This orchestrator wraps HybridLangChainRetriever in a tool and provides
    it to a LangChain agent (Claude Sonnet 4.5) that can iteratively search
    and refine queries to better answer user questions.
    """

    def __init__(
        self,
        chroma_manager,
        top_k: int = 10,
        category_filter: Optional[str] = None,
        min_relevance_score: float = -1.0,
        min_similarity_score: float = 0.0
    ):
        """Initialize the agentic search orchestrator.

        Args:
            chroma_manager: ChromaVectorStoreManager instance for vector search
            top_k: Number of results to return per search
            category_filter: Optional category filter
            min_relevance_score: Minimum BM25 relevance score
            min_similarity_score: Minimum vector similarity score
        """
        self.chroma_manager = chroma_manager
        self.top_k = top_k
        self.category_filter = category_filter
        self.min_relevance_score = min_relevance_score
        self.min_similarity_score = min_similarity_score

        # Initialize the LLM for the agent
        self.llm = ChatAnthropic(
            model=AGENT_MODEL,
            temperature=AGENT_TEMPERATURE,
            max_tokens=AGENT_MAX_TOKENS
        )

        # OPTIMIZATION: Create retriever once and reuse it
        # This avoids re-instantiation overhead on every tool call
        self.retriever = HybridLangChainRetriever(
            top_k=self.top_k,
            bm25_top_k=self.top_k * 2,
            vector_top_k=self.top_k * 2,
            bm25_weight=0.3,
            vector_weight=0.7,
            rrf_c=15,
            category_filter=self.category_filter,
            min_relevance_score=self.min_relevance_score,
            min_similarity_score=self.min_similarity_score,
            chroma_manager=self.chroma_manager
        )

        # Create the search tool
        self.search_tool = self._create_search_tool()

        # Create the agent graph
        self.agent_graph = self._create_agent()

    def _create_search_tool(self):
        """Create the search_collections tool wrapping HybridLangChainRetriever."""

        # Capture self in closure for tool function
        orchestrator = self

        @tool
        def search_collections(query: str) -> str:
            """Search the collection using hybrid search.

            Args:
                query: Search query string

            Returns:
                Formatted string with search results
            """
            # Execute search using the reusable retriever instance
            # OPTIMIZATION: Reuses self.retriever instead of creating new instance
            try:
                documents = orchestrator.retriever.invoke(query)

                if not documents:
                    return "No relevant items found for this query."

                # Store documents for later retrieval
                orchestrator._last_documents = documents

                # OPTIMIZATION: Reduced verbosity - minimal output format
                # Only include essential info: rank, title, category, score
                # Removed 200-char content preview to reduce token usage
                result_lines = [f"Found {len(documents)} items:"]
                for i, doc in enumerate(documents, 1):
                    metadata = doc.metadata
                    score = metadata.get("rrf_score", metadata.get("score", 0))
                    result_lines.append(
                        f"{i}. {metadata.get('headline', 'Untitled')[:60]} "
                        f"[{metadata.get('category', '?')}] {score:.2f}"
                    )

                return "".join(result_lines)

            except Exception as e:
                logger.error(f"Search tool error: {e}")
                return f"Error executing search: {str(e)}"

        return search_collections

    def _create_agent(self):
        """Create the LangGraph ReAct agent."""

        # Create agent graph using LangGraph
        agent_graph = create_react_agent(
            model=self.llm,
            tools=[self.search_tool],
            prompt=AGENT_SYSTEM_MESSAGE
        )

        return agent_graph

    def _format_initial_results(self, documents: List[Document]) -> str:
        """Format initial search results for agent prompt."""
        if not documents:
            return "No results found."

        result_lines = [f"Found {len(documents)} items:"]
        for i, doc in enumerate(documents, 1):
            m = doc.metadata
            score = m.get("rrf_score", m.get("score", 0))
            # Concise format: rank, title, category, score
            result_lines.append(
                f"{i}. {m.get('headline', 'Untitled')[:60]} "
                f"[{m.get('category', '?')}] {score:.2f}"
            )

        return "\n".join(result_lines)

    @traceable(name="agentic_search", run_type="chain")
    def search(self, query: str) -> Dict[str, Any]:
        """Execute agentic search and return results with reasoning.

        This implementation uses "eager first search" optimization:
        1. Performs initial hybrid search BEFORE starting the agent
        2. Presents results to the agent in the initial prompt
        3. Agent evaluates if results are sufficient or if refinement is needed

        Benefits:
        - Saves 1 LLM call (agent doesn't need to decide to do initial search)
        - Reduces latency by ~1.5-2 seconds for most queries
        - Agent can focus on evaluation rather than query construction

        Args:
            query: User's search query

        Returns:
            Dict with:
                - documents: List of final Document objects
                - reasoning: List of agent reasoning steps
                - tools_used: List of tool invocations with inputs/outputs
                - final_answer: Agent's final response
        """
        try:
            # Initialize last_documents
            self._last_documents = []

            # OPTIMIZATION: Eager first search - perform initial search BEFORE agent starts
            # Uses the reusable self.retriever instance created in __init__
            logger.info(f"Performing eager first search for query: {query}")
            initial_documents = self.retriever.invoke(query)
            self._last_documents = initial_documents  # Store for potential use

            # Format results for agent
            formatted_results = self._format_initial_results(initial_documents)

            # Create enhanced prompt with pre-fetched results
            enhanced_query = f"""User query: "{query}"

I've already performed an initial hybrid search and found {len(initial_documents)} results:

{formatted_results}

Your task:
1. Analyze these results - do they adequately answer the user's query?
2. If YES: Provide a clear summary of the findings
3. If NO (fewer than 3 results OR completely off-topic): Use search_collections to refine with a different query

Remember: The search uses semantic understanding, so synonyms and related terms are already matched. Only refine if truly necessary."""

            # Execute the agent graph with enhanced prompt
            inputs = {"messages": [HumanMessage(content=enhanced_query)]}

            config = {
                "metadata": {
                    "search_type": "agentic",
                    "model": AGENT_MODEL,
                    "eager_first_search": True  # Track that we used this optimization
                },
                "tags": ["agentic-search", "eager-first-search"],
                # LangGraph recursion limit counts all graph steps (agent + tool calls)
                # Each iteration involves ~3 steps, so multiply by 4 to be safe
                "recursion_limit": AGENT_MAX_ITERATIONS * 4
            }

            # Stream the agent execution to get all steps
            reasoning_steps = []
            tools_used = []
            final_answer = ""
            all_messages = []
            tool_call_counter = 0

            for event in self.agent_graph.stream(inputs, config=config):
                # Extract messages from each event
                if "agent" in event:
                    agent_messages = event["agent"].get("messages", [])
                    all_messages.extend(agent_messages)
                    for msg in agent_messages:
                        # Extract tool calls
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            for tool_call in msg.tool_calls:
                                tool_info = {
                                    "tool": tool_call.get("name", SEARCH_TOOL_NAME),
                                    "input": tool_call.get("args", {}),
                                    "output": "",  # Will be filled by tool response
                                    "index": tool_call_counter
                                }
                                tools_used.append(tool_info)
                                tool_call_counter += 1

                elif "tools" in event:
                    tool_messages = event["tools"].get("messages", [])
                    all_messages.extend(tool_messages)
                    # Match tool responses to tool calls by order
                    start_idx = max(0, len(tools_used) - len(tool_messages))
                    for idx, msg in enumerate(tool_messages):
                        if hasattr(msg, 'content') and msg.content:
                            target_idx = start_idx + idx
                            if target_idx < len(tools_used):
                                # Truncate output to prevent huge responses
                                tools_used[target_idx]["output"] = str(msg.content)[:300]

            # Get documents from last tool execution
            documents = self._last_documents

            # Extract final answer and reasoning from AI messages
            for msg in all_messages:
                if hasattr(msg, 'content') and isinstance(msg.content, str) and msg.content:
                    # Check if this is an AI message
                    msg_type = getattr(msg, 'type', '')

                    # AI messages without tool calls are reasoning/answers
                    if msg_type == 'ai' or (hasattr(msg, '__class__') and 'AI' in msg.__class__.__name__):
                        if not (hasattr(msg, 'tool_calls') and msg.tool_calls):
                            # This is the final answer
                            final_answer = str(msg.content)
                            reasoning_steps.append(final_answer)

            # Build summary reasoning from tool calls if no explicit reasoning
            if not reasoning_steps and tools_used:
                summary_parts = []
                summary_parts.append(f"Executed {len(tools_used)} search operation(s)")
                for idx, tool in enumerate(tools_used, 1):
                    query = tool["input"].get("query", "unknown")
                    summary_parts.append(f"Search {idx}: '{query}'")
                reasoning_steps.append(". ".join(summary_parts))

            # Fallback: generate simple answer from search results
            if not final_answer:
                if documents:
                    final_answer = f"Found {len(documents)} items matching your query."
                else:
                    final_answer = "No items found matching your query."

            # Clean up tool info - remove internal index
            for tool in tools_used:
                tool.pop("index", None)

            return {
                "documents": documents,
                "reasoning": reasoning_steps if reasoning_steps else ["Agent completed search"],
                "tools_used": tools_used,
                "final_answer": final_answer,
                "iterations": len(tools_used)
            }

        except Exception as e:
            logger.error(f"Agentic search failed: {e}")
            # Return empty result on error
            return {
                "documents": [],
                "reasoning": [f"Error: {str(e)}"],
                "tools_used": [],
                "final_answer": f"Search failed: {str(e)}",
                "iterations": 0
            }
