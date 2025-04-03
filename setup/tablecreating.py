import psycopg2

conn = psycopg2.connect(
    dbname="stock_network",
    user="postgres",
    password="postgres",  
    host="localhost",
    port="5432"
)

cursor = conn.cursor()

###########################################################
# Stock Data
###########################################################
cursor.execute("""
    CREATE TABLE IF NOT EXISTS Stock (
        symbol VARCHAR(10) PRIMARY KEY,
        current_price FLOAT
    );
""")

cursor.execute("""
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
""")

###########################################################
# User Data
###########################################################
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username VARCHAR(100) UNIQUE NOT NULL,
        password VARCHAR(200) NOT NULL,
        PRIMARY KEY (username)
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS friends (
        username1 VARCHAR(100) NOT NULL,
        username2 VARCHAR(100) NOT NULL,
        status INT NOT NULL CHECK (status IN (-1, 0, 1)),  -- -1: Rejected, 0: Pending, 1: Friend
        timestamp TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY (username1, username2),
        FOREIGN KEY (username1) REFERENCES users(username) ON DELETE CASCADE,
        FOREIGN KEY (username2) REFERENCES users(username) ON DELETE CASCADE
    );
""")

###########################################################
# Portfolio Data
###########################################################
cursor.execute("""
    CREATE TABLE IF NOT EXISTS portfolio (
        pname VARCHAR(100),
        cashbalance FLOAT NOT NULL,
        username VARCHAR(100) REFERENCES users(username) ON DELETE CASCADE,
        PRIMARY KEY (pname, username)
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS portfolioholding (
        pname VARCHAR(100),
        username VARCHAR(100),             
        symbol VARCHAR(10),
        qty INT NOT NULL,
        PRIMARY KEY (pname, username, symbol),
        FOREIGN KEY (pname, username) REFERENCES portfolio(pname, username) ON DELETE CASCADE,
        FOREIGN KEY (symbol) REFERENCES stock(symbol) ON DELETE CASCADE
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS portfoliohistory (
        pname VARCHAR(100),
        username VARCHAR(100),             
        symbol VARCHAR(10),
        qty INT NOT NULL,
        timestamp TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY (pname, username, timestamp),
        FOREIGN KEY (pname, username) REFERENCES portfolio(pname, username) ON DELETE CASCADE,
        FOREIGN KEY (symbol) REFERENCES stock(symbol) ON DELETE CASCADE
    );
""")

###########################################################
# Stocklist Data
###########################################################
cursor.execute("""
    CREATE TABLE IF NOT EXISTS stocklist_data (
        sname VARCHAR(100),
        visible INT NOT NULL DEFAULT 0 CHECK (visible IN (0, 1, 2)),  -- 0: private, 1: shared, 2: public
        username VARCHAR(100) REFERENCES users(username) ON DELETE CASCADE,
        PRIMARY KEY (sname, username)
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS stocklistholding (
        sname VARCHAR(100),
        username VARCHAR(100),             
        symbol VARCHAR(10),
        qty INT NOT NULL,
        PRIMARY KEY (sname, username, symbol),
        FOREIGN KEY (sname, username) REFERENCES stocklist_data(sname, username) ON DELETE CASCADE,
        FOREIGN KEY (symbol) REFERENCES stock(symbol) ON DELETE CASCADE
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        sname VARCHAR(100),
        uname_owner VARCHAR(100),
        writer VARCHAR(100),
        text VARCHAR(4000) NOT NULL,
        PRIMARY KEY (sname, uname_owner, writer),
        FOREIGN KEY (sname, uname_owner) REFERENCES stocklist_data(sname, username) ON DELETE CASCADE,
        FOREIGN KEY (writer) REFERENCES users(username) ON DELETE CASCADE
    );
""")


conn.commit()
cursor.close()
conn.close()

print("[DONE] Table Created")
