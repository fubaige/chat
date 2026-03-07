from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class AgentConfig(Base):
    """智能体配置表 - 存储每个用户的提示词和开场白配置"""
    __tablename__ = "agent_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    system_prompt = Column(Text, nullable=False, default="")       # 提示词（系统指令）
    opening_message = Column(Text, nullable=False, default="")     # 开场白内容
    opening_enabled = Column(Boolean, nullable=False, default=True) # 是否启用开场白
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="agent_config")
