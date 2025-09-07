from flask import Flask, request, jsonify, current_app
from flask_cors import CORS
import requests
import threading
import time
import json
import ssl
import sys
import traceback
import os
import mysql.connector
from urllib3.util.ssl_ import create_urllib3_context
from datetime import datetime

app = Flask(__name__)
CORS(app)

# MySQL config
DB_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', 'localhost'),
    'user': os.environ.get('MYSQL_USER', 'flaskuser'),
    'password': os.environ.get('MYSQL_PASSWORD', 'flaskpassword'),
    'database': os.environ.get('MYSQL_DATABASE', 'flaskdb')
}

# SSL config
ctx = create_urllib3_context()
ctx.options |= ssl.OP_NO_SSLv2
ctx.options |= ssl.OP_NO_SSLv3
ctx.options |= ssl.OP_NO_TLSv1
ctx.options |= ssl.OP_NO_TLSv1_1

class ModernSSLAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

# Polling status tracker
polling_status = {
    'isActive': False,
    'frequency': 0,
    'remainingTime': 0,
    'end_time': 0,
    'thread': None
}

# Create table if not exists
def initialize_database():
    db_name = os.environ.get('MYSQL_DATABASE')

    try:
        # Step 1: Connect without specifying database
        conn = mysql.connector.connect(
            host=os.environ.get('MYSQL_HOST'),
            user=os.environ.get('MYSQL_USER'),
            password=os.environ.get('MYSQL_PASSWORD')
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
        print(f"✅ Database '{db_name}' exists or created")
        cursor.close()
        conn.close()


        # Step 2: Reconnect using database name
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_responses (
                id INT AUTO_INCREMENT PRIMARY KEY,
                data TEXT NOT NULL,
                activity VARCHAR(256),
                type VARCHAR(100),
                participants INT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Table 'api_responses' is ready")
        return True

    except mysql.connector.Error as err:
        print(f"🔴 DB init error: {err}")
        return False

# Ensure DB is ready on startup
if not initialize_database():
    print("🔴 Failed to initialize database, exiting.")
    sys.exit(1)
    
# Insert into MySQL
def insert_into_db(data_dict):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO api_responses (data, activity, type, participants, timestamp)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            json.dumps(data_dict),
            data_dict.get('activity') or data_dict.get('uid', 'No activity'),
            data_dict.get('type', 'unknown'),
            data_dict.get('participants', 1),
            datetime.utcnow()
        ))
        conn.commit()
        print("✅ Inserted:", cursor.lastrowid)
        cursor.close()
        conn.close()
    except Exception as e:
        print("🔴 DB insert failed:", str(e))
        
def poll_api(endpoint, frequency, duration):
    print("🟢 poll_api thread started")
    polling_status["end_time"] = time.time() + duration

    # interval = duration / frequency  # time between each call

    for i in range(duration*frequency):
        if not polling_status["isActive"]:
            break
        try:
            print(f"🔁 Calling ({i + 1}/{frequency}):", endpoint)
            r = requests.get(endpoint, timeout=5)
            r.raise_for_status()

            content_type = r.headers.get("Content-Type", "")
            if "json" in content_type:
                data = r.json()
            else:
                data = {"uid": r.text.strip()}

            print("📦 Received:", data)
            insert_into_db(data)

        except Exception as e:
            print("🔴 Polling error:", str(e))

        # if i < frequency - 1:
        #     time.sleep(interval)

    polling_status["isActive"] = False
    polling_status["remainingTime"] = 0
    print("🛑 Polling ended")



# Routes

@app.route('/health', methods=['GET'])
def health_check():
    return {'status': 'ok'}, 200

@app.route("/api/start", methods=["POST"])
def start_polling():
    if polling_status["isActive"]:
        return jsonify({"error": "Already polling"}), 400

    data = request.get_json()
    endpoint = data.get("endpoint")
    frequency = int(data.get("frequency", 2))
    duration = int(data.get("duration", 10))

    polling_status["isActive"] = True
    thread = threading.Thread(target=poll_api, args=(endpoint, frequency, duration), daemon=True)
    polling_status["thread"] = thread
    thread.start()
    return jsonify({"message": "Polling started"})


@app.route('/api/stop', methods=['POST'])
def stop_polling():
    try:
        polling_status['isActive'] = False
        if polling_status['thread']:
            polling_status['thread'].join(timeout=5)
        return jsonify({"message": "Polling stopped"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    if polling_status['isActive']:
        remaining = max(0, int(polling_status['end_time'] - time.time()))
        polling_status['remainingTime'] = remaining
    return jsonify({
        "isActive": polling_status['isActive'],
        "frequency": polling_status['frequency'],
        "remainingTime": polling_status['remainingTime'],
        "currentLoop": polling_status.get('currentLoop', 0),
        "totalLoops": polling_status.get('totalLoops', 0)

    })


@app.route('/api/data', methods=['GET'])
def get_data():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM api_responses ORDER BY timestamp DESC")
        results = cursor.fetchall()
        cursor.close()
        conn.close()

        for r in results:
            r['data'] = json.loads(r['data'])
            r['timestamp'] = r['timestamp'].isoformat()

        return jsonify(results)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Database fetch failed"}), 500

@app.route('/api/clear', methods=['DELETE'])
def clear_data():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM api_responses")
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "All records deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/test-call', methods=['GET'])
def test_call():
    import requests
    try:
        r = requests.get("https://lorem-api.com/api/uid", timeout=5)
        return jsonify({"status": "success", "response": r.text})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
