#!/usr/bin/env python3
"""Push new smzdm deals via hermes send."""
import os, sqlite3, subprocess, sys

DB_PATH = "database.db"
HERMES_BIN = os.path.expanduser("~/.venv/bin/hermes")
QQBOT_TARGET = "qqbot:2EC9F7D14F9F058E56D5C0A8D36A708B"
os.environ["QQBOT_HOME_CHANNEL"] = "2EC9F7D14F9F058E56D5C0A8D36A708B"

def send_msg(text: str):
    result = subprocess.run(
        [HERMES_BIN, "send", "--to", QQBOT_TARGET, text],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode == 0, result.stdout + result.stderr

def main():
    if not os.path.exists(DB_PATH):
        print("No database.db found, skipping")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM ZDM WHERE pushed = 0 ORDER BY article_time DESC LIMIT 20")
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

        msg = f"🛒 可悠然好价推送\n"
        msg += f"━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📦 {title}\n"
        if price:
            msg += f"💰 {price}\n"
        if mall:
            msg += f"🏪 {mall}\n"
        if voted:
            msg += f"👍 {voted}人觉得值\n"
        if link:
            msg += f"🔗 {link}\n"

        ok, out = send_msg(msg)
        if ok:
            sent += 1
            print(f"✅ Sent: {title[:40]}...")
        else:
            print(f"❌ Failed: {title[:40]}... {out[:100]}")

        cur.execute("UPDATE ZDM SET pushed = 1 WHERE article_id = ?", (row["article_id"],))

    conn.commit()
    conn.close()
    print(f"\nSent {sent}/{len(rows)} articles")

if __name__ == "__main__":
    main()
