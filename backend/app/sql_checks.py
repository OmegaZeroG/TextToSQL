"""Logic and dialect checks for generated SQL.

Parsing and column resolution (schema_validation.py) say a query is *well formed*.
They don't say it is *right*: SQL can parse, use only real columns and still
compare to NULL with `=`, divide by a column that is sometimes zero, select a
column that isn't grouped, or turn a month number back into the month `00`.

Everything here is a structural rule over the parsed query, not a pattern for one
question, so it holds for queries nobody has written yet. Each rule reports an
`Issue`. Errors are things that are wrong or very likely wrong; the pipeline asks
the model to repair them. Warnings are shown to the user but do not block.

Best effort, by design: a rule only fires when it is confident. Missing an issue
is acceptable; crying wolf makes people stop reading the warnings.
"""
import calendar
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify

from app.schema_parser import DIALECTS, ParsedSchema


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    severity: str = "error"  # "error": wrong, triggers a repair. "warning": shown only.

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


# --------------------------------------------------------------------------- helpers

_DIALECT: ContextVar[str] = ContextVar("sql_dialect", default="postgres")


def _show(node: exp.Expression) -> str:
    """The node as the author would have written it: in the query's own dialect
    (so MySQL's `/` doesn't turn into NULLIF(...)), without optimizer quoting."""
    plain = node.copy()
    for identifier in plain.find_all(exp.Identifier):
        identifier.set("quoted", False)
    return plain.sql(dialect=_DIALECT.get())


def _scope_nodes(root: exp.Expression) -> Iterator[exp.Expression]:
    """`root` and everything under it, without descending into nested queries
    (a subquery has its own scope and is checked on its own)."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        for child in node.iter_expressions():
            if isinstance(child, exp.Query):
                continue
            stack.append(child)


def _unwrap(node: exp.Expression) -> exp.Expression:
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def _is_number(node: exp.Expression, value: float | None = None) -> bool:
    node = _unwrap(node)
    if not isinstance(node, exp.Literal) or node.is_string:
        return False
    try:
        number = float(node.this)
    except ValueError:
        return False
    return True if value is None else number == value


def _is_windowed(node: exp.Expression) -> bool:
    """True if the aggregate is the function being windowed, e.g. SUM(x) OVER (...)."""
    return isinstance(node.parent, exp.Window) and node.parent.this is node


def _sources(select: exp.Select) -> list[exp.Expression]:
    from_ = select.args.get("from_") or select.args.get("from")
    nodes = [from_.this] if from_ is not None else []
    nodes += [join.this for join in select.args.get("joins") or []]
    return nodes


def _has_star(select: exp.Query) -> bool:
    return any(isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star)) for e in select.expressions)


def _cte_map(tree: exp.Expression) -> dict[str, exp.Expression]:
    return {cte.alias.lower(): cte.this for cte in tree.find_all(exp.CTE)}


# --------------------------------------------------------------------------- NULL


def _null_comparisons(tree: exp.Expression) -> list[Issue]:
    issues = []
    for node in tree.find_all(exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE):
        if isinstance(node.this, exp.Null) or isinstance(node.expression, exp.Null):
            other = node.expression if isinstance(node.this, exp.Null) else node.this
            wants = "IS NOT NULL" if isinstance(node, exp.NEQ) else "IS NULL"
            issues.append(
                Issue(
                    "null_comparison",
                    f"`{_show(node)}` is never true, because comparing anything to NULL gives NULL. "
                    f"Use `{_show(other)} {wants}`.",
                )
            )
    return issues


# --------------------------------------------------------------------------- division


def _guards(condition: exp.Expression) -> set[str]:
    """SQL text of every expression a condition compares against a number
    (`b <> 0`, `b > 0`, `0 < b`): evidence the author guarded against b being zero."""
    guarded: set[str] = set()
    for cmp in condition.find_all(exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE):
        if _is_number(cmp.expression):
            guarded.add(_unwrap(cmp.this).sql())
        elif _is_number(cmp.this):
            guarded.add(_unwrap(cmp.expression).sql())
    return guarded


def _denominator_is_guarded(div: exp.Expression, denominator: exp.Expression) -> bool:
    denominator = _unwrap(denominator)
    if isinstance(denominator, (exp.Nullif, exp.Case, exp.If)):
        return True  # NULLIF(b, 0), or the author handles the cases explicitly
    text = denominator.sql()

    node: exp.Expression | None = div
    while node is not None and not isinstance(node, exp.Query):
        if isinstance(node, exp.If) and text in _guards(node.this):
            return True
        if isinstance(node, exp.Case):
            for when in node.args.get("ifs") or []:
                if text in _guards(when.this):
                    return True
        node = node.parent
    select = div.find_ancestor(exp.Select)
    if select is not None:
        for clause in ("where", "having"):
            part = select.args.get(clause)
            if part is not None and text in _guards(part):
                return True
    return False


def _division(tree: exp.Expression) -> list[Issue]:
    issues = []
    for div in tree.find_all(exp.Div, exp.IntDiv, exp.Mod):
        denominator = _unwrap(div.expression)
        if _is_number(denominator, 0):
            issues.append(Issue("division_by_zero", f"`{_show(div)}` divides by the literal 0."))
            continue
        variable = any(isinstance(n, (exp.Column, exp.AggFunc, exp.Window)) for n in denominator.walk())
        if not variable:
            continue  # a constant like 100.0 or 12 can't be zero
        select = div.find_ancestor(exp.Select)
        grouped = select is not None and select.args.get("group") is not None
        if grouped and isinstance(denominator, exp.Count):
            continue  # COUNT per group is at least 1
        if _denominator_is_guarded(div, denominator):
            continue
        issues.append(
            Issue(
                "division_by_zero",
                f"`{_show(div)}` fails or gives wrong results when `{_show(denominator)}` is 0. "
                f"Guard it, for example `{_show(div.this)} / NULLIF({_show(denominator)}, 0)`.",
            )
        )
    return issues


# --------------------------------------------------------------------------- dates

_DATE_LITERAL = re.compile(r"^\s*(\d{4})-(\d{1,2})(?:-(\d{1,2}))?(?:[ T].*)?$")


def _date_literals(tree: exp.Expression) -> list[Issue]:
    issues = []
    for lit in tree.find_all(exp.Literal):
        if not lit.is_string:
            continue
        match = _DATE_LITERAL.match(lit.this)
        if not match:
            continue
        year, month, day = int(match.group(1)), int(match.group(2)), match.group(3)
        if day is None and not 1900 <= year <= 2200:
            continue  # "1234-56" is more likely a code than a year-month
        if not 1 <= month <= 12:
            issues.append(Issue("invalid_date", f"'{lit.this}' isn't a real date: there is no month {month:02d}."))
        elif day is not None and not 1 <= int(day) <= calendar.monthrange(year, month)[1]:
            issues.append(
                Issue(
                    "invalid_date",
                    f"'{lit.this}' isn't a real date: {calendar.month_name[month]} {year} has "
                    f"{calendar.monthrange(year, month)[1]} days.",
                )
            )
    return issues


_ARITHMETIC = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.IntDiv, exp.Mod, exp.Floor, exp.Ceil)
_DATE_TYPES = {"DATE", "DATETIME", "TIMESTAMP", "TIMESTAMPTZ"}
_FROM_PARTS_NAMES = {"MAKE_DATE", "DATE_FROM_PARTS", "DATEFROMPARTS", "TIMESTAMP_FROM_PARTS"}


def _has_arithmetic(node: exp.Expression) -> bool:
    return any(isinstance(n, _ARITHMETIC) for n in node.walk())


def _date_construction(tree: exp.Expression) -> list[Issue]:
    issues = []

    for node in tree.find_all(exp.DateFromParts, exp.Anonymous):
        if isinstance(node, exp.Anonymous):
            if node.name.upper() not in _FROM_PARTS_NAMES or len(node.expressions) < 3:
                continue
            _, month, day = node.expressions[:3]
        else:
            month, day = node.args.get("month"), node.args.get("day")
        if month is None:
            continue
        if _is_number(month) and not 1 <= float(_unwrap(month).this) <= 12:
            issues.append(Issue("invalid_date", f"`{_show(node)}` builds a date with month {_unwrap(month).this}."))
        elif day is not None and _is_number(day) and not 1 <= float(_unwrap(day).this) <= 31:
            issues.append(Issue("invalid_date", f"`{_show(node)}` builds a date with day {_unwrap(day).this}."))
        elif _has_arithmetic(month):
            issues.append(
                Issue(
                    "date_from_arithmetic",
                    f"`{_show(node)}` computes the month with arithmetic, which can land outside 1-12 "
                    "(month 0 or 13 near a year boundary). Use a native date function such as "
                    "DATE_TRUNC / DATE_FORMAT / DATEFROMPARTS(YEAR(d), MONTH(d), 1) on the original date.",
                )
            )

    # A date assembled by gluing year/month text together.
    for node in tree.find_all(exp.Cast, exp.StrToDate, exp.TsOrDsToDate):
        target = node.args.get("to")
        if isinstance(node, exp.Cast) and not (isinstance(target, exp.DataType) and target.this.name in _DATE_TYPES):
            continue
        inner = _unwrap(node.this)
        if isinstance(inner, (exp.Concat, exp.DPipe, exp.ConcatWs)):
            issues.append(
                Issue(
                    "date_from_text",
                    f"`{_show(node)}` builds a date by joining text together. Take it from the original "
                    "date with a native function (DATE_TRUNC, DATE_FORMAT, etc.) instead.",
                    "error" if _has_arithmetic(inner) else "warning",
                )
            )
    return issues


def _is_year(node: exp.Expression) -> bool:
    if isinstance(node, exp.Year) or (isinstance(node, exp.Extract) and node.name.upper() == "YEAR"):
        return True
    if isinstance(node, exp.TimeToStr):  # strftime('%Y', d), TO_CHAR(d, 'YYYY'), DATE_FORMAT(d, '%Y')
        fmt = node.args.get("format")
        return fmt is not None and bool(re.fullmatch(r"%Y|YYYY|yyyy", fmt.name))
    return False


def _month_index_roundtrip(tree: exp.Expression) -> list[Issue]:
    """Detects the month-number trick (year*12 + month) when the number is later
    converted back to a calendar month, and the YYYYMM integer trick when it is
    used for consecutive-period logic. Both produce months 00/13 at year edges."""
    issues = []

    encodes_12 = any(
        isinstance(mul, exp.Mul)
        and (_is_number(mul.left, 12) or _is_number(mul.right, 12))
        and any(_is_year(n) for n in mul.walk())
        for mul in tree.find_all(exp.Mul)
    )
    if encodes_12:
        decodes = any(
            (isinstance(n, (exp.Mod, exp.Div, exp.IntDiv)) and _is_number(n.expression, 12)) for n in tree.walk()
        )
        if decodes:
            issues.append(
                Issue(
                    "month_index_roundtrip",
                    "The query turns months into a number (year*12 + month) and then converts that number "
                    "back into a year and month with % 12 or / 12. That is easy to get wrong and can produce "
                    "month 00 or 13. Keep a real month-start date next to the number (DATE_TRUNC / "
                    "DATE_FORMAT / DATEFROMPARTS on the original date) and report MIN/MAX of that date "
                    "instead of decoding the number.",
                )
            )

    encodes_yyyymm = any(
        isinstance(mul, exp.Mul)
        and any(_is_number(side, v) for side in (mul.left, mul.right) for v in (100, 10000))
        and any(_is_year(n) for n in mul.walk())
        for mul in tree.find_all(exp.Mul)
    )
    sequence_logic = any(
        isinstance(w.this, (exp.RowNumber, exp.DenseRank, exp.Lag, exp.Lead)) for w in tree.find_all(exp.Window)
    )
    if encodes_yyyymm and sequence_logic:
        issues.append(
            Issue(
                "yyyymm_sequence",
                "A YYYYMM integer (year*100 + month) isn't contiguous across years (202512 is followed by "
                "202601, not 202513), so using it to find consecutive months breaks at year boundaries. "
                "Compare real month-start dates instead.",
            )
        )
    return issues


_NO_DATE_ARITHMETIC = {
    "mysql": ("DATE_ADD(d, INTERVAL n DAY)", "DATEDIFF(a, b)"),
    "sqlite": ("date(d, '+n days')", "julianday(a) - julianday(b)"),
    "tsql": ("DATEADD(day, n, d)", "DATEDIFF(day, b, a)"),
    "bigquery": ("DATE_ADD(d, INTERVAL n DAY)", "DATE_DIFF(a, b, DAY)"),
}


def _is_temporal(node: exp.Expression) -> bool:
    return node.type is not None and node.type.is_type(*exp.DataType.TEMPORAL_TYPES)


def _date_arithmetic(tree: exp.Expression, dialect: str) -> list[Issue]:
    if dialect not in _NO_DATE_ARITHMETIC:
        return []  # PostgreSQL, Oracle and Snowflake do add/subtract days with + and -
    add_hint, diff_hint = _NO_DATE_ARITHMETIC[dialect]
    issues = []
    for node in tree.find_all(exp.Add, exp.Sub):
        left, right = node.left, node.right
        if _is_temporal(left) and not _is_temporal(right) and right.type is not None and right.type.is_type(*exp.DataType.NUMERIC_TYPES):
            issues.append(
                Issue(
                    "date_arithmetic",
                    f"`{_show(node)}` adds a plain number to a date; {DIALECTS[dialect]} doesn't "
                    f"treat that as days. Use {add_hint}.",
                )
            )
        elif isinstance(node, exp.Sub) and _is_temporal(left) and _is_temporal(right):
            issues.append(
                Issue(
                    "date_arithmetic",
                    f"`{_show(node)}` subtracts two dates with `-`; {DIALECTS[dialect]} doesn't "
                    f"give a number of days that way. Use {diff_hint}.",
                )
            )
    return issues


# --------------------------------------------------------------------------- dialect syntax

_AVOID: dict[str, list[tuple[str, str]]] = {
    "mysql": [
        (r"\bDATE_TRUNC\s*\(", "DATE_TRUNC isn't a MySQL function; use DATE_FORMAT(d, '%Y-%m-01') or DATE_SUB(d, INTERVAL DAYOFMONTH(d) - 1 DAY)"),
        (r"\bILIKE\b", "ILIKE isn't MySQL; use LIKE (case-insensitive by default collation) or LOWER(x) LIKE"),
        (r"::\s*\w+", "the :: cast is PostgreSQL; use CAST(x AS type)"),
        (r"\bTO_CHAR\s*\(", "TO_CHAR isn't MySQL; use DATE_FORMAT or CAST"),
        (r"\bSTRING_AGG\s*\(", "STRING_AGG isn't MySQL; use GROUP_CONCAT"),
        (r"\bGENERATE_SERIES\s*\(", "GENERATE_SERIES isn't MySQL; use a recursive CTE"),
        (r"\bDATEADD\s*\(", "DATEADD is SQL Server; use DATE_ADD(d, INTERVAL n UNIT)"),
        (r"\bGETDATE\s*\(", "GETDATE is SQL Server; use NOW()"),
        (r"\bSTRFTIME\s*\(", "STRFTIME is SQLite; use DATE_FORMAT"),
        (r"\bSELECT\s+(?:DISTINCT\s+)?TOP\s+\d", "TOP is SQL Server; use LIMIT"),
        (r"\bINTERVAL\s+'\s*\d+\s*\w+\s*'", "INTERVAL '1 month' is PostgreSQL; MySQL uses INTERVAL 1 MONTH"),
        (r"\bAGE\s*\(", "AGE isn't MySQL; use TIMESTAMPDIFF"),
    ],
    "postgres": [
        (r"\bDATE_FORMAT\s*\(", "DATE_FORMAT is MySQL; use TO_CHAR(d, 'YYYY-MM') or DATE_TRUNC('month', d)"),
        (r"\b(YEAR|MONTH|DAY)\s*\(", "YEAR()/MONTH()/DAY() don't exist in PostgreSQL; use EXTRACT(YEAR FROM d)"),
        (r"\bIFNULL\s*\(", "IFNULL isn't PostgreSQL; use COALESCE"),
        (r"\bISNULL\s*\(", "ISNULL() isn't PostgreSQL; use COALESCE"),
        (r"\bGETDATE\s*\(", "GETDATE is SQL Server; use NOW() or CURRENT_TIMESTAMP"),
        (r"\bDATEADD\s*\(", "DATEADD is SQL Server; use d + INTERVAL '1 month'"),
        (r"\bDATEDIFF\s*\(", "DATEDIFF isn't PostgreSQL; subtract dates or use AGE()"),
        (r"\bDATE_ADD\s*\(", "DATE_ADD is MySQL; use d + INTERVAL '1 day'"),
        (r"\bSTRFTIME\s*\(", "STRFTIME is SQLite; use TO_CHAR"),
        (r"\bGROUP_CONCAT\s*\(", "GROUP_CONCAT is MySQL; use STRING_AGG"),
        (r"\bSELECT\s+(?:DISTINCT\s+)?TOP\s+\d", "TOP is SQL Server; use LIMIT"),
        (r"\bINTERVAL\s+\d+\s+(?:YEAR|MONTH|DAY|HOUR|WEEK)S?\b", "PostgreSQL needs the interval quoted: INTERVAL '1 month'"),
        (r"\bCURDATE\s*\(", "CURDATE is MySQL; use CURRENT_DATE"),
        (r"\bLAST_DAY\s*\(", "LAST_DAY isn't PostgreSQL; use DATE_TRUNC('month', d) + INTERVAL '1 month - 1 day'"),
    ],
    "sqlite": [
        (r"\bDATE_TRUNC\s*\(", "DATE_TRUNC doesn't exist in SQLite; use date(d, 'start of month')"),
        (r"\bDATE_FORMAT\s*\(", "DATE_FORMAT is MySQL; use strftime('%Y-%m', d)"),
        (r"\b(YEAR|MONTH|DAY)\s*\(", "YEAR()/MONTH()/DAY() don't exist in SQLite; use strftime('%Y', d)"),
        (r"\bEXTRACT\s*\(", "EXTRACT isn't supported in SQLite; use strftime"),
        (r"\bDATEADD\s*\(", "DATEADD is SQL Server; use date(d, '+1 month')"),
        (r"\bDATEDIFF\s*\(", "DATEDIFF isn't SQLite; use julianday(a) - julianday(b)"),
        (r"\bDATE_ADD\s*\(", "DATE_ADD isn't SQLite; use date(d, '+1 day')"),
        (r"\bILIKE\b", "ILIKE isn't SQLite; use LIKE"),
        (r"::\s*\w+", "the :: cast is PostgreSQL; use CAST(x AS type)"),
        (r"\bTO_CHAR\s*\(", "TO_CHAR isn't SQLite; use strftime"),
        (r"\bNOW\s*\(", "NOW() isn't SQLite; use datetime('now')"),
        (r"\bINTERVAL\b", "SQLite has no INTERVAL; use date(d, '+1 month')"),
        (r"\bGETDATE\s*\(", "GETDATE is SQL Server; use datetime('now')"),
        (r"\bCURDATE\s*\(", "CURDATE is MySQL; use date('now')"),
    ],
    "tsql": [
        (r"\bDATE_TRUNC\s*\(", "DATE_TRUNC isn't SQL Server; use DATEFROMPARTS(YEAR(d), MONTH(d), 1)"),
        (r"\bDATE_FORMAT\s*\(", "DATE_FORMAT is MySQL; use FORMAT(d, 'yyyy-MM') or DATEFROMPARTS"),
        (r"\bEXTRACT\s*\(", "EXTRACT isn't SQL Server; use YEAR(d), MONTH(d) or DATEPART"),
        (r"\bILIKE\b", "ILIKE isn't SQL Server; use LIKE"),
        (r"::\s*\w+", "the :: cast is PostgreSQL; use CAST(x AS type)"),
        (r"\bNOW\s*\(", "NOW() isn't SQL Server; use GETDATE()"),
        (r"\bIFNULL\s*\(", "IFNULL isn't SQL Server; use ISNULL or COALESCE"),
        (r"\bSTRFTIME\s*\(", "STRFTIME is SQLite; use FORMAT"),
        (r"\bGROUP_CONCAT\s*\(", "GROUP_CONCAT is MySQL; use STRING_AGG"),
        (r"\bINTERVAL\b", "SQL Server has no INTERVAL; use DATEADD(month, 1, d)"),
        (r"\bTO_CHAR\s*\(", "TO_CHAR isn't SQL Server; use FORMAT"),
        (r"\bDATE_ADD\s*\(", "DATE_ADD is MySQL; use DATEADD(day, n, d)"),
        (r"\bCURDATE\s*\(", "CURDATE is MySQL; use CAST(GETDATE() AS date)"),
        (r"\bLAST_DAY\s*\(", "LAST_DAY isn't SQL Server; use EOMONTH(d)"),
        (r"\bSUBSTR\s*\(", "SUBSTR isn't SQL Server; use SUBSTRING"),
        (r"\bLENGTH\s*\(", "LENGTH isn't SQL Server; use LEN"),
        (r"\b(?:TRUE|FALSE)\b", "SQL Server has no TRUE/FALSE literals; use 1 and 0"),
    ],
    "oracle": [
        (r"\bTOP\s+\d", "TOP is SQL Server; use FETCH FIRST n ROWS ONLY"),
        (r"\bILIKE\b", "ILIKE isn't Oracle; use UPPER(x) LIKE UPPER(...)"),
        (r"::\s*\w+", "the :: cast is PostgreSQL; use CAST(x AS type)"),
        (r"\bIFNULL\s*\(", "IFNULL isn't Oracle; use NVL or COALESCE"),
        (r"\bISNULL\s*\(", "ISNULL() isn't Oracle; use NVL or COALESCE"),
        (r"\bNOW\s*\(", "NOW() isn't Oracle; use SYSDATE or CURRENT_TIMESTAMP"),
        (r"\bDATE_TRUNC\s*\(", "DATE_TRUNC isn't Oracle; use TRUNC(d, 'MM')"),
        (r"\bDATE_FORMAT\s*\(", "DATE_FORMAT is MySQL; use TO_CHAR(d, 'YYYY-MM')"),
        (r"\bGETDATE\s*\(", "GETDATE is SQL Server; use SYSDATE"),
        (r"\b(YEAR|MONTH|DAY)\s*\(", "YEAR()/MONTH()/DAY() don't exist in Oracle; use EXTRACT(YEAR FROM d)"),
        (r"\bDATEADD\s*\(", "DATEADD is SQL Server; use ADD_MONTHS(d, n) or d + n"),
        (r"\bDATEDIFF\s*\(", "DATEDIFF isn't Oracle; subtract dates or use MONTHS_BETWEEN"),
        (r"\bSTRFTIME\s*\(", "STRFTIME is SQLite; use TO_CHAR"),
        (r"\bGROUP_CONCAT\s*\(", "GROUP_CONCAT is MySQL; use LISTAGG"),
        (r"\bSTRING_AGG\s*\(", "STRING_AGG isn't Oracle; use LISTAGG"),
        (r"\bINTERVAL\s+\d+\s+(?:YEAR|MONTH|DAY)", "Oracle needs the interval quoted: INTERVAL '1' MONTH"),
        (r"\b(?:FROM|JOIN)\s+[\w.\"]+\s+AS\s+\w+", "Oracle doesn't allow AS before a table alias"),
    ],
    "bigquery": [
        (r"\b(YEAR|MONTH|DAY)\s*\(", "YEAR()/MONTH()/DAY() don't exist in BigQuery; use EXTRACT(YEAR FROM d)"),
        (r"\bDATE_FORMAT\s*\(", "DATE_FORMAT is MySQL; use FORMAT_DATE('%Y-%m', d) or DATE_TRUNC(d, MONTH)"),
        (r"\bDATE_TRUNC\s*\(\s*'", "BigQuery's DATE_TRUNC takes the unit unquoted: DATE_TRUNC(d, MONTH)"),
        (r"\bDATEADD\s*\(", "DATEADD is SQL Server; use DATE_ADD(d, INTERVAL n UNIT)"),
        (r"\bDATEDIFF\s*\(", "DATEDIFF isn't BigQuery; use DATE_DIFF(a, b, DAY)"),
        (r"\bILIKE\b", "ILIKE isn't BigQuery; use LOWER(x) LIKE"),
        (r"\bNOW\s*\(", "NOW() isn't BigQuery; use CURRENT_TIMESTAMP()"),
        (r"\bISNULL\s*\(", "ISNULL() isn't BigQuery; use IFNULL or COALESCE"),
        (r"\bGETDATE\s*\(", "GETDATE is SQL Server; use CURRENT_DATE()"),
        (r"\bSTRFTIME\s*\(", "STRFTIME is SQLite; use FORMAT_DATE"),
        (r"::\s*\w+", "the :: cast is PostgreSQL; use CAST(x AS type)"),
        (r"\bSELECT\s+(?:DISTINCT\s+)?TOP\s+\d", "TOP is SQL Server; use LIMIT"),
        (r"\bGROUP_CONCAT\s*\(", "GROUP_CONCAT is MySQL; use STRING_AGG"),
        (r"\bINTERVAL\s+'", "BigQuery writes INTERVAL 1 MONTH, without quotes"),
    ],
    "snowflake": [
        (r"\bDATE_FORMAT\s*\(", "DATE_FORMAT is MySQL; use TO_CHAR(d, 'YYYY-MM') or DATE_TRUNC('month', d)"),
        (r"\bSTRFTIME\s*\(", "STRFTIME is SQLite; use TO_CHAR"),
        (r"\bGROUP_CONCAT\s*\(", "GROUP_CONCAT is MySQL; use LISTAGG"),
        (r"\bSTRING_AGG\s*\(", "STRING_AGG isn't Snowflake; use LISTAGG"),
        (r"\bCURDATE\s*\(", "CURDATE is MySQL; use CURRENT_DATE()"),
        (r"\bINTERVAL\s+\d+\s+(?:YEAR|MONTH|DAY)", "Snowflake needs the interval quoted: INTERVAL '1 month'"),
        (r"\bDATE_ADD\s*\(\s*(?:MONTH|DAY|YEAR)", "use DATEADD(month, n, d) in Snowflake"),
    ],
}


def _strip_noise(sql: str) -> str:
    """Remove comments and string literals so keywords inside them don't match."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


# Rules about what is *inside* a string literal (INTERVAL '1 month'), so they run on text
# with comments removed but literals kept.
_NEEDS_LITERALS = {r"\bINTERVAL\s+'\s*\d+\s*\w+\s*'"}


def dialect_issues(sql: str, dialect: str) -> list[Issue]:
    """Syntax that belongs to another database. Purely textual, so it also works on
    SQL that doesn't parse (where the useful message is what to write instead)."""
    label = DIALECTS[dialect]
    cleaned = _strip_noise(sql)
    with_literals = re.sub(r"--[^\n]*", " ", re.sub(r"/\*.*?\*/", " ", sql, flags=re.S))
    issues = []
    for pattern, advice in _AVOID.get(dialect, []):
        text = with_literals if pattern in _NEEDS_LITERALS else cleaned
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(Issue("dialect_syntax", f"This isn't {label} syntax: {advice}."))
    return issues


# --------------------------------------------------------------------------- aliases

# Where each dialect lets a SELECT-list alias be used again. ORDER BY always works.
_ALIAS_ALLOWED: dict[str, set[str]] = {
    "postgres": {"GROUP BY", "ORDER BY"},
    "mysql": {"GROUP BY", "HAVING", "ORDER BY"},
    "sqlite": {"WHERE", "GROUP BY", "HAVING", "ORDER BY"},
    "tsql": {"ORDER BY"},
    "oracle": {"GROUP BY", "HAVING", "ORDER BY"},
    "bigquery": {"GROUP BY", "HAVING", "ORDER BY"},
    "snowflake": {"WHERE", "GROUP BY", "HAVING", "ORDER BY", "another SELECT column"},
}


def _source_columns(select: exp.Select, ctes: dict[str, exp.Expression], schema: ParsedSchema | None) -> set[str] | None:
    """Lower-case column names available from the FROM/JOIN sources, or None when
    they can't all be determined (unknown table, SELECT *, table function)."""
    columns: set[str] = set()
    for source in _sources(select):
        if isinstance(source, exp.Table):
            name = source.name.lower()
            if name in ctes:
                inner = ctes[name]
                if _has_star(inner):
                    return None
                columns.update(n.lower() for n in inner.named_selects)
            elif schema is not None and name in schema.table_names():
                real = schema.table_names()[name]
                columns.update(c.name.lower() for t in schema.tables if t.name == real for c in t.columns)
            else:
                return None
        elif isinstance(source, exp.Subquery) and isinstance(source.this, exp.Select):
            if _has_star(source.this):
                return None
            columns.update(n.lower() for n in source.this.named_selects)
        else:
            return None
    return columns


def _alias_scope(tree: exp.Expression, schema: ParsedSchema | None, dialect: str) -> list[Issue]:
    if schema is None:
        return []
    allowed = _ALIAS_ALLOWED[dialect]
    ctes = _cte_map(tree)
    issues = []
    for select in tree.find_all(exp.Select):
        aliases = {p.alias.lower() for p in select.expressions if isinstance(p, exp.Alias) and p.alias}
        if not aliases:
            continue
        real = _source_columns(select, ctes, schema)
        if real is None:
            continue
        reusable = aliases - real  # an alias that shares a real column's name resolves to the column

        clauses: list[tuple[str, exp.Expression]] = []
        for label, key in (("WHERE", "where"), ("GROUP BY", "group"), ("HAVING", "having")):
            if label not in allowed and select.args.get(key) is not None:
                clauses.append((label, select.args[key]))
        if "another SELECT column" not in allowed:
            for projection in select.expressions:
                if isinstance(projection, exp.Alias):
                    clauses.append(("another SELECT column", projection.this))

        for label, node in clauses:
            for part in _scope_nodes(node):
                if isinstance(part, exp.Column) and not part.table and part.name.lower() in reusable:
                    issues.append(
                        Issue(
                            "alias_scope",
                            f"`{part.name}` is an alias defined in the SELECT list, but {DIALECTS[dialect]} "
                            f"doesn't let you use it in {label}. Repeat the expression, or compute it in a "
                            "subquery or CTE and use the alias outside.",
                        )
                    )
    return issues


# --------------------------------------------------------------------------- aggregation and windows

_ORDER_DEPENDENT = (
    exp.RowNumber, exp.Rank, exp.DenseRank, exp.PercentRank, exp.CumeDist, exp.Ntile,
    exp.Lag, exp.Lead, exp.FirstValue, exp.LastValue, exp.NthValue,
)


def _aggregate_misuse(tree: exp.Expression, dialect: str) -> list[Issue]:
    issues = []
    for select in tree.find_all(exp.Select):
        where = select.args.get("where")
        if where is not None:
            for node in _scope_nodes(where):
                if isinstance(node, exp.AggFunc) and not _is_windowed(node):
                    issues.append(
                        Issue(
                            "aggregate_in_where",
                            f"`{_show(node)}` is an aggregate inside WHERE, which isn't allowed. "
                            "Filter aggregates with HAVING, or aggregate in a subquery.",
                        )
                    )
                    break

    if dialect != "oracle":  # Oracle allows nesting aggregates when there is a GROUP BY
        for agg in tree.find_all(exp.AggFunc):
            if _is_windowed(agg):
                continue
            for inner in agg.find_all(exp.AggFunc):
                if inner is not agg and not _is_windowed(inner):
                    issues.append(
                        Issue("nested_aggregate", f"`{_show(agg)}` nests one aggregate inside another. Aggregate in a subquery first.")
                    )
                    break
    return issues


def _windows(tree: exp.Expression) -> list[Issue]:
    issues = []
    for window in tree.find_all(exp.Window):
        text = _show(window)
        parent = window.find_ancestor(exp.Select, exp.Where, exp.Having, exp.Group)
        if isinstance(parent, (exp.Where, exp.Having, exp.Group)):
            clause = {exp.Where: "WHERE", exp.Having: "HAVING", exp.Group: "GROUP BY"}[type(parent)]
            issues.append(
                Issue(
                    "window_in_clause",
                    f"A window function (`{text}`) can't be used in {clause}. Compute it in a subquery or CTE "
                    "and filter on the result outside (or use QUALIFY where the dialect supports it).",
                )
            )
        outer = window.find_ancestor(exp.AggFunc, exp.Window, exp.Select)
        if isinstance(outer, exp.AggFunc):
            issues.append(Issue("window_in_aggregate", f"`{text}` is a window function inside an aggregate, which isn't allowed."))
        elif isinstance(outer, exp.Window):
            issues.append(Issue("window_in_window", f"`{text}` nests a window function inside another window function."))
        if isinstance(window.this, _ORDER_DEPENDENT) and not window.args.get("order"):
            issues.append(
                Issue(
                    "window_without_order",
                    f"`{text}` needs an ORDER BY inside OVER(...); without it the result depends on arbitrary row order.",
                )
            )
    return issues


def _normalized(node: exp.Expression) -> str:
    return _unwrap(node).sql().lower()


def _grouping(qualified: exp.Expression, schema: ParsedSchema | None) -> list[Issue]:
    """Every selected/ordered column must be grouped or aggregated. Works on the
    qualified tree, where aliases and ordinals in GROUP BY are already expanded."""
    issues = []
    pk_by_table: dict[str, set[str]] = {}
    if schema is not None:
        for table in schema.tables:
            pk_by_table[table.name.lower()] = {c.name.lower() for c in table.columns if c.primary_key}

    for select in qualified.find_all(exp.Select):
        group = select.args.get("group")
        having = select.args.get("having")
        if group is not None and any(isinstance(g, (exp.Rollup, exp.Cube, exp.GroupingSets)) for g in group.expressions):
            continue
        group_exprs = list(group.expressions) if group is not None else []
        group_sql = {_normalized(g) for g in group_exprs}
        group_cols = {(g.table.lower(), g.name.lower()) for g in (_unwrap(x) for x in group_exprs) if isinstance(g, exp.Column)}

        checked = list(select.expressions) + ([having.this] if having is not None else [])
        has_aggregate = any(
            isinstance(n, exp.AggFunc) and not _is_windowed(n)
            for part in checked
            for n in _scope_nodes(part)
        )
        if group is None and not has_aggregate:
            continue

        aliases = {p.alias.lower() for p in select.expressions if isinstance(p, exp.Alias) and p.alias}
        local_tables: dict[str, str] = {}
        for source in _sources(select):
            if isinstance(source, exp.Table):
                local_tables[source.alias_or_name.lower()] = source.name.lower()
            elif source.alias:
                local_tables[source.alias.lower()] = ""

        def covered(column: exp.Column) -> bool:
            table = column.table.lower()
            if not table:
                return column.name.lower() in aliases
            if table not in local_tables:
                return True  # a correlated reference to an outer query
            real = local_tables[table]
            keys = pk_by_table.get(real)
            return bool(keys) and all((table, key) in group_cols for key in keys)  # functional dependency on the PK

        def ungrouped(node: exp.Expression) -> list[exp.Column]:
            if _normalized(node) in group_sql or isinstance(node, (exp.AggFunc, exp.Query)):
                return []
            if isinstance(node, exp.Column):
                return [] if covered(node) else [node]
            found: list[exp.Column] = []
            for child in node.iter_expressions():
                found.extend(ungrouped(child))
            return found

        reported: set[str] = set()
        order = select.args.get("order")
        for part in checked + ([order] if order is not None else []):
            for column in ungrouped(part):
                if column.sql() in reported:
                    continue
                reported.add(column.sql())
                if group is None:
                    reason = "the query aggregates but has no GROUP BY"
                else:
                    reason = "it isn't in the GROUP BY or inside an aggregate function"
                issues.append(
                    Issue(
                        "group_by",
                        f"`{column.name}` is selected next to aggregates, but {reason}. Add it to GROUP BY "
                        "or wrap it in an aggregate (MIN, MAX, ...).",
                    )
                )
    return issues


# --------------------------------------------------------------------------- joins


def _joins(tree: exp.Expression, qualified: exp.Expression | None, schema: ParsedSchema | None) -> list[Issue]:
    issues = []
    for join in tree.find_all(exp.Join):
        kind = (join.args.get("kind") or "").upper()
        side = (join.args.get("side") or "").upper()
        if join.args.get("on") is None and not join.args.get("using") and kind != "CROSS" and not join.args.get("method") and not isinstance(join.this, (exp.Unnest, exp.Lateral)):
            issues.append(
                Issue(
                    "join_without_condition",
                    f"The {side + ' ' if side else ''}JOIN to `{_show(join.this)}` has no ON condition, so every "
                    "row is paired with every row. Add the join condition (or write CROSS JOIN if that is intended).",
                )
            )

    if qualified is None or schema is None:
        return issues

    foreign: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for table in schema.tables:
        for column in table.columns:
            if column.foreign_key and "." in column.foreign_key:
                parent, parent_col = column.foreign_key.lower().split(".", 1)
                pair = ((table.name.lower(), column.name.lower()), (parent, parent_col))
                foreign.setdefault(tuple(sorted((pair[0][0], pair[1][0]))), set()).add(tuple(sorted(pair)))

    for select in qualified.find_all(exp.Select):
        names = {}
        for source in _sources(select):
            if isinstance(source, exp.Table):
                names[source.alias_or_name.lower()] = source.name.lower()
        for join in select.args.get("joins") or []:
            on = join.args.get("on")
            if on is None:
                continue
            for eq in on.find_all(exp.EQ):
                left, right = eq.this, eq.expression
                if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                    continue
                lt, rt = names.get(left.table.lower()), names.get(right.table.lower())
                if not lt or not rt or lt == rt:
                    continue
                declared = foreign.get(tuple(sorted((lt, rt))))
                if not declared:
                    continue
                pair = tuple(sorted(((lt, left.name.lower()), (rt, right.name.lower()))))
                if pair not in declared:
                    issues.append(
                        Issue(
                            "join_mismatch",
                            f"`{_show(eq)}` joins {lt} to {rt} on columns the schema doesn't relate; "
                            f"the schema links them through a foreign key on different columns.",
                            "warning",
                        )
                    )
    return issues


# --------------------------------------------------------------------------- streaks needing de-duplication

_OFFSET_CONTEXT = (
    exp.Sub, exp.Add, exp.DateAdd, exp.DateSub, exp.TsOrDsAdd, exp.Interval, exp.DPipe, exp.Concat, exp.Date, exp.Anonymous,
)
_PERIOD_HINT = re.compile(r"(date|month|day|week|period|time|_at$)", re.IGNORECASE)


def _is_period_order(ordered: exp.Expression) -> bool:
    for node in ordered.walk():
        if isinstance(node, (exp.Year, exp.Month, exp.Day, exp.Extract, exp.DateTrunc, exp.TimeToStr, exp.TsOrDsToDate, exp.StrToDate)):
            return True
        if isinstance(node, exp.Column) and _PERIOD_HINT.search(node.name):
            return True
    return False


def _deduplicated(select: exp.Select, ctes: dict[str, exp.Expression]) -> bool:
    for source in _sources(select):
        inner = None
        if isinstance(source, exp.Subquery):
            inner = source.this
        elif isinstance(source, exp.Table) and source.name.lower() in ctes:
            inner = ctes[source.name.lower()]
        if isinstance(inner, exp.Select) and (inner.args.get("distinct") or inner.args.get("group")):
            return True
    return False


def _row_number_without_dedupe(tree: exp.Expression) -> list[Issue]:
    """The classic consecutive-period bug: number the rows with ROW_NUMBER and
    subtract the number from the date to find runs, but number raw rows. Two rows
    in the same period shift every later number by one and break the run."""
    issues = []
    ctes = _cte_map(tree)
    for select in tree.find_all(exp.Select):
        for projection in select.expressions:
            if not isinstance(projection, exp.Alias):
                continue
            window = projection.this
            if not (isinstance(window, exp.Window) and isinstance(window.this, exp.RowNumber)):
                continue
            order = window.args.get("order")
            if not order or not any(_is_period_order(o) for o in order.expressions):
                continue
            if select.args.get("distinct") or select.args.get("group") or _deduplicated(select, ctes):
                continue
            alias = projection.alias.lower()
            used_as_offset = any(
                col.name.lower() == alias
                and any(isinstance(a, _OFFSET_CONTEXT) for a in _ancestors_until_select(col))
                for col in tree.find_all(exp.Column)
            )
            if used_as_offset:
                issues.append(
                    Issue(
                        "streak_without_dedupe",
                        f"`{alias}` numbers raw rows ordered by a date and is later used to find consecutive "
                        "periods. If one period has several rows, the numbering shifts and the run breaks. "
                        "Reduce to one row per entity and period first (SELECT DISTINCT or GROUP BY), "
                        "then number those.",
                    )
                )
    return issues


def _ancestors_until_select(node: exp.Expression) -> Iterator[exp.Expression]:
    parent = node.parent
    while parent is not None and not isinstance(parent, exp.Select):
        yield parent
        parent = parent.parent


# --------------------------------------------------------------------------- entry point


def _qualified(tree: exp.Expression, schema: ParsedSchema | None, dialect: str) -> exp.Expression | None:
    if schema is None:
        return None
    try:
        return qualify(tree.copy(), schema=schema.as_sqlglot_schema(), dialect=dialect, validate_qualify_columns=True)
    except Exception:
        return None  # unknown tables/columns are reported by the schema check; this is only for deeper rules


def check_logic(sql: str, schema: ParsedSchema | None, dialect: str) -> list[Issue]:
    """All logic/dialect issues for one statement, errors first. Syntax errors are
    the parser's job (schema_validation), so unparseable input returns no issues."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except ParseError:
        return []

    _DIALECT.set(dialect)
    issues: list[Issue] = []
    issues += _null_comparisons(tree)
    issues += _division(tree)
    issues += _date_literals(tree)
    issues += _date_construction(tree)
    issues += _month_index_roundtrip(tree)
    issues += dialect_issues(sql, dialect)
    issues += _alias_scope(tree, schema, dialect)
    issues += _aggregate_misuse(tree, dialect)
    issues += _windows(tree)
    issues += _row_number_without_dedupe(tree)

    qualified = _qualified(tree, schema, dialect)
    if qualified is not None:
        issues += _grouping(qualified, schema)
    issues += _joins(tree, qualified, schema)

    typed = qualified if qualified is not None else tree.copy()
    try:
        typed = annotate_types(typed, schema=schema.as_sqlglot_schema() if schema else None, dialect=dialect)
        issues += _date_arithmetic(typed, dialect)
    except Exception:
        pass  # type inference failing on an exotic query isn't a finding

    seen: set[tuple[str, str]] = set()
    unique = []
    for issue in issues:
        key = (issue.code, issue.message)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return sorted(unique, key=lambda i: not i.is_error)
