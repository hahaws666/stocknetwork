import psycopg2

# 连接 PostgreSQL 数据库
conn = psycopg2.connect(
    dbname="stock_network",
    user="postgres",
    password="",  # 请替换为你的 PostgreSQL 密码
    host="localhost",
    port="5432"
)

cursor = conn.cursor()

# # 先删除 `StockHistory`，然后删除 `Stock`
# drop_tables = """
# DROP TABLE IF EXISTS StockHistory CASCADE;
# DROP TABLE IF EXISTS Stock CASCADE;
# """

# 创建 `Stock` 表
create_stock_table = """
CREATE TABLE IF NOT EXISTS Stock (
    symbol VARCHAR(10) PRIMARY KEY,
    company_name VARCHAR(255),
    current_price FLOAT
);
"""

# 创建 `StockHistory` 表
create_stockhistory_table = """
CREATE TABLE IF NOT EXISTS StockHistory (
    date DATE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    open_price FLOAT NOT NULL,
    close_price FLOAT NOT NULL,
    high_price FLOAT NOT NULL,
    low_price FLOAT NOT NULL,
    volume BIGINT NOT NULL,
    PRIMARY KEY (date, symbol),
    FOREIGN KEY (symbol) REFERENCES Stock(symbol) ON DELETE CASCADE
);
"""

# 执行 SQL 语句
# cursor.execute(drop_tables)  # 先删除表，避免冲突
cursor.execute(create_stock_table)
cursor.execute(create_stockhistory_table)
cursor.execute("""
    CREATE TABLE IF NOT EXISTS portfolio (
        symbol VARCHAR(10) REFERENCES stock(symbol),
        qty INT NOT NULL,
        owner INT REFERENCES users(id),
        price FLOAT,
        time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (symbol, owner)
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS watchlist (
        symbol VARCHAR(10) REFERENCES stock(symbol),
        watchlistname VARCHAR(100),
        owner INT REFERENCES users(id),
        quantity INTEGER DEFAULT 1,
    );
""")



# 提交更改并关闭连接
conn.commit()
cursor.close()
conn.close()

print("✅ 数据表已重建成功！")
