from typing import Any, Callable, Coroutine, Dict, List
import asyncio
import os
from pathlib import Path
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logger import get_logger
from langchain_core.runnables import RunnableConfig
import uuid

logger = get_logger(service="customer_tools_node")


class GraphRAGQueryInputState(BaseModel):
    task: str
    query: str
    steps: List[str]


class GraphRAGQueryOutputState(BaseModel):
    task: str
    query: str
    statement: str = ""
    parameters: str = ""
    errors: List[str]
    records: Dict[str, Any]
    steps: List[str]


class GraphRAGAPI:
    """GraphRAG API 包装器。每个用户独立知识库，lancedb 和 parquet 必须在同一个用户目录下。"""

    def __init__(self, storage_dir: str, embedding_type: str = None):
        """
        Args:
            storage_dir: 用户的 GraphRAG 输出目录，如 output/{user_uuid}/{record_id}
            embedding_type: 该目录索引时使用的 embedding 类型（dashscope / sentence_transformer）
                            为 None 时自动从当前全局配置读取
        """
        self.project_dir = settings.GRAPHRAG_PROJECT_DIR
        self.data_dir_name = settings.GRAPHRAG_DATA_DIR
        self.storage_dir = storage_dir
        self.embedding_type = embedding_type  # 记录该文档的 embedding 类型
        self.query_type = "local"
        self.response_type = settings.GRAPHRAG_RESPONSE_TYPE
        self.community_level = settings.GRAPHRAG_COMMUNITY_LEVEL
        self.dynamic_community_selection = settings.GRAPHRAG_DYNAMIC_COMMUNITY
        self.config = None
        self.storage = None
        self.initialized = False
        self.entities = None
        self.text_units = None
        self.communities = None
        self.community_reports = None
        self.relationships = None
        self.covariates = None

    async def initialize(self):
        """初始化 GraphRAG API，加载用户目录下的数据和向量库"""
        if self.initialized:
            return

        import app.graphrag.graphrag.api as api_module
        from app.graphrag.graphrag.config.load_config import load_config
        from app.graphrag.graphrag.utils.storage import load_table_from_storage
        from app.graphrag.graphrag.storage.file_pipeline_storage import FilePipelineStorage

        self.api = api_module
        self.load_table_from_storage = load_table_from_storage

        # 从全局 settings.yaml 加载基础配置（LLM、embedding 等）
        project_directory = os.path.join(self.project_dir, self.data_dir_name)
        self.config = load_config(Path(project_directory), None, None)
        
        # ★ 根据文档索引时使用的 embedding 类型，动态覆盖 embedding 模型配置
        # 确保查询时用的 embedding 和索引时一致，否则向量维度/空间不匹配导致检索失败
        effective_embedding_type = self.embedding_type or settings.EMBEDDING_TYPE
        if 'default_embedding_model' in self.config.models:
            emb_config = self.config.models['default_embedding_model']

            if effective_embedding_type == "dashscope":
                # 百炼 text-embedding-v4，1024 维
                dashscope_key = settings.DASHSCOPE_API_KEY
                dashscope_model = settings.EMBEDDING_MODEL if settings.EMBEDDING_MODEL else "text-embedding-v4"
                emb_config.__dict__['api_key'] = dashscope_key
                emb_config.__dict__['api_base'] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
                emb_config.__dict__['model'] = dashscope_model
                emb_config.__dict__['dimensions'] = 1024
                logger.info(f"使用百炼 embedding：model={dashscope_model}, dimensions=1024")
            else:
                # 本地 sentence_transformer，强制 1024 维（与索引时一致）
                current_dims = getattr(emb_config, 'dimensions', None)
                if current_dims != 1024:
                    emb_config.__dict__['dimensions'] = 1024
                logger.info(f"使用本地 embedding：model={getattr(emb_config, 'model', 'unknown')}, dimensions=1024")

        output_dir = Path(self.storage_dir)

        # ★ 关键：覆盖 vector_store 的 db_uri 指向用户目录下的 lancedb
        # 每个用户的 lancedb 和 parquet 必须在同一个目录下，保证向量和数据匹配
        user_lancedb = output_dir / "lancedb"
        if not user_lancedb.exists():
            # 兼容旧索引：lancedb 在全局 output/lancedb，自动迁移到用户目录
            global_lancedb = Path(project_directory) / "output" / "lancedb"
            if global_lancedb.exists():
                import shutil
                logger.info(f"旧索引迁移：复制全局 lancedb 到用户目录: {global_lancedb} -> {user_lancedb}")
                try:
                    shutil.copytree(str(global_lancedb), str(user_lancedb))
                    logger.info(f"lancedb 迁移成功: {user_lancedb}")
                except Exception as copy_err:
                    logger.error(f"lancedb 迁移失败: {copy_err}")
            else:
                logger.warning(f"No lancedb found anywhere, vector search will fail")
        
        resolved_lancedb = str(user_lancedb.resolve())
        logger.info(f"Using user lancedb: {resolved_lancedb}")

        # 必须用绝对路径覆盖，否则 GraphRAG 内部会相对于 project_dir 解析
        for store_key, store_config in self.config.vector_store.items():
            if store_config.type == "lancedb":
                old_uri = store_config.db_uri
                store_config.db_uri = resolved_lancedb
                logger.info(f"Override vector_store[{store_key}].db_uri: {old_uri} -> {resolved_lancedb}")
                # 验证覆盖是否生效（Pydantic v2 可能阻止直接赋值）
                if store_config.db_uri != resolved_lancedb:
                    logger.error(f"db_uri override FAILED! Pydantic may be blocking mutation. Trying __dict__ approach.")
                    store_config.__dict__["db_uri"] = resolved_lancedb
                    logger.info(f"After __dict__ override: db_uri = {store_config.db_uri}")
                # 验证 model_dump() 也包含正确的 db_uri（get_embedding_store 会用 model_dump()）
                dumped = store_config.model_dump()
                if dumped.get("db_uri") != resolved_lancedb:
                    logger.error(f"model_dump() db_uri mismatch! dumped={dumped.get('db_uri')}, expected={resolved_lancedb}. Forcing via model_fields_set.")
                    # Pydantic v2: 用 model_copy 替换
                    new_config = store_config.model_copy(update={"db_uri": resolved_lancedb})
                    self.config.vector_store[store_key] = new_config
                    logger.info(f"Replaced store_config via model_copy, new db_uri={self.config.vector_store[store_key].db_uri}")
                else:
                    logger.info(f"model_dump() db_uri verified: {dumped.get('db_uri')}")

        # 确定 parquet 存储目录
        if (output_dir / "artifacts").exists():
            storage_root = str(output_dir / "artifacts")
        else:
            storage_root = str(output_dir)

        self.storage = FilePipelineStorage(root_dir=storage_root)
        self._storage_root = storage_root

        # 加载 parquet 数据
        try:
            if os.path.exists(storage_root):
                self.entities = await self.load_table_from_storage("entities", self.storage)
                self.text_units = await self.load_table_from_storage("text_units", self.storage)
                self.communities = await self.load_table_from_storage("communities", self.storage)
                self.community_reports = await self.load_table_from_storage("community_reports", self.storage)
                self.relationships = await self.load_table_from_storage("relationships", self.storage)
                try:
                    self.covariates = await self.load_table_from_storage("covariates", self.storage)
                except Exception:
                    self.covariates = None
                logger.info(f"Loaded GraphRAG data from {storage_root}: entities={len(self.entities) if self.entities is not None else 0}")
            self.initialized = True
        except Exception as e:
            logger.warning(f"Failed to load GraphRAG tables from {storage_root}: {e}")
            self.initialized = True

    def _select_query_type(self, query: str, chat_history: str = "") -> str:
        """根据问题特征和对话历史动态选择 GraphRAG 检索模式。
        
        优先级（从高到低）：
        1. drift  — 含指代词且对话历史非空（多轮追问场景）
        2. global — 含归纳总结类关键词（全局概览场景）
        3. basic  — 短句且无疑问词（关键词直查场景）
        4. local  — 默认（实体相关的精确查询）
        
        Args:
            query: 用户查询文本
            chat_history: 格式化后的对话历史字符串
        
        Returns:
            str: 检索模式，取值为 "drift" / "global" / "basic" / "local"
        """
        # 指代词列表：出现时说明用户在追问上文提到的内容，适合 drift 模式
        anaphora = ["它", "这个", "那个", "上面", "刚才", "之前", "该", "此"]
        # 疑问词：有疑问词说明是完整问句，不适合 basic 模式
        question_words = ["吗", "呢", "？", "?", "怎么", "为什么", "如何", "什么", "哪"]

        # 优先级1：含指代词且有对话历史 → drift（多轮对话追问）
        if chat_history and any(w in query for w in anaphora):
            mode = "drift"
            logger.info(f"GraphRAG 检索模式选择: {mode}（含指代词且有历史）")
            return mode

        # 优先级2：短句且无疑问词 → basic（关键词直查）
        if len(query.strip()) < 10 and not any(w in query for w in question_words):
            mode = "basic"
            logger.info(f"GraphRAG 检索模式选择: {mode}（短句无疑问词）")
            return mode

        # 默认：local（速度快，适合绝大多数问答场景）
        # 注意：global 模式需要对全量 community reports 做 Map-Reduce，耗时 30-60s，已移除
        mode = "local"
        logger.info(f"GraphRAG 检索模式选择: {mode}（默认）")
        return mode

    async def query_graphrag(self, query: str, chat_history: str = "") -> Dict[str, Any]:
        """执行 GraphRAG 查询，根据问题特征动态选择检索模式。
        
        Args:
            query: 用户查询文本
            chat_history: 对话历史（用于 drift 模式判断）
        """
        await self.initialize()

        if self.entities is None:
            return {"response": "", "context": {}}

        # ★ 动态选择检索模式：根据问题特征和对话历史自动决定
        self.query_type = self._select_query_type(query, chat_history)

        callbacks = []
        context_data = {}

        def on_context(context):
            nonlocal context_data
            context_data = context

        from app.graphrag.graphrag.callbacks.noop_query_callbacks import NoopQueryCallbacks
        local_callbacks = NoopQueryCallbacks()
        local_callbacks.on_context = on_context
        callbacks.append(local_callbacks)

        try:
            if self.query_type.lower() == "local":
                response, context = await self.api.local_search(
                    config=self.config,
                    entities=self.entities,
                    communities=self.communities,
                    community_reports=self.community_reports,
                    text_units=self.text_units,
                    relationships=self.relationships,
                    covariates=self.covariates,
                    community_level=self.community_level,
                    response_type=self.response_type,
                    query=query,
                    callbacks=callbacks,
                )
            elif self.query_type.lower() == "global":
                # global 模式已禁用：需要对全量 community reports 做 Map-Reduce，耗时 30-60s
                # 降级为 local 模式
                logger.warning("global 模式已禁用，自动降级为 local 模式")
                response, context = await self.api.local_search(
                    config=self.config,
                    entities=self.entities,
                    communities=self.communities,
                    community_reports=self.community_reports,
                    text_units=self.text_units,
                    relationships=self.relationships,
                    covariates=self.covariates,
                    community_level=self.community_level,
                    response_type=self.response_type,
                    query=query,
                    callbacks=callbacks,
                )
            elif self.query_type.lower() == "drift":
                response, context = await self.api.drift_search(
                    config=self.config,
                    entities=self.entities,
                    communities=self.communities,
                    community_reports=self.community_reports,
                    text_units=self.text_units,
                    relationships=self.relationships,
                    community_level=self.community_level,
                    response_type=self.response_type,
                    query=query,
                    callbacks=callbacks,
                )
            elif self.query_type.lower() == "basic":
                response, context = await self.api.basic_search(
                    config=self.config,
                    text_units=self.text_units,
                    query=query,
                    callbacks=callbacks,
                )
            else:
                raise ValueError(f"不支持的查询类型: {self.query_type}")

            return {"response": response, "context": context_data}

        except Exception as e:
            logger.error(f"GraphRAG query error: {e}", exc_info=True)
            raise


def _get_user_storage_dir(user_id: int) -> str:
    """根据 user_id 计算用户的 GraphRAG 输出根目录（兼容旧结构）。"""
    user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{user_id}"))
    project_dir = settings.GRAPHRAG_PROJECT_DIR
    data_dir = settings.GRAPHRAG_DATA_DIR
    return os.path.join(project_dir, data_dir, "output", user_uuid)


def _get_all_user_storage_dirs(user_id: int) -> list:
    """返回该用户所有文档的独立输出目录列表。
    
    新结构：output/{user_uuid}/{record_id}/
    旧结构（兼容）：output/{user_uuid}/  ← 直接包含 parquet 文件
    """
    base_dir = _get_user_storage_dir(user_id)
    if not os.path.exists(base_dir):
        return []

    dirs = []
    # 扫描子目录，数字命名的是 record_id 独立目录
    for entry in os.scandir(base_dir):
        if entry.is_dir() and entry.name.isdigit():
            # 确认目录内有索引数据
            artifacts = os.path.join(entry.path, "artifacts")
            has_data = os.path.exists(os.path.join(artifacts, "entities.parquet")) or \
                       os.path.exists(os.path.join(entry.path, "entities.parquet"))
            if has_data:
                dirs.append(entry.path)

    # 兼容旧结构：base_dir 下直接有 parquet 文件
    if not dirs:
        artifacts = os.path.join(base_dir, "artifacts")
        has_data = os.path.exists(os.path.join(artifacts, "entities.parquet")) or \
                   os.path.exists(os.path.join(base_dir, "entities.parquet"))
        if has_data:
            dirs.append(base_dir)

    return dirs


async def _try_graphrag_query(query: str, storage_dir: str) -> str:
    """尝试在指定目录执行 GraphRAG 查询。
    
    Returns:
        查询结果文本，失败返回空字符串
    """
    logger.info(f"Attempting GraphRAG query in: {storage_dir}")
    
    if not os.path.exists(storage_dir):
        logger.warning(f"Storage dir does not exist: {storage_dir}")
        return ""
    
    try:
        api = GraphRAGAPI(storage_dir)
        result = await api.query_graphrag(query)
        response = result.get("response", "")
        logger.info(f"GraphRAG query succeeded from: {storage_dir}, response length: {len(response)}")
        return response
    except Exception as e:
        logger.error(f"GraphRAG query failed in {storage_dir}: {e}", exc_info=True)
        return ""


# admin 用户 ID，其知识库作为所有用户的公共知识库
ADMIN_USER_ID = 1



def create_graphrag_query_node():
    """创建 GraphRAG 查询节点的工厂函数。

    查询流程（每个用户独立知识库）：
    1. 如果智能体绑定了 knowledgeBaseIds，优先查询绑定的知识库目录
    2. 否则查询当前用户自己的所有知识库
    3. 如果用户不是 admin 且用户知识库无结果，查询 admin 公共知识库作为兜底
    """

    def _filter_storage_dirs_by_kb_ids(all_dirs: list, kb_ids: list) -> list:
        """根据智能体绑定的 knowledgeBaseIds 过滤知识库目录。

        knowledgeBaseIds 存的是知识库文档的 record_id（数据库 ID），
        目录结构为 output/{user_uuid}/{record_id}/，
        所以目录名（basename）就是 record_id。
        """
        if not kb_ids:
            return all_dirs

        kb_id_set = set(str(kid) for kid in kb_ids)
        filtered = [d for d in all_dirs if os.path.basename(d) in kb_id_set]

        if filtered:
            logger.info(f"按 knowledgeBaseIds 过滤：{len(all_dirs)} → {len(filtered)} 个目录，绑定ID={kb_ids}")
        else:
            # 过滤后为空，可能是旧结构目录，回退到全部
            logger.warning(f"按 knowledgeBaseIds 过滤后为空（绑定ID={kb_ids}），回退到全部 {len(all_dirs)} 个目录")
            return all_dirs

        return filtered

    async def graphrag_query(state, config: RunnableConfig = None):
        """GraphRAG 查询节点 — LangGraph node function。

        从 config["configurable"] 获取用户ID和智能体扩展配置，
        按 knowledgeBaseIds 过滤后并发查询用户独立的知识库索引。

        返回格式必须包含 cyphers 键，与 cypher_query/predefined_cypher 节点一致，
        这样 summarize 节点才能从 state["cyphers"] 中读取结果。
        """
        # 获取查询任务
        task = state.get("task", "") or state.get("question", "")
        logger.info(f"GraphRAG query node received task: {task}")

        # 从 config 获取 user_id 和扩展配置
        user_id = None
        kb_ids = []
        if config:
            configurable = config.get("configurable", {})
            user_id = configurable.get("user_id")
            # 从 agent_config_extended 中读取 knowledgeBaseIds
            ext_config = configurable.get("agent_config_extended", {}) or {}
            kb_ids = ext_config.get("knowledgeBaseIds") or []

        if user_id is None:
            logger.warning("No user_id in config, cannot query user knowledge base")
            return {
                "cyphers": [{
                    "task": task,
                    "statement": "",
                    "parameters": None,
                    "errors": ["no user_id provided"],
                    "records": {"result": ""},
                    "steps": ["customer_tools"],
                }],
                "steps": ["customer_tools"],
            }

        logger.info(f"GraphRAG query for user_id: {user_id}, knowledgeBaseIds: {kb_ids}")

        final_response = ""

        # Step 1: 获取用户所有知识库目录，按 knowledgeBaseIds 过滤
        all_dirs = _get_all_user_storage_dirs(user_id)
        storage_dirs = _filter_storage_dirs_by_kb_ids(all_dirs, kb_ids)
        logger.info(f"Step 1: User storage dirs (after filter): {len(storage_dirs)} dirs, exists: {[os.path.exists(d) for d in storage_dirs]}")

        if storage_dirs:
            # 并发查询所有过滤后的目录
            responses = await asyncio.gather(*[_try_graphrag_query(task, d) for d in storage_dirs])
            # 取第一个有实质内容的回答
            for resp in responses:
                if resp and resp.strip():
                    final_response = resp
                    break

        if final_response and final_response.strip():
            logger.info(f"Step 1: User knowledge base query succeeded")
        else:
            logger.info(f"Step 1: User knowledge base returned empty")

            # Step 2: 非 admin 用户且没有绑定特定知识库时，尝试 admin 公共知识库
            if user_id != ADMIN_USER_ID and not kb_ids:
                admin_storage_dir = _get_user_storage_dir(ADMIN_USER_ID)
                logger.info(f"Step 2: Trying admin public KB: {admin_storage_dir}, exists: {os.path.exists(admin_storage_dir)}")

                final_response = await _try_graphrag_query(task, admin_storage_dir)

                if final_response and final_response.strip():
                    logger.info(f"Step 2: Admin public KB query succeeded")
                else:
                    logger.info(f"Step 2: Admin public KB also returned empty")

        # 记录最终结果
        logger.info(f"GraphRAG final response to pass to summarize: {final_response[:200] if final_response else '(empty)'}")

        return {
            "cyphers": [{
                "task": task,
                "statement": "",
                "parameters": None,
                "errors": [],
                "records": {"result": final_response},
                "steps": ["customer_tools"],
            }],
            "steps": ["customer_tools"],
        }

    return graphrag_query


