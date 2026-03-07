"""删除旧的 2048 维向量库，准备重新索引为 1024 维"""
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
    print(f"\n删除旧的 2048 维 lancedb 向量库...")
    try:
        shutil.rmtree(lancedb_dir)
        print(f"✅ 删除成功")
    except Exception as e:
        print(f"❌ 删除失败: {e}")
        exit(1)
else:
    print(f"\nlancedb 不存在，无需删除")

print(f"\n✅ 准备完成！")
print(f"\n接下来需要重新索引知识库（使用 1024 维 embedding）：")
print(f"方法1：通过 API 重新上传文档触发索引")
print(f"方法2：手动运行索引命令：")
print(f"  cd llm_backend/app/graphrag/data")
print(f"  python -m graphrag index --root .")
print(f"\n注意：索引完成后，向量检索将使用 1024 维，与查询时的维度一致")
