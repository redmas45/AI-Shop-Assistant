CREATE TABLE IF NOT EXISTS categories (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE,
    slug    TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    brand           TEXT NOT NULL,
    category_id     INTEGER NOT NULL REFERENCES categories(id),
    description     TEXT NOT NULL,
    price           REAL NOT NULL,          -- INR
    original_price  REAL,                   -- INR (for discount display)
    color           TEXT,
    size_options    TEXT,                   -- JSON array e.g. '["S","M","L"]'
    tags            TEXT,                   -- JSON array e.g. '["casual","summer"]'
    rating          REAL DEFAULT 0.0,
    review_count    INTEGER DEFAULT 0,
    stock           INTEGER DEFAULT 100,
    image_url       TEXT,
    is_active       INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
CREATE INDEX IF NOT EXISTS idx_products_color ON products(color);
CREATE INDEX IF NOT EXISTS idx_products_rating ON products(rating DESC);

CREATE TABLE IF NOT EXISTS cart (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL DEFAULT 1,
    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_profile (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    address         TEXT,
    payment_method  TEXT
);
