#!/usr/bin/env python3

import asyncio
import os
import argparse

from dotenv import load_dotenv
import yaml

from src.agent import query_index_and_generate
from src.retriever_llama import RetrieverLlama


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def main():
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

    retriever = RetrieverLlama(top_k=top_k, name="bingo")

    if args.build_index:
        await retriever.build_index(data_dir)
        return

    if args.query:
        if not retriever.index_exists():
            print("Index or docs not found. Run with --build-index first.")
            return
        if not openai_key:
            print("OPENAI_API_KEY not set. Copy .env.example to .env and set your key.")
            return
        
        answer, retrieved = query_index_and_generate(args.query, retriever, openai_model, openai_key)
        print("\n--- Answer ---\n")
        print(answer)
        return

    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main()) 