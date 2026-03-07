import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# 设置 SQLAlchemy 日志级别为 WARNING，这样就不会显示 INFO 级别的 SQL 查询日志
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

# 创建异步引擎（PostgreSQL + asyncpg）
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,       # 自动检测断开的连接
    pool_size=10,             # 连接池常驻连接数
    max_overflow=10,          # 最大溢出连接数，峰值最多 20 个并发连接
    pool_recycle=1800,        # 30 分钟回收连接，防止长时间空闲断开
    pool_timeout=120,         # 等待连接超时 120s，兼容 GraphRAG 长查询期间的连接等待
)

# 创建异步会话工厂
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# 创建基类
Base = declarative_base()

# 获取数据库会话的依赖函数
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close() 