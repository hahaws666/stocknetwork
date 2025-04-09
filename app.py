import psycopg2
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_bcrypt import Bcrypt
from collections import defaultdict
from datetime import datetime,timedelta
import pandas as pd
from pmdarima import auto_arima

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

#######################################################################################
# REGISTER, LOGIN, ENTRY
#######################################################################################
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        username = data['username']
        password = data['password']
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s);",
                (username, hashed_password)
            )
            conn.commit()
        except psycopg2.IntegrityError:
            conn.rollback()
            return "Username already taken."

        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.form
        username = data['username']
        password = data['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE username = %s;", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and bcrypt.check_password_hash(user[0], password):
            session['username'] = username
            return redirect(url_for('welcome'))

        return "Login failed. Please check your username or password."

    return render_template('login.html')

#######################################################################################
# WELCOME DASHBOARD
#######################################################################################
@app.route('/welcome')
def welcome():
    if 'username' not in session:
        return redirect(url_for('login'))

    current_username = session['username']

    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 1. Get all users except self
    cursor.execute("""
        SELECT username FROM users WHERE username != %s;
    """, (current_username,))
    users = cursor.fetchall()

    # 🔹 2. Get pending friend requests sent to current user
    cursor.execute("""
        SELECT username1 FROM friends
        WHERE username2 = %s AND status = 0;
    """, (current_username,))
    friend_requests = cursor.fetchall()

    # 🔹 3. Get all confirmed friends (bidirectional where status = 1)
    cursor.execute("""
        SELECT DISTINCT 
            CASE
                WHEN username1 = %s THEN username2
                ELSE username1
            END AS friend
        FROM friends
        WHERE (username1 = %s OR username2 = %s) AND status = 1;
    """, (current_username, current_username, current_username))
    friends = cursor.fetchall()

    # ✅ 新增：获取当前用户发出的待处理好友请求（状态 = 0）
    cursor.execute("""
        SELECT username2 FROM friends WHERE username1 = %s AND status = 0
    """, (current_username,))
    sent_requests = [row[0] for row in cursor.fetchall()]

    # 🔹 4. Get accessible stocklists (public, friends, shared via comment)
    cursor.execute("""
        SELECT DISTINCT s.username, s.sname, s.visible
        FROM stocklist_data s
        WHERE 
            s.visible = 2
            OR (s.visible = 1 AND (
                s.username = %s
                OR s.username IN (
                    SELECT username1 FROM friends WHERE username2 = %s AND status = 1
                    UNION
                    SELECT username2 FROM friends WHERE username1 = %s AND status = 1
                )
            ))
            OR (s.visible = 0 AND (
                s.username = %s
                OR EXISTS (
                    SELECT 1 FROM reviews r
                    WHERE r.uname_owner = s.username AND r.sname = s.sname AND r.writer = %s
                )
            ))
    """, (current_username, current_username, current_username, current_username, current_username))
    public_stocklists = cursor.fetchall()

    # 🔹 Fetch your portfolios
    cursor.execute("""
        SELECT pname, cashbalance FROM portfolio WHERE username = %s
    """, (session['username'],))
    portfolios = cursor.fetchall()

    # 🔹 Fetch your watchlists
    cursor.execute("""
        SELECT sname FROM stocklist_data WHERE username = %s
    """, (session['username'],))
    watchlists = [row[0] for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    return render_template(
        'welcome.html',
        users=users,
        friend_requests=friend_requests,
        friends=friends,
        sent_requests=sent_requests,  # ✅ 加入传给模板
        public_stocklists=[(row[0], row[1], row[2]) for row in public_stocklists],
        current_user=current_username,
        portfolios=portfolios,
        watchlists=watchlists
    )

#######################################################################################
# FRIENDSHIP FUNCTION
#######################################################################################
@app.route('/send_friend_request', methods=['POST'])
def send_friend_request():
    if 'username' not in session:
        return jsonify({"message": "Please log in first"}), 401

    data = request.json
    username1 = session['username']
    username2 = data.get("username2")

    if username1 == username2:
        return jsonify({"message": "You can't friend yourself"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT status, timestamp FROM friends 
        WHERE username1 = %s AND username2 = %s
    """, (username1, username2))

    existing = cursor.fetchone()
    now = datetime.now()

    if existing:
        status, ts = existing
        if status == 0:
            return jsonify({"message": "Friend request already sent."}), 400
        elif status == 1:
            return jsonify({"message": "You're already friends!"}), 400
        elif status == -1 and (now - ts).total_seconds() < 300:
            return jsonify({"message": "Cooling down. Try again in 5 minutes."}), 400
        else:
            cursor.execute("""
                UPDATE friends SET status = 0, timestamp = NOW()
                WHERE username1 = %s AND username2 = %s
            """, (username1, username2))
    else:
        cursor.execute("""
            INSERT INTO friends (username1, username2, status)
            VALUES (%s, %s, 0)
        """, (username1, username2))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": "Friend request sent!"}), 201

@app.route('/respond_friend_request', methods=['POST'])
def respond_friend_request():
    if 'username' not in session:
        return jsonify({"message": "Please log in first"}), 401

    data = request.json
    username1 = data.get("username1")  # sender
    username2 = session['username']    # current user = receiver
    action = data.get("action")        # "accept" or "reject"

    conn = get_db_connection()
    cursor = conn.cursor()

    if action == "accept":
        cursor.execute("""
            UPDATE friends SET status = 1, timestamp = NOW()
            WHERE username1 = %s AND username2 = %s AND status = 0
        """, (username1, username2))
    elif action == "reject":
        cursor.execute("""
            UPDATE friends SET status = -1, timestamp = NOW()
            WHERE username1 = %s AND username2 = %s AND status = 0
        """, (username1, username2))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": f"Friend request {action}ed"}), 200

@app.route('/delete_friend', methods=['POST'])
def delete_friend():
    if 'username' not in session:
        return jsonify({"message": "Please log in first"}), 401

    data = request.get_json()
    username = session['username']
    friend_username = data.get("friend_username")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Delete the friendship (bidirectional check)
    cursor.execute("""
        DELETE FROM friends
        WHERE (username1 = %s AND username2 = %s AND status = 1)
           OR (username1 = %s AND username2 = %s AND status = 1)
    """, (username, friend_username, friend_username, username))

    # Insert cooldown record (forbid immediate re-request)
    cursor.execute("""
        INSERT INTO friends (username1, username2, status, timestamp)
        VALUES (%s, %s, -1, NOW())
        ON CONFLICT (username1, username2)
        DO UPDATE SET status = -1, timestamp = NOW()
    """, (friend_username, username))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": "Friend deleted and cooldown applied"}), 200


@app.route('/cancel_friend_request', methods=['POST'])
def cancel_friend_request():
    if 'username' not in session:
        return jsonify({"message": "Please log in first"}), 401

    data = request.json
    username1 = session['username']  # 当前用户（发送者）
    username2 = data.get("username2")  # 接收者

    conn = get_db_connection()
    cursor = conn.cursor()

    # 只删除还在 pending 状态的请求
    cursor.execute("""
        DELETE FROM friends
        WHERE username1 = %s AND username2 = %s AND status = 0
    """, (username1, username2))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": "Friend request cancelled."}), 200


#######################################################################################
# STOCK FUNCTION
#######################################################################################
@app.route('/search_stock', methods=['GET', 'POST'])
def search_stock():
    results = []
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        keyword = request.form.get('keyword')
        cursor.execute("""
            SELECT symbol, current_price 
            FROM stock 
            WHERE symbol ILIKE %s
        """, (f"%{keyword}%",))
    else:
        cursor.execute("""
            SELECT symbol, current_price 
            FROM stock 
            ORDER BY symbol
        """)

    results = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('search_stock.html', results=results)

@app.route('/stock/<symbol>', methods=['GET', 'POST'])
def view_stock_detail(symbol):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch historical data
    cursor.execute("""
        SELECT date, open_price, close_price, high_price, low_price, volume
        FROM stockhistory
        WHERE symbol = %s
        ORDER BY date
    """, (symbol,))
    history = cursor.fetchall()

    prediction_data = []
    prediction_end = None

    if request.method == 'POST':
        prediction_end = request.form.get("prediction_end")
        if history and prediction_end:
            last_date = max(row[0] for row in history)
            start_date = last_date.strftime('%Y-%m-%d')
            try:
                prediction_data = calculate_prediction(cursor, symbol, start_date, prediction_end)
            except Exception as e:
                print(f"Prediction error: {e}")
                prediction_data = []

    cursor.close()
    conn.close()

    return render_template("stock_detail.html",
                           symbol=symbol,
                           history=history,
                           prediction_data=prediction_data,
                           prediction_end=prediction_end)

@app.route('/add_stock_data/<symbol>', methods=['POST'])
def add_stock_data(symbol): 
    if 'username' not in session: 
        return redirect(url_for('login'))

    date = request.form.get('date')
    open_price = float(request.form.get('open'))
    high_price = float(request.form.get('high'))
    low_price = float(request.form.get('low'))
    close_price = float(request.form.get('close'))
    volume = int(request.form.get('volume'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # Step 1: Insert or update the stockhistory record
    cursor.execute("""
        INSERT INTO stockhistory (date, symbol, open_price, close_price, high_price, low_price, volume)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (date, symbol) DO UPDATE
        SET open_price = EXCLUDED.open_price,
            close_price = EXCLUDED.close_price,
            high_price = EXCLUDED.high_price,
            low_price = EXCLUDED.low_price,
            volume = EXCLUDED.volume;
    """, (date, symbol, open_price, close_price, high_price, low_price, volume))

    # Step 2: Check if this is the latest date for this symbol
    cursor.execute("""
        SELECT MAX(date) FROM stockhistory WHERE symbol = %s
    """, (symbol,))
    latest_date = cursor.fetchone()[0]

    if str(latest_date) == date:
        cursor.execute("""
            UPDATE stock
            SET current_price = %s
            WHERE symbol = %s
        """, (close_price, symbol))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('view_stock_detail', symbol=symbol))



#######################################################################################
# Portofolio and Watchlist
#######################################################################################
@app.route("/portfolio_watchlist")
def portfolio_watchlist():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session["username"]
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Get all portfolios
    cursor.execute("""
        SELECT pname, cashbalance
        FROM portfolio
        WHERE username = %s
        ORDER BY pname
    """, (username,))
    portfolios = cursor.fetchall()

    # 2. Get portfolio holdings
    portfolio_holdings = {}
    for pname, _ in portfolios:
        cursor.execute("""
            SELECT ph.symbol, ph.qty, NULL AS buy_price, NULL AS timestamp
            FROM portfolioholding ph
            WHERE ph.username = %s AND ph.pname = %s
        """, (username, pname))
        portfolio_holdings[pname] = cursor.fetchall()

    # 3. Get all watchlists
    cursor.execute("""
        SELECT sname
        FROM stocklist_data
        WHERE username = %s
    """, (username,))
    watchlists = cursor.fetchall()

    # 4. Get watchlist holdings
    watchlist_holdings = {}
    for sname, in watchlists:
        cursor.execute("""
            SELECT sh.symbol, NULL AS company_name
            FROM stocklistholding sh
            WHERE sh.username = %s AND sh.sname = %s
        """, (username, sname))
        watchlist_holdings[sname] = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "portfolio_watchlist.html",
        current_user=username,
        portfolios=portfolios,
        portfolio_holdings=portfolio_holdings,
        watchlists=[sname for (sname,) in watchlists],
        watchlist_holdings=watchlist_holdings
    )

# Add new portfolio
@app.route("/add_portfolio", methods=["POST"])
def add_portfolio():
    if "username" not in session:
        return redirect(url_for("login"))

    pname = request.form["portfolio_name"].strip()
    cashbalance = request.form["initial_cash"]
    username = session["username"]

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO portfolio (pname, cashbalance, username)
            VALUES (%s, %s, %s)
        """, (pname, cashbalance, username))
        conn.commit()
        # flash("✅ Portfolio created successfully!", "success")
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        # flash("⚠️ Portfolio name already exists.", "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("portfolio_watchlist"))

@app.route("/delete_portfolio", methods=["POST"])
def delete_portfolio():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    pname = request.form.get("pname")

    if not pname:
        return "Missing portfolio name", 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Delete related holdings and history first if you have foreign key constraints
    cursor.execute("""
        DELETE FROM portfolioholding 
        WHERE username = %s AND pname = %s
    """, (username, pname))

    cursor.execute("""
        DELETE FROM portfoliohistory 
        WHERE username = %s AND pname = %s
    """, (username, pname))

    # Then delete the portfolio itself
    cursor.execute("""
        DELETE FROM portfolio WHERE username = %s AND pname = %s
    """, (username, pname))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("portfolio_watchlist"))

# Add new watchlist
@app.route("/add_watchlist", methods=["POST"])
def add_watchlist():
    if "username" not in session:
        return redirect(url_for("login"))

    sname = request.form["watchlist_name"].strip()
    username = session["username"]

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO stocklist_data (sname, visible, username)
            VALUES (%s, %s, %s)
        """, (sname, 0, username))  # 0 = private
        conn.commit()
        # flash("✅ Watchlist created successfully!", "success")
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        # flash("⚠️ Watchlist name already exists.", "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("portfolio_watchlist"))

@app.route("/delete_watchlist", methods=["POST"])
def delete_watchlist():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    sname = request.form.get("sname")

    if not sname:
        return "Missing watchlist name", 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Delete related holdings first
    cursor.execute("""
        DELETE FROM stocklistholding WHERE username = %s AND sname = %s
    """, (username, sname))

    # Delete any associated reviews
    cursor.execute("""
        DELETE FROM reviews WHERE uname_owner = %s AND sname = %s
    """, (username, sname))

    # Finally, delete the watchlist metadata
    cursor.execute("""
        DELETE FROM stocklist_data WHERE username = %s AND sname = %s
    """, (username, sname))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("portfolio_watchlist"))



# #######################################################################################
# # MY Watchlist
# #######################################################################################
# @app.route('/watchlist_dashboard/<watchlist_name>')
# def watchlist_dashboard(watchlist_name):
#     username = session['username']
#     conn = get_db_connection()
#     cursor = conn.cursor()

#     # Get the stocks in the selected watchlist
#     cursor.execute("""
#         SELECT sh.symbol, s.current_price, sh.qty
#         FROM stocklistholding sh
#         JOIN stock s ON sh.symbol = s.symbol
#         WHERE sh.username = %s AND sh.sname = %s
#     """, (username, watchlist_name))
#     stocks = cursor.fetchall()

#     # Visibility
#     cursor.execute("""
#         SELECT visible FROM stocklist_data
#         WHERE username = %s AND sname = %s
#     """, (username, watchlist_name))
#     visible = cursor.fetchone()
#     visibility_data = visible[0] if visible else 0

#     # Get stock price history
#     portfolio_history = defaultdict(float)

#     for symbol, current_price, qty in stocks:
#         cursor.execute("""
#             SELECT date, close_price
#             FROM stockhistory
#             WHERE symbol = %s AND date BETWEEN '2013-01-01' AND '2018-02-07'
#             ORDER BY date
#         """, (symbol,))
#         for date, close_price in cursor.fetchall():
#             portfolio_history[date] += close_price * qty

#     # Convert to sorted list for JSON
#     history_data = [
#         {'date': d.strftime('%Y-%m-%d'), 'price': round(p, 2)}
#         for d, p in sorted(portfolio_history.items())
#     ]

#     cursor.close()
#     conn.close()

#     return render_template(
#         "watchlist_dashboard.html",
#         watchlist_name=watchlist_name,
#         stocks=stocks,
#         history_data=history_data,
#         visibility_data=visibility_data
#     )


#######################################################################################
# Comment Function
#######################################################################################
@app.route('/submit_comment', methods=['POST'])
def submit_comment():
    if 'username' not in session:
        return redirect(url_for('login'))

    data = request.form
    writer = session['username']
    owner_name = data['owner_name']
    watchlist_name = data['watchlist_name']
    text = data['text']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if the comment exists
    cursor.execute("""
        SELECT 1 FROM reviews
        WHERE sname = %s AND uname_owner = %s AND writer = %s
    """, (watchlist_name, owner_name, writer))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE reviews
            SET text = %s
            WHERE sname = %s AND uname_owner = %s AND writer = %s
        """, (text, watchlist_name, owner_name, writer))
    else:
        cursor.execute("""
            INSERT INTO reviews (sname, uname_owner, writer, text)
            VALUES (%s, %s, %s, %s)
        """, (watchlist_name, owner_name, writer, text))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('watchlist_performance', owner_name=owner_name, watchlist_name=watchlist_name))

@app.route('/delete_comment', methods=['POST'])
def delete_comment():
    if 'username' not in session:
        return redirect(url_for('login'))

    owner_name = request.form.get('owner_name')
    watchlist_name = request.form.get('watchlist_name')
    writer = request.form.get('writer')
    current_user = session['username']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Only allow deletion if the current user wrote the comment or is the list owner
    cursor.execute("""
        SELECT 1 FROM reviews
        WHERE sname = %s AND uname_owner = %s AND writer = %s
    """, (watchlist_name, owner_name, writer))

    comment_exists = cursor.fetchone()

    if not comment_exists and current_user != owner_name:
        cursor.close()
        conn.close()
        return "No permission to delete this comment", 403

    cursor.execute("""
        DELETE FROM reviews
        WHERE sname = %s AND uname_owner = %s AND writer = %s
    """, (watchlist_name, owner_name, writer))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('watchlist_performance', owner_name=owner_name, watchlist_name=watchlist_name))


#######################################################################################
# Watchlist view/dashboard
#######################################################################################
@app.route('/watchlist/<owner_name>/<watchlist_name>')
def watchlist_performance(owner_name, watchlist_name):
    if 'username' not in session:
        return redirect(url_for('login'))

    current_user = session['username']
    is_creator = (current_user == owner_name)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get stocks in the watchlist
    cursor.execute("""
        SELECT sh.symbol, s.current_price, sh.qty
        FROM stocklistholding sh
        JOIN stock s ON sh.symbol = s.symbol
        WHERE sh.username = %s AND sh.sname = %s
    """, (owner_name, watchlist_name))
    stocks = cursor.fetchall()

    # Get interval (default full range)
    start = request.args.get("start")
    end = request.args.get("end")
    cursor.execute("SELECT MIN(date), MAX(date) FROM StockHistory")
    min_date, max_date = cursor.fetchone()
    start = start or min_date.strftime('%Y-%m-%d')
    end = end or max_date.strftime('%Y-%m-%d')

    # Daily portfolio value
    portfolio_history = defaultdict(float)
    for symbol, _, qty in stocks:
        cursor.execute("""
            SELECT date, close_price
            FROM stockhistory
            WHERE symbol = %s AND date BETWEEN %s AND %s
            ORDER BY date
        """, (symbol, start, end))
        for date, close_price in cursor.fetchall():
            portfolio_history[date] += close_price * qty

    history_data = [
        {'date': d.strftime('%Y-%m-%d'), 'price': round(v, 2)}
        for d, v in sorted(portfolio_history.items())
    ]

    # Enhance stock data with beta
    enhanced_stocks = []
    for symbol, current_price, qty in stocks:
        beta = calculate_beta(cursor, symbol, start, end)
        enhanced_stocks.append((symbol, current_price, qty, beta))

    # Covariance matrix
    cov_matrix = calculate_cov_matrix(cursor, [s[0] for s in stocks], start, end)

    # Comments
    cursor.execute("""
        SELECT sname, uname_owner, writer, text, NULL AS timestamp
        FROM reviews
        WHERE uname_owner = %s AND sname = %s
        ORDER BY writer
    """, (owner_name, watchlist_name))
    comments = cursor.fetchall()

    # My comment
    cursor.execute("""
        SELECT text FROM reviews
        WHERE uname_owner = %s AND sname = %s AND writer = %s
        LIMIT 1
    """, (owner_name, watchlist_name, current_user))
    my_comment = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template("watchlist_performance.html",
                           comments=comments,
                           stocks=enhanced_stocks,
                           watchlist_name=watchlist_name,
                           owner_name=owner_name,
                           current_user_id=current_user,
                           history_data=history_data,
                           start=start,
                           end=end,
                           cov_matrix=cov_matrix,
                           my_comment=my_comment)

@app.route("/toggle_visibility", methods=["POST"])
def toggle_visibility():
    if "username" not in session:
        return jsonify({"message": "Please log in first."}), 401

    data = request.get_json()
    watchlist_name = data.get("watchlist_name")
    visibility = data.get("visible")
    username = session["username"]

    if visibility not in [0, 1, 2]:
        return jsonify({"message": "Invalid visibility option."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE stocklist_data
        SET visible = %s
        WHERE username = %s AND sname = %s
    """, (visibility, username, watchlist_name))

    if cursor.rowcount == 0:
        message = "Stocklist not found or you do not have permission to edit it."
        status = 404
    else:
        message = f"Visibility updated to {['Private', 'Friends', 'Public'][visibility]}."
        status = 200

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": message}), status


@app.route('/add_to_watchlist', methods=['POST'])
def add_to_watchlist():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    sname = request.form.get('sname')
    symbol = request.form.get('symbol').upper()
    quantity = int(request.form.get('quantity'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # Validate symbol exists
    cursor.execute("SELECT 1 FROM stock WHERE symbol = %s", (symbol,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return "❌ Symbol does not exist", 400

    # Ensure stocklist exists
    cursor.execute("""
        INSERT INTO stocklist_data (username, sname)
        SELECT %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM stocklist_data WHERE username = %s AND sname = %s
        )
    """, (username, sname, username, sname))

    # Insert or update
    cursor.execute("""
        INSERT INTO stocklistholding (username, sname, symbol, qty)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (username, sname, symbol)
        DO UPDATE SET qty = stocklistholding.qty + EXCLUDED.qty
    """, (username, sname, symbol, quantity))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('watchlist_performance', owner_name=username, watchlist_name=sname))

@app.route('/remove_stock_watchlist', methods=['POST'])
def remove_stock_watchlist():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    sname = request.form.get('sname')
    symbol = request.form.get('symbol')

    conn = get_db_connection()
    cursor = conn.cursor()
    print(username)
    print(sname)

    # 确保该用户拥有这个 watchlist
    cursor.execute("""
        SELECT 1 FROM stocklist_data
        WHERE username = %s AND sname = %s
    """, (username, sname))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return "Watchlist not found or no permission.", 403

    # 删除该股票
    cursor.execute("""
        DELETE FROM stocklistholding
        WHERE username = %s AND sname = %s AND symbol = %s
    """, (username, sname, symbol))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('watchlist_performance', owner_name=username, watchlist_name=sname))


# @app.route('/watchlist/<owner_name>/<watchlist_name>')
# def view_watchlist(owner_name, watchlist_name):
#     if 'username' not in session:
#         return redirect(url_for('login'))

#     current_user = session['username']
#     is_creator = (current_user == owner_name)

#     conn = get_db_connection()
#     cursor = conn.cursor()

#     # 1. Check if the stocklist exists and get visibility
#     cursor.execute("""
#         SELECT visible FROM stocklist_data
#         WHERE username = %s AND sname = %s
#     """, (owner_name, watchlist_name))
#     result = cursor.fetchone()

#     if not result:
#         cursor.close()
#         conn.close()
#         return "❌ Stocklist does not exist", 404

#     visible = result[0]

#     # 2. If private & not creator, check if the current user has written a review
#     if visible == 0 and not is_creator:
#         cursor.execute("""
#             SELECT 1 FROM reviews
#             WHERE writer = %s AND uname_owner = %s AND sname = %s
#             LIMIT 1
#         """, (current_user, owner_name, watchlist_name))
#         has_commented = cursor.fetchone() is not None

#         if not has_commented:
#             cursor.close()
#             conn.close()
#             return "❌ This stocklist is private and you’re not the owner or a reviewer.", 403

#     # 3. Fetch all reviews
#     cursor.execute("""
#         SELECT sname, uname_owner, writer, text, NULL AS timestamp
#         FROM reviews
#         WHERE uname_owner = %s AND sname = %s
#         ORDER BY writer
#     """, (owner_name, watchlist_name))
#     comments = cursor.fetchall()

#     # 4. Check if current user already reviewed (for pre-fill)
#     cursor.execute("""
#         SELECT text FROM reviews
#         WHERE uname_owner = %s AND sname = %s AND writer = %s
#         LIMIT 1
#     """, (owner_name, watchlist_name, current_user))
#     my_comment = cursor.fetchone()

#     cursor.close()
#     conn.close()

#     return render_template(
#         'watchlist_comments.html',
#         comments=comments,
#         watchlist_name=watchlist_name,
#         owner_id=owner_name,
#         current_user_id=current_user,
#         my_comment=my_comment,
#         is_creator=is_creator
#     )

#######################################################################################
# Cash Balance
#######################################################################################
@app.route("/deposit_withdraw", methods=["POST"])
def deposit_withdraw():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    pname = request.form.get("pname")
    action = request.form.get("action")  # "deposit" or "withdraw"
    
    try:
        amount = float(request.form.get("amount"))
    except (TypeError, ValueError):
        return "Invalid amount format.", 400

    if amount <= 0:
        return "Amount must be greater than 0.", 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取当前余额
    cursor.execute("""
        SELECT cashbalance FROM portfolio WHERE username = %s AND pname = %s
    """, (username, pname))
    result = cursor.fetchone()

    if not result:
        cursor.close()
        conn.close()
        return "Portfolio not found.", 404

    current_balance = float(result[0])  # 确保是 float 类型

    # Debug print（可移除）
    print(f"[DEBUG] Action: {action}, Amount: {amount}, Current: {current_balance}")

    # 更新余额
    if action == "deposit":
        new_balance = round(current_balance + amount, 2)
    elif action == "withdraw":
        if amount > current_balance:
            cursor.close()
            conn.close()
            return "Not enough balance to withdraw.", 400
        new_balance = round(current_balance - amount, 2)
    else:
        cursor.close()
        conn.close()
        return "Invalid action.", 400

    # Debug 新余额
    print(f"[DEBUG] New Balance: {new_balance}")

    # 执行更新
    cursor.execute("""
        UPDATE portfolio SET cashbalance = %s WHERE username = %s AND pname = %s
    """, (new_balance, username, pname))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("portfolio_watchlist"))

@app.route("/transfer_between_portfolios", methods=["POST"])
def transfer_between_portfolios():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    from_pname = request.form["from_pname"]
    to_pname = request.form["to_pname"]
    amount = float(request.form["amount"])

    if from_pname == to_pname:
        return "Cannot transfer to the same portfolio", 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取 source portfolio 的余额
    cursor.execute("""
        SELECT cashbalance FROM portfolio
        WHERE username = %s AND pname = %s
    """, (username, from_pname))
    result = cursor.fetchone()

    if not result:
        cursor.close()
        conn.close()
        return "Source portfolio not found", 404

    from_balance = result[0]

    if amount > from_balance:
        cursor.close()
        conn.close()
        return "Insufficient funds", 400

    # 检查目标 portfolio 是否存在
    cursor.execute("""
        SELECT 1 FROM portfolio WHERE username = %s AND pname = %s
    """, (username, to_pname))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return "Target portfolio not found", 404

    # 扣减 source，增加 target
    cursor.execute("""
        UPDATE portfolio SET cashbalance = cashbalance - %s
        WHERE username = %s AND pname = %s
    """, (amount, username, from_pname))
    cursor.execute("""
        UPDATE portfolio SET cashbalance = cashbalance + %s
        WHERE username = %s AND pname = %s
    """, (amount, username, to_pname))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("portfolio_watchlist"))

#######################################################################################
# Portofolio
#######################################################################################
@app.route("/portfolio_dashboard/<pname>")
def portfolio_dashboard(pname):
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    start = request.args.get("start")
    end = request.args.get("end")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Cash balance
    cursor.execute("""
        SELECT cashbalance FROM portfolio WHERE username = %s AND pname = %s
    """, (username, pname))
    result = cursor.fetchone()
    if not result:
        cursor.close()
        conn.close()
        return "Portfolio not found", 404
    cashbalance = result[0]

    # Holdings
    cursor.execute("""
        SELECT ph.symbol, ph.qty, s.current_price
        FROM portfolioholding ph
        JOIN stock s ON ph.symbol = s.symbol
        WHERE ph.username = %s AND ph.pname = %s
    """, (username, pname))
    holdings = cursor.fetchall()

    # Default date range (earliest to latest)
    cursor.execute("SELECT MIN(date), MAX(date) FROM StockHistory")
    min_date, max_date = cursor.fetchone()
    start = start or min_date.strftime('%Y-%m-%d')
    end = end or max_date.strftime('%Y-%m-%d')

    # Compute Betas
    holding_betas = []
    for symbol, qty, price in holdings:
        beta = calculate_beta(cursor, symbol, start, end)
        holding_betas.append((symbol, qty, price, beta))

    # Covariance matrix
    symbols = [h[0] for h in holdings]
    cov_matrix = calculate_cov_matrix(cursor, symbols, start, end)

    # Portfolio value chart (summed daily)
    cursor.execute("""
        SELECT sh.date, SUM(sh.close_price * ph.qty) AS value
        FROM StockHistory sh
        JOIN portfolioholding ph ON sh.symbol = ph.symbol
        WHERE ph.username = %s AND ph.pname = %s
        AND sh.date BETWEEN %s AND %s
        GROUP BY sh.date
        ORDER BY sh.date
    """, (username, pname, start, end))
    chart_data = cursor.fetchall()
    chart_labels = [d.strftime('%Y-%m-%d') for d, _ in chart_data]
    chart_values = [float(v) for _, v in chart_data]

    # History
    cursor.execute("""
        SELECT symbol, qty, timestamp
        FROM portfoliohistory
        WHERE username = %s AND pname = %s
        ORDER BY timestamp DESC
    """, (username, pname))
    history = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("portfolio_dashboard.html",
                           pname=pname,
                           cashbalance=cashbalance,
                           holdings=holding_betas,
                           history=history,
                           start=start,
                           end=end,
                           chart_labels=chart_labels,
                           chart_values=chart_values,
                           cov_matrix=cov_matrix)

@app.route("/buy_stock", methods=["POST"])
def buy_stock():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    pname = request.form["pname"]
    symbol = request.form["symbol"].upper()
    qty = int(request.form["qty"])
    date = request.form["date"]

    conn = get_db_connection()
    cursor = conn.cursor()

    # 优先尝试用指定日期的价格
    cursor.execute("SELECT close_price FROM stockhistory WHERE symbol = %s AND date = %s", (symbol, date))
    row = cursor.fetchone()

    if row:
        price = row[0]
    else:
        cursor.execute("SELECT current_price FROM stock WHERE symbol = %s", (symbol,))
        price = cursor.fetchone()[0]

    total_cost = price * qty

    cursor.execute("SELECT cashbalance FROM portfolio WHERE username = %s AND pname = %s", (username, pname))
    balance = cursor.fetchone()[0]

    if balance < total_cost:
        return "❌ Not enough funds", 400

    cursor.execute("UPDATE portfolio SET cashbalance = cashbalance - %s WHERE username = %s AND pname = %s", (total_cost, username, pname))

    cursor.execute("""
        INSERT INTO portfolioholding (username, pname, symbol, qty)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (pname, username, symbol) DO UPDATE SET qty = portfolioholding.qty + EXCLUDED.qty
    """, (username, pname, symbol, qty))

    cursor.execute("""
        INSERT INTO portfoliohistory (username, pname, symbol, qty, timestamp)
        VALUES (%s, %s, %s, %s, %s)
    """, (username, pname, symbol, qty, date))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("portfolio_dashboard", pname=pname))


@app.route("/sell_stock", methods=["POST"])
def sell_stock():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    pname = request.form["pname"]
    symbol = request.form["symbol"].upper()
    qty = int(request.form["qty"])
    date = request.form["date"]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT qty FROM portfolioholding WHERE username = %s AND pname = %s AND symbol = %s", (username, pname, symbol))
    row = cursor.fetchone()
    if not row or row[0] < qty:
        return "❌ Not enough holdings", 400

    cursor.execute("SELECT close_price FROM stockhistory WHERE symbol = %s AND date = %s", (symbol, date))
    row = cursor.fetchone()

    if row:
        price = row[0]
    else:
        cursor.execute("SELECT current_price FROM stock WHERE symbol = %s", (symbol,))
        price = cursor.fetchone()[0]

    total_value = price * qty

    cursor.execute("UPDATE portfolio SET cashbalance = cashbalance + %s WHERE username = %s AND pname = %s", (total_value, username, pname))
    cursor.execute("UPDATE portfolioholding SET qty = qty - %s WHERE username = %s AND pname = %s AND symbol = %s", (qty, username, pname, symbol))
    cursor.execute("DELETE FROM portfolioholding WHERE username = %s AND pname = %s AND symbol = %s AND qty <= 0", (username, pname, symbol))

    cursor.execute("""
        INSERT INTO portfoliohistory (username, pname, symbol, qty, timestamp)
        VALUES (%s, %s, %s, %s, %s)
    """, (username, pname, symbol, -qty, date))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("portfolio_dashboard", pname=pname))

#######################################################################################
# Stat and Prediction
#######################################################################################
def calculate_beta(cursor, symbol, start, end):
    cursor.execute("""
        SELECT MIN(date), MAX(date) FROM StockHistory
        WHERE symbol = %s
    """, (symbol,))
    minmax = cursor.fetchone()
    start = start or minmax[0]
    end = end or minmax[1]

    # DROP + CREATE temp view instead of IF NOT EXISTS
    cursor.execute("DROP VIEW IF EXISTS MarketReturns")
    cursor.execute("""
        CREATE TEMP VIEW MarketReturns AS
        SELECT
            date,
            (SUM(close_price) - LAG(SUM(close_price)) OVER (ORDER BY date)) / 
            LAG(SUM(close_price)) OVER (ORDER BY date) AS market_return
        FROM StockHistory
        WHERE date BETWEEN %s AND %s
        GROUP BY date
    """, (start, end))
    
    # stock return
    cursor.execute("""
        SELECT 
            date,
            (close_price - LAG(close_price) OVER (ORDER BY date)) / 
            LAG(close_price) OVER (ORDER BY date) AS return
        FROM StockHistory
        WHERE symbol = %s AND date BETWEEN %s AND %s
    """, (symbol, start, end))
    returns = cursor.fetchall()
    stock_returns = {date: r for date, r in returns if r is not None}

    cursor.execute("SELECT date, market_return FROM MarketReturns")
    market = cursor.fetchall()
    market_returns = {date: r for date, r in market if r is not None}

    common_dates = set(stock_returns) & set(market_returns)
    if not common_dates:
        return None
    x = [stock_returns[d] for d in common_dates]
    y = [market_returns[d] for d in common_dates]
    beta = sum(xi * yi for xi, yi in zip(x, y)) / sum(yi**2 for yi in y)
    return round(beta, 4)


def calculate_cov_matrix(cursor, symbols, start, end):
    returns_dict = {}
    for symbol in symbols:
        cursor.execute("""
            SELECT 
                date,
                (close_price - LAG(close_price) OVER (ORDER BY date)) / LAG(close_price) OVER (ORDER BY date) AS return
            FROM StockHistory
            WHERE symbol = %s AND date BETWEEN %s AND %s
        """, (symbol, start, end))
        returns_dict[symbol] = {date: r for date, r in cursor.fetchall() if r is not None}

    # Convert to pandas DataFrame
    df = pd.DataFrame(returns_dict).dropna()
    return df.cov().round(4).to_dict()

def calculate_prediction(cursor, symbol, start, end):
    start_date = pd.to_datetime(start)
    end_date = pd.to_datetime(end)
    forecast_days = (end_date - start_date).days + 1

    # Fetch historical data BEFORE the prediction window
    cursor.execute("""
        SELECT date, close_price
        FROM StockHistory
        WHERE symbol = %s AND date < %s
        ORDER BY date
    """, (symbol, start))
    rows = cursor.fetchall()

    if not rows or len(rows) < 30:
        raise ValueError(f"Insufficient historical data for '{symbol}'. At least 30 records are required.")

    df = pd.DataFrame(rows, columns=['date', 'close_price'])
    df.set_index('date', inplace=True)
    df.index = pd.to_datetime(df.index)

    # 🛠 Fix: Set frequency and fill missing business days
    df = df.asfreq('B')  # business day frequency
    df['close_price'] = df['close_price'].astype(float)
    df['close_price'] = df['close_price'].ffill()

    try:
        model = auto_arima(df['close_price'], 
                        start_p=1, start_q=1,
                        max_p=5, max_q=5,
                        seasonal=False,
                        stepwise=True, 
                        suppress_warnings=True, 
                        error_action="ignore")
        forecast = model.predict(n_periods=forecast_days)
        # Recreate future business dates aligned to start
        future_dates = pd.bdate_range(start=start_date, periods=forecast_days)
        predicted_series = list(zip(
            [d.strftime('%Y-%m-%d') for d in future_dates],
            forecast.round(2).tolist()
        ))

        return predicted_series

    except Exception as e:
        raise RuntimeError(f"ARIMA prediction failed for {symbol}: {e}")
#######################################################################################
# Logout
#######################################################################################
# 📌 用户登出
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True,port=5001)