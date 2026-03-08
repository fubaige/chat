
import pandas as pd
import numpy as np
import io
import os

# 模拟 storage.py 中的清洗逻辑
def sanitize_table(table):
    id_cols = [c for c in table.columns if c.endswith("_ids") or c in ["entity_ids", "relationship_ids", "covariate_ids", "sources", "text_unit_ids", "document_ids"]]
    
    for col in id_cols:
        # 使用新的逻辑进行清洗
        table[col] = table[col].apply(
            lambda x: [str(i) for i in x] if isinstance(x, (list, tuple)) 
            else ([str(x)] if pd.notna(x) and str(x).strip() != "" else [])
        )
    return table

def test():
    # 构造一个会导致 PyArrow 推断失败的典型数据集：
    # entity_ids 列混合了：列表、单字符串、空值
    data = {
        "id": [1, 2, 3, 4, 5],
        "entity_ids": [
            ["uuid1", "uuid2"],     # 正常列表
            "uuid3",                # 单个字符串 (触发推断错误的关键)
            None,                   # 空值
            np.nan,                 # NaN
            ["uuid4"]               # 另一个列表
        ]
    }
    
    df = pd.DataFrame(data)
    print("原始数据 (预览):")
    print(df)
    
    # 尝试直接转 parquet (预计在某些版本的 pyarrow 中会失败，或者产生不可读的 object 类型)
    try:
        df.to_parquet("test_fail.parquet")
        print("直接写入 Parquet 成功 (但这不代表没有类型隐患)")
    except Exception as e:
        print(f"直接写入 Parquet 预期失败: {e}")

    # 调用清洗逻辑
    print("\n执行加固清洗逻辑...")
    df_clean = sanitize_table(df.copy())
    
    print("清洗后数据 (预览):")
    for i, val in enumerate(df_clean["entity_ids"]):
        print(f"Row {i}: {val} (type: {type(val)})")
        assert isinstance(val, list), f"Row {i} should be a list"
        if val:
            assert all(isinstance(item, str) for item in val), f"Row {i} items should be strings"

    # 尝试写入 parquet
    try:
        # 使用 BytesIO 模拟内存存储
        buffer = io.BytesIO()
        df_clean.to_parquet(buffer)
        print("\n[SUCCESS] 清洗后 Parquet 写入成功！PyArrow 类型推断正常。")
    except Exception as e:
        print(f"\n[FAILURE] 清洗后 Parquet 写入仍然失败: {e}")
        raise e

if __name__ == "__main__":
    test()
