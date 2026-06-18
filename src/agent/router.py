"""Production query router with prompt injection detection."""
import re
from typing import Dict, Optional

from src.agent.llm_client import LLMClient
from src.utils import logger, log_security_event


class Router:
    """Routes user queries to appropriate processing pipeline.

    Detects prompt injection attempts and classifies queries into:
    - DATA_QUERY: Needs SQL to fetch data
    - VISUALIZATION: Needs chart/dashboard generation
    - ANALYSIS: Needs statistical/business analysis
    - GENERAL: General questions about data or capabilities
    """

    # Prompt injection patterns
    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"forget\s+(everything|all)\s+(you\s+)?(know|learned)",
        r"you\s+are\s+now\s+a",
        r"new\s+role:\s*",
        r"system\s*:\s*",
        r"<\|system\|>",
        r"\{\{.*?\}\}",  # Template injection
        r"\[\[.*?\]\]",
        r"ignore\s+above",
        r"disregard\s+(the\s+)?above",
        r"do\s+not\s+(tell|inform|warn)",
        r"secret\s*key",
        r"api\s*key",
        r"password",
        r"drop\s+table",
        r"delete\s+from",
    ]

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def route(self, user_query: str) -> str:
        """Route user query to appropriate pipeline.

        Args:
            user_query: Raw user query string

        Returns:
            Route category: DATA_QUERY, VISUALIZATION, ANALYSIS, or GENERAL

        Raises:
            SecurityError: If prompt injection is detected
        """
        # Security check: Detect prompt injection
        if self._detect_injection(user_query):
            log_security_event(
                "prompt_injection_detected",
                {"query": user_query[:200]},
                severity="error"
            )
            raise SecurityError("Potentially malicious query detected. Please rephrase your question.")

        # Sanitize query for LLM
        sanitized = self._sanitize_query(user_query)

        # Use LLM for classification with structured prompt
        prompt = f"""Classify the following user query into EXACTLY ONE of these categories:
- DATA_QUERY: User wants specific data retrieved via SQL (e.g., "How many sales?", "Show me revenue by region", "What was last month's total?")
- VISUALIZATION: User wants a chart, graph, or dashboard (e.g., "Plot sales by region", "Create a bar chart", "Show me a trend line")
- ANALYSIS: User wants insights, trends, comparisons, or business analysis (e.g., "Why are sales down?", "Compare Q1 vs Q2", "What trends do you see?")
- GENERAL: General questions about data, capabilities, or definitions (e.g., "What data do you have?", "How does this work?", "What is the North region?")

IMPORTANT: Respond with ONLY the category name, nothing else.

User Query: {sanitized}

Category:"""

        messages = [
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.llm_client.chat(messages, system_prompt="You are a query classifier. Respond with exactly one word: DATA_QUERY, VISUALIZATION, ANALYSIS, or GENERAL.").strip().upper()

            # Exact matching (not substring)
            valid_routes = {"DATA_QUERY", "VISUALIZATION", "ANALYSIS", "GENERAL"}

            if response in valid_routes:
                logger.info(f"Query routed to: {response}", extra={"query": sanitized[:100], "route": response})
                return response

            # Fallback: Check if response contains exactly one valid route
            found_routes = [r for r in valid_routes if r in response]
            if len(found_routes) == 1:
                route = found_routes[0]
                logger.info(f"Query routed to: {route} (from partial match)", extra={"query": sanitized[:100], "route": route})
                return route

            # Heuristic fallback
            route = self._heuristic_route(sanitized)
            logger.warning(f"LLM returned invalid route '{response}', using heuristic: {route}")
            return route

        except Exception as e:
            logger.error(f"Routing failed: {e}, using heuristic fallback")
            return self._heuristic_route(sanitized)

    def _detect_injection(self, query: str) -> bool:
        """Detect potential prompt injection attempts."""
        query_lower = query.lower()
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, query_lower, re.IGNORECASE):
                return True

        # Check for excessive length (possible injection payload)
        if len(query) > 5000:
            return True

        # Check for multiple newlines with system-like content
        lines = query.split('\n')
        if len(lines) > 20:
            system_like_lines = sum(1 for line in lines if any(kw in line.lower() for kw in ['system', 'instruction', 'role', 'act as']))
            if system_like_lines > 5:
                return True

        return False

    def _sanitize_query(self, query: str) -> str:
        """Sanitize user query before sending to LLM."""
        # Remove null bytes
        query = query.replace('\x00', '')
        # Normalize whitespace
        query = ' '.join(query.split())
        # Truncate if extremely long
        if len(query) > 2000:
            query = query[:2000] + "... [truncated]"
        return query

    def _heuristic_route(self, query: str) -> str:
        """Fallback heuristic routing when LLM fails."""
        q = query.lower()

        # Visualization keywords
        viz_keywords = ['plot', 'chart', 'graph', 'visualize', 'visualization', 'dashboard', 
                       'bar chart', 'line chart', 'pie chart', 'scatter', 'histogram',
                       'show me a', 'create a chart', 'draw a']
        if any(kw in q for kw in viz_keywords):
            return "VISUALIZATION"

        # Analysis keywords
        analysis_keywords = ['why', 'trend', 'compare', 'comparison', 'analysis', 'insight',
                            'anomaly', 'forecast', 'predict', 'correlation', 'what if',
                            'should we', 'recommend', 'root cause', 'factor']
        if any(kw in q for kw in analysis_keywords):
            return "ANALYSIS"

        # Data query keywords
        data_keywords = ['how many', 'how much', 'what is', 'what are', 'show me', 'list',
                        'total', 'sum', 'average', 'count', 'find', 'get', 'retrieve',
                        'where', 'which', 'top', 'bottom', 'highest', 'lowest']
        if any(kw in q for kw in data_keywords):
            return "DATA_QUERY"

        return "GENERAL"


class SecurityError(Exception):
    """Raised when a security violation is detected."""
    pass
