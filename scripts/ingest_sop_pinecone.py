import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pypdf
from langchain_core.documents import Document
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from pinecone import Pinecone, ServerlessSpec

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.settings import embedding_index, get_embeddings

POLICY_DIR = project_root / "data" / "policy"
CACHE_DIR = project_root / "data" / "cache"
HASH_CACHE_FILE = CACHE_DIR / "ingestion_hash_cache.json"
SUPPORTED_EXTENSIONS = [".md", ".txt", ".pdf", ".csv", ".xlsx"]
BATCH_SIZE = 100


def parse_and_chunk_document(doc_path: Path) -> list[Document]:
    extension = doc_path.suffix.lower()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)

    if extension == ".md":
        md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "Header_1"), ("##", "Header_2"), ("###", "Header_3")]
        )
        header_docs = md_splitter.split_text(doc_path.read_text(encoding="utf-8"))
        chunks = text_splitter.split_documents(header_docs)
    elif extension == ".txt":
        raw_doc = Document(page_content=doc_path.read_text(encoding="utf-8"))
        chunks = text_splitter.split_documents([raw_doc])
    elif extension == ".pdf":
        reader = pypdf.PdfReader(doc_path)
        page_docs = [
            Document(page_content=page.extract_text(), metadata={"page_number": page_number})
            for page_number, page in enumerate(reader.pages, start=1)
            if page.extract_text()
        ]
        chunks = text_splitter.split_documents(page_docs)
    else:
        if extension == ".csv":
            frame = pd.read_csv(doc_path)
        elif extension == ".xlsx":
            frame = pd.read_excel(doc_path)
        else:
            raise ValueError(f"Unsupported file extension: {extension}")
        chunks = [
            Document(
                page_content=" | ".join(f"{col}: {val}" for col, val in row.items() if pd.notna(val)),
                metadata={"row_index": int(row_index)},
            )
            for row_index, row in frame.iterrows()
        ]

    for chunk in chunks:
        chunk.page_content = chunk.page_content.strip()
    return [chunk for chunk in chunks if chunk.page_content]


def stale_chunk_ids(existing_ids: list[str], uploaded_ids: set[str]) -> list[str]:
    return [chunk_id for chunk_id in existing_ids if chunk_id not in uploaded_ids]


def list_chunk_ids(index_client, file_name: str) -> list[str]:
    prefix = f"{file_name}-chunk-"
    found = []
    for page in index_client.list(prefix=prefix):
        found.extend(page)
    return found


def main() -> None:
    pinecone_api_key = os.getenv("PINECONE_API_KEY")
    if not pinecone_api_key:
        raise ValueError("Missing PINECONE_API_KEY in .env")

    index_name, index_dimension = embedding_index()
    print(f"Connecting to Pinecone index {index_name}...")
    pc = Pinecone(api_key=pinecone_api_key)

    if pc.has_index(index_name) and pc.describe_index(index_name).dimension != index_dimension:
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
    vector_store = PineconeVectorStore(index_name=index_name, embedding=get_embeddings())

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    hash_cache: dict[str, str] = {}
    if HASH_CACHE_FILE.exists():
        hash_cache = json.loads(HASH_CACHE_FILE.read_text())

    policy_files = {
        path.name: path
        for path in sorted(POLICY_DIR.iterdir())
        if path.suffix.lower() in SUPPORTED_EXTENSIONS
    }
    print(f"Found {len(policy_files)} policy file(s) in {POLICY_DIR}")

    for deleted_file in set(hash_cache) - set(policy_files):
        print(f"Removing deleted file from Pinecone: {deleted_file}")
        index_client.delete(filter={"source_file": {"$eq": deleted_file}})
        hash_cache.pop(deleted_file, None)
        HASH_CACHE_FILE.write_text(json.dumps(hash_cache, indent=4))

    for file_name, file_path in policy_files.items():
        file_hash = hashlib.md5(file_path.read_bytes()).hexdigest()
        if hash_cache.get(file_name) == file_hash:
            print(f"Skipped (unchanged): {file_name}")
            continue

        print(f"Processing: {file_name}")
        chunks = parse_and_chunk_document(file_path)
        if not chunks:
            print(f"  No text found in {file_name}, skipping")
            continue

        for chunk in chunks:
            chunk.metadata["source_file"] = file_name
            chunk.metadata["file_format"] = file_path.suffix.lstrip(".").upper()
        chunk_ids = [f"{file_name}-chunk-{chunk_index}" for chunk_index in range(len(chunks))]

        print(f"  Uploading {len(chunks)} chunk(s)...")
        for start in range(0, len(chunks), BATCH_SIZE):
            vector_store.add_documents(
                documents=chunks[start : start + BATCH_SIZE],
                ids=chunk_ids[start : start + BATCH_SIZE],
            )

        leftovers = stale_chunk_ids(list_chunk_ids(index_client, file_name), set(chunk_ids))
        if leftovers:
            index_client.delete(ids=leftovers)

        hash_cache[file_name] = file_hash
        HASH_CACHE_FILE.write_text(json.dumps(hash_cache, indent=4))

    print("SOP ingestion complete.")


if __name__ == "__main__":
    main()
