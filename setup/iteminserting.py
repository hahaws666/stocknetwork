import psycopg2
import pandas as pd

# ✅ PostgreSQL connection
conn = psycopg2.connect(
    dbname="stock_network",
    user="postgres",
    password="postgres",  # 🔒 Replace with your actual password
    host="localhost",
    port="5432"
)
cursor = conn.cursor()

# ✅ Load CSV
csv_file = "SP500History.csv"
df = pd.read_csv(csv_file)

# ✅ Normalize columns
df.columns = df.columns.str.lower()

# ✅ Queries
insert_stock_query = """
INSERT INTO Stock (symbol, current_price)
VALUES (%s, NULL)
ON CONFLICT (symbol) DO NOTHING;
"""

insert_stockhistory_query = """
INSERT INTO StockHistory (date, symbol, open_price, close_price, high_price, low_price, volume)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (date, symbol) DO NOTHING;
"""

# ✅ Loop with progress
for i, row in df.iterrows():
    try:
        cursor.execute(insert_stock_query, (row['code'],))
        cursor.execute(insert_stockhistory_query, (
            row['timestamp'],
            row['code'],
            row['open'],
            row['close'],
            row['high'],
            row['low'],
            row['volume']
        ))
    except Exception as e:
        print(f"⚠️ Error at row {i}: {e}")
    if (i + 1) % 100 == 0:
        print(f"Inserted {i + 1} rows...")

# ✅ Commit + close
conn.commit()
cursor.close()
conn.close()

print("[DONE] iteminserting.py")
