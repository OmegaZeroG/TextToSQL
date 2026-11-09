import json

import pytest

from app.schema_parser import SchemaParseError, analyze_schema, parse_ddl
from tests.helpers import FakeLLM

POSTGRES_DDL = """
CREATE TABLE customers (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email TEXT
);
CREATE TABLE orders (
    id INT PRIMARY KEY,
    customer_id INT REFERENCES customers(id),
    total DECIMAL(10, 2)
);
"""


def no_llm():
    raise AssertionError("the LLM must not be needed when the input is already valid DDL")


class TestParseDdl:
    def test_extracts_tables_columns_and_types(self):
        schema = parse_ddl(POSTGRES_DDL, "postgres")
        assert [t.name for t in schema.tables] == ["customers", "orders"]
        assert [(c.name, c.type) for c in schema.tables[1].columns] == [
            ("id", "INT"), ("customer_id", "INT"), ("total", "DECIMAL(10, 2)"),
        ]

    def test_exposes_a_sqlglot_schema_mapping(self):
        mapping = parse_ddl(POSTGRES_DDL, "postgres").as_sqlglot_schema()
        assert set(mapping) == {"customers", "orders"}
        assert set(mapping["orders"]) == {"id", "customer_id", "total"}

    def test_table_names_are_case_insensitive_lookups(self):
        assert parse_ddl(POSTGRES_DDL, "postgres").table_names()["customers"] == "customers"

    @pytest.mark.parametrize("dialect, ddl, table", [
        ("mysql", "CREATE TABLE `users` (`id` INT AUTO_INCREMENT PRIMARY KEY, `name` VARCHAR(50)) ENGINE=InnoDB;", "users"),
        ("tsql", "CREATE TABLE [dbo].[users] ([id] INT IDENTITY(1,1) PRIMARY KEY, [name] NVARCHAR(50));", "users"),
        ("oracle", "CREATE TABLE users (id NUMBER(10) PRIMARY KEY, name VARCHAR2(50));", "users"),
        ("sqlite", "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);", "users"),
        ("bigquery", "CREATE TABLE `proj.ds.users` (id INT64, name STRING);", "users"),
        ("snowflake", "CREATE TABLE users (id NUMBER, name VARCHAR);", "users"),
    ])
    def test_dialect_specific_ddl(self, dialect, ddl, table):
        schema = parse_ddl(ddl, dialect)
        assert [t.name for t in schema.tables] == [table]
        assert [c.name for c in schema.tables[0].columns] == ["id", "name"]

    def test_ignores_statements_that_are_not_table_definitions(self):
        ddl = POSTGRES_DDL + "\nCREATE INDEX idx_orders_total ON orders (total);\nINSERT INTO customers VALUES (1, 'a', 'b');"
        assert [t.name for t in parse_ddl(ddl, "postgres").tables] == ["customers", "orders"]

    def test_ctas_without_a_column_list_is_not_a_schema(self):
        with pytest.raises(SchemaParseError):
            parse_ddl("CREATE TABLE copy AS SELECT * FROM orders", "postgres")

    @pytest.mark.parametrize("text", [
        "customers have an id, name and email",
        "SELECT * FROM customers",
        "CREATE TABLE broken (id INT,, name",
    ])
    def test_non_ddl_input_raises(self, text):
        with pytest.raises(SchemaParseError):
            parse_ddl(text, "postgres")


class TestAnalyzeSchema:
    def test_valid_ddl_needs_no_llm(self):
        analyzed = analyze_schema(POSTGRES_DDL, "postgres", no_llm)
        assert analyzed.source == "ddl"
        assert [t.name for t in analyzed.parsed.tables] == ["customers", "orders"]
        assert analyzed.ddl == POSTGRES_DDL.strip()

    def test_plain_english_is_converted_by_the_llm(self):
        ddl = "CREATE TABLE books (id INT PRIMARY KEY, title TEXT, price DECIMAL(6, 2));"
        llm = FakeLLM([json.dumps({"ddl": ddl})])

        analyzed = analyze_schema("a books table with a title and a price", "postgres", lambda: llm)

        assert analyzed.source == "text"
        assert analyzed.ddl == ddl
        assert [t.name for t in analyzed.parsed.tables] == ["books"]

    def test_llm_is_told_the_dialect_and_given_the_users_text(self):
        llm = FakeLLM([json.dumps({"ddl": "CREATE TABLE t (id INT);"})])
        analyze_schema("a table t with an id", "tsql", lambda: llm)
        assert "SQL Server" in llm.calls[0]["system"]
        assert llm.calls[0]["user"] == "a table t with an id"
        assert llm.calls[0]["json_mode"] is True

    def test_a_pasted_problem_statement_is_handled_as_text(self):
        statement = (
            "Table: Employees\n+----+------+\n| id | name |\n+----+------+\n"
            "Write a query to find all employees named Sam."
        )
        llm = FakeLLM([json.dumps({"ddl": "CREATE TABLE Employees (id INT, name VARCHAR(50));"})])
        analyzed = analyze_schema(statement, "mysql", lambda: llm)
        assert analyzed.source == "text"
        assert analyzed.parsed.tables[0].name == "Employees"
        assert "Write a query" in llm.calls[0]["user"]

    def test_retries_once_when_the_llm_returns_invalid_ddl(self):
        llm = FakeLLM([
            json.dumps({"ddl": "CREATE TABLE broken (id INT,, name"}),
            json.dumps({"ddl": "CREATE TABLE fixed (id INT, name TEXT);"}),
        ])
        analyzed = analyze_schema("some table description", "postgres", lambda: llm)
        assert [t.name for t in analyzed.parsed.tables] == ["fixed"]
        assert "failed to parse" in llm.calls[1]["user"]

    def test_gives_up_after_two_invalid_attempts(self):
        bad = json.dumps({"ddl": "this is not sql"})
        llm = FakeLLM([bad, bad])
        with pytest.raises(SchemaParseError, match="couldn't turn that text"):
            analyze_schema("some table description", "postgres", lambda: llm)
        assert len(llm.calls) == 2

    def test_response_without_a_ddl_string_is_rejected(self):
        llm = FakeLLM([json.dumps({"tables": []}), json.dumps({"ddl": 5})])
        with pytest.raises(SchemaParseError):
            analyze_schema("some table description", "postgres", lambda: llm)

    def test_markdown_fenced_llm_json_is_accepted(self):
        fenced = '```json\n{"ddl": "CREATE TABLE t (id INT);"}\n```'
        analyzed = analyze_schema("a table t", "postgres", lambda: FakeLLM([fenced]))
        assert analyzed.parsed.tables[0].name == "t"


class TestKeyDetection:
    """Primary and foreign keys are reported so the UI can badge them."""

    def column(self, ddl, table, name, dialect="postgres"):
        schema = parse_ddl(ddl, dialect)
        return next(c for t in schema.tables if t.name == table for c in t.columns if c.name == name)

    def test_inline_primary_key(self):
        ddl = "CREATE TABLE emp (id INT PRIMARY KEY, name TEXT);"
        assert self.column(ddl, "emp", "id").primary_key is True
        assert self.column(ddl, "emp", "name").primary_key is False

    def test_inline_foreign_key_reports_its_target(self):
        ddl = "CREATE TABLE emp (id INT, dept_id INT REFERENCES dept(id));"
        assert self.column(ddl, "emp", "dept_id").foreign_key == "dept.id"
        assert self.column(ddl, "emp", "id").foreign_key is None

    def test_table_level_primary_and_foreign_keys(self):
        ddl = "CREATE TABLE emp (id INT, dept_id INT, PRIMARY KEY (id), FOREIGN KEY (dept_id) REFERENCES dept(id));"
        assert self.column(ddl, "emp", "id").primary_key is True
        assert self.column(ddl, "emp", "dept_id").foreign_key == "dept.id"

    def test_composite_primary_key_marks_every_column(self):
        ddl = "CREATE TABLE ol (order_id INT, line INT, qty INT, PRIMARY KEY (order_id, line));"
        assert self.column(ddl, "ol", "order_id").primary_key is True
        assert self.column(ddl, "ol", "line").primary_key is True
        assert self.column(ddl, "ol", "qty").primary_key is False

    def test_named_constraints(self):
        ddl = (
            "CREATE TABLE emp (id INT, dept_id INT, "
            "CONSTRAINT pk_emp PRIMARY KEY (id), "
            "CONSTRAINT fk_d FOREIGN KEY (dept_id) REFERENCES departments (department_id));"
        )
        assert self.column(ddl, "emp", "id").primary_key is True
        assert self.column(ddl, "emp", "dept_id").foreign_key == "departments.department_id"

    def test_mysql_auto_increment_primary_key(self):
        ddl = "CREATE TABLE `emp` (`id` INT AUTO_INCREMENT PRIMARY KEY, `d` INT, KEY (`d`));"
        assert self.column(ddl, "emp", "id", "mysql").primary_key is True

    def test_foreign_key_without_a_column_list_points_at_the_table(self):
        ddl = "CREATE TABLE emp (id INT, dept_id INT REFERENCES dept);"
        assert self.column(ddl, "emp", "dept_id").foreign_key == "dept"

    def test_a_schema_with_no_keys_reports_none(self):
        schema = parse_ddl("CREATE TABLE t (a INT, b TEXT);", "postgres")
        assert not any(c.primary_key or c.foreign_key for c in schema.tables[0].columns)

    def test_keys_survive_a_schema_update(self):
        from app.schema_parser import apply_schema_change

        current = "CREATE TABLE emp (id INT PRIMARY KEY, dept_id INT REFERENCES dept(id));"
        updated = apply_schema_change(current, "CREATE TABLE tags (id INT PRIMARY KEY);", "postgres", lambda: None)
        emp = next(t for t in updated.parsed.tables if t.name == "emp")
        assert emp.columns[0].primary_key is True
        assert emp.columns[1].foreign_key == "dept.id"
