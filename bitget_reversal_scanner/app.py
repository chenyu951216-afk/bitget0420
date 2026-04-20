from __future__ import annotations

import os
import threading
import time
from flask import Flask, jsonify, render_template

import config
from scanner import BitgetReversalScanner

app = Flask(__name__)

scanner: BitgetReversalScanner | None = None
scanner_thread_started = False
scanner_lock = threading.Lock()


def log(msg: str) -> None:
    print(f"[app] {msg}", flush=True)


def ensure_scanner_started() -> None:
    global scanner, scanner_thread_started

    with scanner_lock:
        if scanner is None:
            log("creating BitgetReversalScanner()")
            scanner = BitgetReversalScanner()

        if not scanner_thread_started:
            log("starting scanner background thread")
            scanner.start_background()
            scanner_thread_started = True
            log("scanner background thread started")


# Flask 3 以前/以後都盡量相容
@app.before_request
def _warmup_scanner() -> None:
    if not scanner_thread_started:
        ensure_scanner_started()


@app.route("/")
def index():
    ensure_scanner_started()
    return render_template(
        "index.html",
        market_type=config.MARKET_TYPE,
        quote=config.QUOTE,
        top_n=config.TOP_N,
        min_change_pct=config.MIN_24H_CHANGE_PCT,
        scan_interval_sec=config.SCAN_INTERVAL_SEC,
        min_score=config.MIN_REVERSAL_SCORE,
    )


@app.route("/health")
def health():
    ensure_scanner_started()
    return jsonify(
        {
            "ok": True,
            "scanner_started": scanner_thread_started,
            "port": int(os.environ.get("PORT", config.APP_PORT)),
            "time": int(time.time()),
        }
    )


@app.route("/api/state")
def api_state():
    ensure_scanner_started()
    return jsonify(scanner.get_state() if scanner else {"error": "scanner not initialized"})


@app.route("/api/scan-now")
def api_scan_now():
    ensure_scanner_started()
    if not scanner:
        return jsonify({"error": "scanner not initialized"}), 500
    state = scanner.scan_once()
    return jsonify(state)


def bootstrap() -> None:
    log("bootstrap start")
    log(f"PORT env = {os.environ.get('PORT')}")
    ensure_scanner_started()
    log("bootstrap done")


bootstrap()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", config.APP_PORT))
    log(f"__main__ start, binding 0.0.0.0:{port}")
    ensure_scanner_started()
    app.run(host="0.0.0.0", port=port, debug=False)
