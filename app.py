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
        password="postgres",  # 请替换为你的 PostgreSQL 密码
        host="localhost",
        port="5432"
    )

bcrypt = Bcrypt(app)

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

    current_user_id = session['user_id']
    user_id = session['user_id']  # ✅ 你漏了这一句！

    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 1. 获取所有其他用户（用于添加好友）
    cursor.execute("""
        SELECT id, username FROM users WHERE id != %s;
    """, (current_user_id,))
    users = cursor.fetchall()

    # 🔹 2. 获取收到的好友请求（pending）
    cursor.execute("""
        SELECT u.id, u.username
        FROM friends f
        JOIN users u ON f.user1_id = u.id
        WHERE f.user2_id = %s AND f.status = 0;
    """, (current_user_id,))
    friend_requests = cursor.fetchall()

    # 🔹 3. 获取已经建立的好友关系（双向 status = 1）
    cursor.execute("""
        SELECT DISTINCT u.id, u.username
        FROM friends f
        JOIN users u ON (
            (f.user1_id = u.id AND f.user2_id = %s)
            OR (f.user2_id = u.id AND f.user1_id = %s)
        )
        WHERE f.status = 1;
    """, (current_user_id, current_user_id))
    friends = cursor.fetchall()

    cursor.execute("""
        SELECT DISTINCT s.owner, u.username, s.name
        FROM stocklist_data s
        JOIN users u ON s.owner = u.id
        WHERE 
            s.visible = 2  -- public
            OR (s.visible = 1 AND (
                s.owner = %s
                OR s.owner IN (
                    SELECT f.user1_id FROM friends f WHERE f.user2_id = %s AND f.status = 1
                    UNION
                    SELECT f.user2_id FROM friends f WHERE f.user1_id = %s AND f.status = 1
                )
            ))
            OR (s.visible = 0 AND (
                s.owner = %s
                OR EXISTS (
                    SELECT 1 FROM comments c
                    WHERE c.watchlist_owner = s.owner AND c.watchlist_name = s.name AND c.user_id = %s
                )
            ))
    """, (user_id, user_id, user_id, user_id, user_id))


    public_stocklists = cursor.fetchall()


    cursor.close()
    conn.close()

    # 🔹 5. 渲染页面
    return render_template(
        'welcome.html',
        users=users,
        friend_requests=friend_requests,
        friends=friends,
        public_stocklists=public_stocklists,
        current_user=session['username'],
        current_user_id=current_user_id
    )


@app.route('/send_friend_request', methods=['POST'])
def send_friend_request():
    if 'user_id' not in session:
        return jsonify({"message": "Please log in first"}), 401

    data = request.json
    user1_id = session['user_id']
    user2_id = data.get("user2_id")

    if user1_id == user2_id:
        return jsonify({"message": "Cannot add myself as a friend"}), 400

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
            return jsonify({"message": "Request sent"}), 400
        elif status == 1:
            return jsonify({"message": "You are already friends"}), 400
        elif status == -1 and (now - ts).total_seconds() < 300:
            return jsonify({"message": "Cooling down, please send again in 5 minutes"}), 400
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

    return jsonify({"message": "Friend request sent"}), 201


@app.route('/respond_friend_request', methods=['POST'])
def respond_friend_request():
    if 'user_id' not in session:
        return jsonify({"message": "Please log in first"}), 401

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

    return jsonify({"message": f"Friend request has been{action}"}), 200

@app.route('/delete_friend', methods=['POST'])
def delete_friend():
    if 'user_id' not in session:
        return jsonify({"message": "Please log in first"}), 401

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

    return jsonify({"message": "Friend has been deleted"})



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
        return jsonify({'message': 'Please log in first'}), 401

    data = request.get_json()
    symbol = data.get('symbol')
    watchlistname = data.get('watchlistname', 'default')
    quantity = int(data.get('quantity', 1))
    user_id = session['user_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        # ✅ Step 1: 自动插入 stocklist_data 行（如果不存在）
        cursor.execute("""
            INSERT INTO stocklist_data (owner, name, visible)
            VALUES (%s, %s, 0)
            ON CONFLICT (owner, name) DO NOTHING;
        """, (user_id, watchlistname))


        cursor.execute("""
            INSERT INTO watchlist (symbol, watchlistname, owner, quantity)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (symbol, watchlistname, owner)
            DO UPDATE SET quantity = watchlist.quantity + EXCLUDED.quantity;
        """, (symbol, watchlistname, user_id, quantity))

        conn.commit()
        message = f"✅ Added {symbol} x{quantity} to {watchlistname}"
    except Exception as e:
        conn.rollback()
        message = f"❌ Add failed: {str(e)}"
    finally:
        cursor.close()
        conn.close()

    return jsonify({'message': message})



@app.route('/add_to_portfolio', methods=['POST'])
def add_to_portfolio():
    if 'user_id' not in session:
        return jsonify({'message': 'Please log in first'}), 401

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
        return jsonify({'message': f'Add failed: {str(e)}'}), 500
    finally:
        cursor.close()
        conn.close()

    return jsonify({'message': f'{symbol} Added to Portfolio, quantity: {qty}'})



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

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()

    # 查询 watchlist 股票数据
    cursor.execute("""
        SELECT w.watchlistname, w.symbol, s.company_name, s.current_price, w.quantity
        FROM watchlist w
        JOIN stock s ON w.symbol = s.symbol
        WHERE w.owner = %s
    """, (user_id,))
    raw_watchlist = cursor.fetchall()

    # 分组并收集数据
    watchlist_grouped = {}
    for watchlistname, symbol, company, price, quantity in raw_watchlist:
        if watchlistname not in watchlist_grouped:
            watchlist_grouped[watchlistname] = []
        watchlist_grouped[watchlistname].append((symbol, company, price, quantity))

    # ✅ 加载 visibility_data
    cursor.execute("""
        SELECT name, visible FROM stocklist_data
        WHERE owner = %s
    """, (user_id,))
    vis_rows = cursor.fetchall()
    visibility_data = {name: visible for name, visible in vis_rows}

    # 查询历史价格
    history_data = {}
    for stocks in watchlist_grouped.values():
        for symbol, _, _, _ in stocks:
            if symbol not in history_data:
                cursor.execute("""
                    SELECT date, close_price FROM stockhistory
                    WHERE symbol = %s AND date BETWEEN '2013-01-01' AND '2018-02-07'
                    ORDER BY date;
                """, (symbol,))
                rows = cursor.fetchall()
                history_data[symbol] = [
                    {'date': row[0].strftime('%Y-%m-%d'), 'price': row[1]} for row in rows
                ]

    cursor.close()
    conn.close()

    return render_template(
        "watchlist_dashboard.html",
        watchlist_grouped=watchlist_grouped,
        history_data=history_data,
        visibility_data=visibility_data  # ✅ 必须传入
    )




@app.route('/watchlist/<int:owner_id>/<watchlist_name>')
def view_watchlist(owner_id, watchlist_name):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    is_creator = (user_id == owner_id)

    conn = get_db_connection()
    cursor = conn.cursor()

    # 查询 stocklist 是否存在 & 可见性
    cursor.execute("""
        SELECT visible FROM stocklist_data
        WHERE owner = %s AND name = %s
    """, (owner_id, watchlist_name))
    result = cursor.fetchone()

    if not result:
        cursor.close()
        conn.close()
        return "❌ Stocklist does not exist", 404

    visible = result[0]

    # 如果不是公开且不是创建者，再检查是否评论过
    if not visible and not is_creator:
        cursor.execute("""
            SELECT 1 FROM comments
            WHERE user_id = %s AND watchlist_owner = %s AND watchlist_name = %s
            LIMIT 1
        """, (user_id, owner_id, watchlist_name))
        has_commented = cursor.fetchone() is not None

        if not has_commented:
            cursor.close()
            conn.close()
            return "❌ This stocklist is not public and you are not the reviewer or owner", 403

    # ✅ 获取所有评论（含评论 ID, user_id, username, content, timestamp）
    cursor.execute("""
        SELECT c.id, c.user_id, u.username, c.content, c.timestamp
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.watchlist_owner = %s AND c.watchlist_name = %s
        ORDER BY c.timestamp DESC
    """, (owner_id, watchlist_name))
    comments = cursor.fetchall()

    # ✅ 当前用户的评论（用于编辑表单）
    cursor.execute("""
        SELECT content FROM comments
        WHERE user_id = %s AND watchlist_owner = %s AND watchlist_name = %s
        LIMIT 1
    """, (user_id, owner_id, watchlist_name))
    my_comment = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        'watchlist_comments.html',
        comments=comments,
        watchlist_name=watchlist_name,
        owner_id=owner_id,
        current_user_id=user_id,
        my_comment=my_comment,
        is_creator=is_creator
    )


@app.route('/submit_comment', methods=['POST'])
def submit_comment():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    data = request.form
    user_id = session['user_id']
    owner_id = int(data['owner_id'])
    watchlist_name = data['watchlist_name']
    text = data['text']

    conn = get_db_connection()
    cursor = conn.cursor()

    # 是否已有评论
    cursor.execute("""
        SELECT id FROM comments
        WHERE user_id = %s AND watchlist_owner = %s AND watchlist_name = %s
    """, (user_id, owner_id, watchlist_name))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE comments SET content = %s, timestamp = NOW()
            WHERE id = %s
        """, (text, existing[0]))
    else:
        cursor.execute("""
            INSERT INTO comments (user_id, watchlist_owner, watchlist_name, content)
            VALUES (%s, %s, %s, %s)
        """, (user_id, owner_id, watchlist_name, text))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('view_watchlist', owner_id=owner_id, watchlist_name=watchlist_name))


@app.route('/delete_comment', methods=['POST'])
def delete_comment():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    comment_id = request.args.get('comment_id')
    user_id = session['user_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    # 检查权限（评论作者或 stocklist owner）
    cursor.execute("""
        SELECT user_id, watchlist_owner, watchlist_name FROM comments WHERE id = %s
    """, (comment_id,))
    comment = cursor.fetchone()

    if not comment:
        return "Comment does not exist", 404

    if user_id != comment[0] and user_id != comment[1]:
        return "No permission to delete this comment", 403

    cursor.execute("DELETE FROM comments WHERE id = %s", (comment_id,))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('view_watchlist', owner_id=comment[1], watchlist_name=comment[2]))



@app.route('/toggle_visibility', methods=['POST'])
def toggle_visibility():
    if 'user_id' not in session:
        return jsonify({'message': 'Not logged in'}), 401

    data = request.json
    watchlist_name = data.get('watchlist_name')
    new_status = data.get('visible')  # 应为 0, 1 或 2
    user_id = session['user_id']

    # 校验 visible 值是否合法
    if new_status not in [0, 1, 2]:
        return jsonify({'message': 'Invalid visibility value'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # 更新数据库中对应 watchlist 的可见性
    cursor.execute("""
        UPDATE stocklist_data
        SET visible = %s
        WHERE owner = %s AND name = %s;
    """, (new_status, user_id, watchlist_name))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({'message': 'Visibility updated successfully ✅'})



@app.route('/watchlist/<int:owner_id>/<watchlist_name>/performance')
def watchlist_performance(owner_id, watchlist_name):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取该 watchlist 中所有的股票 symbol + 数量
    cursor.execute("""
        SELECT w.symbol, s.company_name, s.current_price, w.quantity
        FROM watchlist w
        JOIN stock s ON w.symbol = s.symbol
        WHERE w.owner = %s AND w.watchlistname = %s
    """, (owner_id, watchlist_name))
    stocks = cursor.fetchall()

    # 每个 symbol 的历史价格
    history_data = {}
    for symbol, _, _, _ in stocks:
        cursor.execute("""
            SELECT date, close_price
            FROM stockhistory
            WHERE symbol = %s AND date BETWEEN '2013-01-01' AND '2018-02-07'
            ORDER BY date;
        """, (symbol,))
        rows = cursor.fetchall()
        history_data[symbol] = [{'date': r[0].strftime('%Y-%m-%d'), 'price': r[1]} for r in rows]

    cursor.close()
    conn.close()

    return render_template("watchlist_performance.html",
                           stocks=stocks,
                           watchlist_name=watchlist_name,
                           owner_id=owner_id,
                           history_data=history_data)




# 📌 用户登出
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True,port=5001)