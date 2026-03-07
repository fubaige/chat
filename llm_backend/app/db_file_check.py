import uuid
import os
import sys
import asyncio
from pathlib import Path

# 设置模块搜索路径，确保能导入 app
sys.path.append("/app")

async def check():
    try:
        from app.core.config import settings
        from app.core.database import AsyncSessionLocal
        from app.models.knowledge_base import KnowledgeBase
        from sqlalchemy import select
        
        print(f"--- Settings Check ---")
        print(f"GRAPHRAG_PROJECT_DIR: {settings.GRAPHRAG_PROJECT_DIR}")
        print(f"GRAPHRAG_DATA_DIR: {settings.GRAPHRAG_DATA_DIR}")
        
        async with AsyncSessionLocal() as session:
            # 1. 检查 item 96
            result = await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == 96))
            item = result.scalar_one_or_none()
            if item:
                print(f"\n--- DB Record 96 ---")
                print(f"ID: {item.id}, UserID: {item.user_id}, Name: {item.original_name}, Status: {item.status}")
                
                # 2. 计算预期 UUID
                user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{item.user_id}"))
                print(f"Expected UUID (user_{item.user_id}): {user_uuid}")
                
                # 3. 按照 main.py 的逻辑拼接路径
                project_dir = settings.GRAPHRAG_PROJECT_DIR
                data_dir = settings.GRAPHRAG_DATA_DIR
                output_dir = os.path.join(project_dir, data_dir, "output", user_uuid, str(item.id))
                print(f"Expected Main.py Path: {output_dir}")
                print(f"Path exists: {os.path.exists(output_dir)}")
                
                if os.path.exists(output_dir):
                    print(f"Contents: {os.listdir(output_dir)}")
                
                # 4. 暴力搜索 output 目录
                base_output = os.path.join(project_dir, data_dir, "output")
                print(f"\n--- Output Directory Scan [{base_output}] ---")
                if os.path.exists(base_output):
                    for d in os.listdir(base_output):
                        d_path = os.path.join(base_output, d)
                        if os.path.isdir(d_path):
                            print(f"User Folder: {d}")
                            # 看看里面有没有 96
                            sub_path = os.path.join(d_path, "96")
                            if os.path.exists(sub_path):
                                print(f"  FOUND ID 96 in {d}!")
            else:
                print("Record 96 not found in DB")
    except Exception as e:
        print(f"Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check())
