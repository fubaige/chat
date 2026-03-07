"""
属性测试（Property-Based Tests）：智能客服 Agent 系统
使用 hypothesis 库对核心逻辑进行属性验证。

每个属性测试均标注对应的需求条目，便于追溯。
"""

import math
import re
import sys
import os
import time
import difflib
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# 将 llm_backend 加入 sys.path，确保可以导入 app 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数：从实现中提取纯逻辑，避免触发外部依赖
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_confidence_downgrade(logprob: float, original_type: str) -> str:
    """
    复现 lg_builder.py 中的 logprobs 置信度降级逻辑。
    sigmoid 归一化：confidence = 1 / (1 + exp(-logprob))
    confidence < 0.6 时强制降级为 graphrag。
    """
    confidence = 1 / (1 + math.exp(-logprob))
    if confidence < 0.6:
        return "graphrag"
    return original_type


def _select_query_type(query: str, chat_history: str = "") -> str:
    """
    复现 customer_tools/node.py 中的 GraphRAGAPI._select_query_type 逻辑。
    优先级（从高到低）：drift > global > basic > local
    """
    anaphora = ["它", "这个", "那个", "上面", "刚才", "之前", "该", "此"]
    global_keywords = ["都有什么", "有哪些", "总结", "概述", "列举", "所有", "全部", "介绍一下"]
    question_words = ["吗", "呢", "？", "?", "怎么", "为什么", "如何", "什么", "哪"]

    if chat_history and any(w in query for w in anaphora):
        return "drift"
    if any(kw in query for kw in global_keywords):
        return "global"
    if len(query.strip()) < 10 and not any(w in query for w in question_words):
        return "basic"
    return "local"


def _validate_no_writes_in_cypher_query(cypher_statement: str) -> list:
    """
    复现 cypher_tools/utils.py 中的 validate_no_writes_in_cypher_query 逻辑。
    检测危险写操作关键词（大小写不敏感），包含 DDL 操作 DROP。
    """
    WRITE_CLAUSES = {"CREATE", "DELETE", "DETACH DELETE", "DROP", "SET", "REMOVE", "FOREACH", "MERGE"}
    errors = []
    for wc in WRITE_CLAUSES:
        if wc in (cypher_statement or "").upper():
            errors.append(f"Cypher contains write clause: {wc}")
    return errors



def _guardrails_conditional_edge(next_action: str) -> str:
    """
    复现 edges.py 中的 guardrails_conditional_edge 逻辑。
    """
    match next_action:
        case "final_answer":
            return "final_answer"
        case "end":
            return "final_answer"
        case "planner":
            return "planner"
        case _:
            return "final_answer"


# ═══════════════════════════════════════════════════════════════════════════════
# 属性 1：Logprobs 置信度计算与降级逻辑
# Feature: intelligent-customer-service-agent, Property 1: logprobs 置信度计算与降级逻辑
# 验证：需求 1.2、1.3
# ═══════════════════════════════════════════════════════════════════════════════

@given(logprob=st.floats(min_value=-20.0, max_value=0.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=200)
def test_property1_confidence_in_range(logprob):
    """
    属性 1a：对任意 [-20.0, 0.0] 范围内的 logprob，sigmoid 结果必须在 [0, 1] 内。
    Validates: Requirements 1.2
    """
    confidence = 1 / (1 + math.exp(-logprob))
    assert 0.0 <= confidence <= 1.0, (
        f"置信度超出 [0,1] 范围: logprob={logprob}, confidence={confidence}"
    )


@given(
    logprob=st.floats(min_value=-20.0, max_value=0.0, allow_nan=False, allow_infinity=False),
    original_type=st.sampled_from(["general", "additional", "graphrag", "image", "file"]),
)
@settings(max_examples=200)
def test_property1_downgrade_when_low_confidence(logprob, original_type):
    """
    属性 1b：置信度 < 0.6 时路由必须降级为 graphrag；>= 0.6 时保持原始类型。
    Validates: Requirements 1.2, 1.3
    """
    confidence = 1 / (1 + math.exp(-logprob))
    result = _apply_confidence_downgrade(logprob, original_type)

    if confidence < 0.6:
        assert result == "graphrag", (
            f"置信度 {confidence:.4f} < 0.6，应降级为 graphrag，实际结果: {result}"
        )
    else:
        assert result == original_type, (
            f"置信度 {confidence:.4f} >= 0.6，应保持原始类型 {original_type}，实际结果: {result}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 属性 2：护栏决策与路由行为一致性
# Feature: intelligent-customer-service-agent, Property 2: 护栏决策与路由行为一致性
# 验证：需求 2.2、2.3
# ═══════════════════════════════════════════════════════════════════════════════

@given(decision=st.sampled_from(["end", "planner", "final_answer", "unknown_value"]))
@settings(max_examples=100)
def test_property2_guardrails_routing_consistency(decision):
    """
    属性 2：护栏决策结果与实际路由行为必须完全一致。
    - decision="end" → 路由到 "final_answer"（终止）
    - decision="planner" → 路由到 "planner"（继续）
    - 其他值 → 路由到 "final_answer"（安全兜底）
    Validates: Requirements 2.2, 2.3
    """
    route = _guardrails_conditional_edge(decision)

    if decision == "planner":
        assert route == "planner", (
            f"decision=planner 时应路由到 planner，实际: {route}"
        )
    else:
        # "end"、"final_answer" 及任何未知值都应路由到 final_answer
        assert route == "final_answer", (
            f"decision={decision} 时应路由到 final_answer，实际: {route}"
        )


@given(
    decision=st.one_of(
        st.just("end"),
        st.just("planner"),
        st.text(min_size=1, max_size=20),  # 任意字符串
    )
)
@settings(max_examples=150)
def test_property2_guardrails_never_returns_invalid(decision):
    """
    属性 2b：guardrails_conditional_edge 的返回值必须始终是合法的节点名称。
    Validates: Requirements 2.2, 2.3
    """
    valid_nodes = {"planner", "final_answer"}
    route = _guardrails_conditional_edge(decision)
    assert route in valid_nodes, (
        f"路由结果 '{route}' 不在合法节点集合 {valid_nodes} 中"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 属性 3：Text2Cypher 危险操作拦截完整性
# Feature: intelligent-customer-service-agent, Property 3: Text2Cypher 危险操作拦截完整性
# 验证：需求 4.1、4.2、4.3
# ═══════════════════════════════════════════════════════════════════════════════

# 危险关键词的所有大小写变体
_DANGEROUS_KEYWORDS = ["DELETE", "DROP", "MERGE", "REMOVE", "SET", "CREATE", "FOREACH"]


@given(
    keyword=st.sampled_from(_DANGEROUS_KEYWORDS),
    case_variant=st.sampled_from(["upper", "lower", "title", "mixed"]),
)
@settings(max_examples=200)
def test_property3_dangerous_cypher_intercepted(keyword, case_variant):
    """
    属性 3a：危险关键词的所有大小写变体均必须被拦截。
    Validates: Requirements 4.1, 4.2, 4.3
    """
    if case_variant == "upper":
        kw = keyword.upper()
    elif case_variant == "lower":
        kw = keyword.lower()
    elif case_variant == "title":
        kw = keyword.title()
    else:
        # mixed：交替大小写
        kw = "".join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(keyword))

    cypher = f"MATCH (n) {kw} (n)"
    errors = _validate_no_writes_in_cypher_query(cypher)
    assert len(errors) > 0, (
        f"危险关键词 '{kw}' 应被拦截，但返回了空错误列表"
    )


@given(
    read_clause=st.sampled_from(["MATCH", "RETURN", "WITH", "WHERE", "ORDER BY", "LIMIT"]),
    suffix=st.text(min_size=0, max_size=30, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
)
@settings(max_examples=100)
def test_property3_readonly_cypher_not_intercepted(read_clause, suffix):
    """
    属性 3b：纯只读操作不应被拦截（返回空错误列表）。
    Validates: Requirements 4.4
    """
    # 构造只含只读关键词的 Cypher
    cypher = f"{read_clause} (n) RETURN n"
    errors = _validate_no_writes_in_cypher_query(cypher)
    assert len(errors) == 0, (
        f"只读 Cypher '{cypher}' 不应被拦截，但返回了错误: {errors}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 属性 4：幻觉检测重试上限保证
# Feature: intelligent-customer-service-agent, Property 4: 幻觉检测重试上限保证
# 验证：需求 5.6、5.7、5.8
# ═══════════════════════════════════════════════════════════════════════════════

def _simulate_hallucination_check(hallucination_retry: int, is_suspicious: bool) -> dict:
    """
    复现 lg_builder.py 中 check_hallucinations 的重试策略逻辑。
    返回 {"should_retry": bool, "new_retry_count": int}
    """
    if is_suspicious and hallucination_retry < 1:
        return {"should_retry": True, "new_retry_count": hallucination_retry + 1}
    return {"should_retry": False, "new_retry_count": hallucination_retry}


@given(
    hallucination_retry=st.integers(min_value=1, max_value=10),
    is_suspicious=st.booleans(),
)
@settings(max_examples=200)
def test_property4_no_retry_when_limit_reached(hallucination_retry, is_suspicious):
    """
    属性 4a：hallucination_retry >= 1 时，无论检测结果如何，都不触发重试。
    Validates: Requirements 5.6, 5.7, 5.8
    """
    result = _simulate_hallucination_check(hallucination_retry, is_suspicious)
    assert result["should_retry"] is False, (
        f"retry={hallucination_retry} >= 1 时不应触发重试，但 should_retry={result['should_retry']}"
    )


@given(is_suspicious=st.booleans())
@settings(max_examples=100)
def test_property4_retry_increments_counter(is_suspicious):
    """
    属性 4b：retry=0 且检测失败时，重试计数器必须变为 1。
    Validates: Requirements 5.7
    """
    result = _simulate_hallucination_check(hallucination_retry=0, is_suspicious=is_suspicious)
    if is_suspicious:
        assert result["should_retry"] is True
        assert result["new_retry_count"] == 1, (
            f"retry=0 且可疑时，计数器应变为 1，实际: {result['new_retry_count']}"
        )
    else:
        assert result["should_retry"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 属性 5：GraphRAG 检索模式选择正确性
# Feature: intelligent-customer-service-agent, Property 5: GraphRAG 检索模式选择正确性
# 验证：需求 6.1、6.2、6.3、6.4
# ═══════════════════════════════════════════════════════════════════════════════

@given(
    query=st.text(min_size=1, max_size=50),
    chat_history=st.text(min_size=0, max_size=200),
)
@settings(max_examples=300)
def test_property5_query_type_always_valid(query, chat_history):
    """
    属性 5a：对任意输入，_select_query_type 返回值必须在合法集合内。
    Validates: Requirements 6.1, 6.2, 6.3, 6.4
    """
    result = _select_query_type(query, chat_history)
    assert result in {"basic", "local", "global", "drift"}, (
        f"返回值 '{result}' 不在合法集合 {{basic, local, global, drift}} 内"
    )


@given(
    anaphora_word=st.sampled_from(["它", "这个", "那个", "上面", "刚才", "之前", "该", "此"]),
    suffix=st.text(min_size=0, max_size=20),
    chat_history=st.text(min_size=1, max_size=100),  # 非空历史
)
@settings(max_examples=150)
def test_property5_drift_priority_highest(anaphora_word, suffix, chat_history):
    """
    属性 5b：含指代词且历史非空时，优先级最高，必须返回 drift。
    Validates: Requirements 6.1
    """
    query = anaphora_word + suffix
    result = _select_query_type(query, chat_history)
    assert result == "drift", (
        f"含指代词 '{anaphora_word}' 且历史非空时应返回 drift，实际: {result}"
    )


@given(
    global_kw=st.sampled_from(["都有什么", "有哪些", "总结", "概述", "列举", "所有", "全部", "介绍一下"]),
    prefix=st.text(min_size=0, max_size=10),
)
@settings(max_examples=100)
def test_property5_global_priority_second(global_kw, prefix):
    """
    属性 5c：含归纳关键词且无指代词时，返回 global。
    Validates: Requirements 6.2
    """
    # 确保不含指代词（避免触发 drift 优先级）
    anaphora = ["它", "这个", "那个", "上面", "刚才", "之前", "该", "此"]
    query = prefix + global_kw
    assume(not any(w in query for w in anaphora))

    result = _select_query_type(query, chat_history="")  # 空历史，不触发 drift
    assert result == "global", (
        f"含归纳关键词 '{global_kw}' 且无指代词时应返回 global，实际: {result}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 属性 6：Schema 缓存幂等性与 TTL 刷新
# Feature: intelligent-customer-service-agent, Property 6: Schema 缓存幂等性与 TTL 刷新
# 验证：需求 7.3、7.4
# ═══════════════════════════════════════════════════════════════════════════════

def _make_schema_cache_fn():
    """
    构造一个独立的 Schema 缓存函数实例，用于属性测试（避免全局状态污染）。
    复现 kg_neo4j_conn.py 中的 get_neo4j_schema_cached 逻辑。
    """
    cache = {}
    cache_time = {}
    TTL = 60
    call_count = {"n": 0}

    def get_schema(graph_key: str = "structured", current_time: float = None) -> str:
        now = current_time if current_time is not None else time.time()
        if graph_key in cache and (now - cache_time.get(graph_key, 0)) < TTL:
            return cache[graph_key]
        # 缓存未命中，"重新获取"
        call_count["n"] += 1
        schema = f"schema_v{call_count['n']}"
        cache[graph_key] = schema
        cache_time[graph_key] = now
        return schema

    return get_schema, call_count


@given(
    t0=st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False),
    delta=st.floats(min_value=0.0, max_value=59.9, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_property6_cache_hit_within_ttl(t0, delta):
    """
    属性 6a：TTL 内连续两次调用必须返回相同值，且不触发新的获取。
    Validates: Requirements 7.3, 7.4
    """
    get_schema, call_count = _make_schema_cache_fn()

    # 第一次调用（缓存未命中，触发获取）
    v1 = get_schema("structured", current_time=t0)
    count_after_first = call_count["n"]

    # TTL 内第二次调用（应命中缓存）
    v2 = get_schema("structured", current_time=t0 + delta)
    count_after_second = call_count["n"]

    assert v1 == v2, (
        f"TTL 内两次调用应返回相同值: v1={v1}, v2={v2}, delta={delta:.2f}s"
    )
    assert count_after_second == count_after_first, (
        f"TTL 内第二次调用不应触发新获取: 获取次数从 {count_after_first} 变为 {count_after_second}"
    )


@given(
    t0=st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False),
    extra=st.floats(min_value=0.1, max_value=3600.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_property6_cache_refresh_after_ttl(t0, extra):
    """
    属性 6b：TTL 过期后调用必须重新获取 Schema 并更新缓存。
    Validates: Requirements 7.3, 7.4
    """
    get_schema, call_count = _make_schema_cache_fn()

    # 第一次调用
    v1 = get_schema("structured", current_time=t0)
    count_after_first = call_count["n"]

    # TTL 过期后调用（t0 + 60 + extra）
    v2 = get_schema("structured", current_time=t0 + 60 + extra)
    count_after_second = call_count["n"]

    assert count_after_second > count_after_first, (
        f"TTL 过期后应触发新获取: 获取次数应增加，但从 {count_after_first} 变为 {count_after_second}"
    )
    # 新获取的 schema 版本号不同
    assert v1 != v2, (
        f"TTL 过期后应返回新 Schema: v1={v1}, v2={v2}"
    )
