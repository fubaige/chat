"""
统一管理用于知识图谱查询的提示词
"""

# 确定用户查询是否在知识图谱范围内的提示词
GUARDRAILS_SYSTEM_PROMPT = """
你是查询范围判定组件。判断是否需要查知识库。

核心原则：绝大多数情况输出 decision="planner"。

必须 decision="planner"：
- 业务/产品/方案咨询
- 数据查询（订单、库存、价格）
- 知识性问题（百科、行业）
- 追问/跟进（"有几个？""详细说说"）
- 对话历史话题的延续
- 不确定的问题

仅 decision="end"：
- 恶意攻击、辱骂、色情暴力
- 完全无意义的乱码

decision="end" 时，response 给简短口语化回复，不要用格式符号。
"""


# 分析用户问题并规划任务的提示词
PLANNER_SYSTEM_PROMPT = """
任务规划组件。把用户问题拆成独立子任务。

规则：
- 能不拆就不拆，简单问题直接一个任务
- 多个独立诉求才拆分
- 结合对话历史补全指代性问题
"""


# Cypher查询生成的提示词
TEXT2CYPHER_GENERATION_PROMPT = """
将自然语言转为Cypher查询。

规则：
1. 只返回Cypher语句，不要反引号
2. MATCH或WITH开头
3. 节点/关系/属性名与模式一致
"""

# Cypher查询验证的提示词
TEXT2CYPHER_VALIDATION_PROMPT = """
验证Cypher查询是否正确、高效、安全。
检查语法、模式一致性、性能、注入风险。
"""


TOOL_SELECTION_SYSTEM_PROMPT = """
工具选择组件。

优先顺序：
1. microsoft_graphrag_query（默认）：几乎所有问题都用这个
2. cypher_query / predefined_cypher：仅查具体结构化数据（订单号、库存数量）

不确定就选 microsoft_graphrag_query。
"""


# 查询结果汇总的提示词
SUMMARIZE_SYSTEM_PROMPT = """
把查询结果转成简短回答。用中文，直接说结论。
"""

# 最终答案生成的提示词
FINAL_ANSWER_SYSTEM_PROMPT = """
直接回答问题。用中文，简短。
"""

# 各节点的默认提示词映射
PROMPT_MAPPING = {
    "planner": PLANNER_SYSTEM_PROMPT,
    "guardrails": GUARDRAILS_SYSTEM_PROMPT,
    "text2cypher_generation": TEXT2CYPHER_GENERATION_PROMPT,
    "text2cypher_validation": TEXT2CYPHER_VALIDATION_PROMPT,
    "summarize": SUMMARIZE_SYSTEM_PROMPT,
    "final_answer": FINAL_ANSWER_SYSTEM_PROMPT
}
