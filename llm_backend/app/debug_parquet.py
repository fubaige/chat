import pandas as pd
import os
import sys

# 探测 ID 为 97 的文档（最新生成的）
path = "/app/app/graphrag/data/output/5d417677-9436-5c5b-997a-a3d989d9abbd/97/documents.parquet"
if os.path.exists(path):
    df = pd.read_parquet(path)
    print("--- Documents Table ---")
    print(df[['id', 'title', 'raw_content_path']].to_string())
else:
    print(f"File not found: {path}")

# 探测 text_units
tu_path = "/app/app/graphrag/data/output/5d417677-9436-5c5b-997a-a3d989d9abbd/97/text_units.parquet"
if os.path.exists(tu_path):
    df_tu = pd.read_parquet(tu_path)
    print("\n--- Text Units Table (First 2) ---")
    print(df_tu[['id', 'document_ids']].head(2).to_string())
else:
    print(f"Text units not found: {tu_path}")
