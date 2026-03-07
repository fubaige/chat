"""
内部 API 路由模块

供 Next.js 主应用通过 HTTP 调用的内部 API 端点。
所有端点使用 /internal/ 前缀，通过 X-Internal-API-Key 进行认证。
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth_middleware import (
    AuthenticatedUser,
    verify_internal_api_key,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["内部 API"])


# ==================== 请求/响应模型 ====================


class DeepThinkingConfig(BaseModel):
    """深度思考配置"""
    enabled: bool = False
    model: str = "deepseek-reasoner"


class WebSearchConfig(BaseModel):
    """联网搜索配置"""
    enabled: bool = False
    searchResultCount: int = 10
    serpApiKey: Optional[str] = None


class IntentRouterRoutes(BaseModel):
    """意图路由类型开关"""
    general: bool = True
    additional: bool = True
    graphrag: bool = True
    image: bool = True
    file: bool = True


class IntentRouterConfig(BaseModel):
    """意图路由配置"""
    enabled: bool = True
    confidenceThreshold: float = 0.6
    routes: IntentRouterRoutes = Field(default_factory=IntentRouterRoutes)


class HallucinationDetectionConfig(BaseModel):
    """幻觉检测配置"""
    enabled: bool = False
    maxRetries: int = 1


class MemoryDecayConfig(BaseModel):
    """记忆衰减配置"""
    enabled: bool = True
    maxMessages: int = 30  # 保留的最大聊天记忆条数（10-50）


class MultiModalConfig(BaseModel):
    """多模态配置"""
    imageParsingEnabled: bool = False
    fileParsingEnabled: bool = False
    parseModel: str = "gemini-3.1-pro-preview"
    visionModel: str = "qwen3.5-flash"  # 通义千问视觉模型（多模态第二模型）


class AgentConfigExtended(BaseModel):
    """扩展智能体配置，包含 LangGraph 工作流所需的全部参数"""
    # 基础模型配置
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    temperature: Optional[float] = 1
    maxTokens: Optional[int] = None
    systemPrompt: Optional[str] = ""

    # 扩展配置
    deepThinkingConfig: Optional[DeepThinkingConfig] = None
    webSearchConfig: Optional[WebSearchConfig] = None
    intentRouterConfig: Optional[IntentRouterConfig] = None
    hallucinationDetectionConfig: Optional[HallucinationDetectionConfig] = None
    memoryDecayConfig: Optional[MemoryDecayConfig] = None
    multiModalConfig: Optional[MultiModalConfig] = None

    # 知识库绑定
    knowledgeBaseIds: Optional[list[str]] = None


class InternalChatRequest(BaseModel):
    """内部对话请求体"""
    query: str = Field(..., min_length=1, description="用户消息内容")
    conversation_id: Optional[str] = Field(None, description="会话 ID，为空则创建新会话")
    image_url: Optional[str] = Field(None, description="用户上传的图片/文件 URL（云存储公网地址）")
    link_url: Optional[str] = Field(None, description="用户发送的链接 URL（将自动提取文章内容进行总结）")
    agent_config: AgentConfigExtended = Field(
        default_factory=AgentConfigExtended,
        description="智能体扩展配置",
    )


# ==================== 认证依赖 ====================


async def verify_internal_request(request: Request) -> AuthenticatedUser:
    """
    内部 API 认证依赖。

    验证规则：
    1. 必须携带有效的 X-Internal-API-Key
    2. 必须携带 X-User-ID 请求头
    3. 必须携带 X-Tenant-ID 请求头

    Returns:
        AuthenticatedUser 实例（is_internal=True）

    Raises:
        HTTPException(403): API Key 验证失败
        HTTPException(400): 缺少必要的请求头
    """
    # 验证 Internal API Key
    if not verify_internal_api_key(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal API Key 验证失败",
        )

    # 提取并验证 X-User-ID
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少 X-User-ID 请求头",
        )

    # 提取并验证 X-Tenant-ID
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少 X-Tenant-ID 请求头",
        )

    return AuthenticatedUser(
        user_id=user_id,
        role="user",
        is_internal=True,
    )


# ==================== 辅助函数 ====================


async def _stream_content_with_typing_effect(content: str, delay: float = 0.01):
    """流式输出内容，模拟打字效果"""
    import asyncio

    i = 0
    while i < len(content):
        char = content[i]
        # 中文字符每次发送 1 个，英文/数字每次发送 2-3 个
        if ord(char) > 127:
            chunk = char
            i += 1
        else:
            chunk = content[i:i + 2]
            i += 2

        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        await asyncio.sleep(delay)


# ==================== 端点 ====================


@router.post("/chat/stream", summary="内部对话流式端点")
async def internal_chat_stream(
    body: InternalChatRequest,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """
    内部对话流式端点，供 Next.js 主应用调用。

    接收智能体配置，调用 LangGraph 工作流，返回 SSE 流式响应。

    流程：
    1. 验证内部 API Key + X-User-ID + X-Tenant-ID
    2. 解析 AgentConfigExtended 配置
    3. 构建 LangGraph thread_config
    4. 调用 LangGraph 工作流
    5. 返回 SSE 流式响应
    """
    import asyncio
    from langchain_core.messages import AIMessage
    from app.lg_agent.utils import new_uuid

    user_id = auth_user.user_id
    tenant_id = auth_user.user_id  # tenant_id 从请求头获取，此处用 user_id 作为标识
    agent_config = body.agent_config

    # 确定会话 ID
    thread_id = body.conversation_id if body.conversation_id else new_uuid()

    # 从扩展配置中提取 LangGraph 工作流参数
    deep_thinking = False
    if agent_config.deepThinkingConfig and agent_config.deepThinkingConfig.enabled:
        deep_thinking = True

    web_search = False
    if agent_config.webSearchConfig and agent_config.webSearchConfig.enabled:
        web_search = True

    # 处理用户上传的图片/文件 URL
    # 优先直接传递 URL 给 LangGraph（通义千问可直接通过 URL 解析），
    # 仅当需要 Gemini 回退时才下载到本地
    image_path = None
    if body.image_url:
        # 直接将 URL 传递给 LangGraph，通义千问视觉模型支持 URL 直接解析
        image_path = body.image_url
        logger.info(f"多模态文件 URL 直接传递给 LangGraph: {body.image_url[:80]}...")

    # 处理用户发送的链接 URL - 提取文章内容并注入到用户消息
    article_content = None
    extracted_link_url = body.link_url  # 记录显式传递的链接 URL

    # 自动检测用户消息中的 URL（如果没有显式传递 link_url）
    if not extracted_link_url and body.query:
        import re
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls_found = re.findall(url_pattern, body.query)
        if urls_found:
            # 使用第一个找到的 URL
            extracted_link_url = urls_found[0]
            logger.info(f"自动检测到用户消息中的 URL: {extracted_link_url[:80]}...")

    if extracted_link_url:
        try:
            from app.services.article_extraction_service import (
                extract_article_content,
                format_article_summary,
            )
            logger.info(f"开始提取文章内容: {extracted_link_url[:80]}...")
            article_data = extract_article_content(extracted_link_url)
            if article_data and article_data.get("content"):
                article_content = format_article_summary(
                    type("Article", (), article_data)()
                )
                logger.info(
                    f"文章提取成功: title={article_data.get('title', 'N/A')}, "
                    f"content_length={len(article_data.get('content', ''))}"
                )
            else:
                logger.warning(f"文章内容提取失败或为空: {extracted_link_url[:80]}...")
        except Exception as e:
            logger.error(f"提取文章内容失败: {e}", exc_info=True)

    # 构建 LangGraph 线程配置
    thread_config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "image_path": image_path,
            "link_url": extracted_link_url,  # 用户发送的链接 URL
            "deep_thinking": deep_thinking,
            "web_search": web_search,
            "user_llm_cfg": {},  # 内部调用不使用用户级别的 LLM 配置
            "agent_system_prompt": agent_config.systemPrompt or "",
            # 扩展配置传递给 LangGraph 工作流
            "agent_config_extended": agent_config.model_dump(),
        }
    }

    logger.info(
        f"内部 API 对话请求: user_id={user_id}, "
        f"thread_id={thread_id}, deep_thinking={deep_thinking}, "
        f"web_search={web_search}"
    )

    async def process_stream():
        """SSE 流式生成器，调用 LangGraph 工作流并逐块输出"""
        from app.lg_agent.lg_builder import graph, _sanitize_emoji

        full_response = ""
        is_research_plan = False

        try:
            # 构建输入状态
            user_message = body.query

            # 如果有提取的文章内容，注入到用户消息中
            if article_content:
                user_message = (
                    f"{body.query}\n\n"
                    f"【用户发送的链接文章内容】\n"
                    f"{article_content}\n"
                    f"【结束】\n\n"
                    f"请根据以上文章内容回答用户问题。"
                )
                logger.info(f"已将文章内容注入用户消息，原始消息长度: {len(body.query)}, 注入后长度: {len(user_message)}")

            input_state = {"messages": [{"role": "user", "content": user_message}]}

            # 检查是否存在中断状态
            has_interrupt = False
            try:
                snapshot = await graph.aget_state(thread_config)
                if snapshot and hasattr(snapshot, "tasks") and snapshot.tasks:
                    for task in snapshot.tasks:
                        if hasattr(task, "interrupts") and task.interrupts:
                            has_interrupt = True
                            break
            except Exception as e:
                logger.warning(f"检查中断状态失败: {e}")

            # 预取搜索结果（如果启用了联网搜索）
            search_results = None
            if web_search:
                try:
                    from app.tools.search import SearchTool
                    search_count = 5
                    if agent_config.webSearchConfig:
                        search_count = min(agent_config.webSearchConfig.searchResultCount, 10)
                    search_results = await asyncio.to_thread(
                        SearchTool().search, body.query, search_count
                    )
                    logger.info(f"预取搜索结果: {len(search_results)} 条")
                except Exception as e:
                    logger.error(f"预取搜索失败: {e}")
                    search_results = []

            # 发送搜索结果（如果有）
            if search_results:
                sr_json = json.dumps(
                    {"search_results": search_results}, ensure_ascii=False
                )
                yield f"data: {sr_json}\n\n"

            # 选择流式调用方式：中断恢复 or 新输入
            if has_interrupt:
                from langgraph.types import Command
                stream_input = Command(resume=body.query)
            else:
                stream_input = input_state

            # 流式调用 LangGraph 工作流
            # 注意：LangGraph 0.3.x 存在 FuturesDict callback 为 None 的 bug，
            # 当子图完成时可能抛出 TypeError: 'NoneType' object is not callable
            try:
                stream_iter = graph.astream(
                    input=stream_input,
                    stream_mode="messages",
                    config=thread_config,
                )
                async for c, metadata in stream_iter:
                    node_name = metadata.get("langgraph_node", "")
                    if not c.content or c.additional_kwargs.get("tool_calls"):
                        continue
                    # 跳过 DeepSeek 思考模式的 reasoning_content
                    if c.additional_kwargs.get("reasoning_content"):
                        continue

                    # 白名单节点：只允许这些节点的消息流出
                    # ★ 与原始 main.py 保持一致：invoke_kg_subgraph 和 create_research_plan
                    #   不在白名单中，它们的输出通过 is_research_plan 标记后从图状态取最终答案
                    ALLOWED_NODES = {
                        "respond_to_general_query",
                        "web_search_query",
                        "get_additional_info",
                        "generate_image_node",
                    }

                    if node_name not in ALLOWED_NODES:
                        if node_name:
                            is_research_plan = True
                        continue

                    # 流式输出内容（过滤表情）
                    content = _sanitize_emoji(c.content)
                    async for chunk_data in _stream_content_with_typing_effect(
                        content, delay=0.01
                    ):
                        yield chunk_data
                    full_response += content

            # LangGraph FuturesDict callback bug 捕获：从检查点恢复
            # 注意：此 bug 可能在流迭代完成后触发，需要在 except 块外再次捕获
            except TypeError as ft_err:
                if "'NoneType' object is not callable" in str(ft_err):
                    logger.warning(f"LangGraph FuturesDict callback bug 触发（迭代中），尝试从检查点恢复: {ft_err}")
                    try:
                        snapshot = await graph.aget_state(thread_config)
                        if snapshot and hasattr(snapshot, "values") and snapshot.values:
                            msgs = snapshot.values.get("messages", [])
                            for msg in reversed(msgs):
                                if isinstance(msg, AIMessage) and msg.content and msg.content.strip():
                                    content = _sanitize_emoji(msg.content)
                                    async for chunk_data in _stream_content_with_typing_effect(content, delay=0.01):
                                        yield chunk_data
                                    full_response = content
                                    break
                    except Exception as snapshot_err:
                        logger.error(f"从检查点恢复失败: {snapshot_err}")
                else:
                    raise

            # 流迭代完成后再次检查是否有 FuturesDict callback bug（子图完成后触发）
            if not full_response:
                try:
                    snapshot = await graph.aget_state(thread_config)
                    if snapshot and hasattr(snapshot, "values") and snapshot.values:
                        msgs = snapshot.values.get("messages", [])
                        for msg in reversed(msgs):
                            if isinstance(msg, AIMessage) and msg.content and msg.content.strip():
                                content = _sanitize_emoji(msg.content)
                                async for chunk_data in _stream_content_with_typing_effect(content, delay=0.01):
                                    yield chunk_data
                                full_response = content
                                break
                except TypeError as ft_err2:
                    if "'NoneType' object is not callable" in str(ft_err2):
                        logger.warning(f"LangGraph FuturesDict callback bug 触发（迭代后），尝试从检查点恢复: {ft_err2}")
                except Exception as e:
                    logger.error(f"迭代后获取最终状态失败: {e}")

            # 流结束后，如果是 research_plan 路径，从图状态取最终答案
            if is_research_plan and not full_response:
                try:
                    final_state = await graph.aget_state(thread_config)
                    if (
                        final_state
                        and hasattr(final_state, "values")
                        and final_state.values
                    ):
                        msgs = final_state.values.get("messages", [])
                        for msg in reversed(msgs):
                            if (
                                isinstance(msg, AIMessage)
                                and msg.content
                                and msg.content.strip()
                            ):
                                content = _sanitize_emoji(msg.content)
                                async for chunk_data in _stream_content_with_typing_effect(
                                    content, delay=0.01
                                ):
                                    yield chunk_data
                                full_response = content
                                break
                except Exception as state_err:
                    logger.error(f"获取最终状态失败: {state_err}")

            # 检查是否有生成的图片
            try:
                final_state = await graph.aget_state(thread_config)
                if (
                    final_state
                    and hasattr(final_state, "values")
                    and final_state.values
                ):
                    generated_image = final_state.values.get("generated_image", "")
                    if generated_image:
                        img_json = json.dumps(
                            {"generated_image": generated_image}, ensure_ascii=False
                        )
                        yield f"data: {img_json}\n\n"
            except Exception as img_err:
                logger.warning(f"获取生成图片失败: {img_err}")

            # 检查中断状态
            try:
                state = await graph.aget_state(thread_config)
                if state and hasattr(state, "tasks") and state.tasks:
                    for task in state.tasks:
                        if hasattr(task, "interrupts") and task.interrupts:
                            interrupt_json = json.dumps(
                                {"interruption": True, "conversation_id": thread_id}
                            )
                            yield f"data: {interrupt_json}\n\n"
                            break
            except Exception as e:
                logger.warning(f"检查中断状态失败: {e}")

        except Exception as stream_err:
            logger.error(f"流式处理错误: {stream_err}", exc_info=True)
            if not full_response:
                error_msg = "抱歉，服务暂时繁忙，请稍后重试"
                error_json = json.dumps(error_msg, ensure_ascii=False)
                yield f"data: {error_json}\n\n"

        finally:
            # 发送流结束标记
            yield "data: [DONE]\n\n"

    response = StreamingResponse(
        process_stream(),
        media_type="text/event-stream",
    )
    response.headers["X-Conversation-ID"] = thread_id
    return response


class InternalChatSyncResponse(BaseModel):
    """非流式对话响应"""
    reply: str = Field(..., description="AI 回复文本")
    conversation_id: str = Field(..., description="会话 ID")


@router.post("/chat/sync", summary="内部对话非流式端点")
async def internal_chat_sync(
    body: InternalChatRequest,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """
    内部对话非流式端点，供企微回调等场景调用。

    与 /chat/stream 共用同一套 LangGraph 工作流，
    但等待工作流完全执行完毕后，一次性返回完整回复文本（JSON 格式）。
    """
    import asyncio
    from langchain_core.messages import AIMessage
    from app.lg_agent.utils import new_uuid
    from app.lg_agent.lg_builder import graph, _sanitize_emoji

    user_id = auth_user.user_id
    agent_config = body.agent_config
    thread_id = body.conversation_id if body.conversation_id else new_uuid()

    # 深度思考 & 联网搜索开关
    deep_thinking = bool(
        agent_config.deepThinkingConfig and agent_config.deepThinkingConfig.enabled
    )
    web_search = bool(
        agent_config.webSearchConfig and agent_config.webSearchConfig.enabled
    )

    # 处理用户上传的图片/文件 URL
    # 直接将 URL 传递给 LangGraph，通义千问视觉模型支持 URL 直接解析
    image_path = None
    if body.image_url:
        image_path = body.image_url
        logger.info(f"非流式：多模态文件 URL 直接传递: {body.image_url[:80]}...")

    # 处理用户发送的链接 URL - 提取文章内容并注入到用户消息
    article_content = None
    extracted_link_url = body.link_url  # 记录显式传递的链接 URL

    # 自动检测用户消息中的 URL（如果没有显式传递 link_url）
    if not extracted_link_url and body.query:
        import re
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls_found = re.findall(url_pattern, body.query)
        if urls_found:
            # 使用第一个找到的 URL
            extracted_link_url = urls_found[0]
            logger.info(f"非流式：自动检测到用户消息中的 URL: {extracted_link_url[:80]}...")

    if extracted_link_url:
        try:
            from app.services.article_extraction_service import (
                extract_article_content,
                format_article_summary,
            )
            logger.info(f"非流式：开始提取文章内容: {extracted_link_url[:80]}...")
            article_data = extract_article_content(extracted_link_url)
            if article_data and article_data.get("content"):
                article_content = format_article_summary(
                    type("Article", (), article_data)()
                )
                logger.info(
                    f"非流式：文章提取成功: title={article_data.get('title', 'N/A')}, "
                    f"content_length={len(article_data.get('content', ''))}"
                )
            else:
                logger.warning(f"非流式：文章内容提取失败或为空: {extracted_link_url[:80]}...")
        except Exception as e:
            logger.error(f"非流式：提取文章内容失败: {e}", exc_info=True)

    thread_config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "image_path": image_path,
            "link_url": extracted_link_url,
            "deep_thinking": deep_thinking,
            "web_search": web_search,
            "user_llm_cfg": {},
            "agent_system_prompt": agent_config.systemPrompt or "",
            "agent_config_extended": agent_config.model_dump(),
        }
    }

    logger.info(
        f"内部 API 非流式对话请求: user_id={user_id}, "
        f"thread_id={thread_id}, deep_thinking={deep_thinking}, "
        f"web_search={web_search}"
    )

    try:
        # 构建输入状态
        user_message = body.query

        # 如果有提取的文章内容，注入到用户消息中
        if article_content:
            user_message = (
                f"{body.query}\n\n"
                f"【用户发送的链接文章内容】\n"
                f"{article_content}\n"
                f"【结束】\n\n"
                f"请根据以上文章内容回答用户问题。"
            )
            logger.info(f"非流式：已将文章内容注入用户消息，原始消息长度: {len(body.query)}, 注入后长度: {len(user_message)}")

        input_state = {"messages": [{"role": "user", "content": user_message}]}

        # 检查是否存在中断状态
        has_interrupt = False
        try:
            snapshot = await graph.aget_state(thread_config)
            if snapshot and hasattr(snapshot, "tasks") and snapshot.tasks:
                for task in snapshot.tasks:
                    if hasattr(task, "interrupts") and task.interrupts:
                        has_interrupt = True
                        break
        except Exception as e:
            logger.warning(f"检查中断状态失败: {e}")

        if has_interrupt:
            from langgraph.types import Command
            stream_input = Command(resume=body.query)
        else:
            stream_input = input_state

        # 非流式调用：使用 ainvoke 直接获取最终状态
        # 注意：LangGraph 0.3.x 存在 FuturesDict callback 为 None 的 bug，
        # 当子图完成时可能抛出 TypeError: 'NoneType' object is not callable
        # 使用 try-except 捕获该错误，并从图中获取已保存的状态
        try:
            final_result = await graph.ainvoke(
                input=stream_input,
                config=thread_config,
            )
        except TypeError as e:
            if "'NoneType' object is not callable" in str(e):
                logger.warning(f"LangGraph FuturesDict callback bug 触发，尝试从检查点恢复: {e}")
                # 从检查点获取已保存的状态
                snapshot = await graph.aget_state(thread_config)
                if snapshot and hasattr(snapshot, "values") and snapshot.values:
                    final_result = snapshot.values
                    logger.info("已从检查点恢复状态")
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"LangGraph 工作流执行出错（FuturesDict bug），且无法恢复状态: {str(e)}",
                    )
            else:
                raise

        # 从最终状态中提取 AI 回复
        reply_text = ""
        messages = final_result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content and msg.content.strip():
                reply_text = _sanitize_emoji(msg.content).strip()
                break

        if not reply_text:
            raise HTTPException(
                status_code=500,
                detail="LangGraph 工作流未生成有效回复",
            )

        logger.info(f"非流式对话完成: thread_id={thread_id}, reply_length={len(reply_text)}")

        return InternalChatSyncResponse(
            reply=reply_text,
            conversation_id=thread_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"非流式对话处理错误: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"对话处理失败: {str(e)}",
        )


# ==================== 知识库请求/响应模型 ====================


class KnowledgeBaseUploadResponse(BaseModel):
    """知识库文档上传响应"""
    id: int
    status: str = "indexing"
    message: str = "文件已进入后台索引流程"


class KnowledgeBaseDocumentResponse(BaseModel):
    """知识库文档信息"""
    id: int
    user_id: str
    tenant_id: str
    filename: str
    original_name: str
    file_path: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    preview: Optional[str] = None
    index_id: Optional[str] = None
    embedding_type: Optional[str] = None
    user_uuid: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class KnowledgeBaseSearchRequest(BaseModel):
    """知识库检索请求"""
    query: str = Field(..., min_length=1, description="检索查询文本")
    knowledge_base_ids: list[str] = Field(..., description="知识库 ID 列表")
    user_id: str = Field(..., description="用户 ID")


class SearchResultItem(BaseModel):
    """单条检索结果"""
    content: str
    score: float = 0.0
    source: Optional[str] = None
    knowledge_base_id: Optional[str] = None


class KnowledgeBaseDeleteResponse(BaseModel):
    """知识库文档删除响应"""
    success: bool
    message: str = ""
    cleaned_dirs: list[str] = []
    remaining_files: int = 0


# ==================== 辅助函数 ====================


def _generate_user_uuid(user_id: str) -> str:
    """根据 user_id 生成固定的用户 UUID，用于文件目录隔离"""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{user_id}"))




async def _process_document_async(record_id: int, file_path: str, file_type: str, user_id: str):
    """异步处理文档：直接交由 IndexingService 处理（含完整三级降级链）

    在后台任务中执行，不阻塞 HTTP 响应。
    状态转换：pending → indexing → success/error
    """
    from app.core.database import AsyncSessionLocal
    from app.models.knowledge_base import KnowledgeBaseDocument
    from sqlalchemy import select

    try:
        # 更新状态为 indexing
        async with AsyncSessionLocal() as session:
            stmt = select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.id == record_id)
            result = await session.execute(stmt)
            doc = result.scalar_one_or_none()
            if doc:
                doc.status = "indexing"
                await session.commit()

        # 直接交由 IndexingService 处理（内部含 MinerU → 本地提取 → Gemini 三级降级链）
        from app.services.indexing_service import IndexingService
        indexing_service = IndexingService()
        file_info = {
            "path": file_path,
            "user_id": user_id,
        }
        await indexing_service.process_file(file_info, record_id)
        # process_file 内部会更新状态为 success 或 error

    except Exception as e:
        logger.error(f"文档处理异常: {e}", exc_info=True)
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.id == record_id)
                result = await session.execute(stmt)
                doc = result.scalar_one_or_none()
                if doc:
                    doc.status = "error"
                    doc.error_message = f"处理异常: {str(e)}"
                    await session.commit()
        except Exception:
            logger.error(f"更新文档 {record_id} 错误状态失败", exc_info=True)


# ==================== 知识库端点 ====================


@router.post(
    "/knowledge-base/upload",
    response_model=KnowledgeBaseUploadResponse,
    summary="上传知识库文档",
)
async def internal_knowledge_base_upload(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Form(...),
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """上传知识库文档，异步执行三级降级链解析和 GraphRAG 索引构建。

    流程：
    1. 保存上传文件到用户隔离目录
    2. 创建数据库记录（status=pending）
    3. 启动后台异步任务处理文档
    4. 立即返回记录 ID 和初始状态
    """
    import asyncio
    import re
    from datetime import datetime
    from app.core.database import AsyncSessionLocal
    from app.models.knowledge_base import KnowledgeBaseDocument

    try:
        # 生成用户 UUID 用于目录隔离
        user_uuid = _generate_user_uuid(user_id)

        # 创建上传目录：uploads/{user_uuid}/{timestamp}/
        upload_base = Path(settings.GRAPHRAG_PROJECT_DIR).parent.parent / "uploads"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        upload_dir = upload_base / user_uuid / timestamp
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 清理文件名中的特殊字符
        original_name = file.filename or "unknown"
        base_name, ext = os.path.splitext(original_name)
        safe_name = re.sub(r'[\s\(\)\[\]\{\}#%&\+\?=]', '_', base_name)
        safe_name = re.sub(r'_+', '_', safe_name).strip('_') or 'file'
        new_filename = f"{safe_name}_{timestamp}{ext}"
        file_path = upload_dir / new_filename

        # 保存文件
        content = await file.read()
        await asyncio.to_thread(lambda: file_path.write_bytes(content))

        # 获取租户 ID（从认证用户或请求头）
        tenant_id = request.headers.get("X-Tenant-ID", "")

        # 创建数据库记录
        async with AsyncSessionLocal() as session:
            doc = KnowledgeBaseDocument(
                user_id=user_id,
                tenant_id=tenant_id,
                filename=new_filename,
                original_name=original_name,
                file_path=str(file_path).replace("\\", "/"),
                file_type=file.content_type,
                file_size=len(content),
                status="pending",
                user_uuid=user_uuid,
            )
            session.add(doc)
            await session.commit()
            await session.refresh(doc)
            record_id = doc.id

        logger.info(f"知识库文档上传成功: id={record_id}, user_id={user_id}, file={original_name}")

        # 启动后台异步任务处理文档
        asyncio.create_task(
            _process_document_async(
                record_id=record_id,
                file_path=str(file_path).replace("\\", "/"),
                file_type=file.content_type or "",
                user_id=user_id,
            )
        )

        return KnowledgeBaseUploadResponse(
            id=record_id,
            status="indexing",
            message="文件已进入后台索引流程",
        )

    except Exception as e:
        logger.error(f"知识库文档上传失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文档上传失败: {str(e)}",
        )


@router.get(
    "/knowledge-base/user/{user_id}",
    response_model=list[KnowledgeBaseDocumentResponse],
    summary="获取用户知识库文档列表",
)
async def internal_knowledge_base_list(
    user_id: str,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """返回指定用户的知识库文档列表，按创建时间倒序排列。"""
    from app.core.database import AsyncSessionLocal
    from app.models.knowledge_base import KnowledgeBaseDocument
    from sqlalchemy import select

    try:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(KnowledgeBaseDocument)
                .where(KnowledgeBaseDocument.user_id == user_id)
                .order_by(KnowledgeBaseDocument.created_at.desc())
            )
            result = await session.execute(stmt)
            docs = result.scalars().all()

            return [
                KnowledgeBaseDocumentResponse(
                    id=doc.id,
                    user_id=doc.user_id,
                    tenant_id=doc.tenant_id,
                    filename=doc.filename,
                    original_name=doc.original_name,
                    file_path=doc.file_path,
                    file_type=doc.file_type,
                    file_size=doc.file_size,
                    status=doc.status,
                    error_message=doc.error_message,
                    preview=doc.preview,
                    index_id=doc.index_id,
                    embedding_type=doc.embedding_type,
                    user_uuid=doc.user_uuid,
                    created_at=str(doc.created_at) if doc.created_at else None,
                    updated_at=str(doc.updated_at) if doc.updated_at else None,
                )
                for doc in docs
            ]

    except Exception as e:
        logger.error(f"获取知识库文档列表失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取文档列表失败: {str(e)}",
        )


@router.delete(
    "/knowledge-base/{item_id}",
    response_model=KnowledgeBaseDeleteResponse,
    summary="删除知识库文档",
)
async def internal_knowledge_base_delete(
    item_id: int,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """删除知识库文档及其索引数据。

    清理策略：
    - 最后一个文档：清理所有目录（input/output/uploads）
    - 非最后一个文档：仅清理 output 目录（索引需重建）
    """
    import shutil
    from app.core.database import AsyncSessionLocal
    from app.models.knowledge_base import KnowledgeBaseDocument
    from sqlalchemy import select

    try:
        async with AsyncSessionLocal() as session:
            # 查找文档记录
            stmt = select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.id == item_id)
            result = await session.execute(stmt)
            doc = result.scalar_one_or_none()

            if not doc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="文档不存在",
                )

            doc_user_id = doc.user_id
            user_uuid = _generate_user_uuid(doc_user_id)

            # 删除上传的物理文件
            if doc.file_path and os.path.exists(doc.file_path):
                os.remove(doc.file_path)
                # 清理空的父目录
                parent_dir = os.path.dirname(doc.file_path)
                if os.path.isdir(parent_dir) and not os.listdir(parent_dir):
                    os.rmdir(parent_dir)

            # 删除数据库记录
            await session.delete(doc)

            # 检查该用户是否还有其他文档
            remaining_stmt = select(KnowledgeBaseDocument).where(
                KnowledgeBaseDocument.user_id == doc_user_id,
                KnowledgeBaseDocument.id != item_id,
            )
            remaining_result = await session.execute(remaining_stmt)
            remaining_items = remaining_result.scalars().all()

            # 清理 GraphRAG 索引数据
            graphrag_data_dir = Path(settings.GRAPHRAG_PROJECT_DIR) / settings.GRAPHRAG_DATA_DIR
            cleaned_dirs: list[str] = []

            if not remaining_items:
                # 最后一个文档：彻底清理所有目录
                for subdir in ("input", "output"):
                    dir_path = graphrag_data_dir / subdir / user_uuid
                    if dir_path.exists():
                        shutil.rmtree(str(dir_path), ignore_errors=True)
                        cleaned_dirs.append(f"{subdir}/{user_uuid}")

                # 清理 uploads 目录
                upload_dir = Path(settings.GRAPHRAG_PROJECT_DIR).parent.parent / "uploads" / user_uuid
                if upload_dir.exists():
                    shutil.rmtree(str(upload_dir), ignore_errors=True)
                    cleaned_dirs.append(f"uploads/{user_uuid}")

                logger.info(f"用户 {doc_user_id} 知识库已全部清空，已删除目录: {cleaned_dirs}")
            else:
                # 非最后一个文档：仅清理 output 目录
                output_dir = graphrag_data_dir / "output" / user_uuid
                if output_dir.exists():
                    shutil.rmtree(str(output_dir), ignore_errors=True)
                    cleaned_dirs.append(f"output/{user_uuid}")

                logger.info(f"用户 {doc_user_id} 删除了一个文档，索引数据已清理: {cleaned_dirs}")

            await session.commit()

            return KnowledgeBaseDeleteResponse(
                success=True,
                message="文档及索引数据已删除",
                cleaned_dirs=cleaned_dirs,
                remaining_files=len(remaining_items),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除知识库文档失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除文档失败: {str(e)}",
        )


@router.get(
    "/knowledge-base/{item_id}/chunks",
    summary="获取知识库文档的文本块",
)
async def internal_knowledge_base_chunks(
    item_id: int,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """获取知识库文件的文本块内容（GraphRAG text_units），按文件名过滤"""
    import asyncio
    from app.core.database import AsyncSessionLocal
    from app.models.knowledge_base import KnowledgeBaseDocument
    from sqlalchemy import select

    try:
        async with AsyncSessionLocal() as session:
            stmt = select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.id == item_id)
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()
            if not item:
                raise HTTPException(status_code=404, detail="文件不存在")
            if item.status != "success":
                return {"chunks": [], "total": 0, "message": "索引尚未完成"}

        user_uuid = _generate_user_uuid(item.user_id)

        project_dir = settings.GRAPHRAG_PROJECT_DIR
        data_dir = settings.GRAPHRAG_DATA_DIR

        doc_output_dir = os.path.join(project_dir, data_dir, "output", user_uuid, str(item_id))
        legacy_output_dir = os.path.join(project_dir, data_dir, "output", user_uuid)
        output_dir = doc_output_dir if os.path.exists(doc_output_dir) else legacy_output_dir

        artifacts_dir = os.path.join(output_dir, "artifacts")
        storage_dir = artifacts_dir if os.path.exists(artifacts_dir) else output_dir

        text_units_path = os.path.join(storage_dir, "text_units.parquet")
        documents_path = os.path.join(storage_dir, "documents.parquet")

        if not os.path.exists(text_units_path):
            return {"chunks": [], "total": 0, "message": "未找到文本块数据"}

        import pandas as pd

        df_text = await asyncio.to_thread(pd.read_parquet, text_units_path)

        matched_doc_ids: set = set()
        if os.path.exists(documents_path):
            df_docs = await asyncio.to_thread(pd.read_parquet, documents_path)
            original_stem = os.path.splitext(item.original_name)[0]
            for _, doc_row in df_docs.iterrows():
                title = str(doc_row.get("title", ""))
                raw_path = str(doc_row.get("raw_content_path", ""))
                if (original_stem in title or
                    item.original_name in title or
                    item.original_name in raw_path or
                    original_stem in os.path.basename(raw_path)):
                    matched_doc_ids.add(str(doc_row.get("id", "")))

        chunks = []
        for idx, row in df_text.iterrows():
            if matched_doc_ids:
                doc_ids = row.get("document_ids", [])
                if doc_ids is None:
                    doc_ids = []
                row_doc_ids = {str(d) for d in doc_ids}
                if not row_doc_ids.intersection(matched_doc_ids):
                    continue
            chunks.append({
                "id": str(row.get("id", idx)),
                "text": str(row.get("text", "")),
                "n_tokens": int(row.get("n_tokens", 0)) if pd.notna(row.get("n_tokens")) else 0,
            })

        return {
            "chunks": chunks,
            "total": len(chunks),
            "filename": item.original_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文本块失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/knowledge-base/search",
    response_model=list[SearchResultItem],
    summary="知识库检索",
)
async def internal_knowledge_base_search(
    body: KnowledgeBaseSearchRequest,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """执行知识库检索，并发查询所有指定的知识库目录。

    根据智能体配置中绑定的知识库 ID 列表，并发查询所有关联知识库目录，
    过滤无效回答后返回检索结果。
    """
    import asyncio

    if not body.knowledge_base_ids:
        return []

    user_uuid = _generate_user_uuid(body.user_id)
    graphrag_data_dir = Path(settings.GRAPHRAG_PROJECT_DIR) / settings.GRAPHRAG_DATA_DIR

    # 无效回答标识列表（与现有 LangGraph 逻辑一致）
    no_answer_indicators = [
        "i am sorry",
        "i'm sorry",
        "i don't know",
        "i do not know",
        "no information",
        "no relevant",
        "not found",
        "cannot answer",
        "无法回答",
        "没有找到",
        "没有相关",
        "抱歉",
    ]

    async def _query_single_kb(kb_id: str) -> list[SearchResultItem]:
        """查询单个知识库目录"""
        output_dir = graphrag_data_dir / "output" / user_uuid / kb_id
        if not output_dir.exists():
            logger.warning(f"知识库目录不存在: {output_dir}")
            return []

        try:
            # 尝试使用 GraphRAG 本地查询
            from graphrag.query.cli import run_local_search
            lancedb_uri = str((output_dir / "lancedb").resolve())

            result_text = await asyncio.to_thread(
                run_local_search,
                config_filepath=None,
                data_dir=str(output_dir),
                root_dir=str(graphrag_data_dir),
                community_level=settings.GRAPHRAG_COMMUNITY_LEVEL,
                response_type=settings.GRAPHRAG_RESPONSE_TYPE,
                query=body.query,
            )

            if result_text:
                result_lower = result_text.lower()
                # 过滤无效回答
                if any(indicator in result_lower for indicator in no_answer_indicators):
                    return []
                return [
                    SearchResultItem(
                        content=result_text,
                        score=1.0,
                        source=str(output_dir),
                        knowledge_base_id=kb_id,
                    )
                ]
        except Exception as e:
            logger.warning(f"知识库 {kb_id} 检索失败: {e}")

        return []

    # 并发查询所有知识库
    tasks = [_query_single_kb(kb_id) for kb_id in body.knowledge_base_ids]
    results_nested = await asyncio.gather(*tasks, return_exceptions=True)

    # 合并结果，跳过异常
    all_results: list[SearchResultItem] = []
    for result in results_nested:
        if isinstance(result, list):
            all_results.extend(result)
        elif isinstance(result, Exception):
            logger.warning(f"知识库检索任务异常: {result}")

    return all_results


# ==================== 微信公众号请求/响应模型 ====================


class WechatMpMessageRequest(BaseModel):
    """微信公众号消息处理请求"""
    config_id: int = Field(..., description="公众号配置 ID")
    signature: str = Field(..., description="微信签名")
    timestamp: str = Field(..., description="时间戳")
    nonce: str = Field(..., description="随机数")
    body: str = Field(..., description="微信推送的 XML 消息体")


# ==================== 微信公众号端点 ====================


@router.get("/wechat-mp/verify", summary="微信公众号 URL 验证")
async def internal_wechat_mp_verify(
    config_id: int,
    signature: str,
    timestamp: str,
    nonce: str,
    echostr: str,
):
    """
    微信公众号 URL 验证端点。

    微信服务器发送 GET 请求验证服务器配置时调用。
    根据 config_id 从数据库加载公众号配置，验证签名后返回 echostr。

    注意：此端点不需要 Internal API Key 认证，因为是微信服务器直接调用。
    但实际部署中由 Next.js 转发调用，Next.js 端已做签名预校验。
    """
    from fastapi.responses import PlainTextResponse
    from app.services.wechat_service import WechatMpService

    # 加载公众号配置
    config = await WechatMpService.get_config(config_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="公众号配置不存在或未启用",
        )

    # 验证签名并返回 echostr
    result = WechatMpService.verify_url(config, signature, timestamp, nonce, echostr)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="签名验证失败",
        )

    return PlainTextResponse(content=result, status_code=200)


@router.post("/wechat-mp/message", summary="微信公众号消息处理")
async def internal_wechat_mp_message(
    body: WechatMpMessageRequest,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """
    微信公众号消息处理端点。

    接收 Next.js 转发的微信消息，执行以下流程：
    1. 根据 config_id 加载公众号配置
    2. 验证微信签名
    3. 解析 XML 消息体
    4. 根据消息类型处理（文本消息触发 AI 回复，关注事件返回欢迎语）
    5. 超时保护：处理超过 4.5 秒先返回空响应，异步通过客服消息接口发送

    Returns:
        XML 回复字符串
    """
    from fastapi.responses import PlainTextResponse
    from app.services.wechat_service import WechatMpService, verify_wechat_signature

    # 加载公众号配置
    config = await WechatMpService.get_config(body.config_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="公众号配置不存在或未启用",
        )

    # 验证微信签名
    if not verify_wechat_signature(config.token, body.signature, body.timestamp, body.nonce):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="签名验证失败",
        )

    # 处理消息（内含超时保护）
    reply_xml = await WechatMpService.handle_message(config, body.body)

    return PlainTextResponse(content=reply_xml, media_type="application/xml")


# ==================== 微信公众号菜单端点 ====================


class WechatMenuButton(BaseModel):
    name: str
    type: Optional[str] = None
    key: Optional[str] = None
    url: Optional[str] = None
    appid: Optional[str] = None
    pagepath: Optional[str] = None
    sub_button: Optional[list["WechatMenuButton"]] = None


class WechatMenuPublishRequest(BaseModel):
    button: list[WechatMenuButton]


@router.get("/wechat-mp/configs/{config_id}/menu", summary="获取公众号菜单草稿")
async def internal_wechat_mp_get_menu(
    config_id: int,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """从微信服务器获取当前菜单配置"""
    import httpx
    from app.services.wechat_service import WechatMpService

    config = await WechatMpService.get_config(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="公众号配置不存在")

    service = WechatMpService(config)
    access_token = await service.get_access_token()
    if not access_token:
        raise HTTPException(status_code=400, detail="获取 access_token 失败，请检查 AppID 和 AppSecret")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.weixin.qq.com/cgi-bin/menu/get",
                params={"access_token": access_token},
            )
            data = resp.json()
            if "errcode" in data and data["errcode"] != 0:
                return {"menu": {"button": []}, "wechat_error": data}
            return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取菜单失败: {e}")


@router.post("/wechat-mp/configs/{config_id}/menu", summary="发布公众号菜单")
async def internal_wechat_mp_publish_menu(
    config_id: int,
    body: WechatMenuPublishRequest,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """将菜单发布到微信服务器"""
    import httpx
    from app.services.wechat_service import WechatMpService

    config = await WechatMpService.get_config(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="公众号配置不存在")

    service = WechatMpService(config)
    access_token = await service.get_access_token()
    if not access_token:
        raise HTTPException(status_code=400, detail="获取 access_token 失败，请检查 AppID 和 AppSecret")

    # 清理菜单数据，移除前端专用字段
    def clean_button(btn: dict, is_sub: bool = False) -> dict:
        allowed = {"name", "type", "key", "url", "appid", "pagepath", "sub_button"}
        cleaned = {k: v for k, v in btn.items() if k in allowed and v is not None}
        sub = cleaned.get("sub_button")
        if sub and not is_sub:
            # 顶级按钮有子菜单：递归清理，子按钮不允许再有 sub_button
            cleaned["sub_button"] = [clean_button(b, is_sub=True) for b in sub]
        else:
            # 子菜单按钮或空 sub_button：一律移除 sub_button 字段
            cleaned.pop("sub_button", None)
        return cleaned

    menu_data = {"button": [clean_button(b.model_dump()) for b in body.button]}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.weixin.qq.com/cgi-bin/menu/create",
                params={"access_token": access_token},
                json=menu_data,
            )
            result = resp.json()
            if result.get("errcode", 0) != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"微信返回错误: {result.get('errmsg', '')} (errcode={result.get('errcode')})",
                )
            return {"success": True, "message": "菜单已发布"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发布菜单失败: {e}")


@router.delete("/wechat-mp/configs/{config_id}/menu", summary="删除公众号菜单")
async def internal_wechat_mp_delete_menu(
    config_id: int,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """删除微信服务器上的菜单"""
    import httpx
    from app.services.wechat_service import WechatMpService

    config = await WechatMpService.get_config(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="公众号配置不存在")

    service = WechatMpService(config)
    access_token = await service.get_access_token()
    if not access_token:
        raise HTTPException(status_code=400, detail="获取 access_token 失败")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.weixin.qq.com/cgi-bin/menu/delete",
                params={"access_token": access_token},
            )
            result = resp.json()
            if result.get("errcode", 0) != 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"微信返回错误: {result.get('errmsg', '')} (errcode={result.get('errcode')})",
                )
            return {"success": True, "message": "菜单已删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除菜单失败: {e}")


# ==================== ASR 语音识别接口 ====================


class ASRTranscribeRequest(BaseModel):
    """语音识别请求体"""
    audio_url: str = Field(..., description="音频文件的公网 URL（支持 .silk / .mp3 / .wav 等格式）")
    audio_format: str = Field("silk", description="音频格式：silk / mp3 / wav / amr")
    language: str = Field("zh", description="识别语言，默认中文")


class ASRTranscribeResponse(BaseModel):
    """语音识别响应体"""
    text: str = Field(..., description="识别出的文本内容")
    duration: Optional[float] = Field(None, description="音频时长（秒）")
    engine: str = Field(..., description="使用的识别引擎：sense_voice / whisper / qwen_asr")


@router.post("/asr/transcribe", summary="语音识别（silk/mp3 → 文本）")
async def internal_asr_transcribe(
    body: ASRTranscribeRequest,
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """
    语音识别接口：下载音频文件 → 转换格式（silk→mp3）→ SenseVoice 识别 → 返回文本。

    处理流程：
    1. 从 audio_url 下载音频文件（支持阿里 OSS 签名 URL）
    2. 如果是 .silk 格式，使用 ffmpeg 转换为 .wav（16kHz 单声道）
    3. 优先使用 sherpa-onnx SenseVoice Small 模型识别
    4. 降级方案：通义千问 ASR API（需配置 QWEN_API_KEY）
    5. 返回识别文本
    """
    import tempfile
    import subprocess
    import httpx

    logger.info(f"[ASR] 开始识别语音: url={body.audio_url[:60]}..., format={body.audio_format}")

    # 1. 下载音频文件
    tmp_dir = tempfile.mkdtemp(prefix="asr_")
    raw_ext = f".{body.audio_format.lower()}"
    raw_path = os.path.join(tmp_dir, f"voice{raw_ext}")
    wav_path = os.path.join(tmp_dir, "voice.wav")

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(body.audio_url)
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"下载音频失败: HTTP {resp.status_code}")
            with open(raw_path, "wb") as f:
                f.write(resp.content)
        logger.info(f"[ASR] 音频下载完成: {len(resp.content)} bytes")

        # 2. 转换为 wav（16kHz 单声道），silk 格式需要特殊处理
        convert_ok = _convert_to_wav(raw_path, wav_path, body.audio_format)
        if not convert_ok:
            # 转换失败时尝试直接用原始文件（mp3/wav 可能直接可用）
            wav_path = raw_path

        # 3. 优先使用 SenseVoice（sherpa-onnx）识别
        text, engine = await _transcribe_with_sense_voice(wav_path)

        # 4. SenseVoice 不可用时降级到通义千问 ASR
        if text is None:
            text, engine = await _transcribe_with_qwen_asr(raw_path, body.audio_format)

        # 5. 最终降级：返回空文本提示
        if text is None:
            text = ""
            engine = "none"
            logger.warning("[ASR] 所有识别引擎均不可用，返回空文本")

        logger.info(f"[ASR] 识别完成: engine={engine}, text_len={len(text)}, text={text[:50]}")
        return ASRTranscribeResponse(text=text, engine=engine)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ASR] 识别失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"语音识别失败: {str(e)}")
    finally:
        # 清理临时文件
        import shutil
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _convert_to_wav(input_path: str, output_path: str, audio_format: str) -> bool:
    """
    使用 ffmpeg 将音频转换为 16kHz 单声道 WAV 格式。
    silk 格式需要 ffmpeg 的 silk 解码支持（或先用 silk-v3-decoder 转换）。
    返回 True 表示转换成功。
    """
    import subprocess

    try:
        # ffmpeg 转换命令：输出 16kHz 单声道 PCM WAV
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ar", "16000",   # 采样率 16kHz（SenseVoice 要求）
            "-ac", "1",       # 单声道
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
            logger.info(f"[ASR] ffmpeg 转换成功: {input_path} → {output_path}")
            return True
        else:
            logger.warning(f"[ASR] ffmpeg 转换失败: {result.stderr[-200:]}")
            return False
    except FileNotFoundError:
        logger.warning("[ASR] ffmpeg 未安装，跳过格式转换")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("[ASR] ffmpeg 转换超时")
        return False
    except Exception as e:
        logger.warning(f"[ASR] ffmpeg 转换异常: {e}")
        return False


async def _transcribe_with_sense_voice(wav_path: str) -> tuple[Optional[str], str]:
    """
    使用 sherpa-onnx SenseVoice Small 模型进行语音识别。
    模型路径从环境变量 SENSE_VOICE_MODEL_DIR 读取，
    默认查找 /app/models/asr/sense-voice 目录。
    返回 (识别文本, 引擎名称)，失败返回 (None, "sense_voice")。
    """
    import asyncio

    def _sync_transcribe():
        try:
            import sherpa_onnx
            import wave
            import numpy as np

            # 查找模型文件
            models_dir = os.environ.get(
                "SENSE_VOICE_MODEL_DIR",
                os.path.join(os.path.dirname(__file__), "..", "..", "models", "asr", "sense-voice")
            )
            models_dir = os.path.abspath(models_dir)

            model_file = None
            tokens_file = None

            # 递归搜索 .onnx 和 tokens.txt
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
                logger.info(f"[ASR] SenseVoice 模型未找到，跳过: models_dir={models_dir}")
                return None

            logger.info(f"[ASR] 使用 SenseVoice 模型: {model_file}")

            # 创建识别器
            recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=model_file,
                tokens=tokens_file,
                num_threads=2,
                use_itn=True,
                debug=False,
            )

            # 读取 WAV 文件
            with wave.open(wav_path, "rb") as wf:
                sample_rate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())

            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

            # 分段处理（每段 30 秒）
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
            logger.info("[ASR] sherpa_onnx 未安装，跳过 SenseVoice")
            return None
        except Exception as e:
            logger.warning(f"[ASR] SenseVoice 识别失败: {e}")
            return None

    # 在线程池中运行同步识别，避免阻塞事件循环
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _sync_transcribe)
    return (text, "sense_voice") if text is not None else (None, "sense_voice")


async def _transcribe_with_qwen_asr(audio_path: str, audio_format: str) -> tuple[Optional[str], str]:
    """
    使用通义千问 ASR API 进行语音识别（降级方案）。
    需要配置 QWEN_API_KEY 环境变量。
    返回 (识别文本, 引擎名称)，失败返回 (None, "qwen_asr")。
    """
    import httpx
    import base64

    qwen_api_key = os.environ.get("QWEN_API_KEY", "")
    if not qwen_api_key:
        logger.info("[ASR] QWEN_API_KEY 未配置，跳过通义千问 ASR")
        return None, "qwen_asr"

    try:
        # 读取音频文件并 base64 编码
        with open(audio_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode("utf-8")

        # 确定 MIME 类型
        mime_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "amr": "audio/amr",
            "silk": "audio/silk",
            "m4a": "audio/mp4",
        }
        mime_type = mime_map.get(audio_format.lower(), "audio/mpeg")

        # 调用通义千问多模态 API（支持音频输入）
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
                    logger.info(f"[ASR] 通义千问 ASR 识别成功: {text[:50]}")
                    return text.strip(), "qwen_asr"
            else:
                logger.warning(f"[ASR] 通义千问 ASR 失败: HTTP {resp.status_code}, {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"[ASR] 通义千问 ASR 异常: {e}")

    return None, "qwen_asr"


# ==================== SILK 音频解码接口 ====================


@router.post("/silk/decode", summary="SILK 音频解码（silk → PCM）")
async def internal_silk_decode(
    file: UploadFile = File(...),
    auth_user: AuthenticatedUser = Depends(verify_internal_request),
):
    """
    将企业微信 .silk 格式音频解码为 PCM 原始数据。

    使用 pilk 库（纯 Python SILK 解码器）进行解码，无需外部二进制工具。

    处理流程：
    1. 接收上传的 .silk 文件
    2. 使用 pilk.decode() 解码为 PCM（16-bit little-endian，24000Hz 单声道）
    3. 返回 PCM 二进制数据（Content-Type: application/octet-stream）

    Returns:
        PCM 二进制数据流，采样率 24000Hz，16-bit little-endian，单声道
    """
    import asyncio
    import tempfile
    from fastapi.responses import Response

    logger.info(f"[SILK] 收到解码请求: filename={file.filename}, size={file.size}")

    tmp_dir = tempfile.mkdtemp(prefix="silk_")
    silk_path = os.path.join(tmp_dir, "input.silk")
    pcm_path = os.path.join(tmp_dir, "output.pcm")

    try:
        # 保存上传的 silk 文件
        content = await file.read()
        with open(silk_path, "wb") as f:
            f.write(content)

        # 使用 pilk 解码 SILK → PCM
        def _decode():
            import pilk
            # pilk.decode 返回音频时长（毫秒）
            # 输出 PCM 格式：16-bit little-endian，24000Hz，单声道
            duration_ms = pilk.decode(silk_path, pcm_path)
            return duration_ms

        duration_ms = await asyncio.to_thread(_decode)

        # 读取 PCM 数据
        with open(pcm_path, "rb") as f:
            pcm_data = f.read()

        logger.info(f"[SILK] 解码成功: duration={duration_ms}ms, pcm_size={len(pcm_data)} bytes")

        return Response(
            content=pcm_data,
            media_type="application/octet-stream",
            headers={
                "X-Audio-Duration-Ms": str(duration_ms),
                "X-Audio-SampleRate": "24000",
                "X-Audio-Channels": "1",
                "X-Audio-Format": "s16le",
            },
        )

    except ImportError:
        logger.error("[SILK] pilk 库未安装，请在 requirements.txt 中添加 pilk")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SILK 解码库未安装",
        )
    except Exception as e:
        logger.error(f"[SILK] 解码失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SILK 解码失败: {str(e)}",
        )
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
