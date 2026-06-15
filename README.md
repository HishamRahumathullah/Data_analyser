# AI Data Analyst Agent

A self-hosted, production-ready AI Data Analyst Agent designed for natural language data analysis and visualization.

## Overview

This agent automates 90% of data analyst work by:
- Converting natural language queries to safe SQL.
- Executing queries against a local DuckDB analytical engine.
- Generating and executing Python code for data visualization in a sandboxed environment.
- Using RAG to provide business logic and schema context.

## Architecture

- **Primary Model**: Qwen3.6-27B (optimized for 24GB VRAM)
- **Orchestration**: Custom LangChain-based state machine.
- **Database**: DuckDB (analytical) + PostgreSQL/pgvector (RAG).
- **UI**: Streamlit.
- **Safety**: SQLGlot for SQL validation + Docker/gVisor for Python sandboxing.

## Project Structure

```
.
├── src/
│   ├── agent/       # Core agent logic (Router, Planner, Coder, RAG, LLM Client)
│   ├── safety/      # SQL Safety Validator
│   ├── db/          # Database Manager (DuckDB)
│   └── ui/          # Streamlit UI
├── tests/           # Unit and E2E tests
├── data/            # Local data storage
└── requirements.txt  # Python dependencies
```

## Setup Instructions

### 1. Prerequisites
- Python 3.10+
- Docker (for sandboxed execution)
- (Optional) Ollama or vLLM for running local LLMs.

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Initialize Database
The database is automatically initialized with sample data upon the first run of the application or the DB manager.

### 4. Running the Agent
```bash
# Set PYTHONPATH to include the project root
export PYTHONPATH=$PYTHONPATH:.

# Start the Streamlit app
streamlit run src/ui/app.py
```

## Configuration

In `src/ui/app.py`, you can configure the LLM provider:
```python
llm_client = LLMClient(provider="mock") # Options: "mock", "ollama", "vllm"
```

If using "ollama" or "vllm", provide the `api_url` in the `LLMClient` constructor.

## Safety & Security

- **SQL Safety**: All generated SQL is parsed by `sqlglot` to ensure it only performs read-only operations on authorized tables.
- **Code Sandbox**: Python code for visualization is executed in a restricted environment. In production, it is highly recommended to use the Docker-based sandbox with gVisor (`runsc`).

## Testing

Run the test suite to verify the installation:
```bash
export PYTHONPATH=$PYTHONPATH:.
python3 -m unittest discover tests
python3 tests/e2e_verify.py
```

## License
MIT
