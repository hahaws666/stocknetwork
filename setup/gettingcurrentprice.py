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

query ="""
UPDATE stock
SET current_price = (
    SELECT close_price
    FROM stockhistory
    WHERE stock.symbol = stockhistory.symbol
      AND date = '2018-02-07'
)
WHERE EXISTS (
    SELECT 1
    FROM stockhistory
    WHERE stock.symbol = stockhistory.symbol
      AND date = '2018-02-07'
);
"""
cursor.execute(query)
conn.commit()
cursor.close()
conn.close()