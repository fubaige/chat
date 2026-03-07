from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import logging
import os
import time

logger = logging.getLogger(__name__)

# 获取项目根目录
ROOT_DIR = Path(__file__).parent.parent.parent
ENV_FILE = ROOT_DIR / ".env"


class ServiceType(str, Enum):
    DEEPSEEK = "deepseek"


# .env 中所有配置项的元数据定义（分组、标签、类型、排序）
SETTINGS_META = [
    # --- DeepSeek ---
    {"key": "DEEPSEEK_API_KEY", "group": "deepseek", "label": "DeepSeek API Key", "type": "password", "sort": 1},
    {"key": "DEEPSEEK_BASE_URL", "group": "deepseek", "label": "DeepSeek API 地址", "type": "string", "sort": 2},
    {"key": "DEEPSEEK_MODEL", "group": "deepseek", "label": "DeepSeek 模型名称", "type": "string", "sort": 3},
    # --- Gemini ---
    {"key": "GEMINI_API_KEY", "group": "gemini", "label": "Gemini API Key", "type": "password", "sort": 10},
    {"key": "GEMINI_BASE_URL", "group": "gemini", "label": "Gemini 图片解析模型", "type": "select", "options": ["gemini-3.1-pro-preview", "gemini-3-flash-preview"], "sort": 11},
    {"key": "GEMINI_IMAGE_GEN_URL", "group": "gemini", "label": "Gemini 图片生成模型", "type": "select", "options": ["gemini-3-pro-image-preview", "gemini-2.5-flash-image-preview"], "sort": 12},
    # --- 通义千问视觉（多模态第二模型） ---
    {"key": "QWEN_VISION_MODEL", "group": "qwen_vision", "label": "通义千问视觉模型", "type": "select", "options": ["qwen3.5-flash", "qwen3.5-plus"], "sort": 14},
    # --- 服务选择 ---
    {"key": "CHAT_SERVICE", "group": "service", "label": "对话服务", "type": "string", "sort": 20},
    {"key": "REASON_SERVICE", "group": "service", "label": "推理服务", "type": "string", "sort": 21},
    {"key": "AGENT_SERVICE", "group": "service", "label": "Agent 服务", "type": "string", "sort": 22},
    # --- 搜索 ---
    {"key": "SERPAPI_KEY", "group": "search", "label": "SerpAPI Key", "type": "password", "sort": 30},
    {"key": "SEARCH_RESULT_COUNT", "group": "search", "label": "搜索结果数量", "type": "int", "sort": 31},
    # --- 数据库 ---
    {"key": "DB_HOST", "group": "database", "label": "数据库主机", "type": "string", "sort": 40},
    {"key": "DB_PORT", "group": "database", "label": "数据库端口", "type": "int", "sort": 41},
    {"key": "DB_USER", "group": "database", "label": "数据库用户名", "type": "string", "sort": 42},
    {"key": "DB_PASSWORD", "group": "database", "label": "数据库密码", "type": "password", "sort": 43},
    {"key": "DB_NAME", "group": "database", "label": "数据库名称", "type": "string", "sort": 44},
    # --- Neo4j 主实例（结构化知识图谱）---
    {"key": "NEO4J_URL", "group": "neo4j", "label": "Neo4j 地址（结构化）", "type": "string", "sort": 50},
    {"key": "NEO4J_USERNAME", "group": "neo4j", "label": "Neo4j 用户名（结构化）", "type": "string", "sort": 51},
    {"key": "NEO4J_PASSWORD", "group": "neo4j", "label": "Neo4j 密码（结构化）", "type": "password", "sort": 52},
    {"key": "NEO4J_DATABASE", "group": "neo4j", "label": "Neo4j 数据库（结构化）", "type": "string", "sort": 53},
    # --- Neo4j 第二实例（非结构化文档知识图谱，可选）---
    {"key": "NEO4J_UNSTRUCTURED_URL", "group": "neo4j", "label": "Neo4j 地址（非结构化，可选）", "type": "string", "sort": 54},
    {"key": "NEO4J_UNSTRUCTURED_USERNAME", "group": "neo4j", "label": "Neo4j 用户名（非结构化）", "type": "string", "sort": 55},
    {"key": "NEO4J_UNSTRUCTURED_PASSWORD", "group": "neo4j", "label": "Neo4j 密码（非结构化）", "type": "password", "sort": 56},
    {"key": "NEO4J_UNSTRUCTURED_DATABASE", "group": "neo4j", "label": "Neo4j 数据库（非结构化）", "type": "string", "sort": 57},
    # --- Redis ---
    {"key": "REDIS_HOST", "group": "redis", "label": "Redis 主机", "type": "string", "sort": 60},
    {"key": "REDIS_PORT", "group": "redis", "label": "Redis 端口", "type": "int", "sort": 61},
    {"key": "REDIS_DB", "group": "redis", "label": "Redis DB", "type": "int", "sort": 62},
    {"key": "REDIS_PASSWORD", "group": "redis", "label": "Redis 密码", "type": "password", "sort": 63},
    {"key": "REDIS_CACHE_EXPIRE", "group": "redis", "label": "缓存过期时间(秒)", "type": "int", "sort": 64},
    {"key": "REDIS_CACHE_THRESHOLD", "group": "redis", "label": "缓存相似度阈值", "type": "float", "sort": 65},
    # --- JWT ---
    {"key": "SECRET_KEY", "group": "jwt", "label": "JWT 密钥", "type": "password", "sort": 70},
    {"key": "ALGORITHM", "group": "jwt", "label": "JWT 算法", "type": "string", "sort": 71},
    {"key": "ACCESS_TOKEN_EXPIRE_MINUTES", "group": "jwt", "label": "Token 过期时间(分钟)", "type": "int", "sort": 72},
    # --- MinerU ---
    {"key": "MINERU_API_TOKEN", "group": "mineru", "label": "MinerU API Token", "type": "password", "sort": 78},
    {"key": "SERVER_BASE_URL", "group": "mineru", "label": "服务器公网地址（自动检测）", "type": "readonly_auto", "sort": 79},
    # --- Embedding ---
    {"key": "EMBEDDING_TYPE", "group": "embedding", "label": "Embedding 类型", "type": "readonly", "options": ["dashscope"], "sort": 80},
    {"key": "EMBEDDING_MODEL", "group": "embedding", "label": "Embedding 模型", "type": "string", "sort": 81},
    {"key": "EMBEDDING_THRESHOLD", "group": "embedding", "label": "Embedding 相似度阈值", "type": "float", "sort": 82},
    {"key": "DASHSCOPE_API_KEY", "group": "embedding", "label": "阿里百炼 Embedding API Key", "type": "password", "sort": 83},
    # --- 服务间通信 ---
    {"key": "INTERNAL_API_KEY", "group": "internal", "label": "内部 API 密钥（≥32字符）", "type": "password", "sort": 85},
    {"key": "BETTER_AUTH_SECRET", "group": "internal", "label": "better-auth JWT 密钥", "type": "password", "sort": 86},
    # --- GraphRAG ---
    {"key": "GRAPHRAG_PROJECT_DIR", "group": "graphrag", "label": "GraphRAG 项目目录", "type": "string", "sort": 90},
    {"key": "GRAPHRAG_DATA_DIR", "group": "graphrag", "label": "GraphRAG 数据目录", "type": "string", "sort": 91},
    {"key": "GRAPHRAG_QUERY_TYPE", "group": "graphrag", "label": "GraphRAG 查询类型", "type": "string", "sort": 92},
    {"key": "GRAPHRAG_RESPONSE_TYPE", "group": "graphrag", "label": "GraphRAG 响应类型", "type": "string", "sort": 93},
    {"key": "GRAPHRAG_COMMUNITY_LEVEL", "group": "graphrag", "label": "GraphRAG 社区级别", "type": "int", "sort": 94},
    {"key": "GRAPHRAG_DYNAMIC_COMMUNITY", "group": "graphrag", "label": "动态社区选择", "type": "bool", "sort": 95},
]

# 分组显示名称
GROUP_LABELS = {
    "deepseek": "DeepSeek 模型配置",
    "gemini": "Gemini 视觉配置",
    "qwen_vision": "通义千问视觉配置（多模态第二模型）",
    "service": "服务选择",
    "search": "联网搜索配置",
    "database": "PostgreSQL 数据库",
    "neo4j": "Neo4j 图数据库",
    "redis": "Redis 缓存",
    "jwt": "JWT 认证",
    "mineru": "MinerU 文档解析",
    "embedding": "Embedding 向量",
    "graphrag": "GraphRAG 知识图谱",
    "internal": "服务间通信",
}

# 普通用户可以独立配置的分组（不含数据库等系统级配置）
USER_CONFIGURABLE_GROUPS = {"deepseek", "gemini", "search", "jwt", "mineru", "embedding"}

# 普通用户可配置的 key 集合（从 SETTINGS_META 中过滤）
USER_CONFIGURABLE_KEYS = {
    m["key"] for m in SETTINGS_META if m["group"] in USER_CONFIGURABLE_GROUPS
}


class Settings(BaseSettings):
    """从 .env 加载的初始配置（仅用于首次启动和数据库连接）"""
    # Deepseek settings
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # Gemini settings
    GEMINI_API_KEY: str = ""
    GEMINI_BASE_URL: str = "gemini-3.1-pro-preview"
    GEMINI_IMAGE_GEN_URL: str = "gemini-3-pro-image-preview"

    # 通义千问视觉模型（多模态第二模型，使用阿里云百炼 DASHSCOPE_API_KEY）
    QWEN_VISION_MODEL: str = "qwen3.5-flash"

    @property
    def GEMINI_PARSE_URL(self) -> str:
        return f"https://api.kuai.host/v1beta/models/{self.GEMINI_BASE_URL}:generateContent"

    @property
    def GEMINI_GEN_URL(self) -> str:
        return f"https://api.kuai.host/v1beta/models/{self.GEMINI_IMAGE_GEN_URL}:generateContent"

    # Service selection
    CHAT_SERVICE: ServiceType = ServiceType.DEEPSEEK
    REASON_SERVICE: ServiceType = ServiceType.DEEPSEEK
    AGENT_SERVICE: ServiceType = ServiceType.DEEPSEEK

    # Search settings
    SERPAPI_KEY: str = ""
    SEARCH_RESULT_COUNT: int = 10

    # Database settings (这些始终从 .env 读取，因为需要先连接数据库)
    # 支持两种方式：分项变量 DB_* 或完整 DATABASE_URL
    DATABASE_URL_RAW: str = ""  # 由 model_validator 从 DATABASE_URL 环境变量填充
    DB_HOST: str = ""
    DB_PORT: int = 5432
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_NAME: str = ""

    @model_validator(mode="after")
    def _load_database_url(self) -> "Settings":
        """从 DATABASE_URL 环境变量填充 DATABASE_URL_RAW（兼容 Next.js 共享 .env）"""
        if not self.DATABASE_URL_RAW:
            raw = os.environ.get("DATABASE_URL", "")
            if raw:
                object.__setattr__(self, "DATABASE_URL_RAW", raw.strip('"').strip("'"))
        return self

    # Neo4j 结构化知识图谱（主实例）
    NEO4J_URL: str = "bolt://localhost:7688"
    NEO4J_USERNAME: str = "neo4j"
    NEO4J_PASSWORD: str = "password"
    NEO4J_DATABASE: str = "neo4j"

    # Neo4j 非结构化文档知识图谱（第二实例，可选）
    NEO4J_UNSTRUCTURED_URL: str = ""
    NEO4J_UNSTRUCTURED_USERNAME: str = "neo4j"
    NEO4J_UNSTRUCTURED_PASSWORD: str = "password"
    NEO4J_UNSTRUCTURED_DATABASE: str = "neo4j"

    # JWT settings
    SECRET_KEY: str = "your-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Redis settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_CACHE_EXPIRE: int = 3600
    REDIS_CACHE_THRESHOLD: float = 0.8

    # Embedding settings
    EMBEDDING_TYPE: str = "dashscope"
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_THRESHOLD: float = 0.90
    DASHSCOPE_API_KEY: str = ""

    # MinerU settings
    MINERU_API_TOKEN: str = ""
    SERVER_BASE_URL: str = ""  # 服务器公网地址，自动检测填充，供 MinerU 等外部服务访问文件

    # 服务间通信配置
    INTERNAL_API_KEY: str = ""  # Next.js 与 Python 后端之间的内部 API 密钥，长度至少 32 字符
    BETTER_AUTH_SECRET: str = ""  # better-auth 签发 JWT 使用的密钥，两端必须一致

    # OSS 存储配置（与 Next.js 共享 .env 中的阿里云密钥）
    OSS_REGION: str = ""
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_BUCKET: str = ""
    OSS_ENDPOINT: str = ""
    # 兼容 ALIYUN_ACCESS_KEY_ID/SECRET
    ALIYUN_ACCESS_KEY_ID: str = ""
    ALIYUN_ACCESS_KEY_SECRET: str = ""

    # GraphRAG settings
    GRAPHRAG_PROJECT_DIR: str = str(ROOT_DIR / "app" / "graphrag")
    GRAPHRAG_DATA_DIR: str = "data"
    GRAPHRAG_QUERY_TYPE: str = "local"
    GRAPHRAG_RESPONSE_TYPE: str = "text"
    GRAPHRAG_COMMUNITY_LEVEL: int = 3
    GRAPHRAG_DYNAMIC_COMMUNITY: bool = False

    @property
    def DATABASE_URL(self) -> str:
        # 优先使用完整的 DATABASE_URL 环境变量（兼容 Next.js 共享 .env）
        if self.DATABASE_URL_RAW:
            url = self.DATABASE_URL_RAW
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            return url
        # 回退到分项变量拼接
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def NEO4J_CONN_URL(self) -> str:
        return f"{self.NEO4J_URL}"

    class Config:
        env_file = str(ENV_FILE)
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"  # 忽略未定义的环境变量（避免 Next.js 变量注入时报错）


# 从 .env 加载的初始配置实例（用于数据库连接等启动阶段）
_env_settings = Settings()


class DynamicSettings:
    """动态配置管理器：优先从数据库读取，回退到 .env 初始值
    
    支持缓存过期机制：缓存默认 60 秒后过期，下次访问时自动从数据库刷新。
    满足需求 3.3：system_settings 表中的配置发生变更时，Python_Backend 在下次请求时加载最新配置。
    """

    # 缓存过期时间（秒），默认 60 秒
    CACHE_TTL: int = 60

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._loaded = False
        self._cache_timestamp: float = 0.0  # 缓存加载时间戳
        self._refreshing = False  # 防止并发刷新

    def _cast(self, value: str, field_name: str) -> Any:
        """根据 Settings 类的字段类型自动转换值"""
        field_info = Settings.model_fields.get(field_name)
        if not field_info:
            return value
        annotation = field_info.annotation
        if annotation is int:
            return int(value)
        if annotation is float:
            return float(value)
        if annotation is bool:
            return value.lower() in ("true", "1", "yes")
        if annotation is ServiceType:
            return ServiceType(value)
        return value

    async def load_from_db(self):
        """从数据库加载所有配置到内存缓存，并记录加载时间戳"""
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.system_settings import SystemSettings
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                result = await session.execute(select(SystemSettings))
                rows = result.scalars().all()
                if rows:
                    self._cache = {row.key: row.value for row in rows}
                    self._loaded = True
                    self._cache_timestamp = time.monotonic()
                    logger.info(f"从数据库加载了 {len(self._cache)} 项配置")
                else:
                    logger.info("数据库中无配置，使用 .env 初始值")
        except Exception as e:
            logger.warning(f"从数据库加载配置失败，使用 .env: {e}")

    async def init_db_settings(self):
        """首次部署：将 .env 的值写入数据库（仅当配置项不存在时）
        
        遍历 SETTINGS_META 中定义的所有配置项，确保每一项都存在于数据库中。
        已存在的配置项保留用户修改过的值，不会被覆盖。
        """
        try:
            from app.core.database import AsyncSessionLocal, engine, Base
            from app.models.system_settings import SystemSettings
            from sqlalchemy import select, inspect

            # 确保表存在
            async with engine.begin() as conn:
                def check_table(sync_conn):
                    insp = inspect(sync_conn)
                    return insp.has_table("system_settings")
                exists = await conn.run_sync(check_table)
                if not exists:
                    await conn.run_sync(Base.metadata.create_all)
                    logger.info("创建 system_settings 表")

            async with AsyncSessionLocal() as session:
                # 查出已有的 key
                existing = await session.execute(select(SystemSettings.key))
                existing_keys = {r[0] for r in existing.fetchall()}

                added = 0
                for meta in SETTINGS_META:
                    key = meta["key"]
                    if key in existing_keys:
                        continue  # 已存在则跳过，保留用户修改过的值
                    env_val = getattr(_env_settings, key, "")
                    if isinstance(env_val, Enum):
                        env_val = env_val.value
                    # 构建描述信息：优先使用 meta 中的 description，否则使用 label
                    description = meta.get("description", meta["label"])
                    session.add(SystemSettings(
                        key=key,
                        value=str(env_val),
                        group_name=meta["group"],
                        label=meta["label"],
                        description=description,
                        value_type=meta["type"],
                        sort_order=meta["sort"],
                    ))
                    added += 1

                if added:
                    await session.commit()
                    logger.info(f"新增 {added} 项配置到数据库")
                else:
                    logger.info("system_settings 无新增配置项")

                # 初始化完成后加载配置到缓存
                await self.load_from_db()
        except Exception as e:
            logger.error(f"初始化数据库配置失败: {e}", exc_info=True)

    @property
    def is_cache_expired(self) -> bool:
        """检查缓存是否已过期"""
        if not self._loaded:
            return False  # 未加载过，不算过期
        return (time.monotonic() - self._cache_timestamp) > self.CACHE_TTL

    def __getattr__(self, name: str) -> Any:
        # 内部属性和方法不走缓存逻辑
        if name.startswith("_") or name in (
            "load_from_db", "init_db_settings", "reload",
            "is_cache_expired", "try_refresh_cache", "CACHE_TTL",
        ):
            raise AttributeError(name)

        # 如果缓存已过期，标记需要刷新（实际刷新在异步上下文中执行）
        if self.is_cache_expired and not self._refreshing:
            # 标记缓存为过期状态，但仍返回旧缓存值避免阻塞
            # 调用方应在异步上下文中调用 try_refresh_cache()
            logger.debug(f"配置缓存已过期（TTL={self.CACHE_TTL}s），将在下次异步调用时刷新")

        # 先查数据库缓存（空字符串也回退到 .env，避免数据库未初始化时返回空值）
        if self._loaded and name in self._cache and self._cache[name] != "":
            return self._cast(self._cache[name], name)

        # 回退到 .env 初始值
        return getattr(_env_settings, name)

    async def try_refresh_cache(self):
        """尝试刷新过期的缓存（异步方法，供请求中间件调用）
        
        满足需求 3.3：在下次请求时加载最新配置。
        使用 _refreshing 标志防止并发刷新。
        """
        if not self.is_cache_expired or self._refreshing:
            return
        self._refreshing = True
        try:
            await self.load_from_db()
        finally:
            self._refreshing = False

    async def reload(self):
        """重新从数据库加载配置（强制刷新，忽略 TTL）"""
        self._cache.clear()
        self._loaded = False
        self._cache_timestamp = 0.0
        await self.load_from_db()

    @property
    def GEMINI_PARSE_URL(self) -> str:
        model = self._cache.get("GEMINI_BASE_URL") or getattr(_env_settings, "GEMINI_BASE_URL")
        return f"https://api.kuai.host/v1beta/models/{model}:generateContent"

    @property
    def GEMINI_GEN_URL(self) -> str:
        model = self._cache.get("GEMINI_IMAGE_GEN_URL") or getattr(_env_settings, "GEMINI_IMAGE_GEN_URL")
        return f"https://api.kuai.host/v1beta/models/{model}:generateContent"


# 全局配置实例 — 所有模块通过 `from app.core.config import settings` 使用
settings = DynamicSettings()
