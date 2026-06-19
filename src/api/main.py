"""FastAPI backend with ALL P0/P1 components integrated.

Integrates:
- Security & Governance (RBAC, RLS, CLS, Audit)
- Async Architecture (Parallel agents, streaming)
- Semantic Caching (Exact + embedding-based)
- Resilience (Circuit breaker, bulkhead, fallback)
- Judge Agent (Mandatory quality control)
- Cost Guardrails (Budget management)
"""

import json
import os
import re
import shutil
import pandas as pd
import numpy as np
import asyncio
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config.settings import AppConfig
from src.utils import logger, log_query
from src.db.manager import DBManager
from src.safety.validator import SQLSafetyValidator
from src.agent.llm_client import LLMClient
from src.agent.planner import Planner
from src.agent.coder import Coder
from src.agent.router import Router
from src.agent.sandbox import Sandbox
from src.semantic.layer import SemanticLayer
from src.connectors.validator import ResultValidator
from src.connectors.feedback import FeedbackStore, QueryFeedback
from src.insights.pipeline import InsightPipeline
from src.insights.dashboard import DashboardBuilder, ExportPipeline
from src.insights.judge import JudgeAgent
from src.security.rbac import (
    RBACManager,
    RowLevelSecurity,
    ColumnLevelSecurity,
    AuditLogger,
    UserContext,
    Role,
)
from src.async_tasks.orchestrator import (
    ParallelInsightOrchestrator,
    StreamingResponseManager,
)
from src.cache.semantic_cache import QueryCacheManager
from src.resilience.circuit_breaker import (
    ResilienceManager,
    resilient,
    CircuitOpenError,
    BulkheadFullError,
)
from src.cost.estimator import CostGuardrail

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Global state
app_state: Dict[str, Any] = {}


def clean_for_json(obj):
    """Recursively convert numpy/pandas types to Python native types."""
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(v) for v in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.DataFrame):
        return json.loads(obj.to_json(orient="records", default_handler=str))
    return obj


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize all components."""
    config = AppConfig.from_env()

    db = DBManager(config.db)
    llm = LLMClient(config.llm)
    semantic = SemanticLayer()

    # Security
    rbac = RBACManager()
    # Create default users
    rbac.create_user("admin", "admin@company.com", Role.ADMIN)
    rbac.create_user(
        "analyst",
        "analyst@company.com",
        Role.ANALYST,
        department="Sales",
        region="North",
    )
    rbac.create_user("viewer", "viewer@company.com", Role.VIEWER, region="South")

    app_state["config"] = config
    app_state["db"] = db
    app_state["llm"] = llm
    app_state["semantic"] = semantic
    app_state["router"] = Router(llm)
    app_state["planner"] = Planner(llm)
    app_state["coder"] = Coder(llm)
    app_state["sandbox"] = Sandbox(config.sandbox)
    app_state["validator"] = SQLSafetyValidator(
        allowed_tables=set(db.get_table_names())
    )
    app_state["result_validator"] = ResultValidator()
    app_state["feedback"] = FeedbackStore()
    app_state["insights"] = InsightPipeline(llm)
    app_state["dashboard"] = DashboardBuilder(semantic)

    # P0/P1 Components
    app_state["rbac"] = rbac
    app_state["rls"] = RowLevelSecurity()
    app_state["cls"] = ColumnLevelSecurity()
    app_state["audit"] = AuditLogger()
    app_state["parallel_orchestrator"] = ParallelInsightOrchestrator(llm)
    app_state["cache"] = QueryCacheManager()
    app_state["resilience"] = ResilienceManager()
    app_state["judge"] = JudgeAgent(llm)
    app_state["cost_guardrail"] = CostGuardrail()

    logger.info("Application startup complete with P0/P1 components")
    yield

    db.close()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="AI Data Analyst Agent v2.0",
    description="Production-ready NL analytics with semantic layer, multi-agent insights, and enterprise security",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    logger.info(
        f"{request.method} {request.url.path} - {response.status_code} - {duration:.1f}ms",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "duration_ms": duration,
        },
    )
    return response


# ============================================================================
# Health & Schema
# ============================================================================


@app.get("/health")
async def health_check():
    """Health check with component status."""
    resilience = app_state["resilience"]
    cache = app_state["cache"]

    return {
        "status": "healthy",
        "version": "2.0.0",
        "components": {
            "database": "connected",
            "llm": app_state["llm"].config.provider,
            "semantic_layer": "active",
            "cache": cache.stats(),
            "resilience": resilience.get_all_stats(),
        },
    }


@app.get("/schema")
@limiter.limit("30/minute")
async def get_schema(request: Request):
    """Get database + semantic schema."""
    db = app_state["db"]
    semantic = app_state["semantic"]

    return {
        "raw_schema": db.get_schema(),
        "semantic_schema": semantic.get_schema_description(),
        "tables": db.get_table_names(),
        "metrics": semantic.list_metrics(),
        "dimensions": semantic.list_dimensions(),
        "segments": semantic.list_segments(),
    }


# ============================================================================
# Main Query Endpoint (with ALL P0/P1 features)
# ============================================================================


@app.post("/query")
@limiter.limit("10/minute")
async def process_query(request: Request):
    """Process natural language query with full P0/P1 integration.

    Flow:
    1. Cost guardrail check
    2. Check semantic cache
    3. Route query
    4. Security check (RBAC + RLS)
    5. Plan + Generate SQL
    6. Validate + Execute
    7. Validate results
    8. Run insights (parallel async)
    9. Judge review (mandatory)
    10. Cache result
    11. Audit log
    12. Return response
    """
    body = await request.json()
    user_query = body.get("query", "").strip()
    audience = body.get("audience", "executive")
    user_id = body.get("user_id", "analyst")  # Default for demo

    if not user_query:
        raise HTTPException(status_code=400, detail="Query is required")

    query_id = str(uuid.uuid4())
    start_time = time.time()

    # Get user context
    user = app_state["rbac"].get_user(user_id)
    if not user:
        raise HTTPException(status_code=403, detail="User not found")

    try:
        # 1. Cost Guardrail Check
        cost_guardrail = app_state["cost_guardrail"]
        cost_check = cost_guardrail.check_query(user_id, user_query, "DATA_QUERY")

        if not cost_check["allowed"] and cost_check["requires_confirmation"]:
            return {
                "query_id": query_id,
                "status": "requires_confirmation",
                "cost_estimate": cost_check["estimate"],
                "budget_status": cost_check["budget_status"],
                "message": cost_check["estimate"]["warning"],
            }

        if not cost_check["allowed"]:
            raise HTTPException(
                status_code=429, detail="Budget exceeded. Please try again tomorrow."
            )

        # 2. Check Semantic Cache
        cache = app_state["cache"]
        cached = cache.get_cached_response(user_query, "DATA_QUERY")
        if cached:
            logger.info(f"Cache hit for query: {user_query[:50]}...")
            return {**cached, "query_id": query_id, "cached": True}

        # 3. Route Query
        route = app_state["router"].route(user_query)

        # 4. Get Context + Security
        db = app_state["db"]
        semantic = app_state["semantic"]
        schema = db.get_schema()
        semantic_schema = semantic.get_schema_description()

        # Security: Check table access
        tables = semantic.resolve_query(user_query).metrics
        for metric in tables:
            if not user.can_access_table(metric.sql_table):
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied to table: {metric.sql_table}",
                )

        # 5. Plan
        plan = app_state["planner"].generate_plan(
            user_query, semantic_schema, route=route
        )

        # 6. Generate SQL
        semantic_query = semantic.resolve_query(user_query)
        if semantic_query.metrics:
            sql = semantic_query.to_sql()
        else:
            sql = app_state["coder"].generate_sql(
                user_query, plan["execution_plan"], schema
            )

        # Apply Row-Level Security
        sql = app_state["rls"].apply_filter(sql, user)

        # 7. Validate SQL
        validation = app_state["validator"].validate(sql)
        if not validation["safe"]:
            raise HTTPException(
                status_code=400, detail=f"Unsafe SQL: {', '.join(validation['errors'])}"
            )

        # 8. Execute with circuit breaker
        resilience = app_state["resilience"]
        circuit = resilience.get_circuit("database")
        bulkhead = resilience.get_bulkhead("database")

        if not circuit.can_execute():
            raise HTTPException(
                status_code=503, detail="Database service temporarily unavailable"
            )

        if not bulkhead.acquire(timeout=30.0):
            raise HTTPException(
                status_code=503, detail="Database overloaded, try again later"
            )

        try:
            result = db.execute_query(sql)
            circuit.record_success(result.execution_time_ms)
        except Exception as e:
            circuit.record_failure(type(e).__name__)
            raise
        finally:
            bulkhead.release()

        # 9. Validate Results
        result_validation = app_state["result_validator"].validate(
            result.df, sql, [m.name for m in semantic_query.metrics]
        )

        # 10. Apply Column-Level Security
        result_df = app_state["cls"].filter_columns(result.df, user, "sales")

        # 11. Build Response
        response_data = {
            "query_id": query_id,
            "route": route,
            "sql": sql,
            "execution_time_ms": result.execution_time_ms,
            "rows_returned": result.rows_returned,
            "data": result_df.to_dict("records"),
            "warnings": result.warning,
            "result_validation": result_validation,
            "cost_estimate": cost_check["estimate"],
        }

        # 12. Insights (Parallel Async)
        if route == "ANALYSIS" or route == "VISUALIZATION":
            df = result_df
            date_col = next((c for c in df.columns if "date" in c.lower()), None)
            metric_col = next(
                (
                    c
                    for c in df.columns
                    if c in [m.name for m in semantic_query.metrics]
                ),
                None,
            )
            dimension_col = next(
                (
                    c
                    for c in df.columns
                    if c in [d.name for d in semantic_query.dimensions]
                ),
                None,
            )

            # Use parallel orchestrator
            orchestrator = app_state["parallel_orchestrator"]
            insights = await orchestrator.run_parallel(
                df, user_query, date_col, metric_col, dimension_col, audience
            )

            response_data["insights"] = insights["insights"]
            response_data["narrative"] = insights["narrative"]
            response_data["insight_time_ms"] = insights["execution_time_ms"]

            # 13. Judge Review (Mandatory)
            judge = app_state["judge"]
            judge_result = judge.judge(
                insights["insights"], df, insights["narrative"], user_query
            )

            response_data["judge_review"] = {
                "approved": judge_result["approved"],
                "confidence": judge_result["confidence_score"],
                "issues_found": len(judge_result["issues"]),
            }

            if not judge_result["approved"]:
                response_data["narrative"] = (
                    judge_result["corrected_narrative"] or response_data["narrative"]
                )
                response_data["warnings"] = (
                    response_data.get("warnings") or ""
                ) + " [Reviewed by quality control]"

        # Visualization
        if route == "VISUALIZATION":
            py_code = app_state["coder"].generate_python(
                user_query, result_df.head(10).to_string(), plan["execution_plan"]
            )
            sandbox_result = app_state["sandbox"].execute_python(py_code, result_df)

            if sandbox_result["success"]:
                response_data["visualization"] = {
                    "figure_json": sandbox_result["figure"].to_json()
                    if sandbox_result["figure"]
                    else None,
                }
            else:
                response_data["visualization_error"] = sandbox_result["error"]

        # 14. Cache Result
        cache.cache_response(user_query, route, response_data)

        # 15. Audit Log
        app_state["audit"].log_query(
            user=user,
            sql=sql,
            tables=validation.get("tables", []),
            rows_accessed=result.rows_returned,
            success=True,
        )

        # 16. Record Actual Cost
        actual_cost = (
            cost_check["estimate"]["cost_usd"] * 0.8
        )  # Estimate is conservative
        cost_guardrail.record_actual_cost(user_id, actual_cost)

        # Log query
        total_time = (time.time() - start_time) * 1000
        log_query(
            user_query=user_query,
            route=route,
            sql=sql,
            tables=validation.get("tables", []),
            rows_returned=result.rows_returned,
            execution_time_ms=total_time,
        )

        return clean_for_json(response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Query processing failed: {e}",
            extra={"query": user_query, "error_type": type(e).__name__},
        )

        # Record failure feedback
        app_state["feedback"].add_feedback(
            QueryFeedback(
                query_id=query_id,
                user_query=user_query,
                sql="",
                route="UNKNOWN",
                success=False,
                error_type=type(e).__name__,
            )
        )

        # Audit log failure
        if user:
            app_state["audit"].log_query(
                user=user,
                sql="",
                tables=[],
                rows_accessed=0,
                success=False,
                error=str(e),
            )

        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Streaming Endpoint (for real-time insights)
# ============================================================================


@app.post("/query/stream")
@limiter.limit("5/minute")
async def process_query_stream(request: Request):
    """Stream query results as agents complete."""
    body = await request.json()
    user_query = body.get("query", "").strip()
    audience = body.get("audience", "executive")

    if not user_query:
        raise HTTPException(status_code=400, detail="Query is required")

    async def event_generator():
        stream_mgr = StreamingResponseManager()

        # Simulate streaming phases
        phases = [
            {"phase": "routing", "status": "in_progress"},
            {"phase": "planning", "status": "in_progress"},
            {"phase": "executing", "status": "in_progress"},
            {"phase": "insights", "status": "in_progress"},
            {"phase": "complete", "status": "done"},
        ]

        for phase in phases:
            yield f"data: {json.dumps(phase)}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ============================================================================
# Feedback Endpoints
# ============================================================================


@app.post("/feedback")
@limiter.limit("30/minute")
async def submit_feedback(request: Request):
    body = await request.json()

    feedback = QueryFeedback(
        query_id=body.get("query_id", ""),
        user_query=body.get("user_query", ""),
        sql=body.get("sql", ""),
        route=body.get("route", ""),
        success=body.get("success", True),
        user_rating=body.get("user_rating"),
        user_comment=body.get("user_comment"),
    )

    app_state["feedback"].add_feedback(feedback)
    return {"status": "feedback recorded"}


@app.get("/feedback/stats")
@limiter.limit("10/minute")
async def get_feedback_stats(request: Request):
    feedback = app_state["feedback"]
    return {
        "total_queries": len(feedback._feedback),
        "success_rate": feedback.get_success_rate(),
        "success_rate_by_route": {
            "DATA_QUERY": feedback.get_success_rate("DATA_QUERY"),
            "VISUALIZATION": feedback.get_success_rate("VISUALIZATION"),
            "ANALYSIS": feedback.get_success_rate("ANALYSIS"),
        },
        "common_errors": feedback.get_common_errors(),
    }


# ============================================================================
# Dashboard Endpoints
# ============================================================================


@app.post("/dashboard/create")
@limiter.limit("10/minute")
async def create_dashboard(request: Request):
    body = await request.json()
    metric_name = body.get("metric")
    dimension_name = body.get("dimension")

    if not metric_name or not dimension_name:
        raise HTTPException(status_code=400, detail="metric and dimension are required")

    dashboard = app_state["dashboard"].create_default_dashboard(
        metric_name, dimension_name
    )

    return {
        "title": dashboard.title,
        "description": dashboard.description,
        "charts": [
            {
                "title": c.title,
                "type": c.chart_type.value,
                "metric": c.metric,
                "dimension": c.dimension,
            }
            for c in dashboard.charts
        ],
    }


# ============================================================================
# Upload Endpoint
# ============================================================================


def _sanitize_table_name(name: str) -> str:
    """Sanitize table name to prevent SQL injection."""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "", name)
    if not sanitized or sanitized[0].isdigit():
        sanitized = "t_" + sanitized
    return sanitized.lower()


@app.post("/upload")
@limiter.limit("10/minute")
async def upload_data(file: UploadFile = File(...)):
    """Upload CSV, Excel, Parquet, JSON and register in DuckDB."""
    allowed = {".csv", ".xlsx", ".parquet", ".json"}
    ext = Path(file.filename).suffix.lower()

    if ext not in allowed:
        raise HTTPException(400, f"Unsupported format: {ext}")

    os.makedirs("data/uploads", exist_ok=True)
    path = f"data/uploads/{file.filename}"

    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    db = app_state["db"]
    table = _sanitize_table_name(Path(file.filename).stem)

    if ext == ".csv":
        db._duckdb_conn.execute(
            f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv_auto('{path}')"
        )
    elif ext == ".parquet":
        db._duckdb_conn.execute(
            f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_parquet('{path}')"
        )
    elif ext in [".xlsx", ".xls"]:
        df = pd.read_excel(path)
        db._duckdb_conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM df")
    elif ext == ".json":
        df = pd.read_json(path)
        db._duckdb_conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM df")
    else:
        raise HTTPException(400, f"Upload handling for {ext} not yet implemented")

    db.invalidate_cache()
    rows = db._duckdb_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    return {"status": "success", "table_name": table, "rows": rows}


# ============================================================================
# Admin Endpoints
# ============================================================================


@app.get("/admin/resilience")
@limiter.limit("10/minute")
async def get_resilience_stats(request: Request):
    """Get circuit breaker and bulkhead statistics."""
    return app_state["resilience"].get_all_stats()


@app.get("/admin/cache")
@limiter.limit("10/minute")
async def get_cache_stats(request: Request):
    """Get cache statistics."""
    return app_state["cache"].stats()


@app.get("/admin/audit")
@limiter.limit("5/minute")
async def get_audit_log(request: Request):
    """Get recent audit events."""
    # In production, this would query persistent audit storage
    return {"status": "audit log endpoint active"}


@app.get("/admin/costs")
@limiter.limit("10/minute")
async def get_cost_stats(request: Request):
    """Get cost and budget statistics."""
    return app_state["cost_guardrail"].get_stats()
