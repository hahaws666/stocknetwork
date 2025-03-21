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

    # 创建 friend_request 表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS friend_request (
        id SERIAL PRIMARY KEY,
        sender_id INT NOT NULL,
        receiver_id INT NOT NULL,
        status VARCHAR(20) DEFAULT 'pending' NOT NULL,
        FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    # cursor.execute("DROP TABLE IF EXISTS friends CASCADE;")

    # 📌 创建 friends 表，存储已接受的好友关系
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS friends (
        user1_id INT NOT NULL,
        user2_id INT NOT NULL,
        approved BOOLEAN DEFAULT FALSE,
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

    # 所有其他用户（可用于发送请求）
    cursor.execute("SELECT id, username FROM users;")
    users = cursor.fetchall()

    # 收到的好友请求（pending）
    cursor.execute("""
        SELECT users.id, users.username FROM friends
        JOIN users ON friends.user1_id = users.id
        WHERE friends.user2_id = %s AND friends.approved = FALSE;
    """, (session['user_id'],))
    friend_requests = cursor.fetchall()

    # 📌 所有已经通过的好友（双向考虑）
    cursor.execute("""
        SELECT DISTINCT u.id, u.username FROM friends f
        JOIN users u ON 
            (u.id = f.user1_id AND f.user2_id = %s) OR 
            (u.id = f.user2_id AND f.user1_id = %s)
        WHERE f.approved = TRUE;
    """, (session['user_id'], session['user_id']))
    friends = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'welcome.html',
        users=users,
        friend_requests=friend_requests,
        friends=friends,
        current_user=session['username'],
        current_user_id=session['user_id']
    )



@app.route('/send_friend_request', methods=['POST'])
def send_friend_request():
    if 'user_id' not in session:
        return jsonify({"message": "请先登录"}), 401

    data = request.json
    sender_id = session['user_id']
    receiver_id = data.get("receiver_id")

    if sender_id == receiver_id:
        return jsonify({"message": "不能添加自己为好友"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # 检查是否已有好友请求
    cursor.execute("SELECT * FROM friends WHERE  user1_id = %s AND user2_id  = %s;", (sender_id, receiver_id))
    existing_request = cursor.fetchone()

    if existing_request:
        cursor.close()
        conn.close()
        return jsonify({"message": "好友请求已存在"}), 400

    # **在 friends 表中插入好友请求，approved = FALSE**
    cursor.execute("INSERT INTO friends (user1_id , user2_id , approved) VALUES (%s, %s, FALSE);", (sender_id, receiver_id))
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": "好友请求已发送"}), 201


@app.route('/respond_friend_request', methods=['POST'])
def respond_friend_request():
    if 'user_id' not in session:
        return jsonify({"message": "请先登录"}), 401

    data = request.json
    sender_id = data.get("sender_id")
    action = data.get("action")  # "accept" or "reject"

    conn = get_db_connection()
    cursor = conn.cursor()

    if action == "accept":
        cursor.execute("UPDATE friends SET approved = TRUE WHERE user1_id  = %s AND user2_id  = %s;",
                       (sender_id, session['user_id']))
    elif action == "reject":
        cursor.execute("DELETE FROM friends WHERE user1_id  = %s AND user2_id  = %s;",
                       (sender_id, session['user_id']))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"message": f"好友请求已{action}"}), 200



# 📌 用户登出
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
