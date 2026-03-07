# 实施计划：智能客服 Agent 系统补全修复

## 概述

按照设计文档，将 8 处缺失逻辑逐一补全。每个任务聚焦单一修复点，确保每步改动可独立验证，最终通过子图接入将所有组件串联为完整系统。

## 任务列表

- [x] 1. 补全双 Neo4j 实例架构与 Schema 缓存
  - [x] 1.1 在 `config.py` 的 `Settings` 类中新增第二个 Neo4j 实例的 4 个配置字段（`NEO4J_UNSTRUCTURED_URL`、`NEO4J_UNSTRUCTURED_USERNAME`、`NEO4J_UNSTRUCTURED_PASSWORD`、`NEO4J_UNSTRUCTURED_DATABASE`），默认值均为空字符串或 "neo4j"
    - 同时在 `SETTINGS_META` 列表中追加对应的 4 条 UI 管理条目，`group` 设为 `"neo4j"`
    - _需求：7.1、7.6_
  - [x] 1.2 在 `kg_neo4j_conn.py` 中新增 `get_neo4j_unstructured_graph()` 函数，当 `NEO4J_UNSTRUCTURED_URL` 为空时记录 warning 并返回 `None`，不抛出异常
    - 同时新增 `get_neo4j_schema_cached(graph_key: str)` 函数，使用字典 + 时间戳实现 60 秒 TTL 缓存（不使用 `functools.lru_cache`，因为需要 TTL 控制）
    - _需求：7.2、7.3、7.4、7.5_
  - [x]* 1.3 为 Schema 缓存编写属性测试
    - **属性 6：Schema 缓存幂等性与 TTL 刷新**
    - **验证：需求 7.3、7.4**
    - 测试：60 秒内连续调用返回相同值；mock 时间戳超过 TTL 后调用触发刷新
    - _需求：7.3、7.4_
  - [x]* 1.4 为第二 Neo4j 实例编写单元测试
    - 测试：`NEO4J_UNSTRUCTURED_URL` 为空时 `get_neo4j_unstructured_graph()` 返回 `None` 且不抛异常
    - 测试：`Settings` 类包含 4 个新配置字段
    - 测试：`SETTINGS_META` 包含 4 条新条目
    - _需求：7.1、7.2、7.5、7.6_

- [x] 2. 补全 Text2Cypher 危险操作权限控制
  - [x] 2.1 在 `cypher_tools/node.py` 的 `cypher_query` 函数中，在 Cypher 生成（`cypher_generation`）之后、验证（`validate_cypher`）之前，调用已有的 `validate_no_writes_in_cypher_query` 函数
    - 若检测到危险操作，立即返回包含错误信息的 `CypherQueryOutputState`，`records` 字段设为 `{"result": "该操作涉及数据库写入，已被系统拦截，仅支持查询操作。"}`
    - 导入路径：`from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.cypher_tools.utils import validate_no_writes_in_cypher_query`
    - _需求：4.1、4.2、4.3_
  - [x]* 2.2 为 Cypher 权限控制编写属性测试
    - **属性 3：Text2Cypher 危险操作拦截完整性**
    - **验证：需求 4.1、4.2、4.3**
    - 使用 `hypothesis` 库，对危险关键词的所有大小写变体（DELETE/delete/Delete 等）验证均被拦截
    - 对纯读操作（MATCH/RETURN/WITH/WHERE）验证返回空错误列表
    - _需求：4.1、4.2、4.3、4.4_
  - [x]* 2.3 为边界情况编写单元测试
    - 测试：空字符串输入返回错误
    - 测试：`None` 输入不抛异常
    - _需求：4.5_

- [x] 3. 优化 Router 节点 Few-shot 示例与 Logprobs 置信度
  - [x] 3.1 在 `lg_prompts.py` 的 `ROUTER_SYSTEM_PROMPT` 中补充 few-shot 示例，覆盖 `general`、`additional`、`graphrag` 三类，每类至少 2 个示例
    - 示例格式：`用户输入 → 分类：xxx，原因：xxx`
    - _需求：1.1_
  - [x] 3.2 在 `lg_builder.py` 的 `analyze_and_route_query` 函数中，在调用 `model.with_structured_output(Router).ainvoke(messages)` 时尝试获取 logprobs
    - 从响应的 `response_metadata` 中提取第一个 token 的 `logprob` 值
    - 使用 `math.exp` 计算 sigmoid 归一化：`confidence = 1 / (1 + math.exp(-logprob))`
    - 当 `confidence < 0.6` 时，将 `response.type` 强制改为 `"graphrag"`，并在 `logic` 字段追加置信度信息
    - 用 `try/except` 包裹整个 logprobs 提取逻辑，失败时记录 warning 并使用原始结果
    - _需求：1.2、1.3、1.4_
  - [x]* 3.3 为 logprobs 置信度计算编写属性测试
    - **属性 1：Logprobs 置信度计算与降级逻辑**
    - **验证：需求 1.2、1.3**
    - 使用 `hypothesis` 库，对 [-20.0, 0.0] 范围内的任意 logprob 值验证：sigmoid 结果在 [0,1] 内；< 0.6 时路由降级为 graphrag
    - _需求：1.2、1.3_
  - [x]* 3.4 为边界情况编写单元测试
    - 测试：结构化输出返回 `None` 时默认路由到 `graphrag`（已有兜底逻辑，验证其存在）
    - 测试：`ROUTER_SYSTEM_PROMPT` 字符串包含 "general"、"additional"、"graphrag" 三个关键词
    - _需求：1.1、1.5_

- [x] 4. 实现 GraphRAG 四种检索路径动态选择
  - [x] 4.1 在 `customer_tools/node.py` 的 `GraphRAGAPI` 类中新增 `_select_query_type(self, query: str, chat_history: str = "") -> str` 方法
    - 优先级（从高到低）：drift（含指代词且历史非空）> global（含归纳关键词）> basic（长度 < 10 且无疑问词）> local（默认）
    - 指代词列表：`["它", "这个", "那个", "上面", "刚才", "之前", "该", "此"]`
    - 归纳关键词列表：`["都有什么", "有哪些", "总结", "概述", "列举", "所有", "全部", "介绍一下"]`
    - 在方法末尾记录 `logger.info(f"GraphRAG 检索模式选择: {mode}")`
    - _需求：6.1、6.2、6.3、6.4、6.5_
  - [x] 4.2 修改 `GraphRAGAPI.query_graphrag` 方法，接受可选的 `chat_history: str = ""` 参数，在调用底层 API 之前调用 `self._select_query_type(query, chat_history)` 并将结果赋值给 `self.query_type`
    - _需求：6.1、6.2、6.3、6.4_
  - [x]* 4.3 为 GraphRAG 检索模式选择编写属性测试
    - **属性 5：GraphRAG 检索模式选择正确性**
    - **验证：需求 6.1、6.2、6.3、6.4**
    - 使用 `hypothesis` 库，对任意查询字符串和对话历史组合，验证返回值在 `["basic", "local", "global", "drift"]` 内，且优先级规则一致应用
    - _需求：6.1、6.2、6.3、6.4_

- [x] 5. 实现幻觉检测四种方式并接入主图
  - [x] 5.1 在 `lg_states.py` 的 `AgentState` 中新增两个字段：`documents: str = field(default_factory=str)` 和 `hallucination_retry: int = field(default=0)`
    - _需求：5.1_
  - [x] 5.2 重写 `lg_builder.py` 中的 `check_hallucinations` 函数，实现四种检测方式
    - **方式 1（知识溯源）**：使用 `difflib.SequenceMatcher(None, answer, context).ratio()` 计算相似度，相似度 < 0.1 且答案长度 > 50 时标记为可疑
    - **方式 2（数值一致性）**：用 `re.findall(r'\d+\.?\d*', text)` 提取数值集合，答案含数值但上下文完全不含时标记为可疑
    - **方式 3（实体存在性）**：用 `re.findall(r'[\u4e00-\u9fa5]{2,8}', answer)` 提取中文实体，超过 50% 的实体不在上下文中时标记为可疑
    - **方式 4（LLM 辅助）**：使用 `deepseek-reasoner` + 现有 `CHECK_HALLUCINATIONS` prompt + `GradeHallucinations` 结构化输出
    - 任一方式标记为可疑时，若 `state.hallucination_retry < 1`，将 `hallucination_retry + 1` 并返回触发重试的信号；否则直接返回当前答案
    - _需求：5.2、5.3、5.4、5.5、5.6、5.7、5.8_
  - [x] 5.3 在 `lg_builder.py` 的 `StateGraph` 中注册 `check_hallucinations` 节点，并在 `invoke_kg_subgraph`（下一步创建）完成后连接到该节点
    - 添加条件边：`hallucination_retry < 1` 且检测失败 → 重新调用 `invoke_kg_subgraph`；否则 → `END`
    - _需求：5.1、5.6、5.7_
  - [x]* 5.4 为幻觉检测重试逻辑编写属性测试
    - **属性 4：幻觉检测重试上限保证**
    - **验证：需求 5.6、5.7、5.8**
    - 测试：`hallucination_retry >= 1` 时，检测函数不触发重试，直接返回答案
    - 测试：`hallucination_retry = 0` 时，检测失败后 `hallucination_retry` 变为 1
    - _需求：5.6、5.7、5.8_
  - [x]* 5.5 为各检测方式编写单元测试
    - 测试 difflib 相似度：相同字符串返回 1.0，完全不同返回接近 0
    - 测试数值提取：`"价格是 99.9 元"` 提取出 `{"99.9"}`
    - 测试实体匹配：答案中的实体在上下文中存在时不标记为可疑
    - _需求：5.2、5.3、5.4_

- [x] 6. 将 Planner + 多工具子图接入主图（核心串联）
  - [x] 6.1 在 `lg_builder.py` 中，在 `StateGraph` 构建代码之前，创建子图实例
    - 调用 `create_multi_tool_workflow`，传入 `llm`（deepseek-chat）、`graph`（`get_neo4j_graph()`，失败时为 `None`）、`tool_schemas=[]`、`predefined_cypher_dict={}`、`cypher_example_retriever=NorthwindCypherRetriever()`、`scope_description="智能客服业务范围"`
    - 用 `try/except` 包裹，失败时记录 error 日志，`_kg_subgraph` 设为 `None`
    - _需求：3.1、3.5_
  - [x] 6.2 在 `lg_builder.py` 中新增 `invoke_kg_subgraph` 异步函数，替代原来的 `create_research_plan` 节点
    - 从 `state.messages[-1].content` 提取 `question`
    - 调用 `_format_chat_history(state.messages[:-1])` 格式化历史（复用现有的 `_get_recent_messages` 逻辑）
    - 构建 `subgraph_input = {"question": question, "chat_history": chat_history, "data": [], "history": []}`
    - 调用 `await _kg_subgraph.ainvoke(subgraph_input, config=config)`，提取 `result.get("answer", "")`
    - 将答案写入 `state.documents`（供幻觉检测使用）并返回 `{"messages": [AIMessage(content=answer)], "documents": answer}`
    - 若 `_kg_subgraph` 为 `None`，降级调用原有的 GraphRAG 直查逻辑
    - _需求：3.2、3.3、3.4_
  - [x] 6.3 在 `StateGraph` 中将原来的 `"create_research_plan"` 节点替换为 `"invoke_kg_subgraph"` 节点
    - 更新所有引用 `"create_research_plan"` 的边定义，改为 `"invoke_kg_subgraph"`
    - 确保 `route_query` 函数中的 `"create_research_plan"` 返回值也改为 `"invoke_kg_subgraph"`
    - _需求：3.1_
  - [x]* 6.4 为状态映射编写单元测试
    - 测试：`invoke_kg_subgraph` 正确从 `AgentState.messages` 提取 `question` 和 `chat_history`
    - 测试：子图输出的 `answer` 字段被正确写入 `AgentState.messages` 和 `AgentState.documents`
    - _需求：3.3、3.4_

- [x] 7. 检查点 — 确保所有测试通过
  - 确保所有测试通过，如有问题请向用户说明。
  - 验证主图可以正常编译（`builder.compile()` 不报错）
  - 验证子图可以正常编译（`create_multi_tool_workflow` 不报错）
  - 验证 `AgentState` 新字段不破坏现有序列化

- [x] 8. 护栏覆盖 GraphRAG 路径的验证与收尾
  - [x] 8.1 验证 `create_multi_tool_workflow` 中的 `create_guardrails_node` 调用已传入 `graph` 参数（动态注入 Neo4j Schema）
    - 若 `graph` 为 `None`（Neo4j 连接失败），确认护栏仍可正常运行（`create_guardrails_prompt_template` 对 `graph=None` 的处理已存在）
    - _需求：2.1、2.4、2.5_
  - [x] 8.2 在 `invoke_kg_subgraph` 的降级路径中，确保 Neo4j 连接失败时护栏允许通过，记录 warning 日志
    - _需求：2.5_
  - [x]* 8.3 为护栏决策一致性编写属性测试
    - **属性 2：护栏决策与路由行为一致性**
    - **验证：需求 2.2、2.3**
    - mock `guardrails_chain.ainvoke` 返回 `GuardrailsOutput(decision="end", response="...")` 和 `GuardrailsOutput(decision="planner")`，验证 `guardrails_conditional_edge` 的路由结果与决策一致
    - _需求：2.2、2.3_
  - [x]* 8.4 为护栏 Schema 注入编写单元测试
    - 测试：`create_guardrails_prompt_template(graph=mock_graph)` 生成的提示词包含 Schema 内容
    - 测试：`create_guardrails_prompt_template(graph=None)` 不抛异常
    - _需求：2.4、2.5_

- [x] 9. 最终检查点 — 端到端验证
  - 确保所有测试通过，如有问题请向用户说明。
  - 验证完整的 graphrag 路径：Router → invoke_kg_subgraph → check_hallucinations → END
  - 验证 `route_query` 函数的所有分支返回值与 `StateGraph` 中注册的节点名称一致
  - 验证 `AgentState` 中所有新增字段有正确的默认值，不影响现有功能

## 备注

- 标有 `*` 的子任务为可选测试任务，可跳过以加快 MVP 进度
- 每个任务均引用了具体的需求条目，便于追溯
- 任务 6（子图接入）是核心串联步骤，依赖任务 1-5 的所有修复已完成
- 属性测试使用 `hypothesis` 库，需确保已安装：`pip install hypothesis`
