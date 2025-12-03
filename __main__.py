#!/usr/bin/env python3

import os
import argparse

from dotenv import load_dotenv
import yaml

from src.agent import query_index_and_generate
from src.retriever_faiss import read_text_files, build_index, load_index


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
