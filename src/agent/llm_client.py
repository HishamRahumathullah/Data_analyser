"""Production LLM client with error handling, retries, and fallback strategies."""

import os
import time
import json
import re
from typing import List, Dict, Any, Optional, Callable
from functools import wraps

import requests

from config.settings import LLMConfig
from src.utils import logger, log_llm_call


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator for retrying with exponential backoff."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.RequestException, requests.Timeout) as e:
                    last_exception = e
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"LLM request failed (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
            raise last_exception

        return wrapper

    return decorator


class LLMClient:
    """Production LLM client with multiple provider support."""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig.from_env()
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        if self.config.api_key:
            self._session.headers.update(
                {"Authorization": f"Bearer {self.config.api_key}"}
            )

    def chat(
        self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None
    ) -> str:
        """Send chat completion request with error handling and retries.

        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt to prepend

        Returns:
            Generated text response

        Raises:
            LLMError: If all retries fail or response is invalid
        """
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        start_time = time.time()

        try:
            if self.config.provider == "mock":
                response = self._mock_response(messages)
            elif self.config.provider == "ollama":
                response = self._ollama_chat(messages)
            elif self.config.provider == "vllm":
                response = self._vllm_chat(messages)
            elif self.config.provider == "openai":
                response = self._openai_chat(messages)
            else:
                raise LLMError(f"Unknown provider: {self.config.provider}")

            latency = (time.time() - start_time) * 1000
            log_llm_call(
                provider=self.config.provider,
                model=self.config.model,
                latency_ms=latency,
                success=True,
            )

            return response

        except Exception as e:
            latency = (time.time() - start_time) * 1000
            log_llm_call(
                provider=self.config.provider,
                model=self.config.model,
                latency_ms=latency,
                success=False,
                error=str(e),
            )
            logger.error(f"LLM call failed after all retries: {e}")
            raise LLMError(f"LLM request failed: {str(e)}") from e

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def _ollama_chat(self, messages: List[Dict[str, str]]) -> str:
        """Chat with Ollama API."""
        url = f"{self.config.api_url}/api/chat"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.config.temperature},
        }

        response = self._session.post(url, json=payload, timeout=self.config.timeout)
        response.raise_for_status()

        data = response.json()
        if "message" not in data or "content" not in data["message"]:
            raise LLMError(f"Invalid Ollama response format: {data}")

        return data["message"]["content"]

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def _vllm_chat(self, messages: List[Dict[str, str]]) -> str:
        """Chat with vLLM API."""
        url = f"{self.config.api_url}/v1/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }

        response = self._session.post(url, json=payload, timeout=self.config.timeout)
        response.raise_for_status()

        data = response.json()
        if "choices" not in data or not data["choices"]:
            raise LLMError(f"Invalid vLLM response format: {data}")

        return data["choices"][0]["message"]["content"]

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def _openai_chat(self, messages: List[Dict[str, str]]) -> str:
        """Chat with OpenAI API."""
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }

        response = self._session.post(url, json=payload, timeout=self.config.timeout)
        response.raise_for_status()

        data = response.json()
        if "choices" not in data or not data["choices"]:
            raise LLMError(f"Invalid OpenAI response format: {data}")

        return data["choices"][0]["message"]["content"]

    def _mock_response(self, messages: List[Dict[str, str]]) -> str:
        """Smart mock that uses query context for better responses."""
        last_message = messages[-1]["content"] if messages else ""
        last_lower = last_message.lower()

        # Detect intent from user query
        if "router" in last_lower or "classify" in last_lower:
            # Extract ONLY the actual user query, not the prompt template
            user_query_part = ""
            if "User Query:" in last_message:
                user_query_part = (
                    last_message.split("User Query:")[-1]
                    .split("Category:")[0]
                    .strip()
                    .lower()
                )
            else:
                user_query_part = last_lower

            # Now match against ONLY the user's query, not the examples
            if any(
                word in user_query_part
                for word in [
                    "plot",
                    "chart",
                    "graph",
                    "visualize",
                    "show me a chart",
                    "show me a graph",
                    "create a chart",
                    "draw a",
                ]
            ):
                return "VISUALIZATION"
            elif any(
                word in user_query_part
                for word in [
                    "how many",
                    "how much",
                    "total",
                    "sum",
                    "average",
                    "count",
                    "what is the",
                    "what are the",
                    "list",
                    "find",
                    "get",
                    "retrieve",
                    "show me",
                ]
            ):
                return "DATA_QUERY"
            elif any(
                word in user_query_part
                for word in [
                    "why",
                    "trend",
                    "compare",
                    "comparison",
                    "analysis",
                    "insight",
                    "anomaly",
                    "forecast",
                    "predict",
                    "correlation",
                    "what if",
                    "should we",
                    "recommend",
                    "root cause",
                    "factor",
                    "declining",
                    "going down",
                    "down",
                ]
            ):
                return "ANALYSIS"
            else:
                return "GENERAL"

        if "planner" in last_lower or "plan" in last_lower:
            return self._generate_mock_plan(last_message)

        if "sql" in last_lower or "select" in last_lower or "query" in last_lower:
            return self._generate_mock_sql(last_message)

        if (
            "python" in last_lower
            or "plotly" in last_lower
            or "visualization" in last_lower
            or "chart" in last_lower
        ):
            return self._generate_mock_viz(last_message)

        return self._generate_mock_general(last_message)

    def _generate_mock_plan(self, query: str) -> str:
        """Generate a context-aware execution plan."""
        q = query.lower()
        if "sales" in q and "region" in q:
            return """1. Query the sales table filtering by the specified region
2. Join with customers table to get segment information
3. Aggregate sales amounts by customer segment
4. Calculate total revenue and average order value
5. Return results with regional context"""
        elif "total" in q or "sum" in q:
            return """1. Identify the relevant table and metric
2. Apply any filters from the query
3. Aggregate using SUM/AVG/COUNT as appropriate
4. Format results for presentation"""
        else:
            return """1. Understand the user's data request
2. Identify relevant tables and columns
3. Construct appropriate SQL query
4. Execute and validate results
5. Present findings with context"""

    def _generate_mock_sql(self, query: str) -> str:
        """Generate context-aware SQL."""
        q = query.lower()

        if "north" in q and "sales" in q:
            return """SELECT s.*, c.name, c.segment 
FROM sales s 
JOIN customers c ON s.customer_id = c.customer_id 
WHERE s.region = 'North' 
ORDER BY s.sale_date;"""
        elif "total" in q and "region" in q:
            return """SELECT region, SUM(amount) as total_sales, COUNT(*) as order_count
FROM sales 
GROUP BY region 
ORDER BY total_sales DESC;"""
        elif "product" in q:
            return """SELECT p.name, p.category, SUM(s.amount) as revenue, SUM(s.quantity) as units_sold
FROM sales s
JOIN products p ON s.product_id = p.product_id
GROUP BY p.name, p.category
ORDER BY revenue DESC;"""
        elif "customer" in q and "enterprise" in q:
            return """SELECT c.name, c.segment, c.employees, SUM(s.amount) as total_spent
FROM sales s
JOIN customers c ON s.customer_id = c.customer_id
WHERE c.segment = 'Enterprise'
GROUP BY c.name, c.segment, c.employees
ORDER BY total_spent DESC;"""
        else:
            return "SELECT * FROM sales LIMIT 10;"

    def _generate_mock_viz(self, query: str) -> str:
        """Generate context-aware visualization code."""
        q = query.lower()

        if "region" in q:
            return """import plotly.express as px

# Aggregate sales by region
region_sales = df.groupby('region')['amount'].sum().reset_index()
region_sales = region_sales.sort_values('amount', ascending=True)

fig = px.bar(
    region_sales, 
    x='amount', 
    y='region',
    orientation='h',
    title='Total Sales by Region',
    labels={'amount': 'Revenue ($)', 'region': 'Region'},
    color='amount',
    color_continuous_scale='Blues',
    text='amount'
)
fig.update_traces(texttemplate='$%{text:,.0f}', textposition='outside')
fig.update_layout(showlegend=False, height=400)
"""
        elif "trend" in q or "time" in q or "month" in q:
            return """import plotly.express as px

# Ensure date column is datetime
df['sale_date'] = pd.to_datetime(df['sale_date'])

# Group by date
daily_sales = df.groupby('sale_date')['amount'].sum().reset_index()

fig = px.line(
    daily_sales,
    x='sale_date',
    y='amount',
    title='Sales Trend Over Time',
    labels={'sale_date': 'Date', 'amount': 'Revenue ($)'},
    markers=True
)
fig.update_layout(height=400)
"""
        else:
            return """import plotly.express as px

fig = px.bar(df, x=df.columns[0], y=df.columns[-1], title='Data Visualization')
fig.update_layout(height=400)
"""

    def _generate_mock_general(self, query: str) -> str:
        """Generate general analytical response."""
        q = query.lower()
        if "north" in q:
            return (
                "The North region includes New York (NY), New Jersey (NJ), and Connecticut (CT). "
                "In our dataset, North region sales are driven by Enterprise customers like Alice Smith. "
                "The region shows strong online channel performance."
            )
        elif "enterprise" in q:
            return (
                "Enterprise customers are defined as those with more than 500 employees. "
                "In our dataset, Enterprise customers (Alice Smith with 1,200 employees, "
                "Eva Martinez with 2,500 employees) represent high-value accounts."
            )
        else:
            return (
                "I can help you analyze sales data, customer segments, and regional performance. "
                "Ask me about specific metrics, trends, or visualizations."
            )


class LLMError(Exception):
    """Custom exception for LLM-related errors."""

    pass
