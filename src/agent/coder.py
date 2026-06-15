import re
from typing import Dict, Optional
from src.agent.llm_client import LLMClient

class Coder:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def generate_sql(self, user_query: str, plan: str, schema: str) -> str:
        prompt = f"""
        You are a SQL expert. Based on the plan and schema, write a SQL query for DuckDB to answer the user's question.

        Schema:
        {schema}

        Plan:
        {plan}

        User Question:
        {user_query}

        Output only the SQL query, wrapped in ```sql ``` blocks.
        """
        messages = [
            {"role": "system", "content": "You are a SQL query generator."},
            {"role": "user", "content": prompt}
        ]
        response = self.llm_client.chat(messages)
        return self._extract_code(response, "sql")

    def generate_python(self, user_query: str, data_summary: str, plan: str) -> str:
        prompt = f"""
        You are a Python data visualization expert. Write Python code using Plotly to visualize the data.
        Assume the data is available in a pandas DataFrame named 'df'.

        Data Summary:
        {data_summary}

        Plan:
        {plan}

        User Question:
        {user_query}

        Output only the Python code, wrapped in ```python ``` blocks.
        """
        messages = [
            {"role": "system", "content": "You are a Python code generator."},
            {"role": "user", "content": prompt}
        ]
        response = self.llm_client.chat(messages)
        return self._extract_code(response, "python")

    def _extract_code(self, text: str, lang: str) -> str:
        pattern = rf"```{lang}\s*(.*?)\s*```"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Fallback if no code blocks but looks like SQL
        if lang == "sql" and "SELECT" in text.upper():
            # Basic attempt to grab everything after SQL: prefix if present
            if "SQL:" in text:
                return text.split("SQL:")[1].strip().split(";")[0] + ";"
            return text.strip()

        return text.strip()
