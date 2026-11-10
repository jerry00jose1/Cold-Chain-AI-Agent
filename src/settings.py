import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

EXAMPLE_QUESTIONS = (
    (
        "Los Angeles breach",
        "Find shipments near Los Angeles (latitude 33.8, longitude -118.1) with "
        "cargo_temperature_c above 4. Check the weather there and say whether that "
        "violates the SOP for fresh perishables.",
    ),
    (
        "High-risk rule",
        "I'm a new dispatcher on the night shift. Can you explain what this SOP "
        "requires for a high-risk shipment?",
    ),
)

AGENT_LLMS = ("OPENAI", "DEEPSEEK", "OLLAMA")
EMBEDDING_MODELS = ("OPENAI", "LOCAL")


def agent_llm_name() -> str:
    name = os.getenv("Agent_llm", "DEEPSEEK").strip().upper()
    if name not in AGENT_LLMS:
        allowed = ", ".join(AGENT_LLMS)
        raise ValueError(f"Unknown Agent_llm={name!r}. Use one of: {allowed}.")
    return name


def embedding_choice() -> str:
    name = os.getenv("Embeddings_model", "LOCAL").strip().upper()
    if name not in EMBEDDING_MODELS:
        allowed = ", ".join(EMBEDDING_MODELS)
        raise ValueError(f"Unknown Embeddings_model={name!r}. Use one of: {allowed}.")
    return name


def embedding_index() -> tuple[str, int]:
    if embedding_choice() == "OPENAI":
        return "fde-sop-index-openai", 1536
    return "fde-sop-index-local", 1024


@lru_cache(maxsize=1)
def get_embeddings():
    if embedding_choice() == "OPENAI":
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Embeddings_model=OPENAI but OPENAI_API_KEY is empty in .env")
        from langchain_openai import OpenAIEmbeddings

        print("Embeddings: OpenAI (1536 dimensions)")
        return OpenAIEmbeddings()

    from langchain_huggingface import HuggingFaceEmbeddings

    local_model = os.getenv("Local_Embedding_Model", "BAAI/bge-m3").strip()
    print(f"Embeddings: local Hugging Face model {local_model} (1024 dimensions)")
    return HuggingFaceEmbeddings(model_name=local_model, model_kwargs={"device": "cpu"})


def database_engine(username: str, password: str):
    database = os.getenv("PG_DB")
    if not username or not password or not database:
        raise ValueError("Database name, user, or password is missing.")
    return create_engine(
        URL.create(
            "postgresql+psycopg",
            username=username,
            password=password,
            host=os.getenv("PG_HOST", "localhost"),
            port=int(os.getenv("PG_PORT", "5432")),
            database=database,
        ),
        pool_pre_ping=True,
    )
