#!/usr/bin/env python3
"""Push new smzdm deals via hermes webhook with HMAC-SHA256 signature."""
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
import urllib.request

DB_PATH = "database.db"

# Hermes webhook endpoint
WEBHOOK_URL = os.environ.get(
    "HERMES_WEBHOOK_URL",
    "http://37.114.52.247:8644/webhooks/smzdm"
)
WEBHOOK_SECRET = os.environ.get("HERMES_WEBHOOK_SECRET", "smzdm_hmac_secret_2026")


def sign_payload(payload_bytes: bytes, secret: str, timestamp: str) -> str:
    """Generate HMAC-SHA256 signature for webhook payload."""
    signed_data = f"{timestamp}:{payload_bytes.decode('utf-8')}"
    return hmac.new(
        secret.encode('utf-8'),
        signed_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def send_webhook(message: str) -> bool:
    """Send message to hermes webhook endpoint."""
    payload = json.dumps({"message": message}).encode('utf-8')
    timestamp = str(int(time.time()))
    signature = sign_payload(payload, WEBHOOK_SECRET, timestamp)

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature-V2": f"t={timestamp},v2={signature}",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.getcode()
            body = resp.read().decode('utf-8')
            return status == 200
    except Exception as e:
        print(f"Webhook error: {e}", file=sys.stderr)
        return False


def main():
    if not os.path.exists(DB_PATH):
        print("No database.db found, skipping")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM ZDM WHERE pushed = 0 ORDER BY article_time DESC LIMIT 20"
    )
    rows = cur.fetchall()

    if not rows:
        print("No new articles to push")
        conn.close()
        return

    sent = 0
    for row in rows:
        title = row["article_title"]
        price = row.get("article_price", "")
        link = row.get("article_url", "")
        mall = row.get("article_mall", "")
        voted = row.get("article_voted", 0)

        msg = "🛒 可悠然好价推送\n"
        msg += "━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📦 {title}\n"
        if price:
            msg += f"💰 {price}\n"
        if mall:
            msg += f"🏪 {mall}\n"
        if voted:
            msg += f"👍 {voted}人觉得值\n"
        if link:
            msg += f"🔗 {link}\n"

        ok = send_webhook(msg)
        if ok:
            sent += 1
            print(f"✅ Sent: {title[:40]}...")
        else:
            print(f"❌ Failed: {title[:40]}...")

        cur.execute(
            "UPDATE ZDM SET pushed = 1 WHERE article_id = ?",
            (row["article_id"],)
        )

    conn.commit()
    conn.close()
    print(f"\nSent {sent}/{len(rows)} articles")


if __name__ == "__main__":
    main()
