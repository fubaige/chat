from typing import Any, Callable, Coroutine, Dict, List
import asyncio
import os
import re
from pathlib import Path
from pydantic import BaseModel, Field

# 导入GraphRAG相关模块
import app.graphrag.graphrag.api as api
from app.graphrag.graphrag.config.load_config import load_config
from app.graphrag.graphrag.callbacks.noop_query_callbacks import NoopQueryCallbacks
from app.graphrag.graphrag.utils.storage import load_table_from_storage
from app.graphrag.graphrag.storage.file_pipeline_storage import FilePipelineStorage
from app.lg_agent.kg_sub_graph.kg_neo4j_conn import get_neo4j_graph
from app.core.logger import get_logger
from langchain_deepseek import ChatDeepSeek
from app.core.config import settings, ServiceType
from app.lg_agent.kg_sub_graph.agentic_rag_agents.retrievers.cypher_examples.northwind_retriever import NorthwindCypherRetriever
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.cypher_tools.utils import (
    create_text2cypher_generation_node,
    create_text2cypher_validation_node,
    create_text2cypher_execution_node,
    validate_no_writes_in_cypher_query,  # 危险操作权限校验
)



# 获取日志记录器
logger = get_logger(service="cypher_tools")

# 定义GraphRAG查询的输入状态类型
class CypherQueryInputState(BaseModel):
    task: str
    query: str
    steps: List[str]

# 定义GraphRAG查询的输出状态类型
class CypherQueryOutputState(BaseModel):
    task: str
    query: str
    statement: str = ""
    parameters: str = ""
    errors: List[str]
    records: Dict[str, Any]
    steps: List[str]

# 定义GraphRAG API包装器

def create_cypher_query_node(
) -> Callable[
    [CypherQueryInputState],
    Coroutine[Any, Any, Dict[str, List[CypherQueryOutputState] | List[str]]],
]:
    """
    创建 Text2Cypher 查询节点，用于LangGraph工作流。

    返回
    -------
    Callable[[CypherQueryInputState], Dict[str, List[CypherQueryOutputState] | List[str]]]
        名为`cypher_query`的LangGraph节点。
    """

    async def cypher_query(
        state: Dict[str, Any],
    ) -> Dict[str, List[CypherQueryOutputState] | List[str]]:
        """
        执行Text2Cypher查询并返回结果。
        如果 Neo4j 连接失败或查询出错，返回空结果而不是崩溃。
        """
        errors = list()
        # 获取查询文本
        query = state.get("task", "")
        if not query:
            errors.append("未提供查询文本")
 
        # 使用大模型执行查询/多跳/并行查询计划
        model = ChatDeepSeek(
            api_key=settings.DEEPSEEK_API_KEY,
            api_base=settings.DEEPSEEK_BASE_URL + "/v1",
            model_name=settings.DEEPSEEK_MODEL,
            temperature=0.7,
            max_retries=3,
            request_timeout=60,
            streaming=True,  # DeepSeek 官方推荐开启流式
            tags=["research_plan"],
        )

        # 2. 获取Neo4j图数据库连接
        neo4j_graph = None
        try:
            neo4j_graph = get_neo4j_graph()
            logger.info("success to get Neo4j graph database connection")
        except Exception as e:
            logger.warning(f"Neo4j connection failed in cypher_query: {e}")
            errors.append(f"Neo4j连接失败: {str(e)}")
        
        # 如果 Neo4j 连接失败，返回空结果
        if neo4j_graph is None:
            return {
                "cyphers": [
                    CypherQueryOutputState(
                        **{
                            "task": state.get("task", ""),
                            "query": query,
                            "statement": "",
                            "parameters": "",
                            "errors": errors,
                            "records": {"result": "Neo4j数据库暂无数据"},
                            "steps": ["execute_cypher_query"],
                        }
                    )
                ],
                "steps": ["execute_cypher_query"],
            }

        try:
            # step 2. 创建自定义检索器实例
            cypher_retriever = NorthwindCypherRetriever()

            # Step 3. 生成 Cypher 查询语句
            cypher_generation = create_text2cypher_generation_node(
                llm=model, graph=neo4j_graph, cypher_example_retriever=cypher_retriever
            )

            cypher_result = await cypher_generation(state)

            # ★ 权限控制：Cypher 生成后立即检查是否含危险写操作
            # 拦截 DELETE/DROP/MERGE/REMOVE/SET/CREATE/FOREACH 等写操作，防止数据被意外修改
            generated_statement = cypher_result.get("statement", "") if isinstance(cypher_result, dict) else ""
            write_errors = validate_no_writes_in_cypher_query(generated_statement)
            if write_errors:
                logger.warning(f"Cypher 权限拦截：检测到危险写操作，语句: {generated_statement[:200]}")
                return {
                    "cyphers": [
                        CypherQueryOutputState(
                            **{
                                "task": state.get("task", ""),
                                "query": query,
                                "statement": generated_statement,
                                "parameters": "",
                                "errors": write_errors,
                                "records": {"result": "该操作涉及数据库写入，已被系统拦截，仅支持查询操作。"},
                                "steps": ["permission_denied"],
                            }
                        )
                    ],
                    "steps": ["permission_denied"],
                }

            # step 4. 验证生成的 Cypher 查询语句是否正确 (Retry Loop)
            max_retries = 3
            current_cypher = cypher_result
            final_execute_info = None

            for attempt in range(max_retries):
                logger.info(f"Cypher Validation Attempt {attempt + 1}/{max_retries}")
                
                validate_cypher = create_text2cypher_validation_node(
                    llm=model,
                    graph=neo4j_graph,
                    llm_validation=True,
                    cypher_statement=current_cypher
                )
                
                execute_info = await validate_cypher(state=state)
                
                if not execute_info.get("errors") and not execute_info.get("mapping_errors"):
                    logger.info("Cypher validation passed.")
                    final_execute_info = execute_info
                    break
                
                if attempt < max_retries - 1:
                    logger.warning(f"Cypher validation failed. Errors: {execute_info.get('errors')}. Retrying...")
                    current_cypher = execute_info["statement"]
                else:
                    logger.warning("Max checking retries reached. Using last corrected result.")
                    final_execute_info = execute_info

            execute_info = final_execute_info

            # step 6. 执行 Cypher 查询语句
            execute_cypher = create_text2cypher_execution_node(
                graph=neo4j_graph, cypher=execute_info
            )

            final_result = await execute_cypher(state)

            return {
                "cyphers": [
                    CypherQueryOutputState(
                        **{
                            "task": state.get("task", ""),
                            "query": query,
                            "statement": "",
                            "parameters": "",
                            "errors": errors,
                            "records": {"result": final_result["cyphers"][0]["records"]} if final_result.get("cyphers") and len(final_result["cyphers"]) > 0 else {"result": []},
                            "steps": ["execute_cypher_query"],
                        }
                    )
                ],
                "steps": ["execute_cypher_query"],
            }
        
        except Exception as e:
            logger.warning(f"Cypher query execution failed: {e}")
            return {
                "cyphers": [
                    CypherQueryOutputState(
                        **{
                            "task": state.get("task", ""),
                            "query": query,
                            "statement": "",
                            "parameters": "",
                            "errors": [f"Cypher查询执行失败: {str(e)}"],
                            "records": {"result": "数据库暂无相关数据"},
                            "steps": ["execute_cypher_query"],
                        }
                    )
                ],
                "steps": ["execute_cypher_query"],
            }
  
    return cypher_query

