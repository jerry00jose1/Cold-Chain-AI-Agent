import os
import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.settings import EXAMPLE_QUESTIONS, agent_llm_name
from src.transcript import message_text

system_prompt = (project_root / "src" / "prompts" / "system_prompt.txt").read_text()

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


_graph = None


def build_chat_model():
    name = agent_llm_name()
    if name == "OPENAI":
        from langchain_openai import ChatOpenAI

        print("Agent model: OpenAI gpt-4o")
        return ChatOpenAI(model="gpt-4o", temperature=0)
    if name == "DEEPSEEK":
        from langchain_openai import ChatOpenAI

        deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        if not deepseek_api_key:
            raise ValueError("Agent_llm=DEEPSEEK but DEEPSEEK_API_KEY is empty in .env")
        print("Agent model: DeepSeek deepseek-v4-flash")
        return ChatOpenAI(
            model="deepseek-v4-flash",
            temperature=0,
            api_key=deepseek_api_key,
            base_url="https://api.deepseek.com",
            max_tokens=2048,
        )

    from langchain_community.chat_models import ChatOllama

    print("Agent model: local Ollama qwen2.5:7b")
    return ChatOllama(model="qwen2.5:7b", temperature=0, num_predict=1024)


def get_graph():
    global _graph
    if _graph is not None:
        return _graph

    from src.agent_tools import (
        fetch_corridor_conditions,
        query_telemetry_db,
        search_compliance_sop,
    )

    tools = [query_telemetry_db, fetch_corridor_conditions, search_compliance_sop]
    llm_with_tools = build_chat_model().bind_tools(tools)

    def reasoning_node(state: AgentState):
        messages = list(state["messages"])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt), *messages]
        return {"messages": [llm_with_tools.invoke(messages)]}

    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("reasoner", reasoning_node)
    graph_builder.add_node("tools", ToolNode(tools))
    graph_builder.add_edge(START, "reasoner")
    graph_builder.add_conditional_edges("reasoner", tools_condition, {"tools": "tools", END: END})
    graph_builder.add_edge("tools", "reasoner")
    _graph = graph_builder.compile(checkpointer=MemorySaver())
    return _graph


def ask(question: str, thread_id: str = "dispatcher") -> str:
    result = get_graph().invoke(
        {"messages": [HumanMessage(content=question)]},
        {"configurable": {"thread_id": thread_id}, "recursion_limit": 12},
    )
    return message_text(result["messages"][-1]) or "No answer was produced."


if __name__ == "__main__":
    print("Cold-chain dispatcher. Type 'exit' to stop.")
    print("Try:")
    for _label, question in EXAMPLE_QUESTIONS:
        print(f"  {question}")
    thread_id = "dispatcher-cli"
    graph = get_graph()
    while True:
        question = input("\nDispatcher: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue
        for step in graph.stream(
            {"messages": [HumanMessage(content=question)]},
            {"configurable": {"thread_id": thread_id}, "recursion_limit": 12},
            stream_mode="values",
        ):
            step["messages"][-1].pretty_print()
