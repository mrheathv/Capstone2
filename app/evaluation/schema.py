from __future__ import annotations
from typing import Literal, Union
from pydantic import BaseModel, Field
import uuid
from datetime import datetime


class TestCase(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    test_type: Literal["conversational", "golden_sql", "golden_sql_perf"]
    question: str
    enabled: bool = True
    tags: list[str] = []
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ConversationalCase(TestCase):
    test_type: Literal["conversational"]
    expected_answer_contains: list[str]
    expected_answer_excludes: list[str] = []


class GoldenSqlCase(TestCase):
    test_type: Literal["golden_sql"]
    expected_sql: str


class GoldenSqlPerfCase(TestCase):
    test_type: Literal["golden_sql_perf"]
    expected_sql: str
    max_exec_ms: int
    expected_row_count: int | None = None


AnyCase = Union[ConversationalCase, GoldenSqlCase, GoldenSqlPerfCase]


def parse_case(data: dict) -> AnyCase:
    t = data.get("test_type")
    if t == "conversational":
        return ConversationalCase(**data)
    elif t == "golden_sql":
        return GoldenSqlCase(**data)
    elif t == "golden_sql_perf":
        return GoldenSqlPerfCase(**data)
    else:
        raise ValueError(f"Unknown test_type: {t!r}")
