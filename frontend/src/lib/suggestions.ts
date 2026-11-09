import type { SchemaTable } from "../types";

export const DEFAULT_EXAMPLES = [
  "Top 5 customers by total spend last month",
  "Second highest distinct salary from the Employee table",
  "Delete all inactive users",
];

const NUMERIC_TYPE = /int|dec|num|float|double|real|money|number/i;

/**
 * Example questions drawn from the user's own tables, so the chips are useful
 * for their schema instead of generic. Falls back to the defaults.
 */
export function suggestQuestions(tables: SchemaTable[] | undefined): string[] {
  if (!tables || tables.length === 0) return DEFAULT_EXAMPLES;

  const suggestions: string[] = [];
  const first = tables[0];
  suggestions.push(`How many rows are in ${first.name}?`);

  for (const table of tables) {
    const measure = table.columns.find((c) => !c.primary_key && !c.foreign_key && NUMERIC_TYPE.test(c.type));
    if (measure) {
      suggestions.push(`Top 5 ${table.name} by ${measure.name}`);
      break;
    }
  }

  for (const table of tables) {
    const link = table.columns.find((c) => c.foreign_key);
    if (link?.foreign_key) {
      const target = link.foreign_key.split(".")[0];
      suggestions.push(`List each ${table.name} with its ${target}`);
      break;
    }
  }

  if (suggestions.length < 3) suggestions.push(`Show the 10 most recent rows from ${first.name}`);
  return suggestions.slice(0, 3);
}
