from app.lg_agent.lg_states import AgentState, Router
from app.lg_agent.lg_prompts import (
    ROUTER_SYSTEM_PROMPT,
    GET_ADDITIONAL_SYSTEM_PROMPT,
    GENERAL_QUERY_SYSTEM_PROMPT,
    GET_IMAGE_SYSTEM_PROMPT,
    GUARDRAILS_SYSTEM_PROMPT,
    RAGSEARCH_SYSTEM_PROMPT,
    CHECK_HALLUCINATIONS,
    GENERATE_QUERIES_SYSTEM_PROMPT
)
from langchain_core.runnables import RunnableConfig
from langchain_deepseek import ChatDeepSeek
from app.core.config import settings, ServiceType
from app.core.logger import get_logger
from typing import cast, Literal, TypedDict, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from app.lg_agent.lg_states import AgentState, InputState, Router, GradeHallucinations
from app.lg_agent.kg_sub_graph.agentic_rag_agents.retrievers.cypher_examples.northwind_retriever import NorthwindCypherRetriever
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.planner.node import create_planner_node
from app.lg_agent.kg_sub_graph.agentic_rag_agents.workflows.multi_agent.multi_tool import create_multi_tool_workflow
from app.lg_agent.kg_sub_graph.kg_neo4j_conn import get_neo4j_graph
from app.lg_agent.kg_sub_graph.kg_tools_list import microsoft_graphrag_query
from pydantic import BaseModel
from typing import Dict, List
from langchain_core.messages import AIMessage
from langchain_core.runnables.base import Runnable
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.utils.utils import retrieve_and_parse_schema_from_graph_for_prompts
from langchain_core.prompts import ChatPromptTemplate
from app.tools.search import SearchTool  # Import SearchTool
import base64
import os
import math
import asyncio
import json
import time
import re
import difflib
import tempfile
import shutil
from pathlib import Path


from typing import Literal
from pydantic import BaseModel, Field


class AdditionalGuardrailsOutput(BaseModel):
    """
    格式化输出，用于判断用户的问题是否与图谱内容相关
    """
    decision: Literal["end", "continue"] = Field(
        description="Decision on whether the question is related to the graph contents."
    )


# 构建日志记录器
logger = get_logger(service="lg_builder")


def _get_extended_config(config: RunnableConfig) -> dict:
    """从 LangGraph 线程配置中提取 AgentConfigExtended 字典。
    
    配置通过 thread_config["configurable"]["agent_config_extended"] 传入，
    由 internal.py 的 internal_chat_stream 端点设置。
    
    Returns:
        AgentConfigExtended 的字典表示，如果不存在则返回空字典。
    """
    configurable = config.get("configurable", {})
    return configurable.get("agent_config_extended", {})


def _filter_storage_dirs_by_kb_ids(all_dirs: list, kb_ids: list) -> list:
    """根据智能体绑定的 knowledgeBaseIds 过滤知识库目录。
    
    knowledgeBaseIds 存的是知识库文档的 record_id（数据库 ID），
    目录结构为 output/{user_uuid}/{record_id}/，
    所以目录名（basename）就是 record_id。
    
    Args:
        all_dirs: 用户的所有知识库目录列表
        kb_ids: 智能体绑定的知识库 ID 列表（字符串）
    
    Returns:
        过滤后的目录列表。如果 kb_ids 为空，返回全部目录。
    """
    if not kb_ids:
        return all_dirs
    
    kb_id_set = set(str(kid) for kid in kb_ids)
    filtered = [d for d in all_dirs if os.path.basename(d) in kb_id_set]
    
    if filtered:
        logger.info(f"按 knowledgeBaseIds 过滤：{len(all_dirs)} → {len(filtered)} 个目录，绑定ID={kb_ids}")
    else:
        # 过滤后为空，可能是旧结构目录（没有 record_id 子目录），回退到全部
        logger.warning(f"按 knowledgeBaseIds 过滤后为空（绑定ID={kb_ids}），回退到全部 {len(all_dirs)} 个目录")
        return all_dirs
    
    return filtered

def _create_deepseek_model(tags: list = None, model_name: str = None, **kwargs):
    """创建 DeepSeek 模型实例，统一配置 timeout 和 max_retries。
    
    根据 DeepSeek 官方文档：
    - streaming=True 启用流式输出
    - deepseek-reasoner 模式下 temperature/top_p/presence_penalty/frequency_penalty 不生效（设置不报错但无效）
    - 为保持代码整洁，思考模式下不设置这些参数
    
    Args:
        tags: 模型标签列表
        model_name: 模型名称，优先级高于 settings.DEEPSEEK_MODEL
        **kwargs: 额外参数，如 temperature
    """
    resolved_model = model_name or settings.DEEPSEEK_MODEL
    is_thinking = resolved_model == "deepseek-reasoner"
    
    params = dict(
        api_key=settings.DEEPSEEK_API_KEY,
        api_base=settings.DEEPSEEK_BASE_URL + "/v1",
        model_name=resolved_model,
        max_retries=3,
        request_timeout=60,
        streaming=True,  # DeepSeek 官方推荐开启流式
        tags=tags or [],
    )
    
    # 思考模式下 temperature 等参数无效，不设置以保持整洁
    if not is_thinking:
        params["temperature"] = kwargs.get("temperature", 1)
    
    return ChatDeepSeek(**params)


def _strip_reasoning_content(messages: list) -> list:
    """清理消息历史中的 reasoning_content，符合 DeepSeek 多轮对话规范。
    
    DeepSeek 官方文档明确指出：
    - 多轮对话中，上一轮输出的 reasoning_content 不应传入下一轮上下文
    - 只保留 content 字段，丢弃 reasoning_content 以节省带宽
    """
    cleaned = []
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, 'additional_kwargs'):
            # 清除 reasoning_content（LangChain 可能存储在 additional_kwargs 中）
            if msg.additional_kwargs.get('reasoning_content'):
                new_kwargs = {k: v for k, v in msg.additional_kwargs.items() if k != 'reasoning_content'}
                cleaned.append(AIMessage(
                    content=msg.content,
                    additional_kwargs=new_kwargs,
                    id=msg.id
                ))
                continue
        cleaned.append(msg)
    return cleaned


def _get_recent_messages(messages: list, max_messages: int = 30) -> list:
    """获取最近的 N 条消息，实现对话历史衰减。
    
    Args:
        messages: 完整消息列表
        max_messages: 保留的最大消息数（默认30条）
    
    Returns:
        最近的消息列表（已清理 reasoning_content）
    """
    if not messages:
        return []
    
    # 先衰减，再清理 reasoning_content
    recent = messages[-max_messages:] if len(messages) > max_messages else messages
    return _strip_reasoning_content(recent)


def _get_memory_limit(config: RunnableConfig) -> int:
    """从扩展配置中获取记忆衰减的最大消息数。
    
    优先使用 memoryDecayConfig.maxMessages，范围限制在 10-50，默认 30。
    """
    ext_config = _get_extended_config(config)
    memory_cfg = ext_config.get("memoryDecayConfig", {}) or {}
    if not memory_cfg.get("enabled", True):
        return 50  # 禁用衰减时使用最大值
    limit = memory_cfg.get("maxMessages", 30)
    return max(10, min(50, int(limit)))


async def _generate_related_questions(api, user_query: str, storage_dir: str) -> str:
    """基于知识库内容生成相关问题推荐。
    
    当用户的问题在知识库中找不到直接答案时，
    从知识库中提取相关主题和实体，生成用户可能感兴趣的相关问题。
    
    Args:
        api: GraphRAGAPI 实例
        user_query: 用户的原始问题
        storage_dir: 知识库存储目录
    
    Returns:
        格式化的相关问题列表字符串，如果无法生成则返回空字符串
    """
    try:
        # 确保 API 已初始化
        await api.initialize()
        
        # 获取知识库中的实体信息
        if api.entities is None or len(api.entities) == 0:
            logger.warning("知识库中没有实体数据")
            return ""
        
        # 提取前 20 个实体的标题作为主题
        entity_titles = []
        for _, row in api.entities.head(20).iterrows():
            if 'title' in row and row['title']:
                title = str(row['title']).split(':')[0]  # 提取实体名称（去掉描述部分）
                if title and len(title) < 50:  # 过滤过长的标题
                    entity_titles.append(title)
        
        if not entity_titles:
            logger.warning("无法提取实体标题")
            return ""
        
        # 使用 LLM 生成相关问题
        model = _create_deepseek_model(tags=["related_questions"])
        
        prompt = f"""基于以下知识库主题，为用户生成 3-5 个相关问题建议。

用户原始问题：{user_query}

知识库包含的主题：
{', '.join(entity_titles[:15])}

要求：
1. 生成的问题要与知识库主题相关
2. 问题要自然、口语化，像朋友聊天一样
3. 每个问题一行，用数字编号（1. 2. 3.）
4. 不要使用 markdown 格式
5. 问题要简短，不超过 20 个字

直接输出问题列表，不要其他说明："""

        response = await model.ainvoke([{"role": "user", "content": prompt}])
        related_questions = response.content.strip()
        
        if related_questions and len(related_questions) > 10:
            logger.info(f"成功生成相关问题: {related_questions[:100]}")
            return related_questions
        else:
            return ""
            
    except Exception as e:
        logger.error(f"生成相关问题时出错: {e}", exc_info=True)
        return ""

async def analyze_and_route_query(
    state: AgentState, *, config: RunnableConfig
) -> dict[str, Router]:
    """Analyze the user's query and determine the appropriate routing.

    This function uses a language model to classify the user's query and decide how to route it
    within the conversation flow.

    支持 AgentConfigExtended 中的 intentRouterConfig：
    - enabled=False 时跳过意图识别，直接路由到 graphrag
    - confidenceThreshold 自定义置信度阈值（默认 0.6）

    Args:
        state (AgentState): The current state of the agent, including conversation history.
        config (RunnableConfig): Configuration with the model used for query analysis.

    Returns:
        dict[str, Router]: A dictionary containing the 'router' key with the classification result (classification type and logic).
    """
    # 获取扩展配置
    ext_config = _get_extended_config(config)
    intent_router_cfg = ext_config.get("intentRouterConfig", {}) or {}
    intent_router_enabled = intent_router_cfg.get("enabled", True)

    # 如果意图路由被禁用，直接返回 graphrag 路由，跳过 LLM 意图识别
    if not intent_router_enabled:
        logger.info("意图路由已禁用（intentRouterConfig.enabled=False），直接路由到 graphrag")
        last_content = state.messages[-1].content if state.messages else ""
        return {
            "router": Router(
                question=last_content,
                type="graphrag",
                logic="意图路由已禁用，直接走知识库检索",
            ),
            "need_image_gen": False,
        }

    # 选择模型实例，通过.env文件中的AGENT_SERVICE参数选择
    model = _create_deepseek_model(tags=["router"])
    logger.info(f"Using DeepSeek model: {settings.DEEPSEEK_MODEL}")

    # 拼接提示模版 + 用户的实时问题（包含历史上下文对话）
    # 按照 DeepSeek 多轮对话规范：每轮只传 role + content，
    # 清除 reasoning_content、response_metadata 等额外字段
    # 同时应用历史衰减：根据配置保留最近 N 条消息
    mem_limit = _get_memory_limit(config)
    cleaned_messages = _get_recent_messages(state.messages, max_messages=mem_limit)
    history_dicts = []
    for msg in cleaned_messages:
        if isinstance(msg, AIMessage):
            role = "assistant"
        elif hasattr(msg, 'type') and msg.type == 'human':
            role = "user"
        else:
            role = "user"
        history_dicts.append({"role": role, "content": msg.content})
    
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT}
    ] + history_dicts
    logger.info("-----Analyze user query type-----")
    logger.info(f"History messages: {state.messages}")
    
    # 使用结构化输出，输出问题类型（意图识别核心：Prompt-template + DeepSeek v3，5类标签 JSON 输出）
    response = cast(
        Router, await model.with_structured_output(Router).ainvoke(messages)
    )
    
    # 兜底：如果结构化输出解析失败返回 None，默认路由到 graphrag
    if response is None:
        logger.warning("Structured output returned None, defaulting to graphrag route")
        last_content = state.messages[-1].content if state.messages else ""
        response = Router(question=last_content, type="graphrag", logic="structured output failed, defaulting to graphrag")
    
    # ★ Logprobs 置信度计算与降级逻辑
    # 从扩展配置中获取自定义置信度阈值，默认 0.6
    confidence_threshold = intent_router_cfg.get("confidenceThreshold", 0.6)
    logger.info(f"使用置信度阈值: {confidence_threshold}")

    try:
        raw_response = await model.ainvoke(messages, logprobs=True)
        metadata = getattr(raw_response, "response_metadata", {}) or {}
        logprobs_data = metadata.get("logprobs", {}) or {}
        content_logprobs = logprobs_data.get("content", []) or []
        if content_logprobs:
            first_logprob = content_logprobs[0].get("logprob", None)
            if first_logprob is not None:
                confidence = 1 / (1 + math.exp(-first_logprob))
                logger.info(f"Router logprob={first_logprob:.4f}, confidence={confidence:.4f}")
                if confidence < confidence_threshold:
                    original_type = response["type"]
                    response = Router(
                        type="graphrag",
                        logic=response.get("logic", "") + f"（置信度 {confidence:.2f} < {confidence_threshold}，已降级为 graphrag）",
                        question=response.get("question", ""),
                    )
                    logger.info(f"置信度不足，路由从 {original_type} 降级为 graphrag")
    except Exception as logprob_err:
        logger.warning(f"Logprobs 置信度计算失败，使用原始路由结果: {logprob_err}")

    logger.info(f"Analyze user query type completed, result: {response}")

    # 检测绘画意图：无论是否上传图片，都以文字意图为准
    configurable = config.get("configurable", {})
    image_path = configurable.get("image_path")
    need_image_gen = False

    try:
        from app.lg_agent.lg_prompts import IMAGE_GEN_INTENT_PROMPT
        last_query = state.messages[-1].content if state.messages else ""
        intent_prompt = IMAGE_GEN_INTENT_PROMPT.format(query=last_query)
        intent_model = _create_deepseek_model(tags=["intent"])
        intent_resp = await intent_model.ainvoke([{"role": "user", "content": intent_prompt}])
        intent_text = (intent_resp.content or "").strip().upper()
        need_image_gen = intent_text.startswith("YES")
        logger.info(f"绘画意图检测结果: {intent_text} -> need_image_gen={need_image_gen}，image_path={'有' if image_path else '无'}")
    except Exception as e:
        logger.warning(f"绘画意图检测失败，跳过: {e}")

    return {"router": response, "need_image_gen": need_image_gen}

def route_query(
    state: AgentState, *, config: RunnableConfig,
) -> Literal["respond_to_general_query", "get_additional_info", "invoke_kg_subgraph", "create_image_query", "create_file_query", "web_search_query", "generate_image_node"]:
    """根据意图识别结果确定下一步操作。
    
    支持 AgentConfigExtended 中的配置驱动路由：
    - intentRouterConfig.routes.{type}=False 时禁用对应路由类型，降级为 graphrag
    - webSearchConfig.enabled=True 时启用联网搜索节点
    - deepThinkingConfig 通过 configurable.deep_thinking 传递（已在 internal.py 中处理）
    
    路由优先级：
    1. 文件/图片上传 → 对应处理节点（受 multiModalConfig 控制）
    2. 绘画意图 → generate_image_node
    3. 联网搜索开关 → web_search_query
    4. 意图识别结果（Router）→ 对应节点
       - general：纯闲聊寒暄 → respond_to_general_query（不触发知识库）
       - additional：问题不完整 → get_additional_info
       - graphrag：业务问题 → invoke_kg_subgraph（走完整知识库检索链路）
       - image/file：多媒体 → 对应节点
    """
    configurable = config.get("configurable", {})
    image_path = configurable.get("image_path")
    need_image_gen = state.need_image_gen

    # 获取扩展配置
    ext_config = _get_extended_config(config)
    intent_router_cfg = ext_config.get("intentRouterConfig", {}) or {}
    routes_cfg = intent_router_cfg.get("routes", {}) or {}
    web_search_cfg = ext_config.get("webSearchConfig", {}) or {}

    # 1. 处理文件/文档上传（优先级最高，与意图无关）
    if image_path:
        # 支持 URL 和本地路径两种格式，从路径中提取扩展名
        # URL 示例: https://oss.example.com/uploads/abc.jpg?token=xxx
        path_for_ext = image_path.split("?")[0] if image_path.startswith("http") else image_path
        ext = os.path.splitext(path_for_ext)[1].lower()

        # 文档类型
        if ext in [".pdf", ".doc", ".docx"]:
            if not routes_cfg.get("file", True):
                logger.info("文件路由已禁用（routes.file=False），降级为 graphrag")
                return "invoke_kg_subgraph"
            logger.info(f"检测到文档: ext={ext}，转为文件查询处理")
            return "create_file_query"
        # 语音类型（.silk/.amr 等）→ 走文件解析节点，由通义千问音频能力处理
        elif ext in [".silk", ".amr", ".mp3", ".wav", ".ogg"]:
            if not routes_cfg.get("file", True):
                logger.info("语音文件路由已禁用，降级为 graphrag")
                return "invoke_kg_subgraph"
            logger.info(f"检测到语音文件: ext={ext}，转为文件查询处理")
            return "create_file_query"
        # 视频类型 → 走文件解析节点
        elif ext in [".mp4", ".avi", ".mov", ".wmv", ".flv"]:
            if not routes_cfg.get("file", True):
                logger.info("视频文件路由已禁用，降级为 graphrag")
                return "invoke_kg_subgraph"
            logger.info(f"检测到视频文件: ext={ext}，转为文件查询处理")
            return "create_file_query"
        # 图片类型
        elif ext in [".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".gif", ".bmp"]:
            if need_image_gen:
                logger.info("检测到图片路径 + 绘画意图，直接路由到 generate_image_node（参考图生成）")
                return "generate_image_node"
            else:
                if not routes_cfg.get("image", True):
                    logger.info("图片路由已禁用（routes.image=False），降级为 graphrag")
                    return "invoke_kg_subgraph"
                logger.info(f"检测到图片: ext={ext}，转为图片查询处理")
                return "create_image_query"
        else:
            # 未知扩展名但有 image_path，尝试走图片解析
            logger.info(f"未知文件类型 ext={ext}，尝试走图片查询处理")
            return "create_image_query"

    # 2. 纯文字绘画意图 → 直接走生成图片节点
    if need_image_gen:
        logger.info("检测到绘画意图（纯文字），直接路由到 generate_image_node")
        return "generate_image_node"

    # 3. 联网搜索开关：支持扩展配置中的 webSearchConfig.enabled 和原有的 configurable.web_search
    web_search_enabled = configurable.get("web_search", False) or web_search_cfg.get("enabled", False)
    if web_search_enabled:
        logger.info("Web Search Enabled: Routing to web_search_query")
        return "web_search_query"

    # 4. 严格按意图识别结果路由，不做额外的知识库检测覆盖
    # Router 已经通过 few-shot + logprobs 置信度保证了分类准确性
    # general = 纯闲聊，直接回复，不触发任何数据库连接
    # graphrag = 业务问题，走完整的 Planner + 工具链路径
    _type = state.router["type"]
    logger.info(f"意图识别结果: type={_type}, logic={state.router.get('logic', '')[:80]}")

    if _type == "general":
        # 检查 general 路由是否被禁用
        if not routes_cfg.get("general", True):
            logger.info("闲聊路由已禁用（routes.general=False），降级为 graphrag")
            return "invoke_kg_subgraph"
        # 纯闲聊寒暄，直接回复，不触发 Neo4j 或 GraphRAG
        return "respond_to_general_query"
    elif _type == "additional":
        # 检查 additional 路由是否被禁用
        if not routes_cfg.get("additional", True):
            logger.info("追问路由已禁用（routes.additional=False），降级为 graphrag")
            return "invoke_kg_subgraph"
        # 问题不完整，追问用户
        return "get_additional_info"
    elif _type == "graphrag":
        # 业务问题：走 Guardrails → Planner → 并行工具链 → 幻觉检测
        return "invoke_kg_subgraph"
    elif _type == "image":
        # 检查 image 路由是否被禁用
        if not routes_cfg.get("image", True):
            logger.info("图片路由已禁用（routes.image=False），降级为 graphrag")
            return "invoke_kg_subgraph"
        return "create_image_query"
    elif _type == "file":
        # 检查 file 路由是否被禁用
        if not routes_cfg.get("file", True):
            logger.info("文件路由已禁用（routes.file=False），降级为 graphrag")
            return "invoke_kg_subgraph"
        return "create_file_query"
    else:
        # 兜底：未知类型默认闲聊回复
        logger.warning(f"未知路由类型 {_type}，降级为 respond_to_general_query")
        return "respond_to_general_query"
    
async def respond_to_general_query(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """生成对一般查询的响应。
    
    支持 AgentConfigExtended 中的 deepThinkingConfig：
    - enabled=True 时使用 deepThinkingConfig.model 指定的模型（默认 deepseek-reasoner）
    - 同时兼容原有的 configurable.deep_thinking 开关
    """
    logger.info("-----generate general response-----")
    
    # 从扩展配置中获取深度思考设置
    ext_config = _get_extended_config(config)
    deep_thinking_cfg = ext_config.get("deepThinkingConfig", {}) or {}
    
    configurable = config.get("configurable", {})
    is_deep_thinking = configurable.get("deep_thinking", False) or deep_thinking_cfg.get("enabled", False)
    logger.info(f"General Query - Deep Thinking: {is_deep_thinking}")
    
    model_name = "deepseek-chat"  # 默认模型
    if is_deep_thinking:
        # 优先使用扩展配置中指定的模型名称
        model_name = deep_thinking_cfg.get("model", "deepseek-reasoner")
        logger.info(f"Switching to {model_name} for deep thinking")
    
    # 使用大模型生成回复
    model = _create_deepseek_model(tags=["general_query"], model_name=model_name)
    
    # 优先使用用户配置的智能体提示词，否则使用默认提示词
    user_agent_prompt = configurable.get("agent_system_prompt", "").strip()
    if user_agent_prompt:
        system_prompt = user_agent_prompt
    else:
        system_prompt = GENERAL_QUERY_SYSTEM_PROMPT.format(
            logic=state.router["logic"]
        )
    
    if is_deep_thinking:
        logger.info("Deep Thinking Enabled: Using deep thinking model")
        system_prompt += "\n深度思考模式：一步步分析，但回答依然简洁口语化，不要用格式符号。"

    # DeepSeek 官方文档：多轮对话中，上一轮的 reasoning_content 不应传入下一轮上下文
    # 同时应用历史衰减：根据配置保留最近 N 条消息
    mem_limit = _get_memory_limit(config)
    cleaned_messages = _get_recent_messages(state.messages, max_messages=mem_limit)
    messages = [{"role": "system", "content": system_prompt}] + cleaned_messages
    response = await model.ainvoke(messages)
    return {"messages": [response]}

async def web_search_query(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """执行联网搜索并生成回复。
    
    支持 AgentConfigExtended 中的配置：
    - deepThinkingConfig：深度思考模式，使用指定的推理模型
    - webSearchConfig.searchResultCount：自定义搜索结果数量
    """
    logger.info("-----Executing Web Search-----")
    logger.info(f"Config received in web_search_query: {config}")
    
    # 获取扩展配置
    ext_config = _get_extended_config(config)
    web_search_cfg = ext_config.get("webSearchConfig", {}) or {}
    deep_thinking_cfg = ext_config.get("deepThinkingConfig", {}) or {}
    
    # 搜索结果数量：优先使用扩展配置，默认 5
    num_results = web_search_cfg.get("searchResultCount", 5)
    
    query = state.messages[-1].content
    search_tool = SearchTool()
    results = search_tool.search(query, num_results=num_results)
    
    context = ""
    if results:
        context = "\n".join([f"- [{r['title']}]({r['url']}): {r['snippet']}" for r in results])
    else:
        context = "未找到相关搜索结果。"
        
    logger.info(f"Search Results: {len(results)} items")
    
    # 深度思考开关：兼容扩展配置和原有开关
    configurable = config.get("configurable", {})
    is_deep_thinking = configurable.get("deep_thinking", False) or deep_thinking_cfg.get("enabled", False)
    logger.info(f"Deep Thinking Toggle: {is_deep_thinking}, Config: {configurable}")

    # 优先使用用户配置的智能体提示词，否则使用默认提示词
    user_agent_prompt = configurable.get("agent_system_prompt", "").strip()
    if user_agent_prompt:
        system_prompt = f"""{user_agent_prompt}

以下是联网搜索结果，请结合搜索结果回答用户问题。搜索结果不够就说明。引用来源。像微信聊天一样说话，简短直接，绝对不要用markdown格式，用中文。

搜索结果：
{context}
"""
    else:
        system_prompt = f"""根据搜索结果回答问题。搜索结果不够就说明。引用来源。像微信聊天一样说话，简短直接，绝对不要用markdown格式，用中文。

搜索结果：
{context}
"""

    if is_deep_thinking:
        system_prompt += "\n深度思考模式：综合分析给出见解，但依然简洁口语化，不要用格式符号。"

    model_name = "deepseek-chat"  # 默认模型
    if is_deep_thinking:
        model_name = deep_thinking_cfg.get("model", "deepseek-reasoner")
        logger.info(f"Switching to {model_name} for deep thinking mode")
    
    logger.info(f"Using model: {model_name}")
    model = _create_deepseek_model(tags=["web_search"], model_name=model_name)
    # DeepSeek 官方文档：多轮对话中清除 reasoning_content，应用历史衰减
    mem_limit = _get_memory_limit(config)
    cleaned_messages = _get_recent_messages(state.messages, max_messages=mem_limit)
    messages = [{"role": "system", "content": system_prompt}] + cleaned_messages
    
    response = await model.ainvoke(messages)
    return {"messages": [response]}


async def get_additional_info(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """生成一个响应，要求用户提供更多信息。
    """
    logger.info("------continue to get additional info------")
    
    # 使用大模型生成回复
    model = _create_deepseek_model(tags=["additional_info"])

    # 如果用户的问题是电商相关，但与自己的业务无关，则需要返回"无关问题"

    # 首先连接 Neo4j 图数据库
    neo4j_graph = None
    try:
        neo4j_graph = get_neo4j_graph()
        logger.info("success to get Neo4j graph database connection")
    except Exception as e:
        logger.error(f"failed to get Neo4j graph database connection: {e}")

    # 动态从 Neo4j 图表中获取图表结构
    graph_context = (
        f"\n参考图表结构来回答:\n{retrieve_and_parse_schema_from_graph_for_prompts(neo4j_graph)}"
        if neo4j_graph is not None
        else ""
    )

    message = graph_context + "\nQuestion: {question}"

    # 拼接提示模版
    full_system_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                GUARDRAILS_SYSTEM_PROMPT,
            ),
            (
                "human",
                (message),
            ),
        ]
    )

    # 构建格式化输出的 Chain， 如果匹配，返回 continue，否则返回 end
    guardrails_chain = full_system_prompt | model.with_structured_output(AdditionalGuardrailsOutput)
    guardrails_output = await guardrails_chain.ainvoke(
            {"question": state.messages[-1].content if state.messages else ""}
        )

    # 根据格式化输出的结果，返回不同的响应
    if guardrails_output.decision == "end":
        logger.info("-----Fail to pass guardrails check, routing to general query-----")
        return await respond_to_general_query(state, config=config)
    else:
        logger.info("-----Pass guardrails check-----")
        system_prompt = GET_ADDITIONAL_SYSTEM_PROMPT.format(
            logic=state.router["logic"]
        )
        mem_limit = _get_memory_limit(config)
        cleaned_messages = _get_recent_messages(state.messages, max_messages=mem_limit)
        messages = [{"role": "system", "content": system_prompt}] + cleaned_messages
        response = await model.ainvoke(messages)
        return {"messages": [response]}

async def create_image_query(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """处理图片查询并生成描述回复
    
    优先使用通义千问视觉模型（通过 URL 直接解析），回退到 Gemini（本地文件 base64）。
    """
    logger.info("-----Found User Upload Image-----")
    configurable = config.get("configurable", {})
    image_path = configurable.get("image_path", None)

    if not image_path:
        logger.warning("User Upload Image Not Found: image_path is None")
        return {"messages": []}

    # 获取扩展配置中的多模态设置
    ext_config = _get_extended_config(config)
    multi_modal_cfg = ext_config.get("multiModalConfig", {}) or {}
    vision_model = multi_modal_cfg.get("visionModel", "qwen3.5-flash")

    # 判断 image_path 是 URL 还是本地文件路径
    is_url = image_path.startswith("http://") or image_path.startswith("https://")

    try:
        parsed_text = None

        # 优先尝试通义千问视觉模型（需要 URL）
        if is_url:
            try:
                from app.services.qwen_vision_service import qwen_vision_service
                parsed_text = await asyncio.wait_for(
                    asyncio.shield(
                        qwen_vision_service.parse_by_url(
                            file_url=image_path,
                            prompt="你是一个专业的图像分析助手。请详细分析图片中的内容，特别关注产品细节、品牌、型号等信息。",
                            model=vision_model,
                            timeout=55.0,
                        )
                    ),
                    timeout=58.0,
                )
                if parsed_text:
                    logger.info(f"通义千问 {vision_model} 图片解析成功")
            except Exception as qwen_err:
                logger.warning(f"通义千问视觉解析失败，回退到 Gemini: {qwen_err}")

        # 回退到 Gemini（本地文件 base64 方式）
        if not parsed_text and Path(image_path).exists():
            from app.services.gemini_service import gemini_service
            parsed_text = await asyncio.wait_for(
                asyncio.shield(
                    gemini_service.parse_file(
                        image_path,
                        prompt="你是一个专业的图像分析助手。请详细分析图片中的内容，特别关注产品细节、品牌、型号等信息。",
                        timeout=55.0,
                    )
                ),
                timeout=58.0,
            )
            if parsed_text:
                logger.info("Gemini 图片解析成功（回退）")

        if not parsed_text:
            logger.error("所有多模态模型均解析失败")
            return {"messages": []}

        # 解析完成后，将图片描述注入到用户消息中，走完整的知识库检索流程
        # 取出原始用户消息，拼接图片解析内容，让 invoke_kg_subgraph 处理
        logger.info("图片解析完成，将解析内容注入用户消息，转入完整智能体流程")
        original_query = state.messages[-1].content if state.messages else ""
        enriched_query = f"{original_query}\n\n【图片内容】：{parsed_text}" if original_query else f"【图片内容】：{parsed_text}"

        # 构造注入了图片描述的新 state，调用 invoke_kg_subgraph 走完整流程
        from langchain_core.messages import HumanMessage
        import dataclasses
        enriched_messages = list(state.messages[:-1]) + [HumanMessage(content=enriched_query)]
        enriched_state = dataclasses.replace(state, messages=enriched_messages)
        return await invoke_kg_subgraph(enriched_state, config=config)

    except asyncio.TimeoutError:
        logger.error(f"图片分析超时: {image_path[:60]}")
        return {"messages": []}
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        return {"messages": []}

async def create_file_query(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[BaseMessage]]:
    """使用多模态模型处理文件（PDF/Word/语音等）查询并生成描述回复
    
    优先使用通义千问视觉模型（通过 URL 直接解析），回退到 Gemini（本地文件 base64）。
    语音/视频文件优先使用 SenseVoice Small 转写为文本。
    """
    logger.info("-----Found User Upload File-----")
    configurable = config.get("configurable", {})
    file_path = configurable.get("image_path", None)

    if not file_path:
        logger.warning("User Upload File Not Found: file_path is None")
        return {"messages": [AIMessage(content="抱歉，我无法查看这个文件，请重新上传。")]}

    # 获取扩展配置中的多模态设置
    ext_config = _get_extended_config(config)
    multi_modal_cfg = ext_config.get("multiModalConfig", {}) or {}
    vision_model = multi_modal_cfg.get("visionModel", "qwen3.5-flash")

    # 判断 file_path 是 URL 还是本地文件路径
    is_url = file_path.startswith("http://") or file_path.startswith("https://")

    # 根据扩展名区分文档 / 语音 / 视频
    path_for_ext = file_path.split("?")[0] if is_url else file_path
    ext = os.path.splitext(path_for_ext)[1].lower()
    audio_exts = [".silk", ".amr", ".mp3", ".wav", ".ogg", ".m4a"]
    video_exts = [".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv"]

    try:
        parsed_text = None
        prompt = "你是一个专业的文档分析助手。请详细分析并总结该文档的内容，包括核心观点、关键数据和重要结论。"

        # 语音/视频文件：优先使用 SenseVoice Small 转写为文本
        if ext in audio_exts or ext in video_exts:
            logger.info(f"检测到语音/视频文件 ext={ext}，优先使用 SenseVoice Small 转写为文本")
            parsed_text = await _transcribe_media_with_asr(file_path, ext.lstrip("."))
            if parsed_text:
                logger.info("SenseVoice Small 语音转写成功，将转写文本注入用户消息")
            else:
                logger.warning("SenseVoice Small 语音转写失败，回退到通义千问 / Gemini 文件解析")

        # 文档或 ASR 失败的回退：使用通义千问视觉模型 + Gemini
        if not parsed_text:
            # 优先尝试通义千问视觉模型（需要 URL）
            if is_url:
                try:
                    from app.services.qwen_vision_service import qwen_vision_service
                    parsed_text = await asyncio.wait_for(
                        asyncio.shield(
                            qwen_vision_service.parse_by_url(
                                file_url=file_path,
                                prompt=prompt,
                                model=vision_model,
                                timeout=55.0,
                            )
                        ),
                        timeout=58.0,
                    )
                    if parsed_text:
                        logger.info(f"通义千问 {vision_model} 文件解析成功")
                except Exception as qwen_err:
                    logger.warning(f"通义千问视觉文件解析失败，回退到 Gemini: {qwen_err}")

            # 回退到 Gemini（本地文件 base64 方式）
            if not parsed_text and Path(file_path).exists():
                from app.services.gemini_service import gemini_service
                parsed_text = await asyncio.wait_for(
                    gemini_service.parse_file(file_path, prompt=prompt, timeout=55.0),
                    timeout=58.0,
                )
                if parsed_text:
                    logger.info("Gemini 文件解析成功（回退）")

        if not parsed_text:
            logger.error("所有多模态模型均文件解析失败")
            return {"messages": [AIMessage(content="抱歉，我解析不了这个文件，请稍后再试。")]}

        # 解析/转写完成后，将内容注入到用户消息中，走完整的知识库检索流程
        logger.info("文件解析完成，将解析内容注入用户消息，转入完整智能体流程")
        from langchain_core.messages import HumanMessage
        import dataclasses
        original_query = state.messages[-1].content if state.messages else ""
        enriched_query = f"{original_query}\n\n【文件内容】：{parsed_text}" if original_query else f"【文件内容】：{parsed_text}"
        enriched_messages = list(state.messages[:-1]) + [HumanMessage(content=enriched_query)]

        # AgentState may be either a dataclass (current implementation) or a Pydantic model
        # in some deployments. Use model_copy when available, otherwise fall back to
        # dataclasses.replace to avoid AttributeError: 'AgentState' object has no attribute 'model_copy'.
        if hasattr(state, "model_copy"):
            enriched_state = state.model_copy(update={"messages": enriched_messages})  # type: ignore[call-arg]
        else:
            enriched_state = dataclasses.replace(state, messages=enriched_messages)

        return await invoke_kg_subgraph(enriched_state, config=config)

    except asyncio.TimeoutError:
        logger.error(f"文件分析超时: {file_path[:60]}")
        return {"messages": [AIMessage(content="文件解析超时，请稍后重试。")]}
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}", exc_info=True)
        return {"messages": [AIMessage(content="抱歉，解析文件时出错。")]}


async def _transcribe_media_with_asr(file_path: str, audio_format_hint: str) -> str | None:
    """
    Transcribe audio/video file to text using ASR services.
    Priority:
    1. douyin ASR Server (same as Next.js voice-processor.ts)
    2. Qwen ASR API (fallback)

    Args:
        file_path: Public URL or local path of the media file.
        audio_format_hint: File extension without dot, e.g. "mp3", "wav", "mp4".

    Returns:
        Transcribed text if successful, otherwise None.
    """
    import httpx
    import asyncio

    is_url = file_path.startswith("http://") or file_path.startswith("https://")

    tmp_dir: str | None = None
    raw_path = file_path
    audio_format = audio_format_hint.lstrip(".").lower() or "mp3"

    try:
        # Download remote media into a temporary directory
        if is_url:
            tmp_dir = tempfile.mkdtemp(prefix="media_asr_")
            raw_path = os.path.join(tmp_dir, f"media.{audio_format}")

            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(file_path)
                if resp.status_code != 200:
                    logger.warning(f"ASR 媒体下载失败: HTTP {resp.status_code}")
                    return None
                with open(raw_path, "wb") as f:
                    f.write(resp.content)
            logger.info(f"ASR 媒体下载完成: size={len(resp.content)} bytes, path={raw_path}")
        else:
            # Local file: ensure it exists
            if not os.path.exists(raw_path):
                logger.warning(f"ASR 本地媒体文件不存在: {raw_path}")
                return None
            # For local files we still normalize into WAV in a temp dir
            tmp_dir = tempfile.mkdtemp(prefix="media_asr_")
            dest_path = os.path.join(tmp_dir, os.path.basename(raw_path))
            shutil.copy2(raw_path, dest_path)
            raw_path = dest_path

        # Priority 1: Use douyin ASR Server (same as Next.js voice-processor.ts)
        asr_server_url = os.environ.get("DOUYIN_ASR_SERVER_URL", "http://host.docker.internal:3333")
        logger.info(f"ASR 尝试连接 douyin ASR Server: {asr_server_url}")

        text = await _transcribe_with_douyin_asr(raw_path, asr_server_url, audio_format)
        if text:
            logger.info(f"ASR 使用 douyin ASR Server 成功: text_len={len(text)}")
            return text.strip()

        # Priority 2: Fallback to Qwen ASR API
        logger.warning("douyin ASR Server 失败，回退到 Qwen ASR API")
        text, engine = await _transcribe_with_qwen_asr(raw_path, audio_format)
        if text:
            logger.info(f"ASR 使用通义千问成功: engine={engine}, text_len={len(text)}")
            return text.strip()

        logger.warning("ASR 所有引擎均识别失败")
        return None

    except Exception as e:  # noqa: BLE001
        logger.error(f"ASR 媒体转写异常: {e}", exc_info=True)
        return None
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


async def _transcribe_with_douyin_asr(
    audio_path: str,
    asr_server_url: str,
    audio_format: str,
    timeout: float = 60.0,
) -> str | None:
    """
    Call douyin ASR Server for speech recognition.
    This is the same ASR service used by Next.js voice-processor.ts.

    Args:
        audio_path: Local path to the audio file.
        asr_server_url: Base URL of the ASR server.
        audio_format: Audio format (e.g., "mp3", "wav").
        timeout: Request timeout in seconds.

    Returns:
        Transcribed text if successful, otherwise None.
    """
    import httpx

    try:
        # Read audio file content
        with open(audio_path, "rb") as f:
            file_content = f.read()

        # Determine MIME type
        mime_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "amr": "audio/amr",
            "silk": "audio/silk",
            "m4a": "audio/mp4",
        }
        mime_type = mime_map.get(audio_format.lower(), "audio/mpeg")

        # Create multipart form data
        files = {
            "file": (f"audio.{audio_format}", file_content, mime_type),
        }
        data = {
            "videoId": f"asr_{int(asyncio.get_event_loop().time() * 1000)}",
        }

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(
                f"{asr_server_url}/api/transcribe",
                files=files,
                data=data,
            )

            if resp.status_code == 200:
                result = resp.json()
                # Same response format as Next.js asr-client.ts
                transcript = result.get("transcript")
                if transcript:
                    logger.info(f"douyin ASR Server 识别成功: {transcript[:50]}...")
                    return transcript
                else:
                    logger.warning(f"douyin ASR Server 响应缺少 transcript 字段: {result}")
            else:
                logger.warning(f"douyin ASR Server 请求失败: HTTP {resp.status_code}, {resp.text[:200]}")

    except httpx.TimeoutException:
        logger.warning(f"douyin ASR Server 请求超时 ({timeout}s)")
    except httpx.ConnectError as e:
        logger.warning(f"douyin ASR Server 连接失败: {e}")
    except Exception as e:
        logger.warning(f"douyin ASR Server 调用异常: {e}")

    return None


def _convert_to_wav(input_path: str, output_path: str, audio_format: str) -> bool:
    """
    Use ffmpeg to convert audio to 16kHz mono WAV format.
    Returns True if conversion succeeded.
    """
    import subprocess

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ar", "16000",   # Sample rate 16kHz (SenseVoice requirement)
            "-ac", "1",       # Mono
            "-f", "wav",
            output_path
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"[ASR] ffmpeg conversion succeeded: {input_path} -> {output_path}")
            return True
        else:
            logger.warning(f"[ASR] ffmpeg conversion failed: {result.stderr[-200:]}")
            return False
    except FileNotFoundError:
        logger.warning("[ASR] ffmpeg not installed, skipping format conversion")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("[ASR] ffmpeg conversion timeout")
        return False
    except Exception as e:
        logger.warning(f"[ASR] ffmpeg conversion exception: {e}")
        return False


async def _transcribe_with_sense_voice(wav_path: str) -> tuple[Optional[str], str]:
    """
    Use sherpa-onnx SenseVoice Small model for speech recognition.
    Returns (transcribed_text, engine_name), or (None, "sense_voice") on failure.
    """
    import httpx

    def _sync_transcribe():
        try:
            import sherpa_onnx
            import wave
            import numpy as np

            # Find model files
            models_dir = os.environ.get(
                "SENSE_VOICE_MODEL_DIR",
                os.path.join(os.path.dirname(__file__), "..", "..", "models", "asr", "sense-voice")
            )
            models_dir = os.path.abspath(models_dir)

            model_file = None
            tokens_file = None

            # Recursively search for .onnx and tokens.txt
            for root, dirs, files in os.walk(models_dir):
                for f in files:
                    fpath = os.path.join(root, f)
                    if f.endswith(".onnx") and model_file is None:
                        model_file = fpath
                    if f == "tokens.txt" and tokens_file is None:
                        tokens_file = fpath
                if model_file and tokens_file:
                    break

            if not model_file or not tokens_file:
                logger.info(f"[ASR] SenseVoice model not found, skipping: models_dir={models_dir}")
                return None

            logger.info(f"[ASR] Using SenseVoice model: {model_file}")

            # Create recognizer
            recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=model_file,
                tokens=tokens_file,
                num_threads=2,
                use_itn=True,
                debug=False,
            )

            # Read WAV file
            with wave.open(wav_path, "rb") as wf:
                sample_rate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())

            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

            # Process in chunks (30 seconds each)
            chunk_size = sample_rate * 30
            all_text = []
            for i in range(0, len(samples), chunk_size):
                chunk = samples[i:i + chunk_size]
                stream = recognizer.create_stream()
                stream.accept_waveform(sample_rate, chunk.tolist())
                recognizer.decode_stream(stream)
                t = stream.result.text.strip()
                if t:
                    all_text.append(t)

            return " ".join(all_text)

        except ImportError:
            logger.info("[ASR] sherpa_onnx not installed, skipping SenseVoice")
            return None
        except Exception as e:
            logger.warning(f"[ASR] SenseVoice recognition failed: {e}")
            return None

    # Run synchronous transcription in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _sync_transcribe)
    return (text, "sense_voice") if text is not None else (None, "sense_voice")


async def _transcribe_with_qwen_asr(audio_path: str, audio_format: str) -> tuple[Optional[str], str]:
    """
    Use Qwen ASR API for speech recognition (fallback).
    Requires QWEN_API_KEY environment variable.
    Returns (transcribed_text, engine_name), or (None, "qwen_asr") on failure.
    """
    import httpx
    import base64

    qwen_api_key = os.environ.get("QWEN_API_KEY", "")
    if not qwen_api_key:
        logger.info("[ASR] QWEN_API_KEY not configured, skipping Qwen ASR")
        return None, "qwen_asr"

    try:
        # Read audio file and base64 encode
        with open(audio_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode("utf-8")

        # Determine MIME type
        mime_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "amr": "audio/amr",
            "silk": "audio/silk",
            "m4a": "audio/mp4",
        }
        mime_type = mime_map.get(audio_format.lower(), "audio/mpeg")

        # Call Qwen multimodal API (supports audio input)
        payload = {
            "model": "qwen-audio-turbo",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "audio": f"data:{mime_type};base64,{audio_data}"
                            },
                            {
                                "text": "请将这段语音转录为文字，只输出转录文本，不要添加任何解释。"
                            }
                        ]
                    }
                ]
            }
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                headers={
                    "Authorization": f"Bearer {qwen_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", [{}])[0].get("text", "")
                if text:
                    logger.info(f"[ASR] Qwen ASR recognition succeeded: {text[:50]}")
                    return text.strip(), "qwen_asr"
            else:
                logger.warning(f"[ASR] Qwen ASR failed: HTTP {resp.status_code}, {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"[ASR] Qwen ASR exception: {e}")

    return None, "qwen_asr"


async def create_research_plan(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, List[str] | str]:
    """直接查询 GraphRAG 知识库，不做任何预判断。

    用户提问随机性大，不应该预先分类。直接用 GraphRAG 向量检索召回相关内容，
    让大模型基于召回内容回答。如果知识库没有相关内容，再给通用回复。
    """
    logger.info("------直接查询 GraphRAG 知识库------")

    # 获取用户问题和对话历史
    last_message = state.messages[-1].content if state.messages else ""

    # 格式化对话历史（应用衰减：根据配置保留最近 N 条消息，不含当前问题）
    mem_limit = _get_memory_limit(config)
    chat_history = ""
    if len(state.messages) > 1:
        history_lines = []
        recent_history = _get_recent_messages(state.messages[:-1], max_messages=mem_limit)
        for msg in recent_history:
            if isinstance(msg, AIMessage):
                role = "助手"
            else:
                role = "用户"
            content = msg.content if hasattr(msg, 'content') else str(msg)
            if content and content.strip():
                history_lines.append(f"{role}: {content[:800]}")
        chat_history = "\n".join(history_lines)
        if chat_history:
            logger.info(f"对话历史: {len(history_lines)} 条消息（已衰减至最近30条）")

    # 从 config 获取 user_id
    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id")

    if not user_id:
        logger.warning("No user_id in config")
        return {"messages": [AIMessage(content="系统配置错误，请重试")]}

    # 直接调用 GraphRAG API 查询
    try:
        from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.customer_tools.node import _get_user_storage_dir, _get_all_user_storage_dirs, GraphRAGAPI

        storage_dirs = _get_all_user_storage_dirs(user_id)
        logger.info(f"查询用户知识库，共 {len(storage_dirs)} 个文档目录: {storage_dirs}")

        # ★ 按智能体绑定的 knowledgeBaseIds 过滤目录
        ext_config = _get_extended_config(config)
        kb_ids = ext_config.get("knowledgeBaseIds") or []
        storage_dirs = _filter_storage_dirs_by_kb_ids(storage_dirs, kb_ids)

        if not storage_dirs:
            logger.warning(f"用户知识库不存在: {_get_user_storage_dir(user_id)}")
            return {"messages": [AIMessage(content="知识库暂无内容，请先上传文档")]}

        # 并发查询所有文档目录，合并结果
        async def _query_one(storage_dir: str) -> str:
            try:
                api = GraphRAGAPI(storage_dir)
                result = await api.query_graphrag(last_message)
                return result.get("response", "")
            except Exception as e:
                logger.warning(f"查询目录 {storage_dir} 失败: {e}")
                return ""

        responses = await asyncio.gather(*[_query_one(d) for d in storage_dirs])
        # 每个目录单独判断是否有效，取第一个有实质内容的回答
        # 不做全局合并（避免"无答案"污染有效答案）
        no_answer_indicators = [
            "没有这方面", "没有具体信息", "没有相关信息", "没有确切",
            "目前没有", "暂无相关", "未找到相关", "没有找到相关",
            "无法确定", "没有找到",
            "I don't have", "no information", "not found",
            "智语科技", "AI智能体开发平台", "广东深华", "教育投资集团",
        ]
        def _is_valid_response(r: str) -> bool:
            if not r or not r.strip():
                return False
            # 必须超过50字才算有实质内容（排除纯"没有信息"短句）
            if len(r.strip()) < 50:
                return any(ind not in r for ind in no_answer_indicators)
            # 长回复：只要不是全部都是"无答案"词就算有效
            no_answer_count = sum(1 for ind in no_answer_indicators if ind in r)
            # 超过3个无答案词才判定为无效
            return no_answer_count < 3

        valid_responses = [r.strip() for r in responses if _is_valid_response(r)]
        graphrag_response = "\n\n".join(valid_responses)
        graphrag_context = {}

        logger.info(f"GraphRAG 查询结果长度: {len(graphrag_response)}")

        # 打印上下文内容，用于调试
        if graphrag_context:
            logger.info(f"GraphRAG 上下文键: {list(graphrag_context.keys())}")

        if not graphrag_response or graphrag_response.strip() == "":
            # 知识库为空，尝试 admin 公共知识库
            ADMIN_USER_ID = 1
            if user_id != ADMIN_USER_ID:
                admin_dirs = _get_all_user_storage_dirs(ADMIN_USER_ID)
                if admin_dirs:
                    logger.info(f"尝试 admin 公共知识库，共 {len(admin_dirs)} 个目录")
                    admin_responses = await asyncio.gather(*[_query_one(d) for d in admin_dirs])
                    valid_admin = [r.strip() for r in admin_responses if _is_valid_response(r)]
                    graphrag_response = "\n\n".join(valid_admin)
        has_real_answer = False
        if graphrag_response and graphrag_response.strip():
            # 清理掉各目录"无答案"短句前缀，只保留有实质内容的部分
            cleaned_lines = []
            for line in graphrag_response.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                # 跳过纯"无答案"短句（长度短且包含无答案词）
                if len(line_stripped) < 30 and any(ind in line_stripped for ind in no_answer_indicators):
                    continue
                cleaned_lines.append(line)
            graphrag_response = "\n".join(cleaned_lines).strip()

            logger.info(f"GraphRAG 原始结果: {graphrag_response[:200]}")
            # 超过3个无答案词才判定为无效（单个词可能只是回答中的一句话）
            no_answer_count = sum(1 for ind in no_answer_indicators if ind in graphrag_response)
            is_no_answer = no_answer_count >= 3

            if is_no_answer:
                logger.info(f"GraphRAG 返回了无效回复（无答案词={no_answer_count}），触发自动联网搜索")
                has_real_answer = False
            else:
                has_real_answer = True

        if has_real_answer:
            # 有真正的答案，结合用户自定义提示词（角色规则）+ 知识库内容一次性生成回答
            agent_system_prompt = configurable.get("agent_system_prompt", "").strip()
            if agent_system_prompt:
                try:
                    role_model = _create_deepseek_model(tags=["agent_role_answer"])
                    role_messages = [
                        {"role": "system", "content": (
                            f"{agent_system_prompt}\n\n"
                            "---\n"
                            "【知识库资料】以下是检索到的相关内容，请结合资料按照上述角色设定回答用户问题。\n"
                            "资料中没有的内容，按角色限制范围说明无法回答，不要编造。\n"
                            "禁止使用任何 markdown 格式，用自然语言口语化表达。"
                        )},
                        {"role": "user", "content": (
                            f"知识库资料：{graphrag_response}\n\n"
                            f"用户问题：{last_message}"
                        )},
                    ]
                    role_response = await role_model.ainvoke(role_messages)
                    return {"messages": [role_response]}
                except Exception as role_err:
                    logger.warning(f"角色回答失败，直接返回原始答案: {role_err}")
            return {"messages": [AIMessage(content=graphrag_response)]}

        # ★ 知识库无答案，自动尝试联网搜索
        logger.info("GraphRAG 未找到有效答案，自动启用联网搜索")
        try:
            search_tool = SearchTool()
            search_results = search_tool.search(last_message, num_results=5)
            
            if search_results:
                context = "\n".join([f"- [{r['title']}]({r['url']}): {r['snippet']}" for r in search_results])
                logger.info(f"自动联网搜索找到 {len(search_results)} 条结果")
                
                # 用搜索结果让 LLM 生成回答
                search_model = _create_deepseek_model(tags=["auto_web_search"])
                search_prompt = f"""知识库没有找到答案，以下是联网搜索的结果，请根据搜索结果回答用户的问题。
搜索结果不够就说明。引用来源。像微信聊天一样说话，简短直接，绝对不要用markdown格式，用中文。

搜索结果：
{context}
"""
                mem_limit = _get_memory_limit(config)
                cleaned_messages = _get_recent_messages(state.messages, max_messages=mem_limit)
                messages = [{"role": "system", "content": search_prompt}] + cleaned_messages
                response = await search_model.ainvoke(messages)
                return {"messages": [response]}
        except Exception as search_err:
            logger.error(f"自动联网搜索失败: {search_err}", exc_info=True)

        # ★ 联网搜索也失败了，生成相关问题推荐
        logger.info("联网搜索也未找到有效答案，生成相关问题推荐")

        try:
            related_questions = await _generate_related_questions(
                api if storage_dirs else None,
                last_message,
                storage_dirs[0] if storage_dirs else ""
            )

            if related_questions:
                fallback_msg = f"这个问题我暂时没有直接的资料。不过，我可以帮你了解以下相关内容：\n\n{related_questions}\n\n你想了解哪个方面呢？"
                logger.info(f"生成了相关问题推荐: {related_questions[:100]}")
            else:
                fallback_msg = "这个暂时没有确切资料，你可以换个问法或者问问其他的"

            return {"messages": [AIMessage(content=fallback_msg)]}

        except Exception as e:
            logger.error(f"生成相关问题失败: {e}", exc_info=True)
            fallback_msg = "这个暂时没有确切资料，你可以换个问法或者问问其他的"
            return {"messages": [AIMessage(content=fallback_msg)]}

    except Exception as e:
        logger.error(f"GraphRAG 查询失败: {e}", exc_info=True)
        return {"messages": [AIMessage(content="查询出错了，请稍后重试")]}

async def check_hallucinations(
    state: AgentState, *, config: RunnableConfig
) -> dict[str, Any]:
    """幻觉检测节点：通过四种方式综合判断答案是否存在幻觉。
    
    支持 AgentConfigExtended 中的 hallucinationDetectionConfig：
    - enabled=False 时跳过幻觉检测，直接返回通过
    - maxRetries 自定义最大重试次数（默认 1）
    
    检测方式（任一触发即标记为可疑）：
    1. 知识溯源  — difflib 相似度，答案与上下文相似度 < 0.1 且答案较长时可疑
    2. 数值一致性 — 正则提取数值，答案含数值但上下文完全不含时可疑
    3. 实体存在性 — 规则匹配中文实体，超过 50% 的实体不在上下文中时可疑
    4. LLM 辅助  — deepseek-reasoner + GradeHallucinations 结构化输出
    
    重试策略：hallucination_retry < maxRetries 时触发重新查询，否则直接返回当前答案。
    """
    # 获取扩展配置中的幻觉检测设置
    ext_config = _get_extended_config(config)
    hallucination_cfg = ext_config.get("hallucinationDetectionConfig", {}) or {}
    hallucination_enabled = hallucination_cfg.get("enabled", True)
    max_retries = hallucination_cfg.get("maxRetries", 1)

    # 微信等场景：如果 state 中明确要求跳过，则直接返回
    if getattr(state, "skip_hallucination", False):
        logger.info("微信场景或显式请求：跳过幻觉检测以加速回复")
        return {"hallucination": GradeHallucinations(binary_score="1")}

    # 如果幻觉检测被禁用，直接返回通过
    if not hallucination_enabled:
        logger.info("幻觉检测已禁用（hallucinationDetectionConfig.enabled=False），跳过检测")
        return {"hallucination": GradeHallucinations(binary_score="1")}

    logger.info(f"---幻觉检测：开始四种方式综合检测（maxRetries={max_retries}）---")

    # 获取答案和上下文
    answer = state.messages[-1].content if state.messages else ""
    context = state.documents or ""
    is_suspicious = False

    # ── 方式1：知识溯源（difflib 相似度）──────────────────────────────
    try:
        similarity = difflib.SequenceMatcher(None, answer, context).ratio()
        logger.info(f"幻觉检测方式1（知识溯源）: 相似度={similarity:.4f}")
        # 相似度极低且答案有实质内容时，说明答案与检索内容严重偏离
        if similarity < 0.1 and len(answer) > 50 and context:
            logger.warning(f"幻觉检测方式1 触发：相似度={similarity:.4f} < 0.1，答案长度={len(answer)}")
            is_suspicious = True
    except Exception as e:
        logger.warning(f"幻觉检测方式1 失败，跳过: {e}")

    # ── 方式2：数值一致性（正则表达式）────────────────────────────────
    if not is_suspicious:
        try:
            nums_answer = set(re.findall(r'\d+\.?\d*', answer))
            nums_context = set(re.findall(r'\d+\.?\d*', context))
            logger.info(f"幻觉检测方式2（数值一致性）: 答案数值={nums_answer}, 上下文数值={nums_context}")
            # 答案中有数值但上下文完全没有 → 数值可能是编造的
            if nums_answer and not nums_context and context:
                logger.warning(f"幻觉检测方式2 触发：答案含数值 {nums_answer} 但上下文无任何数值")
                is_suspicious = True
        except Exception as e:
            logger.warning(f"幻觉检测方式2 失败，跳过: {e}")

    # ── 方式3：实体存在性（规则关键词匹配）────────────────────────────
    if not is_suspicious:
        try:
            # 提取答案中的中文名词短语（2-8个连续汉字）
            entities = re.findall(r'[\u4e00-\u9fa5]{2,8}', answer)
            if entities and context:
                # 只检查前10个实体，避免过度检测
                sample = entities[:10]
                missing = [e for e in sample if e not in context]
                missing_ratio = len(missing) / len(sample)
                logger.info(f"幻觉检测方式3（实体存在性）: 检查={sample}, 缺失={missing}, 缺失率={missing_ratio:.2f}")
                if missing_ratio > 0.5:
                    logger.warning(f"幻觉检测方式3 触发：{missing_ratio:.0%} 的实体不在上下文中")
                    is_suspicious = True
        except Exception as e:
            logger.warning(f"幻觉检测方式3 失败，跳过: {e}")

    # ── 方式4：LLM 辅助校验（deepseek-chat）+ 意图匹配验证 ──────────
    llm_grade = None
    try:
        # 使用 deepseek-chat 进行幻觉校验（reasoner 不支持 tool_choice/structured_output）
        # 单轮独立判断，不携带对话历史
        model = _create_deepseek_model(tags=["hallucinations"], model_name="deepseek-chat")
        
        # 获取用户最新问题，用于意图匹配验证
        user_question = ""
        for msg in reversed(state.messages[:-1]):  # 排除最后一条（AI 回复）
            if hasattr(msg, "type") and msg.type == "human":
                user_question = msg.content
                break
        
        system_prompt = CHECK_HALLUCINATIONS.format(
            documents=context or "（无检索上下文）",
            generation=answer,
        )
        # 在用户消息中加入原始问题，帮助 LLM 判断意图匹配
        user_msg = "请判断以上回复是否存在幻觉，输出 binary_score（1=正常，0=幻觉）。"
        if user_question:
            user_msg = f"用户的原始问题是：「{user_question}」\n\n{user_msg}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]
        llm_grade = cast(
            GradeHallucinations,
            await model.with_structured_output(GradeHallucinations).ainvoke(messages)
        )
        logger.info(f"幻觉检测方式4（LLM辅助）: binary_score={llm_grade.binary_score if llm_grade else 'None'}")
        if llm_grade and llm_grade.binary_score == "0":
            logger.warning("幻觉检测方式4 触发：LLM 判定答案与事实不符")
            is_suspicious = True
    except Exception as e:
        logger.warning(f"幻觉检测方式4（LLM辅助）失败，跳过: {e}")

    # ── 重试策略 ──────────────────────────────────────────────────────
    final_grade = llm_grade or GradeHallucinations(binary_score="1" if not is_suspicious else "0")

    if is_suspicious and state.hallucination_retry < max_retries:
        logger.warning(f"幻觉检测：发现可疑答案，触发重试（当前重试次数={state.hallucination_retry}，最大重试={max_retries}）")
        return {
            "hallucination": GradeHallucinations(binary_score="0"),
            "hallucination_retry": state.hallucination_retry + 1,
        }

    if is_suspicious:
        logger.warning(f"幻觉检测：已达重试上限（retry={state.hallucination_retry}，max={max_retries}），放行当前答案")
        # 达到重试上限，强制放行（binary_score="1"），避免无限循环
        return {"hallucination": GradeHallucinations(binary_score="1")}
    else:
        logger.info("幻觉检测：答案通过所有检测，质量良好")

    return {"hallucination": final_grade}


# 使用内存存储（支持多轮对话，无需额外数据库依赖）
checkpointer = MemorySaver()

# 子图实例：懒加载，第一次调用时初始化（此时 settings 已从数据库加载完毕）
# 不在模块导入时初始化，避免 settings.NEO4J_URL 还是默认的 localhost:7688
_kg_subgraph = None
_kg_subgraph_initialized = False


def _init_kg_subgraph():
    """懒加载初始化子图，确保使用数据库中的 Neo4j 配置。"""
    global _kg_subgraph, _kg_subgraph_initialized
    if _kg_subgraph_initialized:
        return
    _kg_subgraph_initialized = True

    try:
        _neo4j_graph_for_subgraph = None
        try:
            _neo4j_graph_for_subgraph = get_neo4j_graph()
            logger.info(f"子图初始化：Neo4j 连接成功 ({settings.NEO4J_URL})")
        except Exception as _neo4j_err:
            logger.warning(f"子图初始化：Neo4j 连接失败，护栏将降级运行: {_neo4j_err}")

        _kg_subgraph = create_multi_tool_workflow(
            llm=_create_deepseek_model(tags=["kg_subgraph"]),
            graph=_neo4j_graph_for_subgraph,
            # 注册 GraphRAG 工具，tool_selection 节点会优先选择它
            tool_schemas=[microsoft_graphrag_query],
            predefined_cypher_dict={},
            cypher_example_retriever=NorthwindCypherRetriever(),
            scope_description="智能客服业务范围",
        )
        logger.info("子图（Planner + 多工具）初始化成功")
    except Exception as _subgraph_err:
        logger.error(f"子图初始化失败，将降级为直接 GraphRAG 查询: {_subgraph_err}", exc_info=True)
        _kg_subgraph = None


def _format_chat_history(messages: list, max_messages: int = 30) -> str:
    """将消息列表格式化为对话历史字符串，供子图使用。"""
    if not messages:
        return ""
    lines = []
    recent = _get_recent_messages(messages, max_messages=max_messages)
    for msg in recent:
        role = "助手" if isinstance(msg, AIMessage) else "用户"
        content = msg.content if hasattr(msg, "content") else str(msg)
        if content and content.strip():
            lines.append(f"{role}: {content[:800]}")
    return "\n".join(lines)


async def invoke_kg_subgraph(
    state: AgentState, *, config: RunnableConfig
) -> Dict[str, Any]:
    """调用 Planner + 多工具子图，替代原来的 create_research_plan 节点。
    
    将主图 AgentState 转换为子图 InputState，调用子图，提取答案后写回主图。
    子图内部已包含：Guardrails → Planner → 并行工具链 → summarize → final_answer。
    
    降级策略：子图不可用时，回退到原有的直接 GraphRAG 查询逻辑。
    """
    logger.info("------调用 Planner + 多工具子图------")

    # 懒加载子图：此时 settings 已从数据库加载，NEO4J_URL 是正确的远程地址
    _init_kg_subgraph()

    question = state.messages[-1].content if state.messages else ""
    mem_limit = _get_memory_limit(config)
    chat_history = _format_chat_history(state.messages[:-1], max_messages=mem_limit)

    # ── 子图可用：走完整的 Planner + 工具链路径 ──────────────────────
    if _kg_subgraph is not None:
        try:
            subgraph_input = {
                "question": question,
                "chat_history": chat_history,
                "data": [],
                "history": [],
            }
            logger.info(f"子图输入: question={question[:100]}, history_len={len(chat_history)}")

            # 将 user_id 透传到子图 config，customer_tools 节点需要它来定位知识库
            subgraph_config = dict(config) if config else {}
            configurable = dict(subgraph_config.get("configurable", {}))
            user_id = configurable.get("user_id")
            logger.info(f"子图透传 user_id: {user_id}")
            subgraph_config["configurable"] = configurable

            # 用 astream 替代 ainvoke，绕过 LangGraph 0.3.x FuturesDict 回调为 None 的 bug
            # ainvoke 内部在 Map-Reduce 子图完成时触发 on_done 回调，但 callback 为 None 导致 TypeError
            # astream 逐步消费事件流，不依赖 FuturesDict 回调机制
            result = None
            async for chunk in _kg_subgraph.astream(subgraph_input, config=subgraph_config):
                # chunk 是每个节点输出的状态片段，取最后一个包含 answer 的片段
                if isinstance(chunk, dict):
                    # final_answer 节点输出包含 answer 字段
                    if "final_answer" in chunk and "answer" in chunk["final_answer"]:
                        result = chunk["final_answer"]
                    # 兼容直接输出 answer 的情况
                    elif "answer" in chunk:
                        result = chunk

            answer = result.get("answer", "") if isinstance(result, dict) else ""
            logger.info(f"子图输出: answer_len={len(answer)}, answer_preview={answer[:100]}")

            # 过滤"暂无资料"类话术：Neo4j 无数据时子图会生成这类前缀，不应输出给用户
            NO_DATA_PHRASES = [
                "这个暂时没有确切资料",
                "数据库暂无相关数据",
                "暂无相关",
                "没有确切资料",
                "目前知识库中暂无",
                "暂时没有相关",
            ]
            if answer and any(phrase in answer for phrase in NO_DATA_PHRASES):
                logger.warning(f"子图答案含'暂无资料'话术，视为空答案降级: {answer[:100]}")
                answer = ""

            if answer and answer.strip():
                return {
                    "messages": [AIMessage(content=answer)],
                    "documents": answer,
                }
            else:
                logger.warning("子图返回空答案，降级为直接 GraphRAG 查询")
        except Exception as e:
            logger.error(f"子图调用失败，降级为直接 GraphRAG 查询: {e}", exc_info=True)

    # ── 降级路径：直接调用 GraphRAG（原 create_research_plan 逻辑）────
    logger.info("降级路径：直接调用 GraphRAG 知识库")
    result = await create_research_plan(state, config=config)
    # 提取答案写入 documents 供幻觉检测使用
    answer_msg = result.get("messages", [])
    answer_text = answer_msg[-1].content if answer_msg else ""
    result["documents"] = answer_text
    return result


async def generate_image_node(
    state: AgentState, *, config: RunnableConfig
) -> dict:
    """图片生成节点：调用 Gemini 生成图片，结果存入 state.generated_image"""
    from app.services.gemini_image_gen_service import generate_image

    configurable = config.get("configurable", {})
    user_llm_cfg = configurable.get("user_llm_cfg", {})
    image_path = configurable.get("image_path")

    # 取用户或全局的 Gemini 配置
    api_key = user_llm_cfg.get("GEMINI_API_KEY") or settings.GEMINI_API_KEY
    # GEMINI_IMAGE_GEN_URL 现在存的是模型名，通过 GEMINI_GEN_URL property 拼出完整 URL
    user_model = user_llm_cfg.get("GEMINI_IMAGE_GEN_URL")
    if user_model:
        api_url = f"https://api.kuai.host/v1beta/models/{user_model}:generateContent"
    else:
        api_url = settings.GEMINI_GEN_URL

    if not api_key or not api_url:
        logger.warning("Gemini 图片生成 API Key 或 URL 未配置，跳过图片生成")
        return {
            "messages": [AIMessage(content="图片生成功能未配置，请先在设置中填写 Gemini API Key 和图片生成地址")],
            "generated_image": ""
        }

    # 取最后一条用户消息作为提示词
    query = ""
    for msg in reversed(state.messages):
        if hasattr(msg, "type") and msg.type == "human":
            query = msg.content
            break

    logger.info(f"开始生成图片，提示词: {query[:80]}，参考图: {image_path or '无'}")

    # 如果参考图是 URL，先下载到临时文件（Gemini 图片生成需要本地文件 base64）
    actual_image_path = image_path
    if image_path and (image_path.startswith("http://") or image_path.startswith("https://")):
        try:
            import httpx as _httpx
            from urllib.parse import urlparse
            import tempfile
            parsed_url = urlparse(image_path)
            ref_ext = os.path.splitext(parsed_url.path.split("?")[0])[1] or '.jpg'
            async with _httpx.AsyncClient(timeout=30) as _http:
                _resp = await _http.get(image_path)
                _resp.raise_for_status()
                tmp_dir = Path(settings.GRAPHRAG_PROJECT_DIR).parent.parent / "uploads" / "tmp"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                import uuid as _uuid
                tmp_file = tmp_dir / f"{_uuid.uuid4().hex}{ref_ext}"
                tmp_file.write_bytes(_resp.content)
                actual_image_path = str(tmp_file)
                logger.info(f"参考图已下载到临时路径: {actual_image_path}")
        except Exception as dl_err:
            logger.warning(f"参考图下载失败，将仅用文字生成: {dl_err}")
            actual_image_path = None

    image_url = await generate_image(
        prompt=query,
        api_key=api_key,
        api_url=api_url,
        reference_image_path=actual_image_path if actual_image_path else None,
    )

    if image_url:
        logger.info(f"图片生成成功，URL: {image_url}")
        return {
            "messages": [AIMessage(content="好的，图片已生成 ✨")],
            "generated_image": image_url
        }
    else:
        logger.warning("图片生成失败")
        return {
            "messages": [AIMessage(content="图片生成失败，请稍后重试")],
            "generated_image": ""
        }


def route_after_text(state: AgentState) -> str:
    """文字回复完成后，判断是否需要继续生成图片"""
    if state.need_image_gen:
        return "generate_image_node"
    return END


# ==================== 表情过滤正则 ====================
# 匹配中文括号表情：（微笑）、（保持专业微笑）、（笑）等
# 匹配英文括号表情：(smile)、(laughing) 等
# 匹配 emoji 表情符号
_EMOJI_PATTERNS = re.compile(
    r'[（\(][^）\)]{0,20}(?:微笑|笑|害羞|尴尬|思考|点头|挥手|鼓掌|叹气|无奈|认真|严肃|温柔|亲切|专业|礼貌|热情|开心|高兴|得意|调皮|眨眼|抱拳|握手|比心|加油|鞠躬|摊手|耸肩|沉思|疑惑|惊讶|感动|委屈|抱歉|歉意|遗憾|同情|安慰|鼓励|赞赏|佩服|崇拜|期待|兴奋|激动|紧张|担心|焦虑|放松|轻松|自信|坚定|果断|冷静|淡定|优雅|从容|smile|grin|laugh|wink|nod)[^）\)]*[）\)]'
    r'|[\U0001F600-\U0001F64F]'  # 表情符号
    r'|[\U0001F300-\U0001F5FF]'  # 杂项符号
    r'|[\U0001F680-\U0001F6FF]'  # 交通和地图符号
    r'|[\U0001F1E0-\U0001F1FF]'  # 旗帜
    r'|[\U00002702-\U000027B0]'  # 装饰符号
    r'|[\U0001F900-\U0001F9FF]'  # 补充表情
    r'|[\U0001FA00-\U0001FA6F]'  # 象棋符号
    r'|[\U0001FA70-\U0001FAFF]'  # 扩展A符号
    r'|[\U00002600-\U000026FF]'  # 杂项符号
    r'|[\U0000FE00-\U0000FE0F]'  # 变体选择器
    r'|[\U0000200D]'             # 零宽连接符
    r'|[\U000020E3]'             # 组合用封闭键帽
    r'|[\U0000231A-\U0000231B]'  # 手表/沙漏
    r'|[\U000023E9-\U000023F3]'  # 各种符号
    r'|[\U000023F8-\U000023FA]'  # 播放控制
    r'|',
    re.UNICODE
)

# 匹配结构化话术前缀，例如：（先共情）、（核心观点）、（引导提问）
_STRUCTURE_PREFIX_PATTERN = re.compile(
    r'[（\(](?:先共情|核心观点|引导提问)[^）\)]*[）\)]'
)


def _sanitize_emoji(text: str) -> str:
    """清除回复中的括号表情、结构化前缀和 emoji 符号。"""
    if not text:
        return text
    cleaned = _EMOJI_PATTERNS.sub('', text)
    # 清除结构化前缀括号，如：（先共情）、（核心观点）、（引导提问）
    cleaned = _STRUCTURE_PREFIX_PATTERN.sub('', cleaned)
    # 清理多余空格
    cleaned = re.sub(r'  +', ' ', cleaned)
    cleaned = re.sub(r'\n +\n', '\n\n', cleaned)
    return cleaned.strip()


async def sanitize_response(
    state: AgentState, *, config: RunnableConfig
) -> dict:
    """后处理节点：清除回复中的表情文字和 emoji。
    
    所有生成回复的路径最终都经过此节点，确保输出干净。
    """
    if not state.messages:
        return {}
    
    last_msg = state.messages[-1]
    if not isinstance(last_msg, AIMessage) or not last_msg.content:
        return {}
    
    original = last_msg.content
    cleaned = _sanitize_emoji(original)
    
    if cleaned != original:
        logger.info(f"sanitize_response: 清除了表情文字，原长度={len(original)}，清理后={len(cleaned)}")
        return {"messages": [AIMessage(content=cleaned, id=last_msg.id)]}
    
    return {}


def route_after_hallucination_check(state: AgentState) -> str:
    """幻觉检测完成后的路由：
    - 检测失败（binary_score="0"）且来源是 graphrag → 重新调用子图
    - 检测失败但来源是其他路径（general/web_search 等）→ 直接进入后处理（无法重试）
    - 其他情况（通过或已达上限）→ sanitize_response（表情过滤）
    
    注意：非 graphrag 路径没有知识库上下文可重新查询，重试无意义，直接放行。
    重试次数上限由 check_hallucinations 中的 hallucinationDetectionConfig.maxRetries 控制。
    """
    if state.hallucination.binary_score == "0":
        # 只有 graphrag 路径（有 documents 上下文）才值得重试
        if state.documents and state.documents.strip():
            logger.info(f"幻觉检测路由：graphrag 路径重新查询（retry={state.hallucination_retry}）")
            return "invoke_kg_subgraph"
        else:
            logger.info("幻觉检测路由：非 graphrag 路径，无法重试，直接进入后处理")
            return "sanitize_response"
    logger.info("幻觉检测路由：答案通过，进入后处理")
    return "sanitize_response"


def route_after_sanitize(state: AgentState) -> str:
    """后处理完成后，判断是否需要继续生成图片"""
    if state.need_image_gen:
        return "generate_image_node"
    return END


# 定义状态图
builder = StateGraph(AgentState, input=InputState)

# 添加节点
builder.add_node(analyze_and_route_query)
builder.add_node(respond_to_general_query)
builder.add_node(get_additional_info)
# ★ 用 invoke_kg_subgraph 替代原来的 create_research_plan
builder.add_node("invoke_kg_subgraph", invoke_kg_subgraph)
builder.add_node(create_image_query)
builder.add_node(create_file_query)
builder.add_node(web_search_query)
builder.add_node(generate_image_node)
# ★ 注册幻觉检测节点
builder.add_node("check_hallucinations", check_hallucinations)
# ★ 注册后处理节点（表情过滤 + 清理）
builder.add_node("sanitize_response", sanitize_response)

# 添加边
builder.add_edge(START, "analyze_and_route_query")
builder.add_conditional_edges("analyze_and_route_query", route_query)

# ★ 所有生成回复的路径都经过幻觉检测 → 后处理（表情过滤）
# graphrag 路径：invoke_kg_subgraph → check_hallucinations → sanitize_response / 重试
builder.add_edge("invoke_kg_subgraph", "check_hallucinations")
# 其他回复路径也经过幻觉检测（意图匹配验证 + 表情过滤）
builder.add_edge("respond_to_general_query", "check_hallucinations")
builder.add_edge("web_search_query", "check_hallucinations")
builder.add_edge("create_image_query", "check_hallucinations")
builder.add_edge("create_file_query", "check_hallucinations")

# 幻觉检测后路由：失败重试（仅 graphrag）或进入后处理
builder.add_conditional_edges("check_hallucinations", route_after_hallucination_check)

# 后处理完成后：判断是否需要生成图片，否则 END
builder.add_conditional_edges("sanitize_response", route_after_sanitize)

# 追问节点直接经过后处理（不需要幻觉检测）
builder.add_edge("get_additional_info", "sanitize_response")

# 图片生成节点直接 END（图片不需要文字过滤）
builder.add_edge("generate_image_node", END)

graph = builder.compile(checkpointer=checkpointer)