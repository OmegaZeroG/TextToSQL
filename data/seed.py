"""Generates a synthetic e-commerce dataset in Postgres for the text-to-SQL demo.

Schema: categories, products, customers, orders, order_items.
Deliberately includes multi-table joins, aggregations, and a few realistic
data quirks (NULL shipped_date for pending orders, discontinued products)
so generated SQL and guardrails have something real to work against.

Drops and recreates the schema on every run — deterministic reset, safe to
run on every container startup for a demo (see backend/entrypoint.sh).
"""
import os
import random
from datetime import datetime, timedelta

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5433/texttosql"
)

random.seed(42)

CATEGORIES = ["Electronics", "Home & Kitchen", "Books", "Sports", "Toys", "Clothing"]

PRODUCT_NAMES = {
    "Electronics": ["Wireless Mouse", "USB-C Hub", "Bluetooth Speaker", "4K Monitor", "Mechanical Keyboard", "Webcam"],
    "Home & Kitchen": ["Air Fryer", "Coffee Grinder", "Cast Iron Skillet", "Blender", "Knife Set"],
    "Books": ["Python Crash Course", "Atomic Habits", "The Pragmatic Programmer", "Dune", "Clean Code"],
    "Sports": ["Yoga Mat", "Dumbbell Set", "Running Shoes", "Resistance Bands", "Water Bottle"],
    "Toys": ["Building Blocks", "RC Car", "Puzzle 1000pc", "Board Game"],
    "Clothing": ["Denim Jacket", "Running Shorts", "Wool Sweater", "Rain Jacket"],
}

CITIES = ["New York", "Austin", "Seattle", "Chicago", "Denver", "Miami", "Boston", "Phoenix"]
STATUSES = ["completed", "shipped", "processing", "cancelled"]

SCHEMA_SQL = """
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS categories CASCADE;

CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    category_id INTEGER REFERENCES categories(category_id),
    price NUMERIC(10,2) NOT NULL,
    is_discontinued BOOLEAN DEFAULT FALSE
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    first_name VARCHAR NOT NULL,
    last_name VARCHAR NOT NULL,
    email VARCHAR NOT NULL,
    city VARCHAR,
    signup_date DATE NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(customer_id),
    order_date DATE NOT NULL,
    shipped_date DATE,
    status VARCHAR NOT NULL
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER REFERENCES orders(order_id),
    product_id INTEGER REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(10,2) NOT NULL
);
"""


def build():
    engine = create_engine(DATABASE_URL)

    categories = [{"id": i + 1, "name": name} for i, name in enumerate(CATEGORIES)]

    products = []
    pid = 1
    for cat in categories:
        for name in PRODUCT_NAMES[cat["name"]]:
            products.append({
                "id": pid,
                "name": name,
                "category_id": cat["id"],
                "price": round(random.uniform(8, 400), 2),
                "discontinued": random.random() < 0.08,
            })
            pid += 1

    first_names = ["Alex", "Jordan", "Sam", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Priya", "Wei", "Fatima", "Liam"]
    last_names = ["Smith", "Johnson", "Lee", "Garcia", "Brown", "Patel", "Kim", "Nguyen", "Davis", "Miller"]

    customers = []
    for cid in range(1, 121):
        fn, ln = random.choice(first_names), random.choice(last_names)
        signup = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 700))
        customers.append({
            "id": cid, "first_name": fn, "last_name": ln,
            "email": f"{fn.lower()}.{ln.lower()}{cid}@example.com",
            "city": random.choice(CITIES), "signup_date": signup.date(),
        })

    orders = []
    order_items = []
    order_id = 1
    item_id = 1
    for _ in range(400):
        customer_id = random.randint(1, 120)
        order_date = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 600))
        status = random.choices(STATUSES, weights=[0.55, 0.2, 0.15, 0.1])[0]
        shipped_date = None
        if status in ("completed", "shipped"):
            shipped_date = (order_date + timedelta(days=random.randint(1, 6))).date()
        orders.append({
            "id": order_id, "customer_id": customer_id, "order_date": order_date.date(),
            "shipped_date": shipped_date, "status": status,
        })

        for _ in range(random.randint(1, 4)):
            product = random.choice(products)
            qty = random.randint(1, 3)
            order_items.append({
                "id": item_id, "order_id": order_id, "product_id": product["id"],
                "quantity": qty, "unit_price": product["price"],
            })
            item_id += 1
        order_id += 1

    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL))

        conn.execute(text("INSERT INTO categories VALUES (:id, :name)"), categories)
        conn.execute(text(
            "INSERT INTO products VALUES (:id, :name, :category_id, :price, :discontinued)"
        ), products)
        conn.execute(text(
            "INSERT INTO customers VALUES (:id, :first_name, :last_name, :email, :city, :signup_date)"
        ), customers)
        conn.execute(text(
            "INSERT INTO orders VALUES (:id, :customer_id, :order_date, :shipped_date, :status)"
        ), orders)
        conn.execute(text(
            "INSERT INTO order_items VALUES (:id, :order_id, :product_id, :quantity, :unit_price)"
        ), order_items)

    print(f"Seeded Postgres with {len(customers)} customers, {len(products)} products, "
            f"{len(orders)} orders, {len(order_items)} order items.")


if __name__ == "__main__":
    build()
