"""Query feedback system for self-improvement."""
import json
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

from src.utils import logger


@dataclass
class QueryFeedback:
    """User feedback on a query result."""
    query_id: str
    user_query: str
    sql: str
    route: str
    success: bool
    user_rating: Optional[int] = None  # 1-5
    user_comment: Optional[str] = None
    error_type: Optional[str] = None
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class FeedbackStore:
    """Stores and analyzes query feedback for continuous improvement."""

    def __init__(self, storage_path: str = "data/feedback.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._feedback: List[QueryFeedback] = []
        self._load()

    def add_feedback(self, feedback: QueryFeedback) -> None:
        """Add feedback entry."""
        self._feedback.append(feedback)
        self._append_to_storage(feedback)
        logger.info(f"Feedback recorded: query_id={feedback.query_id}, rating={feedback.user_rating}")

    def get_feedback_for_query(self, query_id: str) -> Optional[QueryFeedback]:
        """Get feedback for a specific query."""
        for fb in self._feedback:
            if fb.query_id == query_id:
                return fb
        return None

    def get_success_rate(self, route: Optional[str] = None) -> float:
        """Calculate success rate, optionally filtered by route."""
        feedbacks = self._feedback
        if route:
            feedbacks = [f for f in feedbacks if f.route == route]

        if not feedbacks:
            return 1.0

        successful = sum(1 for f in feedbacks if f.success)
        return successful / len(feedbacks)

    def get_common_errors(self, limit: int = 10) -> List[Dict]:
        """Get most common error types."""
        errors = {}
        for fb in self._feedback:
            if not fb.success and fb.error_type:
                errors[fb.error_type] = errors.get(fb.error_type, 0) + 1

        return [{"error_type": k, "count": v} for k, v in sorted(errors.items(), key=lambda x: x[1], reverse=True)[:limit]]

    def get_low_rated_queries(self, threshold: int = 3) -> List[QueryFeedback]:
        """Get queries rated below threshold."""
        return [f for f in self._feedback if f.user_rating and f.user_rating < threshold]

    def _load(self) -> None:
        """Load feedback from storage."""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r") as f:
                for line in f:
                    data = json.loads(line.strip())
                    self._feedback.append(QueryFeedback(**data))
            logger.info(f"Loaded {len(self._feedback)} feedback entries")
        except Exception as e:
            logger.error(f"Failed to load feedback: {e}")

    def _append_to_storage(self, feedback: QueryFeedback) -> None:
        """Append feedback to persistent storage."""
        with open(self.storage_path, "a") as f:
            f.write(json.dumps(asdict(feedback)) + "\n")
