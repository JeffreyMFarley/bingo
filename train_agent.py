#!/usr/bin/env python3
"""train_agent.py - simple scaffold for building a FAISS index and querying with OpenAI.

This is a lightweight, opinionated starting point. Update model names and glue code
according to your project's requirements.
"""
import os
import glob
import json
import argparse
from dotenv import load_dotenv
import yaml
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

try:
    import faiss
except Exception:
    faiss = None

try:
    import openai
except Exception:
    openai = None


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_text_files(data_dir):
    docs = []
    patterns = ["**/*.txt", "*.txt"]
    for pat in patterns:
        for p in glob.glob(os.path.join(data_dir, pat), recursive=True):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    docs.append({"path": p, "text": fh.read()})
            except Exception:
                continue
    return docs


def build_index(docs, model_name, index_path="index.faiss", docs_path="docs.json"):
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is required. Install from requirements.txt")
    if faiss is None:
        raise RuntimeError("faiss (faiss-cpu) is required. Install from requirements.txt")
    model = SentenceTransformer(model_name)
    texts = [d["text"] for d in docs]
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(np.asarray(embeddings, dtype="float32"))
    faiss.write_index(index, index_path)
    with open(docs_path, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)
    print(f"Saved index to {index_path} and docs to {docs_path}")


def load_index(index_path="index.faiss", docs_path="docs.json"):
    if faiss is None:
        raise RuntimeError("faiss (faiss-cpu) is required. Install from requirements.txt")
    index = faiss.read_index(index_path)
    with open(docs_path, "r", encoding="utf-8") as f:
        docs = json.load(f)
    return index, docs


def query_index_and_generate(query, index, docs, embed_model_name, top_k, openai_model, openai_key):
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is required. Install from requirements.txt")
    if openai is None:
        raise RuntimeError("openai package is required. Install from requirements.txt")
    emb_model = SentenceTransformer(embed_model_name)
    q_emb = emb_model.encode([query], convert_to_numpy=True)
    q_emb = np.asarray(q_emb, dtype="float32")
    D, I = index.search(q_emb, top_k)
    retrieved = [docs[i] for i in I[0] if i < len(docs)]
    context = "\n\n---\n\n".join(d.get("text", "") for d in retrieved)
    system = "You are an assistant that answers using the provided context. If the answer is not in the context, say you don't know and be concise."
    prompt = f"CONTEXT:\n{context}\n\nQUESTION: {query}\n\nAnswer concisely:"
    openai.api_key = openai_key
    resp = openai.ChatCompletion.create(
        model=openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=512,
        temperature=0.0,
    )
    return resp["choices"][0]["message"]["content"].strip(), retrieved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-index", action="store_true", help="Build FAISS index from data dir")
    parser.add_argument("--query", type=str, help="Query the index with a question")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    load_dotenv()
    cfg = load_config(args.config)
    data_dir = cfg.get("data_dir", "data")
    embed_model = cfg.get("embed_model", "sentence-transformers/all-MiniLM-L6-v2")
    index_path = cfg.get("index_path", "index.faiss")
    docs_path = cfg.get("docs_path", "docs.json")
    openai_model = cfg.get("openai_model", "gpt-4o-mini")
    top_k = cfg.get("top_k", 3)
    openai_key = os.getenv("OPENAI_API_KEY")

    if args.build_index:
        docs = read_text_files(data_dir)
        if not docs:
            print(f"No .txt files found in {data_dir}. Add plaintext docs and try again.")
            return
        build_index(docs, embed_model, index_path=index_path, docs_path=docs_path)
        return

    if args.query:
        if not os.path.exists(index_path) or not os.path.exists(docs_path):
            print("Index or docs not found. Run with --build-index first.")
            return
        if not openai_key:
            print("OPENAI_API_KEY not set. Copy .env.example to .env and set your key.")
            return
        index, docs = load_index(index_path=index_path, docs_path=docs_path)
        answer, retrieved = query_index_and_generate(args.query, index, docs, embed_model, top_k, openai_model, openai_key)
        print("--- Retrieved docs ---")
        for r in retrieved:
            print(r.get("path"))
        print("\n--- Answer ---\n")
        print(answer)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
