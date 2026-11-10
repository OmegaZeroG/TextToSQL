"""A small e-commerce database that exists only to grade the eval.

The product never touches a database. The eval needs an answer key, though:
it sends SAMPLE_DDL to the API as the user's schema, then runs both the
generated SQL and the hand-written `expected_sql` against this in-memory SQLite
copy and compares the rows. Nothing is stored; the data is rebuilt (with a fixed
random seed, so it is identical every run) each time the eval starts.
"""
import random
import sqlite3
from datetime import date, timedelta

SAMPLE_DDL = """CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(category_id),
    price REAL NOT NULL,
    is_discontinued INTEGER DEFAULT 0
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL,
    city TEXT,
    signup_date TEXT NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,
    shipped_date TEXT,
    status TEXT NOT NULL
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER REFERENCES orders(order_id),
    product_id INTEGER REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
"""

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
NEVER_ORDERED = {"Webcam", "Board Game"}
FIRST_NAMES = ["Alex", "Jordan", "Sam", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Priya", "Wei", "Fatima", "Liam"]
LAST_NAMES = ["Smith", "Johnson", "Lee", "Garcia", "Brown", "Patel", "Kim", "Nguyen", "Davis", "Miller"]


# Customers whose order months are chosen by hand, so "consecutive months" questions
# have a known answer. Each is a scenario a naive query tends to get wrong.
STREAK_CUSTOMERS = {
    # customer_id: order dates
    121: ["2025-01-05", "2025-01-12", "2025-01-20", "2025-02-10", "2025-03-15"],  # Jan-Mar, several orders in January
    122: ["2025-01-10", "2025-02-10", "2025-04-10"],  # Jan-Feb, then a gap: no 3-month run
    123: ["2025-01-10", "2025-02-10", "2025-03-10", "2025-06-10", "2025-07-10", "2025-08-10", "2025-09-10"],  # longest is Jun-Sep
    124: ["2025-01-10", "2025-02-10", "2025-03-10", "2025-06-10", "2025-07-10", "2025-08-10"],  # tie: earliest (Jan-Mar) wins
    125: ["2025-11-20", "2025-12-18", "2026-01-09"],  # runs across a year end
}


def _add_streak_customers(conn: sqlite3.Connection, order_count: int, item_count: int, product: tuple) -> None:
    order_id, item_id = order_count, item_count
    for customer_id, dates in STREAK_CUSTOMERS.items():
        conn.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)",
            (customer_id, "Streak", f"Tester{customer_id}", f"streak{customer_id}@example.com", "Testville", "2025-01-01"),
        )
        for day in dates:
            order_id += 1
            item_id += 1
            conn.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", (order_id, customer_id, day, day, "completed"))
            conn.execute("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", (item_id, order_id, product[0], 1, product[3]))


def build_sample_db() -> sqlite3.Connection:
    """Return a read-only-after-load in-memory database. Dates are ISO text."""
    rng = random.Random(42)
    conn = sqlite3.connect(":memory:")
    conn.executescript(SAMPLE_DDL)

    conn.executemany("INSERT INTO categories VALUES (?, ?)", list(enumerate(CATEGORIES, 1)))

    products = []
    for category_id, category in enumerate(CATEGORIES, 1):
        for name in PRODUCT_NAMES[category]:
            products.append((len(products) + 1, name, category_id, round(rng.uniform(8, 400), 2), int(rng.random() < 0.08)))
    conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", products)

    customers = []
    for customer_id in range(1, 121):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        signup = date(2023, 1, 1) + timedelta(days=rng.randint(0, 700))
        customers.append((
            customer_id, first, last, f"{first.lower()}.{last.lower()}{customer_id}@example.com",
            rng.choice(CITIES), signup.isoformat(),
        ))
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)", customers)

    # Two products are never ordered, so "which products have never been ordered?"
    # has a real answer (otherwise an empty result would pass any wrong query).
    orderable = [p for p in products if p[1] not in NEVER_ORDERED]
    orders, items = [], []
    for order_id in range(1, 401):
        order_date = date(2024, 1, 1) + timedelta(days=rng.randint(0, 600))
        status = rng.choices(STATUSES, weights=[0.55, 0.2, 0.15, 0.1])[0]
        shipped = None
        if status in ("completed", "shipped"):
            shipped = (order_date + timedelta(days=rng.randint(1, 6))).isoformat()
        orders.append((order_id, rng.randint(1, 120), order_date.isoformat(), shipped, status))
        for _ in range(rng.randint(1, 4)):
            product = rng.choice(orderable)
            items.append((len(items) + 1, order_id, product[0], rng.randint(1, 3), product[3]))
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders)
    conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", items)
    _add_streak_customers(conn, len(orders), len(items), products[0])
    conn.commit()

    conn.execute("PRAGMA query_only = ON")  # whatever runs next can only read
    return conn
