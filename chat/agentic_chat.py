"""Multi-turn agentic chat orchestrator using LangGraph with conversation memory."""

import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langgraph.prebuilt import create_react_agent
from langsmith import traceable
from langchain_community.tools.tavily_search import TavilySearchResults

from chat.conversation_manager import ConversationManager
from retrieval.langchain_retrievers import HybridLangChainRetriever
from config.chat_config import (
    CHAT_MODEL,
    CHAT_TEMPERATURE,
    CHAT_MAX_TOKENS,
    CHAT_MAX_ITERATIONS,
    CHAT_SYSTEM_MESSAGE,
)

logger = logging.getLogger(__name__)


class AgenticChatOrchestrator:
    """Orchestrates multi-turn agentic chat with conversation memory.

    Extends the single-turn agentic search pattern to support:
    - Persistent conversation state via DynamoDB checkpointing
    - Context-aware responses that reference previous exchanges
    - Follow-up queries ("show me more", "filter those by...")
    - Multi-tenant support with user isolation
    """

    def __init__(
        self,
        chroma_manager,
        conversation_manager: ConversationManager,
        top_k: int = 10,
        category_filter: Optional[str] = None,
        min_relevance_score: float = -1.0,
        min_similarity_score: float = 0.0
    ):
        """Initialize the chat orchestrator.

        Args:
            chroma_manager: ChromaVectorStoreManager for vector search.
            conversation_manager: ConversationManager for state persistence.
            top_k: Number of results per search.
            category_filter: Optional category filter.
            min_relevance_score: Minimum BM25 score.
            min_similarity_score: Minimum vector similarity score.
        """
        self.chroma_manager = chroma_manager
        self.conversation_manager = conversation_manager
        self.top_k = top_k
        self.category_filter = category_filter
        self.min_relevance_score = min_relevance_score
        self.min_similarity_score = min_similarity_score

        # Initialize the LLM
        self.llm = ChatAnthropic(
            model=CHAT_MODEL,
            temperature=CHAT_TEMPERATURE,
            max_tokens=CHAT_MAX_TOKENS
        )

        # Create the retriever (reused across tool calls)
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

        # Create search tool
        self.search_tool = self._create_search_tool()

        # Create Tavily search tool
        self.tavily_tool = self._create_tavily_tool()

        # Create agent with checkpointer for memory
        self.agent = self._create_agent()

        # Store last search results for response building
        self._last_documents: List[Document] = []

    def _create_search_tool(self):
        """Create the search_collections tool."""
        orchestrator = self

        @tool
        def search_collections(query: str) -> str:
            """Search the image collection using hybrid search.

            Use this tool to find relevant items in the collection.
            The search uses both keyword matching and semantic understanding.

            Args:
                query: Search query string

            Returns:
                Formatted search results
            """
            try:
                documents = orchestrator.retriever.invoke(query)

                if not documents:
                    return "No relevant items found for this query."

                # Store for later retrieval
                orchestrator._last_documents = documents

                # Format results concisely
                result_lines = [f"Found {len(documents)} items:"]
                for i, doc in enumerate(documents, 1):
                    metadata = doc.metadata
                    score = metadata.get("rrf_score", metadata.get("score", 0))
                    headline = metadata.get("headline", "Untitled")[:60]
                    category = metadata.get("category", "?")
                    result_lines.append(f"{i}. {headline} [{category}] {score:.2f}")

                return "\n".join(result_lines)

            except Exception as e:
                logger.error(f"Search tool error: {e}")
                return f"Error executing search: {str(e)}"

        return search_collections

    def _create_tavily_tool(self):
        """Create the Tavily web search tool."""
        try:
            from config.chat_config import (
                TAVILY_MAX_RESULTS,
                TAVILY_SEARCH_DEPTH,
                TAVILY_INCLUDE_DOMAINS,
                TAVILY_EXCLUDE_DOMAINS,
            )
            import os

            # Validate API key exists
            if not os.getenv("TAVILY_API_KEY"):
                logger.error("TAVILY_API_KEY not found in environment variables")
                return None

            # Parse domain lists
            include_domains = [d.strip() for d in TAVILY_INCLUDE_DOMAINS.split(",") if d.strip()]
            exclude_domains = [d.strip() for d in TAVILY_EXCLUDE_DOMAINS.split(",") if d.strip()]

            # Create Tavily search tool with optional domain filtering
            tavily_kwargs = {
                "max_results": TAVILY_MAX_RESULTS,
                "search_depth": TAVILY_SEARCH_DEPTH,
                "include_answer": True,  # Get AI-generated answer summary
                "include_raw_content": False,  # Don't need full page content
            }

            # Only add domain filters if they have values
            if include_domains:
                tavily_kwargs["include_domains"] = include_domains
            if exclude_domains:
                tavily_kwargs["exclude_domains"] = exclude_domains

            tavily = TavilySearchResults(**tavily_kwargs)

            # Customize the tool description for agent guidance
            tavily.name = "search_web"
            tavily.description = """Search the web for current information, facts, or external knowledge.

Use this tool when:
- The query asks about current events, recent information, or breaking news
- The query requires general knowledge not in the image collection
- The user explicitly asks to "search the web" or "look online"
- The query is about facts, definitions, or public information

Args:
    query: The search query string

Returns:
    List of web search results with titles, URLs, and content snippets.
"""

            return tavily

        except Exception as e:
            logger.error(f"Failed to create Tavily tool: {e}")
            logger.warning("Tavily search will not be available. Check TAVILY_API_KEY in .env")
            return None

    def _create_agent(self):
        """Create the LangGraph agent with checkpointer."""
        checkpointer = self.conversation_manager.get_checkpointer()

        # Build tools list - include Tavily if available
        tools = [self.search_tool]
        if self.tavily_tool is not None:
            tools.append(self.tavily_tool)
            logger.info("Tavily web search enabled")
        else:
            logger.info("Running without Tavily web search")

        agent = create_react_agent(
            model=self.llm,
            tools=tools,
            checkpointer=checkpointer,
            prompt=CHAT_SYSTEM_MESSAGE
        )

        return agent

    @traceable(name="chat", run_type="chain")
    def chat(self, message: str, session_id: str) -> Dict[str, Any]:
        """Process a chat message with conversation memory.

        Args:
            message: User's message.
            session_id: Session identifier for conversation continuity.

        Returns:
            Dict with response, search results, reasoning, etc.
        """
        start_time = time.time()

        try:
            # Reset last documents
            self._last_documents = []

            # Get thread config for this session
            config = self.conversation_manager.get_thread_config(session_id)

            # Add metadata for tracing
            config["metadata"] = {
                "session_id": session_id,
                "model": CHAT_MODEL,
            }
            config["tags"] = ["chat", "multi-turn"]
            config["recursion_limit"] = CHAT_MAX_ITERATIONS * 4

            # Create input message
            inputs = {"messages": [HumanMessage(content=message)]}

            # Stream agent execution
            reasoning_steps = []
            tools_used = []
            final_answer = ""
            all_messages = []
            tool_call_counter = 0

            for event in self.agent.stream(inputs, config=config):
                if "agent" in event:
                    agent_messages = event["agent"].get("messages", [])
                    all_messages.extend(agent_messages)

                    for msg in agent_messages:
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            for tool_call in msg.tool_calls:
                                tool_info = {
                                    "tool": tool_call.get("name", "search_collections"),
                                    "input": tool_call.get("args", {}),
                                    "output": "",
                                    "index": tool_call_counter
                                }
                                tools_used.append(tool_info)
                                tool_call_counter += 1

                elif "tools" in event:
                    tool_messages = event["tools"].get("messages", [])
                    all_messages.extend(tool_messages)

                    # Match responses to tool calls
                    start_idx = max(0, len(tools_used) - len(tool_messages))
                    for idx, msg in enumerate(tool_messages):
                        if hasattr(msg, 'content') and msg.content:
                            target_idx = start_idx + idx
                            if target_idx < len(tools_used):
                                tools_used[target_idx]["output"] = str(msg.content)[:500]

            # Extract final answer from AI messages
            for msg in all_messages:
                if hasattr(msg, 'content') and isinstance(msg.content, str) and msg.content:
                    msg_type = getattr(msg, 'type', '')
                    if msg_type == 'ai' or (hasattr(msg, '__class__') and 'AI' in msg.__class__.__name__):
                        if not (hasattr(msg, 'tool_calls') and msg.tool_calls):
                            final_answer = str(msg.content)
                            reasoning_steps.append(final_answer)

            # Fallback answer
            if not final_answer:
                if self._last_documents:
                    final_answer = f"Found {len(self._last_documents)} items matching your query."
                else:
                    final_answer = "I couldn't find any relevant items. Could you try rephrasing your question?"

            # Clean up tool info
            for tool in tools_used:
                tool.pop("index", None)

            # Get session info for turn count
            session_info = self.conversation_manager.get_session_info(session_id)
            turn_count = session_info.get("message_count", 1) if session_info else 1

            response_time = (time.time() - start_time) * 1000

            return {
                "session_id": session_id,
                "response": final_answer,
                "documents": self._last_documents,
                "reasoning": reasoning_steps if reasoning_steps else ["Response generated"],
                "tools_used": tools_used,
                "conversation_turn": turn_count,
                "response_time_ms": response_time,
            }

        except Exception as e:
            logger.error(f"Chat failed: {e}")
            return {
                "session_id": session_id,
                "response": f"I encountered an error: {str(e)}",
                "documents": [],
                "reasoning": [f"Error: {str(e)}"],
                "tools_used": [],
                "conversation_turn": 0,
                "response_time_ms": (time.time() - start_time) * 1000,
            }

    def get_conversation_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get conversation history for a session.

        Args:
            session_id: Session identifier.

        Returns:
            List of message dicts with role and content.
        """
        try:
            config = self.conversation_manager.get_thread_config(session_id)
            checkpointer = self.conversation_manager.get_checkpointer()

            # Get the latest checkpoint for this thread
            checkpoint = checkpointer.get(config)

            if not checkpoint:
                return []

            # Extract messages from checkpoint state
            messages = []
            state = checkpoint.get("channel_values", {})
            raw_messages = state.get("messages", [])

            for msg in raw_messages:
                if isinstance(msg, HumanMessage):
                    messages.append({
                        "role": "user",
                        "content": msg.content,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                elif isinstance(msg, AIMessage):
                    # Skip tool call messages
                    if not (hasattr(msg, 'tool_calls') and msg.tool_calls):
                        messages.append({
                            "role": "assistant",
                            "content": msg.content,
                            "timestamp": datetime.utcnow().isoformat(),
                        })

            return messages

        except Exception as e:
            logger.error(f"Failed to get conversation history: {e}")
            return []

    def clear_session(self, session_id: str) -> bool:
        """Clear a conversation session.

        Args:
            session_id: Session identifier.

        Returns:
            True if session was cleared.
        """
        return self.conversation_manager.delete_session(session_id)
