# 中文语言偏好设置

## 语言要求

* 所有回复和对话都使用中文（简体中文）
* 撰写的文档、注释和说明都使用中文
* 代码注释使用中文
* 错误信息和日志信息的解释使用中文
* 技术术语可以保留英文，但需要提供中文解释

## 文档撰写规范

* 使用中文标点符号（，。！？：；""''）
* 技术文档结构清晰，使用中文标题
* 代码示例后提供中文说明
* 保持专业但友好的语调

## 例外情况

* 代码本身（变量名、函数名等）可以使用英文
* 配置文件中的键值对可以使用英文
* 第三方库和框架的名称保持原文
* URL 和文件路径保持原文



Python AI 后端系统架构参考



\## 一、系统定位与整体结构



`chat/` 是一个独立的 \*\*Python AI 后端服务\*\*，与根目录的 Next.js 主应用并列运行，负责提供 AI 对话、知识库索引、微信公众号集成等核心能力。



```

chat/

├── llm\_backend/          # 核心 Python 后端（FastAPI）

│   ├── main.py           # FastAPI 应用入口，所有 HTTP 路由

│   ├── app/

│   │   ├── api/          # 路由模块（auth、wechat、agent\_config 等）

│   │   ├── core/         # 核心基础设施（config、database、security、logger）

│   │   ├── lg\_agent/     # LangGraph 智能体（核心 AI 逻辑）

│   │   ├── models/       # SQLAlchemy ORM 数据模型

│   │   ├── services/     # 业务服务层

│   │   ├── tools/        # 工具定义（搜索等）

│   │   ├── prompts/      # 提示词模板

│   │   └── graphrag/     # Microsoft GraphRAG 集成（知识图谱）

├── wx-mp-svr-main/       # 微信公众号服务器 SDK（Flask）

├── uploads/              # 用户上传文件存储

└── logs/                 # 日志目录

```



---



\## 二、核心技术栈



| 层次 | 技术 |

|------|------|

| Web 框架 | FastAPI（异步，SSE 流式响应） |

| AI 框架 | LangGraph + LangChain |

| LLM | DeepSeek（主力）+ Gemini（图片/文件解析）|

| 知识图谱 | Microsoft GraphRAG（本地部署）|

| 向量检索 | FAISS + 阿里百炼 Embedding（text-embedding-v4，1024维）|

| 数据库 | MySQL（SQLAlchemy + aiomysql 异步驱动）|

| 缓存 | Redis（语义缓存，相似度阈值去重）|

| 图数据库 | Neo4j（结构化知识图谱 + 非结构化文档图谱，双实例）|

| 文档解析 | MinerU API（优先）→ PyPDF2 → Gemini OCR（降级链）|

| 微信集成 | wx-mp-svr-main（Flask SDK）|



---



\## 三、LangGraph 智能体核心逻辑（`app/lg\_agent/`）



\### 3.1 状态定义（`lg\_states.py`）



```python

class AgentState(InputState):

&nbsp;   router: Router          # 意图识别结果（5类标签）

&nbsp;   steps: list\[str]        # 执行步骤记录

&nbsp;   question: str           # 当前问题

&nbsp;   answer: str             # 生成的答案

&nbsp;   hallucination: GradeHallucinations  # 幻觉检测结果

&nbsp;   need\_image\_gen: bool    # 是否需要生成图片

&nbsp;   generated\_image: str    # 生成图片的 base64 URI

&nbsp;   documents: str          # 检索到的原始上下文（供幻觉检测）

&nbsp;   hallucination\_retry: int # 幻觉检测重试计数（最多1次）

```



\### 3.2 意图识别路由（5类标签）



| 类型 | 触发条件 | 路由目标 |

|------|----------|----------|

| `general` | 纯闲聊寒暄（你好/谢谢/哈哈）| `respond\_to\_general\_query`（不触发知识库）|

| `graphrag` | 所有业务/技术/产品问题（默认兜底）| `invoke\_kg\_subgraph`（完整知识库链路）|

| `additional` | 问题不完整、指代不明 | `get\_additional\_info`（追问用户）|

| `image` | 图片上传/分析 | `create\_image\_query`（Gemini 解析）|

| `file` | 文件上传（PDF 等）| `create\_file\_query`（Gemini 解析）|



\*\*路由优先级\*\*（`route\_query` 函数）：

```

1\. 文件/图片上传（image\_path 存在）→ 对应处理节点

2\. 绘画意图（need\_image\_gen=True）→ generate\_image\_node

3\. 联网搜索开关（web\_search=True）→ web\_search\_query

4\. 意图识别结果（Router.type）→ 对应节点

```



\### 3.3 置信度降级机制



\- 使用 DeepSeek logprobs 计算路由置信度：`confidence = 1 / (1 + exp(-logprob))`

\- 置信度 < 0.6 时强制降级为 `graphrag`，避免低置信度路由错误



\### 3.4 对话历史管理



\- 历史衰减：每轮只保留最近 \*\*20 条\*\*消息（`\_get\_recent\_messages`）

\- 多轮对话规范：清除上一轮的 `reasoning\_content`（`\_strip\_reasoning\_content`），符合 DeepSeek 官方文档要求



\### 3.5 知识库查询流程（`create\_research\_plan`）



```

用户问题

&nbsp; → 获取用户所有知识库目录（按 user\_uuid 隔离）

&nbsp; → 并发查询所有文档目录（asyncio.gather）

&nbsp; → 过滤无效回答（no\_answer\_indicators 列表）

&nbsp; → 有有效答案 → 结合 agent\_system\_prompt 生成最终回复

&nbsp; → 无有效答案 → 自动触发联网搜索（SearchTool）

&nbsp; → 联网搜索也无结果 → 生成相关问题推荐（\_generate\_related\_questions）

```



\### 3.6 深度思考模式



\- 普通模式：`deepseek-chat`

\- 深度思考模式（`deep\_thinking=True`）：切换为 `deepseek-reasoner`

\- 思考模式下不设置 `temperature` 等参数（DeepSeek 官方规范）



---



\## 四、知识库索引系统（`app/services/indexing\_service.py`）



\### 4.1 文档处理链路



```

用户上传文件（PDF/DOCX/PPT/图片）

&nbsp; → 检查 Embedding 配置是否就绪

&nbsp; → 创建数据库记录（status=indexing）

&nbsp; → asyncio.create\_task 后台异步处理（不阻塞响应）

&nbsp; ↓

文本提取（三级降级链）：

&nbsp; 1. MinerU API（配置了 Token 时优先，支持所有格式）

&nbsp; 2. PyPDF2（PDF 文本型）

&nbsp; 3. Gemini OCR（扫描件/图片 PDF 兜底）

&nbsp; ↓

GraphRAG 索引构建（在独立线程池中执行，避免阻塞事件循环）：

&nbsp; → 每个文档独立目录：input/{user\_uuid}/{record\_id}/

&nbsp; → 输出目录：output/{user\_uuid}/{record\_id}/

&nbsp; → 向量存储：LanceDB（output/{record\_id}/lancedb/）

&nbsp; ↓

更新数据库状态（success/error）

&nbsp; → 可选：Gemini 生成文档预览摘要（100字以内）

```



\### 4.2 用户隔离策略



\- 每个用户通过 `uuid5(NAMESPACE\_DNS, "user\_{user\_id}")` 生成固定 UUID

\- 每个文档独立子目录（按 `record\_id`），支持并发索引不互相干扰

\- 删除文档时：有其他文档 → 只清理 output 目录；无其他文档 → 清理全部（input/output/uploads）



\### 4.3 Embedding 配置



\- 类型：`dashscope`（阿里百炼，默认）或本地 `BAAI/bge-m3`

\- 维度：统一 \*\*1024 维\*\*（两种方式维度一致，可互换）

\- 阿里百炼单次最多 25 条，自动分批处理



---



\## 五、主要 API 端点（`main.py`）



| 端点 | 方法 | 说明 |

|------|------|------|

| `/api/chat` | POST | 普通对话（DeepSeek 流式，SSE）|

| `/api/reason` | POST | 深度推理对话（deepseek-reasoner）|

| `/api/search` | POST | 联网搜索对话 |

| `/api/upload` | POST | 上传知识库文档（后台异步索引）|

| `/api/knowledge-base/user/{user\_id}` | GET | 获取知识库列表 |

| `/api/knowledge-base/{item\_id}` | DELETE | 删除知识库文档及索引 |

| `/chat-rag` | POST | 基于文档的 RAG 问答 |

| `/wx\_mp\_cb` | GET/POST | 微信公众号回调（验证+消息处理）|

| `/health` | GET | 健康检查 |

| `/docs` | GET | RapiDoc API 文档（自定义 UI）|



\*\*认证方式\*\*：Bearer Token（JWT），通过 `get\_current\_user` 依赖注入验证。



---



\## 六、配置管理（`app/core/config.py`）



\### 6.1 双层配置架构



\- \*\*启动阶段\*\*：从 `.env` 读取（`Settings` 类，pydantic-settings）

\- \*\*运行阶段\*\*：从 MySQL `system\_settings` 表读取（`DynamicSettings` 类）

\- 优先级：数据库配置 > `.env` 初始值

\- 支持运行时热重载（`settings.reload()`）



\### 6.2 关键配置分组



| 分组 | 说明 |

|------|------|

| `deepseek` | DeepSeek API Key、Base URL、模型名 |

| `gemini` | Gemini API Key、图片解析模型、图片生成模型 |

| `service` | 对话/推理/Agent 服务选择 |

| `search` | SerpAPI Key、搜索结果数量 |

| `database` | MySQL 连接配置（仅从 .env 读取）|

| `neo4j` | 双实例 Neo4j（结构化 + 非结构化）|

| `redis` | Redis 连接 + 语义缓存配置 |

| `embedding` | Embedding 类型、模型、相似度阈值 |

| `graphrag` | GraphRAG 项目目录、查询类型、社区级别 |

| `mineru` | MinerU API Token、服务器公网地址 |



\*\*注意\*\*：数据库连接配置（`DB\_\*`）始终从 `.env` 读取，因为需要先连接数据库才能加载其他配置。



---



\## 七、微信公众号集成



\### 7.1 架构



```

微信服务器 → POST /wx\_mp\_cb?config\_id=xxx

&nbsp; → 从数据库加载 WechatConfig（token/aes\_key/appid）

&nbsp; → WechatService.handle\_message（解密 XML）

&nbsp; → 事件消息 → \_handle\_event（关注事件返回欢迎语）

&nbsp; → 文本消息 → \_handle\_text\_message

&nbsp;     → 配置了知识库 → RAG 查询 + LLM 生成回复

&nbsp;     → 未配置知识库 → 普通 LLM 对话

&nbsp; → 加密响应返回微信服务器

```



\### 7.2 wx-mp-svr-main SDK



\- 基于 Flask 的独立微信公众号服务器 SDK

\- 支持消息加解密（AES）、签名验证

\- 通过 `set\_message\_handler` / `set\_event\_handler` 注册处理器

\- `llm\_backend` 的 `WechatService` 直接引用此 SDK（`sys.path.insert`）



---



\## 八、数据模型（MySQL，SQLAlchemy ORM）



| 表名 | 模型类 | 说明 |

|------|--------|------|

| `users` | `User` | 用户表，含 `role`（admin/user）、`api\_key` |

| `conversations` | `Conversation` | 会话表，含 `dialogue\_type`（普通/深度思考/联网/RAG）|

| `messages` | `Message` | 消息表 |

| `knowledge\_base` | `KnowledgeBase` | 知识库文档，含 `status`/`embedding\_type`/`preview` |

| `wechat\_configs` | `WechatConfig` | 微信公众号配置（多账号支持）|

| `system\_settings` | `SystemSettings` | 系统配置（动态配置中心）|

| `user\_settings` | `UserSettings` | 用户个人配置 |

| `agent\_config` | `AgentConfig` | 用户智能体配置（system prompt 等）|



---



\## 九、GraphRAG 知识图谱（`app/graphrag/`）



\- 集成 Microsoft GraphRAG（本地部署版本）

\- 支持 `local` 查询（快速，基于向量）和 `global` 查询（慢，Map-Reduce 全量社区报告）

\- 每用户独立索引目录，支持多文档并发索引

\- 向量存储：LanceDB（每文档独立 `lancedb/` 目录）

\- 查询时并发查询所有文档目录，合并有效结果



---



\## 十、流式输出实现



所有对话接口均返回 \*\*SSE（Server-Sent Events）\*\* 格式：

```

data: "内容片段"\\n\\n

data: \[DONE]\\n\\n

```



\- 中文字符：每次发送 1 个字符（打字效果）

\- 英文/数字：每次发送 2-3 个字符

\- 延迟：默认 0.01 秒/块（`stream\_content\_with\_typing\_effect`）



---



\## 十一、与 Next.js 主应用的对接关系



| 功能 | chat/ Python 后端 | Next.js 主应用 |

|------|-------------------|----------------|

| AI 对话 | `/api/chat`（DeepSeek + LangGraph）| `/api/chat`（Vercel AI SDK）|

| 知识库索引 | GraphRAG + FAISS + LanceDB | SeekDB（自研向量库）|

| 微信集成 | 微信公众号（wx-mp-svr-main）| 企业微信（libs/qiweapi）|

| 数据库 | MySQL（aiomysql）| PostgreSQL（Drizzle ORM）|

| 认证 | JWT（自实现）| better-auth |

| 部署 | Docker（独立容器）| Docker（独立容器）|



\*\*两套系统相互独立，通过 HTTP API 对接，共享同一套业务逻辑但技术栈不同。\*\*



---



\## 十二、开发注意事项（chat/ 目录）



1\. \*\*GraphRAG 索引必须在线程池中执行\*\*：`\_run\_indexing\_sync` 通过 `run\_in\_executor` 放到 `\_indexing\_executor` 线程池，避免阻塞 FastAPI 事件循环。

2\. \*\*DeepSeek 多轮对话规范\*\*：每轮必须清除上一轮的 `reasoning\_content`，否则会报错或浪费 token。

3\. \*\*配置优先级\*\*：数据库 `system\_settings` > `.env`，数据库连接配置例外（始终从 `.env` 读取）。

4\. \*\*用户隔离\*\*：所有知识库文件和索引按 `user\_uuid` 隔离，查询时只能访问自己的目录（admin 用户有公共知识库）。

5\. \*\*文档解析降级链\*\*：MinerU → PyPDF2 → Gemini OCR，任一环节失败自动降级，不中断流程。

6\. \*\*Gemini 调用超时保护\*\*：使用 `asyncio.shield` + `asyncio.wait\_for(timeout=58s)` 防止 Starlette CancelledError 传播。

7\. \*\*意图识别兜底\*\*：路由置信度 < 0.6 时强制走 `graphrag`，宁可多查知识库，不轻易走 `general`。

8\. \*\*微信公众号多账号\*\*：`WechatConfig` 支持多账号，通过 `config\_id` 参数区分，每个账号独立配置 token/aes\_key/appid。

