import asyncio
import os
import sys

# 将当前目录加入路径以便导入 app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import AsyncSessionLocal
from app.models.system_settings import SystemSettings
from sqlalchemy import select, update

async def fix_config():
    configs = {
        "GRAPHRAG_API_BASE": "https://api.deepseek.com",
        "GRAPHRAG_API_KEY": "sk-2e2bb78d9e364f6e9e0acfc2aec95832",
        "GRAPHRAG_MODEL_NAME": "deepseek-chat",
        "Embedding_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "Embedding_API_KEY": "sk-d477ad3781f14f9db06c5995d89762f0",
        "Embedding_MODEL_NAME": "text-embedding-v4"
    }
    
    print("开始修复数据库中的 GraphRAG 配置...")
    
    async with AsyncSessionLocal() as session:
        for key, value in configs.items():
            # 检查是否存在
            result = await session.execute(select(SystemSettings).where(SystemSettings.key == key))
            item = result.scalar_one_or_none()
            
            if item:
                # 只有当值为空或者是默认占位符时才更新
                if not item.value or item.value == "":
                    print(f"更新 {key} -> {value[:8]}...")
                    item.value = value
                else:
                    print(f"跳过 {key} (已有值: {item.value[:8]}...)")
            else:
                print(f"找不到配置项 {key}，请确保服务已重启过一次以初始化表。")
        
        await session.commit()
    
    print("修复完成！请重启服务或稍等片刻让配置生效。")

if __name__ == "__main__":
    asyncio.run(fix_config())
