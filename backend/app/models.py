from typing import Literal

from pydantic import BaseModel, Field

from app.schema_parser import DIALECTS

Dialect = Literal[tuple(DIALECTS)]  # one source of truth: the keys of DIALECTS

MAX_SCHEMA_CHARS = 20000


class SchemaColumn(BaseModel):
    name: str
    type: str
    primary_key: bool = False
    foreign_key: str | None = None  # "table.column" this column references


class SchemaTable(BaseModel):
    name: str
    columns: list[SchemaColumn]


class SchemaAnalyzeRequest(BaseModel):
    schema_text: str = Field(..., min_length=1, max_length=MAX_SCHEMA_CHARS)
    dialect: Dialect = "postgres"


class SchemaAnalyzeResponse(BaseModel):
    dialect: Dialect
    source: Literal["ddl", "text"]
    ddl: str
    tables: list[SchemaTable]


class SchemaUpdateRequest(BaseModel):
    current_ddl: str = Field(..., min_length=1, max_length=MAX_SCHEMA_CHARS)
    change_text: str = Field(..., min_length=1, max_length=MAX_SCHEMA_CHARS)
    dialect: Dialect = "postgres"


class SchemaUpdateResponse(BaseModel):
    dialect: Dialect
    source: Literal["ddl", "text"]
    ddl: str
    tables: list[SchemaTable]
    changes: list[str]


class GenerateRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    # Optional: with no schema the model assumes one and reports what it assumed.
    schema_ddl: str | None = Field(None, max_length=MAX_SCHEMA_CHARS)
    dialect: Dialect = "postgres"


class GenerateConfidence(BaseModel):
    syntax_valid: bool
    back_translation_alignment: float  # 0-1
    schema_check_passed: bool
    overall: float  # 0-1


class GenerateResponse(BaseModel):
    question: str
    dialect: Dialect
    sql: str
    explanation: str
    tables_used: list[str]
    confidence: GenerateConfidence
    warnings: list[str] = []
    guardrail_blocked: bool = False
    block_reason: str | None = None
    schema_provided: bool = True
    # Only when no schema was given: the schema the model assumed (as DDL) and
    # the individual guesses it made, so the user can adopt or correct them.
    assumed_schema: str | None = None
    assumptions: list[str] = []


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
