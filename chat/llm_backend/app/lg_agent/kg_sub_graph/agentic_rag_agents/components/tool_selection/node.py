"""
A tool_selection node must
* take a single task at a time
* retrieve a list of available tools
    * text2cypher
    * custom pre-written cypher executors
        * these can be numerous and may be retrieved in the same fashion as CypherQuery node contents
    * unstructured text search (sim search)
* decide the appropriate tool for the task
* generate and validate parameters for the selected tool
* send the validated parameters to the appropriate tool node
"""

from typing import Any, Callable, Coroutine, Dict, List, Literal, Set
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticToolsParser
from langchain_core.runnables.base import Runnable
from langgraph.types import Command, Send
from pydantic import BaseModel


from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.state import ToolSelectionInputState
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.tool_selection.prompts import create_tool_selection_prompt_template

# 定义工具选择提示词
tool_selection_prompt = create_tool_selection_prompt_template()


# 声明式的使用可配置模型：https://python.langchain.com/docs/how_to/chat_models_universal_init/#using-a-configurable-model-declaratively
def create_tool_selection_node(
    llm: BaseChatModel,
    tool_schemas: List[type[BaseModel]],
    default_to_text2cypher: bool = True,
) -> Callable[[ToolSelectionInputState], Coroutine[Any, Any, Command[Any]]]:
    """
    Create a tool_selection node to be used in a LangGraph workflow.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM used to process data.
    tool_schemas : Sequence[Union[Dict[str, Any], type, Callable, BaseTool]
        tools schemas that inform the LLM which tools are available.
    default_to_text2cypher : bool, optional
        Whether to attempt Text2Cypher if no tool calls are returned by the LLM, by default True

    Returns
    -------
    Callable[[ToolSelectionInputState], ToolSelectionOutputState]
        The LangGraph node.
    """

    # 构建工具选择链，由大模型根据传递过来的 Task，在预定义的工具列表中选择一个工具。
    tool_selection_chain: Runnable[Dict[str, Any], Any] = (
        tool_selection_prompt
        | llm.bind_tools(tools=tool_schemas)
        | PydanticToolsParser(tools=tool_schemas, first_tool_only=True)
    )

    # 从传入的tool_schemas列表中，获取每个工具的title属性，创建出一个工具名称集合。
    predefined_cypher_tools: Set[str] = {
        t.model_json_schema().get("title", "") for t in tool_schemas
    }


    # async def tool_selection(
    #     state: ToolSelectionInputState,
    # ) -> Command[Literal["text2cypher", "predefined_cypher", "customer_tools"]]:
    async def tool_selection(
        state: ToolSelectionInputState,
    ) -> Command[Literal["cypher_query", "predefined_cypher", "customer_tools"]]:
        """
        Choose the appropriate tool for the given task.
        
        优先级强制规则：
        1. 如果工具列表包含 microsoft_graphrag_query，优先使用（文档知识库）
        2. 只有在明确需要查询结构化数据（订单号、库存数量等）时才用 cypher_query
        """
        question = state.get("question", "")
        
        # 强制优先 GraphRAG：检查工具列表是否包含 microsoft_graphrag_query
        graphrag_tool_name = "microsoft_graphrag_query"
        has_graphrag = any(
            t.model_json_schema().get("title", "") == graphrag_tool_name 
            for t in tool_schemas
        )
        
        # 如果有 GraphRAG 工具，直接使用，不让 LLM 选择
        # 除非问题明确包含"订单号"、"库存"、"数量"等结构化数据关键词
        if has_graphrag:
            structured_keywords = ["订单号", "订单id", "库存数量", "精确价格", "具体数量", "order id", "stock quantity"]
            needs_structured = any(kw in question.lower() for kw in structured_keywords)
            
            if not needs_structured:
                # 直接使用 GraphRAG，不调用 LLM
                return Command(
                    goto=Send(
                        "customer_tools",
                        {
                            "task": question,
                            "query_name": graphrag_tool_name,
                            "query_parameters": {"query": question},
                            "steps": ["tool_selection"],
                        },
                    )
                )
        
        # 如果明确需要结构化数据，或没有 GraphRAG 工具，才让 LLM 选择
        tool_selection_output: BaseModel = await tool_selection_chain.ainvoke(
            {"question": question}
        )

        # 根据路由到对应的工具节点
        go_to_text2cypher = Command(
            goto=Send(
                "cypher_query",
                {
                    "task": state.get("question", ""),
                    "query_name": "cypher_query",
                    "query_parameters": {},
                    "steps": ["tool_selection"],
                },
            )
        )
        if tool_selection_output is not None:
            tool_name: str = tool_selection_output.model_json_schema().get("title", "")
            tool_args: Dict[str, Any] = tool_selection_output.model_dump() 
            if tool_name == "predefined_cypher":
                return Command(
                    goto=Send(
                        "predefined_cypher",
                        {
                            "task": state.get("question", ""),
                            "query_name": tool_name,
                            "query_parameters": tool_args,
                            "steps": ["tool_selection"],
                        },
                    )
                )
            elif tool_name == "cypher_query":
                return go_to_text2cypher
            
            else:
                return Command(
                    goto=Send(
                        "customer_tools",
                        {
                            "task": state.get("question", ""),
                            "query_name": tool_name,
                            "query_parameters": tool_args,
                            "steps": ["tool_selection"],
                        },
                    )
                )


           
                
        elif default_to_text2cypher:
            return go_to_text2cypher

        # handle instance where no tool is chosen
        else:
            return Command(
                goto=Send(
                    "error_tool_selection",
                    {
                        "task": state.get("question", ""),
                        "errors": [
                            f"Unable to assign tool to question: `{state.get('question', '')}`"
                        ],
                        "steps": ["tool_selection"],
                    },
                )
            )

        return go_to_text2cypher

    return tool_selection
