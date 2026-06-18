"""Central configuration management."""
import os
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DatabaseConfig:
    """Database connection configuration."""
    # DuckDB (default/local)
    duckdb_path: str = "data/analyst.db"

    # PostgreSQL
    pg_host: Optional[str] = None
    pg_port: int = 5432
    pg_database: Optional[str] = None
    pg_user: Optional[str] = None
    pg_password: Optional[str] = None

    # MySQL
    mysql_host: Optional[str] = None
    mysql_port: int = 3306
    mysql_database: Optional[str] = None
    mysql_user: Optional[str] = None
    mysql_password: Optional[str] = None

    # Connection pooling
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30

    # Query limits
    max_rows: int = 10000
    query_timeout: int = 60

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Load configuration from environment variables."""
        return cls(
            duckdb_path=os.getenv("DUCKDB_PATH", "data/analyst.db"),
            pg_host=os.getenv("PG_HOST"),
            pg_port=int(os.getenv("PG_PORT", "5432")),
            pg_database=os.getenv("PG_DATABASE"),
            pg_user=os.getenv("PG_USER"),
            pg_password=os.getenv("PG_PASSWORD"),
            mysql_host=os.getenv("MYSQL_HOST"),
            mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
            mysql_database=os.getenv("MYSQL_DATABASE"),
            mysql_user=os.getenv("MYSQL_USER"),
            mysql_password=os.getenv("MYSQL_PASSWORD"),
            max_rows=int(os.getenv("MAX_QUERY_ROWS", "10000")),
            query_timeout=int(os.getenv("QUERY_TIMEOUT", "60")),
        )


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    provider: str = "mock"  # "mock", "ollama", "vllm", "openai"
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model: str = "qwen3.6-27b"
    timeout: int = 30
    max_retries: int = 3
    temperature: float = 0.1

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            provider=os.getenv("LLM_PROVIDER", "mock"),
            api_url=os.getenv("LLM_API_URL"),
            api_key=os.getenv("LLM_API_KEY"),
            model=os.getenv("LLM_MODEL", "qwen3.6-27b"),
            timeout=int(os.getenv("LLM_TIMEOUT", "30")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        )


@dataclass
class SandboxConfig:
    """Code execution sandbox configuration."""
    use_docker: bool = False
    docker_image: str = "python:3.11-slim"
    runtime: str = "runc"  # or "runsc" for gVisor
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    timeout: int = 30
    max_output_size: int = 10 * 1024 * 1024  # 10MB

    @classmethod
    def from_env(cls) -> "SandboxConfig":
        return cls(
            use_docker=os.getenv("SANDBOX_USE_DOCKER", "false").lower() == "true",
            docker_image=os.getenv("SANDBOX_DOCKER_IMAGE", "python:3.11-slim"),
            runtime=os.getenv("SANDBOX_RUNTIME", "runc"),
            memory_limit=os.getenv("SANDBOX_MEMORY_LIMIT", "512m"),
            cpu_limit=float(os.getenv("SANDBOX_CPU_LIMIT", "1.0")),
            timeout=int(os.getenv("SANDBOX_TIMEOUT", "30")),
        )


@dataclass
class RAGConfig:
    """RAG system configuration."""
    provider: str = "simple"  # "simple", "pgvector"
    embedding_model: str = "BAAI/bge-m3"
    pgvector_host: Optional[str] = None
    pgvector_port: int = 5432
    pgvector_database: Optional[str] = None
    pgvector_user: Optional[str] = None
    pgvector_password: Optional[str] = None
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k: int = 5

    @classmethod
    def from_env(cls) -> "RAGConfig":
        return cls(
            provider=os.getenv("RAG_PROVIDER", "simple"),
            embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-m3"),
            pgvector_host=os.getenv("PGVECTOR_HOST"),
            pgvector_port=int(os.getenv("PGVECTOR_PORT", "5432")),
            pgvector_database=os.getenv("PGVECTOR_DATABASE"),
            pgvector_user=os.getenv("PGVECTOR_USER"),
            pgvector_password=os.getenv("PGVECTOR_PASSWORD"),
        )


@dataclass
class AppConfig:
    """Application-wide configuration."""
    db: DatabaseConfig = field(default_factory=DatabaseConfig.from_env)
    llm: LLMConfig = field(default_factory=LLMConfig.from_env)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig.from_env)
    rag: RAGConfig = field(default_factory=RAGConfig.from_env)

    # Rate limiting
    rate_limit_requests: int = 60
    rate_limit_window: int = 60  # seconds

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            rate_limit_requests=int(os.getenv("RATE_LIMIT_REQUESTS", "60")),
            rate_limit_window=int(os.getenv("RATE_LIMIT_WINDOW", "60")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_format=os.getenv("LOG_FORMAT", "json"),
        )
