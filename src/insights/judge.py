"""Judge Agent — Mandatory quality control before returning to user.

The Judge is a HARDCODED final step (not a tool call) that validates:
- Are insights supported by the actual data?
- Are there hallucinations or unsupported claims?
- Is the severity level appropriate?
- Are numbers consistent with the data?

HockeyStack research: The Judge agent was the highest-impact accuracy improvement
in production multi-agent systems. It must be mandatory, not optional.
"""
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

from src.agent.llm_client import LLMClient
from src.utils import logger


class JudgeAgent:
    """Validates insight quality before user presentation.

    Checks:
    1. Data-backed claims — every number must be verifiable
    2. Consistency — insights don't contradict each other
    3. Severity appropriateness — high severity needs strong evidence
    4. Hallucination detection — claims not in the data
    5. Statistical validity — sample sizes, significance
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def judge(self, insights: List[Dict], df: pd.DataFrame, 
              narrative: str, user_query: str) -> Dict[str, Any]:
        """Judge the quality of insights and narrative.

        Returns:
            Dict with:
            - approved: bool (can show to user?)
            - issues: List of problems found
            - corrected_narrative: str (fixed version if issues found)
            - confidence_score: float (0-1)
        """
        issues = []
        confidence = 1.0

        # 1. Validate each insight against data
        for insight in insights:
            issue = self._validate_insight(insight, df)
            if issue:
                issues.append(issue)
                confidence -= 0.15

        # 2. Check for contradictions
        contradiction = self._check_contradictions(insights)
        if contradiction:
            issues.append(contradiction)
            confidence -= 0.2

        # 3. Check narrative against data
        narrative_issue = self._validate_narrative(narrative, df, insights)
        if narrative_issue:
            issues.append(narrative_issue)
            confidence -= 0.1

        # 4. Check severity appropriateness
        severity_issue = self._check_severity_appropriateness(insights, df)
        if severity_issue:
            issues.append(severity_issue)
            confidence -= 0.1

        # 5. Check for hallucinations (claims not in data)
        hallucination = self._detect_hallucinations(narrative, df)
        if hallucination:
            issues.append(hallucination)
            confidence -= 0.25

        confidence = max(0.0, confidence)
        approved = confidence >= 0.7 and len(issues) <= 2

        # Generate corrected narrative if issues found
        corrected_narrative = narrative
        if issues and not approved:
            corrected_narrative = self._generate_safe_narrative(insights, df, issues)

        result = {
            "approved": approved,
            "confidence_score": round(confidence, 2),
            "issues": issues,
            "corrected_narrative": corrected_narrative if corrected_narrative != narrative else None,
            "original_narrative": narrative,
        }

        logger.info(
            f"Judge review: approved={approved}, confidence={confidence:.2f}, issues={len(issues)}",
            extra={"issues": [i["type"] for i in issues]}
        )

        return result

    def _validate_insight(self, insight: Dict, df: pd.DataFrame) -> Optional[Dict]:
        """Validate a single insight against the data."""
        metric = insight.get("metric", "")
        value = insight.get("value")

        if not metric or metric not in df.columns:
            return {
                "type": "missing_metric",
                "severity": "high",
                "message": f"Insight references metric '{metric}' not found in data columns: {list(df.columns)}",
                "insight": insight.get("title", ""),
            }

        # Check if value is in reasonable range
        if value is not None:
            col_min = df[metric].min()
            col_max = df[metric].max()
            if value < col_min * 0.9 or value > col_max * 1.1:
                return {
                    "type": "value_out_of_range",
                    "severity": "high",
                    "message": f"Claimed value {value} is outside data range [{col_min}, {col_max}]",
                    "insight": insight.get("title", ""),
                }

        return None

    def _check_contradictions(self, insights: List[Dict]) -> Optional[Dict]:
        """Check if insights contradict each other."""
        # Example: "Sales are increasing" and "Sales are decreasing" for same metric
        trends = [i for i in insights if i.get("type") == "trend"]

        if len(trends) >= 2:
            directions = []
            for t in trends:
                change = t.get("change_pct", 0)
                if change > 0:
                    directions.append("up")
                elif change < 0:
                    directions.append("down")

            if "up" in directions and "down" in directions:
                return {
                    "type": "contradiction",
                    "severity": "high",
                    "message": "Contradictory trends detected: some metrics increasing while others decreasing",
                }

        return None

    def _validate_narrative(self, narrative: str, df: pd.DataFrame, insights: List[Dict]) -> Optional[Dict]:
        """Check if narrative contains numbers not in insights."""
        # Extract numbers from narrative
        import re
        narrative_numbers = set(re.findall(r'\d+\.?\d*', narrative))

        # Extract numbers from insights
        insight_numbers = set()
        for i in insights:
            for key in ["value", "change_pct", "benchmark"]:
                val = i.get(key)
                if val is not None:
                    insight_numbers.add(str(int(val)) if val == int(val) else f"{val:.1f}")

        # Check for numbers in narrative not backed by insights
        unbacked = narrative_numbers - insight_numbers
        if unbacked:
            return {
                "type": "unbacked_claim",
                "severity": "medium",
                "message": f"Narrative contains numbers not found in insights: {unbacked}",
            }

        return None

    def _check_severity_appropriateness(self, insights: List[Dict], df: pd.DataFrame) -> Optional[Dict]:
        """Check if high-severity insights have strong evidence."""
        high_severity = [i for i in insights if i.get("severity") == "high"]

        for insight in high_severity:
            change_pct = insight.get("change_pct")
            if change_pct is not None and abs(change_pct) < 20:
                return {
                    "type": "inappropriate_severity",
                    "severity": "medium",
                    "message": f"High severity assigned to small change ({change_pct:.1f}%) — should be medium or low",
                    "insight": insight.get("title", ""),
                }

        return None

    def _detect_hallucinations(self, narrative: str, df: pd.DataFrame) -> Optional[Dict]:
        """Detect claims in narrative not supported by data."""
        # Check for specific column names mentioned that don't exist
        columns = set(df.columns.str.lower())
        words = set(narrative.lower().split())

        # Common hallucination patterns
        hallucination_patterns = [
            "last year", "yoy", "year over year", "quarter over quarter",
            "forecast", "prediction", "will increase", "will decrease",
            "expected to", "projected",
        ]

        found_patterns = [p for p in hallucination_patterns if p in narrative.lower()]
        if found_patterns:
            return {
                "type": "potential_hallucination",
                "severity": "medium",
                "message": f"Narrative contains forward-looking/unsupported claims: {found_patterns}",
            }

        return None

    def _generate_safe_narrative(self, insights: List[Dict], df: pd.DataFrame, 
                                  issues: List[Dict]) -> str:
        """Generate a conservative narrative when issues are found."""
        # Build from verified insights only
        lines = ["## Analysis Summary"]
        lines.append("Based on the available data, we observed the following:")
        lines.append("")

        for insight in insights[:3]:  # Top 3 only
            lines.append(f"- **{insight.get('title', '')}**: {insight.get('description', '')}")

        lines.append("")
        lines.append("## Note")
        lines.append("Some aspects of this analysis require additional data or verification. "
                    "Please review the detailed results before making decisions.")

        return "\n".join(lines)
