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
    """Write a table to storage with Atomic Sanitization and type forcing."""
    import numpy as np
    import ast
    import json
    
    def atomic_list_unwrapper(x):
        """深度展开并规范化为 list[str]，安全处理 Pandas Extension Arrays"""
        if x is None:
            return []
            
        # 0. 标量且为空
        if pd.api.types.is_scalar(x) and pd.isna(x):
            return []
            
        # 1. 判断是否为容器 (非字符串、标量)，适配 Numpy Array 和 Pandas Series/ExtensionArray
        is_container = pd.api.types.is_list_like(x) and not isinstance(x, (str, bytes, dict))

        if is_container:
            # 统一转为原生 list，消除 DataFrame 内部特殊类型（如 ArrowStringArray）的副作用
            x_list = list(x)
            
            # 递归解包逻辑：如果是一个单元素的列表且里面是字符串形式的列表，先解包
            if len(x_list) == 1 and isinstance(x_list[0], str):
                inner = x_list[0].strip()
                if inner.startswith('[') and inner.endswith(']'):
                    x = inner
                    is_container = False # 已经变成字符串了，交由下面的逻辑处理
                else:
                    return [str(i) for i in x_list]
            else:
                return [str(i) for i in x_list]
        
        # 2. 处理字符串形式的列表 "['a', 'b']"
        if isinstance(x, str):
            trimmed = x.strip()
            if trimmed.startswith('[') and trimmed.endswith(']'):
                try:
                    try:
                        parsed = json.loads(trimmed.replace("'", '"'))
                    except:
                        parsed = ast.literal_eval(trimmed)
                    
                    if isinstance(parsed, (list, tuple)):
                        # 递归处理解析后的结果，防止多层嵌套
                        return [str(i) for i in (parsed if not isinstance(parsed, (list, tuple)) or len(parsed) != 1 or not isinstance(parsed[0], str) or not parsed[0].startswith('[') else atomic_list_unwrapper(parsed))]
                except:
                    pass
            if trimmed:
                return [trimmed]
            return []
            
        return [str(x)]

    try:
        # 1. 识别关键列
        list_cols = [c for c in table.columns if c.endswith("_ids") or c in ["entity_ids", "relationship_ids", "covariate_ids", "sources", "text_unit_ids", "document_ids"]]
        text_cols = [c for c in table.columns if c in ["id", "text", "description", "name", "title"]]
        
        # 2. 执行原子级清洗
        for col in list_cols:
            table[col] = table[col].apply(atomic_list_unwrapper)
        
        for col in text_cols:
            if col in table.columns:
                table[col] = table[col].apply(lambda x: str(x) if pd.notna(x) else "")

        # 3. 强制显式转换数据类型为 object，消除 PyArrow 自动推断冲突
        # 重要：对于包含列表的列，必须显式声明为 object
        for col in table.columns:
            if col in list_cols:
                table[col] = table[col].astype(object)
            
        await storage.set(f"{name}.parquet", table.to_parquet())
    except Exception as e:
        log.warning("Atomic write failed for %s, attempting emergency flat stringification: %s", name, e)
        # 最终应急处理：平铺所有数据为字符串，宁可丢失列表结构也不让索引中断
        for col in table.columns:
            try:
                table[col] = table[col].apply(lambda x: str(x) if pd.notna(x) else "")
            except:
                pass
        
        try:
            await storage.set(f"{name}.parquet", table.to_parquet())
            log.info("Parquet write recovered for %s after emergency flat stringification", name)
        except Exception as retry_e:
            log.error("Parquet write CRITICALLY FAILED for %s: %s", name, retry_e)
            raise


async def delete_table_from_storage(name: str, storage: PipelineStorage) -> None:
    """Delete a table to storage."""
    await storage.delete(f"{name}.parquet")


async def storage_has_table(name: str, storage: PipelineStorage) -> bool:
    """Check if a table exists in storage."""
    return await storage.has(f"{name}.parquet")
