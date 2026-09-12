import json
import re

from app.llm.base import LLMProvider
from app.models import GeneratedSQL
from app.schema_introspection import TableInfo, filter_relevant_tables, format_schema_for_prompt

SYSTEM_PROMPT = """You are a senior data analyst that translates natural language questions into \
DuckDB SQL queries. Follow these rules strictly:

1. Only ever write a single SELECT (or WITH ... SELECT) statement. Never write INSERT, UPDATE, \
DELETE, CREATE, ALTER, or DROP.
2. Use only the tables and columns given in the schema below. Never invent column or table names.
3. Prefer explicit JOINs with ON clauses over implicit joins.
4. If the question is ambiguous (e.g. could mean two different things), do not guess — say so.
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
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def generate_sql(llm: LLMProvider, question: str, tables: list[TableInfo]) -> dict:
    relevant = filter_relevant_tables(question, tables)
    schema_text = format_schema_for_prompt(tables, relevant)
    system_prompt = SYSTEM_PROMPT.format(schema=schema_text, examples=DEFAULT_EXAMPLES)

    raw = llm.complete(system_prompt, f"Question: {question}", json_mode=True)
    return _extract_json(raw)
