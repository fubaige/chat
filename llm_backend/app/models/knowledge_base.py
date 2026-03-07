from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, Text
from sqlalchemy.orm import relationship
from app.core.database import Base

class KnowledgeBase(Base):
    """知识库模型，用于存储上传的文件及其索引状态"""
    __tablename__ = "knowledge_base"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_type = Column(String(100))
    size = Column(Integer)
    
    status = Column(String(20), default="pending")
    error_message = Column(Text, nullable=True)
    
    preview = Column(Text, nullable=True)
    index_id = Column(String(100), index=True)
    embedding_type = Column(String(50), nullable=True)  # 索引时使用的 embedding 类型
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    user = relationship("User", back_populates="knowledge_items")
