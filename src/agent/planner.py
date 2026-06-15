from typing import List, Dict
from src.agent.llm_client import LLMClient

class Planner:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def generate_plan(self, user_query: str, schema: str) -> str:
        prompt = f"""
        You are an expert Data Analyst. Your task is to create a plan to answer the user's question using the provided database schema.

        Database Schema:
        {schema}

        User Question:
        {user_query}

        Provide a step-by-step plan. If it requires data, specify which tables to query. If it requires visualization, specify what to plot.
        """
        messages = [
            {"role": "system", "content": "You are a helpful data analyst planner."},
            {"role": "user", "content": prompt}
        ]
        return self.llm_client.chat(messages)
