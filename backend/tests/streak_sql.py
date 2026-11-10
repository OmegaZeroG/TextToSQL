"""Reference SQL for "consecutive months" questions, built from the same dialect
templates the prompt gives the model (app/dialect_guide.py).

These are what a correct answer looks like. The tests run them to prove the
harness and the validator agree with a known-good query, and then contrast them
with the broken patterns the checks exist to catch.
"""
from app.dialect_guide import GUIDES


def longest_streak_sql(dialect: str, table: str = "orders", entity: str = "customer_id", date: str = "order_date") -> str:
    """Each entity's longest run of consecutive calendar months with at least one
    row; ties go to the earliest run."""
    guide = GUIDES[dialect]
    return f"""WITH months AS (
  SELECT DISTINCT {entity}, {guide.month(date)} AS month_start
  FROM {table}
), numbered AS (
  SELECT {entity}, month_start,
         ROW_NUMBER() OVER (PARTITION BY {entity} ORDER BY month_start) AS rn
  FROM months
), runs AS (
  SELECT {entity}, month_start, {guide.back_months("month_start", "rn")} AS grp
  FROM numbered
), streaks AS (
  SELECT {entity}, MIN(month_start) AS first_month, MAX(month_start) AS last_month, COUNT(*) AS consecutive_months
  FROM runs
  GROUP BY {entity}, grp
), ranked AS (
  SELECT {entity}, first_month, last_month, consecutive_months,
         ROW_NUMBER() OVER (PARTITION BY {entity} ORDER BY consecutive_months DESC, first_month ASC) AS pick
  FROM streaks
)
SELECT {entity}, first_month, last_month, consecutive_months
FROM ranked
WHERE pick = 1
ORDER BY {entity}"""


def naive_row_number_sql() -> str:
    """The duplicate-order bug: numbering raw rows, so ten orders in one month
    look like ten consecutive periods. SQLite."""
    return """WITH numbered AS (
  SELECT customer_id, date(order_date, 'start of month') AS month_start,
         ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY date(order_date, 'start of month')) AS rn
  FROM orders
), runs AS (
  SELECT customer_id, month_start, date(month_start, '-' || rn || ' months') AS grp FROM numbered
)
SELECT customer_id, MIN(month_start) AS first_month, MAX(month_start) AS last_month, COUNT(*) AS consecutive_months
FROM runs GROUP BY customer_id, grp"""


def month_number_roundtrip_sql(dialect: str) -> str:
    """The reported bug: months as year*12+month, decoded back with arithmetic."""
    year = {"mysql": "YEAR(order_date)", "sqlite": "CAST(strftime('%Y', order_date) AS INTEGER)"}.get(
        dialect, "EXTRACT(YEAR FROM order_date)"
    )
    month = {"mysql": "MONTH(order_date)", "sqlite": "CAST(strftime('%m', order_date) AS INTEGER)"}.get(
        dialect, "EXTRACT(MONTH FROM order_date)"
    )
    return f"""WITH months AS (
  SELECT customer_id, {year} * 12 + {month} AS month_num FROM orders GROUP BY customer_id, {year} * 12 + {month}
), numbered AS (
  SELECT customer_id, month_num, month_num - ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY month_num) AS grp FROM months
), streaks AS (
  SELECT customer_id, MIN(month_num) AS start_num, COUNT(*) AS consecutive_months FROM numbered GROUP BY customer_id, grp
)
SELECT customer_id,
       CAST(start_num / 12 AS INTEGER) AS first_year,
       start_num % 12 AS first_month_num,
       CAST(start_num / 12 AS INTEGER) || '-' || printf('%02d', start_num % 12) || '-01' AS first_month,
       consecutive_months
FROM streaks"""
