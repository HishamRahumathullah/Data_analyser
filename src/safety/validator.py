import sqlglot
from sqlglot import exp
from typing import Set, Dict, List

class SQLSafetyValidator:
    def __init__(self, allowed_tables: Set[str], read_only: bool = True):
        self.allowed_tables = {t.lower() for t in allowed_tables}
        self.read_only = read_only
        self.forbidden_ops = {
            'DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'GRANT',
            'REVOKE', 'INSERT', 'UPDATE', 'MERGE', 'CREATE', 'REPLACE'
        } if read_only else {'DROP', 'TRUNCATE', 'GRANT', 'REVOKE'}

    def validate(self, query: str) -> Dict:
        result = {'safe': False, 'errors': [], 'tables': set()}
        try:
            # Basic keyword check for forbidden operations
            query_upper = query.upper()
            for op in self.forbidden_ops:
                # Use word boundaries to avoid false positives (e.g., 'created_at')
                import re
                if re.search(rf'\b{op}\b', query_upper):
                    result['errors'].append(f"Forbidden operation: {op}")

            parsed = sqlglot.parse(query)
            if not parsed or not parsed[0]:
                result['errors'].append("Failed to parse SQL query")
                return result

            for stmt in parsed:
                for table in stmt.find_all(exp.Table):
                    t = table.name.lower()
                    result['tables'].add(t)
                    if t not in self.allowed_tables:
                        result['errors'].append(f"Unauthorized table: {t}")

            result['safe'] = len(result['errors']) == 0
            # Convert set to list for JSON serialization if needed
            result['tables'] = list(result['tables'])
            return result
        except Exception as e:
            result['errors'].append(f"Validation error: {str(e)}")
            return result
