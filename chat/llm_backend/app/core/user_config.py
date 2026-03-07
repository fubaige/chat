"""
用户级别配置获取工具
LLM 服务调用时，优先使用用户自己配置的 API Key 等参数
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.logger import get_logger

logger = get_logger(service="user_config")

# 用户必须配置才能使用的关键 key
REQUIRED_USER_KEYS = {
    "deepseek": ["DEEPSEEK_API_KEY"],
    "gemini": ["GEMINI_API_KEY"],
    "search": ["SERPAPI_KEY"],
    "embedding": ["DASHSCOPE_API_KEY"],  # dashscope 类型时必须配置
}

# 知识库上传所需的配置检查
KNOWLEDGE_BASE_REQUIRED_KEYS = ["EMBEDDING_TYPE", "DASHSCOPE_API_KEY"]


async def get_user_setting(user_id: int, key: str, db: AsyncSession) -> Optional[str]:
    """获取用户的某个配置值，不存在则返回 None"""
    from app.models.user_settings import UserSettings
    result = await db.execute(
        select(UserSettings).where(
            UserSettings.user_id == user_id,
            UserSettings.key == key
        )
    )
    row = result.scalar_one_or_none()
    return row.value if row and row.value else None


async def get_user_settings_dict(user_id: int, db: AsyncSession) -> dict:
    """获取用户所有配置，返回 {key: value} 字典"""
    from app.models.user_settings import UserSettings
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    return {r.key: r.value for r in result.scalars().all() if r.value}


async def check_user_config_ready(user_id: int, service: str, db: AsyncSession) -> tuple[bool, str]:
    """
    检查用户是否已配置指定服务的必要参数
    返回 (is_ready, error_message)
    """
    required_keys = REQUIRED_USER_KEYS.get(service, [])
    if not required_keys:
        return True, ""

    user_cfg = await get_user_settings_dict(user_id, db)
    missing = [k for k in required_keys if not user_cfg.get(k)]

    if missing:
        label_map = {
            "DEEPSEEK_API_KEY": "DeepSeek API Key",
            "GEMINI_API_KEY": "Gemini API Key",
            "SERPAPI_KEY": "SerpAPI Key",
        }
        missing_labels = [label_map.get(k, k) for k in missing]
        return False, f"请先在【系统配置】中配置：{', '.join(missing_labels)}"

    return True, ""


def build_user_llm_config(user_cfg: dict, global_settings) -> dict:
    """
    合并用户配置和全局配置，用户配置优先
    返回可直接用于初始化 LLM 的参数字典
    """
    return {
        "deepseek_api_key": user_cfg.get("DEEPSEEK_API_KEY") or getattr(global_settings, "DEEPSEEK_API_KEY", ""),
        "deepseek_base_url": user_cfg.get("DEEPSEEK_BASE_URL") or getattr(global_settings, "DEEPSEEK_BASE_URL", ""),
        "deepseek_model": user_cfg.get("DEEPSEEK_MODEL") or getattr(global_settings, "DEEPSEEK_MODEL", ""),
        "gemini_api_key": user_cfg.get("GEMINI_API_KEY") or getattr(global_settings, "GEMINI_API_KEY", ""),
        "gemini_base_url": user_cfg.get("GEMINI_BASE_URL") or getattr(global_settings, "GEMINI_BASE_URL", ""),
        "serpapi_key": user_cfg.get("SERPAPI_KEY") or getattr(global_settings, "SERPAPI_KEY", ""),
        "search_result_count": int(user_cfg.get("SEARCH_RESULT_COUNT") or getattr(global_settings, "SEARCH_RESULT_COUNT", 3)),
    }


async def check_knowledge_base_config_ready(user_id: int, db: AsyncSession, is_admin: bool = False) -> tuple[bool, str]:
    """
    检查用户是否已配置知识库上传所需的 Embedding 参数。
    - 管理员：检查全局 system_settings
    - 普通用户：优先检查用户自己的 user_settings，回退到全局配置
    返回 (is_ready, error_message)
    """
    from app.models.system_settings import SystemSettings
    from sqlalchemy import select

    user_cfg = await get_user_settings_dict(user_id, db)

    # 获取全局配置作为回退
    result = await db.execute(select(SystemSettings))
    sys_map = {r.key: r.value for r in result.scalars().all()}

    def get_val(key: str) -> str:
        return user_cfg.get(key) or sys_map.get(key) or ""

    embedding_type = get_val("EMBEDDING_TYPE")
    dashscope_key = get_val("DASHSCOPE_API_KEY")

    missing = []

    if not embedding_type:
        missing.append("Embedding 类型")

    # dashscope 模式必须有 API Key
    if (not embedding_type or embedding_type == "dashscope") and not dashscope_key:
        missing.append("阿里百炼 Embedding API Key（DASHSCOPE_API_KEY）")

    if missing:
        return False, f"请先在【系统设置 → Embedding 向量】中配置：{', '.join(missing)}"

    return True, ""
