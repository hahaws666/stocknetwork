import psycopg2
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_bcrypt import Bcrypt

app = Flask(__name__, template_folder="templates")
app.config['SECRET_KEY'] = 'your_secret_key'  # 用于 session

# 连接数据库
def get_db_connection():
    return psycopg2.connect(
        dbname="stock_network",
        user="postgres",
        password="",  # 请替换为你的 PostgreSQL 密码
        host="localhost",
        port="5432"
    )

bcrypt = Bcrypt(app)

# 📌 创建数据库表
def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 创建 users 表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        email VARCHAR(100) UNIQUE NOT NULL,
        password VARCHAR(200) NOT NULL
    );
    """)

    # cursor.execute("DROP TABLE IF EXISTS friends CASCADE;")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS friends (
           user1_id INT NOT NULL,
            user2_id INT NOT NULL,
            status INT NOT NULL CHECK (status IN (-1, 0, 1)),  -- -1: 拒绝, 0: 待处理, 1: 好友
            timestamp TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (user1_id, user2_id),
            FOREIGN KEY (user1_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (user2_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)



    conn.commit()
    cursor.close()
    conn.close()

create_tables()


# 📌 主页（"/"）
@app.route('/')
def home():
    return render_template('index.html')


# 📌 用户注册
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s) RETURNING id;",
                       (data['username'], data['email'], hashed_password))
        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('login'))

    return render_template('register.html')



# 📌 用户登录
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.form

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password FROM users WHERE email = %s;", (data['email'],))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and bcrypt.check_password_hash(user[2], data['password']):
            session['user_id'] = user[0]  # 存储用户 ID
            session['username'] = user[1]  # 存储用户名
            return redirect(url_for('welcome'))  # 登录成功后跳转到 welcome 页面
        return "登录失败，请检查邮箱或密码！"

    return render_template('login.html')

# 📌 Welcome 页面（显示所有用户）
@app.route('/welcome')
def welcome():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    current_user_id = session['user_id']

    # 所有其他用户（可用于发送请求）
    cursor.execute("SELECT id, username FROM users WHERE id != %s;", (current_user_id,))
    users = cursor.fetchall()

    # 收到的好友请求（status = 0）
    cursor.execute("""
        SELECT u.id, u.username
        FROM friends f
        JOIN users u ON f.user1_id = u.id
        WHERE f.user2_id = %s AND f.status = 0;
    """, (current_user_id,))
    friend_requests = cursor.fetchall()

    # 所有已经通过的好友（双向考虑，status = 1）
    cursor.execute("""
        SELECT DISTINCT u.id, u.username
        FROM friends f
        JOIN users u ON 
            (f.status = 1 AND u.id = f.user1_id AND f.user2_id = %s)
         OR (f.status = 1 AND u.id = f.user2_id AND f.user1_id = %s);
    """, (current_user_id, current_user_id))
    friends = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'welcome.html',
        users=users,
        friend_requests=friend_requests,
        friends=friends,
        current_user=session['username'],
        current_user_id=current_user_id
    )


@app.route('/send_friend_request', methods=['POST'])
def send_friend_request():
    if 'user_id' not in session:
        return jsonify({"message": "请先登录"}), 401

    data = request.json
    user1_id = session['user_id']
    user2_id = data.get("user2_id")

    if user1_id == user2_id:
        return jsonify({"message": "不能添加自己为好友"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # 检查是否已有记录（用于避免重复请求 & 判断冷却时间）
    cursor.execute("""
        SELECT status, timestamp FROM friends 
        WHERE user1_id = %s AND user2_id = %s
    """, (user1_id, user2_id))

    existing = cursor.fetchone()

    from datetime import datetime, timedelta
    now = datetime.now()

    if existing:
        status, ts = existing
        if status == 0:
            return jsonify({"message": "请求已发送"}), 400
        elif status == 1:
            return jsonify({"message": "你们已经是好友"}), 400
        elif status == -1 and (now - ts).total_seconds() < 300:
            return jsonify({"message": "冷却中，5分钟后再发送"}), 400
        else:
            # 超过冷却时间后，更新为新的请求
            cursor.execute("""
                UPDATE friends SET status = 0, timestamp = NOW()
                WHERE user1_id = %s AND user2_id = %s
            """, (user1_id, user2_id))
    else:
    # 没有记录，插入新的请求
        cursor.execute("""
            INSERT INTO friends (user1_id, user2_id, status)
            VALUES (%s, %s, 0)
        """, (user1_id, user2_id))


    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": "好友请求已发送"}), 201


@app.route('/respond_friend_request', methods=['POST'])
def respond_friend_request():
    if 'user_id' not in session:
        return jsonify({"message": "请先登录"}), 401

    data = request.json
    user1_id = data.get("user1_id")
    user2_id = session['user_id']
    action = data.get("action")

    conn = get_db_connection()
    cursor = conn.cursor()

    if action == "accept":
        cursor.execute("""
            UPDATE friends SET status = 1, timestamp = NOW()
            WHERE user1_id = %s AND user2_id = %s AND status = 0
        """, (user1_id, user2_id))
    elif action == "reject":
        cursor.execute("""
            UPDATE friends SET status = -1, timestamp = NOW()
            WHERE user1_id = %s AND user2_id = %s AND status = 0
        """, (user1_id, user2_id))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": f"好友请求已{action}"}), 200

@app.route('/delete_friend', methods=['POST'])
def delete_friend():
    if 'user_id' not in session:
        return jsonify({"message": "请先登录"}), 401

    data = request.get_json()
    user_id = session['user_id']
    friend_id = data.get("friend_id")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 删除任何方向的好友记录（双向可能）
    cursor.execute("""
        DELETE FROM friends
        WHERE 
            (user1_id = %s AND user2_id = %s AND status = 1)
         OR (user1_id = %s AND user2_id = %s AND status = 1)
    """, (user_id, friend_id, friend_id, user_id))

    # 写入一条冷却记录（只存当前用户为 user1）
    cursor.execute("""
        INSERT INTO friends (user1_id, user2_id, status, timestamp)
        VALUES (%s, %s, -1, NOW())
        ON CONFLICT (user1_id, user2_id)
        DO UPDATE SET status = -1, timestamp = NOW()
    """, (friend_id,user_id))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": "好友已删除"})



@app.route('/search_stock', methods=['GET', 'POST'])
def search_stock():
    results = []

    if request.method == 'POST':
        keyword = request.form.get('keyword')
        conn = get_db_connection()
        cursor = conn.cursor()

        # 使用 SQL LIKE 进行模糊匹配
        cursor.execute("""
            SELECT symbol, company_name, current_price 
            FROM stock 
            WHERE symbol ILIKE %s
        """, (f"%{keyword}%",))

        results = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template('search_stock.html', results=results)



@app.route('/add_to_watchlist', methods=['POST'])
def add_to_watchlist():
    if 'user_id' not in session:
        return jsonify({'message': '请先登录'}), 401

    data = request.get_json()
    symbol = data.get('symbol')
    watchlistname = data.get('watchlistname', 'default')
    quantity = int(data.get('quantity', 1))
    user_id = session['user_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO watchlist (symbol, watchlistname, owner, quantity)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (symbol, watchlistname, owner)
            DO UPDATE SET quantity = watchlist.quantity + EXCLUDED.quantity;
        """, (symbol, watchlistname, user_id, quantity))

        conn.commit()
        message = f"✅ 已添加 {symbol} x{quantity} 到 {watchlistname}"
    except Exception as e:
        conn.rollback()
        message = f"❌ 添加失败: {str(e)}"
    finally:
        cursor.close()
        conn.close()

    return jsonify({'message': message})



@app.route('/add_to_portfolio', methods=['POST'])
def add_to_portfolio():
    if 'user_id' not in session:
        return jsonify({'message': '请先登录'}), 401

    data = request.json
    symbol = data.get('symbol')
    qty = data.get('qty', 0)
    price = data.get('price', None)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO portfolio (symbol, qty, owner, price)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (symbol, owner) DO UPDATE
            SET qty = portfolio.qty + EXCLUDED.qty;
        """, (symbol, qty, session['user_id'], price))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'message': f'添加失败: {str(e)}'}), 500
    finally:
        cursor.close()
        conn.close()

    return jsonify({'message': f'{symbol} 已加入 Portfolio，数量：{qty}'})



@app.route('/portfolio_watchlist')
def portfolio_watchlist():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    user_id = session['user_id']

    # 获取 Portfolio 数据
    cursor.execute("""
        SELECT p.symbol, s.company_name, p.qty, p.price, p.time
        FROM portfolio p
        JOIN stock s ON p.symbol = s.symbol
        WHERE p.owner = %s;
    """, (user_id,))
    portfolio = cursor.fetchall()

    # 获取 Watchlist 数据
    cursor.execute("""
        SELECT w.symbol, s.company_name, w.watchlistname
        FROM watchlist w
        JOIN stock s ON w.symbol = s.symbol
        WHERE w.owner = %s;
    """, (user_id,))
    watchlist = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("portfolio_watchlist.html", portfolio=portfolio, watchlist=watchlist, current_user=session['username'])




@app.route('/watchlist_dashboard')
def watchlist_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # 查询当前用户所有 watchlist 股票（带 watchlistname 分组）
    cursor.execute("""
        SELECT w.watchlistname, w.symbol, s.company_name, s.current_price, w.quantity
        FROM watchlist w
        JOIN stock s ON w.symbol = s.symbol
        WHERE w.owner = %s
    """, (session['user_id'],))

    raw_watchlist = cursor.fetchall()

    # group by watchlistname
    watchlist_grouped = {}
    for watchlistname, symbol, company, price, quantity in raw_watchlist:
        if watchlistname not in watchlist_grouped:
            watchlist_grouped[watchlistname] = []
        watchlist_grouped[watchlistname].append((symbol, company, price, quantity))

    # 获取每只股票的时间序列数据（2013-01-01 至 2018-02-07）
    history_data = {}
    for stocks in watchlist_grouped.values():
        for symbol, _, _, _ in stocks:
            if symbol not in history_data:  # 防止重复查同一股票
                cursor.execute("""
                    SELECT date, close_price FROM stockhistory
                    WHERE symbol = %s AND date BETWEEN '2013-01-01' AND '2018-02-07'
                    ORDER BY date;
                """, (symbol,))
                rows = cursor.fetchall()
                history_data[symbol] = [
                    {'date': row[0].strftime('%Y-%m-%d'), 'price': row[1]}
                    for row in rows
                ]

    cursor.close()
    conn.close()

    return render_template("watchlist_dashboard.html",
                           watchlist_grouped=watchlist_grouped,
                           history_data=history_data)




# 📌 用户登出
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
