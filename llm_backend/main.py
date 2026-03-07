from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Form, Depends, Request, Response, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
import sys
import os
import asyncio
# Add graphrag to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), "app", "graphrag"))

from app.services.llm_factory import LLMFactory
from app.services.search_service import SearchService
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from pathlib import Path

from app.core.logger import get_logger, log_structured
from app.core.middleware import LoggingMiddleware
from app.core.config import settings
from app.core.security import get_current_user
from app.api import api_router
from app.core.database import AsyncSessionLocal
from app.models.conversation import Conversation, DialogueType
from app.models.message import Message
from app.models.user import User
from sqlalchemy import select, delete
from app.services.conversation_service import ConversationService
# from app.services.rag_chat_service import RAGChatService
from app.models.knowledge_base import KnowledgeBase
import uuid
import os
# from app.services.indexing_service import IndexingService
import sys
from app.lg_agent.lg_states import AgentState, InputState
from app.lg_agent.utils import new_uuid
# from app.lg_agent.lg_builder import graph
from langgraph.types import Command
from langchain_core.messages import AIMessage, AIMessageChunk
import json


# 配置上传目录 - RAG 功能的
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# logger 变量就被初始化为一个日志记录器实例。
# 之后，便可以在当前文件中直接使用 logger.info()、logger.error() 等方法来记录日志，而不需要进行其他操作。
logger = get_logger(service="main")


# ==================== 流式输出辅助函数 ====================

async def stream_content_with_typing_effect(content: str, delay: float = 0.01):
    """
    将内容按打字效果流式输出
    
    Args:
        content: 要输出的内容
        delay: 每个字符的延迟（秒），默认 0.01 秒
    
    Yields:
        SSE 格式的数据块
    """
    # 智能分块：中文按 1 个字符，英文/数字按 2-3 个字符
    i = 0
    while i < len(content):
        char = content[i]
        
        # 判断是否是中文字符
        if '\u4e00' <= char <= '\u9fff':
            # 中文：每次发送 1 个字符
            chunk = content[i:i+1]
            i += 1
        else:
            # 英文/数字/符号：每次发送 2-3 个字符
            chunk = content[i:i+3]
            i += 3
        
        # 发送数据块
        content_json = json.dumps(chunk, ensure_ascii=False)
        yield f"data: {content_json}\n\n"
        
        # 添加微小延迟，模拟打字效果
        if delay > 0:
            await asyncio.sleep(delay)


# 创建 FastAPI 应用实例
app = FastAPI(
    title="智能对话 REST API",
    description="""
## 接口说明

本系统提供智能对话、知识库管理、微信公众号集成等功能的 REST API。

### 认证方式

所有需要认证的接口均使用 **Bearer Token** 方式：

```
Authorization: Bearer <您的 JWT 密钥>
```

获取 Token 方式：
1. 调用 `POST /api/token` 登录接口，传入邮箱和密码
2. 返回的 `access_token` 即为 JWT Token
3. 也可在系统设置 → JWT 认证 中查看您的专属 API 密钥

### 接口分组

- **用户认证**：注册、登录、获取当前用户信息
- **对话管理**：创建会话、发送消息、查看历史
- **知识库**：上传文档、查询文档列表、删除文档
- **系统配置**：查看和修改 AI 参数配置
- **微信集成**：微信公众号自动回复配置
    """,
    version="1.0.0",
    openapi_tags=[
        {"name": "用户认证", "description": "用户注册、登录及身份验证相关接口"},
        {"name": "对话管理", "description": "会话创建、消息发送、历史记录查询"},
        {"name": "知识库", "description": "文档上传、索引管理、内容查询"},
        {"name": "系统配置", "description": "AI 模型参数、API Key 等系统配置"},
        {"name": "微信集成", "description": "微信公众号自动回复配置管理"},
        {"name": "文件上传", "description": "图片及文件上传接口"},
        {"name": "健康检查", "description": "服务状态检查"},
    ],
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "requestSnippetsEnabled": True,
        "requestSnippets": {
            "generators": {
                "curl_bash":       {"title": "cURL (bash)",       "syntax": "bash"},
                "curl_powershell": {"title": "cURL (PowerShell)", "syntax": "powershell"},
                "curl_cmd":        {"title": "cURL (CMD)",        "syntax": "bat"},
            },
            "defaultExpanded": True,
            "languages": None,
        },
    },
    docs_url=None,  # 关闭默认 docs，使用自定义
)

# 添加日志中间件， 使用 LoggingMiddleware 来统一处理日志记录，从而替代 FastAPI 的原生打印日志。
app.add_middleware(LoggingMiddleware)

# CORS设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中要设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. 用户注册、登录路由通过 api_router 路由挂载到 /api 前缀
app.include_router(api_router, prefix="/api")

# 覆盖 openapi schema，全局注入 Bearer 安全方案
from fastapi.openapi.utils import get_openapi

def _build_code_samples(method: str, path: str, operation: dict, is_public: bool) -> list:
    """为每个接口生成多语言代码示例"""
    base_url = "https://chat.aigcqun.cn"
    url = base_url + path
    method_upper = method.upper()
    auth_header_py = '' if is_public else '\n    headers["Authorization"] = "Bearer <YOUR_TOKEN>"'
    auth_header_js = '' if is_public else '\n  "Authorization": "Bearer <YOUR_TOKEN>",'
    auth_header_go = '' if is_public else '\n\treq.Header.Set("Authorization", "Bearer <YOUR_TOKEN>")'

    # 判断请求体类型
    req_body = operation.get("requestBody", {})
    content = req_body.get("content", {})
    is_form = "multipart/form-data" in content or "application/x-www-form-urlencoded" in content
    is_json = "application/json" in content

    if is_json:
        py_body = '    data = {{}}  # 填写请求体\n    response = requests.{method}(url, json=data, headers=headers)'.format(method=method.lower())
        js_body = '  body: JSON.stringify({{}}),  // 填写请求体\n  headers: {{\n    "Content-Type": "application/json",{auth}\n  }}'.format(auth=auth_header_js)
        go_body = 'body := strings.NewReader(`{{}}`)\n\treq, _ := http.NewRequest("{method}", "{url}", body)\n\treq.Header.Set("Content-Type", "application/json"){auth}'.format(method=method_upper, url=url, auth=auth_header_go)
    elif is_form:
        py_body = '    files = {{}}  # 填写表单数据\n    response = requests.{method}(url, data=files, headers=headers)'.format(method=method.lower())
        js_body = '  body: new FormData(),  // 填写表单数据\n  headers: {{\n    {auth}\n  }}'.format(auth=auth_header_js.strip())
        go_body = 'req, _ := http.NewRequest("{method}", "{url}", nil){auth}'.format(method=method_upper, url=url, auth=auth_header_go)
    else:
        py_body = '    response = requests.{method}(url, headers=headers)'.format(method=method.lower())
        js_body = '  headers: {{\n    {auth}\n  }}'.format(auth=auth_header_js.strip())
        go_body = 'req, _ := http.NewRequest("{method}", "{url}", nil){auth}'.format(method=method_upper, url=url, auth=auth_header_go)

    python_code = '''import requests

url = "{url}"
headers = {{"accept": "application/json"}}{auth}
{body}
print(response.json())'''.format(url=url, auth=auth_header_py, body=py_body)

    js_code = '''const response = await fetch("{url}", {{
  method: "{method}",
  {body}
}});
const data = await response.json();
console.log(data);'''.format(url=url, method=method_upper, body=js_body)

    go_code = '''package main

import (
\t"fmt"
\t"net/http"
\t"strings"
)

func main() {{
\t{body}
\tclient := &http.Client{{}}
\tresp, _ := client.Do(req)
\tdefer resp.Body.Close()
\tfmt.Println(resp.Status)
}}'''.format(body=go_body)

    return [
        {"lang": "Python", "source": python_code},
        {"lang": "JavaScript", "source": js_code},
        {"lang": "Go", "source": go_code},
    ]


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        tags=app.openapi_tags,
        routes=app.routes,
    )
    # 注入 Bearer 安全方案
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "请输入您的 JWT Token。格式：Bearer <token>",
        }
    }
    # 不需要认证的公开接口
    public_paths = {"/api/register", "/api/token", "/health", "/wx_mp_cb",
                    "/api/wechat/callback"}
    # 强制给所有非公开路由加上安全要求（覆盖 FastAPI 自动生成的空 security: []）
    for path, path_item in schema.get("paths", {}).items():
        is_public = any(path.startswith(p) for p in public_paths)
        for method, operation in path_item.items():
            if isinstance(operation, dict):
                if is_public:
                    operation["security"] = []
                else:
                    operation["security"] = [{"BearerAuth": []}]
                # 注入多语言代码示例
                operation["x-codeSamples"] = _build_code_samples(method, path, operation, is_public)
    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi
# 清除缓存，确保下次请求重新生成
app.openapi_schema = None


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html>
<head>
  <title>智能对话 REST API</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <rapi-doc
    spec-url="/openapi.json"
    theme="dark"
    bg-color="#1a1a2e"
    text-color="#e0e0e0"
    primary-color="#4fc3f7"
    render-style="read"
    show-header="true"
    show-info="true"
    allow-authentication="true"
    allow-server-selection="false"
    show-components="false"
    default-schema-tab="example"
    schema-description-expanded="true"
    fill-request-fields-with-example="true"
  ></rapi-doc>
  <script type="module" src="https://unpkg.com/rapidoc/dist/rapidoc-min.js"></script>
</body>
</html>""")


def _migrate_add_missing_columns(conn):
    """启动时自动补全已有表中缺失的列（幂等，列已存在则跳过）"""
    from sqlalchemy import text, inspect
    inspector = inspect(conn)

    migrations = [
        # (表名, 列名, 列定义SQL)
        ("wechat_configs", "appsecret", "VARCHAR(255)"),
        ("knowledge_base", "embedding_type", "VARCHAR(50)"),
    ]

    for table, column, col_def in migrations:
        try:
            existing = [c["name"] for c in inspector.get_columns(table)]
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
                logger.info(f"迁移: {table}.{column} 列已添加")
        except Exception as e:
            logger.warning(f"迁移 {table}.{column} 跳过: {e}")


@app.on_event("startup")
async def startup_event():
    """应用启动时执行初始化"""
    try:
        # 初始化 Checkpointer 表结构
        from app.lg_agent.lg_builder import checkpointer
        if hasattr(checkpointer, "ensure_tables"):
            await checkpointer.ensure_tables()
            logger.info("Checkpointer tables ensured.")
    except Exception as e:
        logger.error(f"Startup initialization failed: {e}", exc_info=True)

    # 自动建表（user_settings 等新增表）
    try:
        from app.core.database import engine, Base
        import app.models  # noqa: 确保所有模型都被导入，触发 metadata 注册
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("数据库表结构已同步")
    except Exception as e:
        logger.error(f"数据库表结构同步失败: {e}", exc_info=True)

    # 自动补列迁移（create_all 不会给已有表加新列）
    try:
        from app.core.database import engine
        async with engine.begin() as conn:
            await conn.run_sync(_migrate_add_missing_columns)
        logger.info("数据库列迁移完成")
    except Exception as e:
        logger.error(f"数据库列迁移失败: {e}", exc_info=True)

    # 初始化系统配置：首次部署从 .env 写入数据库，然后从数据库加载
    try:
        await settings.init_db_settings()
        await settings.load_from_db()
        logger.info("系统配置已从数据库加载")
    except Exception as e:
        logger.error(f"系统配置初始化失败，使用 .env 默认值: {e}", exc_info=True)

class ReasonRequest(BaseModel):
    messages: List[Dict[str, str]]
    user_id: int

class ChatMessage(BaseModel):
    messages: List[Dict[str, str]]
    user_id: int
    conversation_id: int  # 添加会话ID字段

class RAGChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    index_id: str
    user_id: int

class CreateConversationRequest(BaseModel):
    user_id: int

class UpdateConversationNameRequest(BaseModel):
    name: str

class LangGraphRequest(BaseModel):
    query: str
    user_id: int
    conversation_id: Optional[str] = None
    image: Optional[UploadFile] = None

class LangGraphResumeRequest(BaseModel):
    query: str
    user_id: int
    conversation_id: str


@app.get("/health", tags=["健康检查"], summary="服务健康检查", description="检查服务是否正常运行")
async def health_check():
    return {"status": "ok"}

# 微信公众号回调路由（直接处理，不重定向）
@app.get("/wx_mp_cb")
async def wechat_callback_get(
    config_id: int = Query(...),
    signature: str = Query(...),  # 微信验证使用signature参数
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...)
):
    """微信公众号回调（GET）- 验证服务器"""
    from app.models.wechat_config import WechatConfig
    from app.services.wechat_service import WechatService
    from sqlalchemy import select
    
    try:
        async with AsyncSessionLocal() as db:
            # 获取配置
            result = await db.execute(
                select(WechatConfig).where(WechatConfig.id == config_id)
            )
            config = result.scalar_one_or_none()
            
            if not config or not config.is_active:
                logger.error(f"配置不存在或未启用: config_id={config_id}")
                raise HTTPException(status_code=404, detail="配置不存在或未启用")
            
            logger.info(f"微信验证请求: config_id={config_id}, signature={signature}, timestamp={timestamp}, nonce={nonce}, echostr={echostr[:20]}...")
            
            # 验证签名
            wechat_service = WechatService(config)
            verified_echostr = wechat_service.verify_signature(signature, timestamp, nonce, echostr)
            
            if verified_echostr:
                logger.info(f"微信验证成功，config_id={config_id}, 返回echostr={verified_echostr}")
                # 返回纯文本响应（微信要求）
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse(content=verified_echostr, status_code=200)
            else:
                logger.error(f"微信验证失败，config_id={config_id}, signature={signature}")
                raise HTTPException(status_code=403, detail="签名验证失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"微信回调验证失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")

@app.post("/wx_mp_cb")
async def wechat_callback_post(
    request: Request,
    background_tasks: BackgroundTasks,
    config_id: int = Query(...),
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...)
):
    """微信公众号回调（POST）- 接收消息"""
    from app.models.wechat_config import WechatConfig
    from app.services.wechat_service import WechatService
    from sqlalchemy import select
    
    try:
        async with AsyncSessionLocal() as db:
            # 获取配置
            result = await db.execute(
                select(WechatConfig).where(WechatConfig.id == config_id)
            )
            config = result.scalar_one_or_none()
            
            if not config or not config.is_active:
                raise HTTPException(status_code=404, detail="配置不存在或未启用")
            
            # 获取请求体
            body = await request.body()
            
            # 处理消息 - 增加 4 秒超时控制
            wechat_service = WechatService(config)
            try:
                # 尝试在 4 秒内完成处理并直接回复 XML
                response = await asyncio.wait_for(
                    wechat_service.handle_message(body, signature, timestamp, nonce, db),
                    timeout=4.0
                )
                return Response(content=response, media_type="text/xml")
            except asyncio.TimeoutError:
                # 超时则转入后台异步处理，并立即回复 success 以防微信报错
                logger.info(f"微信消息处理超时 (4s)，转入后台异步任务: config_id={config_id}")
                background_tasks.add_task(_handle_wechat_async, body, signature, timestamp, nonce, config_id)
                return Response(content=b"success", media_type="text/plain")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"微信消息处理失败: {str(e)}", exc_info=True)
        return Response(content=b"success", media_type="text/plain")

async def _handle_wechat_async(body: bytes, signature: str, timestamp: str, nonce: str, config_id: int):
    """后台处理微信消息并异步回复（客服消息）"""
    from app.services.wechat_service import WechatService
    from app.models.wechat_config import WechatConfig
    from sqlalchemy import select
    import xml.etree.cElementTree as ET
    from wx_mp_svr import WxMpReqMsg

    try:
        async with AsyncSessionLocal() as db:
            # 1. 获取配置
            result = await db.execute(select(WechatConfig).where(WechatConfig.id == config_id))
            config = result.scalar_one_or_none()
            if not config or not config.is_active: return
            
            wechat_service = WechatService(config)
            
            # 2. 解密以获取 OpenID 和内容
            ret, xml_content = wechat_service.wx_crypt.DecryptMsg(body, signature, timestamp, nonce)
            if ret != 0: return
            
            xml_tree = ET.fromstring(xml_content)
            req_msg = WxMpReqMsg.create_msg(xml_tree)
            openid = req_msg.from_user_name
            
            if req_msg.msg_type != "text": return # 暂时只处理异步文本回复

            # 3. 调用 AI 逻辑（bypass_dedup=True 因为同步请求可能已经设置了 dedup_key）
            ai_reply = await wechat_service._get_ai_reply(req_msg.content, db)
            
            # 4. 发送客服消息
            await wechat_service.send_custom_message(openid, ai_reply)
    except Exception as e:
        logger.error(f"后台异步处理微信消息异常: {e}", exc_info=True)

@app.post("/api/chat", tags=["对话管理"], summary="普通对话", description="基于 LLM 的流式对话接口，返回 SSE 流式响应")
async def chat_endpoint(request: ChatMessage, current_user: User = Depends(get_current_user)):
    """聊天接口"""
    try:
        logger.info(f"Processing chat request for user {request.user_id} in conversation {request.conversation_id}")
        chat_service = LLMFactory.create_chat_service()
        
        return StreamingResponse(
            chat_service.generate_stream(
                messages=request.messages,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                on_complete=ConversationService.save_message
            ),
            media_type="text/event-stream"
        )
    except Exception as e:
        logger.error(f"Chat error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/reason", tags=["对话管理"], summary="深度推理对话", description="使用推理模型进行深度思考的流式对话接口")
async def reason_endpoint(request: ReasonRequest, current_user: User = Depends(get_current_user)):
    """推理接口"""
    try:
        logger.info(f"Processing reasoning request for user {request.user_id}")
        reasoner = LLMFactory.create_reasoner_service()
        
        log_structured("reason_request", {
            "user_id": request.user_id,
            "message_count": len(request.messages),
            "last_message": request.messages[-1]["content"][:100] + "..."
        })
        
        return StreamingResponse(
            reasoner.generate_stream(request.messages),
            media_type="text/event-stream"
        )
    
    except Exception as e:
        logger.error(f"Reasoning error for user {request.user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/search", tags=["对话管理"], summary="联网搜索对话", description="结合联网搜索结果进行回答的流式对话接口")
async def search_endpoint(request: ChatMessage, current_user: User = Depends(get_current_user)):
    """带搜索功能的聊天接口"""
    try:
        logger.info(f"Processing search request for user {request.user_id} in conversation {request.conversation_id}")
        logger.info(f"Request: {request}")
        search_service = LLMFactory.create_search_service()
        return StreamingResponse(
            search_service.generate_stream(
                query=request.messages[0]["content"],
                user_id=request.user_id,
                conversation_id=request.conversation_id,
            ),
            media_type="text/event-stream"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _sync_write_file(path: str, data: bytes):
    """同步写文件，供 asyncio.to_thread 调用"""
    with open(path, "wb") as f:
        f.write(data)


@app.post("/api/upload", tags=["知识库"], summary="上传知识库文档", description="上传文档（PDF、TXT 等）到知识库，系统将自动进行索引处理")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    user_id: int = Form(...),
    current_user: User = Depends(get_current_user)
):
    """上传文件并准备 RAG 处理 (异步后台索引)"""
    try:
        logger.info(f"Uploading file for user {user_id}: {file.filename}")

        # 0. 检查用户是否存在，不存在则创建 (Fix IntegrityError)
        async with AsyncSessionLocal() as session:
            # 检查用户
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()
            if not user:
                logger.info(f"User {user_id} not found, creating new user...")
                new_user = User(
                    id=user_id, # Use the ID from frontend
                    username=f"user_{user_id}",
                    email=f"user_{user_id}@admin.com",
                    password_hash="hashed_password_placeholder", # In a real app, use proper hashing
                    status="active"
                )
                session.add(new_user)
                await session.commit()
                logger.info(f"Created new user {user_id}")

            # 1. 检查 Embedding 配置是否完善（未配置则拒绝上传）
            from app.core.user_config import check_knowledge_base_config_ready
            is_ready, err_msg = await check_knowledge_base_config_ready(
                user_id, session, is_admin=(current_user.role == "admin")
            )
            if not is_ready:
                raise HTTPException(status_code=422, detail=err_msg)
        
        # 1. 创建基于UUID的一级目录
        user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{user_id}"))
        first_level_dir = UPLOAD_DIR / user_uuid
        
        # 2. 创建基于时间戳的二级目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        second_level_dir = first_level_dir / timestamp
        second_level_dir.mkdir(parents=True, exist_ok=True)
        
        # 3. 生成带时间戳的文件名（清理特殊字符，确保 URL 安全）
        import re
        original_name, ext = os.path.splitext(file.filename)
        # 将空格、括号等特殊字符替换为下划线，避免 MinerU 等外部服务解析 URL 失败
        safe_name = re.sub(r'[\s\(\)\[\]\{\}#%&\+\?=]', '_', original_name)
        safe_name = re.sub(r'_+', '_', safe_name).strip('_') or 'file'
        new_filename = f"{safe_name}_{timestamp}{ext}"
        file_path = second_level_dir / new_filename
        
        # 保存文件 (异步写入，避免阻塞事件循环)
        content = await file.read()
        await asyncio.to_thread(_sync_write_file, str(file_path), content)
            
        # 获取文件信息
        file_info = {
            "filename": new_filename,
            "original_name": file.filename,
            "size": len(content),
            "type": file.content_type,
            "path": str(file_path).replace('\\', '/'),
            "user_id": user_id,
            "user_uuid": user_uuid,
            "upload_time": timestamp,
            "directory": str(second_level_dir)
        }
        
        # 4. 提交后台任务进行索引处理
        from app.services.indexing_service import IndexingService
        indexing_service = IndexingService()

        # 自动从请求头提取服务器公网 base URL（供 MinerU 构造文件访问链接）
        forwarded_proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        server_base_url = f"{forwarded_proto}://{forwarded_host}"
        file_info["server_base_url"] = server_base_url
        logger.info(f"服务器公网地址（自动检测）: {server_base_url}")
        
        # 如果数据库中尚未保存服务器地址，自动持久化（避免每次都依赖请求头）
        if server_base_url and not settings.SERVER_BASE_URL:
            try:
                from app.models.system_settings import SystemSettings
                from sqlalchemy import select as sa_select
                async with AsyncSessionLocal() as _sess:
                    row = await _sess.execute(
                        sa_select(SystemSettings).where(SystemSettings.key == "SERVER_BASE_URL")
                    )
                    existing = row.scalar_one_or_none()
                    if existing:
                        existing.value = server_base_url
                    else:
                        _sess.add(SystemSettings(
                            key="SERVER_BASE_URL",
                            value=server_base_url,
                            group_name="mineru",
                            label="服务器公网地址（自动检测）",
                            value_type="readonly_auto",
                            sort_order=79,
                        ))
                    await _sess.commit()
                await settings.reload()
                logger.info(f"服务器公网地址已自动保存到数据库: {server_base_url}")
            except Exception as _e:
                logger.warning(f"保存服务器地址到数据库失败（不影响上传）: {_e}")
        
        # 预先创建数据库记录以获取 ID，并回传给前端以保持兼容性
        record_id = await indexing_service.create_db_record(file_info)
        
        # ★ 使用 asyncio.create_task 而非 BackgroundTasks
        # BackgroundTasks 在响应发送后仍在主事件循环中串行执行，
        # 如果 process_file 耗时很长（GraphRAG 索引需要几分钟），会阻塞所有后续请求。
        # create_task 让任务在后台并发执行，process_file 内部的重活已通过 run_in_executor 放到线程池。
        asyncio.create_task(indexing_service.process_file(file_info, record_id))
        
        # 构造与旧版前端完全兼容的响应对象：平铺 file_info 并在 index_result 中提供初始状态
        result = {
            **file_info,
            "index_result": {
                "id": record_id,
                "status": "indexing",
                "message": "文件已进入后台索引流程"
            }
        }
        
        return result
        
    except Exception as e:
        logger.error("Upload failed for user {}: {}", user_id, str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat-rag")
async def rag_chat_endpoint(request: RAGChatRequest, current_user: User = Depends(get_current_user)):
    """基于文档的问答接口"""
    try:
        from app.services.rag_chat_service import RAGChatService
        logger.info(f"Processing RAG chat request for user {request.user_id}")
        rag_chat_service = RAGChatService()
        
        return StreamingResponse(
            rag_chat_service.generate_stream(
                request.messages,
                request.index_id
            ),
            media_type="text/event-stream"
        )
    except Exception as e:
        logger.error(f"RAG chat error for user {request.user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/knowledge-base/user/{user_id}", tags=["知识库"], summary="获取知识库列表", description="获取指定用户的所有知识库文档列表及索引状态")
async def get_knowledge_base(user_id: int, current_user: User = Depends(get_current_user)):
    """获取用户的知识库文件列表"""
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(KnowledgeBase).where(KnowledgeBase.user_id == user_id).order_by(KnowledgeBase.created_at.desc())
            result = await session.execute(stmt)
            items = result.scalars().all()
            return items
    except Exception as e:
        logger.error(f"Error getting knowledge base: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/knowledge-base/{item_id}", tags=["知识库"], summary="删除知识库文档", description="删除指定知识库文档及其所有索引数据，如该用户无其他文档则清理全部索引")
async def delete_knowledge_item(item_id: int, current_user: User = Depends(get_current_user)):
    """删除知识库文件及其索引，清理所有产生的文件索引和数据"""
    try:
        import shutil

        async with AsyncSessionLocal() as session:
            # 1. 获取记录
            stmt = select(KnowledgeBase).where(KnowledgeBase.id == item_id)
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()
            
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")
            
            user_id = item.user_id
            
            # 2. 删除上传的物理文件
            if os.path.exists(item.file_path):
                os.remove(item.file_path)
                # 尝试清理空的时间戳子目录
                parent_dir = os.path.dirname(item.file_path)
                if os.path.isdir(parent_dir) and not os.listdir(parent_dir):
                    os.rmdir(parent_dir)
            
            # 3. 删除数据库记录
            await session.delete(item)
            
            # 4. 检查该用户是否还有其他知识库文件
            remaining_stmt = select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.id != item_id
            )
            remaining_result = await session.execute(remaining_stmt)
            remaining_items = remaining_result.scalars().all()
            
            # 5. 清理 GraphRAG 产生的索引数据
            user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{user_id}"))
            graphrag_data_dir = Path(settings.GRAPHRAG_PROJECT_DIR) / settings.GRAPHRAG_DATA_DIR
            
            cleaned_dirs = []
            
            if not remaining_items:
                # 该用户没有其他知识库文件了，彻底清理所有 GraphRAG 数据
                
                # 清理 GraphRAG input 目录（提取后的 txt 文件）
                user_input_dir = graphrag_data_dir / "input" / user_uuid
                if user_input_dir.exists():
                    shutil.rmtree(str(user_input_dir), ignore_errors=True)
                    cleaned_dirs.append(f"input/{user_uuid}")
                
                # 清理 GraphRAG output 目录（parquet、lancedb、artifacts 等）
                user_output_dir = graphrag_data_dir / "output" / user_uuid
                if user_output_dir.exists():
                    shutil.rmtree(str(user_output_dir), ignore_errors=True)
                    cleaned_dirs.append(f"output/{user_uuid}")
                
                # 清理 uploads 目录下该用户的文件夹
                user_upload_dir = UPLOAD_DIR / user_uuid
                if user_upload_dir.exists():
                    shutil.rmtree(str(user_upload_dir), ignore_errors=True)
                    cleaned_dirs.append(f"uploads/{user_uuid}")
                
                logger.info(f"用户 {user_id} 知识库已全部清空，已删除目录: {cleaned_dirs}")
            else:
                # 还有其他文件，只清理 GraphRAG 数据（因为索引是整体构建的，部分删除后需要重建）
                user_output_dir = graphrag_data_dir / "output" / user_uuid
                if user_output_dir.exists():
                    shutil.rmtree(str(user_output_dir), ignore_errors=True)
                    cleaned_dirs.append(f"output/{user_uuid}")
                
                logger.info(f"用户 {user_id} 删除了一个文件，索引数据已清理（需重建索引）: {cleaned_dirs}")
            
            # 6. 清理该用户的 checkpoint 缓存
            from app.core.checkpointer import CheckpointModel, CheckpointWriteModel
            from app.models import Conversation
            
            conv_stmt = select(Conversation.id).where(Conversation.user_id == user_id)
            conv_result = await session.execute(conv_stmt)
            conversation_ids = [str(row[0]) for row in conv_result.fetchall()]
            
            cleaned_checkpoints = 0
            cleaned_checkpoint_writes = 0
            
            if conversation_ids:
                checkpoint_delete_stmt = delete(CheckpointModel).where(
                    CheckpointModel.thread_id.in_(conversation_ids)
                )
                checkpoint_result = await session.execute(checkpoint_delete_stmt)
                cleaned_checkpoints = checkpoint_result.rowcount
                
                checkpoint_writes_delete_stmt = delete(CheckpointWriteModel).where(
                    CheckpointWriteModel.thread_id.in_(conversation_ids)
                )
                checkpoint_writes_result = await session.execute(checkpoint_writes_delete_stmt)
                cleaned_checkpoint_writes = checkpoint_writes_result.rowcount
            
            await session.commit()
            
            return {
                "message": "知识库文件及所有索引数据已彻底删除",
                "cleaned_checkpoints": cleaned_checkpoints,
                "cleaned_checkpoint_writes": cleaned_checkpoint_writes,
                "cleaned_dirs": cleaned_dirs,
                "remaining_files": len(remaining_items),
            }
    except Exception as e:
        logger.error(f"Error deleting knowledge item: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/knowledge-base/{item_id}/chunks", tags=["知识库"], summary="获取文档文本块", description="获取知识库文档经过 GraphRAG 索引后的文本块内容")
async def get_knowledge_chunks(item_id: int, current_user: User = Depends(get_current_user)):
    """获取知识库文件的文本块内容（GraphRAG text_units），按文件名过滤"""
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(KnowledgeBase).where(KnowledgeBase.id == item_id)
            result = await session.execute(stmt)
            item = result.scalar_one_or_none()
            if not item:
                raise HTTPException(status_code=404, detail="文件不存在")
            if item.status != "success":
                return {"chunks": [], "message": "索引尚未完成"}

        # 根据 user_id 和 record_id 定位文档独立的 GraphRAG 输出目录
        user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{item.user_id}"))
        from app.core.config import settings as app_settings
        project_dir = app_settings.GRAPHRAG_PROJECT_DIR
        data_dir = app_settings.GRAPHRAG_DATA_DIR

        # 优先用文档独立目录（新结构），回退到旧的用户级目录
        doc_output_dir = os.path.join(project_dir, data_dir, "output", user_uuid, str(item_id))
        legacy_output_dir = os.path.join(project_dir, data_dir, "output", user_uuid)
        output_dir = doc_output_dir if os.path.exists(doc_output_dir) else legacy_output_dir

        artifacts_dir = os.path.join(output_dir, "artifacts")
        storage_dir = artifacts_dir if os.path.exists(artifacts_dir) else output_dir

        text_units_path = os.path.join(storage_dir, "text_units.parquet")
        documents_path = os.path.join(storage_dir, "documents.parquet")

        if not os.path.exists(text_units_path):
            return {"chunks": [], "message": "未找到文本块数据"}

        import pandas as pd

        df_text = await asyncio.to_thread(pd.read_parquet, text_units_path)

        # 通过 documents.parquet 找到当前文件对应的 document_id 集合
        matched_doc_ids: set = set()
        if os.path.exists(documents_path):
            df_docs = await asyncio.to_thread(pd.read_parquet, documents_path)
            # documents 里的 title 通常是去掉扩展名的文件名，raw_content_path 是完整路径
            # 用原始文件名（去扩展名）和完整文件名两种方式匹配
            original_stem = os.path.splitext(item.original_name)[0]
            for _, doc_row in df_docs.iterrows():
                title = str(doc_row.get("title", ""))
                raw_path = str(doc_row.get("raw_content_path", ""))
                # 匹配：title 包含原始文件名（去扩展名），或路径包含原始文件名
                if (original_stem in title or
                    item.original_name in title or
                    item.original_name in raw_path or
                    original_stem in os.path.basename(raw_path)):
                    matched_doc_ids.add(str(doc_row.get("id", "")))

        chunks = []
        for idx, row in df_text.iterrows():
            # 如果找到了文档映射，按 document_ids 过滤；否则返回全部（兼容旧索引）
            if matched_doc_ids:
                doc_ids = row.get("document_ids", [])
                if doc_ids is None:
                    doc_ids = []
                # document_ids 可能是 list 或 numpy array
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
            "preview": item.preview or ""
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting knowledge chunks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 系统设置 API ====================

def _mask_password(val: str) -> str:
    """直接返回原始值，不做脱敏"""
    return val if val else ""


@app.get("/api/settings", tags=["系统配置"], summary="获取系统配置", description="管理员获取全部配置；普通用户获取 DeepSeek/Gemini/搜索/JWT 等个人配置")
async def get_all_settings(current_user: User = Depends(get_current_user)):
    """
    获取配置：
    - 管理员：返回全部分组配置（从全局 system_settings 读取）
    - 普通用户：仅返回 deepseek/gemini/search 三组，值优先从用户自己的 user_settings 读取
    """
    from app.core.config import SETTINGS_META, GROUP_LABELS, USER_CONFIGURABLE_GROUPS
    from app.models.system_settings import SystemSettings
    from app.models.user_settings import UserSettings

    is_admin = current_user.role == "admin"

    try:
        async with AsyncSessionLocal() as session:
            # 全局配置（管理员用 / 普通用户作为默认值占位）
            sys_rows = await session.execute(
                select(SystemSettings).order_by(SystemSettings.sort_order)
            )
            sys_map = {r.key: r for r in sys_rows.scalars().all()}

            # 用户自己的配置
            user_rows = await session.execute(
                select(UserSettings).where(UserSettings.user_id == current_user.id)
            )
            user_map = {r.key: r.value for r in user_rows.scalars().all()}

        meta_map = {m["key"]: m for m in SETTINGS_META}
        groups: dict = {}

        for meta in SETTINGS_META:
            group_key = meta["group"]

            # 普通用户只看可配置分组
            if not is_admin and group_key not in USER_CONFIGURABLE_GROUPS:
                continue

            # 普通用户的 jwt 分组：只显示自己的 api_key，跳过全局 SECRET_KEY / ALGORITHM
            if not is_admin and group_key == "jwt":
                # jwt 分组只插入一次（在第一个 jwt meta 时）
                if "jwt" not in groups:
                    groups["jwt"] = {"label": GROUP_LABELS.get("jwt", "JWT 认证"), "items": [
                        {
                            "key": "USER_API_KEY",
                            "value": current_user.api_key or "",
                            "group": "jwt",
                            "label": "我的 API 密钥（用于对外调用验证）",
                            "type": "readonly",
                            "sort": 70,
                        }
                    ]}
                continue

            # 取值：管理员用全局值，普通用户优先用自己的值（key类型留空，其他字段用全局默认值填充）
            if is_admin:
                sys_row = sys_map.get(meta["key"])
                from app.core.config import _env_settings as _env
                raw_val = sys_row.value if sys_row else str(getattr(_env, meta["key"], ""))
                val = _mask_password(raw_val) if meta["type"] == "password" and raw_val else raw_val
            else:
                user_val = user_map.get(meta["key"], "")
                if meta["type"] == "password":
                    # API Key 类字段：只显示用户自己填的值，空则留空（不用全局 key）
                    raw_val = user_val
                    val = _mask_password(raw_val) if raw_val else ""
                else:
                    # 非 key 字段（地址、模型名、数量等）：用户有值用用户的，否则用全局默认值
                    from app.core.config import _env_settings as _env
                    sys_row = sys_map.get(meta["key"])
                    default_val = sys_row.value if sys_row else str(getattr(_env, meta["key"], ""))
                    raw_val = user_val if user_val else default_val
                    val = raw_val

            if group_key not in groups:
                groups[group_key] = {"label": GROUP_LABELS.get(group_key, group_key), "items": []}

            groups[group_key]["items"].append({
                "key": meta["key"],
                "value": val,
                "group": group_key,
                "label": meta["label"],
                "type": meta["type"],
                "options": meta.get("options", []),
                "sort": meta["sort"],
            })

        return {"groups": groups, "is_admin": is_admin}
    except Exception as e:
        logger.error(f"获取系统配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, str]  # {key: value, ...}


@app.put("/api/settings", tags=["系统配置"], summary="保存系统配置", description="管理员保存全局配置；普通用户只能保存自己的 API Key 等个人配置")
async def update_settings(request: SettingsUpdateRequest, current_user: User = Depends(get_current_user)):
    """
    保存配置：
    - 管理员：写入全局 system_settings，并重载内存配置
    - 普通用户：只允许写 USER_CONFIGURABLE_KEYS，写入 user_settings
    """
    from app.core.config import USER_CONFIGURABLE_KEYS
    from app.models.system_settings import SystemSettings
    from app.models.user_settings import UserSettings

    is_admin = current_user.role == "admin"

    try:
        async with AsyncSessionLocal() as session:
            updated = 0
            for key, value in request.settings.items():
                if value.endswith("******"):
                    continue  # 未修改的脱敏密码跳过

                if is_admin:
                    # 管理员写全局配置
                    result = await session.execute(
                        select(SystemSettings).where(SystemSettings.key == key)
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        row.value = value
                        updated += 1
                else:
                    # 普通用户只能写允许的 key
                    if key not in USER_CONFIGURABLE_KEYS:
                        continue
                    result = await session.execute(
                        select(UserSettings).where(
                            UserSettings.user_id == current_user.id,
                            UserSettings.key == key
                        )
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        row.value = value
                    else:
                        session.add(UserSettings(user_id=current_user.id, key=key, value=value))
                    updated += 1

            await session.commit()

        if is_admin:
            await settings.reload()

        logger.info(f"用户 {current_user.id} 更新配置 {updated} 项")
        return {"message": f"已保存 {updated} 项配置", "updated": updated}
    except Exception as e:
        logger.error(f"更新配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/conversations", tags=["对话管理"], summary="创建新会话", description="创建一个新的对话会话，返回会话 ID")
async def create_conversation(request: CreateConversationRequest, current_user: User = Depends(get_current_user)):
    """创建新会话"""
    try:
        conversation_id = await ConversationService.create_conversation(request.user_id)
        return {"conversation_id": conversation_id}
    except Exception as e:
        logger.error(f"Error creating conversation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/conversations/user/{user_id}", tags=["对话管理"], summary="获取用户会话列表", description="获取指定用户的所有历史会话列表，按创建时间倒序排列")
async def get_user_conversations(user_id: int, current_user: User = Depends(get_current_user)):
    """获取用户的所有会话"""
    try:
        conversations = await ConversationService.get_user_conversations(user_id)
        return conversations
    except Exception as e:
        logger.error(f"Error getting conversations: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/conversations/{conversation_id}/messages", tags=["对话管理"], summary="获取会话消息记录", description="获取指定会话的所有消息记录，包含用户消息和 AI 回复")
async def get_conversation_messages(conversation_id: int, user_id: int, current_user: User = Depends(get_current_user)):
    """获取会话的所有消息"""
    try:
        messages = await ConversationService.get_conversation_messages(conversation_id, user_id)
        return messages
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting messages: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/conversations/{conversation_id}", tags=["对话管理"], summary="删除会话", description="删除指定会话及其所有消息记录")
async def delete_conversation(conversation_id: int, current_user: User = Depends(get_current_user)):
    """删除会话及其所有消息"""
    try:
        conversation_service = ConversationService()
        await conversation_service.delete_conversation(conversation_id)
        return {"message": "会话已删除"}
    except Exception as e:
        logger.error(f"删除会话失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/conversations/{conversation_id}/name", tags=["对话管理"], summary="修改会话名称", description="修改指定会话的显示名称")
async def update_conversation_name(
    conversation_id: int,
    request: UpdateConversationNameRequest,
    current_user: User = Depends(get_current_user)
):
    """修改会话名称"""
    try:
        conversation_service = ConversationService()
        await conversation_service.update_conversation_name(conversation_id, request.name)
        return {"message": "会话名称已更新"}
    except Exception as e:
        logger.error(f"更新会话名称失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/langgraph/query", tags=["对话管理"], summary="智能对话（主接口）", description="""
LangGraph 智能对话主接口，支持：
- 普通文字对话
- 上传图片进行图像分析
- 上传图片 + 文字生成参考图
- 纯文字生成图片（绘画意图自动识别）
- 深度思考模式（R1）
- 联网搜索模式

**请求格式**：multipart/form-data

**认证**：需要在 Header 中携带 `Authorization: Bearer <token>`
""")
async def langgraph_query(
    query: str = Form(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    deep_thinking: str = Form("false"),
    web_search: str = Form("false"),
    current_user: User = Depends(get_current_user)
):
    """使用LangGraph处理用户查询，支持图片上传"""
    try:
        deep_thinking = deep_thinking.lower() == "true"
        web_search = web_search.lower() == "true"

        logger.info(f"Processing LangGraph query for user {user_id} and conversation {conversation_id}. DeepThinking: {deep_thinking}, WebSearch: {web_search}")

        # ── 并发执行：用户检查 + 图片读取 ──────────────────────────────────
        image_bytes = None
        image_filename = None
        image_content_type = None
        if image:
            image_bytes = await image.read()
            image_filename = image.filename
            image_content_type = image.content_type

        async def _ensure_user_and_cfg():
            """检查用户存在性 + 获取用户配置 + 获取智能体配置，合并为一次 DB 会话"""
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalars().first()
                if not user:
                    logger.info(f"User {user_id} not found, creating...")
                    session.add(User(
                        id=user_id,
                        username=f"user_{user_id}",
                        email=f"{user_id}@admin.com",
                        password_hash="hashed_password_placeholder",
                        status="active",
                    ))
                    await session.commit()
                    return None, {}, ""  # 新用户，无配置
                # 获取智能体配置（提示词）
                from app.models.agent_config import AgentConfig
                agent_cfg_result = await session.execute(
                    select(AgentConfig).where(AgentConfig.user_id == user_id)
                )
                agent_cfg = agent_cfg_result.scalar_one_or_none()
                agent_system_prompt = (agent_cfg.system_prompt or "").strip() if agent_cfg else ""
                # 非管理员获取用户配置
                if user.role != "admin":
                    from app.core.user_config import get_user_settings_dict
                    cfg = await get_user_settings_dict(user_id, session)
                    return user, cfg, agent_system_prompt
                return user, {}, agent_system_prompt

        async def _save_image():
            """保存图片到磁盘（线程池），返回 Path 或 None"""
            if not image_bytes:
                return None
            image_dir = Path("uploads/images")
            image_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_name, ext = os.path.splitext(image_filename or "image")
            new_filename = f"{uuid.uuid4().hex}_{timestamp}{ext}"
            img_path = image_dir / new_filename
            await asyncio.to_thread(_sync_write_file, str(img_path), image_bytes)
            logger.info(f"Saved image {new_filename} for user {user_id}")
            return img_path

        # 并发：用户检查 + 图片保存
        (user_obj, user_llm_cfg, agent_system_prompt), image_path = await asyncio.gather(
            _ensure_user_and_cfg(),
            _save_image(),
        )

        # 校验 API Key（需要在并发结果拿到后才能判断）
        if user_obj and user_obj.role != "admin":
            if not user_llm_cfg.get("DEEPSEEK_API_KEY"):
                async def _err_stream():
                    msg = "请先在左侧【系统配置】中填写您的 DeepSeek API Key，才能开始对话。"
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(_err_stream(), media_type="text/event-stream")
            if web_search and not user_llm_cfg.get("SERPAPI_KEY"):
                async def _err_stream():
                    msg = "联网搜索需要配置 SerpAPI Key，请在【系统配置】中填写后再使用。"
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(_err_stream(), media_type="text/event-stream")

        # ── thread_id / thread_config ────────────────────────────────────
        thread_id = conversation_id if conversation_id else new_uuid()
        thread_config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
                "image_path": str(image_path) if image_path else None,
                "deep_thinking": deep_thinking,
                "web_search": web_search,
                "user_llm_cfg": user_llm_cfg,
                "agent_system_prompt": agent_system_prompt,  # 用户配置的智能体提示词
            }
        }

        # ── 并发执行：保存用户消息 + 检查中断状态 + 预取搜索结果 ──────────
        from app.lg_agent.lg_builder import graph

        async def _save_user_message():
            """立即保存用户消息，前端可立即显示"""
            try:
                db_conv_id = int(thread_id)
            except ValueError:
                return
            try:
                user_image_url = ("/" + str(image_path).replace("\\", "/")) if image_path else None
                async with AsyncSessionLocal() as session:
                    stmt = select(Conversation).where(Conversation.id == db_conv_id)
                    result = await session.execute(stmt)
                    conv = result.scalar_one_or_none()
                    if conv and conv.title == "新会话":
                        conv.title = ConversationService.get_conversation_title(query)
                    session.add(Message(
                        conversation_id=db_conv_id,
                        sender="user",
                        content=query,
                        image_url=user_image_url,
                    ))
                    await session.commit()
                    logger.info(f"Saved user message for conversation {db_conv_id}")
            except Exception as e:
                logger.error(f"Failed to save user message: {e}", exc_info=True)

        async def _check_interrupt():
            try:
                snapshot = await graph.aget_state(thread_config)
                if snapshot and hasattr(snapshot, "tasks") and snapshot.tasks:
                    for task in snapshot.tasks:
                        if hasattr(task, "interrupts") and task.interrupts:
                            return True
            except Exception as e:
                logger.warning(f"Error retrieving state: {e}")
            return False

        async def _prefetch_search():
            if not web_search:
                return None
            try:
                from app.tools.search import SearchTool
                results = await asyncio.to_thread(SearchTool().search, query, 5)
                logger.info(f"Pre-fetched {len(results)} search results")
                return results
            except Exception as e:
                logger.error(f"Pre-fetch search failed: {e}")
                return []

        # 三件事并发跑
        _, has_interrupt, search_results_for_sse = await asyncio.gather(
            _save_user_message(),
            _check_interrupt(),
            _prefetch_search(),
        )

        # 只有存在中断时才用 resume，否则始终作为新输入处理
        if has_interrupt:
            logger.info("Resuming interrupted conversation")
            async def process_stream():
                # ★ 先发送搜索结果（如果有）
                if search_results_for_sse:
                    sr_json = json.dumps({"search_results": search_results_for_sse}, ensure_ascii=False)
                    yield f"data: {sr_json}\n\n"

                full_response = ""
                is_research_plan = False
                try:
                    async for c, metadata in graph.astream(
                        Command(resume=query), 
                        stream_mode="messages", 
                        config=thread_config
                    ):
                        if c.content and not c.additional_kwargs.get("tool_calls"):
                            node_name = metadata.get("langgraph_node", "")
                            
                            # DeepSeek 思考模式：跳过 reasoning_content（思维链）
                            if c.additional_kwargs.get("reasoning_content"):
                                continue

                            # 白名单：只允许这些节点的消息流出给前端
                            ALLOWED_NODES = {
                                "respond_to_general_query",
                                "web_search_query",
                                "get_additional_info",
                                "generate_image_node",
                            }

                            if node_name not in ALLOWED_NODES:
                                if node_name not in ("", ):
                                    is_research_plan = True
                                continue

                            # generate_image_node：输出文字提示，图片通过 generated_image SSE 单独发送
                            if node_name == "generate_image_node":
                                content = c.content
                                async for chunk_data in stream_content_with_typing_effect(content, delay=0.01):
                                    yield chunk_data
                                full_response += content
                                continue
                            
                            # 白名单节点正常流式输出
                            content = c.content
                            async for chunk_data in stream_content_with_typing_effect(content, delay=0.01):
                                yield chunk_data
                            full_response += content
                            
                        elif c.additional_kwargs.get("tool_calls"):
                            pass
                    
                    # stream 结束后，如果是 research_plan 路径，从图状态取最终答案
                    if is_research_plan and not full_response:
                        try:
                            final_state = await graph.aget_state(thread_config)
                            if final_state and hasattr(final_state, 'values') and final_state.values:
                                msgs = final_state.values.get("messages", [])
                                for msg in reversed(msgs):
                                    if isinstance(msg, AIMessage) and msg.content and msg.content.strip():
                                        content = msg.content
                                        # 使用打字效果流式输出
                                        async for chunk_data in stream_content_with_typing_effect(content, delay=0.01):
                                            yield chunk_data
                                        full_response = content
                                        break
                        except Exception as state_err:
                            logger.error(f"Failed to get final state: {state_err}")
                            
                    try:
                        state = await graph.aget_state(thread_config)
                        if state and hasattr(state, 'tasks') and state.tasks:
                            for task in state.tasks:
                                if hasattr(task, 'interrupts') and task.interrupts:
                                    interrupt_json = json.dumps({"interruption": True, "conversation_id": thread_id})
                                    yield f"data: {interrupt_json}\n\n"
                                    break
                    except Exception as e:
                        logger.warning(f"Error checking interrupt state: {e}")

                    # 检查是否有生成的图片，发送给前端
                    try:
                        final_state = await graph.aget_state(thread_config)
                        if final_state and hasattr(final_state, 'values') and final_state.values:
                            generated_image = final_state.values.get("generated_image", "")
                            if generated_image:
                                logger.info("检测到生成图片（resume路径），发送给前端")
                                img_json = json.dumps({"generated_image": generated_image}, ensure_ascii=False)
                                yield f"data: {img_json}\n\n"
                    except Exception as img_err:
                        logger.warning(f"获取生成图片失败（resume路径）: {img_err}")
                            
                finally:
                    if full_response or True:  # 即使没有文字也要保存图片
                        try:
                            db_conv_id = None
                            try:
                                db_conv_id = int(str(thread_id))
                            except ValueError:
                                pass
                            
                            if db_conv_id:
                                # 获取生成的图片 URL
                                saved_image_url = None
                                try:
                                    final_state = await graph.aget_state(thread_config)
                                    if final_state and hasattr(final_state, 'values') and final_state.values:
                                        saved_image_url = final_state.values.get("generated_image", "") or None
                                except Exception:
                                    pass

                                if full_response or saved_image_url:
                                    async with AsyncSessionLocal() as session:
                                        assistant_message = Message(
                                            conversation_id=db_conv_id,
                                            sender="assistant",
                                            content=full_response or "",
                                            image_url=saved_image_url
                                        )
                                        session.add(assistant_message)
                                        await session.commit()
                                        logger.info(f"Saved assistant message for conversation {db_conv_id}, image_url={saved_image_url}")
                        except Exception as e:
                            logger.error(f"Failed to save assistant message: {e}", exc_info=True)

        else:
            # 新会话或找不到现有状态，创建新的输入状态
            logger.info("Creating new conversation state")
            # input_state = InputState(messages=query) # Fix: InputState object is not JSON serializable in checkpoint metadata
            input_state = {"messages": [{"role": "user", "content": query}]}
            
            # 流式处理查询
            async def process_stream():
                # ★ 先发送搜索结果（如果有）
                if search_results_for_sse:
                    sr_json = json.dumps({"search_results": search_results_for_sse}, ensure_ascii=False)
                    yield f"data: {sr_json}\n\n"

                full_response = ""
                # 对 create_research_plan 节点，跳过所有 stream 消息（子图内部会产生多个 AIMessage），
                # stream 结束后从图的最终状态取最后一条 AIMessage 作为答案
                is_research_plan = False
                try:
                    async for c, metadata in graph.astream(
                        input=input_state, 
                        stream_mode="messages", 
                        config=thread_config
                    ):
                        if c.content and not c.additional_kwargs.get("tool_calls"):
                            node_name = metadata.get("langgraph_node", "")
                            
                            # DeepSeek 思考模式：跳过 reasoning_content（思维链）
                            if c.additional_kwargs.get("reasoning_content"):
                                continue

                            # 白名单：只允许这些节点的消息流出给前端
                            # 子图路径（invoke_kg_subgraph）内部节点（planner/tool_selection/
                            # cypher_query/guardrails/summarize 等）全部被过滤，
                            # 最终答案通过 stream 结束后从图状态读取
                            ALLOWED_NODES = {
                                "respond_to_general_query",
                                "web_search_query",
                                "get_additional_info",
                                "generate_image_node",
                            }

                            if node_name not in ALLOWED_NODES:
                                # 标记：如果是子图路径，流结束后从状态取最终答案
                                if node_name not in ("", ):
                                    is_research_plan = True
                                continue

                            # generate_image_node：输出文字提示，图片通过 generated_image SSE 单独发送
                            if node_name == "generate_image_node":
                                content = c.content
                                async for chunk_data in stream_content_with_typing_effect(content, delay=0.01):
                                    yield chunk_data
                                full_response += content
                                continue
                            
                            # 白名单节点正常流式输出
                            content = c.content
                            async for chunk_data in stream_content_with_typing_effect(content, delay=0.01):
                                yield chunk_data
                            full_response += content
                            
                        elif c.additional_kwargs.get("tool_calls"):
                            pass
                    
                    # stream 结束后，如果是 research_plan 路径，从图状态取最终答案
                    if is_research_plan and not full_response:
                        try:
                            final_state = await graph.aget_state(thread_config)
                            if final_state and hasattr(final_state, 'values') and final_state.values:
                                msgs = final_state.values.get("messages", [])
                                # 取最后一条 AIMessage 作为答案
                                for msg in reversed(msgs):
                                    if isinstance(msg, AIMessage) and msg.content and msg.content.strip():
                                        content = msg.content
                                        # 使用打字效果流式输出
                                        async for chunk_data in stream_content_with_typing_effect(content, delay=0.01):
                                            yield chunk_data
                                        full_response = content
                                        logger.info(f"Research plan final answer from state: {content[:100]}")
                                        break
                        except Exception as state_err:
                            logger.error(f"Failed to get final state: {state_err}")

                    # 流结束后，检查是否有生成的图片，发送给前端
                    try:
                        final_state = await graph.aget_state(thread_config)
                        if final_state and hasattr(final_state, 'values') and final_state.values:
                            generated_image = final_state.values.get("generated_image", "")
                            if generated_image:
                                logger.info("检测到生成图片，发送给前端")
                                img_json = json.dumps({"generated_image": generated_image}, ensure_ascii=False)
                                yield f"data: {img_json}\n\n"
                    except Exception as img_err:
                        logger.warning(f"获取生成图片失败: {img_err}")
                
                except Exception as stream_err:
                    logger.error(f"Stream processing error: {stream_err}", exc_info=True)
                    if not full_response:
                        error_msg = "抱歉，服务暂时繁忙，请稍后重试"
                        error_json = json.dumps(error_msg, ensure_ascii=False)
                        yield f"data: {error_json}\n\n"
                        full_response = error_msg
                            
                    # 处理中断情况
                    try:
                        state = await graph.aget_state(thread_config)
                        if state and hasattr(state, 'values') and state.values:
                            tasks = state.tasks if hasattr(state, 'tasks') else ()
                            for task in tasks:
                                if hasattr(task, 'interrupts') and task.interrupts:
                                    interrupt_json = json.dumps({"interruption": True, "conversation_id": thread_id})
                                    yield f"data: {interrupt_json}\n\n"
                                    break
                    except Exception as e:
                        logger.warning(f"Error checking interrupt state: {e}")

                finally:
                    # 保存 AI 回复到数据库（用户消息已在流式响应开始前保存）
                    if full_response or True:  # 即使没有文字也要保存图片
                        try:
                            db_conv_id = None
                            try:
                                db_conv_id = int(thread_id)
                            except ValueError:
                                logger.warning(f"Thread ID {thread_id} is not an integer, skipping DB save.")
                            
                            if db_conv_id:
                                # 获取生成的图片 URL
                                saved_image_url = None
                                try:
                                    final_state = await graph.aget_state(thread_config)
                                    if final_state and hasattr(final_state, 'values') and final_state.values:
                                        saved_image_url = final_state.values.get("generated_image", "") or None
                                except Exception:
                                    pass

                                if full_response or saved_image_url:
                                    async with AsyncSessionLocal() as session:
                                        assistant_message = Message(
                                            conversation_id=db_conv_id,
                                            sender="assistant",
                                            content=full_response or "",
                                            image_url=saved_image_url
                                        )
                                        session.add(assistant_message)
                                        await session.commit()
                                        logger.info(f"Saved assistant message for conversation {db_conv_id}, image_url={saved_image_url}")
                        except Exception as e:
                            logger.error(f"Failed to save assistant message: {e}")

        response = StreamingResponse(
            process_stream(),
            media_type="text/event-stream"
        )
        
        # 添加会话ID到响应头，方便前端获取
        response.headers["X-Conversation-ID"] = thread_id
        
        return response
        
    except Exception as e:
        logger.error(f"LangGraph query error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/langgraph/resume", tags=["对话管理"], summary="恢复中断的对话", description="恢复被中断的 LangGraph 对话流程，继续执行未完成的任务")
async def langgraph_resume(request: LangGraphResumeRequest, current_user: User = Depends(get_current_user)):
    """继续执行LangGraph流程"""
    try:
        logger.info(f"Resuming LangGraph query for user {request.user_id} with conversation {request.conversation_id}")
        
        # 使用会话ID作为线程ID
        thread_config = {"configurable": {"thread_id": request.conversation_id}}
        
        # 流式处理恢复
        from app.lg_agent.lg_builder import graph
        async def process_resume():
            async for c, metadata in graph.astream(Command(resume=request.query), stream_mode="messages", config=thread_config):
                # 只处理最终展示给用户的内容
                if c.content and not c.additional_kwargs.get("tool_calls"):
                    # 同样使用json.dumps处理内容
                    content_json = json.dumps(c.content, ensure_ascii=False)
                    yield f"data: {content_json}\n\n"
                
                # 工具调用单独处理，不发送给前端
                elif c.additional_kwargs.get("tool_calls"):
                    tool_data = c.additional_kwargs.get("tool_calls")[0]["function"].get("arguments")
                    logger.debug(f"Tool call: {tool_data}")
        
        return StreamingResponse(
            process_resume(),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        logger.error(f"LangGraph resume error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/image", tags=["文件上传"], summary="上传图片", description="上传图片文件，返回图片存储路径，可用于后续对话中的图片分析或参考图生成")
async def upload_image(
    image: UploadFile = File(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user)
):
    """上传图片并返回图片存储路径"""
    try:
        # 创建图片存储目录
        image_dir = Path("uploads/images")
        if conversation_id:
            image_dir = image_dir / conversation_id
        image_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_name, ext = os.path.splitext(image.filename)
        new_filename = f"{original_name}_{timestamp}{ext}"
        image_path = image_dir / new_filename
        
        # 保存图片 (异步写入)
        content = await image.read()
        await asyncio.to_thread(_sync_write_file, str(image_path), content)
        
        # 获取图片信息
        image_info = {
            "filename": new_filename,
            "original_name": image.filename,
            "size": len(content),
            "type": image.content_type,
            "path": str(image_path).replace('\\', '/'),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "upload_time": timestamp
        }
        
        logger.info(f"Image uploaded: {image_info}")
        
        return image_info
        
    except Exception as e:
        logger.error(f"Image upload failed for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# 最后挂载静态文件，并确保使用绝对路径
# 最后挂载静态文件，并确保使用绝对路径
STATIC_DIR = Path(__file__).parent / "static" / "dist"

# Mount assets specifically (if frontend uses /assets)
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

# 挂载生成图片目录（AI 生成的图片）
GENERATED_IMAGES_DIR = Path(__file__).parent / "static" / "generated_images"
GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/generated_images", StaticFiles(directory=str(GENERATED_IMAGES_DIR)), name="generated_images")

# 挂载用户上传图片目录（用于历史消息持久显示）
UPLOADS_IMAGES_DIR = Path(__file__).parent / "uploads" / "images"
UPLOADS_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/images", StaticFiles(directory=str(UPLOADS_IMAGES_DIR)), name="uploads_images")

# 挂载完整 uploads 目录（供 MinerU 等外部服务通过公网 URL 访问文件）
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

from fastapi.responses import FileResponse

# ==================== 用户管理 API（仅管理员）====================

@app.get("/api/admin/users", tags=["用户管理"], summary="获取所有用户列表")
async def admin_list_users(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权限")
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).order_by(User.id))
            users = result.scalars().all()
            return [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "role": u.role,
                    "status": u.status,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "last_login": u.last_login.isoformat() if u.last_login else None,
                }
                for u in users
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/users/{user_id}", tags=["用户管理"], summary="删除用户及其所有数据")
async def admin_delete_user(user_id: int, current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权限")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")
            from app.models.knowledge_base import KnowledgeBase
            import os
            kb_result = await session.execute(
                select(KnowledgeBase).where(KnowledgeBase.user_id == user_id)
            )
            kb_items = kb_result.scalars().all()
            for item in kb_items:
                if item.file_path and os.path.exists(item.file_path):
                    try:
                        os.remove(item.file_path)
                    except Exception:
                        pass
            await session.delete(user)
            await session.commit()
        return {"message": f"用户 {user_id} 及其所有数据已删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ResetPasswordRequest(BaseModel):
    new_password: str


@app.put("/api/admin/users/{user_id}/password", tags=["用户管理"], summary="重置用户密码")
async def admin_reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权限")
    try:
        from app.core.hashing import get_password_hash
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")
            user.password_hash = get_password_hash(body.new_password)
            await session.commit()
        return {"message": "密码已重置"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Catch-all route for SPA
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # If file exists in static/dist, serve it (optional, if not covered by mount)
    file_path = STATIC_DIR / full_path
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    
    # Otherwise serve index.html
    return FileResponse(STATIC_DIR / "index.html")


# ==================== 管理 API ====================

@app.post("/api/admin/cleanup-checkpoints")
async def cleanup_checkpoints(user_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    """清理 checkpoint 缓存（管理员功能）"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权限")
    try:
        from app.core.checkpointer import CheckpointModel, CheckpointWriteModel
        from app.models import Conversation
        
        async with AsyncSessionLocal() as session:
            if user_id:
                # 清理指定用户的 checkpoint
                conv_stmt = select(Conversation.id).where(Conversation.user_id == user_id)
                conv_result = await session.execute(conv_stmt)
                conversation_ids = [str(row[0]) for row in conv_result.fetchall()]
                
                if not conversation_ids:
                    return {
                        "message": f"用户 {user_id} 没有对话记录",
                        "cleaned_checkpoints": 0,
                        "cleaned_checkpoint_writes": 0
                    }
                
                # 删除 checkpoints
                checkpoint_delete_stmt = delete(CheckpointModel).where(
                    CheckpointModel.thread_id.in_(conversation_ids)
                )
                checkpoint_result = await session.execute(checkpoint_delete_stmt)
                
                # 删除 checkpoint_writes
                checkpoint_writes_delete_stmt = delete(CheckpointWriteModel).where(
                    CheckpointWriteModel.thread_id.in_(conversation_ids)
                )
                checkpoint_writes_result = await session.execute(checkpoint_writes_delete_stmt)
                
                await session.commit()
                
                logger.info(f"Admin cleanup: user {user_id}, "
                           f"{checkpoint_result.rowcount} checkpoints, "
                           f"{checkpoint_writes_result.rowcount} checkpoint_writes deleted")
                
                return {
                    "message": f"已清理用户 {user_id} 的 checkpoint 缓存",
                    "cleaned_checkpoints": checkpoint_result.rowcount,
                    "cleaned_checkpoint_writes": checkpoint_writes_result.rowcount
                }
            else:
                # 清理所有 checkpoint（慎用）
                checkpoint_delete_stmt = delete(CheckpointModel)
                checkpoint_result = await session.execute(checkpoint_delete_stmt)
                
                checkpoint_writes_delete_stmt = delete(CheckpointWriteModel)
                checkpoint_writes_result = await session.execute(checkpoint_writes_delete_stmt)
                
                await session.commit()
                
                logger.warning(f"Admin cleanup: ALL checkpoints cleared! "
                              f"{checkpoint_result.rowcount} checkpoints, "
                              f"{checkpoint_writes_result.rowcount} checkpoint_writes deleted")
                
                return {
                    "message": "已清理所有用户的 checkpoint 缓存",
                    "cleaned_checkpoints": checkpoint_result.rowcount,
                    "cleaned_checkpoint_writes": checkpoint_writes_result.rowcount,
                    "warning": "所有对话状态已重置"
                }
    except Exception as e:
        logger.error(f"Error cleaning up checkpoints: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/checkpoint-stats")
async def get_checkpoint_stats(current_user: User = Depends(get_current_user)):
    """获取 checkpoint 统计信息（管理员功能）"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权限")
    try:
        from app.core.checkpointer import CheckpointModel, CheckpointWriteModel
        from sqlalchemy import func
        
        async with AsyncSessionLocal() as session:
            # 统计 checkpoints 表
            checkpoint_count_stmt = select(func.count(CheckpointModel.thread_id))
            checkpoint_count = await session.execute(checkpoint_count_stmt)
            total_checkpoints = checkpoint_count.scalar()
            
            # 统计 checkpoint_writes 表
            checkpoint_writes_count_stmt = select(func.count(CheckpointWriteModel.thread_id))
            checkpoint_writes_count = await session.execute(checkpoint_writes_count_stmt)
            total_checkpoint_writes = checkpoint_writes_count.scalar()
            
            # 统计不同 thread_id 数量
            unique_threads_stmt = select(func.count(func.distinct(CheckpointModel.thread_id)))
            unique_threads = await session.execute(unique_threads_stmt)
            total_threads = unique_threads.scalar()
            
            return {
                "total_checkpoints": total_checkpoints,
                "total_checkpoint_writes": total_checkpoint_writes,
                "total_threads": total_threads,
                "note": "checkpoint 是 LangGraph 对话状态缓存，可以安全清理"
            }
    except Exception as e:
        logger.error(f"Error getting checkpoint stats: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
