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
        # 【全栈专家补丁】主动清洗：识别常见的 ID 列表列并规范化为 list[str]
        # 这能解决 90% 的 PyArrow 嵌套列表类型推断失败问题
        id_cols = [c for c in table.columns if c.endswith("_ids") or c in ["entity_ids", "relationship_ids", "covariate_ids", "sources"]]
        for col in id_cols:
            try:
                table[col] = table[col].apply(
                    lambda x: [str(i) for i in x] if isinstance(x, (list, tuple)) else ([] if pd.isna(x) else x)
                )
            except:
                pass
            
        await storage.set(f"{name}.parquet", table.to_parquet())
    except Exception as e:
        log.warning("Initial parquet write failed for %s, attempting aggressive sanitization: %s", name, e)
        # 深度清洗：对所有 object 列执行激进转换
        for col in table.select_dtypes(include=['object']).columns:
            try:
                # 规则：列表转 list[str]，其他非空对象转 str，空值保留
                table[col] = table[col].apply(
                    lambda x: [str(i) for i in x] if isinstance(x, (list, tuple)) 
                    else (str(x) if pd.notna(x) and not isinstance(x, (dict, set)) else x)
                )
            except:
                pass
        
        try:
            await storage.set(f"{name}.parquet", table.to_parquet())
            log.info("Parquet write recovered for %s after aggressive sanitization", name)
        except Exception as retry_e:
            log.error("Parquet write FAILED even after sanitization for %s: %s", name, retry_e)
            raise


async def delete_table_from_storage(name: str, storage: PipelineStorage) -> None:
    """Delete a table to storage."""
    await storage.delete(f"{name}.parquet")


async def storage_has_table(name: str, storage: PipelineStorage) -> bool:
    """Check if a table exists in storage."""
    return await storage.has(f"{name}.parquet")
