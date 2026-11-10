import os
import sys
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.agent_tools import (
    fetch_corridor_conditions,
    query_telemetry_db,
    search_compliance_sop,
)

load_dotenv(project_root / ".env")

system_prompt = (project_root / "src" / "prompts" / "system_prompt.txt").read_text()

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


agent_llm = os.getenv("Agent_llm", "DEEPSEEK").strip().upper()

if agent_llm == "OPENAI":
    from langchain_openai import ChatOpenAI

    print("Agent model: OpenAI gpt-4o")
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
elif agent_llm == "DEEPSEEK":
    from langchain_openai import ChatOpenAI

    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    if not deepseek_api_key:
        raise ValueError("Agent_llm=DEEPSEEK but DEEPSEEK_API_KEY is empty in .env")
    print("Agent model: DeepSeek deepseek-v4-flash")
    llm = ChatOpenAI(
        model="deepseek-v4-flash",
        temperature=0,
        api_key=deepseek_api_key,
        base_url="https://api.deepseek.com",
        max_tokens=2048,
    )
else:
    from langchain_community.chat_models import ChatOllama

    print("Agent model: local Ollama qwen2.5:7b")
    llm = ChatOllama(model="qwen2.5:7b", temperature=0, num_predict=1024)

fde_tools = [query_telemetry_db, fetch_corridor_conditions, search_compliance_sop]
llm_with_tools = llm.bind_tools(fde_tools)


def reasoning_node(state: AgentState):
    messages = list(state["messages"])
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt), *messages]
    return {"messages": [llm_with_tools.invoke(messages)]}


graph_builder = StateGraph(AgentState)
graph_builder.add_node("reasoner", reasoning_node)
graph_builder.add_node("tools", ToolNode(fde_tools))
graph_builder.add_edge(START, "reasoner")
graph_builder.add_conditional_edges("reasoner", tools_condition, {"tools": "tools", END: END})
graph_builder.add_edge("tools", "reasoner")
graph = graph_builder.compile(checkpointer=MemorySaver())


def ask(question: str, thread_id: str = "dispatcher") -> str:
    result = graph.invoke(
        {"messages": [HumanMessage(content=question)]},
        {"configurable": {"thread_id": thread_id}, "recursion_limit": 12},
    )
    return result["messages"][-1].content


if __name__ == "__main__":
    print("Cold-chain dispatcher. Type 'exit' to stop.")
    print("Try:")
    print("  Find shipments near Los Angeles (latitude 33.8, longitude -118.1) with cargo_temperature_c above 4. Check the weather there and say whether that violates the SOP for fresh perishables.")
    print("  I'm a new dispatcher on the night shift. Can you explain what this SOP requires for a high-risk shipment?")
    thread_id = "dispatcher-cli"
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
