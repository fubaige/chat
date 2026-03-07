# 需求文档

## 简介

本文档描述智能客服 Agent 系统的补全与修复需求。当前系统基于 LangGraph 构建多 Agent 智能客服框架，已有基础骨架但存在 8 处核心逻辑缺失，导致系统无法按设计意图完整运行。本次修复目标是在保持现有代码结构的前提下，最小化改动范围，补全所有缺失逻辑，使系统达到生产可用状态。

技术栈：Python、LangGraph、FastAPI、DeepSeek（deepseek-chat / deepseek-reasoner）、Neo4j、GraphRAG。

---

## 词汇表

- **Router（路由器）**：`lg_builder.py` 中的 `analyze_and_route_query` 节点，负责将用户问题分类为 general / additional / graphrag 等类型
- **Guardrails（安全护栏）**：判断用户问题是否在业务范围内的过滤节点，拒绝范围外问题
- **Planner（规划器）**：将复杂问题分解为多个子任务的节点，位于 `kg_sub_graph/planner/planner_node.py`
- **Multi_Tool_Workflow（多工具子图）**：由 `create_multi_tool_workflow` 创建的子图，包含 Guardrails → Planner → 工具选择 → 执行 → 汇总的完整流程
- **Text2Cypher（文本转 Cypher）**：将自然语言转换为 Neo4j Cypher 查询语句的组件，位于 `cypher_tools/node.py`
- **GraphRAG（图谱增强检索）**：基于知识图谱的检索增强生成，支持 basic / local / global / drift 四种检索模式
- **Hallucination_Checker（幻觉检测器）**：检测 LLM 生成内容是否与知识库事实一致的组件
- **Neo4j_Structured（结构化 Neo4j）**：存储结构化业务数据（产品、订单等）的 Neo4j 实例
- **Neo4j_Unstructured（非结构化 Neo4j）**：存储非结构化文档知识图谱的第二个 Neo4j 实例
- **Schema_Cache（Schema 缓存）**：使用 `functools.lru_cache` 缓存 Neo4j Schema，避免每次实时获取
- **Logprobs（对数概率）**：LLM 输出 token 的对数概率，用于计算路由置信度
- **Few-shot（少样本示例）**：在提示词中提供的示例，帮助 LLM 理解分类规则

---

## 需求

### 需求 1：Router 节点 Few-shot 示例与置信度优化

**用户故事：** 作为系统管理员，我希望路由器能够准确分类用户问题并具备置信度评估能力，以便在分类不确定时自动降级到更安全的检索路径。

#### 验收标准

1. THE Router SHALL include few-shot examples covering all three query types (general, additional, graphrag) in the `ROUTER_SYSTEM_PROMPT`
2. WHEN the Router classifies a query, THE Router SHALL compute a confidence score using sigmoid normalization of logprobs
3. WHEN the confidence score is below 0.6, THE Router SHALL downgrade the routing decision to `graphrag` type
4. WHEN logprobs are unavailable or the API does not support them, THE Router SHALL fall back to the structured output result without error
5. IF the structured output from the Router returns None, THEN THE Router SHALL default to `graphrag` type with a fallback logic message

---

### 需求 2：GraphRAG 路径安全护栏覆盖

**用户故事：** 作为系统管理员，我希望所有进入 GraphRAG 查询路径的问题都经过安全护栏过滤，以便拒绝超出业务范围的问题并保护系统安全。

#### 验收标准

1. WHEN a query is routed to the `graphrag` path, THE Guardrails SHALL evaluate the query before it reaches the Planner
2. WHEN the Guardrails node determines a query is out of scope, THE Guardrails SHALL return a polite rejection response and terminate the workflow
3. WHEN the Guardrails node determines a query is in scope, THE Guardrails SHALL pass the query to the Planner node
4. THE Guardrails SHALL dynamically inject the Neo4j Schema into the evaluation prompt to determine business relevance
5. IF the Neo4j connection fails during Guardrails evaluation, THEN THE Guardrails SHALL allow the query to pass through with a warning log

---

### 需求 3：Planner 与多工具子图接入主图

**用户故事：** 作为系统架构师，我希望 Planner 和多工具并行工作流被正确注册到主图中，以便 graphrag 路径能够执行完整的任务分解和并行工具调用流程。

#### 验收标准

1. THE Main_Graph SHALL replace the current `create_research_plan` node with a call to the sub-graph created by `create_multi_tool_workflow`
2. THE Sub_Graph SHALL execute the following sequential flow: Guardrails → Planner → Map-Reduce tool selection → [Text2Cypher OR GraphRAG] → Summarize → Final Answer
3. WHEN the sub-graph is invoked, THE Main_Graph SHALL pass the user question and chat history from `AgentState` to the sub-graph's `InputState`
4. WHEN the sub-graph completes, THE Main_Graph SHALL extract the final answer from the sub-graph output and store it in `AgentState.messages`
5. THE Sub_Graph SHALL be compiled once at application startup and reused across requests

---

### 需求 4：Text2Cypher 危险操作权限控制

**用户故事：** 作为数据库管理员，我希望 Text2Cypher 组件在执行 Cypher 语句前拦截危险操作，以便防止意外的数据删除或结构变更。

#### 验收标准

1. WHEN a generated Cypher statement contains any of the keywords DELETE, DROP, MERGE, REMOVE, SET, CREATE (write operations), THE Cypher_Validator SHALL intercept the statement before execution
2. WHEN a dangerous Cypher statement is intercepted, THE Cypher_Validator SHALL return an error message indicating the operation is not permitted
3. WHEN a Cypher statement contains only read operations (MATCH, RETURN, WITH, WHERE, ORDER BY, LIMIT), THE Cypher_Validator SHALL allow execution to proceed
4. THE Cypher_Validator SHALL perform keyword detection in a case-insensitive manner
5. IF the Cypher statement is empty or None, THEN THE Cypher_Validator SHALL return an appropriate error without attempting execution

---

### 需求 5：幻觉检测节点接入主图与四种检测方式实现

**用户故事：** 作为产品负责人，我希望系统在生成最终答案后自动检测幻觉内容，以便提高回答的准确性和可信度。

#### 验收标准

1. THE Main_Graph SHALL register the `check_hallucinations` node and connect it after the final answer generation in the `graphrag` path
2. THE Hallucination_Checker SHALL implement knowledge source verification using `difflib.SequenceMatcher` or simple string matching to compute similarity between the answer and retrieved context
3. THE Hallucination_Checker SHALL implement numerical consistency checking using regular expressions to extract and compare numerical values between the answer and source documents
4. THE Hallucination_Checker SHALL implement entity existence checking using rule-based keyword matching (without external NER models) to verify that mentioned entities exist in the source context
5. THE Hallucination_Checker SHALL implement LLM-assisted verification using `deepseek-reasoner` to perform a final binary grading of the answer
6. WHEN any of the four detection methods flags the answer as a hallucination, THE Hallucination_Checker SHALL trigger a self-correction cycle by re-querying the knowledge base and regenerating the answer
7. THE Hallucination_Checker SHALL limit self-correction retries to a maximum of 1 retry to prevent infinite loops
8. WHEN the maximum retry count is reached, THE Hallucination_Checker SHALL return the best available answer with a confidence indicator

---

### 需求 6：GraphRAG 四种检索路径动态选择

**用户故事：** 作为系统架构师，我希望 GraphRAG 能够根据问题特征自动选择最合适的检索模式，以便提高检索质量和回答准确性。

#### 验收标准

1. WHEN a query consists of short phrases or keyword-style input (fewer than 10 characters or no verb), THE GraphRAG_API SHALL use `basic` search mode
2. WHEN a query references specific entities, products, or named items, THE GraphRAG_API SHALL use `local` search mode as the default
3. WHEN a query requests summarization, enumeration, or overview (contains keywords such as "都有什么", "有哪些", "总结", "概述"), THE GraphRAG_API SHALL use `global` search mode
4. WHEN a query contains anaphoric references (pronouns such as "它", "这个", "那个", "上面说的") AND the chat history is non-empty, THE GraphRAG_API SHALL use `drift` search mode
5. THE GraphRAG_API SHALL determine the search mode before calling the underlying search API and log the selected mode

---

### 需求 7：双 Neo4j 实例架构

**用户故事：** 作为系统架构师，我希望系统支持两个独立的 Neo4j 实例，以便将结构化业务数据与非结构化文档知识图谱分离管理。

#### 验收标准

1. THE Config SHALL define a second Neo4j instance with configuration keys `NEO4J_UNSTRUCTURED_URL`, `NEO4J_UNSTRUCTURED_USERNAME`, `NEO4J_UNSTRUCTURED_PASSWORD`, and `NEO4J_UNSTRUCTURED_DATABASE`
2. THE Neo4j_Connector SHALL provide a `get_neo4j_unstructured_graph()` function that returns a `Neo4jGraph` instance connected to the second Neo4j instance
3. THE Schema_Cache SHALL use `functools.lru_cache` to cache the Neo4j Schema with a TTL of 60 seconds to avoid repeated real-time fetches
4. WHEN the TTL expires, THE Schema_Cache SHALL automatically refresh the cached Schema on the next access
5. IF the second Neo4j instance is not configured (empty URL), THEN THE Neo4j_Connector SHALL log a warning and return None without raising an exception
6. THE Config SHALL include the second Neo4j instance configuration in the `SETTINGS_META` list for UI management
