from sqlalchemy import Column, Integer, String, DateTime, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime, nullable=True)
    status = Column(String(20), default="active")
    role = Column(String(20), default="user")  # 'admin' 或 'user'
    api_key = Column(String(36), nullable=True)  # 用户独立 API 密钥，用于对外调用验证
    
    # 关系
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    knowledge_items = relationship("KnowledgeBase", back_populates="user", cascade="all, delete-orphan")
    wechat_configs = relationship("WechatConfig", back_populates="user", cascade="all, delete-orphan")
    user_settings = relationship("UserSettings", back_populates="user", cascade="all, delete-orphan")
    agent_config = relationship("AgentConfig", back_populates="user", uselist=False, cascade="all, delete-orphan")