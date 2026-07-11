#!/usr/bin/env python3
"""Push new smzdm deals via hermes webhook with HMAC-SHA256 V2 signature."""
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request

DB_PATH = "database.db"

WEBHOOK_URL = os.environ.get(
    "HERMES_WEBHOOK_URL",
    "http://37.114.52.247:8644/webhooks/smzdm"
)
WEBHOOK_SECRET = os.environ.get("HERMES_WEBHOOK_SECRET", "smzdm_hmac_secret_2026")


# ── 价格阈值 (元/瓶) ──
PRICE_550ML = 23.0
PRICE_1000ML = 50.0


def extract_price(price_str: str) -> float:
    """从价格字符串中提取数字"""
    if not price_str:
        return 0
    match = re.search(r'(\d+\.?\d*)', str(price_str))
    return float(match.group(1)) if match else 0


def parse_volume(title: str):
    """
    从标题解析容量和数量，返回 (ml_per_bottle, count)
    例如:
      "550ml*2瓶装" → (550, 2)
      "1L*3"        → (1000, 3)
      "550ml"       → (550, 1)
      "1000g"       → (1000, 1)  (无法判断是ml还是g，保守按ml处理)
    """
    title_lower = title.lower().replace("＊", "*").replace("×", "x")

    # 先找 "容量x数量" 或 "数量x容量" 的组合
    # 匹配: 550ml*2, 550ml×3, 550ml*2瓶, 2瓶*550ml 等
    patterns = [
        r'(\d+)\s*(?:ml|ml|毫升)\s*[*x×]\s*(\d+)',     # 550ml*2
        r'(\d+)\s*(?:l|升)\s*[*x×]\s*(\d+)',             # 1l*3
        r'(\d+)\s*(?:g|克)\s*[*x×]\s*(\d+)',             # 500g*2
        r'(\d+)\s*瓶\s*[*x×]\s*(\d+)\s*(?:ml|ml)',       # 2瓶*550ml
        r'(\d+)\s*(?:ml|ml)\s*(\d+)\s*瓶',               # 550ml2瓶 (少见)
    ]

    for pat in patterns:
        m = re.search(pat, title_lower)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            # 判断哪个是容量哪个是数量
            if a > 100:  # a 是容量
                return (a, b)
            else:        # a 是数量, b 是容量
                # 如果 b 是升为单位的大数，先转 ml
                ml = b * 1000 if b < 100 else b
                return (ml, a)

    # 单独找容量
    m = re.search(r'(\d+)\s*(?:ml|毫升)', title_lower)
    if m:
        return (int(m.group(1)), 1)

    m = re.search(r'(\d+)\s*(?:l|升)(?!\w)', title_lower)
    if m:
        val = int(m.group(1))
        return (val * 1000, 1)

    # 单独找数量 (x瓶, x袋, x盒 等)
    m = re.search(r'[*x×]\s*(\d+)\s*(?:瓶|袋|盒|包|支|件)', title_lower)
    if m:
        return (None, int(m.group(1)))

    return (None, 1)


def is_within_price_limit(title: str, total_price: float) -> tuple:
    """
    判断价格是否在阈值内
    返回 (通过, 单瓶价, 阈值, 说明)
    """
    if total_price <= 0:
        return (True, 0, 0, "无价格信息")

    ml, count = parse_volume(title)

    if ml is not None and ml >= 900:
        # 大瓶 (1L / 1000ml)
        threshold = PRICE_1000ML * count
        per_bottle = total_price / count
        return (total_price <= threshold, per_bottle, threshold, f"1L×{count}")
    elif ml is not None and ml >= 400:
        # 小瓶 (550ml)
        threshold = PRICE_550ML * count
        per_bottle = total_price / count
        return (total_price <= threshold, per_bottle, threshold, f"{ml}ml×{count}")
    elif count > 1:
        # 有数量但没容量，保守按550ml算
        threshold = PRICE_550ML * count
        per_bottle = total_price / count
        return (total_price <= threshold, per_bottle, threshold, f"未知容量×{count}")
    else:
        # 无法解析，放行
        return (True, total_price, 0, "无法解析容量")


def send_webhook(message: str) -> bool:
    payload = json.dumps({"message": message}).encode('utf-8')
    timestamp = str(int(time.time()))
    signed_content = timestamp.encode() + b"." + payload
    signature = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        signed_content,
        hashlib.sha256
    ).hexdigest()

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature-V2": signature,
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.getcode() == 200
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
    skipped = 0

    for row in rows:
        title = row["article_title"]
        price_str = row["article_price"] if "article_price" in row.keys() else ""
        link = row["article_url"] if "article_url" in row.keys() else ""
        mall = row["article_mall"] if "article_mall" in row.keys() else ""
        voted = row["article_voted"] if "article_voted" in row.keys() else 0

        price = extract_price(price_str)
        ok, per_bottle, threshold, note = is_within_price_limit(title, price)

        if not ok:
            print(f"⏭️ Skip ({note} ¥{per_bottle:.1f}/瓶 > ¥{threshold:.0f}): {title[:40]}...")
            skipped += 1
            cur.execute(
                "UPDATE ZDM SET pushed = 1 WHERE article_id = ?",
                (row["article_id"],)
            )
            continue

        msg = "🛒 可悠然好价推送\n"
        msg += "━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📦 {title}\n"
        if price_str:
            msg += f"💰 {price_str}\n"
        if per_bottle > 0 and per_bottle != price:
            msg += f"   (约 ¥{per_bottle:.1f}/瓶)\n"
        if mall:
            msg += f"🏪 {mall}\n"
        if voted:
            msg += f"👍 {voted}人觉得值\n"
        if link:
            msg += f"🔗 {link}\n"

        ok = send_webhook(msg)
        if ok:
            sent += 1
            print(f"✅ Sent ({note} ¥{per_bottle:.1f}/瓶): {title[:40]}...")
        else:
            print(f"❌ Failed: {title[:40]}...")

        cur.execute(
            "UPDATE ZDM SET pushed = 1 WHERE article_id = ?",
            (row["article_id"],)
        )

    conn.commit()
    conn.close()
    print(f"\nSent {sent}/{len(rows)} articles ({skipped} skipped by price filter)")


if __name__ == "__main__":
    main()
