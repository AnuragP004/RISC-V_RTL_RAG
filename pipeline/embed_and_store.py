# pipeline/embed_and_store.py
import json
import os
from pathlib import Path
from typing import List, Dict
import chromadb
from chromadb.utils import embedding_functions
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(Path(__file__).parent / ".env")

# ── Embedding model config ──────────────────────────────────────────
# Option A: Gemini (Google Generative AI)
# Get free API key from Google AI Studio, then: export GEMINI_API_KEY=your_key
USE_GEMINI = bool(os.getenv("GEMINI_API_KEY"))

# Option B: Local sentence-transformers (no API key needed)
LOCAL_MODEL = "sentence-transformers/all-mpnet-base-v2"

def get_embedding_function():
    if USE_GEMINI:
        print("Using Gemini embeddings (models/text-embedding-004)")
        return embedding_functions.GoogleGenerativeAiEmbeddingFunction(
            api_key=os.getenv("GEMINI_API_KEY"),
            task_type="RETRIEVAL_DOCUMENT"
        )
    else:
        print(f"Using local embeddings: {LOCAL_MODEL}")
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=LOCAL_MODEL
        )

def load_all_chunks(chunks_dir: str) -> List[Dict]:
    """Load all JSON chunk files from the chunks directory."""
    all_chunks = []
    seen_ids = set()
    for json_file in Path(chunks_dir).glob('*.json'):
        with open(json_file) as f:
            chunks = json.load(f)
            for chunk in chunks:
                if chunk['id'] not in seen_ids:
                    seen_ids.add(chunk['id'])
                    all_chunks.append(chunk)
        print(f"Loaded {len(chunks)} chunks from {json_file.name}")
    return all_chunks

def build_vector_store(chunks: List[Dict], persist_dir: str):
    """Embed all chunks and store in ChromaDB."""
    
    embed_fn = get_embedding_function()
    
    # Initialize persistent ChromaDB
    client = chromadb.PersistentClient(path=persist_dir)
    
    # Separate collections for Verilog and text
    # (lets you retrieve from each independently later)
    verilog_collection = client.get_or_create_collection(
        name="verilog_rtl",
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"}
    )
    
    text_collection = client.get_or_create_collection(
        name="spec_and_docs",
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"}
    )
    
    # Split chunks by type
    verilog_chunks = [c for c in chunks if c.get('type') in 
                      ('module_header', 'always_block', 'assign_statements')]
    text_chunks = [c for c in chunks if c.get('type') in 
                   ('text_section', 'text_window')]
    
    print(f"\nIndexing {len(verilog_chunks)} Verilog chunks...")
    batch_upsert(verilog_collection, verilog_chunks)
    
    print(f"Indexing {len(text_chunks)} text chunks...")
    batch_upsert(text_collection, text_chunks)
    
    print(f"\n✓ Vector store built at: {persist_dir}")
    print(f"  Verilog collection: {verilog_collection.count()} docs")
    print(f"  Text collection:    {text_collection.count()} docs")
    
    return client

def batch_upsert(collection, chunks: List[Dict], batch_size: int = 100):
    """Upsert chunks in batches (ChromaDB has limits on batch size)."""
    for i in tqdm(range(0, len(chunks), batch_size)):
        batch = chunks[i:i + batch_size]
        
        ids = [c['id'] for c in batch]
        documents = [c['content'] for c in batch]
        metadatas = [c.get('metadata', {}) for c in batch]
        
        # ChromaDB metadata values must be str/int/float/bool
        # Clean any None values
        metadatas = [
            {k: str(v) if v is not None else "" for k, v in m.items()}
            for m in metadatas
        ]
        
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

if __name__ == "__main__":
    chunks = load_all_chunks("corpus/chunks")
    print(f"\nTotal chunks to index: {len(chunks)}")
    build_vector_store(chunks, "data/chroma_db")