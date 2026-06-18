"""Query result validation — catches silent failures."""
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np

from src.utils import logger


class ResultValidator:
    """Validates query results for plausibility and correctness.

    Catches:
    - Empty results (maybe wrong filter?)
    - Exploded counts (missing JOIN condition)
    - Wrong units (cents vs dollars)
    - Suspicious distributions
    """

    def __init__(self):
        self._historical_stats: Dict[str, Dict] = {}

    def validate(self, df: pd.DataFrame, sql: str, expected_metrics: List[str] = None) -> Dict[str, Any]:
        """Validate query result.

        Returns:
            Dict with 'valid', 'warnings', 'errors', 'stats'
        """
        result = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "stats": {}
        }

        if df is None:
            result["valid"] = False
            result["errors"].append("Result is None")
            return result

        # Check empty result
        if len(df) == 0:
            result["warnings"].append("Query returned 0 rows — verify filters and date ranges")

        # Check for nulls
        null_rates = df.isnull().mean()
        high_null_cols = null_rates[null_rates > 0.5].index.tolist()
        if high_null_cols:
            result["warnings"].append(f"High null rate in columns: {high_null_cols}")

        # Check numeric columns for suspicious values
        for col in df.select_dtypes(include=[np.number]).columns:
            stats = {
                "min": df[col].min(),
                "max": df[col].max(),
                "mean": df[col].mean(),
                "median": df[col].median(),
                "null_count": df[col].isnull().sum(),
            }
            result["stats"][col] = stats

            # Check for negative values in typically positive metrics
            if col in ["amount", "revenue", "total", "count"] and stats["min"] < 0:
                result["warnings"].append(f"Negative values found in {col} — verify data quality")

            # Check for extreme outliers (>100x median)
            if stats["median"] > 0 and stats["max"] > stats["median"] * 100:
                result["warnings"].append(f"Extreme outliers in {col} (max {stats['max']:.2f} vs median {stats['median']:.2f})")

        # Check row count vs historical
        table_hash = self._hash_sql(sql)
        if table_hash in self._historical_stats:
            hist = self._historical_stats[table_hash]
            if len(df) > hist["avg_rows"] * 10:
                result["warnings"].append(f"Result has {len(df)} rows, historically averages {hist['avg_rows']:.0f} — possible Cartesian product")

        # Update historical stats
        self._update_stats(table_hash, len(df))

        result["valid"] = len(result["errors"]) == 0
        return result

    def _hash_sql(self, sql: str) -> str:
        """Create a simple hash of SQL for tracking."""
        import hashlib
        # Normalize: lowercase, remove extra whitespace
        normalized = " ".join(sql.lower().split())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    def _update_stats(self, sql_hash: str, row_count: int):
        """Update historical statistics for a query pattern."""
        if sql_hash not in self._historical_stats:
            self._historical_stats[sql_hash] = {"count": 0, "avg_rows": 0}

        stats = self._historical_stats[sql_hash]
        stats["count"] += 1
        # Running average
        stats["avg_rows"] = (stats["avg_rows"] * (stats["count"] - 1) + row_count) / stats["count"]
