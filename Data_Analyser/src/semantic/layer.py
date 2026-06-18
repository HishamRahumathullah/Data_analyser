"""Semantic Layer — The load-bearing foundation of the entire system.

Defines business metrics, dimensions, and segments as first-class objects.
The LLM queries the semantic layer, not raw tables. This ensures:
- Consistent metric definitions across all queries
- Governed business logic (KPIs, targets, segments)
- Reusable SQL fragments (no hallucinated joins)
- Cross-chart consistency in dashboards
"""
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import re

from src.utils import logger


class AggregationType(Enum):
    SUM = "SUM"
    AVG = "AVG"
    COUNT = "COUNT"
    COUNT_DISTINCT = "COUNT(DISTINCT {})"
    MIN = "MIN"
    MAX = "MAX"


class TimeGrain(Enum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    YEAR = "YEAR"


@dataclass
class Dimension:
    """A reusable dimension (e.g., region, product_category, customer_segment)."""
    name: str
    display_name: str
    description: str
    sql_column: str
    sql_table: str
    data_type: str = "VARCHAR"
    allowed_values: Optional[List[str]] = None

    def to_sql(self, table_alias: str = "t") -> str:
        return f"{table_alias}.{self.sql_column}"

    def to_description(self) -> str:
        values = f" Allowed values: {', '.join(self.allowed_values)}" if self.allowed_values else ""
        return f"{self.display_name} ({self.name}): {self.description}{values}"


@dataclass  
class Metric:
    """A business metric with pre-defined SQL (e.g., total_revenue, active_users)."""
    name: str
    display_name: str
    description: str
    aggregation: AggregationType
    sql_expression: str  # The SQL expression, e.g., "amount * quantity"
    sql_table: str
    unit: str = ""
    format_string: str = "{:.2f}"
    dimensions: List[str] = field(default_factory=list)
    filters: List[str] = field(default_factory=list)

    def to_sql(self, table_alias: str = "t") -> str:
        expr = self.sql_expression.replace("{table}", table_alias)
        if self.aggregation == AggregationType.COUNT_DISTINCT:
            return f"COUNT(DISTINCT {expr})"
        return f"{self.aggregation.value}({expr})"

    def to_description(self) -> str:
        dims = f" Breaks down by: {', '.join(self.dimensions)}" if self.dimensions else ""
        return f"{self.display_name} ({self.name}): {self.description} Unit: {self.unit}{dims}"


@dataclass
class Segment:
    """A business segment/filter (e.g., Enterprise customers, North region)."""
    name: str
    display_name: str
    description: str
    sql_condition: str  # e.g., "segment = 'Enterprise'"
    applicable_tables: List[str] = field(default_factory=list)

    def to_sql(self, table_alias: str = "t") -> str:
        return self.sql_condition.replace("{table}", table_alias)

    def to_description(self) -> str:
        return f"{self.display_name} ({self.name}): {self.description}"


@dataclass
class SemanticQuery:
    """A resolved semantic query ready for SQL generation."""
    metrics: List[Metric]
    dimensions: List[Dimension]
    segments: List[Segment]
    time_grain: Optional[TimeGrain] = None
    time_range: Optional[Dict[str, str]] = None  # {"start": "2026-01-01", "end": "2026-01-31"}
    order_by: Optional[str] = None
    limit: int = 1000

    def to_sql(self) -> str:
        """Generate SQL from semantic components."""
        # Build SELECT
        selects = []
        for dim in self.dimensions:
            selects.append(f"{dim.to_sql('t')} AS {dim.name}")
        for metric in self.metrics:
            selects.append(f"{metric.to_sql('t')} AS {metric.name}")

        # Build FROM
        tables = set()
        for m in self.metrics:
            tables.add(m.sql_table)
        for d in self.dimensions:
            tables.add(d.sql_table)

        from_clause = list(tables)[0] if len(tables) == 1 else self._build_joins(tables)

        # Build WHERE
        conditions = []
        for seg in self.segments:
            conditions.append(seg.to_sql('t'))
        if self.time_range:
            conditions.append(f"t.sale_date BETWEEN '{self.time_range['start']}' AND '{self.time_range['end']}'")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Build GROUP BY
        group_cols = [f"t.{d.sql_column}" for d in self.dimensions]
        group_clause = f"GROUP BY {', '.join(group_cols)}" if group_cols else ""

        # Build ORDER BY
        order_clause = f"ORDER BY {self.order_by}" if self.order_by else ""

        sql = f"""SELECT {', '.join(selects)}
FROM {from_clause} t
{where_clause}
{group_clause}
{order_clause}
LIMIT {self.limit}"""

        return sql.strip()

    def _build_joins(self, tables: set) -> str:
        """Build JOINs between tables based on known relationships."""
        # Simplified join logic — production would use a relationship graph
        table_list = list(tables)
        if len(table_list) == 2 and "sales" in table_list and "customers" in table_list:
            return "sales JOIN customers ON sales.customer_id = customers.customer_id"
        elif len(table_list) == 2 and "sales" in table_list and "products" in table_list:
            return "sales JOIN products ON sales.product_id = products.product_id"
        return table_list[0]


class SemanticLayer:
    """Central registry for all semantic objects."""

    def __init__(self):
        self._metrics: Dict[str, Metric] = {}
        self._dimensions: Dict[str, Dimension] = {}
        self._segments: Dict[str, Segment] = {}
        self._join_paths: Dict[str, List[str]] = {}

        self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        """Initialize default semantic objects for the sample schema."""
        # Dimensions
        self.add_dimension(Dimension(
            name="region",
            display_name="Region",
            description="Sales region: North, South, East, West",
            sql_column="region",
            sql_table="sales",
            allowed_values=["North", "South", "East", "West"]
        ))

        self.add_dimension(Dimension(
            name="channel",
            display_name="Sales Channel",
            description="Channel through which sale occurred",
            sql_column="channel",
            sql_table="sales",
            allowed_values=["Online", "Retail", "Wholesale"]
        ))

        self.add_dimension(Dimension(
            name="customer_segment",
            display_name="Customer Segment",
            description="Customer classification",
            sql_column="segment",
            sql_table="customers",
            allowed_values=["Enterprise", "SMB", "Consumer"]
        ))

        self.add_dimension(Dimension(
            name="product_category",
            display_name="Product Category",
            description="Product classification",
            sql_column="category",
            sql_table="products",
            allowed_values=["Electronics", "Furniture"]
        ))

        self.add_dimension(Dimension(
            name="sale_date",
            display_name="Sale Date",
            description="Date of the transaction",
            sql_column="sale_date",
            sql_table="sales",
            data_type="DATE"
        ))

        # Metrics
        self.add_metric(Metric(
            name="total_revenue",
            display_name="Total Revenue",
            description="Sum of all sales amounts",
            aggregation=AggregationType.SUM,
            sql_expression="amount",
            sql_table="sales",
            unit="USD",
            format_string="${:,.2f}",
            dimensions=["region", "channel", "customer_segment", "product_category", "sale_date"]
        ))

        self.add_metric(Metric(
            name="order_count",
            display_name="Order Count",
            description="Number of orders placed",
            aggregation=AggregationType.COUNT,
            sql_expression="sale_id",
            sql_table="sales",
            unit="orders",
            dimensions=["region", "channel", "customer_segment", "product_category"]
        ))

        self.add_metric(Metric(
            name="avg_order_value",
            display_name="Average Order Value",
            description="Average revenue per order",
            aggregation=AggregationType.AVG,
            sql_expression="amount",
            sql_table="sales",
            unit="USD",
            format_string="${:,.2f}",
            dimensions=["region", "channel", "customer_segment"]
        ))

        self.add_metric(Metric(
            name="total_units_sold",
            display_name="Total Units Sold",
            description="Sum of quantities sold",
            aggregation=AggregationType.SUM,
            sql_expression="quantity",
            sql_table="sales",
            unit="units",
            dimensions=["product_category", "region"]
        ))

        self.add_metric(Metric(
            name="unique_customers",
            display_name="Unique Customers",
            description="Count of distinct customers",
            aggregation=AggregationType.COUNT_DISTINCT,
            sql_expression="customer_id",
            sql_table="sales",
            unit="customers",
            dimensions=["region", "customer_segment"]
        ))

        # Segments
        self.add_segment(Segment(
            name="enterprise_customers",
            display_name="Enterprise Customers",
            description="Customers with more than 500 employees",
            sql_condition="{table}.segment = 'Enterprise'",
            applicable_tables=["customers", "sales"]
        ))

        self.add_segment(Segment(
            name="north_region",
            display_name="North Region",
            description="North region sales (NY, NJ, CT)",
            sql_condition="{table}.region = 'North'",
            applicable_tables=["sales"]
        ))

        self.add_segment(Segment(
            name="online_channel",
            display_name="Online Channel",
            description="Online sales only",
            sql_condition="{table}.channel = 'Online'",
            applicable_tables=["sales"]
        ))

    def add_metric(self, metric: Metric) -> None:
        self._metrics[metric.name] = metric
        logger.info(f"Registered metric: {metric.name}")

    def add_dimension(self, dimension: Dimension) -> None:
        self._dimensions[dimension.name] = dimension
        logger.info(f"Registered dimension: {dimension.name}")

    def add_segment(self, segment: Segment) -> None:
        self._segments[segment.name] = segment
        logger.info(f"Registered segment: {segment.name}")

    def get_metric(self, name: str) -> Optional[Metric]:
        return self._metrics.get(name)

    def get_dimension(self, name: str) -> Optional[Dimension]:
        return self._dimensions.get(name)

    def get_segment(self, name: str) -> Optional[Segment]:
        return self._segments.get(name)

    def list_metrics(self) -> List[str]:
        return list(self._metrics.keys())

    def list_dimensions(self) -> List[str]:
        return list(self._dimensions.keys())

    def list_segments(self) -> List[str]:
        return list(self._segments.keys())

    def get_schema_description(self) -> str:
        """Generate schema description for LLM context."""
        lines = ["=== AVAILABLE METRICS ==="]
        for name, metric in self._metrics.items():
            lines.append(f"  • {metric.to_description()}")

        lines.append("\n=== AVAILABLE DIMENSIONS ===")
        for name, dim in self._dimensions.items():
            lines.append(f"  • {dim.to_description()}")

        lines.append("\n=== AVAILABLE SEGMENTS/FILTERS ===")
        for name, seg in self._segments.items():
            lines.append(f"  • {seg.to_description()}")

        return "\n".join(lines)

    def resolve_query(self, user_query: str) -> SemanticQuery:
        """Resolve a natural language query to semantic components.

        This is the bridge between natural language and structured semantics.
        In production, this would use an LLM call. Here we use keyword matching
        as a fallback with LLM enhancement.
        """
        q = user_query.lower()

        # Resolve metrics
        metrics = []
        for name, metric in self._metrics.items():
            if any(kw in q for kw in [name, metric.display_name.lower()]):
                metrics.append(metric)

        # Default metric if none found
        if not metrics:
            metrics = [self._metrics.get("total_revenue", list(self._metrics.values())[0])]

        # Resolve dimensions
        dimensions = []
        for name, dim in self._dimensions.items():
            if any(kw in q for kw in [name, dim.display_name.lower()]):
                dimensions.append(dim)

        # Resolve segments
        segments = []
        for name, seg in self._segments.items():
            if any(kw in q for kw in [name, seg.display_name.lower()]):
                segments.append(seg)

        # Detect time grain
        time_grain = None
        if any(kw in q for kw in ["daily", "day", "per day"]):
            time_grain = TimeGrain.DAY
        elif any(kw in q for kw in ["weekly", "week", "per week"]):
            time_grain = TimeGrain.WEEK
        elif any(kw in q for kw in ["monthly", "month", "per month"]):
            time_grain = TimeGrain.MONTH

        return SemanticQuery(
            metrics=metrics,
            dimensions=dimensions,
            segments=segments,
            time_grain=time_grain,
            limit=1000
        )
