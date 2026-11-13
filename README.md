
# Cold-chain dispatch assistant

A small dispatcher assistant for refrigerated shipments. You ask a question in the browser or in Slack, and it checks fleet readings in Postgres, looks up the operating procedure in Pinecone, and can pull live weather for a coordinate. The model answers from those results.

The fleet data is a historical CSV (Jan 2021 through Aug 2024), loaded into a messy "legacy" table. The assistant is only allowed to read a cleaned-up view. It can write an audit log of what it did, and it cannot read that log back.

## Stack

- Python 3.12
- Postgres
- LangGraph, with DeepSeek model
- Embeddings from a local Hugging Face model (`BAAI/bge-m3`)
- Pinecone for the SOP
- Streamlit for the browser UI
- Slack Bolt, in Socket Mode, for the same assistant in Slack

## Setup

You need Postgres running locally, a Pinecone API key, and a key for whichever chat model you pick. DeepSeek is what I used.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create the database and an admin login (this one is `jerry` / `jerry` on my machine):

```bash
psql postgres -c "CREATE ROLE jerry LOGIN PASSWORD 'jerry';"
psql postgres -c "CREATE DATABASE cold_chain OWNER jerry;"
```

Copy this into `.env` and fill in the keys:

```
PG_HOST=localhost
PG_PORT=5432
PG_DB=cold_chain
PG_ADMIN_USER=jerry
PG_ADMIN_PASSWORD=jerry
PG_AGENT_USER=usr_fde_ro
PG_AGENT_PASSWORD=AgentPassword2026

Embeddings_model=LOCAL
Agent_llm=DEEPSEEK

SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=

OPENAI_API_KEY=
DEEPSEEK_API_KEY=
PINECONE_API_KEY=
```

`Agent_llm` can be `DEEPSEEK`, `OPENAI`, or `OLLAMA`. `Embeddings_model` can be `LOCAL` or `OPENAI`. The SOP upload and the assistant have to use the same embedding setting, because they write to different Pinecone indexes (`fde-sop-index-local` and `fde-sop-index-openai`).

The first time you use `LOCAL`, it downloads `BAAI/bge-m3` (about 2 GB).

## Load the data

```bash
python scripts/ingest_legacy_data.py
psql -d cold_chain -f scripts/setup_security_and_view.sql
psql -d cold_chain -f scripts/setup_audit_log.sql
python scripts/ingest_sop_pinecone.py
```

`setup_security_and_view.sql` creates the read-only login `usr_fde_ro` and the view `fde_views.vw_active_fleet`. Run that file as a superuser. If the role already exists, that line will fail and the rest of the file still needs to be applied by hand.

If you change `data/policy/Cold_Chain_Incident_SOP_v2.md`, run the Pinecone script again. It skips the file when nothing changed.

Running the CSV load again empties the legacy table and refills it. It does not drop the table, so the view stays intact.

## Run it

```bash
streamlit run app.py
```

Open http://localhost:8501.

The Dispatch page is the chat. The Audit log page asks for the admin database login (`PG_ADMIN_USER`). The agent login can insert audit rows and cannot select them.

There is also a terminal version:

```bash
python src/orchestrator.py
```

## Slack

Same assistant, different front door. `slack_app.py` acknowledges the message, runs the question, and posts the answer in the thread. Leave the process running while you use it.

```bash
python slack_app.py
```

The Slack tokens are created at [api.slack.com/apps](https://api.slack.com/apps):

- **Basic Information → App-Level Tokens.** Generate a token with the `connections:write` scope. It starts with `xapp-`. That is `SLACK_APP_TOKEN`. Then turn on **Socket Mode**.
- **OAuth & Permissions.** Add the bot scopes `app_mentions:read`, `chat:write`, `im:history`, `im:read`, and `im:write`. Click **Install to Workspace**. The **Bot User OAuth Token** starts with `xoxb-`. That is `SLACK_BOT_TOKEN`.
- **Event Subscriptions.** Subscribe to `app_mention` and `message.im`.
- **App Home.** Turn on the Messages tab, or direct messages never arrive.

Invite the bot into a channel (`/invite @YourBot`), then mention it:

```text
@YourBot which shipments near Los Angeles are above 4°C?
```

A direct message does not need the mention. Follow-ups in the same thread keep the conversation. Restarting `slack_app.py` clears it. The first question also downloads or loads the embedding model, so it is slower than the ones after it.

## Layout

- `app.py` is the Streamlit console
- `slack_app.py` is the Slack listener
- `src/agent_tools.py` is the SQL, weather, and SOP tools
- `src/orchestrator.py` is the LangGraph loop
- `scripts/ingest_legacy_data.py` loads the CSV into `legacy.t_rfr_tlm_hist`
- `data/policy/` is the SOP that gets embedded

