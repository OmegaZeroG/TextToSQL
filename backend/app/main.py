from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.cache import ResponseCache, make_key
from app.config import (
    CACHE_MAX_ENTRIES,
    CACHE_TTL_SECONDS,
    CORS_ORIGINS,
    LLM_MODEL,
    RATE_LIMIT_EXEMPT_IPS,
    RATE_LIMIT_EXEMPT_LOCAL,
    RATE_LIMIT_PER_DAY,
    RATE_LIMIT_PER_HOUR,
    RATE_LIMIT_PER_MINUTE,
    TRUSTED_PROXY_HOPS,
)
from app.guardrails import check_sql
from app.llm.factory import get_llm_provider
from app.models import (
    GenerateConfidence,
    GenerateRequest,
    GenerateResponse,
    SchemaAnalyzeRequest,
    SchemaAnalyzeResponse,
    SchemaColumn,
    SchemaTable,
    SchemaUpdateRequest,
    SchemaUpdateResponse,
)
from app.rate_limit import RateLimiter
from app.schema_parser import (
    DIALECTS,
    ParsedSchema,
    SchemaParseError,
    analyze_schema,
    apply_schema_change,
    parse_ddl,
)
from app.sql_generation import generate_sql_for_schema, generate_sql_without_schema, repair_sql
from app.validation import back_translate_and_score, compute_confidence
from app.verification import Verdict, verify_sql

# Without a schema the model is guessing table and column names, so the answer
# can't honestly be rated above "medium" however clean it looks.
NO_SCHEMA_CONFIDENCE_CAP = 0.6

# Rounds of "tell the model what the checks found and ask for a fix". Each round
# costs one LLM call, so this is small; a repair is only accepted if it has fewer
# problems than the draft it replaces.
MAX_REPAIR_ATTEMPTS = 2


def _brief(message: str) -> str:
    """First sentence of a problem message, for the one-line note shown to the user."""
    first = message.split(". ")[0].rstrip(".")
    return first if len(first) <= 200 else first[:197] + "..."


def _try_repair(
    llm,
    request: GenerateRequest,
    schema_ddl: str | None,
    schema: ParsedSchema | None,
    sql: str,
    problems: list[str],
) -> tuple[str, dict, Verdict] | None:
    """One repair round. Returns the repaired (sql, model output, verdict), or None
    when the model fails, refuses, or hands back something the guardrail blocks."""
    try:
        fixed = repair_sql(llm, request.question, schema_ddl, request.dialect, sql, problems)
    except Exception:
        return None
    candidate = fixed.get("sql")
    if fixed.get("ambiguous") or fixed.get("unanswerable_reason") or not isinstance(candidate, str):
        return None
    guardrail = check_sql(candidate)
    if not guardrail.allowed:
        return None
    return guardrail.sql, fixed, verify_sql(guardrail.sql, schema, request.dialect)

limiter = RateLimiter(
    RATE_LIMIT_PER_MINUTE,
    60,
    RATE_LIMIT_PER_HOUR,
    3600,
    TRUSTED_PROXY_HOPS,
    daily=RATE_LIMIT_PER_DAY,
    exempt_ips=RATE_LIMIT_EXEMPT_IPS,
    exempt_local=RATE_LIMIT_EXEMPT_LOCAL,
)
cache = ResponseCache(CACHE_MAX_ENTRIES, CACHE_TTL_SECONDS)

# Answers the checks themselves distrust are not remembered: asking again should get a
# fresh attempt, not the same weak answer for a day.
MIN_CACHEABLE_CONFIDENCE = 0.5


def rate_limit(request: Request) -> None:
    # Looked up at call time so tests can swap the limiter.
    limiter.enforce(request)


app = FastAPI(
    title="plainquery",
    description="Natural language to SQL with safety guardrails and hallucination detection.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Uptime monitors (UptimeRobot's free plan, for one) probe with HEAD, and Render's own check uses GET.
# Touches no database and no model, so frequent pings cost nothing.
@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/v1/dialects")
def list_dialects():
    return [{"id": key, "label": label} for key, label in DIALECTS.items()]


@app.post("/v1/schema/analyze", response_model=SchemaAnalyzeResponse, dependencies=[Depends(rate_limit)])
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
def generate(request: GenerateRequest, http_request: Request, response: Response):
    """A remembered answer is returned without touching the LLM or the rate limit
    (neither costs anything then); otherwise the limit applies and the answer is made."""
    key = make_key(request.question, request.schema_ddl, request.dialect, LLM_MODEL)
    remembered = cache.get(key)
    if remembered is not None:
        response.headers["X-Cache"] = "HIT"
        return remembered.model_copy(deep=True)

    limiter.enforce(http_request)
    result = _generate(request)
    response.headers["X-Cache"] = "MISS"
    if result.guardrail_blocked or result.confidence.overall >= MIN_CACHEABLE_CONFIDENCE:
        cache.put(key, result.model_copy(deep=True))
    return result


def _generate(request: GenerateRequest) -> GenerateResponse:
    """Generate SQL for a question, with or without a schema. The SQL is never
    executed (there is no database), so the hallucination check is static.

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
    guardrail = check_sql(generated["sql"])
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
        checked_against, checked_ddl = schema, schema_text
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
        checked_against, checked_ddl = assumed, assumed_ddl
        raw_assumptions = generated.get("assumptions")
        if isinstance(raw_assumptions, list):
            assumptions = [a for a in raw_assumptions if isinstance(a, str)][:8]
        warnings.append(
            "No schema was provided, so table and column names are assumed. "
            "Add your schema to have the SQL checked against your real tables."
        )

    # Verify, and give the model a chance to fix what the checks found. A query
    # that merely parses is not treated as correct.
    verdict = verify_sql(sql, checked_against, request.dialect)
    corrected: list[str] = []
    for _ in range(MAX_REPAIR_ATTEMPTS):
        if verdict.clean:
            break
        repaired = _try_repair(llm, request, checked_ddl, checked_against, sql, verdict.errors)
        if repaired is None:
            break
        new_sql, new_generated, new_verdict = repaired
        if len(new_verdict.errors) >= len(verdict.errors):
            break  # the "fix" isn't better; keep the draft and show its problems honestly
        corrected += verdict.errors
        sql, generated, verdict = new_sql, new_generated, new_verdict
    explanation = generated.get("explanation", explanation)

    notes = list(warnings)
    warnings = list(verdict.errors) + list(verdict.warnings)
    if corrected:
        warnings.append(f"Corrected automatically after checks found: {_brief(corrected[0])}")
    warnings += notes

    alignment = back_translate_and_score(llm, request.question, sql)
    overall = compute_confidence(
        generated.get("confidence", 3), alignment, verdict.syntax_valid and verdict.schema_ok and verdict.logic_ok
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
        tables_used=verdict.tables_used,
        confidence=GenerateConfidence(
            syntax_valid=verdict.syntax_valid,
            back_translation_alignment=alignment,
            schema_check_passed=verdict.schema_ok,
            logic_check_passed=verdict.logic_ok,
            overall=overall,
        ),
        warnings=warnings,
        schema_provided=schema is not None,
        assumed_schema=assumed_ddl,
        assumptions=assumptions,
    )


@app.post("/v1/schema/update", response_model=SchemaUpdateResponse, dependencies=[Depends(rate_limit)])
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
