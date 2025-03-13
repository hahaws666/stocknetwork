import psycopg2
import pandas as pd

# 连接 PostgreSQL 数据库
conn = psycopg2.connect(
    dbname="stock_network",
    user="postgres",
    password="yourpassword",  # 请替换为你的 PostgreSQL 密码
    host="localhost",
    port="5432"
)
cursor = conn.cursor()

# 读取 CSV 文件
csv_file = "SP500History.csv"  # 请确保文件路径正确
df = pd.read_csv(csv_file)

# 规范列名（防止大小写问题）
df.columns = df.columns.str.lower()

# 插入数据到 Stock 表
insert_stock_query = """
INSERT INTO Stock (symbol, company_name, current_price)
VALUES (%s, NULL, NULL)
ON CONFLICT (symbol) DO NOTHING;
"""

# 插入数据到 StockHistory 表
insert_stockhistory_query = """
INSERT INTO StockHistory (date, symbol, open_price, close_price, high_price, low_price, volume)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (date, symbol) DO NOTHING;
"""

for _, row in df.iterrows():
    # 插入 `Stock`（company_name 和 current_price 设为 NULL）
    cursor.execute(insert_stock_query, (row['code'],))

    # 插入 `StockHistory`
    cursor.execute(insert_stockhistory_query, (
        row['timestamp'], row['code'], row['open'],
        row['close'], row['high'], row['low'], row['volume']
    ))

# 提交更改并关闭连接
conn.commit()
cursor.close()
conn.close()

print("✅ 数据成功存入 Stock 和 StockHistory！")
