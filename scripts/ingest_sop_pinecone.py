import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pypdf
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from pinecone import Pinecone, ServerlessSpec

project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env")

policy_dir = project_root / "data" / "policy"
cache_dir = project_root / "data" / "cache"
hash_cache_file = cache_dir / "ingestion_hash_cache.json"

SUPPORTED_EXTENSIONS = [".md", ".txt", ".pdf", ".csv", ".xlsx"]
BATCH_SIZE = 100

pinecone_api_key = os.getenv("PINECONE_API_KEY")
if not pinecone_api_key:
    raise ValueError("Missing PINECONE_API_KEY in .env")

embeddings_setting = os.getenv("Embeddings_model", "LOCAL").strip().upper()

# Potentially move embeddings model to openai
if embeddings_setting == "OPENAI":
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Embeddings_model=OPENAI but OPENAI_API_KEY is empty in .env")
    print("Embeddings: OpenAI (1536 dimensions)")
    embeddings = OpenAIEmbeddings()
    index_name = "fde-sop-index-openai"
    index_dimension = 1536
else:
    from langchain_huggingface import HuggingFaceEmbeddings

    local_model = os.getenv("Local_Embedding_Model", "BAAI/bge-m3").strip()
    print(f"Embeddings: local Hugging Face model {local_model} (1024 dimensions)")
    embeddings = HuggingFaceEmbeddings(
        model_name=local_model, model_kwargs={"device": "cpu"}
    )
    index_name = "fde-sop-index-local"
    index_dimension = 1024


def parse_and_chunk_document(doc_path: Path) -> list[Document]:
    extension = doc_path.suffix.lower()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)

    if extension == ".md":
        md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "Header_1"),
                ("##", "Header_2"),
                ("###", "Header_3"),
            ]
        )
        header_docs = md_splitter.split_text(doc_path.read_text(encoding="utf-8"))
        chunks = text_splitter.split_documents(header_docs)
    elif extension == ".txt":
        raw_doc = Document(page_content=doc_path.read_text(encoding="utf-8"))
        chunks = text_splitter.split_documents([raw_doc])
    elif extension == ".pdf":
        reader = pypdf.PdfReader(doc_path)
        page_docs = [
            Document(
                page_content=page.extract_text(), metadata={"page_number": page_number}
            )
            for page_number, page in enumerate(reader.pages, start=1)
            if page.extract_text()
        ]
        chunks = text_splitter.split_documents(page_docs)
    else:
        if extension == ".csv":
            df = pd.read_csv(doc_path)
        elif extension == ".xlsx":
            df = pd.read_excel(doc_path)
        else:
            raise ValueError(f"Unsupported file extension: {extension}")
        chunks = [
            Document(
                page_content=" | ".join(
                    f"{col}: {val}" for col, val in row.items() if pd.notna(val)
                ),
                metadata={"row_index": int(row_index)},
            )
            for row_index, row in df.iterrows()
        ]

    for chunk in chunks:
        chunk.page_content = chunk.page_content.strip()
    return [chunk for chunk in chunks if chunk.page_content]


print(f"Connecting to Pinecone index {index_name}...")
pc = Pinecone(api_key=pinecone_api_key)

if (
    pc.has_index(index_name)
    and pc.describe_index(index_name).dimension != index_dimension
):
    print(f"Index {index_name} has the wrong dimension, recreating it...")
    pc.delete_index(index_name)

if not pc.has_index(index_name):
    print(f"Creating index {index_name} ({index_dimension} dimensions)...")
    pc.create_index(
        name=index_name,
        dimension=index_dimension,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )

index_client = pc.Index(index_name)
vector_store = PineconeVectorStore(index_name=index_name, embedding=embeddings)

# The cache remembers each file's hash so unchanged files are not re-embedded on every run
cache_dir.mkdir(parents=True, exist_ok=True)
hash_cache: dict[str, str] = {}
if hash_cache_file.exists():
    hash_cache = json.loads(hash_cache_file.read_text())

policy_files = {
    path.name: path
    for path in sorted(policy_dir.iterdir())
    if path.suffix.lower() in SUPPORTED_EXTENSIONS
}
print(f"Found {len(policy_files)} policy file(s) in {policy_dir}")

for deleted_file in set(hash_cache) - set(policy_files):
    print(f"Removing deleted file from Pinecone: {deleted_file}")
    index_client.delete(filter={"source_file": {"$eq": deleted_file}})

updated_cache: dict[str, str] = {}

for file_name, file_path in policy_files.items():
    file_hash = hashlib.md5(file_path.read_bytes()).hexdigest()

    if hash_cache.get(file_name) == file_hash:
        print(f"Skipped (unchanged): {file_name}")
        updated_cache[file_name] = file_hash
        continue

    print(f"Processing: {file_name}")
    if file_name in hash_cache:
        index_client.delete(filter={"source_file": {"$eq": file_name}})

    chunks = parse_and_chunk_document(file_path)
    if not chunks:
        print(f"  No text found in {file_name}, skipping")
        continue

    for chunk in chunks:
        chunk.metadata["source_file"] = file_name
        chunk.metadata["file_format"] = file_path.suffix.lstrip(".").upper()
    chunk_ids = [
        f"{file_name}-chunk-{chunk_index}" for chunk_index in range(len(chunks))
    ]

    print(f"  Uploading {len(chunks)} chunk(s)...")
    for start in range(0, len(chunks), BATCH_SIZE):
        vector_store.add_documents(
            documents=chunks[start : start + BATCH_SIZE],
            ids=chunk_ids[start : start + BATCH_SIZE],
        )
    updated_cache[file_name] = file_hash

hash_cache_file.write_text(json.dumps(updated_cache, indent=4))
print("SOP ingestion complete.")
