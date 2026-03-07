from sqlalchemy import Column, Integer, String, DateTime, Text, func
from app.core.database import Base


class KnowledgeBaseDocument(Base):
    """知识库文档模型，存储用户上传的文件及其索引状态
    
    表结构与 Drizzle ORM 端的 knowledge_base_document 表保持一致，
    两端共享同一张 PostgreSQL 表。
    """
    __tablename__ = "knowledge_base_document"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 用户和租户关联
    user_id = Column(Text, nullable=False, index=True)
    tenant_id = Column(Text, nullable=False, index=True)

    # 文件信息
    filename = Column(String(255), nullable=False)          # 存储文件名
    original_name = Column(String(255), nullable=False)     # 原始文件名
    file_path = Column(String(512), nullable=False)         # 文件存储路径
    file_type = Column(String(100), nullable=True)          # MIME 类型
    file_size = Column(Integer, nullable=True)              # 文件大小（字节）

    # 处理状态：pending / indexing / success / error
    status = Column(String(20), default="pending")
    error_message = Column(Text, nullable=True)             # 错误信息

    # 文档预览与索引
    preview = Column(Text, nullable=True)                   # 文档预览摘要
    index_id = Column(String(100), nullable=True)           # GraphRAG 索引 ID
    embedding_type = Column(String(50), nullable=True)      # 使用的 embedding 类型
    user_uuid = Column(String(100), nullable=True)          # 用户 UUID（用于文件隔离）

    # 时间戳（带时区）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
