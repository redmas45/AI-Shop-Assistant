# 🛍️ ShopBot — Voice AI Shopping Assistant

A production-ready voice-enabled AI shopping assistant for e-commerce websites.  
Customers speak naturally → the system understands intent → retrieves products → controls the website in real-time → responds with voice.

---

## Architecture

```
Customer Audio (WAV/WebM/MP3)
        │
        ▼
┌─────────────────────┐
│  1. Whisper STT     │  groq: whisper-large-v3-turbo
└──────────┬──────────┘
           │ transcript
           ▼
┌─────────────────────┐
│  2. Input Guardrail │  Injection detection, PII redaction, length check
└──────────┬──────────┘
           │ safe_text
           ▼
┌─────────────────────┐
│  3. RAG Retrieval   │  FAISS + sentence-transformers (384-dim)
│     (FAISS index)   │  Top-K=10 → re-ranked → Top-3 context
└──────────┬──────────┘
           │ product_context
           ▼
┌─────────────────────┐
│  4. LLM Agent       │  groq: llama-3.3-70b-versatile  (JSON mode)
│  System Prompt +    │  → {response_text, intent, ui_actions}
│  Few-shot examples  │
└──────────┬──────────┘
           │ structured_output
           ▼
┌─────────────────────┐
│  5. Output Guardrail│  Validates action types, product IDs, brand safety
└──────────┬──────────┘
           │ validated_output
           ▼
┌─────────────────────┐
│  6. Orpheus TTS     │  groq: canopylabs/orpheus-v1-english
└──────────┬──────────┘
           │ audio_bytes
           ▼
┌─────────────────────┐
│  7. API Response    │  {ui_actions, audio_b64, transcript, response_text}
└─────────────────────┘
```

---

## Tech Stack

| Layer       | Technology                              |
|-------------|------------------------------------------|
| STT         | `whisper-large-v3-turbo` via Groq        |
| LLM         | `llama-3.3-70b-versatile` via Groq       |
| TTS         | `canopylabs/orpheus-v1-english` via Groq |
| Embeddings  | `all-MiniLM-L6-v2` (384-dim)            |
| Vector DB   | FAISS (IndexFlatIP, cosine similarity)   |
| Database    | SQLite (WAL mode)                        |
| API         | FastAPI + Uvicorn                        |
| Frontend    | Vanilla HTML/CSS/JS                      |

---

## Project Structure

```
Shopping_Voice_Agent/
├── api/
│   ├── main.py          # FastAPI app, endpoints
│   ├── models.py        # Pydantic request/response schemas
│   └── middleware.py    # Request tracing, logging
├── agent/
│   ├── stt.py           # Groq Whisper STT
│   ├── tts.py           # Groq TTS
│   ├── llm.py           # Groq LLM with JSON mode
│   ├── rag.py           # FAISS retrieval engine
│   ├── prompt.py        # System prompt & few-shot examples
│   ├── guardrails.py    # Input/output safety checks
│   └── orchestrator.py  # End-to-end pipeline
├── db/
│   ├── schema.sql       # SQLite schema
│   ├── database.py      # Connection helpers
│   └── seed.py          # 50 sample Indian e-commerce products
├── frontend/
│   ├── index.html       # Voice shopping frontend
│   ├── index.css        # Styling
│   └── app.jsx          # React components
├── scripts/
│   ├── build_index.py   # Build/rebuild FAISS index
│   └── test_pipeline.py # CLI smoke tests
├── tests/
│   ├── test_guardrails.py
│   ├── test_rag.py
│   └── test_api.py
├── config.py            # Central configuration
├── run.py               # One-click startup script
├── requirements.txt
└── .env.example
```

---

## Quick Start

### 1. Clone & Install

```bash
cd Shopping_Voice_Agent

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
copy .env.example .env
```

Edit `.env` and set your Groq API key:

```env
GROQ_API_KEY=gsk_your_groq_api_key_here
```

Get a free Groq API key at: https://console.groq.com

### 3. Start the Application

```bash
python run.py
```

This will automatically:
- Check Python version and install missing dependencies
- Initialize the SQLite database and seed 50 sample products
- Build the FAISS vector index (if missing or stale)
- Start the FastAPI server via uvicorn
- Open the frontend in your default browser

*Note: For more options, run `python run.py --help`.*

---

## API Reference

### `POST /v1/shop` — Main Endpoint

**Request** (`multipart/form-data`):

| Field      | Type   | Required | Description                    |
|------------|--------|----------|--------------------------------|
| `audio`    | File   | Either/Or| Audio file (WAV, MP3, WebM)    |
| `text`     | String | Either/Or| Plain text input for testing   |
| `skip_tts` | Bool   | No       | Skip TTS synthesis (faster)    |

**Response** (`application/json`):

```json
{
  "transcript":    "Show me red shoes under 5000",
  "response_text": "Here are some great red shoes under ₹5,000!",
  "intent":        "product_search",
  "confidence":    0.97,
  "ui_actions": [
    {"action": "FILTER_PRODUCTS", "params": {"color": "red", "max_price": 5000}},
    {"action": "SHOW_PRODUCTS",   "params": {"product_ids": [1, 7]}}
  ],
  "audio_b64":  "UklGRiQA...",
  "latency_ms": {"stt_ms": 420, "rag_ms": 85, "llm_ms": 1200, "tts_ms": 380, "total_ms": 2090}
}
```

### UI Action Types

| Action              | Params                                                      |
|---------------------|-------------------------------------------------------------|
| `SHOW_PRODUCTS`     | `product_ids: [int]`                                        |
| `FILTER_PRODUCTS`   | `category, color, max_price, min_price, min_rating, brand`  |
| `SORT_PRODUCTS`     | `sort_by: "price_asc" \| "price_desc" \| "rating"`         |
| `NAVIGATE_TO`       | `page: "cart" \| "checkout" \| "category/shoes" \| ...`    |
| `ADD_TO_CART`       | `product_id: int`                                           |
| `SHOW_PRODUCT_DETAIL`| `product_id: int`                                          |
| `CLEAR_FILTERS`     | `{}`                                                        |

### `GET /v1/products` — Product Catalog

Returns all 50 active products. Use this to populate your frontend's product grid.

### `POST /v1/rebuild-index` — Admin

Rebuilds the FAISS vector index. Call after updating product data.

### `GET /health` — Health Check

Returns API status and model configuration.

---

## Testing

```bash
# Unit tests (no API key needed for guardrail + RAG tests)
pytest tests/test_guardrails.py -v

# RAG tests (needs DB + index)
pytest tests/test_rag.py -v

# API tests (uses TestClient, needs GROQ_API_KEY)
pytest tests/test_api.py -v

# Full test suite
pytest tests/ -v

# CLI smoke test (7 diverse queries)
python scripts/test_pipeline.py

# Single query test
python scripts/test_pipeline.py --text "Show me wireless earbuds under 3000"

# Test with audio file
python scripts/test_pipeline.py --audio path/to/audio.wav --with-tts
```

---

## Frontend Integration

The frontend team needs to:

1. Call `GET /v1/products` on page load to fetch the full product catalog.
2. Build a product map: `{ id → productData }`.
3. Call `POST /v1/shop` with customer audio.
4. Execute received `ui_actions` to update the UI:
   - `SHOW_PRODUCTS` → display specific product cards
   - `FILTER_PRODUCTS` → apply filters to the grid
   - `NAVIGATE_TO` → route to a page
   - etc.
5. Play `audio_b64` as WAV for the voice response.

---

## Environment Variables

| Variable         | Default                              | Description                   |
|------------------|--------------------------------------|-------------------------------|
| `GROQ_API_KEY`   | *(required)*                         | Groq API key                  |
| `STT_MODEL`      | `whisper-large-v3-turbo`             | Groq Whisper model            |
| `LLM_MODEL`      | `llama-3.3-70b-versatile`            | Groq LLM model                |
| `TTS_MODEL`      | `canopylabs/orpheus-v1-english`      | Groq TTS model                |
| `TTS_VOICE`      | `default`                            | TTS voice                     |
| `EMBEDDING_MODEL`| `sentence-transformers/all-MiniLM-L6-v2` | Embedding model           |
| `RAG_TOP_K`      | `10`                                 | FAISS candidates to fetch     |
| `RAG_TOP_N`      | `3`                                  | Products sent to LLM          |
| `LLM_TEMPERATURE`| `0.30`                               | LLM sampling temperature      |
| `PORT`           | `8000`                               | API server port               |
| `DB_PATH`        | `db/products.db`                     | SQLite database path          |

---

## Adding Products

1. Add product entries to `db/seed.py` → `PRODUCTS` list.
2. Re-run the seeder:
   ```bash
   python -m db.seed
   ```
3. Rebuild the FAISS index:
   ```bash
   python scripts/build_index.py
   # or call the admin endpoint:
   curl -X POST http://localhost:8000/v1/rebuild-index
   ```

---

## Safety Guardrails

### Input Protection
- Prompt injection detection (20+ regex patterns)
- PII redaction (phone numbers, emails, card numbers)
- Maximum transcript length enforcement
- Offensive content filtering

### Output Protection
- UI action type whitelist
- Product ID existence validation (prevents hallucinated products)
- Price/rating range validation
- Response length cap
- Brand safety (offensive content blocked)

---

## Groq Models Used

All three AI models are served by [Groq](https://console.groq.com) — the fastest LLM inference platform:

| Model                           | Use          | Speed      |
|---------------------------------|--------------|------------|
| `whisper-large-v3-turbo`        | STT          | ~0.2-0.5s  |
| `llama-3.3-70b-versatile`       | LLM Reasoning| ~0.5-2s    |
| `canopylabs/orpheus-v1-english` | TTS          | ~0.3-0.8s  |

Total pipeline latency: typically **2–4 seconds** end-to-end.
