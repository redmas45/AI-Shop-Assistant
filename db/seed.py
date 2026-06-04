"""
Seed the database with products from the local products.json file.
Run: python db/seed.py
"""
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import init_db, get_db  # noqa: E402


def format_category_name(slug: str) -> str:
    mapping = {
        "beauty": "Beauty",
        "fragrances": "Fragrances",
        "furniture": "Furniture",
        "groceries": "Groceries",
        "home-decoration": "Home Decor",
        "kitchen-accessories": "Kitchen Accessories",
        "laptops": "Laptops",
        "mens-shirts": "Men's Shirts",
        "mens-shoes": "Men's Shoes",
        "mens-watches": "Men's Watches",
        "mobile-accessories": "Mobile Accessories",
        "motorcycle": "Motorcycle Accessories",
        "skin-care": "Skin Care",
        "smartphones": "Smartphones",
        "sports-accessories": "Sports Accessories",
        "sunglasses": "Sunglasses",
        "tablets": "Tablets",
        "tops": "Women's Tops",
        "vehicle": "Automotive",
        "womens-bags": "Women's Bags",
        "womens-dresses": "Women's Dresses",
        "womens-jewellery": "Women's Jewellery",
        "womens-shoes": "Women's Shoes",
        "womens-watches": "Women's Watches",
    }
    return mapping.get(slug, slug.replace("-", " ").title())


def seed():
    """Read products.json and seed the SQLite database."""
    json_path = Path(__file__).parent.parent / "products.json"
    if not json_path.exists():
        print(f"Error: {json_path} does not exist.")
        sys.exit(1)

    print(f"Reading product data from {json_path}...")
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Error reading JSON file: {exc}")
        sys.exit(1)

    products = data.get("products", [])
    if not products:
        print("No products found in the JSON file.")
        sys.exit(1)

    print(f"Retrieved {len(products)} products from local file. Seeding database...")
    init_db()

    with get_db() as conn:
        # Clear existing data first
        conn.execute("DELETE FROM cart")
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM categories")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('products', 'categories', 'cart')")
        conn.commit()

        # Insert categories dynamically
        categories = set(p["category"] for p in products)
        cat_id_map = {}
        for cat_slug in categories:
            cat_name = format_category_name(cat_slug)
            conn.execute(
                "INSERT OR IGNORE INTO categories (name, slug) VALUES (?, ?)",
                (cat_name, cat_slug),
            )
            # Fetch inserted ID
            row = conn.execute("SELECT id FROM categories WHERE slug = ?", (cat_slug,)).fetchone()
            cat_id_map[cat_slug] = row[0]

        # Insert products
        for p in products:
            cat_id = cat_id_map[p["category"]]
            
            # Map images & tags
            img_list = p.get("images", [])
            img_url = json.dumps(img_list) if img_list else ""
            
            # Combine tags and category for rich tags
            item_tags = p.get("tags", [])
            if p["category"] not in item_tags:
                item_tags.append(p["category"])
            tags_str = json.dumps(item_tags)
            
            # Convert price to realistic INR (scale by 80)
            usd_price = p.get("price", 0.0)
            inr_price = round(usd_price * 80, 2)
            original_price = round(inr_price * (1 + p.get("discountPercentage", 10.0) / 100), 2)
            
            # Extract rating, review count, stock
            rating = p.get("rating", 4.0)
            review_count = len(p.get("reviews", [])) * 15 + 10  # realistic count
            stock = p.get("stock", 100)
            brand = p.get("brand", "AI-KART")
            
            conn.execute(
                """
                INSERT INTO products
                  (name, brand, category_id, description, price, original_price,
                   color, size_options, tags, rating, review_count, stock, image_url, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    p["title"], brand, cat_id, p["description"],
                    inr_price, original_price, "", "[]",
                    tags_str, rating, review_count, stock, img_url
                ),
            )

    print(f"[+] Successfully seeded {len(products)} products across {len(categories)} categories.")


if __name__ == "__main__":
    seed()
