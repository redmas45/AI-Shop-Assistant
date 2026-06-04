"""
RAG (Retrieval-Augmented Generation) engine.
Uses FAISS for vector similarity search and sentence-transformers for embeddings.
Index is built from the SQLite product catalog and persisted to disk.
"""
import json
import logging
import re
import threading
from pathlib import Path
from typing import Optional

import numpy as np

import config
from db.database import get_all_products, get_products_by_ids

logger = logging.getLogger(__name__)

# ── Lazy globals (loaded once) ────────────────────────────────────────────────
_lock = threading.Lock()
_embedder = None
_index = None
_product_ids: list[int] = []


# ── Embedder ──────────────────────────────────────────────────────────────────

def _get_embedder():
    """Lazy-load the sentence-transformer model (thread-safe)."""
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                from sentence_transformers import SentenceTransformer
                logger.info("RAG | Loading embedding model: %s", config.EMBEDDING_MODEL)
                _embedder = SentenceTransformer(config.EMBEDDING_MODEL)
                logger.info("RAG | Embedding model loaded.")
    return _embedder


def _embed(texts: list[str]) -> np.ndarray:
    """Embed a list of texts into unit-normalized vectors (for cosine sim)."""
    embedder = _get_embedder()
    vecs = embedder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return vecs.astype(np.float32)


# ── Price constraint extraction ───────────────────────────────────────────────

def extract_price_constraints(query: str) -> dict:
    """
    Parse price constraints from a user's natural language query.

    Returns a dict with optional keys:
        max_price (float): Upper price limit  ("under 300", "below 500", "less than 1000")
        min_price (float): Lower price limit  ("above 200", "over 500", "more than 100")

    Examples:
        "food under 300 rupees"        → {"max_price": 300.0}
        "shoes between 500 and 2000"   → {"min_price": 500.0, "max_price": 2000.0}
        "show me laptops above 50000"  → {"min_price": 50000.0}
        "I only have 300 rupees"       → {"max_price": 300.0}
    """
    constraints = {}
    q = query.lower().strip()

    # Pattern: "between X and Y" / "from X to Y"
    between_pat = re.compile(
        r'(?:between|from)\s+(?:₹|rs\.?|rupees?)?\s*(\d+(?:[.,]\d+)?)'
        r'\s*(?:and|to|-)\s*'
        r'(?:₹|rs\.?|rupees?)?\s*(\d+(?:[.,]\d+)?)',
        re.IGNORECASE,
    )
    m = between_pat.search(q)
    if m:
        lo = float(m.group(1).replace(",", ""))
        hi = float(m.group(2).replace(",", ""))
        constraints["min_price"] = min(lo, hi)
        constraints["max_price"] = max(lo, hi)
        logger.info("RAG | Price constraint (between): %s", constraints)
        return constraints

    # Pattern: "under / below / less than / within / upto / at most / max / cheaper than X"
    max_pat = re.compile(
        r'(?:under|below|less\s+than|within|upto|up\s+to|at\s+most|max|maximum|cheaper\s+than|not\s+(?:more|above)\s+(?:than)?)'
        r'\s*(?:₹|rs\.?|rupees?)?\s*(\d+(?:[.,]\d+)?)',
        re.IGNORECASE,
    )
    m = max_pat.search(q)
    if m:
        constraints["max_price"] = float(m.group(1).replace(",", ""))

    # Pattern: "above / over / more than / at least / min / starting from / costlier than X"
    min_pat = re.compile(
        r'(?:above|over|more\s+than|at\s+least|min|minimum|starting\s+from|costlier\s+than|not\s+(?:less|below|under)\s+(?:than)?)'
        r'\s*(?:₹|rs\.?|rupees?)?\s*(\d+(?:[.,]\d+)?)',
        re.IGNORECASE,
    )
    m = min_pat.search(q)
    if m:
        constraints["min_price"] = float(m.group(1).replace(",", ""))

    # Pattern: "I (only) have X rupees" / "my budget is X" / "budget X"
    budget_pat = re.compile(
        r'(?:i\s+(?:only\s+)?have|(?:my\s+)?budget\s+(?:is)?)\s*(?:₹|rs\.?|rupees?)?\s*(\d+(?:[.,]\d+)?)',
        re.IGNORECASE,
    )
    m = budget_pat.search(q)
    if m and "max_price" not in constraints:
        constraints["max_price"] = float(m.group(1).replace(",", ""))

    # Pattern: standalone "X rupees" with implicit budget context (only if no other constraint found)
    if not constraints:
        rupee_pat = re.compile(
            r'(?:₹|rs\.?)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:₹|rs\.?|rupees?)',
            re.IGNORECASE,
        )
        m = rupee_pat.search(q)
        if m:
            val = float((m.group(1) or m.group(2)).replace(",", ""))
            # If the query tone suggests a budget/limit, treat as max_price
            if any(word in q for word in ["only", "just", "budget", "afford", "cheap", "save"]):
                constraints["max_price"] = val

    if constraints:
        logger.info("RAG | Price constraints extracted: %s from query: %r", constraints, query[:80])
    return constraints


# ── Index management ──────────────────────────────────────────────────────────

def build_index() -> None:
    """
    Build a FAISS index from all active products in the database.
    Persists the index and product-ID mapping to disk.
    Called by scripts/build_index.py and automatically on first query if index missing.
    """
    import faiss

    logger.info("RAG | Building FAISS index from product catalog…")
    products = get_all_products()

    if not products:
        logger.warning("RAG | No products found. Seeding database first…")
        from db.seed import seed
        seed()
        products = get_all_products()

    # Build text corpus for each product
    corpus = [_product_to_text(p) for p in products]
    ids    = [p["id"] for p in products]

    vecs = _embed(corpus)
    dim  = vecs.shape[1]

    index = faiss.IndexFlatIP(dim)   # Inner product on normalised vectors = cosine similarity
    index.add(vecs)

    # Persist
    config.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(config.INDEX_PATH))
    config.INDEX_IDS_PATH.write_text(json.dumps(ids), encoding="utf-8")

    logger.info("RAG | Index built: %d products, dim=%d", len(ids), dim)


def _load_index():
    """Load persisted FAISS index from disk (thread-safe)."""
    global _index, _product_ids
    if _index is not None:
        return

    with _lock:
        if _index is not None:
            return
        import faiss

        if not config.INDEX_PATH.exists() or not config.INDEX_IDS_PATH.exists():
            logger.info("RAG | Index not found — building now…")
            build_index()

        _index = faiss.read_index(str(config.INDEX_PATH))
        _product_ids = json.loads(config.INDEX_IDS_PATH.read_text(encoding="utf-8"))
        logger.info("RAG | Index loaded: %d vectors", _index.ntotal)


def preload() -> None:
    """Preload the embedding model and FAISS index into memory (e.g., at startup)."""
    logger.info("RAG | Preloading models and index...")
    _get_embedder()
    _load_index()
    logger.info("RAG | Preload complete.")


# ── Price filtering ───────────────────────────────────────────────────────────

def _apply_price_filter(products: list[dict], constraints: dict) -> list[dict]:
    """
    Filter a list of product dicts by extracted price constraints.
    Returns only products whose price falls within the specified range.
    """
    if not constraints:
        return products

    max_price = constraints.get("max_price")
    min_price = constraints.get("min_price")
    filtered = []

    for p in products:
        price = p.get("price", 0)
        if max_price is not None and price > max_price:
            continue
        if min_price is not None and price < min_price:
            continue
        filtered.append(p)

    logger.info(
        "RAG | Price filter: %d → %d products (constraints=%s)",
        len(products), len(filtered), constraints,
    )
    return filtered


# ── Retrieval ─────────────────────────────────────────────────────────────────

def retrieve(
    query: str,
    top_k: Optional[int] = None,
    top_n: Optional[int] = None,
    price_constraints: Optional[dict] = None,
) -> list[dict]:
    """
    Retrieve the most relevant products for a user query.

    Args:
        query:              User's natural language query.
        top_k:              Number of candidates to fetch from FAISS (default: config.RAG_TOP_K).
        top_n:              Final number of products to return after re-ranking (default: config.RAG_TOP_N).
        price_constraints:  Optional dict with 'max_price' and/or 'min_price' keys.
                            If not provided, constraints are auto-extracted from the query.

    Returns:
        List of product dicts (top_n most relevant), filtered by price if applicable.
    """
    _load_index()

    k = top_k or config.RAG_TOP_K
    n = top_n or config.RAG_TOP_N

    # Auto-extract price constraints from query if not explicitly provided
    if price_constraints is None:
        price_constraints = extract_price_constraints(query)

    # When we have price constraints, fetch more candidates from FAISS to compensate
    # for products that will be filtered out by price.
    search_k = k * 3 if price_constraints else k

    query_vec = _embed([query])                              # shape: (1, dim)
    scores, indices = _index.search(query_vec, search_k)     # both shape: (1, search_k)

    candidate_ids: list[int] = []
    score_map: dict[int, float] = {}

    for idx, score in zip(indices[0], scores[0]):
        if idx < 0 or idx >= len(_product_ids):
            continue
            
        # Ignore weak semantic matches (cosine similarity < 0.3)
        if float(score) < 0.3:
            continue
            
        pid = _product_ids[idx]
        candidate_ids.append(pid)
        score_map[pid] = float(score)

    if not candidate_ids:
        logger.warning("RAG | No candidates found for query: %r", query)
        return []

    # Fetch product details from DB
    products = get_products_by_ids(candidate_ids[:search_k])

    # Attach semantic scores
    for p in products:
        p["_semantic_score"] = score_map.get(p["id"], 0.0)

    # Apply price filtering BEFORE ranking
    if price_constraints:
        products = _apply_price_filter(products, price_constraints)

        # If price filtering removed everything, try a DB-level fallback
        if not products:
            logger.info("RAG | Price filter removed all candidates — trying DB fallback")
            products = _price_fallback_from_db(price_constraints, n)
            for p in products:
                p["_semantic_score"] = score_map.get(p["id"], 0.0)

    # Re-rank by semantic score
    products.sort(key=lambda p: p["_semantic_score"], reverse=True)

    # Return top_n
    result = products[:n]
    logger.info(
        "RAG | query=%r | candidates=%d | returned=%d | top_score=%.3f | price_filter=%s",
        query[:60], len(candidate_ids), len(result),
        result[0]["_semantic_score"] if result else 0,
        price_constraints or "none",
    )
    return result


def _price_fallback_from_db(constraints: dict, limit: int) -> list[dict]:
    """
    Fallback: query the database directly with price constraints
    when semantic search + price filter yields no results.
    """
    from db.database import get_db

    max_price = constraints.get("max_price")
    min_price = constraints.get("min_price")

    conditions = ["p.is_active = 1"]
    params = []

    if max_price is not None:
        conditions.append("p.price <= ?")
        params.append(max_price)
    if min_price is not None:
        conditions.append("p.price >= ?")
        params.append(min_price)

    where_clause = " AND ".join(conditions)
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT p.*, c.name AS category_name, c.slug AS category_slug
            FROM products p
            JOIN categories c ON p.category_id = c.id
            WHERE {where_clause}
            ORDER BY p.rating DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    results = [dict(row) for row in rows]
    logger.info("RAG | DB price fallback returned %d products", len(results))
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _product_to_text(product: dict) -> str:
    """
    Convert a product dict into a rich text string for embedding.
    The richer the text, the better the semantic retrieval.
    """
    tags = ""
    try:
        tags = ", ".join(json.loads(product.get("tags") or "[]"))
    except (json.JSONDecodeError, TypeError):
        tags = str(product.get("tags", ""))

    return (
        f"{product['name']} by {product['brand']}. "
        f"Category: {product.get('category_name', '')}. "
        f"Color: {product.get('color', '')}. "
        f"Price: {int(product['price'])} rupees. "
        f"Description: {product['description']}. "
        f"Tags: {tags}. "
        f"Rating: {product['rating']} stars."
    )
