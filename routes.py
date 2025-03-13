from flask import Flask, request, jsonify
from models import db, User, Portfolio, StockHolding

app = Flask(__name__)

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    user = User(username=data['username'], email=data['email'], password=data['password'])
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "User registered successfully"}), 201

@app.route('/portfolio/<int:user_id>', methods=['GET'])
def get_portfolio(user_id):
    portfolio = Portfolio.query.filter_by(user_id=user_id).first()
    if not portfolio:
        return jsonify({"message": "Portfolio not found"}), 404
    return jsonify({"user_id": portfolio.user_id, "cash_balance": portfolio.cash_balance})

if __name__ == '__main__':
    app.run(debug=True)
