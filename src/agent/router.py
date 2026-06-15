from typing import Dict
from src.agent.llm_client import LLMClient

class Router:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def route(self, user_query: str) -> str:
        # For simple cases, we can use heuristics.
        # For production, we'd use a small model like Qwen 8B.

        prompt = f"""
        Classify the following user query into one of these categories:
        - DATA_QUERY: Needs SQL to fetch data.
        - VISUALIZATION: Needs Python to create a chart.
        - GENERAL: General question about the data or capabilities.

        User Query: {user_query}

        Output only the category name.
        """
        messages = [
            {"role": "system", "content": "You are a query router."},
            {"role": "user", "content": prompt}
        ]
        response = self.llm_client.chat(messages).strip().upper()

        if "DATA_QUERY" in response:
            return "DATA_QUERY"
        elif "VISUALIZATION" in response:
            return "VISUALIZATION"
        else:
            return "GENERAL"
