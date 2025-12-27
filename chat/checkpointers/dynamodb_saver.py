"""DynamoDB-based checkpoint saver for LangGraph conversations.

Implements BaseCheckpointSaver using AWS DynamoDB for serverless,
multi-tenant conversation state persistence with automatic TTL expiration.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Iterator, Optional, Sequence
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
)
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


class DynamoDBSaver(BaseCheckpointSaver):
    """DynamoDB-based checkpoint saver for LangGraph agents.

    Features:
    - Multi-tenant thread IDs: {user_id}#{session_id}
    - Automatic TTL expiration (4 hours default)
    - Supports all BaseCheckpointSaver operations
    - Uses boto3 DynamoDB resource API

    Attributes:
        table_name: Name of the DynamoDB table
        ttl_hours: Hours until checkpoint expires (default: 4)
        region_name: AWS region name
    """

    def __init__(
        self,
        table_name: str,
        ttl_hours: int = 4,
        region_name: Optional[str] = None,
        **kwargs
    ):
        """Initialize the DynamoDB checkpoint saver.

        Args:
            table_name: Name of the DynamoDB table for checkpoints
            ttl_hours: Hours until checkpoint expires (default: 4)
            region_name: AWS region name (uses default if None)
            **kwargs: Additional arguments passed to BaseCheckpointSaver
        """
        super().__init__(**kwargs)

        self.table_name = table_name
        self.ttl_hours = ttl_hours
        self.region_name = region_name

        # Initialize DynamoDB resource
        if region_name:
            self.dynamodb = boto3.resource('dynamodb', region_name=region_name)
        else:
            self.dynamodb = boto3.resource('dynamodb')

        self.table = self.dynamodb.Table(table_name)

        logger.info(f"Initialized DynamoDBSaver with table={table_name}, ttl_hours={ttl_hours}")

    def _calculate_ttl(self) -> int:
        """Calculate TTL timestamp for current time + ttl_hours.

        Returns:
            Unix timestamp (seconds since epoch)
        """
        expiration = datetime.utcnow() + timedelta(hours=self.ttl_hours)
        return int(expiration.timestamp())

    def _serialize_checkpoint(self, checkpoint: Checkpoint) -> bytes:
        """Serialize checkpoint for DynamoDB storage.

        Args:
            checkpoint: Checkpoint to serialize

        Returns:
            Serialized bytes suitable for DynamoDB storage
        """
        # Use the serde serializer from BaseCheckpointSaver
        # dumps_typed returns (type, bytes) tuple
        type_str, data_bytes = self.serde.dumps_typed(checkpoint)
        # For DynamoDB, store as bytes (Binary type)
        return data_bytes

    def _deserialize_checkpoint(self, data) -> Checkpoint:
        """Deserialize checkpoint from DynamoDB storage.

        Args:
            data: Serialized checkpoint bytes (may be Binary object from DynamoDB)

        Returns:
            Checkpoint object
        """
        # Convert DynamoDB Binary to bytes if needed
        if hasattr(data, 'value'):
            # DynamoDB Binary object
            data = bytes(data.value)

        # Use the serde deserializer from BaseCheckpointSaver
        # The JsonPlusSerializer uses msgpack for binary data
        return self.serde.loads_typed(("msgpack", data))

    def _serialize_metadata(self, metadata: CheckpointMetadata) -> dict:
        """Serialize metadata for DynamoDB storage.

        Args:
            metadata: Metadata to serialize

        Returns:
            Dict suitable for DynamoDB storage
        """
        # Convert metadata dict to DynamoDB-compatible format
        # (handle any float values that need to be Decimal)
        result = {}
        for key, value in metadata.items():
            if isinstance(value, float):
                result[key] = Decimal(str(value))
            else:
                result[key] = value
        return result

    def _deserialize_metadata(self, item: dict) -> CheckpointMetadata:
        """Deserialize metadata from DynamoDB storage.

        Args:
            item: DynamoDB item containing metadata

        Returns:
            CheckpointMetadata dict
        """
        # Convert Decimal back to float
        result = {}
        for key, value in item.items():
            if isinstance(value, Decimal):
                result[key] = float(value)
            else:
                result[key] = value
        return result

    def _deserialize_write_value(self, type_str: str, value):
        """Deserialize a write value from DynamoDB storage.

        Args:
            type_str: Type indicator for deserialization
            value: Value to deserialize (may be Binary object)

        Returns:
            Deserialized value
        """
        # Convert DynamoDB Binary to bytes if needed
        if hasattr(value, 'value'):
            value = bytes(value.value)

        return self.serde.loads_typed((type_str, value))

    def _get_thread_id(self, config: RunnableConfig) -> str:
        """Extract thread_id from config.

        Args:
            config: RunnableConfig with configurable.thread_id

        Returns:
            Thread ID string

        Raises:
            ValueError: If thread_id not found in config
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            raise ValueError("thread_id must be provided in config['configurable']")
        return thread_id

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Fetch a checkpoint tuple from DynamoDB.

        Args:
            config: Configuration specifying which checkpoint to retrieve

        Returns:
            CheckpointTuple or None if not found
        """
        try:
            thread_id = self._get_thread_id(config)
            checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
            checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

            # Build the sort key
            if checkpoint_id:
                # Specific checkpoint requested
                sort_key = f"{checkpoint_ns}#{checkpoint_id}"
            else:
                # Get the latest checkpoint for this thread
                # Query with limit=1, descending order
                query_kwargs = {
                    'KeyConditionExpression': Key('thread_id').eq(thread_id),
                    'Limit': 1,
                    'ScanIndexForward': False  # Descending order (latest first)
                }

                # Add filter for checkpoint_ns if specified
                if checkpoint_ns:
                    query_kwargs['FilterExpression'] = Key('checkpoint_ns').eq(checkpoint_ns)

                response = self.table.query(**query_kwargs)

                if not response.get('Items'):
                    return None

                item = response['Items'][0]

                # Build CheckpointTuple
                checkpoint = self._deserialize_checkpoint(item['checkpoint_data'])
                metadata = self._deserialize_metadata(item.get('metadata', {}))

                parent_config = None
                if item.get('parent_checkpoint_id'):
                    parent_config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": item['parent_checkpoint_id']
                        }
                    }

                # Deserialize pending_writes if present
                pending_writes = []
                if 'pending_writes' in item:
                    for write in item['pending_writes']:
                        pending_writes.append((
                            write['task_id'],
                            write['channel'],
                            self._deserialize_write_value(write['type'], write['value'])
                        ))

                return CheckpointTuple(
                    config=config,
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config=parent_config,
                    pending_writes=pending_writes
                )

            # Get specific checkpoint
            response = self.table.get_item(
                Key={
                    'thread_id': thread_id,
                    'sort_key': sort_key
                }
            )

            if 'Item' not in response:
                return None

            item = response['Item']

            # Build CheckpointTuple
            checkpoint = self._deserialize_checkpoint(item['checkpoint_data'])
            metadata = self._deserialize_metadata(item.get('metadata', {}))

            parent_config = None
            if item.get('parent_checkpoint_id'):
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": item['parent_checkpoint_id']
                    }
                }

            # Deserialize pending_writes if present
            pending_writes = []
            if 'pending_writes' in item:
                for write in item['pending_writes']:
                    pending_writes.append((
                        write['task_id'],
                        write['channel'],
                        self._deserialize_write_value(write['type'], write['value'])
                    ))

            return CheckpointTuple(
                config=config,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
                pending_writes=pending_writes
            )

        except ClientError as e:
            logger.error(f"DynamoDB get error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in get_tuple: {e}")
            return None

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """List checkpoints from DynamoDB matching criteria.

        Args:
            config: Base configuration for filtering checkpoints
            filter: Additional filtering criteria for metadata
            before: List checkpoints created before this configuration
            limit: Maximum number of checkpoints to return

        Yields:
            CheckpointTuple objects matching criteria
        """
        try:
            if not config:
                logger.warning("list() called without config, returning empty iterator")
                return

            thread_id = self._get_thread_id(config)
            checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

            # Build query parameters
            query_kwargs = {
                'KeyConditionExpression': Key('thread_id').eq(thread_id),
                'ScanIndexForward': False  # Descending order (latest first)
            }

            if limit:
                query_kwargs['Limit'] = limit

            # Query DynamoDB
            response = self.table.query(**query_kwargs)

            for item in response.get('Items', []):
                # Filter by checkpoint_ns if specified
                item_ns = item.get('checkpoint_ns', '')
                if checkpoint_ns and item_ns != checkpoint_ns:
                    continue

                # Apply metadata filter if provided
                if filter:
                    metadata = self._deserialize_metadata(item.get('metadata', {}))
                    if not all(metadata.get(k) == v for k, v in filter.items()):
                        continue

                # Apply before filter if provided
                if before:
                    before_checkpoint_id = before.get("configurable", {}).get("checkpoint_id")
                    if before_checkpoint_id:
                        # Compare checkpoint IDs (assuming they are sortable)
                        item_checkpoint_id = item.get('checkpoint_id')
                        if item_checkpoint_id and item_checkpoint_id >= before_checkpoint_id:
                            continue

                # Build CheckpointTuple
                checkpoint = self._deserialize_checkpoint(item['checkpoint_data'])
                metadata = self._deserialize_metadata(item.get('metadata', {}))

                checkpoint_id = item.get('checkpoint_id')
                tuple_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": item_ns,
                        "checkpoint_id": checkpoint_id
                    }
                }

                parent_config = None
                if item.get('parent_checkpoint_id'):
                    parent_config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": item_ns,
                            "checkpoint_id": item['parent_checkpoint_id']
                        }
                    }

                # Deserialize pending_writes if present
                pending_writes = []
                if 'pending_writes' in item:
                    for write in item['pending_writes']:
                        pending_writes.append((
                            write['task_id'],
                            write['channel'],
                            self._deserialize_write_value(write['type'], write['value'])
                        ))

                yield CheckpointTuple(
                    config=tuple_config,
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config=parent_config,
                    pending_writes=pending_writes
                )

        except ClientError as e:
            logger.error(f"DynamoDB list error: {e}")
            return
        except Exception as e:
            logger.error(f"Unexpected error in list: {e}")
            return

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store a checkpoint in DynamoDB.

        Args:
            config: Configuration for the checkpoint
            checkpoint: The checkpoint to store
            metadata: Additional metadata for the checkpoint
            new_versions: New channel versions as of this write

        Returns:
            Updated configuration after storing the checkpoint
        """
        try:
            thread_id = self._get_thread_id(config)
            checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

            # Generate checkpoint ID if not provided
            checkpoint_id = checkpoint.get("id")
            if not checkpoint_id:
                checkpoint_id = checkpoint["id"] = str(int(time.time() * 1000000))

            # Build sort key
            sort_key = f"{checkpoint_ns}#{checkpoint_id}"

            # Get parent checkpoint ID from config
            parent_checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

            # Serialize checkpoint and metadata
            serialized_checkpoint = self._serialize_checkpoint(checkpoint)
            serialized_metadata = self._serialize_metadata(metadata)

            # Build item
            item = {
                'thread_id': thread_id,
                'sort_key': sort_key,
                'checkpoint_id': checkpoint_id,
                'checkpoint_ns': checkpoint_ns,
                'checkpoint_data': serialized_checkpoint,
                'metadata': serialized_metadata,
                'expires_at': self._calculate_ttl(),
                'created_at': datetime.utcnow().isoformat()
            }

            if parent_checkpoint_id:
                item['parent_checkpoint_id'] = parent_checkpoint_id

            # Store in DynamoDB
            self.table.put_item(Item=item)

            logger.debug(f"Stored checkpoint {checkpoint_id} for thread {thread_id}")

            # Return updated config with new checkpoint_id
            return {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id
                }
            }

        except ClientError as e:
            logger.error(f"DynamoDB put error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in put: {e}")
            raise

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store intermediate writes linked to a checkpoint.

        Args:
            config: Configuration of the related checkpoint
            writes: List of (channel, value) writes to store
            task_id: Identifier for the task creating the writes
            task_path: Path of the task creating the writes
        """
        try:
            thread_id = self._get_thread_id(config)
            checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
            checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

            if not checkpoint_id:
                logger.warning("put_writes called without checkpoint_id, skipping")
                return

            # Serialize writes
            serialized_writes = []
            for channel, value in writes:
                serialized = self.serde.dumps_typed(value)
                serialized_writes.append({
                    'task_id': task_id,
                    'task_path': task_path,
                    'channel': channel,
                    'type': serialized[0],
                    'value': serialized[1]
                })

            # Update the checkpoint item with pending writes
            sort_key = f"{checkpoint_ns}#{checkpoint_id}"

            # Use update_item to append to pending_writes list
            self.table.update_item(
                Key={
                    'thread_id': thread_id,
                    'sort_key': sort_key
                },
                UpdateExpression='SET pending_writes = list_append(if_not_exists(pending_writes, :empty_list), :writes)',
                ExpressionAttributeValues={
                    ':writes': serialized_writes,
                    ':empty_list': []
                }
            )

            logger.debug(f"Stored {len(writes)} writes for checkpoint {checkpoint_id}")

        except ClientError as e:
            logger.error(f"DynamoDB put_writes error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in put_writes: {e}")
            raise

    def delete_thread(self, thread_id: str) -> None:
        """Delete all checkpoints for a thread.

        Args:
            thread_id: The thread ID whose checkpoints should be deleted
        """
        try:
            # Query all items for this thread
            response = self.table.query(
                KeyConditionExpression=Key('thread_id').eq(thread_id),
                ProjectionExpression='thread_id, sort_key'
            )

            # Delete each item
            with self.table.batch_writer() as batch:
                for item in response.get('Items', []):
                    batch.delete_item(
                        Key={
                            'thread_id': item['thread_id'],
                            'sort_key': item['sort_key']
                        }
                    )

            logger.info(f"Deleted {len(response.get('Items', []))} checkpoints for thread {thread_id}")

        except ClientError as e:
            logger.error(f"DynamoDB delete_thread error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in delete_thread: {e}")
            raise

    # Async methods (not implemented - fall back to sync versions)
    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Async version - not implemented, falls back to sync."""
        return self.get_tuple(config)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Async version - not implemented, falls back to sync."""
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Async version - not implemented, falls back to sync."""
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Async version - not implemented, falls back to sync."""
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        """Async version - not implemented, falls back to sync."""
        self.delete_thread(thread_id)
