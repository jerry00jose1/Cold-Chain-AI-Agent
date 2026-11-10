from langchain_core.messages import AIMessage, ToolMessage


def message_text(message) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("text"):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content or "")


def pair_tool_results(messages) -> tuple[list[dict], str]:
    """Attach each tool result to the call id that produced it."""
    tools_by_id: dict[str, dict] = {}
    order: list[dict] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                item = {
                    "id": call["id"],
                    "name": call["name"],
                    "args": call.get("args", {}),
                    "result": "",
                }
                tools_by_id[call["id"]] = item
                order.append(item)
        elif isinstance(message, ToolMessage):
            item = tools_by_id.get(message.tool_call_id)
            if item is not None:
                item["result"] = message_text(message)

    answer = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message_text(message) and not message.tool_calls:
            answer = message_text(message)
            break
    return order, answer
