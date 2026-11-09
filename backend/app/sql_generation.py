import json
import re

from app.llm.base import LLMProvider
from app.models import GeneratedSQL
from app.schema_parser import DIALECTS
from app.schema_introspection import TableInfo, filter_relevant_tables, format_schema_for_prompt

SYSTEM_PROMPT = """You are a SQL translation engine that converts natural language questions into \
PostgreSQL queries. You are one stage in a pipeline — a separate safety layer downstream of you \
statically analyzes and blocks any unsafe SQL before it ever executes. Follow these rules strictly:

1. Translate the question into the literal SQL it describes, even if that SQL would be a write \
or destructive statement (e.g. "delete all cancelled orders" -> a real DELETE statement). Do NOT \
refuse, moralize, or add disclaimers — that is the downstream safety layer's job, not yours. \
Never respond with plain-text refusals; always respond with the required JSON object.
2. Use only the tables and columns given in the schema below. Never invent column or table names.
3. Prefer explicit JOINs with ON clauses over implicit joins.
4. If the question is ambiguous (e.g. could mean two different things), do not guess — say so. \
Ambiguity means genuinely multiple valid readings of the question itself, not uncertainty about \
which tables to join — the full schema is always given below, so every table it lists is available.
5. Respond with a single JSON object with exactly these keys:
   "sql" (string), "explanation" (one sentence, plain English), "confidence" (integer 1-5), \
"tables_used" (list of table names), and "ambiguous" (boolean, true only if you genuinely cannot \
pick a single interpretation) and "interpretations" (list of strings, only if ambiguous is true).

SCHEMA:
{schema}

FEW-SHOT EXAMPLES:
{examples}
"""

DEFAULT_EXAMPLES = """Q: How many orders were placed in 2024?
A: {"sql": "SELECT COUNT(*) AS order_count FROM orders WHERE order_date >= '2024-01-01' AND order_date < '2025-01-01'", "explanation": "Counts orders placed during 2024.", "confidence": 5, "tables_used": ["orders"], "ambiguous": false}

Q: Who are the top 5 customers by total spend?
A: {"sql": "SELECT c.customer_id, c.first_name, c.last_name, SUM(oi.quantity * oi.unit_price) AS total_spend FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_items oi ON o.order_id = oi.order_id GROUP BY c.customer_id, c.first_name, c.last_name ORDER BY total_spend DESC LIMIT 5", "explanation": "Sums each customer's order line totals and returns the top 5.", "confidence": 5, "tables_used": ["customers", "orders", "order_items"], "ambiguous": false}

Q: Delete all cancelled orders
A: {"sql": "DELETE FROM orders WHERE status = 'cancelled'", "explanation": "Deletes every order row with status cancelled.", "confidence": 5, "tables_used": ["orders"], "ambiguous": false}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


# Below this many tables, keyword-based filtering isn't worth the false-negative
# risk (e.g. "total spend" not matching an "orders" table by keyword) — just
# send the whole schema. Filtering only pays off once a schema is too big to
# fit comfortably in the prompt.
RELEVANCE_FILTER_TABLE_THRESHOLD = 12


def generate_sql(llm: LLMProvider, question: str, tables: list[TableInfo]) -> dict:
    if len(tables) > RELEVANCE_FILTER_TABLE_THRESHOLD:
        relevant = filter_relevant_tables(question, tables)
    else:
        relevant = {t.name for t in tables}
    schema_text = format_schema_for_prompt(tables, relevant)
    system_prompt = SYSTEM_PROMPT.format(schema=schema_text, examples=DEFAULT_EXAMPLES)

    raw = llm.complete(system_prompt, f"Question: {question}", json_mode=True)
    return _parse_model_output(raw)


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
        dialect=DIALECTS[dialect], schema=schema_ddl, examples=BYO_EXAMPLES
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
"""


def generate_sql_without_schema(llm: LLMProvider, question: str, dialect: str) -> dict:
    raw = llm.complete(
        NO_SCHEMA_SYSTEM_PROMPT.format(dialect=DIALECTS[dialect]), f"Question: {question}", json_mode=True
    )
    return _parse_model_output(raw)
