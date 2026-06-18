"""Async orchestrator for parallel multi-agent execution.

Parallelizes:
- DomainDetector + TrendAgent + AnomalyAgent + CompareAgent (all run simultaneously)
- Streaming partial results as agents complete
- Early termination if sufficient insights found

Based on Microsoft Research: parallel multi-agent execution achieves 1.6-2.2x speedup.
"""
import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import time

import pandas as pd

from src.agent.llm_client import LLMClient
from src.insights.pipeline import (
    DomainDetector, TrendAgent, AnomalyAgent, CompareAgent,
    InsightSynthesizer, Insight
)
from src.utils import logger


@dataclass
class AgentResult:
    """Result from a single agent execution."""
    agent_name: str
    insights: List[Insight]
    execution_time_ms: float
    error: Optional[str] = None


class ParallelInsightOrchestrator:
    """Orchestrates insight agents in parallel with streaming."""

    def __init__(self, llm_client: LLMClient, max_workers: int = 4):
        self.llm_client = llm_client
        self.max_workers = max_workers
        self.domain_detector = DomainDetector(llm_client)
        self.trend_agent = TrendAgent()
        self.anomaly_agent = AnomalyAgent()
        self.compare_agent = CompareAgent()
        self.synthesizer = InsightSynthesizer(llm_client)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    async def run_parallel(self, df: pd.DataFrame, user_query: str,
                          date_col: Optional[str] = None,
                          metric_col: Optional[str] = None,
                          dimension_col: Optional[str] = None,
                          audience: str = "executive",
                          stream_callback: Optional[Callable] = None,
                          early_termination_threshold: int = 3) -> Dict[str, Any]:
        """Run insight pipeline in parallel with streaming.

        Args:
            df: DataFrame to analyze
            user_query: Original user query
            date_col: Date column name
            metric_col: Metric column name
            dimension_col: Dimension column name
            audience: Target audience
            stream_callback: Called with partial results as agents complete
            early_termination_threshold: Stop after N high-severity insights found

        Returns:
            Final results with all insights
        """
        start_time = time.time()

        # Phase 1: Domain detection (must complete first — other agents need it)
        domain = await self._run_async(
            self._detect_domain, df, user_query
        )

        if stream_callback:
            stream_callback({"phase": "domain_detected", "domain": domain})

        # Phase 2: Run analytical agents in parallel
        agent_tasks = []

        if date_col and metric_col:
            agent_tasks.append(self._run_agent_async(
                "trend", self.trend_agent.analyze, df, date_col, metric_col
            ))

        if metric_col:
            agent_tasks.append(self._run_agent_async(
                "anomaly", self.anomaly_agent.analyze, df, metric_col
            ))

        if metric_col and dimension_col:
            agent_tasks.append(self._run_agent_async(
                "compare", self.compare_agent.analyze, df, metric_col, dimension_col
            ))

        # Execute all agents in parallel
        agent_results = await asyncio.gather(*agent_tasks, return_exceptions=True)

        # Collect insights
        all_insights = []
        high_severity_count = 0

        for result in agent_results:
            if isinstance(result, Exception):
                logger.error(f"Agent failed: {result}")
                continue

            if stream_callback:
                stream_callback({
                    "phase": "agent_complete",
                    "agent": result.agent_name,
                    "insight_count": len(result.insights),
                    "time_ms": result.execution_time_ms,
                })

            for insight in result.insights:
                all_insights.append(insight)
                if insight.severity == "high":
                    high_severity_count += 1

            # Early termination check
            if high_severity_count >= early_termination_threshold:
                logger.info(f"Early termination: {high_severity_count} high-severity insights found")
                if stream_callback:
                    stream_callback({"phase": "early_termination", "reason": "sufficient_insights"})
                break

        # Phase 3: Synthesize (sequential — needs all insights)
        data_summary = f"Data has {len(df)} rows, {len(df.columns)} columns: {', '.join(df.columns)}"
        narrative = await self._run_async(
            self.synthesizer.synthesize, all_insights, user_query, data_summary
        )

        total_time = (time.time() - start_time) * 1000

        if stream_callback:
            stream_callback({"phase": "complete", "total_time_ms": total_time})

        return {
            "domain": domain,
            "insights": [self._insight_to_dict(i) for i in all_insights],
            "narrative": narrative,
            "execution_time_ms": total_time,
            "agents_used": len([r for r in agent_results if not isinstance(r, Exception)]),
            "early_terminated": high_severity_count >= early_termination_threshold,
        }

    async def _detect_domain(self, df: pd.DataFrame, user_query: str) -> str:
        """Run domain detection in async context."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self.domain_detector.detect, df, user_query
        )

    async def _run_agent_async(self, name: str, agent_func, *args) -> AgentResult:
        """Run an agent function asynchronously."""
        start = time.time()
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(self._executor, agent_func, *args)

            insights = []
            if isinstance(result, list):
                insights = result
            elif result is not None:
                insights = [result]

            return AgentResult(
                agent_name=name,
                insights=insights,
                execution_time_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return AgentResult(
                agent_name=name,
                insights=[],
                execution_time_ms=(time.time() - start) * 1000,
                error=str(e),
            )

    async def _run_async(self, func, *args):
        """Run a synchronous function asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    @staticmethod
    def _insight_to_dict(insight: Insight) -> Dict:
        return {
            "type": insight.type.value,
            "title": insight.title,
            "description": insight.description,
            "severity": insight.severity,
            "metric": insight.metric,
            "value": insight.value,
            "change_pct": insight.change_pct,
        }


class StreamingResponseManager:
    """Manages streaming responses for real-time UI updates."""

    def __init__(self):
        self._chunks: List[Dict] = []

    def add_chunk(self, chunk: Dict):
        """Add a response chunk."""
        self._chunks.append({
            "timestamp": time.time(),
            **chunk
        })

    def get_stream(self) -> List[Dict]:
        """Get all chunks for streaming."""
        return self._chunks

    def format_sse(self, chunk: Dict) -> str:
        """Format chunk as Server-Sent Events."""
        import json
        return f"data: {json.dumps(chunk)}\n\n"
