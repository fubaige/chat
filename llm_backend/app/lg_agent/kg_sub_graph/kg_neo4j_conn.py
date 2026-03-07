from langchain_neo4j import Neo4jGraph
from app.core.config import settings
from app.core.logger import get_logger
from typing import Optional
import logging
import time

# 获取日志记录器
logger = get_logger(service="kg_builder")

# 设置Neo4j驱动的日志级别为ERROR，禁止WARNING消息
logging.getLogger("neo4j").setLevel(logging.ERROR)
# 禁用langchain_neo4j相关日志
logging.getLogger("langchain_neo4j").setLevel(logging.ERROR)
# 禁用驱动相关日志
logging.getLogger("neo4j.io").setLevel(logging.ERROR)
logging.getLogger("neo4j.bolt").setLevel(logging.ERROR)

# Schema 缓存：字典 + 时间戳实现 60 秒 TTL（不用 lru_cache，因为需要 TTL 控制）
_schema_cache: dict = {}
_schema_cache_time: dict = {}
SCHEMA_CACHE_TTL = 60  # 缓存有效期（秒）


def get_neo4j_graph() -> Neo4jGraph:
    """
    创建并返回主 Neo4jGraph 实例（结构化知识图谱），使用配置文件中的设置。
    
    Returns:
        Neo4jGraph: 配置好的 Neo4j 图数据库连接实例
    """
    logger.info(f"initialize Neo4j connection: {settings.NEO4J_URL}")
    
    try:
        neo4j_graph = Neo4jGraph(
            url=settings.NEO4J_URL,
            username=settings.NEO4J_USERNAME,
            password=settings.NEO4J_PASSWORD,
            database=settings.NEO4J_DATABASE
        )
        return neo4j_graph
    except Exception as e:
        raise


def get_neo4j_unstructured_graph() -> Optional[Neo4jGraph]:
    """
    创建并返回第二个 Neo4jGraph 实例（非结构化文档知识图谱）。
    
    当 NEO4J_UNSTRUCTURED_URL 未配置时，记录 warning 并返回 None，不抛出异常。
    调用方应检查返回值是否为 None 再使用。
    
    Returns:
        Optional[Neo4jGraph]: 配置好的第二 Neo4j 实例，或 None（未配置时）
    """
    url = settings.NEO4J_UNSTRUCTURED_URL
    if not url:
        logger.warning("NEO4J_UNSTRUCTURED_URL 未配置，跳过非结构化 Neo4j 连接")
        return None

    logger.info(f"initialize unstructured Neo4j connection: {url}")
    try:
        neo4j_graph = Neo4jGraph(
            url=url,
            username=settings.NEO4J_UNSTRUCTURED_USERNAME,
            password=settings.NEO4J_UNSTRUCTURED_PASSWORD,
            database=settings.NEO4J_UNSTRUCTURED_DATABASE,
        )
        return neo4j_graph
    except Exception as e:
        logger.warning(f"非结构化 Neo4j 连接失败: {e}")
        return None


def get_neo4j_schema_cached(graph_key: str = "structured") -> str:
    """
    获取 Neo4j Schema，带 60 秒 TTL 内存缓存。
    
    TTL 内重复调用直接返回缓存值，不重新连接数据库；
    TTL 过期后重新获取并刷新缓存。
    
    Args:
        graph_key: 缓存键，"structured" 对应主实例，"unstructured" 对应第二实例
    
    Returns:
        str: Schema 字符串，连接失败时返回空字符串
    """
    now = time.time()
    # 检查缓存是否在 TTL 内有效
    if graph_key in _schema_cache and (now - _schema_cache_time.get(graph_key, 0)) < SCHEMA_CACHE_TTL:
        logger.debug(f"Schema 缓存命中: graph_key={graph_key}")
        return _schema_cache[graph_key]

    # 缓存过期或不存在，重新获取
    logger.info(f"Schema 缓存未命中或已过期，重新获取: graph_key={graph_key}")
    try:
        from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.utils.utils import retrieve_and_parse_schema_from_graph_for_prompts
        graph = get_neo4j_graph() if graph_key == "structured" else get_neo4j_unstructured_graph()
        if graph is None:
            return ""
        schema = retrieve_and_parse_schema_from_graph_for_prompts(graph)
        _schema_cache[graph_key] = schema
        _schema_cache_time[graph_key] = now
        logger.info(f"Schema 缓存已更新: graph_key={graph_key}, 长度={len(schema)}")
        return schema
    except Exception as e:
        logger.warning(f"获取 Neo4j Schema 失败: graph_key={graph_key}, error={e}")
        return ""