# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Storage functions for the GraphRAG run module."""

import logging
from io import BytesIO

import pandas as pd

from graphrag.storage.pipeline_storage import PipelineStorage

log = logging.getLogger(__name__)


async def load_table_from_storage(name: str, storage: PipelineStorage) -> pd.DataFrame:
    """Load a parquet from the storage instance."""
    filename = f"{name}.parquet"
    if not await storage.has(filename):
        msg = f"Could not find {filename} in storage!"
        raise ValueError(msg)
    try:
        log.info("reading table from storage: %s", filename)
        return pd.read_parquet(BytesIO(await storage.get(filename, as_bytes=True)))
    except Exception:
        log.exception("error loading table from storage: %s", filename)
        raise


async def write_table_to_storage(
    table: pd.DataFrame, name: str, storage: PipelineStorage
) -> None:
    """Write a table to storage with Arrow durability fix."""
    try:
        # 【全栈专家补丁】修复 PyArrow 在处理嵌套列表（如 entity_ids）时的类型推导错误
        # 强制将 entity_ids 转换为标准的 list[str]，避免混合类型导致 ArrowInvalid
        if "entity_ids" in table.columns:
            table["entity_ids"] = table["entity_ids"].apply(
                lambda x: [str(i) for i in x] if isinstance(x, (list, tuple)) else []
            )
            
        await storage.set(f"{name}.parquet", table.to_parquet())
    except Exception as e:
        log.warning("Initial parquet write failed for %s, attempting sanitization: %s", name, e)
        # 深度清洗所有 object 列，确保没有无法识别的 Python 对象
        for col in table.select_dtypes(include=['object']).columns:
            try:
                table[col] = table[col].apply(lambda x: str(x) if not isinstance(x, (list, tuple, dict)) else x)
            except:
                pass
        await storage.set(f"{name}.parquet", table.to_parquet())


async def delete_table_from_storage(name: str, storage: PipelineStorage) -> None:
    """Delete a table to storage."""
    await storage.delete(f"{name}.parquet")


async def storage_has_table(name: str, storage: PipelineStorage) -> bool:
    """Check if a table exists in storage."""
    return await storage.has(f"{name}.parquet")
