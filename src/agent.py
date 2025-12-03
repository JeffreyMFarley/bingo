#!/usr/bin/env python3
"""train_agent.py - simple scaffold for building a FAISS index and querying with OpenAI.

This is a lightweight, opinionated starting point. Update model names and glue code
according to your project's requirements.
"""
from langfuse import get_client
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

from src.retriever_faiss import query_index

def query_index_and_generate(query, index, docs, embed_model_name, top_k, openai_model, openai_key):
    if OpenAI is None:
        raise RuntimeError("openai package is required. Install from requirements.txt")
    client = OpenAI(api_key=openai_key)

    try:
        langfuse_cli = get_client()
    except Exception:
        print("Langfuse client initialization failed. Make sure LANGFUSE keys are set in .env.")
        langfuse_cli = None

    retrieved, context = query_index(query, index, docs, embed_model_name, top_k)
    system = "You are an assistant that answers using the provided context. If the answer is not in the context, say you don't know and be concise."
    prompt = f"CONTEXT:\n{context}\n\nQUESTION: {query}\n\nAnswer concisely:"

    with langfuse_cli.start_as_current_observation(
        as_type="generation",
        name="call-llm",
        model=openai_model,
        input={"prompt": prompt, "system": system},
        model_parameters={"temperature": 0.0}
    ) as span:
        try:
            resp = client.chat.completions.create(model=openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=512,
            temperature=0.0)
            span.update(output={"response": resp.choices[0].message.content})
        except Exception as e:
            span.update(error={"message": str(e)})
            raise
        finally:
            langfuse_cli.flush()

    return resp.choices[0].message.content.strip(), retrieved
