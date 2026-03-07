"""
This code is based on content found in the LangGraph documentation: https://python.langchain.com/docs/tutorials/graph/#advanced-implementation-with-langgraph
"""

from typing import Any, Callable, Coroutine, Dict

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableConfig
from app.core.logger import get_logger

from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.state import OverallState
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.summarize.prompts import create_summarization_prompt_template

logger = get_logger(service="summarize_node")

generate_summary_prompt = create_summarization_prompt_template()


def _extract_text_from_records(records) -> str:
    """从 records 中提取纯文本内容。
    
    records 可能是：
    - dict: {"result": "...text..."} (来自 GraphRAG customer_tools)
    - list: [{"col": "val"}, ...] (来自 Cypher 查询)
    - str: 直接文本
    """
    if isinstance(records, str):
        return records
    if isinstance(records, dict):
        # GraphRAG 返回格式: {"result": "...response text..."}
        if "result" in records:
            return str(records["result"])
        # 其他 dict 格式，转为可读文本
        return "\n".join(f"{k}: {v}" for k, v in records.items())
    if isinstance(records, list):
        parts = []
        for item in records:
            parts.append(_extract_text_from_records(item))
        return "\n".join(parts)
    return str(records)


def create_summarization_node(
    llm: BaseChatModel,
) -> Callable[[OverallState], Coroutine[Any, Any, dict[str, Any]]]:
    """
    Create a Summarization node for a LangGraph workflow.
    """

    generate_summary = generate_summary_prompt | llm | StrOutputParser()

    async def summarize(state: OverallState, config: RunnableConfig = None) -> Dict[str, Any]:
        """
        Summarize results of the performed Cypher queries.
        优先使用用户配置的智能体提示词作为角色约束。
        """
        raw_results = []
        
        for cypher in state.get("cyphers", list()):
            if isinstance(cypher, dict) and cypher.get("records") is not None:
                raw_results.append(cypher.get("records"))
            elif hasattr(cypher, "records") and cypher.records is not None:
                raw_results.append(cypher.records)
        
        # 提取纯文本，避免传 dict/list 给 LLM 导致误判
        results_text = _extract_text_from_records(raw_results) if raw_results else ""
        
        logger.info(f"Summarize node received {len(raw_results)} result(s), extracted text length: {len(results_text)}")
        if results_text:
            logger.info(f"Summarize results preview: {results_text[:200]}")

        # 读取用户配置的智能体提示词
        agent_system_prompt = ""
        if config:
            configurable = config.get("configurable", {}) if isinstance(config, dict) else getattr(config, "get", lambda k, d=None: d)("configurable", {})
            agent_system_prompt = (configurable.get("agent_system_prompt", "") or "").strip()

        if agent_system_prompt:
            # 有用户自定义提示词：将知识库内容作为背景资料，让 LLM 按角色设定一次性回答
            from langchain_core.messages import SystemMessage, HumanMessage
            system_content = (
                f"{agent_system_prompt}\n\n"
                "---\n"
                "【知识库资料】以下是检索到的相关内容，请结合资料按照上述角色设定回答用户问题。\n"
                "资料中没有的内容，按角色限制范围说明无法回答，不要编造。\n"
                "禁止使用任何 markdown 格式，用自然语言口语化表达。"
            )
            human_content = (
                f"对话历史:\n{state.get('chat_history', '')}\n\n"
                f"知识库资料：{results_text or '暂无相关资料'}\n\n"
                f"用户问题：\"{state.get('question')}\""
            )
            messages = [SystemMessage(content=system_content), HumanMessage(content=human_content)]
            response = await llm.ainvoke(messages)
            summary = response.content if hasattr(response, "content") else str(response)
            logger.info(f"Summarize 使用用户自定义提示词，角色约束已生效")
        else:
            # 无自定义提示词：使用默认摘要模板
            summary = await generate_summary.ainvoke(
                {
                    "question": state.get("question"),
                    "results": results_text or "目前知识库中暂无直接相关数据",
                    "chat_history": state.get("chat_history", ""),
                }
            )

        return {"summary": summary, "steps": ["summarize"]}

    return summarize
