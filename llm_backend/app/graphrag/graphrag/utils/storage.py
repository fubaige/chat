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
    """Write a table to storage with robust type enforcement and sanitization."""
    import numpy as np
    import ast
    
    def robust_list_sanitizer(x):
        """确保返回值必然是一个 list[str]"""
        # 0. 首先排除列表/数组类型，防止 pd.isna 报错 (ambiguous truth value)
        if isinstance(x, (list, tuple, np.ndarray)):
            return [str(i) for i in x]
            
        if x is None or pd.isna(x):
            return []
        
        # 2. 处理字符串形式的列表 "['a', 'b']" 或 '["a", "b"]'
        if isinstance(x, str):
            trimmed = x.strip()
            if trimmed.startswith('[') and trimmed.endswith(']'):
                try:
                    # 尝试解析字符串列表
                    import json
                    try:
                        parsed = json.loads(trimmed.replace("'", '"'))
                    except:
                        parsed = ast.literal_eval(trimmed)
                    
                    if isinstance(parsed, (list, tuple)):
                        return [str(i) for i in parsed]
                except:
                    pass
            # 如果不是列表字符串，或者解析失败，当作单值处理
            if trimmed:
                return [trimmed]
            return []
            
        # 3. 其他单值情况，包装进列表
        return [str(x)]

    try:
        # 识别关键的列表列
        list_cols = [c for c in table.columns if c.endswith("_ids") or c in ["entity_ids", "relationship_ids", "covariate_ids", "sources", "text_unit_ids", "document_ids"]]
        
        for col in list_cols:
            try:
                table[col] = table[col].apply(robust_list_sanitizer)
            except Exception as col_e:
                log.debug("Column sanitization failed for %s: %s", col, col_e)
            
        await storage.set(f"{name}.parquet", table.to_parquet())
    except Exception as e:
        log.warning("Final parquet write failed for %s, attempting emergency stringification: %s", name, e)
        # 最后的挣扎：如果列表格式还是过不去（比如 PyArrow 内部元数据冲突），将所有 object 列强转为字符串
        for col in table.select_dtypes(include=['object']).columns:
            try:
                table[col] = table[col].apply(lambda x: str(x) if pd.notna(x) else "")
            except:
                pass
        
        try:
            await storage.set(f"{name}.parquet", table.to_parquet())
            log.info("Parquet write recovered for %s after emergency stringification", name)
        except Exception as retry_e:
            log.error("Parquet write CRITICALLY FAILED for %s: %s", name, retry_e)
            raise


async def delete_table_from_storage(name: str, storage: PipelineStorage) -> None:
    """Delete a table to storage."""
    await storage.delete(f"{name}.parquet")


async def storage_has_table(name: str, storage: PipelineStorage) -> bool:
    """Check if a table exists in storage."""
    return await storage.has(f"{name}.parquet")
