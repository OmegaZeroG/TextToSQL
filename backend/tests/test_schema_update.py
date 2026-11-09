import json

import pytest

from app.schema_parser import (
    SchemaChangeError,
    SchemaParseError,
    apply_schema_change,
    diff_schemas,
    merge_ddl,
    parse_ddl,
)
from tests.helpers import FakeLLM

CURRENT = """
CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, email TEXT);
CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT REFERENCES customers(id), total DECIMAL(10, 2));
"""


def no_llm():
    raise AssertionError("the LLM must not be needed for an explicit CREATE TABLE change")


def llm_returning(*ddls):
    return FakeLLM([json.dumps({"ddl": d}) for d in ddls])


class TestMergeDdl:
    def test_appends_a_new_table(self):
        merged = merge_ddl(CURRENT, "CREATE TABLE invoices (id INT, amount INT);", "postgres")
        assert [t.name for t in parse_ddl(merged, "postgres").tables] == ["customers", "orders", "invoices"]

    def test_replaces_an_existing_table_in_place(self):
        merged = merge_ddl(CURRENT, "CREATE TABLE customers (id INT PRIMARY KEY, phone TEXT);", "postgres")
        schema = parse_ddl(merged, "postgres")
        assert [t.name for t in schema.tables] == ["customers", "orders"]
        assert [c.name for c in schema.tables[0].columns] == ["id", "phone"]

    def test_table_names_match_case_insensitively(self):
        merged = merge_ddl(CURRENT, "CREATE TABLE CUSTOMERS (id INT, phone TEXT);", "postgres")
        assert len(parse_ddl(merged, "postgres").tables) == 2

    def test_untouched_tables_keep_their_keys_and_constraints(self):
        merged = merge_ddl(CURRENT, "CREATE TABLE invoices (id INT);", "postgres")
        assert "PRIMARY KEY" in merged
        assert "NOT NULL" in merged
        assert "REFERENCES customers (id)" in merged  # kept on one line, not exploded by the pretty-printer

    def test_non_ddl_additions_raise(self):
        with pytest.raises(SchemaParseError):
            merge_ddl(CURRENT, "add a phone column to customers", "postgres")


class TestDiffSchemas:
    def diff(self, new_ddl):
        return diff_schemas(parse_ddl(CURRENT, "postgres"), parse_ddl(new_ddl, "postgres"))

    def test_identical_schemas_have_no_changes(self):
        assert self.diff(CURRENT) == []

    def test_added_table(self):
        changes = self.diff(CURRENT + "CREATE TABLE invoices (id INT, amount INT);")
        assert changes == ["Added table invoices (2 columns)"]

    def test_removed_table(self):
        only_customers = "CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(100), email TEXT);"
        assert self.diff(only_customers) == ["Removed table orders"]

    def test_added_and_removed_columns(self):
        changed = (
            "CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(100), phone TEXT);"
            "CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT, total DECIMAL(10, 2));"
        )
        assert self.diff(changed) == ["Added column customers.phone (TEXT)", "Removed column customers.email"]

    def test_changed_column_type(self):
        changed = CURRENT.replace("total DECIMAL(10, 2)", "total BIGINT")
        assert self.diff(changed) == ["Changed type of orders.total: DECIMAL(10, 2) -> BIGINT"]

    def test_type_comparison_ignores_case(self):
        assert self.diff(CURRENT.replace("TEXT", "text")) == []


class TestApplySchemaChange:
    def test_explicit_create_table_is_applied_without_an_llm(self):
        result = apply_schema_change(CURRENT, "CREATE TABLE invoices (id INT, amount INT);", "postgres", no_llm)
        assert result.source == "ddl"
        assert result.changes == ["Added table invoices (2 columns)"]
        assert [t.name for t in result.parsed.tables] == ["customers", "orders", "invoices"]

    def test_replacing_a_table_may_remove_its_columns_because_that_is_explicit(self):
        result = apply_schema_change(
            CURRENT, "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);", "postgres", no_llm
        )
        assert "Removed column customers.email" in result.changes

    def test_plain_english_is_applied_by_the_llm_and_the_diff_is_reported(self):
        updated = CURRENT.replace("email TEXT", "email TEXT, phone VARCHAR(20)")
        llm = llm_returning(updated)

        result = apply_schema_change(CURRENT, "add a phone number to customers", "postgres", lambda: llm)

        assert result.source == "text"
        assert result.changes == ["Added column customers.phone (VARCHAR(20))"]

    def test_llm_receives_the_current_schema_and_the_request(self):
        llm = llm_returning(CURRENT.replace("email TEXT", "email TEXT, phone TEXT"))
        apply_schema_change(CURRENT, "add a phone number to customers", "postgres", lambda: llm)
        user = llm.calls[0]["user"]
        assert "CREATE TABLE customers" in user
        assert "add a phone number to customers" in user
        assert "Never drop a table or column unless" in llm.calls[0]["system"]

    def test_alter_table_statements_go_through_the_llm(self):
        llm = llm_returning(CURRENT.replace("email TEXT", "email TEXT, phone TEXT"))
        result = apply_schema_change(
            CURRENT, "ALTER TABLE customers ADD COLUMN phone TEXT", "postgres", lambda: llm
        )
        assert result.source == "text"
        assert result.changes == ["Added column customers.phone (TEXT)"]

    def test_retries_once_when_the_llm_returns_invalid_ddl(self):
        good = CURRENT.replace("email TEXT", "email TEXT, phone TEXT")
        llm = llm_returning("not valid ddl", good)
        result = apply_schema_change(CURRENT, "add phone to customers", "postgres", lambda: llm)
        assert result.changes == ["Added column customers.phone (TEXT)"]
        assert "failed to parse" in llm.calls[1]["user"]

    def test_gives_up_after_two_invalid_attempts(self):
        llm = llm_returning("garbage", "more garbage")
        with pytest.raises(SchemaChangeError, match="couldn't turn that change"):
            apply_schema_change(CURRENT, "add phone to customers", "postgres", lambda: llm)


class TestRefusesToApplyRiskyOrPointlessChanges:
    def test_a_no_op_is_reported_as_a_failure(self):
        llm = llm_returning(CURRENT)
        with pytest.raises(SchemaChangeError, match="doesn't change anything"):
            apply_schema_change(CURRENT, "make sure customers has a name", "postgres", lambda: llm)

    def test_an_explicit_no_op_create_table_is_also_a_failure(self):
        same = "CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, email TEXT);"
        with pytest.raises(SchemaChangeError, match="doesn't change anything"):
            apply_schema_change(CURRENT, same, "postgres", no_llm)

    def test_llm_silently_dropping_things_is_rejected(self):
        """The LLM was asked to add a column but returned a schema missing a table."""
        dropped_orders = "CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(100), email TEXT, phone TEXT);"
        llm = llm_returning(dropped_orders)
        with pytest.raises(SchemaChangeError, match="Removed table orders"):
            apply_schema_change(CURRENT, "add a phone number to customers", "postgres", lambda: llm)

    def test_llm_silently_dropping_a_column_is_rejected(self):
        dropped_email = CURRENT.replace(", email TEXT", ", phone TEXT")
        llm = llm_returning(dropped_email)
        with pytest.raises(SchemaChangeError, match="Removed column customers.email"):
            apply_schema_change(CURRENT, "add a phone number to customers", "postgres", lambda: llm)

    @pytest.mark.parametrize("request_text", [
        "remove the email column from customers",
        "drop email from customers",
        "rename email to contact",
        "delete the email field",
    ])
    def test_removals_are_allowed_when_the_user_asked_for_them(self, request_text):
        llm = llm_returning(CURRENT.replace(", email TEXT", ""))
        result = apply_schema_change(CURRENT, request_text, "postgres", lambda: llm)
        assert result.changes == ["Removed column customers.email"]

    def test_an_unreadable_current_schema_is_reported(self):
        with pytest.raises(SchemaChangeError, match="saved schema can't be read"):
            apply_schema_change("garbage", "add a table", "postgres", no_llm)

    def test_failures_never_return_a_partial_result(self):
        """apply_schema_change either returns a complete UpdatedSchema or raises."""
        llm = llm_returning("garbage", "garbage")
        with pytest.raises(SchemaParseError):
            apply_schema_change(CURRENT, "add something", "postgres", lambda: llm)
