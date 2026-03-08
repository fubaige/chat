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
        # 这能解决 PyArrow 嵌套列表类型推断失败（mixed types）的问题
        # 常见受影响列：entity_ids, relationship_ids, covariate_ids, sources, text_unit_ids
        id_cols = [c for c in table.columns if c.endswith("_ids") or c in ["entity_ids", "relationship_ids", "covariate_ids", "sources", "text_unit_ids", "document_ids"]]
        
        for col in id_cols:
            try:
                # 严格转换逻辑：
                # 1. 如果是列表/元组，强制转为 list[str]
                # 2. 如果是单值（如字符串或ID），包装进列表 [str(x)]
                # 3. 如果是空值，转为空列表 []
                # 最终确保该列所有行都是真正的列表对象，且元数据保持一致
                table[col] = table[col].apply(
                    lambda x: [str(i) for i in x] if isinstance(x, (list, tuple)) 
                    else ([str(x)] if pd.notna(x) and str(x).strip() != "" else [])
                )
            except Exception as col_e:
                log.debug("Column sanitization skipped for %s: %s", col, col_e)
            
        await storage.set(f"{name}.parquet", table.to_parquet())
    except Exception as e:
        log.warning("Initial parquet write failed for %s, attempting aggressive sanitization: %s", name, e)
        # 深度清洗：对所有非数值列执行激进转换
        for col in table.select_dtypes(include=['object']).columns:
            try:
                # 更加决断的规则：只要是 object 类型，要么是合法的列表字符串，要么全部转为字符串
                table[col] = table[col].apply(
                    lambda x: [str(i) for i in x] if isinstance(x, (list, tuple)) 
                    else (str(x) if pd.notna(x) else "")
                )
            except:
                pass
        
        try:
            await storage.set(f"{name}.parquet", table.to_parquet())
            log.info("Parquet write recovered for %s after aggressive sanitization", name)
        except Exception as retry_e:
            log.error("Parquet write FAILED even after sanitization for %s: %s", name, retry_e)
            # 输出详细列信息用于调试
            for c in table.columns:
                log.error("Column %s dtype: %s, sample: %s", c, table[c].dtype, str(table[c].iloc[0])[:100] if len(table) > 0 else "None")
            raise


async def delete_table_from_storage(name: str, storage: PipelineStorage) -> None:
    """Delete a table to storage."""
    await storage.delete(f"{name}.parquet")


async def storage_has_table(name: str, storage: PipelineStorage) -> bool:
    """Check if a table exists in storage."""
    return await storage.has(f"{name}.parquet")
