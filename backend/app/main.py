import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import history
from app.config import CORS_ORIGINS, MAX_ROW_LIMIT
from app.db import run_query
from app.guardrails import check_sql
from app.llm.factory import get_llm_provider
from app.models import (
    ConfidenceBreakdown,
    GenerateConfidence,
    GenerateRequest,
    GenerateResponse,
    HistoryEntry,
    QueryRequest,
    QueryResponse,
    SchemaAnalyzeRequest,
    SchemaAnalyzeResponse,
    SchemaColumn,
    SchemaTable,
    SchemaUpdateRequest,
    SchemaUpdateResponse,
)
from app.schema_introspection import format_schema_for_prompt, introspect_schema
from app.schema_parser import (
    DIALECTS,
    ParsedSchema,
    SchemaParseError,
    analyze_schema,
    apply_schema_change,
    parse_ddl,
)
from app.schema_validation import check_sql_against_schema
from app.sql_generation import generate_sql, generate_sql_for_schema, generate_sql_without_schema

# Without a schema the model is guessing table and column names, so the answer
# can't honestly be rated above "medium" however clean it looks.
NO_SCHEMA_CONFIDENCE_CAP = 0.6
from app.validation import back_translate_and_score, compute_confidence, result_sanity_check

app = FastAPI(
    title="Text-to-SQL with Guardrails",
    description="Natural language to SQL with safety guardrails and hallucination detection.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/schema")
def get_schema():
    tables = introspect_schema()
    return {"schema": format_schema_for_prompt(tables), "tables": [t.name for t in tables]}


@app.get("/v1/dialects")
def list_dialects():
    return [{"id": key, "label": label} for key, label in DIALECTS.items()]


@app.post("/v1/schema/analyze", response_model=SchemaAnalyzeResponse)
def analyze(request: SchemaAnalyzeRequest):
    """Bring-your-own-schema, step 1: accept DDL or plain text and return the
    structured schema we understood, so the user can confirm it before asking."""
    try:
        analyzed = analyze_schema(request.schema_text, request.dialect, lambda: get_llm_provider())
    except SchemaParseError as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't read that schema: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Schema analysis failed: {exc}") from exc

    return SchemaAnalyzeResponse(
        dialect=request.dialect,
        source=analyzed.source,
        ddl=analyzed.ddl,
        tables=[
            SchemaTable(name=t.name, columns=[SchemaColumn(name=c.name, type=c.type, primary_key=c.primary_key, foreign_key=c.foreign_key) for c in t.columns])
            for t in analyzed.parsed.tables
        ],
    )


@app.post("/v1/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest):
    """Generate SQL for a question, with or without a schema. Nothing is executed
    (there is no data), so the hallucination check is static.

    With a schema: does the SQL only use tables and columns that exist in it?
    Without one: the model assumes a schema and tells us what it assumed; we check
    the SQL is at least consistent with its own assumptions, cap the confidence,
    and hand the assumed schema back so the user can adopt or correct it."""
    schema_text = (request.schema_ddl or "").strip()
    schema: ParsedSchema | None = None
    if schema_text:
        try:
            schema = parse_ddl(schema_text, request.dialect)
        except SchemaParseError as exc:
            raise HTTPException(status_code=422, detail=f"Couldn't read that schema: {exc}") from exc

    llm = get_llm_provider()
    try:
        if schema is not None:
            generated = generate_sql_for_schema(llm, request.question, schema_text, request.dialect)
        else:
            generated = generate_sql_without_schema(llm, request.question, request.dialect)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}") from exc

    if schema is not None:  # with no schema the model is told to guess rather than ask
        if generated.get("ambiguous"):
            raise HTTPException(
                status_code=422,
                detail={
                    "kind": "ambiguous",
                    "message": "This question has multiple possible interpretations.",
                    "interpretations": generated.get("interpretations", []),
                },
            )
        if generated.get("unanswerable_reason"):
            raise HTTPException(
                status_code=422,
                detail={
                    "kind": "unanswerable",
                    "message": "Your schema doesn't contain the data needed to answer this.",
                    "interpretations": [generated["unanswerable_reason"]],
                },
            )

    if not isinstance(generated.get("sql"), str):
        raise HTTPException(status_code=502, detail="LLM generation failed: model output is missing a 'sql' string")

    explanation = generated.get("explanation", "")
    guardrail = check_sql(generated["sql"], for_execution=False)
    if not guardrail.allowed:
        return GenerateResponse(
            question=request.question,
            dialect=request.dialect,
            sql=generated["sql"],
            explanation=explanation,
            tables_used=[],
            confidence=GenerateConfidence(
                syntax_valid=False, back_translation_alignment=0, schema_check_passed=False, overall=0
            ),
            guardrail_blocked=True,
            block_reason=guardrail.reason,
            schema_provided=schema is not None,
        )

    sql = guardrail.sql
    warnings: list[str] = []
    assumed_ddl: str | None = None
    assumptions: list[str] = []

    if schema is not None:
        check = check_sql_against_schema(sql, schema, request.dialect)
    else:
        assumed_text = generated.get("assumed_schema")
        try:
            assumed = parse_ddl(assumed_text, request.dialect) if isinstance(assumed_text, str) else None
            if assumed is None:
                raise SchemaParseError("no assumed schema returned")
            assumed_ddl = assumed_text.strip()
        except SchemaParseError:
            assumed = None
            warnings.append("The assumed schema couldn't be read, so the SQL wasn't checked against it.")
        check = check_sql_against_schema(sql, assumed, request.dialect)
        raw_assumptions = generated.get("assumptions")
        if isinstance(raw_assumptions, list):
            assumptions = [a for a in raw_assumptions if isinstance(a, str)][:8]
        warnings.append(
            "No schema was provided, so table and column names are assumed. "
            "Add your schema to have the SQL checked against your real tables."
        )

    warnings = list(check.problems) + warnings
    alignment = back_translate_and_score(llm, request.question, sql)
    overall = compute_confidence(
        generated.get("confidence", 3), alignment, check.syntax_valid and check.schema_ok
    )
    if schema is None:
        overall = min(overall, NO_SCHEMA_CONFIDENCE_CAP)
    if overall < 0.5:
        warnings.append(
            "Low confidence: this SQL may not answer your question. Review it before relying on it."
        )

    return GenerateResponse(
        question=request.question,
        dialect=request.dialect,
        sql=sql,
        explanation=explanation,
        tables_used=check.tables_used,
        confidence=GenerateConfidence(
            syntax_valid=check.syntax_valid,
            back_translation_alignment=alignment,
            schema_check_passed=check.schema_ok,
            overall=overall,
        ),
        warnings=warnings,
        schema_provided=schema is not None,
        assumed_schema=assumed_ddl,
        assumptions=assumptions,
    )


@app.post("/v1/schema/update", response_model=SchemaUpdateResponse)
def update_schema(request: SchemaUpdateRequest):
    """Add to or change a saved schema using plain English or SQL. All or nothing:
    on success you get the full updated schema plus exactly what changed; on
    failure nothing is modified and the reason is returned."""
    try:
        updated = apply_schema_change(
            request.current_ddl, request.change_text, request.dialect, lambda: get_llm_provider()
        )
    except SchemaParseError as exc:  # includes SchemaChangeError
        raise HTTPException(status_code=422, detail=f"Schema not changed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Schema update failed: {exc}") from exc

    return SchemaUpdateResponse(
        dialect=request.dialect,
        source=updated.source,
        ddl=updated.ddl,
        tables=[
            SchemaTable(name=t.name, columns=[SchemaColumn(name=c.name, type=c.type, primary_key=c.primary_key, foreign_key=c.foreign_key) for c in t.columns])
            for t in updated.parsed.tables
        ],
        changes=updated.changes,
    )


@app.get("/v1/history", response_model=list[HistoryEntry])
def get_history(limit: int = 50):
    return history.get_all(limit)


@app.post("/v1/query", response_model=QueryResponse)
def query(request: QueryRequest):
    llm = get_llm_provider()
    tables = introspect_schema()

    try:
        generated = generate_sql(llm, request.question, tables)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}") from exc

    if generated.get("ambiguous"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "This question has multiple possible interpretations.",
                "interpretations": generated.get("interpretations", []),
            },
        )

    sql = generated["sql"]
    guardrail_result = check_sql(sql)

    if not guardrail_result.allowed:
        return QueryResponse(
            question=request.question,
            sql=sql,
            explanation=generated.get("explanation", ""),
            columns=[],
            rows=[],
            row_count=0,
            execution_time_ms=0,
            confidence=ConfidenceBreakdown(
                syntax_valid=False, back_translation_alignment=0, result_sanity_passed=False, overall=0,
            ),
            guardrail_blocked=True,
            block_reason=guardrail_result.reason,
        )

    safe_sql = guardrail_result.sql

    start = time.perf_counter()
    try:
        df = run_query(safe_sql, MAX_ROW_LIMIT)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Query execution failed: {exc}") from exc
    execution_time_ms = (time.perf_counter() - start) * 1000

    sanity_passed, warnings = result_sanity_check(df, MAX_ROW_LIMIT)
    alignment_score = back_translate_and_score(llm, request.question, safe_sql)
    overall_confidence = compute_confidence(
        generated.get("confidence", 3), alignment_score, sanity_passed,
    )

    if overall_confidence < 0.5:
        warnings.append("Low confidence: the generated SQL may not accurately answer your question. Review before trusting these results.")

    history.record(request.question, safe_sql, len(df), overall_confidence)

    return QueryResponse(
        question=request.question,
        sql=safe_sql,
        explanation=generated.get("explanation", ""),
        columns=list(df.columns),
        rows=df.values.tolist(),
        row_count=len(df),
        execution_time_ms=round(execution_time_ms, 2),
        confidence=ConfidenceBreakdown(
            syntax_valid=True,
            back_translation_alignment=alignment_score,
            result_sanity_passed=sanity_passed,
            overall=overall_confidence,
        ),
        warnings=warnings,
    )
