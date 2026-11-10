import os
import re
from pathlib import Path

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv(Path(__file__).resolve().parent / ".env")

from src.orchestrator import ask

MENTION = re.compile(r"<@[A-Z0-9]+>")


def question_text(event: dict) -> str:
    return MENTION.sub("", event.get("text") or "").strip()


def conversation_id(event: dict) -> str:
    return f"{event['channel']}:{event.get('thread_ts') or event['ts']}"


def slack_text(answer: str) -> str:
    lines = []
    for line in answer.splitlines():
        if line.startswith("### "):
            lines.append(f"*{line[4:].strip()}*")
        else:
            lines.append(line.replace("**", "*"))
    text = "\n".join(lines).strip() or "No answer was produced."
    if len(text) > 39000:
        return text[:39000] + "\n…"
    return text


def acknowledge(ack):
    ack()


def reply(event, say):
    if event.get("bot_id") or event.get("subtype"):
        return
    question = question_text(event)
    thread_ts = event.get("thread_ts") or event["ts"]
    if not question:
        say(text="Send a question after the mention.", thread_ts=thread_ts)
        return

    say(
        text="Checking the fleet data, weather, and the SOP. Just a sec ...",
        thread_ts=thread_ts,
    )
    try:
        answer = ask(question, thread_id=conversation_id(event))
    except Exception as exc:
        say(text=f"The assistant failed: {exc}", thread_ts=thread_ts)
        return
    say(text=slack_text(answer), thread_ts=thread_ts)


def reply_to_dm(event, say):
    if event.get("channel_type") != "im":
        return
    reply(event, say)


def main() -> None:
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")
    if not bot_token or not app_token:
        raise ValueError("Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env")

    app = App(token=bot_token)
    app.event("app_mention")(ack=acknowledge, lazy=[reply])
    app.event("message")(ack=acknowledge, lazy=[reply_to_dm])
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
