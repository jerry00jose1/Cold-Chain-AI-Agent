import os
import uuid

import pandas as pd
import streamlit as st
from langchain_core.messages import HumanMessage
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.agent_tools import get_agent_engine
from src.orchestrator import get_graph
from src.settings import EXAMPLE_QUESTIONS, agent_llm_name, database_engine
from src.transcript import pair_tool_results

st.set_page_config(page_title="Cold-chain dispatch", page_icon="❄", layout="wide")


def log_audit(session_id: str, node_name: str, tool_name: str, content: str) -> None:
    with get_agent_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO fde_views.agent_audit_log
                    (session_id, node_name, tool_name, content)
                VALUES
                    (:session_id, :node_name, :tool_name, :content)
                """
            ),
            {
                "session_id": session_id,
                "node_name": node_name,
                "tool_name": tool_name,
                "content": content,
            },
        )


def run_turn(question: str, session_id: str) -> dict:
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 12}
    snapshot = graph.get_state(config)
    previous = snapshot.values.get("messages", []) if snapshot.values else []
    result = graph.invoke({"messages": [HumanMessage(content=question)]}, config)
    tools, answer = pair_tool_results(result["messages"][len(previous):])

    audit_error = None
    try:
        for tool in tools:
            log_audit(
                session_id,
                "tools",
                tool["name"],
                f"Arguments: {tool['args']}\n\nResult:\n{tool['result']}",
            )
        if answer:
            log_audit(session_id, "reasoner", "answer", answer)
    except SQLAlchemyError as exc:
        audit_error = str(exc)
    return {
        "role": "assistant",
        "content": answer or "No answer was produced.",
        "tools": tools,
        "audit_error": audit_error,
    }


def ensure_session() -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "turns" not in st.session_state:
        st.session_state.turns = []
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None
    if "page" not in st.session_state:
        st.session_state.page = "Dispatch"


def queue_example(question: str) -> None:
    st.session_state.pending_question = question
    st.session_state.page = "Dispatch"


def draw_sidebar() -> None:
    with st.sidebar:
        st.radio("Page", ["Dispatch", "Audit log"], key="page")
        st.caption(f"Agent model: {agent_llm_name()}")
        st.caption(f"Session: {st.session_state.session_id[:8]}")
        st.divider()
        st.markdown("**Try a question**")
        for label, question in EXAMPLE_QUESTIONS:
            st.button(label, use_container_width=True, on_click=queue_example, args=(question,))
        st.divider()
        st.caption("Fleet readings in the database run from 1 Jan 2021 through 29 Aug 2024.")


def draw_dispatch() -> None:
    st.title("Cold-chain dispatch")
    st.caption("Ask about cargo temperature, route risk, live weather, or the operating procedure.")

    for turn in st.session_state.turns:
        with st.chat_message(turn["role"]):
            if turn["role"] == "assistant" and turn.get("tools"):
                with st.expander(f"{len(turn['tools'])} tool call(s)"):
                    for tool in turn["tools"]:
                        st.markdown(f"**{tool['name']}**")
                        st.code(str(tool["args"]), language="text")
                        st.text(tool["result"])
            st.markdown(turn["content"])

    question = st.chat_input("Ask the dispatcher assistant")
    if st.session_state.pending_question:
        question = st.session_state.pending_question
        st.session_state.pending_question = None
    if not question:
        return

    st.session_state.turns.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Checking fleet data, weather, and the SOP..."):
            try:
                turn = run_turn(question, st.session_state.session_id)
            except Exception as exc:
                turn = {"role": "assistant", "content": f"The assistant failed: {exc}", "tools": []}
        if turn.get("tools"):
            with st.expander(f"{len(turn['tools'])} tool call(s)"):
                for tool in turn["tools"]:
                    st.markdown(f"**{tool['name']}**")
                    st.code(str(tool["args"]), language="text")
                    st.text(tool["result"])
        if turn.get("audit_error"):
            st.warning(f"The answer was not written to the audit log: {turn['audit_error']}")
        st.markdown(turn["content"])
    st.session_state.turns.append(turn)


def read_audit_log(username: str, password: str) -> pd.DataFrame:
    engine = database_engine(username, password)
    with engine.connect() as conn:
        return pd.read_sql(
            text(
                """
                SELECT log_id, logged_at, session_id, node_name, tool_name, content
                FROM fde_views.agent_audit_log
                ORDER BY log_id DESC
                LIMIT 200
                """
            ),
            conn,
        )


def draw_audit() -> None:
    st.title("Audit log")
    st.caption("Sign in with the database admin login. The agent login can write this log and cannot read it.")

    if not st.session_state.get("audit_user"):
        with st.form("audit_login"):
            username = st.text_input("Database user", value=os.getenv("PG_ADMIN_USER", ""))
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Show log")
        if not submitted:
            return
        try:
            frame = read_audit_log(username, password)
        except SQLAlchemyError as exc:
            st.error(f"Could not read the audit log: {exc}")
            return
        st.session_state.audit_user = username
        st.session_state.audit_password = password
    else:
        try:
            frame = read_audit_log(st.session_state.audit_user, st.session_state.audit_password)
        except SQLAlchemyError as exc:
            st.error(f"Could not read the audit log: {exc}")
            return

    st.write(f"Signed in as `{st.session_state.audit_user}`. {len(frame)} recent row(s).")
    if st.button("Lock"):
        for key in ("audit_user", "audit_password"):
            st.session_state.pop(key, None)
        st.rerun()
    if frame.empty:
        st.info("No audit rows yet. Ask a question on the Dispatch page first.")
        return
    st.dataframe(frame, use_container_width=True, hide_index=True)


ensure_session()
draw_sidebar()
if st.session_state.page == "Dispatch":
    draw_dispatch()
else:
    draw_audit()
