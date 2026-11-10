import json
import re

from app.dialect_guide import guidance
from app.llm.base import LLMProvider
from app.schema_parser import DIALECTS


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def _parse_model_output(raw: str) -> dict:
    parsed = _extract_json(raw)

    if not isinstance(parsed, dict):
        raise ValueError("model output is not a JSON object")
    has_reason_to_omit_sql = parsed.get("ambiguous") or parsed.get("unanswerable_reason")
    if not has_reason_to_omit_sql and not isinstance(parsed.get("sql"), str):
        raise ValueError("model output is missing a 'sql' string")
    return parsed


BYO_SYSTEM_PROMPT = """You are a SQL translation engine that converts natural language questions into \
{dialect} queries for the schema below. You are one stage in a pipeline: a separate safety layer \
downstream of you statically analyzes and blocks any unsafe SQL, and the query is never run \
against a database. Follow these rules strictly:

1. Write a single query in {dialect} syntax. Use that dialect's own constructs (for example \
LIMIT vs TOP vs FETCH FIRST, and its date functions and quoting rules).
2. Translate the question into the literal SQL it describes, even if that SQL would be a write or \
destructive statement (e.g. "remove all books under $5" -> a real DELETE statement). Do NOT \
refuse, moralize, or add disclaimers: that is the downstream safety layer's job, not yours. Never \
respond with plain-text refusals; always respond with the required JSON object.
3. Use ONLY the tables and columns in the schema. Never invent a table or column name, and never \
assume a column exists because it would be convenient.
4. If the schema does not contain the data needed to answer the question, do not guess: set \
"unanswerable_reason" to a one-sentence explanation of what is missing.
5. If the question has several genuinely different valid readings, do not guess: set "ambiguous" \
to true and list the readings in "interpretations". Missing schema data is NOT ambiguity; use \
"unanswerable_reason" for that.
6. Prefer explicit JOINs with ON clauses. Format the SQL with line breaks and indentation so it \
is easy to read.
7. Respond with a single JSON object with exactly these keys: "sql" (string, empty if you set \
"ambiguous" or "unanswerable_reason"), "explanation" (one sentence, plain English), \
"confidence" (integer 1-5), "tables_used" (list of table names), "ambiguous" (boolean), \
"interpretations" (list of strings, only when ambiguous), "unanswerable_reason" (string, only \
when the schema cannot answer the question).

{guidance}

SCHEMA:
{schema}

FORMAT EXAMPLES (these use a different, unrelated schema: books(id, title, author_id, price), \
authors(id, name). Do not use these tables unless they appear in the schema above):
{examples}
"""

BYO_EXAMPLES = """Q: Which authors have written more than 3 books?
A: {"sql": "SELECT a.name\\nFROM authors a\\nJOIN books b ON b.author_id = a.id\\nGROUP BY a.name\\nHAVING COUNT(*) > 3", "explanation": "Groups books by author and keeps authors with more than three.", "confidence": 5, "tables_used": ["authors", "books"], "ambiguous": false}

Q: Remove all books priced under 5
A: {"sql": "DELETE FROM books WHERE price < 5", "explanation": "Deletes every book priced below 5.", "confidence": 5, "tables_used": ["books"], "ambiguous": false}

Q: What is each author's favourite colour?
A: {"sql": "", "explanation": "", "confidence": 5, "tables_used": [], "ambiguous": false, "unanswerable_reason": "The schema has no column that stores colours or preferences."}
"""


def generate_sql_for_schema(llm: LLMProvider, question: str, schema_ddl: str, dialect: str) -> dict:
    system_prompt = BYO_SYSTEM_PROMPT.format(
        dialect=DIALECTS[dialect], schema=schema_ddl, examples=BYO_EXAMPLES, guidance=guidance(dialect)
    )
    raw = llm.complete(system_prompt, f"Question: {question}", json_mode=True)
    return _parse_model_output(raw)


NO_SCHEMA_SYSTEM_PROMPT = """You are a SQL translation engine. The user asked a question but gave \
you NO schema. Write the most plausible {dialect} query anyway, by assuming the conventional \
schema that such a question implies. You are one stage in a pipeline: a separate safety layer \
downstream of you statically analyzes and blocks any unsafe SQL, and the query is never run \
against a database. Follow these rules strictly:

1. Write a single query in {dialect} syntax. Use that dialect's own constructs (for example \
LIMIT vs TOP vs FETCH FIRST, and its date functions and quoting rules).
2. Do NOT ask for clarification and do NOT refuse. If the question could be read several ways, \
pick the most common reading and go with it. Translate destructive requests literally (e.g. a \
real DELETE statement): the downstream safety layer handles them, not you. Never respond with \
plain-text refusals; always respond with the required JSON object.
3. If the question itself names tables or columns, use exactly those names. Otherwise assume a \
minimal conventional schema: snake_case plural table names (customers, orders, order_items), an \
"id" primary key, "<singular>_id" foreign keys, and only the columns the question actually \
needs. Never add tables or columns the query does not use.
4. Format the SQL with line breaks and indentation so it is easy to read.
5. Respond with a single JSON object with exactly these keys: "sql" (string), "explanation" \
(one sentence, plain English), "confidence" (integer 1-5, reflecting how much you had to guess), \
"assumed_schema" (string: {dialect} CREATE TABLE statements, with primary and foreign keys, for \
exactly the tables and columns your SQL uses), and "assumptions" (list of short strings: every \
non-obvious thing you assumed, such as what a business term means or which values a status \
column holds).

{guidance}
"""


def generate_sql_without_schema(llm: LLMProvider, question: str, dialect: str) -> dict:
    raw = llm.complete(
        NO_SCHEMA_SYSTEM_PROMPT.format(dialect=DIALECTS[dialect], guidance=guidance(dialect)),
        f"Question: {question}",
        json_mode=True,
    )
    return _parse_model_output(raw)



REPAIR_SYSTEM_PROMPT = """You are a SQL reviewer fixing a query that failed automatic checks. The \
query below was written for the question given, then checked by a validator and by a trial run on \
test data. The problems found are listed. Rewrite the query so that EVERY listed problem is fixed \
while it still answers the question exactly. Follow these rules:

1. Stay strictly in {dialect} syntax. Never borrow syntax from another database.
2. Fix the cause, not the symptom: if a problem says a date was rebuilt from numbers, use native date \
functions on the original date instead of patching the arithmetic.
3. Keep what was already right. Do not change the meaning, the requested columns or the ordering \
unless a problem requires it.
4. Use only tables and columns that exist in the schema (if one is given).
5. Respond with a single JSON object with exactly these keys: "sql" (string), "explanation" (one \
sentence, plain English), "confidence" (integer 1-5), "tables_used" (list of table names).

{guidance}
{schema_block}"""


def repair_sql(
    llm: LLMProvider,
    question: str,
    schema_ddl: str | None,
    dialect: str,
    sql: str,
    problems: list[str],
) -> dict:
    """Asks the model to fix a query given the problems the checks found."""
    schema_block = f"\nSCHEMA:\n{schema_ddl}\n" if schema_ddl else ""
    system_prompt = REPAIR_SYSTEM_PROMPT.format(
        dialect=DIALECTS[dialect], guidance=guidance(dialect), schema_block=schema_block
    )
    listed = "\n".join(f"{i}. {problem}" for i, problem in enumerate(problems, 1))
    user_prompt = f"Question: {question}\n\nQuery to fix:\n{sql}\n\nProblems found:\n{listed}"
    raw = llm.complete(system_prompt, user_prompt, json_mode=True)
    return _parse_model_output(raw)
