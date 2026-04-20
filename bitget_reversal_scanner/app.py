from __future__ import annotations

from flask import Flask, jsonify, render_template

import config
from scanner import BitgetReversalScanner

app = Flask(__name__)
scanner = BitgetReversalScanner()
scanner.start_background()


@app.route("/")
def index():
    return render_template(
        "index.html",
        market_type=config.MARKET_TYPE,
        quote=config.QUOTE,
        top_n=config.TOP_N,
        min_change_pct=config.MIN_24H_CHANGE_PCT,
        scan_interval_sec=config.SCAN_INTERVAL_SEC,
        min_score=config.MIN_REVERSAL_SCORE,
    )


@app.route("/api/state")
def api_state():
    return jsonify(scanner.get_state())


@app.route("/api/scan-now")
def api_scan_now():
    state = scanner.scan_once()
    return jsonify(state)


if __name__ == "__main__":
    app.run(host=config.APP_HOST, port=config.APP_PORT, debug=config.DEBUG)
