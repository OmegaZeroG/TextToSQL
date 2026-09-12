"""Generates a synthetic e-commerce dataset in DuckDB for the text-to-SQL demo.

Schema: categories, products, customers, orders, order_items.
Deliberately includes multi-table joins, aggregations, and a few realistic
data quirks (NULL shipped_at for pending orders, discontinued products)
so generated SQL and guardrails have something real to work against.
"""
import random
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).parent / "sample.duckdb"

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


def build():
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = duckdb.connect(str(DB_PATH))

    con.execute("""
        CREATE TABLE categories (
            category_id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL,
            category_id INTEGER REFERENCES categories(category_id),
            price DECIMAL(10,2) NOT NULL,
            is_discontinued BOOLEAN DEFAULT FALSE
        )
    """)
    con.execute("""
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            first_name VARCHAR NOT NULL,
            last_name VARCHAR NOT NULL,
            email VARCHAR NOT NULL,
            city VARCHAR,
            signup_date DATE NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customers(customer_id),
            order_date DATE NOT NULL,
            shipped_date DATE,
            status VARCHAR NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE order_items (
            order_item_id INTEGER PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id),
            product_id INTEGER REFERENCES products(product_id),
            quantity INTEGER NOT NULL,
            unit_price DECIMAL(10,2) NOT NULL
        )
    """)

    categories = [(i + 1, name) for i, name in enumerate(CATEGORIES)]
    con.executemany("INSERT INTO categories VALUES (?, ?)", categories)

    products = []
    pid = 1
    for cat_id, cat_name in categories:
        for name in PRODUCT_NAMES[cat_name]:
            price = round(random.uniform(8, 400), 2)
            discontinued = random.random() < 0.08
            products.append((pid, name, cat_id, price, discontinued))
            pid += 1
    con.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", products)

    first_names = ["Alex", "Jordan", "Sam", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Priya", "Wei", "Fatima", "Liam"]
    last_names = ["Smith", "Johnson", "Lee", "Garcia", "Brown", "Patel", "Kim", "Nguyen", "Davis", "Miller"]

    customers = []
    for cid in range(1, 121):
        fn, ln = random.choice(first_names), random.choice(last_names)
        signup = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 700))
        customers.append((
            cid, fn, ln, f"{fn.lower()}.{ln.lower()}{cid}@example.com",
            random.choice(CITIES), signup.date(),
        ))
    con.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)", customers)

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
        orders.append((order_id, customer_id, order_date.date(), shipped_date, status))

        for _ in range(random.randint(1, 4)):
            product = random.choice(products)
            qty = random.randint(1, 3)
            order_items.append((item_id, order_id, product[0], qty, product[3]))
            item_id += 1
        order_id += 1

    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders)
    con.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", order_items)

    con.close()
    print(f"Seeded {DB_PATH} with {len(customers)} customers, {len(products)} products, "
          f"{len(orders)} orders, {len(order_items)} order items.")


if __name__ == "__main__":
    build()
