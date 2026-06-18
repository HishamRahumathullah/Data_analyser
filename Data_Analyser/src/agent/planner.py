"""Production planner with execution planning and narrative structure support."""
from typing import List, Dict, Optional

from src.agent.llm_client import LLMClient
from src.utils import logger


class Planner:
    """Generates execution plans and narrative structures for data analysis.

    Supports two modes:
    - Execution Plan: Step-by-step technical plan for SQL/code generation
    - Narrative Plan: Story structure for business communication
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def generate_plan(self, user_query: str, schema: str, context: str = "", route: str = "DATA_QUERY") -> Dict[str, str]:
        """Generate both execution and narrative plans.

        Args:
            user_query: User's natural language query
            schema: Database schema description
            context: RAG-retrieved business context
            route: Routed category (DATA_QUERY, VISUALIZATION, ANALYSIS, GENERAL)

        Returns:
            Dict with 'execution_plan', 'narrative_plan', 'tables_needed', 'metrics_needed'
        """
        # Generate execution plan
        execution_plan = self._generate_execution_plan(user_query, schema, context, route)

        # Generate narrative plan (for business storytelling)
        narrative_plan = self._generate_narrative_plan(user_query, context, route)

        # Extract tables and metrics needed
        tables_needed = self._extract_tables_from_plan(execution_plan, schema)
        metrics_needed = self._extract_metrics_from_query(user_query)

        logger.info(
            f"Plan generated for route: {route}",
            extra={"route": route, "tables": tables_needed, "metrics": metrics_needed}
        )

        return {
            "execution_plan": execution_plan,
            "narrative_plan": narrative_plan,
            "tables_needed": tables_needed,
            "metrics_needed": metrics_needed,
            "route": route,
        }

    def _generate_execution_plan(self, user_query: str, schema: str, context: str, route: str) -> str:
        """Generate technical execution plan."""
        prompt = f"""You are an expert Data Analyst. Create a precise execution plan to answer the user's question.

Database Schema:
{schema}

Business Context:
{context}

User Question:
{user_query}

Query Type: {route}

Create a step-by-step execution plan. Be specific about:
1. Which tables to query and why
2. What JOINs are needed (if any)
3. What aggregations or calculations to perform
4. What filters to apply
5. How to format the results

If visualization is needed, specify chart type and axes.
If analysis is needed, specify what comparisons or trends to look for.

Execution Plan:"""

        messages = [
            {"role": "user", "content": prompt}
        ]

        try:
            return self.llm_client.chat(
                messages,
                system_prompt="You are a senior data analyst who creates precise, actionable execution plans."
            )
        except Exception as e:
            logger.error(f"Execution plan generation failed: {e}")
            return self._fallback_execution_plan(user_query, route)

    def _generate_narrative_plan(self, user_query: str, context: str, route: str) -> str:
        """Generate narrative structure for business storytelling.

        This is the foundation for Capability 3: Business Context & Data Storytelling.
        """
        prompt = f"""You are a consultant presenting data insights to business leaders.

Business Context:
{context}

User Question:
{user_query}

Create a narrative plan that structures the answer as a business story:
1. CONTEXT: What business situation or question are we addressing?
2. DATA: What data points and metrics will illuminate this?
3. INSIGHT: What key finding or pattern should we highlight?
4. IMPACT: What is the business significance? (revenue, efficiency, risk)
5. RECOMMENDATION: What action should the business take?

Keep each section to 1-2 sentences. This will guide how we present findings.

Narrative Plan:"""

        messages = [
            {"role": "user", "content": prompt}
        ]

        try:
            return self.llm_client.chat(
                messages,
                system_prompt="You are a McKinsey consultant who structures data findings into compelling business narratives."
            )
        except Exception as e:
            logger.error(f"Narrative plan generation failed: {e}")
            return self._fallback_narrative_plan(user_query)

    def _fallback_execution_plan(self, user_query: str, route: str) -> str:
        """Fallback plan when LLM fails."""
        q = user_query.lower()

        if "sales" in q and "region" in q:
            return """1. Query sales table
2. Filter by specified region if mentioned
3. Aggregate sales amounts by relevant dimension
4. Join with customers/products if needed for context
5. Return formatted results"""
        elif "total" in q or "sum" in q:
            return """1. Identify the relevant table and metric column
2. Apply any filters from the query
3. Use SUM/AVG/COUNT as appropriate
4. Group by relevant dimensions
5. Return aggregated results"""
        else:
            return """1. Understand the user's data request
2. Identify relevant tables from schema
3. Construct appropriate SQL query
4. Execute and validate results
5. Present findings with context"""

    def _fallback_narrative_plan(self, user_query: str) -> str:
        """Fallback narrative when LLM fails."""
        return """1. CONTEXT: Understanding the business question about our data
2. DATA: Retrieving relevant metrics and dimensions
3. INSIGHT: Identifying key patterns in the data
4. IMPACT: Assessing business implications
5. RECOMMENDATION: Suggesting data-driven next steps"""

    def _extract_tables_from_plan(self, plan: str, schema: str) -> List[str]:
        """Extract table names mentioned in the plan."""
        tables = []
        schema_tables = [line.split(":")[0].replace("Table", "").strip() 
                        for line in schema.split("\n") if line.startswith("Table:")]

        for table in schema_tables:
            if table.lower() in plan.lower():
                tables.append(table)

        return tables

    def _extract_metrics_from_query(self, query: str) -> List[str]:
        """Extract metrics mentioned in the query."""
        metrics = []
        metric_keywords = {
            "sales": ["sales", "revenue", "amount"],
            "customers": ["customers", "users", "accounts"],
            "products": ["products", "items", "sku"],
            "performance": ["growth", "trend", "change", "rate"],
        }

        q = query.lower()
        for category, keywords in metric_keywords.items():
            if any(kw in q for kw in keywords):
                metrics.append(category)

        return metrics
