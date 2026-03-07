from sqlalchemy import Column, Integer, String, DateTime, Text, func
from app.core.database import Base


class SystemSettings(Base):
    """系统配置表，存储所有可编辑的系统配置项
    
    表结构与 Drizzle ORM 端的 system_settings 表保持一致，
    两端共享同一张 PostgreSQL 表。
    """
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False, default="")
    group_name = Column(String(50), nullable=False, default="general")   # 分组名
    label = Column(String(100), nullable=False, default="")              # 显示名称
    description = Column(String(255), nullable=True)                     # 描述
    value_type = Column(String(20), nullable=False, default="string")    # string/int/float/bool/password/readonly
    sort_order = Column(Integer, default=0)                              # 排序

    # 时间戳（带时区）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
