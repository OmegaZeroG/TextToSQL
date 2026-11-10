import type { GenerateResponse, SavedSchema, SchemaTable } from "../types";

export function makeResponse(overrides: Partial<GenerateResponse> = {}): GenerateResponse {
  return {
    question: "How many customers are there?",
    dialect: "postgres",
    sql: "SELECT COUNT(*) FROM customers",
    explanation: "Counts customers.",
    tables_used: ["customers"],
    confidence: {
      syntax_valid: true,
      back_translation_alignment: 0.98,
      schema_check_passed: true,
      logic_check_passed: true,
      overall: 0.97,
    },
    warnings: [],
    guardrail_blocked: false,
    block_reason: null,
    schema_provided: true,
    assumed_schema: null,
    assumptions: [],
    ...overrides,
  };
}

export const CUSTOMERS_AND_ORDERS: SchemaTable[] = [
  {
    name: "customers",
    columns: [
      { name: "id", type: "INT", primary_key: true, foreign_key: null },
      { name: "name", type: "TEXT", primary_key: false, foreign_key: null },
    ],
  },
  {
    name: "orders",
    columns: [
      { name: "id", type: "INT", primary_key: true, foreign_key: null },
      { name: "customer_id", type: "INT", primary_key: false, foreign_key: "customers.id" },
      { name: "total", type: "DECIMAL(10, 2)", primary_key: false, foreign_key: null },
    ],
  },
];

export const CUSTOMERS_AND_ORDERS_DDL =
  "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);\n" +
  "CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT REFERENCES customers(id), total DECIMAL(10, 2));";

export function makeSchema(overrides: Partial<SavedSchema> = {}): SavedSchema {
  return {
    ddl: CUSTOMERS_AND_ORDERS_DDL,
    dialect: "postgres",
    tables: CUSTOMERS_AND_ORDERS,
    savedAt: 1700000000000,
    ...overrides,
  };
}
