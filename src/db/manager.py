import duckdb
import pandas as pd
import os

class DBManager:
    def __init__(self, db_path: str = "data/analyst.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = duckdb.connect(db_path)
        self.initialize_sample_data()

    def initialize_sample_data(self):
        # Create sales table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                sale_id INTEGER PRIMARY KEY,
                product_id INTEGER,
                customer_id INTEGER,
                amount DECIMAL,
                sale_date DATE,
                region VARCHAR
            )
        """)

        # Create customers table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id INTEGER PRIMARY KEY,
                name VARCHAR,
                email VARCHAR,
                signup_date DATE,
                segment VARCHAR
            )
        """)

        # Insert sample data if empty
        if self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0:
            self.conn.execute("""
                INSERT INTO sales VALUES
                (1, 101, 1, 150.00, '2026-01-01', 'North'),
                (2, 102, 2, 200.00, '2026-01-02', 'South'),
                (3, 101, 3, 150.00, '2026-01-03', 'East'),
                (4, 103, 1, 300.00, '2026-01-04', 'West'),
                (5, 102, 4, 200.00, '2026-01-05', 'North')
            """)

        if self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
            self.conn.execute("""
                INSERT INTO customers VALUES
                (1, 'Alice Smith', 'alice@example.com', '2025-10-01', 'Enterprise'),
                (2, 'Bob Jones', 'bob@example.com', '2025-11-15', 'SMB'),
                (3, 'Charlie Brown', 'charlie@example.com', '2025-12-20', 'Consumer'),
                (4, 'David Wilson', 'david@example.com', '2026-01-01', 'SMB')
            """)

    def execute_query(self, query: str) -> pd.DataFrame:
        return self.conn.execute(query).fetchdf()

    def get_schema(self) -> str:
        tables = self.conn.execute("SHOW TABLES").fetchall()
        schema_info = []
        for table_tuple in tables:
            table_name = table_tuple[0]
            columns = self.conn.execute(f"DESCRIBE {table_name}").fetchall()
            col_desc = ", ".join([f"{c[0]} ({c[1]})" for c in columns])
            schema_info.append(f"Table: {table_name}\nColumns: {col_desc}")
        return "\n\n".join(schema_info)

    def get_table_names(self) -> list:
        tables = self.conn.execute("SHOW TABLES").fetchall()
        return [t[0] for t in tables]

if __name__ == "__main__":
    db = DBManager()
    print("Schema:")
    print(db.get_schema())
    print("\nSample Query (Sales total):")
    print(db.execute_query("SELECT SUM(amount) FROM sales"))
