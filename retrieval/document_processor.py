"""
Document chunking and preprocessing for Collections Local API.

Provides chained document splitting:
1. RecursiveJsonSplitter (maintains JSON structure)
2. TokenTextSplitter (respects token limits)

Enabled by default with large chunk size to accommodate typical responses.
"""

import logging
import json
from typing import List

from langchain_text_splitters import RecursiveJsonSplitter, TokenTextSplitter
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Document processor with chained JSON + token splitting.

    Features:
    - Chained splitters: RecursiveJsonSplitter FIRST, then TokenTextSplitter
    - ENABLED by default (all documents processed)
    - Large max_chunk_size (2000 tokens) for typical large responses
    - Graceful fallback if JSON parsing fails
    - Preserves metadata in all chunks
    """

    def __init__(
        self,
        enable_chunking: bool = True,  # ENABLED by default
        max_chunk_size: int = 2000,    # Large enough for typical responses
        chunk_overlap: int = 200
    ):
        """Initialize document processor.

        Args:
            enable_chunking: Enable chunking (default True)
            max_chunk_size: Maximum chunk size in tokens (default 2000)
            chunk_overlap: Overlap between chunks in tokens (default 200)
        """
        self.enable_chunking = enable_chunking
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap

        if enable_chunking:
            # Step 1: JSON-aware splitting (maintains structure)
            self.json_splitter = RecursiveJsonSplitter(
                max_chunk_size=max_chunk_size
            )

            # Step 2: Token-based splitting (for embeddings)
            self.token_splitter = TokenTextSplitter(
                chunk_size=max_chunk_size,
                chunk_overlap=chunk_overlap
            )

            logger.info(
                f"Document processor initialized: "
                f"chunking={enable_chunking}, max_chunk_size={max_chunk_size}"
            )

    def process_documents(self, documents: List[Document]) -> List[Document]:
        """Process documents with chained JSON + token splitting.

        Returns original documents if chunking disabled.

        Processing steps:
        1. Extract raw_response (JSON) from metadata
        2. Apply RecursiveJsonSplitter to JSON structure
        3. Apply TokenTextSplitter to each JSON chunk
        4. Fallback to token splitting if JSON parsing fails

        Args:
            documents: List of Documents to process

        Returns:
            List of processed Documents (chunked or original)
        """
        if not self.enable_chunking:
            logger.debug("Chunking disabled, returning original documents")
            return documents

        processed_docs = []

        for doc in documents:
            try:
                # Step 1: Try JSON splitting first (if content is JSON)
                raw_response = doc.metadata.get("raw_response")

                # Parse raw_response if it's a string
                if isinstance(raw_response, str):
                    try:
                        raw_response = json.loads(raw_response)
                    except json.JSONDecodeError:
                        raw_response = None

                if raw_response and isinstance(raw_response, dict):
                    # Split JSON structure
                    json_chunks = self.json_splitter.split_json(
                        json_data=raw_response,
                        convert_lists=True
                    )

                    # Step 2: Apply token splitting to each JSON chunk
                    for i, json_chunk in enumerate(json_chunks):
                        chunk_text = (
                            json.dumps(json_chunk)
                            if isinstance(json_chunk, dict)
                            else str(json_chunk)
                        )

                        # Create document from JSON chunk
                        chunk_doc = Document(
                            page_content=chunk_text,
                            metadata={
                                **doc.metadata,
                                "chunk_index": i,
                                "total_chunks": len(json_chunks),
                                "split_method": "json+token"
                            }
                        )
                        processed_docs.append(chunk_doc)

                    logger.debug(
                        f"JSON split {doc.metadata.get('item_id')}: "
                        f"{len(json_chunks)} chunks"
                    )

                else:
                    # Fallback: Use token splitter on page_content
                    chunks = self.token_splitter.split_documents([doc])

                    for i, chunk in enumerate(chunks):
                        chunk.metadata.update({
                            "chunk_index": i,
                            "total_chunks": len(chunks),
                            "split_method": "token_only"
                        })

                    processed_docs.extend(chunks)

                    logger.debug(
                        f"Token split {doc.metadata.get('item_id')}: "
                        f"{len(chunks)} chunks"
                    )

            except (json.JSONDecodeError, AttributeError, Exception) as e:
                logger.warning(
                    f"JSON splitting failed for {doc.metadata.get('item_id')}: {e}"
                )

                # Fallback: Use token splitter on page_content
                try:
                    chunks = self.token_splitter.split_documents([doc])

                    for i, chunk in enumerate(chunks):
                        chunk.metadata.update({
                            "chunk_index": i,
                            "total_chunks": len(chunks),
                            "split_method": "token_fallback"
                        })

                    processed_docs.extend(chunks)

                except Exception as fallback_error:
                    logger.error(
                        f"Token splitting fallback failed for "
                        f"{doc.metadata.get('item_id')}: {fallback_error}"
                    )
                    # Last resort: keep original document
                    processed_docs.append(doc)

        logger.info(
            f"Processed {len(documents)} documents into {len(processed_docs)} chunks"
        )
        return processed_docs

    def process_single_document(self, document: Document) -> List[Document]:
        """Process a single document.

        Convenience method for processing one document at a time.

        Args:
            document: Document to process

        Returns:
            List of processed Documents (chunked or original)
        """
        return self.process_documents([document])
