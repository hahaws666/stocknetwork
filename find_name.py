import pandas as pd
import yfinance as yf
import psycopg2

# 加载 CSV 文件
df = pd.read_csv('SP500History.csv')  # 替换为你的文件路径
symbols = df['Code'].dropna().unique()

# 建立数据库连接
conn = psycopg2.connect(
    dbname="stock_network",
    user="postgres",
    password="",  # 填你的密码
    host="localhost",
    port="5432"
)
cursor = conn.cursor()

for symbol in symbols:
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        name = info.get('longName') or info.get('shortName') or "Unknown Company"

        cursor.execute("""
            UPDATE stock
            SET  company_name = %s
            WHERE symbol = %s;
        """, (name, symbol))

        print(f"✅ 插入 {symbol} - {name}")
    except Exception as e:
        print(f"❌ 失败: {symbol}, 错误: {e}")

conn.commit()
cursor.close()
conn.close()
