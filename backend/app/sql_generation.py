import json
import re

from app.llm.base import LLMProvider
from app.models import GeneratedSQL
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
    return _extract_json(raw)
