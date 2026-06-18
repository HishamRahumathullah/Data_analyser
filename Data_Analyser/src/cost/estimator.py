"""Cost estimation and budget guardrails for LLM queries.

Prevents runaway API costs by:
- Estimating cost before execution
- Scoring query complexity
- Requiring confirmation for expensive queries
- Tracking cumulative spend per user
"""
import time
from typing import Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum

from src.utils import logger


class ComplexityLevel(Enum):
    SIMPLE = "simple"      # < $0.50, < 5s
    MODERATE = "moderate"  # $0.50-$2.00, 5-15s
    COMPLEX = "complex"    # $2.00-$5.00, 15-30s
    EXTREME = "extreme"    # > $5.00, > 30s


@dataclass
class CostEstimate:
    """Cost estimate for a query."""
    estimated_cost_usd: float
    estimated_time_ms: int
    complexity: ComplexityLevel
    llm_calls: int
    tokens_estimate: int
    requires_confirmation: bool
    warning_message: Optional[str] = None


class QueryComplexityScorer:
    """Scores query complexity based on multiple factors."""

    def __init__(self):
        # Cost per 1K tokens (approximate OpenAI GPT-4 pricing)
        self.cost_per_1k_input = 0.01   # $0.01 per 1K input tokens
        self.cost_per_1k_output = 0.03  # $0.03 per 1K output tokens

    def score(self, user_query: str, route: str, has_visualization: bool = False,
              has_analysis: bool = False, data_size_estimate: int = 100) -> ComplexityLevel:
        """Score query complexity from 0-100.

        Factors:
        - Query length and specificity
        - Number of implied operations
        - Route type (ANALYSIS > VISUALIZATION > DATA_QUERY)
        - Data size
        - Multi-step requirements
        """
        score = 0

        # Base complexity by route
        route_scores = {
            "DATA_QUERY": 10,
            "VISUALIZATION": 25,
            "ANALYSIS": 40,
            "GENERAL": 5,
        }
        score += route_scores.get(route, 10)

        # Query length and complexity
        words = len(user_query.split())
        score += min(words * 2, 30)  # Longer queries = more complex

        # Specific complexity indicators
        indicators = {
            "compare": 10,
            "trend": 10,
            "forecast": 15,
            "predict": 15,
            "correlation": 15,
            "all time": 10,
            "every": 10,
            "history": 5,
            "join": 10,
            "merge": 10,
            "segment": 5,
            "breakdown": 5,
        }

        q_lower = user_query.lower()
        for indicator, points in indicators.items():
            if indicator in q_lower:
                score += points

        # Data size factor
        if data_size_estimate > 10000:
            score += 15
        elif data_size_estimate > 1000:
            score += 5

        # Multi-step
        if has_visualization and has_analysis:
            score += 15

        # Classify
        if score >= 70:
            return ComplexityLevel.EXTREME
        elif score >= 50:
            return ComplexityLevel.COMPLEX
        elif score >= 25:
            return ComplexityLevel.MODERATE
        else:
            return ComplexityLevel.SIMPLE

    def estimate_cost(self, user_query: str, route: str, 
                      data_size_estimate: int = 100) -> CostEstimate:
        """Estimate cost and time for a query.

        Returns:
            CostEstimate with all details
        """
        complexity = self.score(user_query, route, data_size_estimate=data_size_estimate)

        # Estimate tokens
        query_tokens = len(user_query.split()) * 1.5  # Rough estimate: 1.5 tokens per word
        system_prompt_tokens = 500  # Base system prompt
        schema_tokens = 1000  # Schema context

        # Additional tokens by complexity
        complexity_multipliers = {
            ComplexityLevel.SIMPLE: 1.0,
            ComplexityLevel.MODERATE: 2.0,
            ComplexityLevel.COMPLEX: 3.5,
            ComplexityLevel.EXTREME: 5.0,
        }

        multiplier = complexity_multipliers[complexity]
        total_input_tokens = (query_tokens + system_prompt_tokens + schema_tokens) * multiplier
        estimated_output_tokens = 500 * multiplier

        # Cost calculation
        input_cost = (total_input_tokens / 1000) * self.cost_per_1k_input
        output_cost = (estimated_output_tokens / 1000) * self.cost_per_1k_output
        total_cost = input_cost + output_cost

        # Time estimate (seconds)
        time_estimates = {
            ComplexityLevel.SIMPLE: 3000,
            ComplexityLevel.MODERATE: 8000,
            ComplexityLevel.COMPLEX: 20000,
            ComplexityLevel.EXTREME: 45000,
        }
        estimated_time = time_estimates[complexity]

        # LLM calls estimate
        llm_calls = {
            ComplexityLevel.SIMPLE: 2,
            ComplexityLevel.MODERATE: 4,
            ComplexityLevel.COMPLEX: 6,
            ComplexityLevel.EXTREME: 10,
        }

        # Require confirmation for expensive queries
        requires_confirmation = total_cost > 5.0 or complexity == ComplexityLevel.EXTREME

        warning = None
        if complexity == ComplexityLevel.EXTREME:
            warning = (f"This is a complex query estimated to cost ${total_cost:.2f} "
                      f"and take {estimated_time/1000:.0f}s. Please confirm.")
        elif total_cost > 2.0:
            warning = f"This query is estimated to cost ${total_cost:.2f}. Continue?"

        return CostEstimate(
            estimated_cost_usd=round(total_cost, 2),
            estimated_time_ms=estimated_time,
            complexity=complexity,
            llm_calls=llm_calls[complexity],
            tokens_estimate=int(total_input_tokens + estimated_output_tokens),
            requires_confirmation=requires_confirmation,
            warning_message=warning,
        )


class BudgetManager:
    """Manages per-user and global budgets."""

    def __init__(self, default_user_budget: float = 50.0, global_daily_budget: float = 1000.0):
        self.default_user_budget = default_user_budget
        self.global_daily_budget = global_daily_budget
        self._user_spent: Dict[str, float] = {}
        self._global_spent_today: float = 0.0
        self._last_reset: float = time.time()

    def can_spend(self, user_id: str, amount: float) -> bool:
        """Check if user can spend the estimated amount."""
        self._reset_if_new_day()

        user_spent = self._user_spent.get(user_id, 0.0)

        if user_spent + amount > self.default_user_budget:
            logger.warning(f"User {user_id} budget exceeded: ${user_spent:.2f} + ${amount:.2f} > ${self.default_user_budget:.2f}")
            return False

        if self._global_spent_today + amount > self.global_daily_budget:
            logger.warning(f"Global budget exceeded: ${self._global_spent_today:.2f} + ${amount:.2f} > ${self.global_daily_budget:.2f}")
            return False

        return True

    def record_spend(self, user_id: str, amount: float) -> None:
        """Record actual spend."""
        self._user_spent[user_id] = self._user_spent.get(user_id, 0.0) + amount
        self._global_spent_today += amount
        logger.info(f"Recorded spend: user={user_id}, amount=${amount:.4f}, user_total=${self._user_spent[user_id]:.2f}")

    def get_user_stats(self, user_id: str) -> Dict:
        """Get spending stats for a user."""
        spent = self._user_spent.get(user_id, 0.0)
        return {
            "user_id": user_id,
            "spent_today": round(spent, 2),
            "budget": self.default_user_budget,
            "remaining": round(self.default_user_budget - spent, 2),
            "percentage_used": round((spent / self.default_user_budget) * 100, 1),
        }

    def get_global_stats(self) -> Dict:
        """Get global spending stats."""
        return {
            "spent_today": round(self._global_spent_today, 2),
            "daily_budget": self.global_daily_budget,
            "remaining": round(self.global_daily_budget - self._global_spent_today, 2),
            "percentage_used": round((self._global_spent_today / self.global_daily_budget) * 100, 1),
        }

    def _reset_if_new_day(self) -> None:
        """Reset daily counters if it's a new day."""
        now = time.time()
        if now - self._last_reset > 86400:  # 24 hours
            self._user_spent.clear()
            self._global_spent_today = 0.0
            self._last_reset = now
            logger.info("Daily budget counters reset")


class CostGuardrail:
    """Main interface for cost estimation and guardrails."""

    def __init__(self):
        self.scorer = QueryComplexityScorer()
        self.budget = BudgetManager()

    def check_query(self, user_id: str, user_query: str, route: str,
                    data_size_estimate: int = 100) -> Dict[str, Any]:
        """Check if query is allowed and estimate cost.

        Returns:
            Dict with 'allowed', 'estimate', 'budget_status'
        """
        estimate = self.scorer.estimate_cost(user_query, route, data_size_estimate)

        allowed = self.budget.can_spend(user_id, estimate.estimated_cost_usd)

        budget_status = self.budget.get_user_stats(user_id)

        return {
            "allowed": allowed and not estimate.requires_confirmation,
            "requires_confirmation": estimate.requires_confirmation,
            "estimate": {
                "cost_usd": estimate.estimated_cost_usd,
                "time_ms": estimate.estimated_time_ms,
                "complexity": estimate.complexity.value,
                "llm_calls": estimate.llm_calls,
                "tokens": estimate.tokens_estimate,
                "warning": estimate.warning_message,
            },
            "budget_status": budget_status,
        }

    def record_actual_cost(self, user_id: str, actual_cost: float) -> None:
        """Record actual cost after execution."""
        self.budget.record_spend(user_id, actual_cost)

    def get_stats(self) -> Dict:
        """Get all cost stats."""
        return {
            "global": self.budget.get_global_stats(),
            "scorer": self.scorer,
        }
