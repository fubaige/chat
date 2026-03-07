from sqlalchemy import Column, Integer, String, DateTime, Text, func
from app.core.database import Base


class SystemSettings(Base):
    """系统配置表，存储所有可编辑的系统配置项"""
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False, default="")
    group_name = Column(String(50), nullable=False, default="general")  # 分组名
    label = Column(String(100), nullable=False, default="")  # 显示名称
    description = Column(String(255), nullable=True)  # 描述
    value_type = Column(String(20), nullable=False, default="string")  # string, int, float, bool, password
    sort_order = Column(Integer, default=0)  # 排序
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
