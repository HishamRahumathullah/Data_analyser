"""Business Logic Engine - structured business rules and domain knowledge.

This module provides:
- KPI definitions with formulas and targets
- Business segment definitions
- Regional mappings and hierarchies
- Business rules that affect data interpretation
- Target/benchmark tracking
"""
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
import json

from src.utils import logger


class ComparisonType(Enum):
    """Types of comparative analysis."""
    YOY = "year_over_year"
    MOM = "month_over_month"
    WOW = "week_over_week"
    TARGET = "vs_target"
    BENCHMARK = "vs_benchmark"
    SEGMENT = "vs_segment"


class TrendDirection(Enum):
    """Trend direction classification."""
    UP = "up"
    DOWN = "down"
    FLAT = "flat"
    VOLATILE = "volatile"


@dataclass
class KPITarget:
    """Target definition for a KPI."""
    value: float
    period: str  # "monthly", "quarterly", "annual"
    fiscal_year: Optional[int] = None
    effective_date: Optional[date] = None

    def to_dict(self) -> Dict:
        return {
            "value": self.value,
            "period": self.period,
            "fiscal_year": self.fiscal_year,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
        }


@dataclass
class KPI:
    """Key Performance Indicator definition.

    Defines what a metric means, how to calculate it, and what good looks like.
    """
    name: str
    display_name: str
    description: str
    category: str  # "revenue", "growth", "efficiency", "retention", "satisfaction"
    formula_sql: str  # SQL formula to calculate this KPI
    unit: str  # "dollars", "percent", "count", "ratio"
    aggregation: str  # "sum", "avg", "count", "min", "max"

    # Targets and benchmarks
    targets: List[KPITarget] = field(default_factory=list)
    benchmark_value: Optional[float] = None
    benchmark_source: Optional[str] = None  # "industry", "internal", "competitor"

    # Business rules
    higher_is_better: bool = True
    warning_threshold: Optional[float] = None  # Value that triggers warning
    critical_threshold: Optional[float] = None  # Value that triggers alert

    def calculate(self, df) -> float:
        """Calculate KPI value from a DataFrame."""
        # This would be implemented with actual pandas operations
        # For now, return placeholder
        return 0.0

    def assess_performance(self, value: float) -> Dict[str, Any]:
        """Assess whether a KPI value is good, warning, or critical."""
        status = "good"
        message = f"{self.display_name} is on track"

        if self.higher_is_better:
            if self.critical_threshold is not None and value < self.critical_threshold:
                status = "critical"
                message = f"{self.display_name} is critically low ({value:.1f})"
            elif self.warning_threshold is not None and value < self.warning_threshold:
                status = "warning"
                message = f"{self.display_name} is below target ({value:.1f})"
        else:
            if self.critical_threshold is not None and value > self.critical_threshold:
                status = "critical"
                message = f"{self.display_name} is critically high ({value:.1f})"
            elif self.warning_threshold is not None and value > self.warning_threshold:
                status = "warning"
                message = f"{self.display_name} is above target ({value:.1f})"

        # Compare to latest target
        latest_target = self._get_latest_target()
        if latest_target:
            if self.higher_is_better:
                pct_to_target = (value / latest_target.value * 100) if latest_target.value != 0 else 0
            else:
                pct_to_target = (latest_target.value / value * 100) if value != 0 else 0
        else:
            pct_to_target = None

        return {
            "kpi_name": self.name,
            "display_name": self.display_name,
            "value": value,
            "status": status,
            "message": message,
            "target": latest_target.value if latest_target else None,
            "pct_to_target": pct_to_target,
            "benchmark": self.benchmark_value,
            "unit": self.unit,
        }

    def _get_latest_target(self) -> Optional[KPITarget]:
        """Get the most recent target."""
        if not self.targets:
            return None
        return sorted(self.targets, key=lambda t: t.effective_date or date.min, reverse=True)[0]

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "formula_sql": self.formula_sql,
            "unit": self.unit,
            "aggregation": self.aggregation,
            "targets": [t.to_dict() for t in self.targets],
            "benchmark_value": self.benchmark_value,
            "benchmark_source": self.benchmark_source,
            "higher_is_better": self.higher_is_better,
            "warning_threshold": self.warning_threshold,
            "critical_threshold": self.critical_threshold,
        }


@dataclass
class SegmentRule:
    """Rule for defining a business segment.

    Example: Enterprise customers = employees > 500
    """
    name: str
    display_name: str
    description: str
    table: str  # "customers", "products", etc.
    column: str  # "employees", "price", etc.
    operator: str  # ">", "<", "=", "in", "between"
    value: Any
    value_secondary: Optional[Any] = None  # For "between" operator

    def to_sql_filter(self) -> str:
        """Convert segment rule to SQL WHERE clause."""
        if self.operator == "in":
            if isinstance(self.value, list):
                values = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in self.value)
                return f"{self.column} IN ({values})"
            else:
                return f"{self.column} = '{self.value}'"
        elif self.operator == "between":
            return f"{self.column} BETWEEN {self.value} AND {self.value_secondary}"
        elif self.operator in [">", "<", ">=", "<=", "="]:
            val = f"'{self.value}'" if isinstance(self.value, str) else str(self.value)
            return f"{self.column} {self.operator} {val}"
        else:
            return f"{self.column} = '{self.value}'"

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "table": self.table,
            "column": self.column,
            "operator": self.operator,
            "value": self.value,
        }


@dataclass
class RegionMapping:
    """Mapping of business regions to states/cities/countries."""
    region_name: str
    states: List[str] = field(default_factory=list)
    cities: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict:
        return {
            "region_name": self.region_name,
            "states": self.states,
            "cities": self.cities,
            "countries": self.countries,
            "description": self.description,
        }


class BusinessLogicEngine:
    """Central engine for business logic, KPIs, segments, and rules.

    This is the heart of Capability 3: Business Context & Data Storytelling.
    It transforms raw database queries into business-meaningful insights.
    """

    def __init__(self):
        self.kpis: Dict[str, KPI] = {}
        self.segments: Dict[str, SegmentRule] = {}
        self.regions: Dict[str, RegionMapping] = {}
        self.business_rules: Dict[str, str] = {}
        self._init_default_definitions()

    def _init_default_definitions(self):
        """Initialize default business definitions for the sample data."""
        # KPIs
        self.add_kpi(KPI(
            name="total_revenue",
            display_name="Total Revenue",
            description="Sum of all sales amounts",
            category="revenue",
            formula_sql="SUM(amount)",
            unit="dollars",
            aggregation="sum",
            targets=[
                KPITarget(value=100000, period="monthly", fiscal_year=2026),
            ],
            higher_is_better=True,
            warning_threshold=70000,
            critical_threshold=50000,
        ))

        self.add_kpi(KPI(
            name="avg_order_value",
            display_name="Average Order Value",
            description="Average amount per transaction",
            category="revenue",
            formula_sql="AVG(amount)",
            unit="dollars",
            aggregation="avg",
            targets=[
                KPITarget(value=250, period="monthly", fiscal_year=2026),
            ],
            benchmark_value=220,
            benchmark_source="industry",
            higher_is_better=True,
            warning_threshold=180,
            critical_threshold=150,
        ))

        self.add_kpi(KPI(
            name="customer_count",
            display_name="Active Customers",
            description="Number of unique customers making purchases",
            category="growth",
            formula_sql="COUNT(DISTINCT customer_id)",
            unit="count",
            aggregation="count",
            higher_is_better=True,
        ))

        self.add_kpi(KPI(
            name="enterprise_penetration",
            display_name="Enterprise Penetration",
            description="Percentage of revenue from Enterprise customers",
            category="growth",
            formula_sql="(SUM(CASE WHEN segment = 'Enterprise' THEN amount ELSE 0 END) / SUM(amount)) * 100",
            unit="percent",
            aggregation="ratio",
            targets=[
                KPITarget(value=60, period="quarterly", fiscal_year=2026),
            ],
            higher_is_better=True,
            warning_threshold=45,
        ))

        self.add_kpi(KPI(
            name="online_share",
            display_name="Online Channel Share",
            description="Percentage of sales through online channel",
            category="efficiency",
            formula_sql="(SUM(CASE WHEN channel = 'Online' THEN amount ELSE 0 END) / SUM(amount)) * 100",
            unit="percent",
            aggregation="ratio",
            higher_is_better=True,
        ))

        # Segments
        self.add_segment(SegmentRule(
            name="enterprise",
            display_name="Enterprise Customers",
            description="Customers with more than 500 employees",
            table="customers",
            column="employees",
            operator=">",
            value=500,
        ))

        self.add_segment(SegmentRule(
            name="smb",
            display_name="Small-Medium Business",
            description="Customers with 10-500 employees",
            table="customers",
            column="employees",
            operator="between",
            value=10,
            value_secondary=500,
        ))

        self.add_segment(SegmentRule(
            name="consumer",
            display_name="Consumer",
            description="Individual customers",
            table="customers",
            column="employees",
            operator="<=",
            value=1,
        ))

        # Regions
        self.add_region(RegionMapping(
            region_name="North",
            states=["NY", "NJ", "CT", "MA", "VT", "NH", "ME", "RI", "PA"],
            cities=["New York", "Boston", "Philadelphia"],
            description="Northeast US region including NY, NJ, CT",
        ))

        self.add_region(RegionMapping(
            region_name="South",
            states=["TX", "FL", "GA", "NC", "SC", "TN", "AL", "MS", "LA", "AR", "OK", "KY", "WV", "VA", "MD", "DE", "DC"],
            cities=["Austin", "Miami", "Atlanta"],
            description="Southern US region",
        ))

        self.add_region(RegionMapping(
            region_name="East",
            states=["MA", "CT", "RI", "NH", "VT", "ME"],
            cities=["Boston"],
            description="New England region",
        ))

        self.add_region(RegionMapping(
            region_name="West",
            states=["CA", "OR", "WA", "NV", "AZ", "UT", "CO", "ID", "MT", "WY", "AK", "HI"],
            cities=["Seattle", "Los Angeles", "San Francisco"],
            description="Western US region",
        ))

        # Business rules (textual context for LLM)
        self.add_business_rule(
            "north_region",
            "The 'North' region includes NY, NJ, CT, MA, VT, NH, ME, RI, and PA. "
            "New York is the primary market with highest revenue concentration."
        )

        self.add_business_rule(
            "enterprise_definition",
            "Enterprise customers are defined as those with more than 500 employees. "
            "They typically have longer sales cycles but higher lifetime value. "
            "Enterprise accounts are managed by dedicated account executives."
        )

        self.add_business_rule(
            "channel_strategy",
            "Online channel has lower acquisition cost but lower average order value. "
            "Retail channel has higher AOV but requires physical presence. "
            "Wholesale is B2B only with volume discounts."
        )

        self.add_business_rule(
            "seasonality",
            "Q4 typically sees 30-40% revenue uplift due to holiday shopping. "
            "Q1 is historically the slowest quarter. Plan inventory accordingly."
        )

        logger.info("BusinessLogicEngine initialized with default definitions")

    def add_kpi(self, kpi: KPI) -> None:
        """Register a KPI definition."""
        self.kpis[kpi.name] = kpi
        logger.debug(f"KPI registered: {kpi.name}")

    def add_segment(self, segment: SegmentRule) -> None:
        """Register a segment rule."""
        self.segments[segment.name] = segment
        logger.debug(f"Segment registered: {segment.name}")

    def add_region(self, region: RegionMapping) -> None:
        """Register a region mapping."""
        self.regions[region.region_name] = region
        logger.debug(f"Region registered: {region.region_name}")

    def add_business_rule(self, name: str, rule: str) -> None:
        """Register a business rule (textual context)."""
        self.business_rules[name] = rule
        logger.debug(f"Business rule registered: {name}")

    def get_kpi(self, name: str) -> Optional[KPI]:
        """Get a KPI by name."""
        return self.kpis.get(name)

    def get_segment(self, name: str) -> Optional[SegmentRule]:
        """Get a segment by name."""
        return self.segments.get(name)

    def get_region(self, name: str) -> Optional[RegionMapping]:
        """Get a region by name."""
        return self.regions.get(name)

    def get_kpis_by_category(self, category: str) -> List[KPI]:
        """Get all KPIs in a category."""
        return [kpi for kpi in self.kpis.values() if kpi.category == category]

    def get_all_context(self) -> str:
        """Get all business context as formatted text for LLM prompts."""
        context_parts = []

        # KPIs
        context_parts.append("## Key Performance Indicators (KPIs)\n")
        for kpi in self.kpis.values():
            target_str = ""
            latest = kpi._get_latest_target()
            if latest:
                target_str = f" (Target: {latest.value:,.0f} {kpi.unit})"
            context_parts.append(
                f"- **{kpi.display_name}**: {kpi.description}{target_str}\n"
                f"  - Formula: {kpi.formula_sql}\n"
                f"  - Unit: {kpi.unit}\n"
            )

        # Segments
        context_parts.append("\n## Customer Segments\n")
        for seg in self.segments.values():
            context_parts.append(
                f"- **{seg.display_name}**: {seg.description}\n"
                f"  - Rule: {seg.column} {seg.operator} {seg.value}\n"
            )

        # Regions
        context_parts.append("\n## Regional Definitions\n")
        for region in self.regions.values():
            states_str = ", ".join(region.states[:5]) + ("..." if len(region.states) > 5 else "")
            context_parts.append(
                f"- **{region.region_name}**: {region.description}\n"
                f"  - Key states: {states_str}\n"
            )

        # Business rules
        context_parts.append("\n## Business Rules & Context\n")
        for name, rule in self.business_rules.items():
            context_parts.append(f"- **{name}**: {rule}\n")

        return "\n".join(context_parts)

    def get_relevant_context(self, query: str) -> str:
        """Get business context relevant to a specific query.

        Uses keyword matching to filter context (will be upgraded to semantic search).
        """
        query_lower = query.lower()
        relevant_parts = []

        # Check for KPI mentions
        for kpi in self.kpis.values():
            if any(kw in query_lower for kw in [kpi.name.lower(), kpi.display_name.lower()]):
                relevant_parts.append(f"KPI: {kpi.display_name} - {kpi.description}")
                latest = kpi._get_latest_target()
                if latest:
                    relevant_parts.append(f"  Target: {latest.value:,.0f} {kpi.unit}")

        # Check for segment mentions
        for seg in self.segments.values():
            if any(kw in query_lower for kw in [seg.name.lower(), seg.display_name.lower()]):
                relevant_parts.append(f"Segment: {seg.display_name} - {seg.description}")

        # Check for region mentions
        for region in self.regions.values():
            if region.region_name.lower() in query_lower:
                relevant_parts.append(f"Region: {region.region_name} - {region.description}")
                relevant_parts.append(f"  States: {', '.join(region.states[:10])}")

        # Check for business rule keywords
        for name, rule in self.business_rules.items():
            keywords = name.replace("_", " ").split()
            if any(kw in query_lower for kw in keywords):
                relevant_parts.append(f"Rule: {rule}")

        if not relevant_parts:
            # Return general context if no specific matches
            return self.get_all_context()

        return "\n".join(relevant_parts)

    def to_dict(self) -> Dict:
        """Serialize all business logic to dictionary."""
        return {
            "kpis": {name: kpi.to_dict() for name, kpi in self.kpis.items()},
            "segments": {name: seg.to_dict() for name, seg in self.segments.items()},
            "regions": {name: reg.to_dict() for name, reg in self.regions.items()},
            "business_rules": self.business_rules,
        }

    def save_to_file(self, filepath: str) -> None:
        """Save business logic to JSON file."""
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        logger.info(f"Business logic saved to {filepath}")

    @classmethod
    def load_from_file(cls, filepath: str) -> "BusinessLogicEngine":
        """Load business logic from JSON file."""
        engine = cls()
        with open(filepath, "r") as f:
            data = json.load(f)

        # Clear defaults and load from file
        engine.kpis.clear()
        engine.segments.clear()
        engine.regions.clear()
        engine.business_rules.clear()

        for name, kpi_data in data.get("kpis", {}).items():
            targets = [KPITarget(**t) for t in kpi_data.pop("targets", [])]
            kpi_data["targets"] = targets
            engine.add_kpi(KPI(**kpi_data))

        for name, seg_data in data.get("segments", {}).items():
            engine.add_segment(SegmentRule(**seg_data))

        for name, reg_data in data.get("regions", {}).items():
            engine.add_region(RegionMapping(**reg_data))

        engine.business_rules.update(data.get("business_rules", {}))

        logger.info(f"Business logic loaded from {filepath}")
        return engine
