"""Role-Based Access Control (RBAC) for the semantic layer.

Implements:
- User roles and permissions
- Row-level security (RLS) — users see only their data rows
- Column-level security (CLS) — users see only authorized columns
- Object-level security — table/view access control
- Audit logging for all data access
"""
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import hashlib

from src.utils import logger, log_security_event


class Permission(Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class Role(Enum):
    VIEWER = "viewer"          # Can read aggregated data only
    ANALYST = "analyst"        # Can read raw data, create analysis
    MANAGER = "manager"        # Can read all data in their department
    ADMIN = "admin"            # Full access


@dataclass
class UserContext:
    """User identity and authorization context."""
    user_id: str
    email: str
    role: Role
    department: Optional[str] = None
    region: Optional[str] = None
    allowed_tables: Set[str] = field(default_factory=set)
    allowed_columns: Dict[str, Set[str]] = field(default_factory=dict)
    denied_metrics: Set[str] = field(default_factory=set)

    def can_access_table(self, table: str) -> bool:
        if self.role == Role.ADMIN:
            return True
        return table.lower() in {t.lower() for t in self.allowed_tables}

    def can_access_column(self, table: str, column: str) -> bool:
        if self.role == Role.ADMIN:
            return True
        table_cols = self.allowed_columns.get(table.lower(), set())
        return column.lower() in {c.lower() for c in table_cols}

    def can_access_metric(self, metric: str) -> bool:
        if self.role == Role.ADMIN:
            return True
        return metric.lower() not in {m.lower() for m in self.denied_metrics}


class RBACManager:
    """Manages user roles, permissions, and access control."""

    # Default permissions per role
    ROLE_PERMISSIONS: Dict[Role, List[Permission]] = {
        Role.VIEWER: [Permission.READ],
        Role.ANALYST: [Permission.READ],
        Role.MANAGER: [Permission.READ, Permission.WRITE],
        Role.ADMIN: [Permission.READ, Permission.WRITE, Permission.ADMIN],
    }

    # Default table access per role
    ROLE_TABLES: Dict[Role, Set[str]] = {
        Role.VIEWER: {"sales", "products"},
        Role.ANALYST: {"sales", "customers", "products"},
        Role.MANAGER: {"sales", "customers", "products"},
        Role.ADMIN: {"sales", "customers", "products"},
    }

    # Default column restrictions (sensitive columns)
    SENSITIVE_COLUMNS: Dict[str, Set[str]] = {
        "customers": {"email"},  # PII
    }

    def __init__(self):
        self._users: Dict[str, UserContext] = {}

    def create_user(self, user_id: str, email: str, role: Role,
                    department: Optional[str] = None,
                    region: Optional[str] = None) -> UserContext:
        """Create a user with appropriate permissions."""
        allowed_tables = self.ROLE_TABLES.get(role, set()).copy()

        # Column restrictions: viewers can't see sensitive columns
        allowed_columns = {}
        for table in allowed_tables:
            cols = self._get_table_columns(table)
            if role == Role.VIEWER:
                sensitive = self.SENSITIVE_COLUMNS.get(table, set())
                cols = cols - sensitive
            allowed_columns[table] = cols

        user = UserContext(
            user_id=user_id,
            email=email,
            role=role,
            department=department,
            region=region,
            allowed_tables=allowed_tables,
            allowed_columns=allowed_columns,
        )

        self._users[user_id] = user
        logger.info(f"User created: {user_id} with role {role.value}")
        return user

    def get_user(self, user_id: str) -> Optional[UserContext]:
        return self._users.get(user_id)

    def _get_table_columns(self, table: str) -> Set[str]:
        """Get all columns for a table (simplified)."""
        # In production, query from database schema
        column_map = {
            "sales": {"sale_id", "product_id", "customer_id", "amount", "quantity", "sale_date", "region", "channel"},
            "customers": {"customer_id", "name", "email", "signup_date", "segment", "employees", "city", "state"},
            "products": {"product_id", "name", "category", "price", "cost"},
        }
        return column_map.get(table.lower(), set())

    def check_permission(self, user_id: str, table: str, action: str = "read") -> bool:
        """Check if user has permission for action on table."""
        user = self.get_user(user_id)
        if not user:
            log_security_event("unauthorized_access", {"user_id": user_id, "table": table})
            return False

        if not user.can_access_table(table):
            log_security_event("table_access_denied", {
                "user_id": user_id, "table": table, "role": user.role.value
            })
            return False

        return True


class RowLevelSecurity:
    """Row-level security filters."""

    @staticmethod
    def apply_filter(sql: str, user: UserContext) -> str:
        """Apply row-level filters to SQL query.

        Examples:
        - Sales rep sees only their region
        - Manager sees only their department
        """
        if user.role == Role.ADMIN:
            return sql

        conditions = []

        # Region filter for non-admins
        if user.region and "sales" in sql.lower():
            conditions.append(f"region = '{user.region}'")

        # Department filter
        if user.department and "customers" in sql.lower():
            conditions.append(f"segment = '{user.department}'")

        if not conditions:
            return sql

        # Inject WHERE clause
        where_clause = " AND ".join(conditions)

        if "WHERE" in sql.upper():
            # Append to existing WHERE
            sql = sql.replace("WHERE", f"WHERE ({where_clause}) AND ", 1)
        else:
            # Add WHERE before GROUP BY, ORDER BY, or LIMIT
            for keyword in ["GROUP BY", "ORDER BY", "LIMIT"]:
                if keyword in sql.upper():
                    parts = sql.upper().split(keyword, 1)
                    sql = f"{parts[0]}WHERE {where_clause} {keyword}{parts[1]}"
                    break
            else:
                sql = f"{sql} WHERE {where_clause}"

        logger.info(f"RLS applied for user {user.user_id}: {where_clause}")
        return sql


class ColumnLevelSecurity:
    """Column-level security — masks or removes sensitive columns."""

    @staticmethod
    def filter_columns(df, user: UserContext, table: str) -> Any:
        """Remove columns the user is not authorized to see."""
        if user.role == Role.ADMIN:
            return df

        allowed_cols = user.allowed_columns.get(table.lower(), set())
        if not allowed_cols:
            return df

        # Find columns to drop
        to_drop = [col for col in df.columns if col.lower() not in {c.lower() for c in allowed_cols}]

        if to_drop:
            logger.info(f"CLS filtered columns for user {user.user_id}: {to_drop}")
            return df.drop(columns=to_drop, errors='ignore')

        return df


class AuditLogger:
    """Comprehensive audit logging for all data access."""

    @staticmethod
    def log_query(user: UserContext, sql: str, tables: List[str],
                  rows_accessed: int, success: bool, error: Optional[str] = None):
        """Log a data access event for audit."""
        audit_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "user_id": user.user_id,
            "email": user.email,
            "role": user.role.value,
            "department": user.department,
            "region": user.region,
            "sql_hash": hashlib.sha256(sql.encode()).hexdigest()[:16],
            "tables": tables,
            "rows_accessed": rows_accessed,
            "success": success,
            "error": error,
        }

        log_security_event(
            "data_access",
            audit_entry,
            severity="error" if not success or rows_accessed > 10000 else "warning"
        )

    @staticmethod
    def log_schema_access(user: UserContext, tables_accessed: List[str]):
        """Log schema introspection."""
        log_security_event(
            "schema_access",
            {
                "user_id": user.user_id,
                "role": user.role.value,
                "tables": tables_accessed,
            }
        )
