import psycopg2
import pandas as pd

# 连接 PostgreSQL 数据库
conn = psycopg2.connect(
    dbname="stock_network",
    user="postgres",
    password="postgres",  # 请替换为你的 PostgreSQL 密码
    host="localhost",
    port="5432"
)
cursor = conn.cursor()

query = """
UPDATE stock
SET current_price = latest_prices.close_price
FROM (
    SELECT DISTINCT ON (symbol) symbol, close_price
    FROM stockhistory
    ORDER BY symbol, date DESC
) AS latest_prices
WHERE stock.symbol = latest_prices.symbol;
"""

cursor.execute(query)
conn.commit()

cursor.close()
conn.close()