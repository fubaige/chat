import uuid
import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text

# 数据库连接（容器内使用 mysql 主机名）
DB_URL = "mysql+pymysql://chat_aigcqun_cn:f6WzA5XenzCPh4wS@mysql:3306/chat_aigcqun_cn"
engine = create_engine(DB_URL)

def check():
    with engine.connect() as conn:
        # 1. 检查 item 96
        result = conn.execute(text("SELECT id, user_id, original_name, status FROM knowledge_base WHERE id = 96"))
        row = result.fetchone()
        if row:
            item_id, user_id, name, status = row
            print(f"--- DB Record 96 ---")
            print(f"ID: {item_id}, UserID: {user_id}, Name: {name}, Status: {status}")
            
            # 2. 计算预期 UUID
            expected_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{user_id}"))
            print(f"Expected UUID (user_{user_id}): {expected_uuid}")
            
            # 3. 检查物理目录
            base_dir = "/app/app/graphrag/data/output"
            expected_path = os.path.join(base_dir, expected_uuid, str(item_id))
            print(f"Expected Path: {expected_path}")
            print(f"Path exists: {os.path.exists(expected_path)}")
            
            if os.path.exists(expected_path):
                print(f"Contents of {expected_path}: {os.listdir(expected_path)}")
                
            # 4. 列出 output 下所有文件夹
            if os.path.exists(base_dir):
                print(f"\nExisting folders in {base_dir}:")
                for d in os.listdir(base_dir):
                    if os.path.isdir(os.path.join(base_dir, d)):
                        print(f"  - {d}")
        else:
            print("Record 96 not found in DB")

if __name__ == "__main__":
    check()
