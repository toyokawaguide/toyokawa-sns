"""占い Reels 自動チェック＋再投稿（毎朝 6:30 JST）

main.py の朝 5:00 cron で Reels 投稿失敗した場合、
本スクリプトが 6:30 に発火して以下を実行：
1. Instagram の最新投稿 25件を確認 → 今日の Reel があるか判定
2. ある → 何もしない（静か）
3. 無い → WP記事から TOP12 抽出 → caption 生成 → IG Reels 単独再投稿
4. 成功/失敗 を Gmail 通知

【環境変数】
- WP_URL / WP_USERNAME / WP_PASSWORD
- META_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID
- GMAIL_USER / GMAIL_APP_PASSWORD
- URANAI_SHEETS_URL / URANAI_SHEETS_SECRET（任意）

【使い方】
  python reel_check_resend.py                  # 今日分チェック＋必要時再投稿
  python reel_check_resend.py --date 2026-05-25  # 日付指定
  python reel_check_resend.py --force          # IG確認スキップ・強制再投稿
"""
from __future__ import annotations
import argparse
import html as html_mod
import os
import re
import smtplib
import sys
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

JST = timezone(timedelta(hours=9))

WD_KEY = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


def gmail_notify(subject: str, body: str) -> bool:
    user = os.getenv("GMAIL_USER")
    pw = os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pw:
        print("[warn] GMAIL_USER/PASSWORD 未設定。通知送信スキップ")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = user
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"[error] Gmail 送信失敗: {e}")
        return False


def check_ig_has_reel_today(target_date: date) -> tuple[bool, str]:
    """IG 最新投稿25件のうち、target_date（JST）以降に VIDEO/REELS 投稿があるか判定

    Returns: (exists, info_msg)
    """
    token = os.environ["META_ACCESS_TOKEN"]
    ig_id = os.getenv("INSTAGRAM_ACCOUNT_ID") or "17841467629335560"

    r = requests.get(
        f"https://graph.facebook.com/v19.0/{ig_id}/media",
        params={
            "fields": "id,media_type,timestamp,permalink",
            "limit": 25,
            "access_token": token,
        },
        timeout=30,
    )
    if r.status_code != 200:
        return False, f"IG API エラー: {r.status_code} {r.text[:200]}"

    target_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=JST)
    target_end = target_start + timedelta(days=1)

    for m in r.json().get("data", []):
        ts = m.get("timestamp", "")  # ISO8601
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t < target_start:
            break  # 古いので終了
        if target_start <= t < target_end and m.get("media_type") in ("VIDEO", "REELS"):
            return True, f"検出: {m['permalink']} ({t.isoformat()})"

    return False, "今日の Reel 未投稿"


def get_today_uranai_post(target_date: date) -> dict | None:
    """WP から 今日の占い記事を取得（slug=uranai-YYYYMMDD）"""
    slug = f"uranai-{target_date.strftime('%Y%m%d')}"
    r = requests.get(
        f"{os.environ['WP_URL']}/wp-json/wp/v2/posts",
        params={"slug": slug, "status": "any", "_fields": "id,title,content,status,link"},
        auth=(os.environ["WP_USERNAME"], os.environ["WP_PASSWORD"]),
        timeout=30,
    )
    data = r.json()
    if not data:
        return None
    return data[0]


def find_reel_video_url(target_date: date) -> str | None:
    """WP メディアから 今日の Reel mp4 URL を取得"""
    fname = f"{target_date.strftime('%Y-%m-%d')}_{WD_KEY[target_date.weekday()]}_reel"
    r = requests.get(
        f"{os.environ['WP_URL']}/wp-json/wp/v2/media",
        params={"search": fname, "per_page": 5, "_fields": "id,source_url,mime_type"},
        auth=(os.environ["WP_USERNAME"], os.environ["WP_PASSWORD"]),
        timeout=30,
    )
    for m in r.json():
        if "video" in m.get("mime_type", ""):
            return m["source_url"]
    return None


def parse_wp_post_to_data(content_html: str) -> tuple[list[dict], str]:
    """WP本文からTOP12（or TOP10）と spot 名を抽出

    Returns: (items, spot_name)
    """
    content = html_mod.unescape(content_html)
    # ランキング項目：## 🥇/🥈/🥉/N位 ：【XX】<br/>★...★ N/10<br/>コメント
    pattern = re.compile(
        r"##\s*(?:🥇 第\d位|🥈 第\d位|🥉 第\d位|\d+位)[：:]?\s*"
        r"【([^】]+)】\s*<br\s*/?>\s*"
        r"[★☆]+\s*(\d+)/10\s*<br\s*/?>\s*"
        r"([^<\n]+?)(?=</p>|<br)",
    )
    matches = pattern.findall(content)
    items = [
        {"label": label.strip(), "stars": int(stars), "comment": comment.strip()}
        for label, stars, comment in matches
    ]
    # ラッキースポット
    spot_match = re.search(
        r'<p style="font-size:1\.7em[^>]*?>\s*([^<\n]+?)\s*</p>',
        content,
    )
    spot_name = spot_match.group(1).strip() if spot_match else "（不明）"
    return items, spot_name


def resend_reel(target_date: date) -> dict:
    """Reels 単独再投稿実行"""
    # 1. WP 記事取得
    post = get_today_uranai_post(target_date)
    if not post:
        return {"status": "error", "error": f"WP に {target_date} の占い記事なし"}
    if post["status"] != "publish":
        return {"status": "error", "error": f"WP記事が未公開 (status={post['status']})"}

    # 2. data 抽出
    items, spot_name = parse_wp_post_to_data(post["content"]["rendered"])
    if len(items) < 4:
        return {"status": "error", "error": f"記事から items 抽出失敗 ({len(items)} 件)"}

    # 3. 動画URL取得
    video_url = find_reel_video_url(target_date)
    if not video_url:
        return {"status": "error", "error": "WP に Reel mp4 が見つからない"}

    # 4. Spot, data 準備
    class Spot:
        def __init__(self, name, is_chain=False):
            self.name = name
            self.is_chain = is_chain

    spot = Spot(name=spot_name, is_chain=False)
    article_data = {"items": items}
    weekday_key = WD_KEY[target_date.weekday()]

    # 5. Reels 投稿
    from post_instagram_uranai import post_instagram_uranai_reel
    print(f"  → Reels 投稿開始: {video_url}")
    result = post_instagram_uranai_reel(
        weekday_key=weekday_key,
        data=article_data,
        spot=spot,
        target_date=target_date,
        video_url=video_url,
        cover_url=None,
        dry=False,
    )
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD（省略時 JST 今日）")
    ap.add_argument("--force", action="store_true", help="IG確認スキップ・強制再投稿")
    args = ap.parse_args()

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = datetime.now(JST).date()

    print("=" * 60)
    print(f" Reels 自動チェック＋再投稿 (target={target_date})")
    print("=" * 60)

    # 必須 env チェック
    required = ["WP_URL", "WP_USERNAME", "WP_PASSWORD", "META_ACCESS_TOKEN"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        msg = f"必須 env 未設定: {missing}"
        print(f"❌ {msg}")
        gmail_notify(
            f"⚠️【占い】Reels自動チェック 設定エラー {target_date}",
            f"reel_check_resend.py が必要な環境変数を取得できませんでした:\n{msg}\n\n"
            "GitHub Secrets と workflow.yml の env: を確認してください。",
        )
        sys.exit(1)

    # 1. IG 既に投稿されてるか？
    if args.force:
        exists, info = False, "force モード"
    else:
        exists, info = check_ig_has_reel_today(target_date)
    print(f"\n[IG 確認] {info}")

    if exists:
        print("✅ 既に投稿済み → 何もしない")
        return

    # 2. 投稿されてない → 再投稿
    print("⚠️ Reel 未投稿 → 再投稿実行")
    result = resend_reel(target_date)
    print(f"\n結果: {result.get('status')}")

    if result.get("status") == "ok":
        body = (
            f"【占い】Reels自動再投稿 成功 {target_date}\n\n"
            f"朝の cron で投稿失敗していた Reels を 6:30 cron で復旧しました。\n"
            f"- post_id: {result.get('post_id')}\n"
            f"- attempts: {result.get('attempts')}\n\n"
            f"Instagram で確認してください。\n"
            f"自動配信: toyokawa-sns/reel_check_resend"
        )
        gmail_notify(
            f"✅【占い】Reels自動復旧 成功 {target_date}",
            body,
        )
        print("✅ Gmail 通知送信")
    else:
        body = (
            f"⚠️【占い】Reels自動再投稿 失敗 {target_date}\n\n"
            f"朝の cron で Reels 投稿失敗→6:30 自動再投稿も失敗しました。\n"
            f"手動対応をお願いします:\n"
            f"  1. Instagram アプリで動画 DL\n"
            f"  2. Reel として手動投稿\n\n"
            f"エラー: {result.get('error')}\n"
            f"attempts: {result.get('attempts')}\n\n"
            f"自動配信: toyokawa-sns/reel_check_resend"
        )
        gmail_notify(
            f"🚨【占い】Reels自動復旧 失敗 {target_date}",
            body,
        )
        print(f"❌ Gmail 通知送信（失敗: {result.get('error')}）")
        sys.exit(2)


if __name__ == "__main__":
    main()
