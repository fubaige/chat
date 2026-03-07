
import json
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import (
    Column,
    String,
    Text,
    LargeBinary,
    Integer,
    JSON,
    select,
    desc,
    and_,
    delete,
    update,
    insert,
    func
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import declarative_base

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.core.database import engine
from app.core.logger import get_logger

logger = get_logger(service="mysql_checkpointer")

Base = declarative_base()

class CheckpointModel(Base):
    __tablename__ = "checkpoints"
    
    thread_id = Column(String(255), primary_key=True)
    checkpoint_id = Column(String(255), primary_key=True)
    parent_checkpoint_id = Column(String(255), nullable=True)
    type = Column(String(255), nullable=True)
    checkpoint = Column(LargeBinary, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=False)

class CheckpointWriteModel(Base):
    __tablename__ = "checkpoint_writes"
    
    thread_id = Column(String(255), primary_key=True)
    checkpoint_id = Column(String(255), primary_key=True)
    task_id = Column(String(255), primary_key=True)
    idx = Column(Integer, primary_key=True)
    channel = Column(String(255), nullable=False)
    type = Column(String(255), nullable=True)
    value = Column(LargeBinary, nullable=False)

import asyncio
from functools import wraps
from sqlalchemy.exc import OperationalError

def retry_on_deadlock(retries=3, delay=0.1):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for i in range(retries):
                try:
                    return await func(*args, **kwargs)
                except OperationalError as e:
                    # Check for MySQL Deadlock error code 1213
                    if e.orig and e.orig.args and e.orig.args[0] == 1213:
                        last_exception = e
                        logger.warning(f"Deadlock detected in {func.__name__}, retrying {i+1}/{retries}...")
                        await asyncio.sleep(delay * (2 ** i)) # Exponential backoff
                    else:
                        raise e
            logger.error(f"Failed to execute {func.__name__} after {retries} retries due to deadlock.")
            raise last_exception
        return wrapper
    return decorator

class AsyncMySqlSaver(BaseCheckpointSaver):
    def __init__(
        self,
        engine: AsyncEngine,
        serde: Optional[SerializerProtocol] = None,
    ):
        super().__init__(serde=serde or JsonPlusSerializer())
        self.engine = engine

    async def ensure_tables(self):
        """Ensure the tables exist in the database."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """同步版本的 get_tuple，包装异步调用。
        LangGraph 的 graph.get_state() 会调用此同步方法。
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 已在异步上下文中，无法直接 asyncio.run
            # 创建新线程执行异步调用
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.aget_tuple(config))
                return future.result()
        else:
            return asyncio.run(self.aget_tuple(config))

    def list(
        self,
        config: RunnableConfig,
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ):
        """同步版本的 list，返回空列表以避免 NotImplementedError。"""
        return iter([])

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> RunnableConfig:
        """同步版本的 put，包装异步调用。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.aput(config, checkpoint, metadata, new_versions))
                return future.result()
        else:
            return asyncio.run(self.aput(config, checkpoint, metadata, new_versions))

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """同步版本的 put_writes，包装异步调用。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.aput_writes(config, writes, task_id))
                return future.result()
        else:
            return asyncio.run(self.aput_writes(config, writes, task_id))

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")
        
        async with self.engine.connect() as conn:
            if checkpoint_id:
                stmt = select(CheckpointModel).where(
                    and_(
                        CheckpointModel.thread_id == thread_id,
                        CheckpointModel.checkpoint_id == checkpoint_id
                    )
                )
            else:
                stmt = select(CheckpointModel).where(
                    CheckpointModel.thread_id == thread_id
                ).order_by(desc(CheckpointModel.checkpoint_id)).limit(1)
            
            result = await conn.execute(stmt)
            row = result.fetchone()
            
            if not row:
                return None
                
            # row: thread_id, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
            # indices might differ based on select, but ORM model fields are consistently ordered if selected as entity or specific columns
            # But here we used select(CheckpointModel), so unpacking might be needed carefully or access by attr if using scalars
            # adapting to raw execute result
            
            final_config = {
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_id": row.checkpoint_id,
                }
            }
            
            if row.parent_checkpoint_id:
                final_config["configurable"]["checkpoint_ns"] = config["configurable"].get("checkpoint_ns", "")
            
            checkpoint = self.serde.loads(row.checkpoint)
            metadata = row.metadata # Fix: access DB column name 'metadata' not Model attribute 'metadata_'
            parent_checkpoint_id = row.parent_checkpoint_id
            
            return CheckpointTuple(
                config=final_config,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_id": parent_checkpoint_id,
                    }
                } if parent_checkpoint_id else None,
            )

    async def alist(
        self,
        config: RunnableConfig,
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        
        stmt = select(CheckpointModel).where(CheckpointModel.thread_id == thread_id)
        
        if before:
            before_id = before["configurable"].get("checkpoint_id")
            if before_id:
                stmt = stmt.where(CheckpointModel.checkpoint_id < before_id)
                
        if filter:
            # Simple metadata filtering implementation
            for key, value in filter.items():
                stmt = stmt.where(func.json_extract(CheckpointModel.metadata_, f"$.{key}") == value)

        stmt = stmt.order_by(desc(CheckpointModel.checkpoint_id))
        
        if limit:
            stmt = stmt.limit(limit)
            
        async with self.engine.connect() as conn:
            result = await conn.execute(stmt)
            for row in result:
                checkpoint = self.serde.loads(row.checkpoint)
                yield CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": row.thread_id,
                            "checkpoint_id": row.checkpoint_id,
                        }
                    },
                    checkpoint=checkpoint,
                    metadata=row.metadata, # Fix: access DB column name 'metadata' not Model attribute 'metadata_'
                    parent_config={
                        "configurable": {
                            "thread_id": row.thread_id,
                            "checkpoint_id": row.parent_checkpoint_id,
                        }
                    } if row.parent_checkpoint_id else None,
                )

    @retry_on_deadlock()
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")
        
        checkpoint_blob = self.serde.dumps(checkpoint)
        
        # Prepare safe metadata
        safe_metadata = metadata
        try:
            # metadata might contain non-JSON serializable objects like AIMessage
            # self.serde (JsonPlusSerializer) can handle these objects
            # Convert to a dict of primitives by dumping and reloading
            serialized = self.serde.dumps(metadata)
            safe_metadata = json.loads(serialized)
        except Exception as e:
            logger.warning(f"Failed to serialize metadata with serde: {e}")

        async with self.engine.begin() as conn:
            # Upsert logic (Insert or Do Nothing usually for checkpoints as IDs are unique)
            # SQLAlchemy doesn't have a generic upsert, but checkpoints by ID shouldn't change.
            # We'll use insert().values()
            
            # Checkpoint
            stmt = select(CheckpointModel).where(
                and_(
                    CheckpointModel.thread_id == thread_id,
                    CheckpointModel.checkpoint_id == checkpoint_id
                )
            )
            existing = (await conn.execute(stmt)).fetchone()
            
            if not existing:
                await conn.execute(
                    insert(CheckpointModel).values(
                        thread_id=thread_id,
                        checkpoint_id=checkpoint_id,
                        parent_checkpoint_id=parent_checkpoint_id,
                        type="checkpoint", # default
                        checkpoint=checkpoint_blob,
                        metadata_=safe_metadata
                    )
                )
            else:
                 # Should we update? usually checkpoints are immutable.
                 pass
                 
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }
    
    @retry_on_deadlock()
    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        # Writes need to be atomic.
        # Instead of DELETE + INSERT which causes Gap Locks and Deadlocks in MySQL,
        # we use ON DUPLICATE KEY UPDATE (UPSERT).
        
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"]["checkpoint_id"]
        
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        
        async with self.engine.begin() as conn:
            for idx, (channel, value) in enumerate(writes):
                 value_blob = self.serde.dumps(value)
                 
                 # Prepare the insert statement
                 insert_stmt = mysql_insert(CheckpointWriteModel).values(
                     thread_id=thread_id,
                     checkpoint_id=checkpoint_id,
                     task_id=task_id,
                     idx=idx,
                     channel=channel,
                     type="write",
                     value=value_blob
                 )
                 
                 # On duplicate key, update the value and type (channel is usually same for same idx)
                 upsert_stmt = insert_stmt.on_duplicate_key_update(
                     channel=insert_stmt.inserted.channel,
                     type=insert_stmt.inserted.type,
                     value=insert_stmt.inserted.value
                 )
                 
                 await conn.execute(upsert_stmt)

_checkpointer_instance = None

async def init_checkpointer():
    """初始化全局 Single Instance 并确保表存在"""
    global _checkpointer_instance
    if _checkpointer_instance is None:
        _checkpointer_instance = AsyncMySqlSaver(engine)
        await _checkpointer_instance.ensure_tables()
        logger.info("Initialized MySQL checkpointer and ensured tables.")
    return _checkpointer_instance

def get_checkpointer():
    """
    返回全局实例。
    注意：在调用 graph.compile(checkpointer=...) 之前，必须确保 init_checkpointer 被 await 过。
    为了简化，我们可能需要在 main.py startup 时调用 init_checkpointer。
    而在 lg_builder.py 中，我们可能需要延迟获取或者返回 None 让 graph 在运行时处理？
    不，LangGraph 需要实例。
    
    Hack: 如果 _checkpointer_instance 是 None，这里无法同步等待。
    解决方案：在 main.py 的 startup event 中初始化。
    lg_builder.py 中的 global checkpointer 先设为 None?
    或者使用 Lazy Proxy?
    """
    return _checkpointer_instance
