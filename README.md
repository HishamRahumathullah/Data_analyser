# AI Data Analyst Agent v2.0

A production-ready AI Data Analyst Agent with semantic layer, multi-agent insights, and secure sandboxed execution.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  FOUNDATION                                                         │
├─────────────────────────────────────────────────────────────────────┤
│  Config → Logging → DBManager → Validator → LLMClient → Router     │
│  → Planner → Coder → Sandbox                                        │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  SEMANTIC LAYER (Load-bearing wall)                                │
├─────────────────────────────────────────────────────────────────────┤
│  Metrics → Dimensions → Segments → SemanticQuery → SQL              │
│  Business logic lives here, not bolted on after                     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  CONNECTORS + VALIDATION                                            │
├─────────────────────────────────────────────────────────────────────┤
│  PostgreSQL/MySQL/DuckDB → Connection Pooling → ResultValidator    │
│  → QueryFeedback (self-improvement loop)                            │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  INSIGHTS + NARRATIVE (Multi-agent pipeline)                        │
├─────────────────────────────────────────────────────────────────────┤
│  DomainDetector → Trend/Anomaly/Compare Agents → Synthesizer       │
│  → Narrative Generator → Stakeholder Formatter                      │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  DASHBOARD + UI                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  Semantic Chart Binding → Grid Layout → Cross-Filtering            │
│  → Export Pipeline → FastAPI API → Streamlit UI                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Three Capabilities

### 1. SQL (Structured Query Language)
- **Semantic query resolution**: LLM queries metrics/dimensions, not raw tables
- **Multi-database support**: DuckDB, PostgreSQL, MySQL with SQLAlchemy pooling
- **Query safety**: AST-based validation with DuckDB dialect support
- **Result validation**: Automatic detection of empty results, outliers, Cartesian products

### 2. Data Visualization & BI Tools
- **Semantic chart binding**: Charts reference business metrics, not raw SQL
- **Dashboard builder**: Multi-chart layouts with shared filters
- **Export pipeline**: PNG, SVG, HTML export
- **Chart types**: Bar, Line, Pie, Scatter, Table, KPI cards

### 3. Business Context & Data Storytelling
- **Multi-agent insight pipeline**: Domain detection, trend analysis, anomaly detection, comparison
- **Narrative generation**: Executive summaries with "so what?" analysis
- **Stakeholder formatting**: CEO (1-2 sentences), Manager (paragraph), Analyst (detailed), Engineer (technical)
- **Feedback loop**: Query success tracking with user ratings for continuous improvement

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the API Server
```bash
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Start the Streamlit UI
```bash
streamlit run src/ui/app.py
```

### 4. Run Tests
```bash
pytest tests/test_all.py -v
```

## Configuration

All configuration is via environment variables:

```bash
# Database
export DUCKDB_PATH="data/analyst.db"
export PG_HOST="localhost"
export PG_DATABASE="analytics"
export PG_USER="analyst"
export PG_PASSWORD="secret"

# LLM
export LLM_PROVIDER="openai"  # mock, ollama, vllm, openai
export LLM_API_KEY="sk-..."
export LLM_MODEL="gpt-4"

# Rate Limiting
export RATE_LIMIT_REQUESTS="60"

# Logging
export LOG_LEVEL="INFO"
export LOG_FORMAT="json"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/schema` | GET | Database + semantic schema |
| `/query` | POST | Process natural language query |
| `/feedback` | POST | Submit user feedback |
| `/feedback/stats` | GET | Feedback statistics |
| `/dashboard/create` | POST | Create dashboard |

## Security

- **Subprocess sandbox**: Code runs in isolated process, not `exec()`
- **AST-based SQL validation**: No regex false positives
- **Prompt injection detection**: Router scans for injection patterns
- **Rate limiting**: Per-IP request limits
- **Query result limits**: Automatic `LIMIT` enforcement
- **System table protection**: Blocks `information_schema`, `pg_catalog`

## License
MIT
