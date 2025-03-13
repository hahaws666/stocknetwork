import psycopg2

# 连接 PostgreSQL 数据库
conn = psycopg2.connect("dbname=stock_network user=postgres password=")
cursor = conn.cursor()

# 查询所有用户
cursor.execute('SELECT * FROM "user";')
users = cursor.fetchall()

# 打印用户数据
for user in users:
    print(user)

# 关闭连接
cursor.close()
conn.close()
