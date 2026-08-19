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
import series
series.set_label("さくっとPR")   # 記事・SNS・画像・リールすべてに反映される
import eyecatch_generator
from eyecatch_generator import (generate_ig_feed, generate_eyecatch_photo,
                                 generate_eyecatch_simple)
from sns_clients import (post_threads, post_instagram_feed,
                          post_instagram_feed_carousel,
                          post_instagram_reel_resumable,
                          post_instagram_reel_by_url)
from generate_reel import render_static_reel
from publish_light_article import get_article_photos, parse_publish_date

PR_SHEET = "PRキュー"
PR_SPREADSHEET_ID = "1grn6UiQf8HqxcRSB3tMiZBLWGQCT1H7fCUNqv5CBA7A"   # ★専用スプレッドシート（2026-08-05分離）
PR_PHOTO_BASE = Path("G:/マイドライブ/さくっとPR")   # ★写真もライト記事と分離（2026-08-06社長指示）
JST = timezone(timedelta(hours=9))
PUBLISH_HOUR = 10  # 朝10時


def log(msg: str, indent: int = 0):
    print("  " * indent + msg)


def get_pr_photos(article_id: str, shop: str) -> list[Path]:
    """さくっとPRの写真を返す（ライト記事とはフォルダ分離）
    ローカル: G:\\マイドライブ\\さくっとPR\\{ID}_{店名}\\ ／ GHA: Drive「さくっとPR」フォルダ"""
    from publish_light_article import get_photo_paths
    if PR_PHOTO_BASE.exists():
        exact = PR_PHOTO_BASE / article_id
        cands = [exact] if exact.is_dir() else sorted(PR_PHOTO_BASE.glob(f"{article_id}_*"))
        cands = [c for c in cands if c.is_dir()]
        if cands:
            folder = cands[0]
            if shop and folder.name != article_id:
                import folder_match
                folder_match.verify(article_id, folder.name, shop)
            photos = get_photo_paths(folder)
            log(f"📸 写真: {len(photos)}枚 ({folder.name}) [ローカル]", 1)
            return photos
        log("📸 写真なし（さくっとPRフォルダに該当なし）", 1)
        return []
    try:
        from drive_client import fetch_article_photos
        cache_dir = ROOT / "_drive_cache" / article_id
        photos = fetch_article_photos(article_id, cache_dir, title=shop,
                                      root_name="さくっとPR")
        if photos:
            log(f"📸 写真: {len(photos)}枚 [Drive APIキャッシュ]", 1)
        else:
            log("📸 写真なし（Drive対象フォルダなし or 空）", 1)
        return photos
    except RuntimeError:
        raise               # フォルダ名と記事内容の不一致 → 中止（誤投稿防止）
    except Exception as e:
        log(f"⚠ Drive API取得失敗（写真なしで続行）: {e}", 1)
        return []


def get_pr_rows_for(target: date) -> list[tuple[int, dict]]:
    rows = read_all_rows(sheet=PR_SHEET, spreadsheet_id=PR_SPREADSHEET_ID)
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

    # === 写真（G:\マイドライブ\さくっとPR\{PRID}_{店名}\・ライト記事と分離） ===
    photos = get_pr_photos(article_id, shop)

    # 「0」番＝16:9アイキャッチ専用写真（任意）。全面crop で文字が欠ける写真のときに
    # 手動で切り出した16:9版を 0.jpg として置く。本文・カルーセル・IGカードには出さない
    # （2026-08-19 PR003: 受賞写真の焼き込み文字が16:9cropで欠けた対策）
    ec_photo = next((p for p in photos if int(p.stem) == 0), None)
    photos = [p for p in photos if int(p.stem) != 0]

    # === アイキャッチ＆IG Feed（2026-08-05 確定デザイン：額ぶち／一枚の札） ===
    #     色・ラベルは備考の「色：／ラベル：」を読む（無ければ店名から自動＝申込プレビューと同じ色）
    import pr_eyecatch
    first_photo = photos[0] if photos else None
    eyecatch_path = ROOT / "_sample" / f"_tmp_{article_id}_eyecatch.png"
    eyecatch_path.parent.mkdir(exist_ok=True)
    pr_eyecatch.render_169(row, photo_path=(ec_photo or first_photo), output_path=eyecatch_path)
    log(f"🎨 アイキャッチ16:9（{'一枚の札' if first_photo else '額ぶち'}）: {eyecatch_path.name}", 1)

    ig_feed_path = ROOT / "_sample" / f"_tmp_{article_id}_ig_feed.png"
    pr_eyecatch.render_45(row, photo_path=first_photo, output_path=ig_feed_path)
    log(f"📷 IG Feed 4:5（{'一枚の札' if first_photo else '額ぶち'}）: {ig_feed_path.name}", 1)

    # === リール動画（1080×1920・15秒静止・CBR 3M） ===
    reel_path = ROOT / "_sample" / f"_tmp_{article_id}_reel.mp4"
    reel_frame = pr_eyecatch.render_reel_frame(row, photo_path=first_photo)
    render_static_reel(reel_frame, reel_path)
    log(f"🎬 リール動画生成: {reel_path.name} ({reel_path.stat().st_size/1024:.0f} KB)", 1)

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
    # === IG Feed：写真があればカルーセル（1枚目=PRカード・2枚目以降=届いた写真全部を豊川ガイド枠付きで）===
    #     2026-08-06 社長指示「送られてきた写真は全部インスタで使いたい」。LRと同方式・枠の帯は「さくっとPR」
    try:
        carousel_photos = [p for p in photos if p.stem.isdigit() and int(p.stem) >= 1]
        # IGカルーセルは1投稿10枚まで。1枚目がPRカードなので写真は9枚が上限で、
        # それを超えた分は post_instagram_feed_carousel 側で黙って切られる。
        # 気づかないまま「送ったのに載っていない」が起きるので警告を出す（2026-08-14）
        if len(carousel_photos) > 9:
            dropped = [p.name for p in carousel_photos[9:]]
            log(f"⚠️ 写真が{len(carousel_photos)}枚あります。IGカルーセルの上限（カバー＋9枚）を超えるため "
                f"{len(dropped)}枚はInstagramに載りません: {', '.join(dropped)}"
                f"（WP記事には全部載ります）", 1)
        ig_images = [ig_feed_url]
        if not sns_dry and carousel_photos:
            # 枠はPR専用デザイン（テーマ色連動・店名入り）。LRのphoto_frameは使わない（2026-08-06社長指示）
            for p in carousel_photos:
                framed = ROOT / "_sample" / f"_framed_{article_id}_{p.stem}.png"
                pr_eyecatch.render_carousel_photo(row, p, framed)
                ig_images.append(upload_media(framed)["source_url"])
                log(f"🖼️ PR枠付け→アップ: {p.name}", 2)
        if carousel_photos:
            log(f"📷 IG Feed カルーセル投稿（カバー＋写真{len(carousel_photos)}枚・dry={sns_dry}）", 1)
            r2 = post_instagram_feed_carousel(ig_text, ig_images, dry=sns_dry)
        else:
            log(f"📸 IG Feed 単発投稿（写真なし・dry={sns_dry}）", 1)
            r2 = post_instagram_feed(ig_text, image_url=ig_feed_url, dry=sns_dry)
        log(f"  → {r2}", 2)
    except Exception as e:
        log(f"⚠ IG Feed失敗（続行）: {e}", 1)
    try:
        log(f"🎬 Instagram Reels 投稿（1080×1920・dry={sns_dry}）", 1)
        reel_result = post_instagram_reel_resumable(ig_text, reel_path, dry=sns_dry)
        log(f"  → {reel_result}", 2)
        # Resumable失敗時は公開URL方式でフォールバック（LR053事故と同じ対策）
        if (not sns_dry) and reel_result.get("error"):
            log("  ↻ Resumable失敗 → 公開URL方式でフォールバック", 2)
            video_url = upload_media(Path(reel_path))["source_url"]
            fb = post_instagram_reel_by_url(ig_text, video_url, dry=False)
            log(f"  → (fallback) {fb}", 2)
    except Exception as e:
        log(f"⚠ Reels失敗（続行）: {e}", 1)

    # === Sheets 状態更新＋X文通知 ===
    x_text = build_pr_x_caption(row, wp_url)
    if not use_draft:
        try:
            update_status(row_index, "投稿済", sheet=PR_SHEET, spreadsheet_id=PR_SPREADSHEET_ID)
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
        rows = read_all_rows(sheet=PR_SHEET, spreadsheet_id=PR_SPREADSHEET_ID)
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
