# RAG-Enhanced AI Analysis — SEC Filing Deep Search

The AI Research Assistant can now search through vectorized SEC filing text (10-K, 10-Q, 8-K) using semantic similarity. Users trigger on-demand indexing per company from the AI Analysis tab, and the LLM autonomously decides when to search filings via tool-calling.

## How It Works

```
User clicks "Index Filings"
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  Indexing Pipeline (background task, ~3-5 min)           │
│                                                         │
│  For each filing (per-type limits: 3 10-K, 5 10-Q,     │
│  10 8-K — configurable via env vars):                   │
│    1. Fetch HTML from SEC EDGAR (follows redirects)     │
│    2. Parse into structured sections (Item 1A, 7, etc.) │
│    3. Extract tables as markdown (never split)          │
│    4. Chunk text by section (512 tokens, 50 overlap)    │
│    5. Extract topics per section (GPT-4o-mini)          │
│    6. Generate embeddings (text-embedding-3-small)      │
│    7. INSERT chunks + embeddings into filing_chunks     │
│                                                         │
│  Progress messages stream to UI via polling:            │
│    "Processing 10-K (2025-10-31) [1/18]"                │
│    "Generating embeddings for 115 chunks..."            │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  Chat with Filing Context (agentic tool-calling)        │
│                                                         │
│  User asks: "What risks does the 10-K mention?"         │
│    1. LLM sees search_filings tool in system prompt     │
│    2. LLM calls: search_filings(query="risk factors",   │
│       categories=["risk_factors"], filing_types=["10-K"])│
│    3. Backend: embed query → pgvector cosine search     │
│       → return top-k chunks within token budget         │
│    4. LLM receives filing excerpts with citations       │
│    5. LLM generates response referencing specific       │
│       filings, dates, and sections                      │
│    6. Frontend shows "Searching filings..." status,     │
│       then streams the response                         │
└─────────────────────────────────────────────────────────┘
```

## Architecture Decisions

This section documents the key design decisions, the problems they solve, and the alternatives considered. Written during initial implementation and local testing (Feb 2026).

### ADR-1: pgvector in existing Postgres (not a dedicated vector DB)

**Decision:** Use pgvector extension in our existing Supabase PostgreSQL instance.

**Context:** We needed vector similarity search for filing chunk embeddings. Dedicated vector databases (Pinecone, Weaviate, Qdrant) exist for this purpose.

**Why this approach:**
- Zero infrastructure cost — Supabase already has pgvector available (`CREATE EXTENSION vector`)
- Filing chunks co-locate with their metadata (ticker, filing_type, category, dates) in the same DB, enabling single-query filter + vector search
- HNSW index gives sub-second approximate nearest neighbor search at our scale (~300 chunks per company)
- One fewer service to manage, monitor, and pay for
- Transactional consistency — chunk inserts and status updates share the same DB transaction

**Trade-off:** pgvector is slower than purpose-built vector DBs at millions of vectors. Acceptable here because we index per-company on demand (~300-400 vectors per company, not millions).

### ADR-2: On-demand indexing (not batch)

**Decision:** Users trigger indexing per-company from the AI Analysis tab. We don't batch-process all 2000+ screener stocks.

**Why:**
- Most users research a handful of companies — pre-indexing 2000 stocks wastes ~$60 in OpenAI API costs and millions of DB rows
- Filing content changes quarterly — stale batch indexes give false confidence
- On-demand means the user sees exactly what's indexed and when
- ~3-5 min per company is acceptable as a one-time cost when you're about to deep-dive a stock

**Alternative considered:** Nightly batch job for watchlist companies. Deferred — adds scheduler complexity and may not be needed.

### ADR-3: Section-aware chunking with table preservation

**Decision:** Chunks never cross section boundaries, and HTML tables are never split.

**Why section boundaries matter:** Each chunk gets embedded as a 1536-dimensional vector representing its semantic meaning. If a chunk mixed "supply chain risk" text with "executive compensation" text, the embedding would land somewhere between those topics in vector space — not close enough to either to be a strong match. Keeping chunks within a single section produces focused embeddings that retrieve precisely.

**Why tables are never split:** A financial table split mid-row loses its meaning entirely — "Revenue: $391B" separated from its column header becomes meaningless numbers. Tables are converted to markdown via `markdownify` and kept as whole chunks regardless of token count.

**Fallback:** 10-Q filings often have non-standard HTML structure. When the parser detects fewer than 2 sections, it falls back to treating the entire document as one section with `category='general'`. Partial indexing is better than failure. (Apple's 10-Qs consistently fall back; their 10-Ks parse into 12 sections.)

### ADR-4: Two-tier metadata (category + topics)

**Decision:** Each chunk has a `category` (controlled vocabulary, ~10 values) and `topics` (free-form LLM-extracted phrases).

**Why two tiers:**
- `category` enables reliable SQL WHERE filtering — the LLM can confidently filter to `risk_factors` or `financial_discussion` because the values are constrained enums
- `topics` capture nuance within a section — "china supply chain risk" vs. "cybersecurity risk" are both `risk_factors` but have different topics
- Categories are derived deterministically from section headers (Item 1A → `risk_factors`), so they're free
- Topics cost one GPT-4o-mini call per section (~$0.001 each), extracted once during indexing

### ADR-5: Custom pgvector codec for asyncpg

**Decision:** Register a custom vector type codec with asyncpg on every database connection, rather than using SQL CAST or string formatting.

**Problem:** asyncpg (the PostgreSQL driver) introspects parameter types by sending a "Describe" message to PostgreSQL before executing queries. When it encounters pgvector's `vector` column type, it doesn't know how to serialize Python data to/from that type — it has built-in codecs for standard types (`int`, `text`, `text[]`, etc.) but not for extensions.

**What we tried first:**
1. `::vector` cast in SQL — SQLAlchemy's `text()` parser interprets `:vector` as a named bind parameter, breaking the query
2. `CAST(:embedding AS vector)` — PostgreSQL resolves the parameter type as `vector` (the cast target), and asyncpg still doesn't know how to serialize a Python list as a vector
3. Formatting the embedding as a PostgreSQL literal string `{"topic1","topic2"}` for `text[]` — asyncpg sees the column is `text[]` and expects a Python iterable, rejecting our string

**Solution:** Register a codec in `database.py` that teaches asyncpg how to convert between Python lists and pgvector's text wire format:

```python
# database.py — on every new connection
async def _register_vector_codec(conn):
    await conn.set_type_codec(
        "vector",
        encoder=lambda v: v if isinstance(v, str)
                else "[" + ",".join(str(float(x)) for x in v) + "]",
        decoder=lambda v: [float(x) for x in v[1:-1].split(",")]
                if v else [],
        format="text",
        schema="public",
    )

@event.listens_for(engine.sync_engine, "connect")
def _on_connect(dbapi_connection, connection_record):
    dbapi_connection.run_async(_register_vector_codec)
```

With this codec, we pass native Python types directly — `list[str]` for `text[]` topics, `list[float]` for `vector` embeddings — and asyncpg handles serialization transparently. No CAST, no string formatting, no SQL injection risk.

### ADR-6: In-memory progress tracking (not DB or WebSocket)

**Decision:** Store indexing progress messages in a Python dict (`_indexing_progress`), polled by the status endpoint every 4 seconds.

**Why not a DB column:** Progress messages change every few seconds during indexing. Writing each one to the DB means an UPDATE + COMMIT per message — wasteful for ephemeral data that's only relevant while the background task is running.

**Why not WebSocket/SSE:** The indexing trigger is a fire-and-forget POST. Adding WebSocket infrastructure for a 90-second process used occasionally is over-engineering. TanStack Query already polls; we just added a field to the response.

**Trade-off:** Progress messages are lost on server restart. Acceptable — if the server restarts during indexing, the status is stuck at `indexing` and the user retries anyway.

### ADR-7: Pre-writing indexing status to prevent race condition

**Decision:** The POST `/index` endpoint writes `status='indexing'` to the DB before starting the background task.

**Problem discovered during testing:** FastAPI's `BackgroundTasks` runs the indexing job after the response is sent. The frontend's optimistic update sets status to `indexing`, but `invalidateQueries` triggers an immediate refetch. That refetch hits the DB before the background task has written its first status row — returning `not_indexed`, which overwrites the optimistic update and stops polling. The user sees the banner revert to "not indexed" while indexing silently runs in the background.

**Fix (two-part):**
1. Backend: POST handler upserts `status='indexing'` synchronously before `add_task()`, so the first poll always finds `indexing`
2. Frontend: Removed `invalidateQueries` from `triggerIndexing()` — the optimistic update starts polling, and the 4-second interval picks up real status naturally

### ADR-8: Agentic tool-calling (not pre-fetched context)

**Decision:** The LLM decides when and what to search via tool-calling, rather than pre-stuffing filing context into every prompt.

**Why:**
- Not every question needs filing context — "What's the P/E ratio?" uses structured data, not filing text
- Pre-stuffing wastes tokens (and money) on irrelevant filing excerpts
- The LLM can make targeted searches — "supply chain risks in the 10-K" is a better search than dumping the entire risk factors section
- Multiple search rounds (up to 3) let the LLM drill deeper if the first search isn't sufficient

### ADR-9: Per-type filing limits (not uniform)

**Decision:** Each filing type has its own configurable limit: 3 for 10-K, 5 for 10-Q, 10 for 8-K.

**Why different limits per type:**
- **10-K (3):** Annual reports cover an entire fiscal year with 3-year comparative data. 3 filings = ~5 years of coverage. They're large documents (~1-2MB HTML, ~100+ chunks each), so indexing more adds significant cost for diminishing returns.
- **10-Q (5):** Quarterly reports cover a single quarter. 5 filings = ~15 months of quarterly data, which captures the most recent trends and seasonal patterns. They're mid-sized and cheaper to index.
- **8-K (10):** Current reports disclose material events — acquisitions, leadership changes, earnings releases, cybersecurity incidents. They're typically small (1-2 pages, ~5 chunks each) so 10 is cheap to index and captures recent material events that wouldn't appear in the older 10-K/10-Q filings.

**Why not a date-based cutoff:** "All filings in the last 3 years" would index a variable number of filings depending on the company's event frequency. A fixed count is simpler, predictable, and easier to reason about cost.

**Configuration:** All limits are overridable via environment variables: `FILING_INDEX_MAX_10K`, `FILING_INDEX_MAX_10Q`, `FILING_INDEX_MAX_8K`.

## Architecture

### Database Tables

**`filing_index_status`** — Tracks indexing state per company.

| Column | Type | Purpose |
|--------|------|---------|
| `ticker` | VARCHAR(10) UNIQUE | Company identifier |
| `status` | VARCHAR(20) | `pending`, `indexing`, `ready`, `error` |
| `filings_indexed` | INT | Number of filings successfully processed |
| `chunks_total` | INT | Total chunks in the index |
| `last_indexed_at` | TIMESTAMPTZ | When indexing last completed |
| `last_filing_date` | DATE | Most recent filing date in the index |
| `error_message` | TEXT | Error details if status is `error` |

**`filing_chunks`** — Vectorized filing text with metadata.

| Column | Type | Purpose |
|--------|------|---------|
| `ticker` | VARCHAR(10) | Company (always filtered in queries) |
| `filing_type` | VARCHAR(20) | `10-K`, `10-Q`, or `8-K` |
| `filing_date` | DATE | When the filing was submitted |
| `section_name` | VARCHAR(100) | e.g., "Item 1A - Risk Factors" |
| `category` | VARCHAR(50) | Controlled vocabulary (see below) |
| `topics` | TEXT[] | Free-form phrases from GPT-4o-mini |
| `chunk_text` | TEXT | The actual text content |
| `token_count` | INT | Token count (cl100k_base encoding) |
| `is_table` | BOOLEAN | Whether this chunk is a markdown table |
| `embedding` | vector(1536) | text-embedding-3-small vector |

**Indexes:**
- `idx_fc_ticker` — All queries filter by ticker
- `idx_fc_ticker_type` — Filing type filter
- `idx_fc_category` — Category filter
- `idx_fc_filing_date` — Date range queries
- `idx_fc_embedding` — HNSW index for cosine similarity (`m=16, ef_construction=64`)

### Section Categories

Two-tier metadata system: `category` is a controlled vocabulary for reliable filtering, `topics` are free-form LLM-extracted phrases for nuance.

**Categories by filing type:**

| Category | 10-K Items | 10-Q Items | 8-K Items |
|----------|-----------|-----------|----------|
| `business_overview` | 1, 2 | — | — |
| `risk_factors` | 1A, 1C, 7A | Part II 1A, Part I 3 | 1.05 |
| `financial_discussion` | 7 | Part I 2 | 2.02 |
| `financial_statements` | 8 | Part I 1 | — |
| `legal` | 3 | Part II 1 | — |
| `regulatory` | 9, 9A, 9B | Part I 4, Part II 6 | 9.01 |
| `market_info` | 5 | Part II 2 | — |
| `events_transactions` | — | — | 1.01, 2.01, 2.05 |
| `corporate_governance` | — | — | 5.02, 5.03 |
| `guidance_outlook` | — | — | 7.01, 8.01 |

### Backend Services

```
backend/app/
├── models/
│   └── database.py            # Registers pgvector codec with asyncpg on connect
├── services/
│   ├── filing_fetcher.py      # Fetch HTML from SEC EDGAR (rate-limited, follows redirects)
│   ├── filing_parser.py       # Parse HTML → structured sections
│   ├── filing_chunker.py      # Section-aware chunking with table handling
│   ├── embedding_service.py   # OpenAI text-embedding-3-small (batch + single)
│   ├── filing_topics.py       # GPT-4o-mini topic extraction per section
│   ├── vector_search.py       # pgvector cosine similarity + metadata filters
│   ├── filing_indexer.py      # Orchestrates pipeline + in-memory progress tracking
│   ├── ai_service.py          # Added stream_chat_response_with_tools()
│   ├── ai_prompts.py          # Added filing tool addendum to system prompt
│   └── ai_context.py          # Added get_filing_index_info() helper
└── api/
    ├── indexing.py             # POST/GET/DELETE — pre-writes status, serves progress
    └── ai.py                   # Chat endpoint with agentic tool-calling
```

### Frontend Components

```
frontend/src/
├── lib/
│   ├── types.ts               # FilingIndexStatus (progress_message, filing_type_breakdown), ChatMessage
│   └── api.ts                 # triggerFilingIndex, getFilingIndexStatus, deleteFilingIndex
├── hooks/
│   ├── useFilingIndex.ts      # TanStack Query, 4s polling, optimistic updates (no invalidate)
│   └── useAIChat.ts           # Handles 'status' SSE events from tool calls
└── components/research/
    └── AIAnalysisTab.tsx       # Filing index banner with animated progress + tool-call status
```

## API Endpoints

### Filing Indexing

```
POST   /api/ai/filings/{ticker}/index    Trigger indexing (writes status, runs in background)
GET    /api/ai/filings/{ticker}/status   Get status + live progress message during indexing
DELETE /api/ai/filings/{ticker}/index    Delete all chunks and reset
```

All endpoints require authentication. POST returns 503 if `OPENAI_API_KEY` is not set.

**POST response:**
```json
{
  "message": "Indexing started for AAPL",
  "ticker": "AAPL"
}
```

**GET response (while indexing — includes live progress):**
```json
{
  "ticker": "AAPL",
  "status": "indexing",
  "filings_indexed": 2,
  "chunks_total": 145,
  "progress_message": "Generating embeddings for 115 chunks...",
  "last_indexed_at": null,
  "last_filing_date": null,
  "error_message": null
}
```

**GET response (ready — includes filing type breakdown):**
```json
{
  "ticker": "AAPL",
  "status": "ready",
  "filings_indexed": 18,
  "chunks_total": 850,
  "last_indexed_at": "2026-02-28T16:25:40Z",
  "last_filing_date": "2026-01-30",
  "error_message": null,
  "filing_type_breakdown": {"10-K": 3, "10-Q": 5, "8-K": 10}
}
```

The `filing_type_breakdown` field maps each filing type to the number of distinct filings indexed. The frontend banner renders this as "3 10-K, 5 10-Q, 10 8-K, 850 chunks indexed".

### Chat (modified)

`POST /api/ai/chat` — When the ticker has indexed filings, the response SSE stream now includes an additional event type:

```
data: {"status": "Searching filings: risk factors..."}    ← tool-call in progress
data: {"token": "Based on the 10-K filing..."}            ← content tokens
data: {"done": true}                                       ← end of response
```

The `status` event appears while the LLM is executing a `search_filings` tool call. Once filing excerpts are retrieved and the LLM starts generating content, status events stop and token events begin.

## Configuration

All settings are in `backend/app/config.py` and can be overridden via environment variables:

| Setting | Default | Purpose |
|---------|---------|---------|
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions |
| `CHUNK_MAX_TOKENS` | `512` | Max tokens per text chunk |
| `CHUNK_OVERLAP_TOKENS` | `50` | Overlap between consecutive chunks |
| `RAG_MAX_CONTEXT_TOKENS` | `8000` | Max filing context tokens per tool call |
| `RAG_MAX_TOOL_ITERATIONS` | `3` | Max tool-call rounds per chat turn |
| `TOPIC_EXTRACTION_MODEL` | `gpt-4o-mini` | Model for topic extraction |
| `FILING_INDEX_MAX_10K` | `3` | Most recent N annual filings (10-K) to index |
| `FILING_INDEX_MAX_10Q` | `5` | Most recent N quarterly filings (10-Q) to index |
| `FILING_INDEX_MAX_8K` | `10` | Most recent N current reports (8-K) to index |

## Chunking Rules

1. **Tables are never split** — Each HTML `<table>` becomes its own chunk regardless of token count. Tables are converted to markdown via `markdownify` to preserve spatial structure.

2. **Text never crosses section boundaries** — A chunk from Item 1A (Risk Factors) will never contain text from Item 7 (MD&A). This keeps embeddings semantically focused (see ADR-3).

3. **Token counting uses tiktoken** — `cl100k_base` encoding, which matches the `text-embedding-3-small` model's tokenizer.

4. **Overlap for text chunks** — Consecutive text chunks within a section overlap by 50 tokens to avoid losing context at boundaries.

5. **Fallback for unparseable filings** — If section detection finds fewer than 2 sections, the entire document becomes one section with `category='general'`. This handles unusual filing formats gracefully (Apple 10-Qs consistently use fallback).

## Vector Search

Search uses pgvector's cosine distance operator (`<=>`) with an HNSW index for approximate nearest neighbor lookup. The registered pgvector codec (see ADR-5) handles Python list → vector serialization, so no explicit `::vector` cast is needed:

```sql
SELECT chunk_text, filing_type, filing_date::text, section_name,
       category, topics, is_table, token_count,
       1 - (embedding <=> :query_embedding) AS similarity
FROM filing_chunks
WHERE ticker = :ticker
  AND filing_type = ANY(:filing_types)    -- optional
  AND category = ANY(:categories)         -- optional
  AND filing_date >= :min_date            -- optional
ORDER BY embedding <=> :query_embedding
LIMIT :fetch_limit
```

Results are accumulated within a token budget (`rag_max_context_tokens`, default 8000). The search fetches `top_k * 2` candidates to allow budget trimming while still returning the most relevant results.

## Agentic Tool-Calling

When filings are indexed, the chat endpoint switches from simple streaming to an agentic loop:

1. The system prompt includes a `FILING_TOOL_ADDENDUM` that tells the LLM about the `search_filings` tool and when to use it.
2. The OpenAI API is called with `tools=[FILING_SEARCH_TOOL]`.
3. If the model responds with `finish_reason="tool_calls"`, the backend:
   - Yields a `status` SSE event to the frontend
   - Executes the tool call (embedding + pgvector search)
   - Appends the formatted results as a `tool` message
   - Loops back for another OpenAI call (up to `rag_max_tool_iterations`)
4. When the model responds with content (no tool calls), tokens are streamed normally.

The tool definition includes category enums so the LLM can filter searches effectively:

```python
"categories": {
    "type": "array",
    "items": {
        "type": "string",
        "enum": [
            "risk_factors", "financial_discussion", "business_overview",
            "financial_statements", "legal", "regulatory", "market_info",
            "events_transactions", "corporate_governance", "guidance_outlook",
        ],
    },
}
```

## Cost Estimates

For a typical company with 18 filings (3x 10-K + 5x 10-Q + 10x 8-K):

| Component | Cost | Notes |
|-----------|------|-------|
| Embedding (indexing) | ~$0.02 | ~800 chunks x 512 tokens at $0.02/1M tokens |
| Topic extraction | ~$0.05 | ~50 sections x GPT-4o-mini |
| Embedding (query) | ~$0.00001 | Single query embedding per search |
| Tool call (per chat) | $0 extra | Uses same GPT-4.1 call already happening |
| **Total per company** | **~$0.07** | One-time indexing cost |

8-K filings are typically small (1-2 pages) so they add minimal cost relative to 10-K/10-Q filings. The bulk of the embedding cost comes from 10-K annual reports.

## Setup

### Prerequisites

- pgvector extension available in PostgreSQL (Supabase has it; local dev uses `pgvector/pgvector:pg16` Docker image)
- `OPENAI_API_KEY` environment variable set

### Local Development

1. Rebuild Docker Postgres to get the pgvector image:
   ```bash
   docker compose down -v && docker compose up -d
   ```

2. The schema auto-initializes from `schema.sql` (includes `CREATE EXTENSION IF NOT EXISTS vector` and both new tables).

3. Start the backend and frontend normally (`bash scripts/dev.sh`).

### Production (Supabase)

Run the following SQL in the Supabase SQL editor:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Then run the filing_index_status and filing_chunks table creation
-- from the bottom of backend/schema.sql
```

## Debugging

### Check indexed chunks

```sql
SELECT filing_type, COUNT(*), AVG(token_count)::int as avg_tokens
FROM filing_chunks
WHERE ticker = 'AAPL'
GROUP BY filing_type;
```

### Check section distribution

```sql
SELECT category, COUNT(*), SUM(token_count) as total_tokens
FROM filing_chunks
WHERE ticker = 'AAPL'
GROUP BY category
ORDER BY total_tokens DESC;
```

### Test vector search directly

```sql
-- Find chunks most similar to a query (requires embedding the query first)
SELECT section_name, category, LEFT(chunk_text, 100),
       1 - (embedding <=> '<query_vector>') AS similarity
FROM filing_chunks
WHERE ticker = 'AAPL'
ORDER BY embedding <=> '<query_vector>'
LIMIT 5;
```

### Check indexing status

```sql
SELECT * FROM filing_index_status WHERE ticker = 'AAPL';
```

### Reset stuck indexing

If the server crashes during indexing, the status stays at `indexing`. Reset it:

```bash
# Via API
curl -X DELETE http://localhost:8000/api/ai/filings/AAPL/index

# Or direct SQL
UPDATE filing_index_status SET status = 'error', error_message = 'Reset manually' WHERE ticker = 'AAPL';
```

### Backend logs

The indexing pipeline logs progress at each stage:
```
INFO: [AAPL] Starting filing indexing pipeline
INFO: [AAPL] Found 18 filings to index
INFO: [AAPL] Processing 10-K (2025-10-31) [1/18]
INFO: Fetched https://www.sec.gov/... in 1.0s (1,520,208 bytes)
INFO: Parsed 10-K: 12 sections detected (item_1, item_1a, item_1c, ...)
INFO: Chunked 10-K into 115 chunks (43 tables, 72 text, avg 490 tokens, quality=sectioned)
INFO: Generated 115 embeddings in 1.4s (55,073 tokens, model=text-embedding-3-small)
INFO: [AAPL] Indexed 10-K (2025-10-31): 115 chunks, 12 sections
...
INFO: [AAPL] Processing 8-K (2026-01-30) [12/18]
INFO: Fetched https://www.sec.gov/... in 0.4s (12,340 bytes)
INFO: Parsed 8-K: 2 sections detected (item_2.02, item_9.01)
INFO: Chunked 8-K into 5 chunks (1 tables, 4 text, avg 210 tokens, quality=sectioned)
...
INFO: [AAPL] Indexing complete: 18 filings, ~850 chunks in ~240s
```

Tool calls during chat are also logged:
```
INFO: Tool call: search_filings({'query': 'china supply chain risk', 'categories': ['risk_factors']})
INFO: Filing search for 'china supply chain risk' on AAPL: 6 results (3420 tokens, top similarity=0.847)
```

## Bugs Found During Testing

Documented here for future reference — these patterns may recur with similar stacks.

**SEC EDGAR 301 redirects:** EDGAR moved filing URLs, removing leading zeros from CIK numbers (e.g., `0000320193` → `320193`). Fix: `follow_redirects=True` in httpx client.

**Python import binding:** `from app.models.database import async_session_factory` captures `None` at import time (before `init_db()` runs). Fix: `from app.models import database as _db` then access `_db.async_session_factory` at call time.

**asyncpg type introspection:** asyncpg asks PostgreSQL for parameter types before executing queries. Both `CAST(:param AS type)` and `:param::type` cause asyncpg to expect native Python types matching the target type. For `text[]` it wants a list, for `vector` it wants... nothing (unknown type). Fix: register codecs and pass native Python types (see ADR-5).

**Date type mismatch:** `filing_date` from the database comes back as a `datetime.date` object, not a string. Calling `date.fromisoformat()` on a date object fails. Fix: `isinstance(raw_date, date)` check before conversion.

**Polling race condition:** Frontend optimistic update + immediate `invalidateQueries` creates a race where the refetch returns stale data before the background task starts. Fix: pre-write status in POST handler + remove invalidateQueries (see ADR-7).
