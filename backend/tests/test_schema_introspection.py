from app.schema_introspection import filter_relevant_tables, format_schema_for_prompt


class TestFormatSchema:
    def test_lists_tables_columns_and_types(self, tables):
        text = format_schema_for_prompt(tables)
        assert "TABLE orders" in text
        assert "- order_date: DATE" in text

    def test_includes_foreign_keys(self, tables):
        text = format_schema_for_prompt(tables)
        assert "FOREIGN KEY customer_id -> customers.customer_id" in text

    def test_includes_sample_values_for_categorical_columns(self, tables):
        text = format_schema_for_prompt(tables)
        assert "'completed'" in text and "'processing'" in text

    def test_can_be_restricted_to_a_subset_of_tables(self, tables):
        text = format_schema_for_prompt(tables, {"customers"})
        assert "TABLE customers" in text
        assert "TABLE orders" not in text


class TestFilterRelevantTables:
    def test_matches_on_table_name(self, tables):
        assert "customers" in filter_relevant_tables("list all customers", tables)

    def test_matches_on_distinctive_column_name(self, tables):
        assert "orders" in filter_relevant_tables("what is the earliest order_date", tables)

    def test_pulls_in_tables_referenced_by_foreign_key(self, tables):
        relevant = filter_relevant_tables("show orders", tables)
        assert {"orders", "customers"} <= relevant

    def test_does_not_pull_in_unrelated_tables(self, tables):
        assert "categories" not in filter_relevant_tables("list all customers", tables)

    def test_falls_back_to_every_table_when_nothing_matches(self, tables):
        assert filter_relevant_tables("xyzzy plugh", tables) == {t.name for t in tables}
