"""
Gunicorn configuration for Render deployment.

With YOLO running on HF Space instead of locally, memory usage
is much lower.  We keep 1 worker and a generous timeout for the
remote HF Space API calls.
"""
import os

# ── Workers ──────────────────────────────────────────────────
# 1 worker is fine for Render free tier (512 MB RAM).
workers = int(os.getenv("WEB_CONCURRENCY", "1"))

# ── Timeout ──────────────────────────────────────────────────
# HF Space calls (upload + predict + SSE) can take up to ~60s
# when the Space is waking from sleep.  120s gives headroom.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))

# ── Bind ─────────────────────────────────────────────────────
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# ── Logging ──────────────────────────────────────────────────
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
