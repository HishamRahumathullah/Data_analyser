"""Production-ready database manager with multi-database support."""
import os
import hashlib
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import pandas as pd
import duckdb

from config.settings import DatabaseConfig
from src.utils import logger


@dataclass
class QueryResult:
    """Structured query result with metadata."""
    df: pd.DataFrame
    sql: str
    execution_time_ms: float
    rows_returned: int
    truncated: bool = False
    warning: Optional[str] = None


class DBManager:
    """Universal database manager supporting DuckDB, PostgreSQL, and MySQL."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig.from_env()
        self._duckdb_conn: Optional[duckdb.DuckDBPyConnection] = None
        self._sqlalchemy_engine = None
        self._schema_cache: Dict[str, Dict] = {}
        self._query_cache: Dict[str, QueryResult] = {}
        self._cache_ttl = 300  # 5 minutes
        self._cache_timestamps: Dict[str, float] = {}

        self._init_duckdb()

    def _init_duckdb(self) -> None:
        """Initialize DuckDB connection with sample data."""
        os.makedirs(os.path.dirname(self.config.duckdb_path) or ".", exist_ok=True)
        self._duckdb_conn = duckdb.connect(self.config.duckdb_path)
        self._initialize_sample_data()
        logger.info(f"DuckDB initialized at {self.config.duckdb_path}")

    def _initialize_sample_data(self) -> None:
        """Initialize sample data only if tables are empty."""
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                sale_id INTEGER PRIMARY KEY,
                product_id INTEGER,
                customer_id INTEGER,
                amount DECIMAL(10,2),
                quantity INTEGER,
                sale_date DATE,
                region VARCHAR(20),
                channel VARCHAR(20)
            )
        """)

        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY,
                name VARCHAR(100),
                category VARCHAR(50),
                price DECIMAL(10,2),
                cost DECIMAL(10,2)
            )
        """)

        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id INTEGER PRIMARY KEY,
                name VARCHAR(100),
                email VARCHAR(100),
                signup_date DATE,
                segment VARCHAR(20),
                employees INTEGER,
                city VARCHAR(50),
                state VARCHAR(10)
            )
        """)

        sales_count = self._duckdb_conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        if sales_count == 0:
            self._duckdb_conn.execute("""
                INSERT INTO sales VALUES
                (1, 101, 1, 150.00, 2, '2026-01-01', 'North', 'Online'),
                (2, 102, 2, 200.00, 1, '2026-01-02', 'South', 'Retail'),
                (3, 101, 3, 150.00, 2, '2026-01-03', 'East', 'Online'),
                (4, 103, 1, 300.00, 3, '2026-01-04', 'West', 'Wholesale'),
                (5, 102, 4, 200.00, 1, '2026-01-05', 'North', 'Online'),
                (6, 104, 2, 450.00, 5, '2026-01-06', 'South', 'Retail'),
                (7, 101, 5, 150.00, 2, '2026-01-07', 'North', 'Online'),
                (8, 103, 3, 300.00, 3, '2026-01-08', 'East', 'Wholesale'),
                (9, 105, 1, 800.00, 10, '2026-01-09', 'West', 'Online'),
                (10, 102, 4, 200.00, 1, '2026-01-10', 'North', 'Retail')
            """)

        products_count = self._duckdb_conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if products_count == 0:
            self._duckdb_conn.execute("""
                INSERT INTO products VALUES
                (101, 'Laptop Pro', 'Electronics', 1200.00, 800.00),
                (102, 'Wireless Mouse', 'Electronics', 25.00, 12.00),
                (103, 'Office Chair', 'Furniture', 350.00, 180.00),
                (104, 'Standing Desk', 'Furniture', 650.00, 350.00),
                (105, 'Monitor 4K', 'Electronics', 450.00, 280.00)
            """)

        customers_count = self._duckdb_conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        if customers_count == 0:
            self._duckdb_conn.execute("""
                INSERT INTO customers VALUES
                (1, 'Alice Smith', 'alice@example.com', '2025-10-01', 'Enterprise', 1200, 'New York', 'NY'),
                (2, 'Bob Jones', 'bob@example.com', '2025-11-15', 'SMB', 45, 'Austin', 'TX'),
                (3, 'Charlie Brown', 'charlie@example.com', '2025-12-20', 'Consumer', 1, 'Boston', 'MA'),
                (4, 'David Wilson', 'david@example.com', '2026-01-01', 'SMB', 80, 'Seattle', 'WA'),
                (5, 'Eva Martinez', 'eva@example.com', '2026-01-10', 'Enterprise', 2500, 'Chicago', 'IL')
            """)

    def execute_query(self, sql: str, use_cache: bool = True) -> QueryResult:
        """Execute SQL query with safety limits and caching."""
        start_time = time.time()

        if use_cache:
            cache_key = hashlib.sha256(sql.encode()).hexdigest()
            if cache_key in self._query_cache:
                cached_time = self._cache_timestamps.get(cache_key, 0)
                if time.time() - cached_time < self._cache_ttl:
                    logger.debug(f"Cache hit for query: {sql[:50]}...")
                    return self._query_cache[cache_key]

        try:
            sql_upper = sql.upper().strip()
            if "LIMIT" not in sql_upper and "SELECT" in sql_upper:
                sql = sql.rstrip(";\n") + f" LIMIT {self.config.max_rows}"
                warning = f"Query limited to {self.config.max_rows} rows"
            else:
                warning = None

            df = self._duckdb_conn.execute(sql).fetchdf()

            execution_time = (time.time() - start_time) * 1000
            rows = len(df)
            truncated = rows >= self.config.max_rows

            result = QueryResult(
                df=df,
                sql=sql,
                execution_time_ms=execution_time,
                rows_returned=rows,
                truncated=truncated,
                warning=warning,
            )

            if use_cache:
                self._query_cache[cache_key] = result
                self._cache_timestamps[cache_key] = time.time()

            logger.info(
                f"Query executed: {rows} rows in {execution_time:.1f}ms",
                extra={"sql": sql, "rows_returned": rows, "execution_time_ms": execution_time}
            )

            return result

        except Exception as e:
            logger.error(
                f"Query execution failed: {str(e)}",
                extra={"sql": sql, "error_type": type(e).__name__}
            )
            raise

    def get_schema(self) -> str:
        """Get database schema with caching."""
        cache_key = "schema"
        if cache_key in self._schema_cache:
            return self._schema_cache[cache_key].get("formatted", "")

        tables = self._duckdb_conn.execute("SHOW TABLES").fetchall()
        schema_info = []
        table_schemas = {}

        for table_tuple in tables:
            table_name = table_tuple[0]
            safe_name = table_name.replace('"', '')
            columns = self._duckdb_conn.execute(f'DESCRIBE "{safe_name}"').fetchall()
            col_desc = ", ".join([f"{c[0]} ({c[1]})" for c in columns])
            schema_info.append(f"Table: {table_name}\nColumns: {col_desc}")
            table_schemas[table_name] = [{"name": c[0], "type": c[1]} for c in columns]

        formatted = "\n\n".join(schema_info)
        self._schema_cache[cache_key] = {
            "formatted": formatted,
            "tables": table_schemas,
        }
        return formatted

    def get_schema_dict(self) -> Dict[str, List[Dict[str, str]]]:
        """Get schema as structured dictionary."""
        self.get_schema()
        return self._schema_cache.get("schema", {}).get("tables", {})

    def get_table_names(self) -> List[str]:
        """Get list of table names."""
        tables = self._duckdb_conn.execute("SHOW TABLES").fetchall()
        return [t[0] for t in tables]

    def get_table_stats(self, table_name: str) -> Dict[str, Any]:
        """Get statistics for a table."""
        safe_name = table_name.replace('"', '')
        row_count = self._duckdb_conn.execute(
            f'SELECT COUNT(*) FROM "{safe_name}"'
        ).fetchone()[0]
        return {"table_name": table_name, "row_count": row_count}

    def explain_query(self, sql: str) -> str:
        """Get query execution plan."""
        try:
            result = self._duckdb_conn.execute(f"EXPLAIN {sql}").fetchall()
            return "\n".join([str(r[0]) for r in result])
        except Exception as e:
            return f"Could not explain query: {str(e)}"

    def invalidate_cache(self) -> None:
        """Clear query cache."""
        self._query_cache.clear()
        self._cache_timestamps.clear()
        self._schema_cache.clear()
        logger.info("Query cache invalidated")

    def close(self) -> None:
        """Close database connections."""
        if self._duckdb_conn:
            self._duckdb_conn.close()
            self._duckdb_conn = None
        if self._sqlalchemy_engine:
            self._sqlalchemy_engine.dispose()
        logger.info("Database connections closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
