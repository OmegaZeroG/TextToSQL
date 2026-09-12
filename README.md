# Text-to-SQL with Guardrails and Hallucination Detection

Translates natural-language questions into SQL against a real analytical
database, blocks anything destructive before it can execute, and scores
its own answers for correctness instead of presenting every result with
false confidence.

Built to be run and reviewed for **$0** — no paid API keys, no database
bill, no card required for any service in the stack.

## Why this exists

Text-to-SQL is one of the highest-value LLM applications in the enterprise,
and most demos stop at "it generates SQL." This project treats that as the
easy 80%. The other 20% — the part a compliance team actually cares about —
is:

- **Guardrails**: every generated query is statically checked (blocks DDL/DML,
  caps nesting depth, injects a row limit) and then executed against a
  read-only connection as a second line of defense.
- **Hallucination detection**: the SQL is back-translated into a plain-English
  question and compared against the original — divergence means the query
  probably doesn't answer what was asked, even if it runs without error.
- **Confidence scoring**: every response ships with a transparent breakdown
  (self-reported confidence, back-translation alignment, result sanity checks)
  instead of a single opaque number.

## Architecture

```
┌─────────────┐      question       ┌──────────────────┐
│  Streamlit  │ ──────────────────> │     FastAPI       │
│  frontend   │ <────────────────── │     backend       │
└─────────────┘   SQL + results +   └──────┬───────────┘
                    confidence              │
                                            │ 1. schema introspection
                                            │ 2. LLM generates SQL (Groq)
                                            │ 3. guardrail check
                                            │ 4. read-only execution
                                            │ 5. back-translation + sanity check
                                            ▼
                                    ┌──────────────────┐
                                    │  DuckDB (file)     │
                                    │  seeded e-commerce │
                                    │  dataset           │
                                    └──────────────────┘
```

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python 3.11) |
| LLM | Groq (Llama 3.3 70B) by default — pluggable OpenAI / Anthropic / Gemini |
| Database | DuckDB, seeded with a synthetic multi-table e-commerce dataset |
| Guardrails | `sqlparse` static analysis + read-only DB connection |
| Frontend | Streamlit |
| CI | GitHub Actions running the golden-query eval suite on every PR |
| Containerization | Docker + docker-compose |

## Local setup

```bash
git clone <your-repo-url>
cd TextToSQL
cp .env.example .env   # add your free Groq API key (https://console.groq.com)
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r backend/requirements.txt
python data/seed.py
uvicorn app.main:app --app-dir backend --reload
```

In a second terminal:

```bash
pip install -r frontend/requirements.txt
streamlit run frontend/streamlit_app.py
```

Or with Docker Compose (does both services in one shot):

```bash
docker-compose up --build
```

## Running the eval suite

```bash
python eval/run_eval.py --api-url http://localhost:8000
```

Checks execution-match accuracy on 10 hand-written golden queries, plus
that a disguised `DELETE` request is guardrail-blocked and that a genuinely
ambiguous question ("What is the revenue?") triggers a clarification
request instead of a guess.

## Deploying for free

**Backend → Render**
1. Push this repo to GitHub.
2. On [Render](https://render.com), New → Web Service → connect the repo.
3. Environment: Docker. Dockerfile path: `backend/Dockerfile`. Docker build context: repo root.
4. Add environment variables from `.env.example` (at minimum `LLM_PROVIDER=groq` and `GROQ_API_KEY`).
5. Free tier deploys, sleeps after 15 minutes idle, and wakes on the next request (~30s cold start).

**Frontend → Streamlit Community Cloud**
1. On [share.streamlit.io](https://share.streamlit.io), New app → point at this repo, main file `frontend/streamlit_app.py`.
2. In the app's Settings → Secrets, add `API_URL = "https://<your-render-service>.onrender.com"`.
3. Deploy — free, no sleep, no card.

**LLM → Groq**
Free API key at [console.groq.com](https://console.groq.com), no card required. Swap `LLM_PROVIDER`/`LLM_MODEL`/the matching `*_API_KEY` in `.env` to use OpenAI, Anthropic, or Gemini instead.

## Project layout

```
backend/app/
  main.py                 FastAPI routes
  config.py                Env-driven settings
  db.py                     Read-only DuckDB access
  schema_introspection.py   Extracts schema for the prompt, filters to relevant tables
  sql_generation.py         Prompt construction + LLM call
  guardrails.py             Static SQL safety checks
  validation.py             Back-translation + result sanity checks (hallucination detection)
  history.py                In-memory query history
  llm/                      Provider abstraction (Groq/OpenAI/Anthropic/Gemini)
data/seed.py                 Generates the synthetic e-commerce DuckDB dataset
eval/                          Golden dataset + eval runner
frontend/streamlit_app.py      UI
```
