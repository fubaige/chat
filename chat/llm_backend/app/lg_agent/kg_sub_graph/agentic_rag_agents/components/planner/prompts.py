from langchain_core.prompts import ChatPromptTemplate
from app.lg_agent.kg_sub_graph.prompts.kg_prompts import PLANNER_SYSTEM_PROMPT


def create_planner_prompt_template() -> ChatPromptTemplate:
    """
    Create a planner prompt template with chat history support.
    """
    message = """规则:
    * 确保任务不会返回重复或相似的信息。
    * 确保任务不依赖于从其他任务收集的信息！
    * 相互依赖的任务应该合并为单个问题。
    * 返回相同信息的任务应该合并为单个问题。
    * 结合对话历史理解用户的真实意图，将指代性问题补充完整。

    对话历史:
    {chat_history}

    当前问题: {question}
"""
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                PLANNER_SYSTEM_PROMPT,
            ),
            (
                "human",
                (message),
            ),
        ]
    )
