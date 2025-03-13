
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt

app = Flask(__name__, template_folder="templates")
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:yourpassword@localhost/stock_network'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key'  # 用于存储 session

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# 📌 用户模型
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

# 📌 好友请求模型
class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)

# 📌 创建数据库表
with app.app_context():
    db.create_all()

# 📌 用户注册
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')

        user = User(username=data['username'], email=data['email'], password=hashed_password)
        db.session.add(user)
        db.session.commit()

        return redirect(url_for('login'))

    return render_template('register.html')

# 📌 用户登录
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.form
        user = User.query.filter_by(email=data['email']).first()

        if user and bcrypt.check_password_hash(user.password, data['password']):
            session['user_id'] = user.id  # 存储用户 ID
            session['username'] = user.username  # 存储用户名
            return redirect(url_for('welcome'))  # 登录成功后跳转到 welcome 页面
        return "登录失败，请检查邮箱或密码！"

    return render_template('login.html')

# 主页
@app.route('/')
def home():
    return render_template('index.html')

# 📌 Welcome 页面（显示所有用户）
@app.route('/welcome')
def welcome():
    if 'user_id' not in session:  # 如果用户未登录，跳转到登录页面
        return redirect(url_for('login'))

    users = User.query.all()
    print(users)
    return render_template('welcome.html', users=users, current_user=session['username'], current_user_id=session['user_id'])

# 📌 发送好友请求
@app.route('/send_friend_request', methods=['POST'])
def send_friend_request():
    if 'user_id' not in session:
        return jsonify({"message": "请先登录"}), 401

    data = request.json
    sender_id = session['user_id']  # 从 session 获取当前用户 ID
    receiver_id = data.get("receiver_id")

    if sender_id == receiver_id:
        return jsonify({"message": "不能添加自己为好友"}), 400

    existing_request = FriendRequest.query.filter_by(sender_id=sender_id, receiver_id=receiver_id).first()
    if existing_request:
        return jsonify({"message": "好友请求已发送"}), 400

    friend_request = FriendRequest(sender_id=sender_id, receiver_id=receiver_id)
    db.session.add(friend_request)
    db.session.commit()

    return jsonify({"message": "好友请求已发送"}), 201

# 📌 用户登出
@app.route('/logout')
def logout():
    session.clear()  # 清空 session
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
