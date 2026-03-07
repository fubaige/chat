from typing import Union, Optional
from app.core.config import settings, ServiceType
from app.services.deepseek_service import DeepseekService
from app.services.search_service import SearchService


class LLMFactory:
    @staticmethod
    def create_chat_service(user_cfg: Optional[dict] = None):
        """创建聊天服务实例，user_cfg 优先于全局配置"""
        if user_cfg:
            return DeepseekService(
                api_key=user_cfg.get("DEEPSEEK_API_KEY"),
                base_url=user_cfg.get("DEEPSEEK_BASE_URL"),
                model_name=user_cfg.get("DEEPSEEK_MODEL"),
            )
        return DeepseekService()

    @staticmethod
    def create_reasoner_service(user_cfg: Optional[dict] = None):
        """创建推理服务实例"""
        if user_cfg:
            return DeepseekService(
                api_key=user_cfg.get("DEEPSEEK_API_KEY"),
                base_url=user_cfg.get("DEEPSEEK_BASE_URL"),
                model_name=user_cfg.get("DEEPSEEK_MODEL"),
            )
        return DeepseekService()

    @staticmethod
    def create_search_service(user_cfg: Optional[dict] = None):
        """创建搜索服务实例"""
        return SearchService(user_cfg=user_cfg)

    @staticmethod
    def create_llm(user_cfg: Optional[dict] = None):
        """创建通用 LLM 实例（供 WechatService 等调用）"""
        if user_cfg:
            return DeepseekService(
                api_key=user_cfg.get("DEEPSEEK_API_KEY"),
                base_url=user_cfg.get("DEEPSEEK_BASE_URL"),
                model_name=user_cfg.get("DEEPSEEK_MODEL"),
            )
        return DeepseekService()