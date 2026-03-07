"""重新索引知识库，确保 embedding 模型配置一致"""
import os
import shutil
from pathlib import Path

# admin 用户的知识库路径
storage_dir = Path(__file__).parent / "app" / "graphrag" / "data" / "output" / "adf3796a-f736-572d-a593-33a9a7f89e46"
lancedb_dir = storage_dir / "lancedb"

print(f"知识库路径: {storage_dir}")
print(f"lancedb 路径: {lancedb_dir}")
print(f"lancedb 是否存在: {lancedb_dir.exists()}")

if lancedb_dir.exists():
    print(f"\n删除旧的 lancedb 向量库...")
    try:
        shutil.rmtree(lancedb_dir)
        print(f"✅ 删除成功")
    except Exception as e:
        print(f"❌ 删除失败: {e}")
        exit(1)
else:
    print(f"\nlancedb 不存在，无需删除")

print(f"\n接下来需要重新运行索引命令：")
print(f"cd llm_backend/app/graphrag/data")
print(f"python -m graphrag index --root .")
print(f"\n或者通过 API 重新上传文档触发索引")
