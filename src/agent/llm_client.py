import os
import requests
import json
from typing import List, Dict, Any, Optional

class LLMClient:
    def __init__(self, provider: str = "mock", api_url: Optional[str] = None, model: str = "qwen3.6-27b"):
        self.provider = provider
        self.api_url = api_url
        self.model = model

    def chat(self, messages: List[Dict[str, str]]) -> str:
        if self.provider == "mock":
            return self._mock_response(messages)
        elif self.provider == "ollama":
            return self._ollama_chat(messages)
        elif self.provider == "vllm":
            return self._vllm_chat(messages)
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def _mock_response(self, messages: List[Dict[str, str]]) -> str:
        # Simple heuristic-based mock for demonstration
        system_msg = next((m['content'] for m in messages if m['role'] == 'system'), "").lower()
        last_message = messages[-1]['content'].lower()

        if "router" in system_msg:
            if "plot" in last_message or "chart" in last_message:
                return "VISUALIZATION"
            return "DATA_QUERY"

        if "planner" in system_msg:
            return "1. Query sales data. 2. Aggregate if needed. 3. Return results."

        if "sql" in system_msg:
            return "```sql\nSELECT * FROM sales LIMIT 10;\n```"

        if "python" in system_msg:
            return "```python\nimport plotly.express as px\nfig = px.bar(df, x='region', y='amount')\n```"

        if "select" in last_message and "sales" in last_message:
            return "```sql\nSELECT * FROM sales LIMIT 5;\n```"
        elif "plot" in last_message or "chart" in last_message:
            return "```python\nimport plotly.express as px\nfig = px.bar(df, x='region', y='amount')\n```"

        return "I am a mock AI analyst. I can help you with SQL queries and Python analysis."

    def _ollama_chat(self, messages: List[Dict[str, str]]) -> str:
        url = f"{self.api_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()['message']['content']

    def _vllm_chat(self, messages: List[Dict[str, str]]) -> str:
        url = f"{self.api_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']

if __name__ == "__main__":
    client = LLMClient()
    print(client.chat([{"role": "user", "content": "Show me the sales data"}]))
