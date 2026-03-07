from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, func
from app.core.database import Base


class AgentConfig(Base):
    """智能体配置表 — 存储每个用户的提示词和开场白配置
    
    注意：此表为 Python 端独立使用的简化智能体配置。
    完整的智能体配置（含 LangGraph 扩展字段）存储在 wecom_ai_agent 表中，
    由 Next.js 端通过 Drizzle ORM 管理。
    """
    __tablename__ = "agent_configs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Text, nullable=False, index=True)                  # 用户 ID（Text 类型，匹配 better-auth）
    tenant_id = Column(Text, nullable=True, index=True)                 # 租户 ID（多租户隔离）
    system_prompt = Column(Text, nullable=False, default="")            # 提示词（系统指令）
    opening_message = Column(Text, nullable=False, default="")          # 开场白内容
    opening_enabled = Column(Boolean, nullable=False, default=True)     # 是否启用开场白

    # 时间戳（带时区）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
