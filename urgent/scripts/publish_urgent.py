# -*- coding: utf-8 -*-
"""
publish_urgent.py — 緊急告知を今すぐ出す（ライト記事とは別の仕組み）

【入力】専用スプレッドシート「緊急告知」タブに1行（ID／タイトル／本文）
【動作】
1. 「緊急告知」カード（見出し＝緊急告知＋タイトル）を3サイズ自動生成
2. WP記事を「お知らせ」カテゴリで即公開（本文は書いたまま）
3. Threads／Instagram フィード／リール／ストーリーズに投稿
4. X 用テキストを Gmail で送る（X は社長が手動投稿）
5. シートの 状態 を「投稿済」に

やり直しても二重投稿しない：WP は slug で既存チェック、SNS は「SNS済」列に媒体ごとに記録。
失敗した媒体があれば終了コード1（同じIDで再実行すると失敗分だけやり直す）。

【使い方】
python publish_urgent.py                    # 確認だけ（dry-run・未投稿の1件）
python publish_urgent.py --id EM001         # 確認だけ（ID指定）
python publish_urgent.py --id EM001 --publish   # 本番：今すぐ公開
"""
from __future__ import annotations
import argparse
import html
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIGHT_SCRIPTS = ROOT.parents[1] / "light_articles" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(LIGHT_SCRIPTS))   # WP／SNS／Sheets の通信部品だけライト記事と共用

import urgent_card
from sheets_client import read_all_rows, update_status, get_sns_done, add_sns_done

# 専用スプレッドシート（GitHub の Variables「URGENT_SPREADSHEET_ID」で指定）
SPREADSHEET_ID = os.environ.get("URGENT_SPREADSHEET_ID", "").strip()
SHEET = "緊急告知"
JST = timezone(timedelta(hours=9))
HEADING = "【緊急告知】"
HASHTAGS = "#豊川市 #豊川ガイド #緊急告知"
OUT = ROOT / "_sample"


def log(msg: str, indent: int = 0):
    print("  " * indent + msg, flush=True)


# ───────── 行の選び方 ─────────
def pick_row(rows: list[dict], want_id: str | None) -> tuple[int, dict]:
    """--id があればその行。無ければ「状態」が空（未投稿）の行がちょうど1件ならそれ"""
    if want_id:
        for i, r in enumerate(rows, start=2):
            if r.get("ID", "").strip().upper() == want_id.strip().upper():
                return i, r
        sys.exit(f"❌ ID={want_id} がシート「{SHEET}」に見つかりません")
    pending = [(i, r) for i, r in enumerate(rows, start=2)
               if r.get("タイトル", "").strip() and r.get("状態", "").strip() in ("", "draft", "未投稿")]
    if not pending:
        sys.exit("📭 未投稿の緊急告知はありません（状態が空の行がない）")
    if len(pending) > 1:
        ids = ", ".join(r.get("ID", "").strip() or f"{i}行目" for i, r in pending)
        sys.exit(f"❌ 未投稿の行が{len(pending)}件あります（{ids}）。ID を指定して実行してください")
    return pending[0]


def article_id(row_index: int, row: dict) -> str:
    return row.get("ID", "").strip().upper() or f"EM{row_index:03d}"


# ───────── 文面 ─────────
def build_content(body: str, posted_at: datetime) -> str:
    """本文は書いたまま。空行で段落・改行はそのまま改行"""
    stamp = f"{posted_at.year}年{posted_at.month}月{posted_at.day}日 {posted_at:%H:%M} 発信"
    paras = [p.strip() for p in body.replace("\r\n", "\n").split("\n\n") if p.strip()]
    parts = [f'<p><strong>{HEADING}</strong>（{stamp}）</p>']
    for p in paras:
        parts.append("<p>" + "<br>\n".join(html.escape(l) for l in p.split("\n")) + "</p>")
    return "\n".join(parts)


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def build_threads_text(title: str, body: str, url: str) -> str:
    head = f"{HEADING}{title}\n\n"
    tail = f"\n\n▼詳細\n{url}\n\n{HASHTAGS}"
    return head + _cut(body, 500 - len(head) - len(tail)) + tail     # Threads は500字まで


def build_ig_text(title: str, body: str) -> str:
    return (f"{HEADING}{title}\n\n{body}\n\n"
            f"▼詳細はプロフィールのリンクから\n\n{HASHTAGS}")[:2200]


def build_x_text(title: str, body: str, url: str) -> str:
    """X は全角140字相当（URLは全角12字分）に収める"""
    head = f"{HEADING}{title}\n\n"
    tail = "\n\n▼詳細\n"
    room = 140 - len(head) - len(tail) - 12
    return head + _cut(body.replace("\n\n", "\n"), room) + tail + url


def send_x_mail(aid: str, title: str, x_text: str, wp_url: str):
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not pw:
        log("⚠ GMAIL_USER / GMAIL_APP_PASSWORD 未設定のためメールは送りません", 1)
        return
    body = f"""緊急告知を公開しました（WP・Instagram・Threads）。
X は下のテキストをコピーして、今すぐ投稿してください。

ID: {aid}
WP: {wp_url}

------------ コピペ用 ------------
{x_text}
------------ ここまで ------------
"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"【緊急告知】公開しました・X用テキスト（{title}）"
    msg["From"] = user
    msg["To"] = user
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)


# ───────── 本体 ─────────
def process(row_index: int, row: dict, dry: bool) -> list[str]:
    """失敗した媒体の一覧を返す（空なら全部成功）"""
    aid = article_id(row_index, row)
    title = row.get("タイトル", "").strip()
    body = row.get("本文", "").strip()
    if not title:
        sys.exit(f"❌ {aid}: タイトルが空です")
    slug = aid.lower()
    # WP は「status=publish でも日付が未来」だと予約扱いにするので、時計ずれを見込んで2分前に
    posted_at = (datetime.now(JST) - timedelta(minutes=2)).replace(second=0, microsecond=0)
    log(f"🚨 緊急告知 {aid}: {title}（{'確認のみ・投稿しない' if dry else '今すぐ公開'}）")

    # 画像（タイトルの改行はそのまま。WP／SNS の見出しでは改行を詰める）
    flat_title = " ".join(t.strip() for t in title.splitlines() if t.strip())
    eyecatch = urgent_card.render(title, 1280, 720, OUT / f"{aid}_eyecatch.png", posted_at)
    feed = urgent_card.render(title, 1080, 1350, OUT / f"{aid}_feed.png", posted_at)
    tall = urgent_card.render(title, 1080, 1920, OUT / f"{aid}_tall.png", posted_at)
    from PIL import Image
    from generate_reel import render_static_reel
    reel = render_static_reel(Image.open(tall).convert("RGB"), OUT / f"{aid}_reel.mp4")
    log("🎨 画像・リール動画を生成", 1)

    content = build_content(body, posted_at)
    wp_title = f"{HEADING}{flat_title}"
    if dry:
        url = f"https://toyokawa-rentallife.com/{slug}/"
        print(f"\n---------- WP タイトル ----------\n{wp_title}")
        print(f"---------- WP 本文 ----------\n{content}")
        print(f"---------- Threads ----------\n{build_threads_text(flat_title, body, url)}")
        print(f"---------- Instagram ----------\n{build_ig_text(flat_title, body)}")
        print(f"---------- X（メールで届く） ----------\n{build_x_text(flat_title, body, url)}")
        print(f"\n画像: {OUT}")
        return []

    from wp_client import (upload_media, find_published_post_by_slug,
                           create_scheduled_post_generic)
    from sns_clients import (post_threads, post_instagram_feed, post_instagram_story,
                             post_instagram_reel_resumable, post_instagram_reel_by_url)

    # === WP（即公開・お知らせカテゴリ） ===
    existing = find_published_post_by_slug(slug)
    if existing:
        wp_url = existing["link"]
        log(f"⏭️ WP は公開済み（post_id={existing['id']}）→ SNS だけ続ける", 1)
    else:
        media = upload_media(eyecatch)
        wp = create_scheduled_post_generic(
            title=wp_title, content=content, featured_media_id=media["id"],
            publish_at_jst=posted_at, category_slug="news", status="publish", slug=slug)
        wp_url = wp.get("link") or f"https://toyokawa-rentallife.com/{slug}/"
        log(f"✅ WP 公開: {wp_url}", 1)

    # === SNS（成功済みの媒体はとばす） ===
    done = get_sns_done(row_index, SHEET, SPREADSHEET_ID)
    if done:
        log(f"↩ 投稿済みの媒体はとばします: {', '.join(sorted(done))}", 1)
    failures = []

    def run(key: str, label: str, fn):
        if key in done:
            log(f"{label} … 投稿済みなのでスキップ", 1)
            return
        try:
            r = fn()
        except Exception as e:
            r = {"error": str(e)}
        ok = not r.get("error") and r.get("status") != "error"
        log(f"{label} → {r}", 1)
        if ok:
            add_sns_done(row_index, key, SHEET, SPREADSHEET_ID)
        else:
            failures.append(f"{label}: {r.get('error')}")

    feed_url = upload_media(feed)["source_url"] if not {"threads", "ig_feed"} <= done else ""
    ig_text = build_ig_text(flat_title, body)
    run("threads", "🧵 Threads",
        lambda: post_threads(build_threads_text(flat_title, body, wp_url), image_url=feed_url, dry=False))
    run("ig_feed", "📷 IG フィード", lambda: post_instagram_feed(ig_text, feed_url, dry=False))

    def reel_post():
        r = post_instagram_reel_resumable(ig_text, reel, dry=False)
        if r.get("status") == "error":     # ライト記事と同じく公開URL方式で再挑戦
            log("  ↻ リール Resumable 失敗 → 公開URL方式で再挑戦", 1)
            r = post_instagram_reel_by_url(ig_text, upload_media(reel)["source_url"], dry=False)
        return r
    run("ig_reel", "🎬 IG リール", reel_post)
    run("ig_story", "📱 IG ストーリーズ",
        lambda: post_instagram_story(upload_media(tall)["source_url"], dry=False))

    # === X 用メール（1回だけ）と状態 ===
    if "mail" not in done:
        try:
            send_x_mail(aid, flat_title, build_x_text(flat_title, body, wp_url), wp_url)
            add_sns_done(row_index, "mail", SHEET, SPREADSHEET_ID)
            log("📧 X 用テキストを Gmail で送信", 1)
        except Exception as e:
            log(f"⚠ Gmail 送信失敗: {e}", 1)
    if not failures:
        update_status(row_index, "投稿済", sheet=SHEET, spreadsheet_id=SPREADSHEET_ID)
        log("📋 状態=投稿済", 1)
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="ID（例 EM001）。省略時は未投稿の1件")
    ap.add_argument("--publish", action="store_true", help="本番（今すぐ公開）。無しなら確認だけ")
    args = ap.parse_args()
    if not SPREADSHEET_ID:
        sys.exit("❌ URGENT_SPREADSHEET_ID が未設定です（GitHub の Variables に専用シートのIDを入れてください）")

    rows = read_all_rows(sheet=SHEET, spreadsheet_id=SPREADSHEET_ID)
    row_index, row = pick_row(rows, args.id)
    failures = process(row_index, row, dry=not args.publish)
    if failures:
        print("\n❌ 失敗した媒体があります。同じIDでもう一度実行すると失敗分だけやり直します")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\n✅ 完了")


if __name__ == "__main__":
    main()
