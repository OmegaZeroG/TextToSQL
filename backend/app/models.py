from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class ClarificationNeeded(BaseModel):
    needs_clarification: bool = True
    interpretations: list[str]
    message: str


class GeneratedSQL(BaseModel):
    sql: str
    explanation: str
    confidence: int = Field(ge=1, le=5)
    tables_used: list[str]


class ConfidenceBreakdown(BaseModel):
    syntax_valid: bool
    back_translation_alignment: float  # 0-1
    result_sanity_passed: bool
    overall: float  # 0-1


class QueryResponse(BaseModel):
    question: str
    sql: str
    explanation: str
    columns: list[str]
    rows: list[list]
    row_count: int
    execution_time_ms: float
    confidence: ConfidenceBreakdown
    warnings: list[str] = []
    guardrail_blocked: bool = False
    block_reason: str | None = None


class HistoryEntry(BaseModel):
    id: int
    question: str
    sql: str
    row_count: int
    confidence: float
    created_at: str
