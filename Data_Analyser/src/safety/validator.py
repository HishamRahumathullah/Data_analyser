"""Production SQL safety validator with DuckDB dialect support."""
import sqlglot
from sqlglot import exp
from typing import Set, Dict, List, Optional

from src.utils import logger, log_security_event


class SQLSafetyValidator:
    """Validates SQL queries for safety using AST analysis.

    Uses sqlglot for parse-tree validation instead of regex to avoid
    false positives on comments and string literals.
    """

    # Read-only operations allowed
    ALLOWED_COMMANDS = {
        "SELECT", "WITH", "EXPLAIN", "DESCRIBE", "SHOW", "PRAGMA"
    }

    # Forbidden operations (DDL, DML that modifies data)
    FORBIDDEN_COMMANDS = {
        "DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT",
        "REVOKE", "INSERT", "UPDATE", "MERGE", "CREATE", "REPLACE"
    }

    # System tables that should not be accessible
    FORBIDDEN_TABLES = {
        "information_schema", "pg_catalog", "sqlite_master",
        "sqlite_temp_master", "sys", "mysql"
    }

    # Potentially dangerous functions
    FORBIDDEN_FUNCTIONS = {
        "pg_sleep", "benchmark", "sleep", "xp_cmdshell",
        "sp_oamethod", "sp_oacreate", "load_file", "into_outfile"
    }

    def __init__(self, allowed_tables: Optional[Set[str]] = None, read_only: bool = True):
        self.allowed_tables = {t.lower() for t in (allowed_tables or set())}
        self.read_only = read_only
        self.dialect = "duckdb"

    def validate(self, query: str) -> Dict:
        """Validate SQL query for safety.

        Returns dict with:
            - safe: bool
            - errors: List[str]
            - tables: List[str]
            - warnings: List[str]
            - command_type: Optional[str]
        """
        result = {
            'safe': False,
            'errors': [],
            'warnings': [],
            'tables': [],
            'command_type': None
        }

        if not query or not query.strip():
            result['errors'].append("Empty query")
            return result

        try:
            # Parse with DuckDB dialect
            parsed = sqlglot.parse(query, read=self.dialect)

            if not parsed or not parsed[0]:
                result['errors'].append("Failed to parse SQL query")
                return result

            # Check for multiple statements (potential injection)
            if len(parsed) > 1:
                result['errors'].append("Multiple SQL statements not allowed")
                return result

            for stmt in parsed:
                # Determine command type
                cmd_type = self._get_command_type(stmt)
                result['command_type'] = cmd_type

                # Validate command is allowed
                if cmd_type not in self.ALLOWED_COMMANDS:
                    if cmd_type in self.FORBIDDEN_COMMANDS:
                        result['errors'].append(f"Forbidden operation: {cmd_type}")
                    else:
                        result['errors'].append(f"Unknown/unsupported operation: {cmd_type}")

                # Extract and validate tables
                tables = self._extract_tables(stmt)
                result['tables'] = list(tables)

                for table in tables:
                    table_lower = table.lower()
                    if table_lower in self.FORBIDDEN_TABLES:
                        result['errors'].append(f"Forbidden system table: {table}")
                    elif self.allowed_tables and table_lower not in self.allowed_tables:
                        result['errors'].append(f"Unauthorized table: {table}")

                # Check for forbidden functions
                functions = self._extract_functions(stmt)
                for func in functions:
                    if func.lower() in self.FORBIDDEN_FUNCTIONS:
                        result['errors'].append(f"Forbidden function: {func}")

                # Check for INTO OUTFILE / LOAD_FILE patterns
                if self._has_file_operations(stmt):
                    result['errors'].append("File operations not allowed")

                # Check for UNION-based injection patterns
                if self._has_dangerous_union(stmt):
                    result['warnings'].append("UNION query detected - verify intent")

                # Check subqueries for unauthorized tables
                subquery_tables = self._extract_subquery_tables(stmt)
                for sq_table in subquery_tables:
                    if sq_table.lower() in self.FORBIDDEN_TABLES:
                        result['errors'].append(f"Forbidden table in subquery: {sq_table}")
                    elif self.allowed_tables and sq_table.lower() not in self.allowed_tables:
                        result['errors'].append(f"Unauthorized table in subquery: {sq_table}")

            result['safe'] = len(result['errors']) == 0

            if result['safe'] and result['warnings']:
                logger.warning(f"SQL query passed with warnings: {result['warnings']}")

            return result

        except sqlglot.errors.ParseError as e:
            result['errors'].append(f"SQL parse error: {str(e)}")
            log_security_event(
                "sql_parse_failure",
                {"query": query[:100], "error": str(e)}
            )
            return result
        except Exception as e:
            result['errors'].append(f"Validation error: {str(e)}")
            logger.error(f"Unexpected validation error: {e}", extra={"query": query[:100]})
            return result

    def _get_command_type(self, stmt) -> Optional[str]:
        """Extract the command type from a parsed statement."""
        if isinstance(stmt, exp.Select):
            return "SELECT"
        elif isinstance(stmt, exp.Create):
            return "CREATE"
        elif isinstance(stmt, exp.Drop):
            return "DROP"
        elif isinstance(stmt, exp.Insert):
            return "INSERT"
        elif isinstance(stmt, exp.Update):
            return "UPDATE"
        elif isinstance(stmt, exp.Delete):
            return "DELETE"
        elif isinstance(stmt, exp.Alter):
            return "ALTER"
        elif isinstance(stmt, exp.Explain):
            return "EXPLAIN"
        elif isinstance(stmt, exp.Describe):
            return "DESCRIBE"
        elif isinstance(stmt, exp.Show):
            return "SHOW"
        elif isinstance(stmt, exp.Query) and stmt.find(exp.With):
            return "WITH"
        else:
            # Try to get from statement type name
            return type(stmt).__name__.upper()

    def _extract_tables(self, stmt) -> Set[str]:
        """Extract all table names from a statement."""
        tables = set()
        for table in stmt.find_all(exp.Table):
            if table.name:
                tables.add(table.name)
        return tables

    def _extract_functions(self, stmt) -> Set[str]:
        """Extract all function calls from a statement."""
        functions = set()
        for func in stmt.find_all(exp.Anonymous):
            if func.this:
                functions.add(str(func.this))
        for func in stmt.find_all(exp.Func):
            if hasattr(func, 'name'):
                functions.add(func.name)
        return functions

    def _has_file_operations(self, stmt) -> bool:
        """Check for file-related operations."""
        query_str = str(stmt).upper()
        file_patterns = ["INTO OUTFILE", "LOAD_FILE", "BULK INSERT", "COPY"]
        return any(pattern in query_str for pattern in file_patterns)

    def _has_dangerous_union(self, stmt) -> bool:
        """Check for potentially dangerous UNION patterns."""
        unions = list(stmt.find_all(exp.Union))
        return len(unions) > 0

    def _extract_subquery_tables(self, stmt) -> Set[str]:
        """Extract tables from subqueries and CTEs."""
        tables = set()
        for subquery in stmt.find_all(exp.Subquery):
            for table in subquery.find_all(exp.Table):
                if table.name:
                    tables.add(table.name)
        for cte in stmt.find_all(exp.CTE):
            for table in cte.find_all(exp.Table):
                if table.name:
                    tables.add(table.name)
        return tables
