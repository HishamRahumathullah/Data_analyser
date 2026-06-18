"""Multi-agent insight pipeline for business analysis.

Architecture:
    Domain Detector → Trend Agent → Anomaly Agent → Compare Agent → Synthesizer
    → Narrative Generator → Stakeholder Formatter

Each agent is a lightweight LLM call with specific role prompts.
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np

from src.agent.llm_client import LLMClient
from src.utils import logger


class InsightType(Enum):
    TREND = "trend"
    ANOMALY = "anomaly"
    COMPARISON = "comparison"
    CORRELATION = "correlation"
    FORECAST = "forecast"


@dataclass
class Insight:
    """A single insight discovery."""
    type: InsightType
    title: str
    description: str
    severity: str  # "high", "medium", "low", "info"
    metric: str
    value: Optional[float] = None
    benchmark: Optional[float] = None
    change_pct: Optional[float] = None
    supporting_data: Dict[str, Any] = None


class DomainDetector:
    """Detects the business domain of the data."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def detect(self, df: pd.DataFrame, user_query: str) -> str:
        """Detect business domain from data and query."""
        columns = ", ".join(df.columns)
        prompt = f"""Given these data columns: {columns}
And the user query: {user_query}

What is the primary business domain? Choose one:
- E-commerce / Retail
- SaaS / Subscription
- Finance / Banking
- Healthcare
- Marketing / Advertising
- Operations / Supply Chain
- General Business

Respond with just the domain name."""

        try:
            return self.llm_client.chat(
                [{"role": "user", "content": prompt}],
                system_prompt="You are a business domain classifier."
            ).strip()
        except Exception:
            return "General Business"


class TrendAgent:
    """Detects trends in time-series data."""

    def analyze(self, df: pd.DataFrame, date_col: str, metric_col: str) -> Optional[Insight]:
        """Analyze trends in the data."""
        if date_col not in df.columns or metric_col not in df.columns:
            return None

        try:
            df[date_col] = pd.to_datetime(df[date_col])
            df_sorted = df.sort_values(date_col)

            if len(df_sorted) < 2:
                return None

            # Calculate trend
            first_val = df_sorted[metric_col].iloc[0]
            last_val = df_sorted[metric_col].iloc[-1]
            change_pct = ((last_val - first_val) / abs(first_val) * 100) if first_val != 0 else 0

            # Determine trend direction
            if change_pct > 10:
                direction = "increasing"
                severity = "high" if change_pct > 50 else "medium"
            elif change_pct < -10:
                direction = "decreasing"
                severity = "high" if change_pct < -50 else "medium"
            else:
                direction = "stable"
                severity = "info"

            return Insight(
                type=InsightType.TREND,
                title=f"{metric_col} is {direction}",
                description=f"{metric_col} changed by {change_pct:+.1f}% from {first_val:.2f} to {last_val:.2f}",
                severity=severity,
                metric=metric_col,
                value=last_val,
                benchmark=first_val,
                change_pct=change_pct,
                supporting_data={"data_points": len(df_sorted)}
            )
        except Exception as e:
            logger.error(f"Trend analysis failed: {e}")
            return None


class AnomalyAgent:
    """Detects statistical anomalies."""

    def analyze(self, df: pd.DataFrame, metric_col: str) -> List[Insight]:
        """Find anomalies using IQR method."""
        insights = []

        if metric_col not in df.columns:
            return insights

        try:
            series = df[metric_col].dropna()
            if len(series) < 4:
                return insights

            Q1 = series.quantile(0.25)
            Q3 = series.quantile(0.75)
            IQR = Q3 - Q1
            lower = Q1 - 1.5 * IQR
            upper = Q3 + 1.5 * IQR

            outliers = series[(series < lower) | (series > upper)]

            if len(outliers) > 0:
                insights.append(Insight(
                    type=InsightType.ANOMALY,
                    title=f"{len(outliers)} anomalous values in {metric_col}",
                    description=f"Found {len(outliers)} values outside expected range ({lower:.2f} to {upper:.2f})",
                    severity="medium" if len(outliers) < 3 else "high",
                    metric=metric_col,
                    supporting_data={"outlier_count": len(outliers), "expected_range": [lower, upper]}
                ))

            return insights
        except Exception as e:
            logger.error(f"Anomaly analysis failed: {e}")
            return insights


class CompareAgent:
    """Performs comparative analysis."""

    def analyze(self, df: pd.DataFrame, metric_col: str, dimension_col: str) -> Optional[Insight]:
        """Compare metric across dimension values."""
        if metric_col not in df.columns or dimension_col not in df.columns:
            return None

        try:
            grouped = df.groupby(dimension_col)[metric_col].sum().sort_values(ascending=False)

            if len(grouped) < 2:
                return None

            top = grouped.iloc[0]
            bottom = grouped.iloc[-1]
            ratio = top / bottom if bottom != 0 else float('inf')

            return Insight(
                type=InsightType.COMPARISON,
                title=f"{grouped.index[0]} leads {metric_col}",
                description=f"{grouped.index[0]} ({top:.2f}) is {ratio:.1f}x higher than {grouped.index[-1]} ({bottom:.2f})",
                severity="high" if ratio > 5 else "medium" if ratio > 2 else "info",
                metric=metric_col,
                value=top,
                benchmark=bottom,
                supporting_data={"leader": grouped.index[0], "laggard": grouped.index[-1], "ratio": ratio}
            )
        except Exception as e:
            logger.error(f"Comparison analysis failed: {e}")
            return None


class InsightSynthesizer:
    """Merges insights into a coherent narrative."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def synthesize(self, insights: List[Insight], user_query: str, data_summary: str) -> str:
        """Synthesize insights into business narrative."""
        if not insights:
            return "No significant insights detected in the current data."

        # Sort by severity
        severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        insights.sort(key=lambda x: severity_order.get(x.severity, 4))

        # Build insight summary
        insight_text = "\n".join([
            f"- [{i.severity.upper()}] {i.title}: {i.description}"
            for i in insights[:5]  # Top 5 insights
        ])

        prompt = f"""You are a senior business analyst presenting findings to executives.

User Question: {user_query}

Data Summary:
{data_summary}

Key Insights Discovered:
{insight_text}

Write a concise executive briefing (3-5 sentences) that:
1. States the most important finding first
2. Provides specific numbers
3. Explains business impact
4. Offers one clear recommendation

Use plain language. Be specific with numbers."""

        try:
            return self.llm_client.chat(
                [{"role": "user", "content": prompt}],
                system_prompt="You are a McKinsey partner who distills complex data into actionable executive summaries."
            )
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return self._fallback_synthesis(insights)

    def _fallback_synthesis(self, insights: List[Insight]) -> str:
        """Fallback when LLM fails."""
        lines = ["## Key Findings"]
        for i in insights[:3]:
            lines.append(f"- **{i.title}**: {i.description}")
        lines.append("\n## Recommendation")
        lines.append("Focus on the highest-impact area identified above and investigate root causes.")
        return "\n".join(lines)


class StakeholderFormatter:
    """Formats output for different audience types."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def format(self, content: str, audience: str = "executive") -> str:
        """Format content for specific audience.

        Audiences:
        - executive: 1-2 sentences, focus on impact and action
        - manager: 1 paragraph, include metrics and trends
        - analyst: Detailed, include methodology and caveats
        - engineer: Technical, include SQL and data pipeline details
        """
        templates = {
            "executive": "Rewrite for a CEO: 1-2 sentences max. Focus on revenue impact and one action item.",
            "manager": "Rewrite for a product manager: 1 paragraph with metrics, trends, and 2-3 specific recommendations.",
            "analyst": "Rewrite for a data analyst: Include methodology, data caveats, and suggestions for deeper analysis.",
            "engineer": "Rewrite for an engineer: Include technical details about data sources, query logic, and pipeline considerations.",
        }

        if audience not in templates:
            return content

        prompt = f"""Original analysis:
{content}

{templates[audience]}

Formatted output:"""

        try:
            return self.llm_client.chat(
                [{"role": "user", "content": prompt}],
                system_prompt=f"You are writing for a {audience}."
            )
        except Exception:
            return content


class InsightPipeline:
    """Orchestrates the multi-agent insight pipeline."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.domain_detector = DomainDetector(llm_client)
        self.trend_agent = TrendAgent()
        self.anomaly_agent = AnomalyAgent()
        self.compare_agent = CompareAgent()
        self.synthesizer = InsightSynthesizer(llm_client)
        self.formatter = StakeholderFormatter(llm_client)

    def run(self, df: pd.DataFrame, user_query: str, date_col: Optional[str] = None,
            metric_col: Optional[str] = None, dimension_col: Optional[str] = None,
            audience: str = "executive") -> Dict[str, Any]:
        """Run the full insight pipeline.

        Returns:
            Dict with 'domain', 'insights', 'narrative', 'formatted'
        """
        logger.info("Starting insight pipeline")

        # Detect domain
        domain = self.domain_detector.detect(df, user_query)

        # Collect insights
        insights = []

        if date_col and metric_col:
            trend = self.trend_agent.analyze(df, date_col, metric_col)
            if trend:
                insights.append(trend)

        if metric_col:
            anomalies = self.anomaly_agent.analyze(df, metric_col)
            insights.extend(anomalies)

        if metric_col and dimension_col:
            comparison = self.compare_agent.analyze(df, metric_col, dimension_col)
            if comparison:
                insights.append(comparison)

        # Synthesize narrative
        data_summary = f"Data has {len(df)} rows, {len(df.columns)} columns: {', '.join(df.columns)}"
        narrative = self.synthesizer.synthesize(insights, user_query, data_summary)

        # Format for audience
        formatted = self.formatter.format(narrative, audience)

        return {
            "domain": domain,
            "insights": [self._insight_to_dict(i) for i in insights],
            "narrative": narrative,
            "formatted": formatted,
            "audience": audience,
        }

    def _insight_to_dict(self, insight: Insight) -> Dict:
        return {
            "type": insight.type.value,
            "title": insight.title,
            "description": insight.description,
            "severity": insight.severity,
            "metric": insight.metric,
            "value": insight.value,
            "change_pct": insight.change_pct,
        }
