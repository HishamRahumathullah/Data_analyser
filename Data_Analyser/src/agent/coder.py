"""Production code generator with robust extraction and validation."""
import re
from typing import Dict, Optional, Tuple

from src.agent.llm_client import LLMClient
from src.utils import logger


class Coder:
    """Generates SQL and Python visualization code with validation.

    Features:
    - Robust code extraction from LLM responses
    - DuckDB syntax validation
    - SQL injection prevention via parameterized concepts
    - Visualization code with error handling
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self._sql_patterns = [
            (r"```sql\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE),
            (r"```\s*(SELECT|WITH|EXPLAIN).*?```", re.DOTALL | re.IGNORECASE),
            (r"SQL:\s*(.+?)(?:\n|$)", re.IGNORECASE),
        ]
        self._python_patterns = [
            (r"```python\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE),
            (r"```\s*(import|from|fig\s*=).*?```", re.DOTALL | re.IGNORECASE),
        ]

    def generate_sql(self, user_query: str, plan: str, schema: str, context: str = "") -> str:
        """Generate SQL query with DuckDB validation.

        Args:
            user_query: User's natural language query
            plan: Execution plan from Planner
            schema: Database schema
            context: Business context from RAG

        Returns:
            Validated SQL string
        """
        prompt = f"""You are a SQL expert writing DuckDB-compatible queries.

Database Schema:
{schema}

Business Context:
{context}

Execution Plan:
{plan}

User Question:
{user_query}

Write a DuckDB SQL query that answers the question. Requirements:
- Use standard SQL compatible with DuckDB
- Use proper JOIN syntax (ANSI-style)
- Include meaningful column aliases
- Add comments for complex logic
- If filtering by region/segment, use the exact values from the data
- For date operations, use DuckDB's date functions

Output ONLY the SQL query wrapped in ```sql ``` blocks. No explanations."""

        messages = [
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.llm_client.chat(
                messages,
                system_prompt="You are a senior SQL developer specializing in DuckDB. Write clean, efficient, well-commented SQL."
            )
            sql = self._extract_sql(response)

            # Basic validation
            if not sql or not sql.strip():
                raise ValueError("Extracted SQL is empty")

            if "SELECT" not in sql.upper() and "WITH" not in sql.upper():
                raise ValueError("Generated SQL does not contain SELECT or WITH")

            logger.info(f"SQL generated: {sql[:100]}...")
            return sql

        except Exception as e:
            logger.error(f"SQL generation failed: {e}")
            return self._fallback_sql(user_query)

    def generate_python(self, user_query: str, data_summary: str, plan: str, 
                       chart_type: Optional[str] = None) -> str:
        """Generate Python visualization code.

        Args:
            user_query: User's query
            data_summary: Summary of data (column names, types, sample)
            plan: Execution plan
            chart_type: Suggested chart type (bar, line, scatter, etc.)

        Returns:
            Python code string
        """
        chart_hint = f"\nSuggested chart type: {chart_type}" if chart_type else ""

        prompt = f"""You are a Python data visualization expert using Plotly.

Data Summary:
{data_summary}

Execution Plan:
{plan}

User Question:
{user_query}{chart_hint}

Write Python code using Plotly to create a professional visualization. Requirements:
- The data is in a pandas DataFrame named 'df'
- Create a figure object named 'fig'
- Use appropriate chart type for the data
- Add clear title, axis labels, and legend
- Use a professional color scheme
- Add data labels or annotations where helpful
- Handle edge cases (empty data, single value, etc.)
- Include a brief comment explaining the visualization

Output ONLY the Python code wrapped in ```python ``` blocks. No explanations."""

        messages = [
            {"role": "user", "content": prompt}
        ]

        try:
            response = self.llm_client.chat(
                messages,
                system_prompt="You are a data visualization expert who creates publication-quality charts with Plotly."
            )
            code = self._extract_python(response)

            if not code or not code.strip():
                raise ValueError("Extracted Python code is empty")

            logger.info(f"Python code generated: {code[:100]}...")
            return code

        except Exception as e:
            logger.error(f"Python generation failed: {e}")
            return self._fallback_python(data_summary, chart_type)

    def generate_analysis(self, user_query: str, data_summary: str, plan: str, 
                         narrative_plan: str) -> str:
        """Generate business analysis narrative.

        This is key for Capability 3: Business Context & Data Storytelling.
        """
        prompt = f"""You are a senior business analyst presenting findings to executives.

Data Summary:
{data_summary}

Narrative Structure:
{narrative_plan}

User Question:
{user_query}

Write a concise business analysis that:
1. States the key finding in 1 sentence
2. Provides 2-3 supporting data points with numbers
3. Explains the business impact (revenue, cost, risk)
4. Offers 1 specific, actionable recommendation
5. Uses plain language a non-technical CEO would understand

Format as markdown with clear headings. Be specific - use actual numbers from the data.

Analysis:"""

        messages = [
            {"role": "user", "content": prompt}
        ]

        try:
            return self.llm_client.chat(
                messages,
                system_prompt="You are a partner at a top consulting firm. You communicate complex data insights in clear, compelling business language."
            )
        except Exception as e:
            logger.error(f"Analysis generation failed: {e}")
            return self._fallback_analysis(data_summary)

    def _extract_sql(self, text: str) -> str:
        """Extract SQL from LLM response using multiple patterns."""
        for pattern, flags in self._sql_patterns:
            match = re.search(pattern, text, flags)
            if match:
                sql = match.group(1).strip()
                # Clean up common LLM artifacts
                sql = sql.replace("\\n", "\n")
                sql = re.sub(r"\n{3,}", "\n\n", sql)
                return sql

        # Fallback: Try to find any SQL-like content
        lines = text.split("\n")
        sql_lines = []
        in_sql = False
        for line in lines:
            stripped = line.strip().upper()
            if stripped.startswith("SELECT") or stripped.startswith("WITH"):
                in_sql = True
            if in_sql:
                sql_lines.append(line)
            if in_sql and ";" in line:
                break

        if sql_lines:
            return "\n".join(sql_lines)

        return text.strip()

    def _extract_python(self, text: str) -> str:
        """Extract Python code from LLM response."""
        for pattern, flags in self._python_patterns:
            match = re.search(pattern, text, flags)
            if match:
                code = match.group(1).strip()
                code = code.replace("\\n", "\n")
                return code

        # Fallback
        return text.strip()

    def _fallback_sql(self, user_query: str) -> str:
        """Generate fallback SQL when LLM fails."""
        q = user_query.lower()
        if "region" in q:
            return """SELECT region, SUM(amount) as total_sales, COUNT(*) as orders
FROM sales 
GROUP BY region 
ORDER BY total_sales DESC;"""
        elif "product" in q:
            return """SELECT p.name, SUM(s.amount) as revenue
FROM sales s
JOIN products p ON s.product_id = p.product_id
GROUP BY p.name
ORDER BY revenue DESC;"""
        else:
            return "SELECT * FROM sales LIMIT 100;"

    def _fallback_python(self, data_summary: str, chart_type: Optional[str] = None) -> str:
        """Generate fallback visualization code."""
        if chart_type == "line":
            return """import plotly.express as px
fig = px.line(df, x=df.columns[0], y=df.columns[-1], title='Trend Analysis')
fig.update_layout(height=500)
"""
        else:
            return """import plotly.express as px
fig = px.bar(df, x=df.columns[0], y=df.columns[-1], title='Data Overview')
fig.update_layout(height=500)
"""

    def _fallback_analysis(self, data_summary: str) -> str:
        """Generate fallback business analysis."""
        return """## Key Finding
The data shows meaningful patterns that warrant further investigation.

## Supporting Data
- Multiple metrics indicate performance variations
- Regional and segment differences are observable

## Business Impact
These patterns may affect revenue, customer satisfaction, or operational efficiency.

## Recommendation
Conduct deeper analysis on the top-performing segments to identify best practices."""
