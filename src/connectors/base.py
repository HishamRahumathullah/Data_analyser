"""Database connectors with connection pooling and schema discovery."""
import os
from typing import Optional, List, Dict, Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.pool import QueuePool
import pandas as pd

from config.settings import DatabaseConfig
from src.utils import logger


class DatabaseConnector:
    """Universal database connector with connection pooling."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig.from_env()
        self._engines: Dict[str, Any] = {}

    def get_duckdb_engine(self):
        """Get or create DuckDB engine."""
        if "duckdb" not in self._engines:
            os.makedirs(os.path.dirname(self.config.duckdb_path) or ".", exist_ok=True)
            self._engines["duckdb"] = create_engine(
                f"duckdb:///{self.config.duckdb_path}",
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
            )
        return self._engines["duckdb"]

    def get_postgres_engine(self):
        """Get or create PostgreSQL engine."""
        if "postgres" not in self._engines:
            if not all([self.config.pg_host, self.config.pg_database, self.config.pg_user]):
                raise ConnectionError("PostgreSQL configuration incomplete")

            password = quote_plus(self.config.pg_password or "")
            url = f"postgresql://{self.config.pg_user}:{password}@{self.config.pg_host}:{self.config.pg_port}/{self.config.pg_database}"
            self._engines["postgres"] = create_engine(
                url,
                poolclass=QueuePool,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_timeout=self.config.pool_timeout,
            )
        return self._engines["postgres"]

    def get_mysql_engine(self):
        """Get or create MySQL engine."""
        if "mysql" not in self._engines:
            if not all([self.config.mysql_host, self.config.mysql_database, self.config.mysql_user]):
                raise ConnectionError("MySQL configuration incomplete")

            password = quote_plus(self.config.mysql_password or "")
            url = f"mysql+pymysql://{self.config.mysql_user}:{password}@{self.config.mysql_host}:{self.config.mysql_port}/{self.config.mysql_database}"
            self._engines["mysql"] = create_engine(
                url,
                poolclass=QueuePool,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_timeout=self.config.pool_timeout,
            )
        return self._engines["mysql"]

    def discover_schema(self, db_type: str = "duckdb") -> Dict[str, List[Dict]]:
        """Discover database schema automatically."""
        engine = self._get_engine(db_type)
        inspector = inspect(engine)
        schema = {}

        for table_name in inspector.get_table_names():
            columns = inspector.get_columns(table_name)
            schema[table_name] = [
                {"name": col["name"], "type": str(col["type"]), "nullable": col.get("nullable", True)}
                for col in columns
            ]

        logger.info(f"Discovered schema for {db_type}: {list(schema.keys())}")
        return schema

    def execute(self, sql: str, db_type: str = "duckdb") -> pd.DataFrame:
        """Execute SQL and return DataFrame."""
        engine = self._get_engine(db_type)
        with engine.connect() as conn:
            return pd.read_sql(text(sql), conn)

    def _get_engine(self, db_type: str):
        if db_type == "duckdb":
            return self.get_duckdb_engine()
        elif db_type == "postgres":
            return self.get_postgres_engine()
        elif db_type == "mysql":
            return self.get_mysql_engine()
        else:
            raise ValueError(f"Unknown database type: {db_type}")

    def close_all(self):
        """Close all connections."""
        for name, engine in self._engines.items():
            engine.dispose()
            logger.info(f"Closed {name} connection pool")
        self._engines.clear()
