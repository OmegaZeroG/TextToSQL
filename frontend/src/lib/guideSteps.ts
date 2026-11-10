export type Placement = "bottom" | "top" | "right" | "left";

export interface GuideStep {
  /** Matches a `data-guide` attribute in the page. No target means a centred card. */
  target: string | null;
  title: string;
  body: string;
  /** Where the card prefers to sit; it falls back if there is no room. */
  prefer?: Placement;
}

export const GUIDE_STEPS: GuideStep[] = [
  {
    target: "schema",
    title: "Add your schema",
    body: "Paste CREATE TABLE statements or describe your tables in plain English. It's optional, and it never leaves this browser.",
    prefer: "right",
  },
  {
    target: "question",
    title: "Ask in plain English",
    body: "Describe the result you want. Stuck? Tap an example below the box.",
  },
  {
    target: "dialect",
    title: "Pick your database",
    body: "The SQL is written for this dialect. A saved schema sets it for you.",
  },
  {
    target: "generate",
    title: "Generate",
    body: "Or press Ctrl + Enter. Nothing is ever run against your data.",
    prefer: "top",
  },
  {
    target: "result",
    title: "Check the confidence",
    body: "Every answer shows how far to trust it. Destructive statements are blocked, not handed over.",
  },
];
