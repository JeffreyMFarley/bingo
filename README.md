bingo - OpenAI agent training scaffold

This folder contains a minimal scaffold to start building a training / RAG pipeline that uses OpenAI for generation and a local FAISS vector store for retrieval.

Files added:
- `train_agent.py` — entrypoint and trainer/runner skeleton
- `config.yaml` — configuration example
- `.env.example` — environment variables example (do NOT commit secrets)
- `requirements.txt` — Python dependency list
- `.gitignore` — ignores typical artifacts

Quick start

1. Copy `.env.example` to `.env` and set `OPENAI_API_KEY`.
2. Create a `data/` directory in this folder and put plaintext documents (`.txt`) you want to index.
3. Create a virtualenv and install requirements:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

4. Build the index and run an interactive query:

```bash
python train_agent.py --build-index
python train_agent.py --query "Your question here"
```

This is a scaffold — update the model names and integration points to match your OpenAI plan or project conventions.

## Excel analysis agent

The `excel_agent.py` entrypoint inspects `.xlsx` workbooks and emits a JSON summary of sheets, detected tables, and inferred relational intent (primary keys, foreign keys, enums, etc.).

```bash
python excel_agent.py --workbook data/example.xlsx --pretty
```

Key flags:

- `--db-agent-version`: stamp a semantic version string into the output.
- `--sample-values`: limit per-column sample values in the JSON.
- `--enum-threshold`: tweak how aggressively enum warnings are emitted.
- `--output`: optional path to save the JSON blob (otherwise prints to stdout).
