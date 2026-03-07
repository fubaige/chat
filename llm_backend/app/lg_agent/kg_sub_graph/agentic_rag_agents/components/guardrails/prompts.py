"""
Guardrails prompt template with chat history support.
"""

from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_neo4j import Neo4jGraph
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.utils.utils import retrieve_and_parse_schema_from_graph_for_prompts
from app.lg_agent.kg_sub_graph.prompts.kg_prompts import GUARDRAILS_SYSTEM_PROMPT


def create_guardrails_prompt_template(
    graph: Optional[Neo4jGraph] = None, scope_description: Optional[str] = None
) -> ChatPromptTemplate:
    scope_context = (
        f"参考此范围描述来决策:\n{scope_description}"
        if scope_description is not None
        else ""
    )

    graph_context = (
        f"\n参考图表结构来回答:\n{retrieve_and_parse_schema_from_graph_for_prompts(graph)}"
        if graph is not None
        else ""
    )

    message = scope_context + graph_context + "\n\n对话历史（如有）:\n{chat_history}\n\n当前问题: {question}"

    return ChatPromptTemplate.from_messages(
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
