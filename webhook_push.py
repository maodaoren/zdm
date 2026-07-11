#!/usr/bin/env python3
"""Push new smzdm deals to Hermes webhook via HMAC-signed POST."""
import hashlib, hmac, json, os, sqlite3, sys, urllib.request, urllib.error

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "http://37.114.52.247:8644/webhooks/smzdm-deals")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DB_PATH = "database.db"

def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

def push(deal: dict):
    body = json.dumps(deal, ensure_ascii=False).encode()
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code

def main():
    if not WEBHOOK_SECRET:
        print("WARN: WEBHOOK_SECRET not set, skipping", file=sys.stderr)
        return

    if not os.path.exists(DB_PATH):
        print("No database.db found, skipping", file=sys.stderr)
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get recently pushed articles (pushed=1 means already sent via email, check for new unpushed)
    cur.execute("SELECT * FROM ZDM WHERE pushed = 0 ORDER BY timesort DESC LIMIT 20")
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
        comments = row.get("article_comments", 0)

        payload = {
            "title": title,
            "price": price,
            "link": link,
            "mall": mall,
            "voted": voted,
            "comments": comments,
            "source": "smzdm",
        }

        status = push(payload)
        if 200 <= status < 300:
            sent += 1
            print(f"✅ Pushed: {title[:40]}... ({price})")
        else:
            print(f"❌ Failed ({status}): {title[:40]}...")

        # Mark as pushed
        cur.execute("UPDATE ZDM SET pushed = 1 WHERE article_id = ?", (row["article_id"],))

    conn.commit()
    conn.close()
    print(f"\nPushed {sent}/{len(rows)} articles to webhook")

if __name__ == "__main__":
    main()
