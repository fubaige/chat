import os
import json
import asyncio
from typing import List, Dict, Any, AsyncGenerator
from pathlib import Path

# import graphrag.api as api
# from graphrag.config.load_config import load_config

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(service="rag_chat")

class RAGChatService:
    def __init__(self):
        self.project_dir = settings.GRAPHRAG_PROJECT_DIR
        self.data_dir = os.path.join(self.project_dir, settings.GRAPHRAG_DATA_DIR)
        
    def _load_graphrag_env(self):
        """加载 GraphRAG 专用的环境变量"""
        env_path = os.path.join(self.data_dir, ".env")
        if os.path.exists(env_path):
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path, override=True)
            except Exception as e:
                logger.error(f"加载 GraphRAG 环境变量失败: {e}")
        
    async def generate_stream(self, messages: List[Dict[str, str]], index_id: str) -> AsyncGenerator[str, None]:
        """基于文档索引生成流式回复"""
        try:
            query = messages[-1]["content"]
            logger.info(f"RAG query: {query} for index: {index_id}")
            
            # 准备配置和索引路径
            # 假设 index_id 是用户的 UUID
            user_output_dir = os.path.join(self.data_dir, "output", index_id)
            if not os.path.exists(user_output_dir):
                logger.error(f"Index directory not found: {user_output_dir}")
                yield f"data: {json.dumps('抱歉，找不到对应的知识库索引。', ensure_ascii=False)}\n\n"
                return

            # 延迟导入 GraphRAG 核心模块
            import graphrag.api as api
            from graphrag.config.load_config import load_config

            # 确保环境变量已加载
            self._load_graphrag_env()

            # 加载配置
            config_path = os.path.join(self.data_dir, "settings.yaml")
            graphrag_config = load_config(Path(self.data_dir), Path(config_path))
            
            # 使用 graphrag API 进行查询（local 模式，速度快）
            # global 模式已禁用：需要对全量 community reports 做 Map-Reduce，耗时 30-60s
            
            logger.info("Executing Local Search via GraphRAG...")
            
            # 注意：graphrag 的标准 API 可能不支持直接流式返回，
            # 如果不支持，我们只能先获取全文再模拟流。
            
            result, context = await api.local_search(
                config=graphrag_config,
                nodes_dir=Path(user_output_dir),
                community_level=2,
                query=query
            )
            
            # 模拟流输出
            if result:
                # 简单地按字符或段落模拟流式输出
                chunk_size = 10
                for i in range(0, len(result), chunk_size):
                    chunk = result[i:i+chunk_size]
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)
                yield "data: [DONE]\n\n"
            else:
                yield f"data: {json.dumps('未能在知识库中找到相关信息。', ensure_ascii=False)}\n\n"
                
        except Exception as e:
            logger.error(f"RAG generation failed: {str(e)}", exc_info=True)
            yield f"data: {json.dumps(f'抱歉，知识库查询出错: {str(e)}', ensure_ascii=False)}\n\n"
