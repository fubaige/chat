from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class WechatMpConfig(Base):
    """微信公众号配置模型，支持多账号配置
    
    表结构与 Drizzle ORM 端的 wechat_mp_config 表保持一致，
    两端共享同一张 PostgreSQL 表。
    """
    __tablename__ = "wechat_mp_config"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 租户和用户关联
    tenant_id = Column(Text, nullable=False, index=True)
    user_id = Column(Text, nullable=False)

    # 基本信息
    name = Column(String(100), nullable=False)                          # 配置名称

    # 微信公众号凭证
    appid = Column(String(100), nullable=False)                         # 微信 AppID
    appsecret = Column(String(255), nullable=True)                      # 微信 AppSecret
    token = Column(String(100), nullable=False)                         # Token 令牌
    encoding_aes_key = Column(String(255), nullable=False)              # 消息加解密密钥

    # 服务器配置
    server_url = Column(String(500), nullable=True)                     # 服务器回调 URL

    # AI 智能体绑定
    ai_agent_id = Column(Text, nullable=True)                           # 绑定的 AI 智能体 ID

    # 关联的知识库 ID 列表（JSONB 数组）
    knowledge_base_ids = Column(JSONB, default=[])

    # 消息配置
    welcome_message = Column(Text, nullable=True)                       # 关注欢迎消息
    default_reply = Column(Text, nullable=True)                         # 默认回复

    # 开关配置
    enable_ai_reply = Column(Boolean, default=True)                     # 是否启用 AI 回复
    is_active = Column(Boolean, default=True)                           # 是否启用

    # 时间戳（带时区）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
