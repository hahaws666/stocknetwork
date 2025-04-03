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

    # 🔹 4. Get accessible stocklists (public, friends, shared via comment)
    cursor.execute("""
        SELECT DISTINCT s.username, s.sname
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
        public_stocklists=[(row[0], row[1]) for row in public_stocklists],  # mock (owner_name, list_name)
        current_user=current_username,
        current_user_id=current_username,
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


#######################################################################################
# STOCK FUNCTION
#######################################################################################
@app.route('/search_stock', methods=['GET', 'POST'])
def search_stock():
    results = []

    if request.method == 'POST':
        keyword = request.form.get('keyword')
        conn = get_db_connection()
        cursor = conn.cursor()

        # 使用 SQL LIKE 进行模糊匹配
        cursor.execute("""
            SELECT symbol, NULL AS company_name, current_price 
            FROM stock 
            WHERE symbol ILIKE %s
        """, (f"%{keyword}%",))

        results = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template('search_stock.html', results=results)

@app.route("/add_to_watchlist", methods=["POST"])
def add_to_watchlist():
    data = request.get_json()
    symbol = data["symbol"]
    sname = data["watchlistname"]
    qty = int(data.get("quantity", 1))  # fallback to 1 if not sent
    username = session.get("username")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Create watchlist if doesn't exist
    cursor.execute("""
        INSERT INTO stocklist_data (username, sname)
        SELECT %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM stocklist_data WHERE username = %s AND sname = %s
        )
    """, (username, sname, username, sname))

    # Add stock to watchlist
    cursor.execute("""
        INSERT INTO stocklistholding (username, sname, symbol, qty)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (sname, username, symbol) DO UPDATE SET qty = stocklistholding.qty + EXCLUDED.qty
    """, (username, sname, symbol, qty))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": f"Added {symbol} (qty: {qty}) to {sname}."})


@app.route("/add_to_portfolio", methods=["POST"])
def add_to_portfolio():
    data = request.get_json()
    symbol = data["symbol"]
    pname = data["pname"]
    qty = int(data["qty"])
    username = session.get("username")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Ensure portfolio exists
    cursor.execute("""
        INSERT INTO portfolio (username, pname, cashbalance)
        SELECT %s, %s, 0
        WHERE NOT EXISTS (
            SELECT 1 FROM portfolio WHERE username = %s AND pname = %s
        );
    """, (username, pname, username, pname))

    # Update/Add to holding
    cursor.execute("""
        INSERT INTO portfolioholding (username, pname, symbol, qty)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (pname, username, symbol)
        DO UPDATE SET qty = portfolioholding.qty + EXCLUDED.qty;
    """, (username, pname, symbol, qty))

    # Log history
    cursor.execute("""
        INSERT INTO portfoliohistory (username, pname, symbol, qty)
        VALUES (%s, %s, %s, %s);
    """, (username, pname, symbol, qty))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": f"Added {qty} of {symbol} to portfolio '{pname}'."})


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
    """, (username,))
    portfolios = cursor.fetchall()

    # 2. Get portfolio holdings
    portfolio_holdings = {}
    for pname, _ in portfolios:
        cursor.execute("""
            SELECT ph.symbol, NULL AS company_name, ph.qty, NULL AS buy_price, NULL AS timestamp
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

@app.route('/watchlist_dashboard/<watchlist_name>')
def watchlist_dashboard(watchlist_name):
    username = session['username']
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get the stocks in the selected watchlist
    cursor.execute("""
        SELECT sh.symbol, s.current_price, sh.qty
        FROM stocklistholding sh
        JOIN stock s ON sh.symbol = s.symbol
        WHERE sh.username = %s AND sh.sname = %s
    """, (username, watchlist_name))
    stocks = cursor.fetchall()

    # Visibility
    cursor.execute("""
        SELECT visible FROM stocklist_data
        WHERE username = %s AND sname = %s
    """, (username, watchlist_name))
    visible = cursor.fetchone()
    visibility_data = visible[0] if visible else 0

    # Get stock price history
    history_data = {}
    for symbol, _, _ in stocks:
        cursor.execute("""
            SELECT date, close_price
            FROM stockhistory
            WHERE symbol = %s AND date BETWEEN '2013-01-01' AND '2018-02-07'
            ORDER BY date
        """, (symbol,))
        history_data[symbol] = [
            {'date': r[0].strftime('%Y-%m-%d'), 'price': r[1]}
            for r in cursor.fetchall()
        ]

    cursor.close()
    conn.close()

    return render_template(
        "watchlist_dashboard.html",
        watchlist_name=watchlist_name,
        stocks=stocks,
        history_data=history_data,
        visibility_data=visibility_data
    )

@app.route('/watchlist/<owner_name>/<watchlist_name>')
def view_watchlist(owner_name, watchlist_name):
    if 'username' not in session:
        return redirect(url_for('login'))

    current_user = session['username']
    is_creator = (current_user == owner_name)

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Check if the stocklist exists and get visibility
    cursor.execute("""
        SELECT visible FROM stocklist_data
        WHERE username = %s AND sname = %s
    """, (owner_name, watchlist_name))
    result = cursor.fetchone()

    if not result:
        cursor.close()
        conn.close()
        return "❌ Stocklist does not exist", 404

    visible = result[0]

    # 2. If private & not creator, check if the current user has written a review
    if visible == 0 and not is_creator:
        cursor.execute("""
            SELECT 1 FROM reviews
            WHERE writer = %s AND uname_owner = %s AND sname = %s
            LIMIT 1
        """, (current_user, owner_name, watchlist_name))
        has_commented = cursor.fetchone() is not None

        if not has_commented:
            cursor.close()
            conn.close()
            return "❌ This stocklist is private and you’re not the owner or a reviewer.", 403

    # 3. Fetch all reviews
    cursor.execute("""
        SELECT sname, uname_owner, writer, text, NULL AS timestamp
        FROM reviews
        WHERE uname_owner = %s AND sname = %s
        ORDER BY writer
    """, (owner_name, watchlist_name))
    comments = cursor.fetchall()

    # 4. Check if current user already reviewed (for pre-fill)
    cursor.execute("""
        SELECT text FROM reviews
        WHERE uname_owner = %s AND sname = %s AND writer = %s
        LIMIT 1
    """, (owner_name, watchlist_name, current_user))
    my_comment = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        'watchlist_comments.html',
        comments=comments,
        watchlist_name=watchlist_name,
        owner_id=owner_name,
        current_user_id=current_user,
        my_comment=my_comment,
        is_creator=is_creator
    )

#######################################################################################
# Comment Function
#######################################################################################
@app.route('/submit_comment', methods=['POST'])
def submit_comment():
    if 'username' not in session:
        return redirect(url_for('login'))

    data = request.form
    writer = session['username']
    owner_name = data['owner_id']
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

    return redirect(url_for('view_watchlist', owner_name=owner_name, watchlist_name=watchlist_name))

@app.route('/delete_comment', methods=['POST'])
def delete_comment():
    if 'username' not in session:
        return redirect(url_for('login'))

    data = request.form  # Assuming form submission, not JS fetch
    owner_name = data['owner_name']
    watchlist_name = data['watchlist_name']
    current_user = session['username']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get writer + check permission
    cursor.execute("""
        SELECT writer FROM reviews
        WHERE sname = %s AND uname_owner = %s AND writer = %s
    """, (watchlist_name, owner_name, current_user))
    comment = cursor.fetchone()

    if not comment and current_user != owner_name:
        return "No permission to delete this comment", 403

    cursor.execute("""
        DELETE FROM reviews
        WHERE sname = %s AND uname_owner = %s AND writer = %s
    """, (watchlist_name, owner_name, current_user))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('view_watchlist', owner_name=owner_name, watchlist_name=watchlist_name))


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


@app.route('/watchlist/<owner_name>/<watchlist_name>/performance')
def watchlist_performance(owner_name, watchlist_name):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sh.symbol, NULL AS company_name, s.current_price, sh.qty
        FROM stocklistholding sh
        JOIN stock s ON sh.symbol = s.symbol
        WHERE sh.username = %s AND sh.sname = %s
    """, (owner_name, watchlist_name))
    stocks = cursor.fetchall()

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
                           owner_name=owner_name,
                           history_data=history_data)


# 📌 用户登出
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True,port=5001)