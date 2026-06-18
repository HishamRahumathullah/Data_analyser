"""Dashboard builder with semantic metric binding and cross-filtering.

Charts reference semantic metrics (not raw SQL), ensuring consistency.
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import json

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px

from src.semantic.layer import SemanticLayer, Metric, Dimension
from src.utils import logger


class ChartType(Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    TABLE = "table"
    KPI = "kpi"
    FUNNEL = "funnel"


@dataclass
class ChartSpec:
    """Specification for a single chart."""
    title: str
    chart_type: ChartType
    metric: str  # Semantic metric name
    dimension: Optional[str] = None  # Semantic dimension name
    segment: Optional[str] = None  # Semantic segment name
    color: Optional[str] = None
    height: int = 400
    width: Optional[int] = None


@dataclass
class Dashboard:
    """A dashboard with multiple charts and shared filters."""
    title: str
    description: str
    charts: List[ChartSpec] = field(default_factory=list)
    shared_filters: Dict[str, Any] = field(default_factory=dict)
    layout: str = "grid"  # "grid", "row", "column"

    def add_chart(self, chart: ChartSpec) -> None:
        self.charts.append(chart)

    def set_filter(self, dimension: str, value: Any) -> None:
        self.shared_filters[dimension] = value


class ChartBuilder:
    """Builds individual charts from semantic specifications."""

    def __init__(self, semantic_layer: SemanticLayer):
        self.semantic = semantic_layer

    def build(self, spec: ChartSpec, df: pd.DataFrame) -> go.Figure:
        """Build a chart from specification and data."""
        metric = self.semantic.get_metric(spec.metric)
        dimension = self.semantic.get_dimension(spec.dimension) if spec.dimension else None

        if spec.chart_type == ChartType.BAR:
            return self._build_bar(df, spec, metric, dimension)
        elif spec.chart_type == ChartType.LINE:
            return self._build_line(df, spec, metric, dimension)
        elif spec.chart_type == ChartType.PIE:
            return self._build_pie(df, spec, metric, dimension)
        elif spec.chart_type == ChartType.SCATTER:
            return self._build_scatter(df, spec, metric, dimension)
        elif spec.chart_type == ChartType.KPI:
            return self._build_kpi(df, spec, metric)
        else:
            return self._build_table(df, spec)

    def _build_bar(self, df: pd.DataFrame, spec: ChartSpec, metric: Metric, dimension: Optional[Dimension]) -> go.Figure:
        x_col = dimension.name if dimension else df.columns[0]
        y_col = metric.name if metric.name in df.columns else df.columns[-1]

        fig = px.bar(
            df,
            x=x_col,
            y=y_col,
            title=spec.title,
            color=spec.color or x_col,
            text_auto='.2s',
            height=spec.height,
        )
        fig.update_layout(
            xaxis_title=dimension.display_name if dimension else x_col,
            yaxis_title=metric.display_name if metric else y_col,
            showlegend=False,
        )
        return fig

    def _build_line(self, df: pd.DataFrame, spec: ChartSpec, metric: Metric, dimension: Optional[Dimension]) -> go.Figure:
        x_col = dimension.name if dimension else df.columns[0]
        y_col = metric.name if metric.name in df.columns else df.columns[-1]

        fig = px.line(
            df,
            x=x_col,
            y=y_col,
            title=spec.title,
            markers=True,
            height=spec.height,
        )
        fig.update_layout(
            xaxis_title=dimension.display_name if dimension else x_col,
            yaxis_title=metric.display_name if metric else y_col,
        )
        return fig

    def _build_pie(self, df: pd.DataFrame, spec: ChartSpec, metric: Metric, dimension: Optional[Dimension]) -> go.Figure:
        names_col = dimension.name if dimension else df.columns[0]
        values_col = metric.name if metric.name in df.columns else df.columns[-1]

        fig = px.pie(
            df,
            names=names_col,
            values=values_col,
            title=spec.title,
            height=spec.height,
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        return fig

    def _build_scatter(self, df: pd.DataFrame, spec: ChartSpec, metric: Metric, dimension: Optional[Dimension]) -> go.Figure:
        x_col = df.columns[0]
        y_col = metric.name if metric.name in df.columns else df.columns[-1]

        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            title=spec.title,
            height=spec.height,
            size=y_col,
            color=dimension.name if dimension else None,
        )
        return fig

    def _build_kpi(self, df: pd.DataFrame, spec: ChartSpec, metric: Metric) -> go.Figure:
        """Build a KPI card showing a single metric."""
        value_col = metric.name if metric.name in df.columns else df.columns[-1]
        total = df[value_col].sum() if metric.aggregation.value in ["SUM", "COUNT"] else df[value_col].mean()

        fig = go.Figure(go.Indicator(
            mode="number+delta",
            value=total,
            title={"text": spec.title},
            number={"prefix": "$" if "revenue" in metric.name or "amount" in metric.name else "",
                   "valueformat": ",.0f"},
            height=spec.height,
        ))
        return fig

    def _build_table(self, df: pd.DataFrame, spec: ChartSpec) -> go.Figure:
        """Build a data table."""
        fig = go.Figure(data=[go.Table(
            header=dict(values=list(df.columns), fill_color='paleturquoise', align='left'),
            cells=dict(values=[df[col] for col in df.columns], fill_color='lavender', align='left')
        )])
        fig.update_layout(title=spec.title, height=spec.height)
        return fig


class DashboardBuilder:
    """Builds dashboards with cross-chart consistency."""

    def __init__(self, semantic_layer: SemanticLayer):
        self.semantic = semantic_layer
        self.chart_builder = ChartBuilder(semantic_layer)

    def build(self, dashboard: Dashboard, data: Dict[str, pd.DataFrame]) -> Dict[str, go.Figure]:
        """Build all charts for a dashboard.

        Args:
            dashboard: Dashboard specification
            data: Dict mapping chart index to DataFrame

        Returns:
            Dict mapping chart title to Figure
        """
        figures = {}

        for i, chart_spec in enumerate(dashboard.charts):
            df = data.get(i, pd.DataFrame())
            if df.empty:
                logger.warning(f"No data for chart: {chart_spec.title}")
                continue

            try:
                fig = self.chart_builder.build(chart_spec, df)
                figures[chart_spec.title] = fig
            except Exception as e:
                logger.error(f"Failed to build chart '{chart_spec.title}': {e}")

        return figures

    def create_default_dashboard(self, metric_name: str, dimension_name: str) -> Dashboard:
        """Create a default dashboard for exploring a metric by dimension."""
        metric = self.semantic.get_metric(metric_name)
        dimension = self.semantic.get_dimension(dimension_name)

        dashboard = Dashboard(
            title=f"{metric.display_name if metric else metric_name} Analysis",
            description=f"Exploring {metric.display_name if metric else metric_name} by {dimension.display_name if dimension else dimension_name}",
        )

        # Chart 1: Bar chart
        dashboard.add_chart(ChartSpec(
            title=f"{metric.display_name if metric else metric_name} by {dimension.display_name if dimension else dimension_name}",
            chart_type=ChartType.BAR,
            metric=metric_name,
            dimension=dimension_name,
        ))

        # Chart 2: Pie chart
        dashboard.add_chart(ChartSpec(
            title="Distribution",
            chart_type=ChartType.PIE,
            metric=metric_name,
            dimension=dimension_name,
        ))

        # Chart 3: KPI card
        dashboard.add_chart(ChartSpec(
            title=f"Total {metric.display_name if metric else metric_name}",
            chart_type=ChartType.KPI,
            metric=metric_name,
        ))

        return dashboard


class ExportPipeline:
    """Export dashboards to various formats."""

    @staticmethod
    def to_png(fig: go.Figure, path: str) -> str:
        """Export figure to PNG."""
        fig.write_image(path, scale=2)
        return path

    @staticmethod
    def to_svg(fig: go.Figure, path: str) -> str:
        """Export figure to SVG."""
        fig.write_image(path)
        return path

    @staticmethod
    def to_html(fig: go.Figure, path: str) -> str:
        """Export figure to interactive HTML."""
        fig.write_html(path)
        return path

    @staticmethod
    def to_json(fig: go.Figure) -> str:
        """Export figure to JSON."""
        return fig.to_json()
