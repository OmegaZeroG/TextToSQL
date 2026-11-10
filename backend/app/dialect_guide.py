"""Per-dialect building blocks and the correctness rules given to the model.

The model is told *how this dialect does* the things that go wrong most (month
buckets, shifting a date by months, row limits) so it reaches for native date
functions instead of inventing arithmetic. The same templates are used by the
tests to build reference queries, which keeps the guidance and the validator
from drifting apart: whatever this module recommends must pass sql_checks.
"""
from dataclasses import dataclass

from app.schema_parser import DIALECTS


@dataclass(frozen=True)
class DialectGuide:
    limit: str
    month_start: str  # template: the first day of the month of {d}
    shift_months: str  # template: {d} moved back by {n} months
    add_days: str  # template: {d} plus {n} days
    diff_days: str  # template: days from {b} to {a}

    def month(self, d: str) -> str:
        return self.month_start.format(d=d)

    def back_months(self, d: str, n: str) -> str:
        return self.shift_months.format(d=d, n=n)


GUIDES: dict[str, DialectGuide] = {
    "postgres": DialectGuide(
        limit="LIMIT n at the end",
        month_start="DATE_TRUNC('month', {d})::date",
        shift_months="({d} - {n} * INTERVAL '1 month')::date",
        add_days="{d} + {n}",
        diff_days="{a} - {b}",
    ),
    "mysql": DialectGuide(
        limit="LIMIT n at the end",
        month_start="CAST(DATE_FORMAT({d}, '%Y-%m-01') AS DATE)",
        shift_months="DATE_SUB({d}, INTERVAL {n} MONTH)",
        add_days="DATE_ADD({d}, INTERVAL {n} DAY)",
        diff_days="DATEDIFF({a}, {b})",
    ),
    "sqlite": DialectGuide(
        limit="LIMIT n at the end",
        month_start="date({d}, 'start of month')",
        shift_months="date({d}, '-' || {n} || ' months')",
        add_days="date({d}, '+' || {n} || ' days')",
        diff_days="julianday({a}) - julianday({b})",
    ),
    "tsql": DialectGuide(
        limit="SELECT TOP n, or ORDER BY ... OFFSET 0 ROWS FETCH NEXT n ROWS ONLY (never LIMIT)",
        month_start="DATEFROMPARTS(YEAR({d}), MONTH({d}), 1)",
        shift_months="DATEADD(month, -{n}, {d})",
        add_days="DATEADD(day, {n}, {d})",
        diff_days="DATEDIFF(day, {b}, {a})",
    ),
    "oracle": DialectGuide(
        limit="FETCH FIRST n ROWS ONLY at the end (never LIMIT or TOP)",
        month_start="TRUNC({d}, 'MM')",
        shift_months="ADD_MONTHS({d}, -{n})",
        add_days="{d} + {n}",
        diff_days="{a} - {b}",
    ),
    "bigquery": DialectGuide(
        limit="LIMIT n at the end",
        month_start="DATE_TRUNC({d}, MONTH)",
        shift_months="DATE_SUB({d}, INTERVAL {n} MONTH)",
        add_days="DATE_ADD({d}, INTERVAL {n} DAY)",
        diff_days="DATE_DIFF({a}, {b}, DAY)",
    ),
    "snowflake": DialectGuide(
        limit="LIMIT n at the end",
        month_start="DATE_TRUNC('month', {d})",
        shift_months="DATEADD(month, -{n}, {d})",
        add_days="DATEADD(day, {n}, {d})",
        diff_days="DATEDIFF(day, {b}, {a})",
    ),
}

assert set(GUIDES) == set(DIALECTS), "every supported dialect needs a guide"


def guidance(dialect: str) -> str:
    """The text spliced into the generation prompts for this dialect."""
    guide = GUIDES[dialect]
    label = DIALECTS[dialect]
    return f"""{label} NOTES (use these, not another database's syntax):
- Limit rows with: {guide.limit}.
- First day of the month of a date d: {guide.month("d")}
- A date d moved back by n months: {guide.back_months("d", "n")}
- d plus n days: {guide.add_days.format(d="d", n="n")}; days between a and b: {guide.diff_days.format(a="a", b="b")}

CORRECTNESS RULES. Your SQL is checked automatically for each of these and sent back if it breaks one:
- Dates: use native date functions on the original date column. Never rebuild a date from numbers: \
do not encode months as year*12+month and decode it with % 12 or / 12 (that produces month 00 or 13), \
and do not assemble dates by joining year and month text. To group by month use the month-start \
expression above, and report MIN/MAX of that real date.
- Consecutive periods (months, days, weeks): first reduce to one row per entity and period \
(SELECT DISTINCT entity, period_start, or GROUP BY), so several rows in one period count once. Number \
those rows with ROW_NUMBER() OVER (PARTITION BY entity ORDER BY period_start). Periods are consecutive \
when period_start moved back by the row number (for months: {guide.back_months("period_start", "rn")}) is the \
same value, so group by entity and that value. Report MIN and MAX of the real period_start and COUNT(*) as \
the length. A gap, even of one period, starts a new run.
- Superlatives ("longest", "most", "first"): break ties explicitly (for example ORDER BY length DESC, \
start_date ASC) so the answer is deterministic, and say which tie-break you used.
- NULL: use IS NULL / IS NOT NULL, never = NULL or <> NULL.
- Division: guard any denominator that can be zero with NULLIF(denominator, 0). Percentages: \
100.0 * part / NULLIF(total, 0).
- GROUP BY: every selected column that is not inside an aggregate must be in the GROUP BY.
- Aliases: do not use a SELECT-list alias in WHERE (or anywhere {label} forbids). Repeat the expression, \
or compute it in a subquery or CTE and use the alias outside.
- Window functions: never in WHERE, HAVING or GROUP BY (compute in a subquery or CTE, filter outside). \
Ranking and LAG/LEAD need an ORDER BY inside OVER(...).
- Counting: joins can repeat rows, so use COUNT(DISTINCT ...) when the question asks how many distinct things.
- Stay in {label}: no functions or syntax from other databases."""
