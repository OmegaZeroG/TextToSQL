"""The post-generation verification pipeline for one SQL statement.

    syntax -> schema -> logic and dialect rules -> trial run on test data

A query that merely parses is not treated as correct. Each stage can add
problems; the first stage a query fails at decides what else is worth running
(there is no point trial-running SQL that names a table that doesn't exist).

Errors are what the repair loop in main.py sends back to the model. Warnings are
shown to the user but don't block anything.
"""
from dataclasses import dataclass, field

from app.schema_parser import ParsedSchema
from app.schema_validation import check_sql_against_schema
from app.sql_checks import check_logic, dialect_issues
from app.sql_execution import verify_by_execution


@dataclass
class Verdict:
    syntax_valid: bool
    schema_ok: bool
    logic_ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tables_used: list[str] = field(default_factory=list)
    executed: bool = False  # whether the trial run happened

    @property
    def clean(self) -> bool:
        return not self.errors


def verify_sql(sql: str, schema: ParsedSchema | None, dialect: str) -> Verdict:
    check = check_sql_against_schema(sql, schema, dialect)

    if not check.syntax_valid:
        # A bare parse error doesn't say what to write instead; foreign syntax usually does.
        advice = [i.message for i in dialect_issues(sql, dialect)]
        return Verdict(False, False, True, errors=list(check.problems) + advice)

    errors: list[str] = []
    warnings: list[str] = []
    # schema_validation reports schema_ok=False for real problems, and schema_ok=True
    # with a note when it simply couldn't verify something.
    (warnings if check.schema_ok else errors).extend(check.problems)

    logic_ok = True
    for issue in check_logic(sql, schema, dialect):
        if issue.is_error:
            logic_ok = False
            errors.append(issue.message)
        else:
            warnings.append(issue.message)

    executed = False
    if check.schema_ok and schema is not None:
        trial = verify_by_execution(sql, schema, dialect)
        executed = trial.ran
        for issue in trial.issues:
            if issue.message not in errors:
                logic_ok = False
                errors.append(issue.message)

    return Verdict(True, check.schema_ok, logic_ok, errors, warnings, check.tables_used, executed)
