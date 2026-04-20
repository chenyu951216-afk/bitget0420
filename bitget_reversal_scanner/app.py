import os
import threading
from flask import Flask, render_template, jsonify
from scanner import run_scanner, get_latest_results, get_latest_signals

app = Flask(__name__)

# ================================
# Web UI
# ================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/results")
def api_results():
    return jsonify(get_latest_results())

@app.route("/api/signals")
def api_signals():
    return jsonify(get_latest_signals())

# ================================
# 啟動掃描器（重點修復）
# ================================

def start_scanner():
    print("🔥 Scanner thread started")
    run_scanner()

# ================================
# Main
# ================================

if __name__ == "__main__":
    print("🚀 App starting...")

    # ✅ 啟動背景掃描器
    t = threading.Thread(target=start_scanner, daemon=True)
    t.start()

    # ✅ 啟動 Web Server（Zeabur 需要）
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
