# -*- coding: utf-8 -*-
"""
publish_pr_article.py — さくっとPR（広告記事）自動投稿メインスクリプト

【動作】毎朝10:00 JST（GHA cron）
1. Sheets「PRキュー」から 状態=draft かつ 公開希望日=今日 の行を1件取得
2. 写真（G:\\マイドライブ\\ライト記事\\{PRID}_{店名}\\ or Drive API）ロード
3. アイキャッチ（PRバッジ）＋IG Feed画像 生成→WPメディアアップ
4. WP予約投稿（カテゴリ=pr・10:00・slug=pr001形式）
5. Threads / IG Feed 自動投稿
6. Sheets 状態更新＋Gmail通知（X予約用テキスト）

【使い方】
python publish_pr_article.py             # dry-run
python publish_pr_article.py --publish   # 本番
python publish_pr_article.py --draft     # WP draftテスト
python publish_pr_article.py --id PR001 --draft
"""
from __future__ import annotations
import argparse
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sheets_client import read_all_rows, update_status
from pr_builder import (build_pr_title, build_pr_content,
                        build_pr_x_caption, build_pr_threads_caption,
                        build_pr_instagram_caption)
import eyecatch_generator
eyecatch_generator.SERIES_LABEL = "さくっとPR"  # PRブランドに差し替え
from eyecatch_generator import (generate_ig_feed, generate_eyecatch_photo,
                                 generate_eyecatch_simple)
from sns_clients import post_threads, post_instagram_feed
from publish_light_article import get_article_photos, parse_publish_date

PR_SHEET = "PRキュー"
JST = timezone(timedelta(hours=9))
PUBLISH_HOUR = 10  # 朝10時


def log(msg: str, indent: int = 0):
    print("  " * indent + msg)


def get_pr_rows_for(target: date) -> list[tuple[int, dict]]:
    rows = read_all_rows(sheet=PR_SHEET)
    out = []
    for i, row in enumerate(rows, start=2):
        if row.get("状態", "").strip() != "draft":
            continue
        d = parse_publish_date(row.get("公開希望日", "").strip() or "")
        if d == target:
            out.append((i, row))
    return out


def send_pr_x_mail(article_id: str, title: str, x_text: str, publish_at: str,
                   wp_url: str, dry: bool):
    """X予約用テキストをGmail送信（notifyの雛形をPR用件名で）"""
    try:
        from notify import send_x_caption_mail
        return send_x_caption_mail(article_id, f"[さくっとPR] {title}", x_text,
                                   publish_at, wp_url, dry=dry)
    except Exception as e:
        log(f"⚠ Gmail通知失敗（続行）: {e}", 1)
        return {"error": str(e)}


def process_row(row_index: int, row: dict, *, dry_run: bool, use_draft: bool,
                target_date: date, skip_if_published: bool = True) -> dict:
    article_id = row.get("ID", "?").strip()
    shop = row.get("店名", "?").strip()
    catch = row.get("ひとことキャッチ", "").strip()
    log(f"📝 さくっとPR 処理開始: {article_id} - {shop}")

    publish_dt = datetime.combine(target_date, time(PUBLISH_HOUR, 0), tzinfo=JST)

    # === 写真（ライト記事と同じ置き場: {PRID}_{店名} フォルダ） ===
    photos = get_article_photos(article_id, shop)

    # === アイキャッチ ===
    eyecatch_path = ROOT / "_sample" / f"_tmp_{article_id}_eyecatch.png"
    eyecatch_path.parent.mkdir(exist_ok=True)
    if photos:
        generate_eyecatch_photo(
            photo_path=photos[0], place_name=shop,
            label_text="PR", original_title="",
            output_path=eyecatch_path,
        )
        log(f"🎨 アイキャッチ（写真版・PRバッジ）: {eyecatch_path.name}", 1)
    else:
        generate_eyecatch_simple(
            place_name=shop, label_text="PR", original_title="",
            sub_text=catch or "さくっとPR",
            output_path=eyecatch_path,
        )
        log(f"🎨 アイキャッチ（カード版・PRバッジ）: {eyecatch_path.name}", 1)

    # === IG Feed 画像 ===
    ig_feed_path = ROOT / "_sample" / f"_tmp_{article_id}_ig_feed.png"
    generate_ig_feed(
        place_name=shop,
        sub_text=catch or "さくっとPR",
        address=row.get("エリア・住所", "豊川市内"),
        landmark="",
        original_title="",
        label_text="PR",
        output_path=ig_feed_path,
    )
    log(f"📷 IG Feed画像: {ig_feed_path.name}", 1)

    title = build_pr_title(row)
    log(f"📰 タイトル: {title}", 1)

    if dry_run:
        content = build_pr_content(row, photo_urls=["(dry-photo)"] * len(photos))
        log("[DRY] WP投稿スキップ", 1)
        log(f"[DRY] 公開予定: {publish_dt.isoformat()}", 1)
        log(f"[DRY] 本文文字数: {len(content)}", 1)
        x_text = build_pr_x_caption(row, f"https://toyokawa-rentallife.com/{article_id.lower()}/")
        print("\n---------- [DRY] X投稿用 ----------")
        print(x_text)
        print("\n---------- [DRY] 本文プレビュー(先頭600字) ----------")
        print(content[:600])
        return {"article_id": article_id, "dry_run": True, "title": title}

    from wp_client import (upload_media, find_published_post_by_slug,
                            create_scheduled_post_generic)

    slug = article_id.lower()

    existing_wp = None
    if skip_if_published and not use_draft:
        existing_wp = find_published_post_by_slug(slug)
        if existing_wp:
            log(f"⏭️ WP既存（post_id={existing_wp['id']}）→SNSのみ実行", 1)

    if existing_wp:
        ig_feed_media = upload_media(ig_feed_path)
        ig_feed_url = ig_feed_media["source_url"]
        wp_result = {"id": existing_wp["id"], "link": existing_wp["link"]}
    else:
        photo_urls = []
        for p in photos:
            media = upload_media(p)
            photo_urls.append(media["source_url"])
            log(f"📤 写真アップ: {p.name} → {media['id']}", 2)
        eyecatch_media = upload_media(eyecatch_path)
        log(f"🖼️ アイキャッチアップ: {eyecatch_media['id']}", 1)
        ig_feed_media = upload_media(ig_feed_path)
        ig_feed_url = ig_feed_media["source_url"]

        content = build_pr_content(row, photo_urls=photo_urls)
        wp_result = create_scheduled_post_generic(
            title=title, content=content,
            featured_media_id=eyecatch_media["id"],
            publish_at_jst=publish_dt,
            category_slug="pr",
            status="draft" if use_draft else "future",
            slug=slug,
        )
        log(f"✅ WP{'draft' if use_draft else '予約'}投稿: post_id={wp_result['id']}", 1)

    wp_url = wp_result.get("link", f"https://toyokawa-rentallife.com/{slug}/")

    # === SNS（draftテスト時は投稿しない） ===
    sns_dry = use_draft
    threads_text = build_pr_threads_caption(row, wp_url)
    ig_text = build_pr_instagram_caption(row, wp_url)
    try:
        r1 = post_threads(threads_text, image_url=ig_feed_url, dry=sns_dry)
        log(f"🧵 Threads: {r1}", 1)
    except Exception as e:
        log(f"⚠ Threads失敗（続行）: {e}", 1)
    try:
        r2 = post_instagram_feed(ig_text, image_url=ig_feed_url, dry=sns_dry)
        log(f"📸 IG Feed: {r2}", 1)
    except Exception as e:
        log(f"⚠ IG Feed失敗（続行）: {e}", 1)

    # === Sheets 状態更新＋X文通知 ===
    x_text = build_pr_x_caption(row, wp_url)
    if not use_draft:
        try:
            update_status(row_index, "投稿済", sheet=PR_SHEET)
            log("📋 Sheets 状態=投稿済", 1)
        except Exception as e:
            log(f"⚠ Sheets更新失敗（続行）: {e}", 1)
    send_pr_x_mail(article_id, title, x_text, publish_dt.isoformat(), wp_url,
                   dry=use_draft)

    print("\n---------- 📋 X 投稿用（コピペ） ----------")
    print(x_text)
    return {"article_id": article_id, "wp_post_id": wp_result["id"],
            "wp_url": wp_url, "title": title, "dry_run": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="本番投稿")
    ap.add_argument("--draft", action="store_true", help="WP draftテスト")
    ap.add_argument("--id", help="特定IDのみ処理")
    ap.add_argument("--date", help="公開日上書き YYYY-MM-DD")
    args = ap.parse_args()

    dry_run = not (args.publish or args.draft)
    target = parse_publish_date(args.date) if args.date else datetime.now(JST).date()

    if args.id:
        rows = read_all_rows(sheet=PR_SHEET)
        found = [(i, r) for i, r in enumerate(rows, start=2)
                 if r.get("ID", "").strip().upper() == args.id.upper()]
        if not found:
            print(f"❌ {args.id} がPRキューに見つかりません")
            return
        targets = found[:1]
    else:
        targets = get_pr_rows_for(target)

    if not targets:
        print(f"📭 {target} のさくっとPRはありません（正常終了）")
        return

    for row_index, row in targets[:1]:  # 1日1件
        process_row(row_index, row, dry_run=dry_run, use_draft=args.draft,
                    target_date=target)


if __name__ == "__main__":
    main()
