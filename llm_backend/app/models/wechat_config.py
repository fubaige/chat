from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from datetime import datetime


class WechatConfig(Base):
    """微信公众号/服务号配置模型"""
    __tablename__ = "wechat_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # 基本配置
    name = Column(String(100), nullable=False, comment="配置名称")
    appid = Column(String(100), nullable=False, comment="微信AppID")
    appsecret = Column(String(255), nullable=True, comment="微信AppSecret（用于菜单API）")
    token = Column(String(100), nullable=False, comment="Token令牌")
    encoding_aes_key = Column(String(255), nullable=False, comment="消息加解密密钥")
    
    # 服务器配置
    server_url = Column(String(500), nullable=True, comment="服务器地址URL")
    
    # 知识库关联
    knowledge_base_id = Column(String(100), nullable=True, comment="关联的知识库ID")
    
    # 自动回复配置
    welcome_message = Column(Text, nullable=True, comment="关注时的欢迎消息")
    default_reply = Column(Text, nullable=True, comment="默认回复消息")
    enable_ai_reply = Column(Boolean, default=True, comment="是否启用公众号/服务号接入")
    
    # 状态
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    
    # 关系
    user = relationship("User", back_populates="wechat_configs")
