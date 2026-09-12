import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import history
from app.config import CORS_ORIGINS, MAX_ROW_LIMIT
from app.db import run_query
from app.guardrails import check_sql
from app.llm.factory import get_llm_provider
from app.models import ConfidenceBreakdown, HistoryEntry, QueryRequest, QueryResponse
from app.schema_introspection import format_schema_for_prompt, introspect_schema
from app.sql_generation import generate_sql
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
