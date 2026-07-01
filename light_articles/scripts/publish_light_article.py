"""
publish_light_article.py — ライト記事 自動投稿メインスクリプト

【動作】
1. Sheets から draft 取得（古い順1件）
2. WP の翌日19時手動投稿チェック→あればスキップ
3. 写真フォルダ→WPメディアアップ
4. アイキャッチ自動生成→WPメディアアップ
5. 本文テンプレ生成
6. WP REST API で予約投稿（または draft）
7. Sheets 状態を「予約済」に更新
8. Gmail通知（X予約用テキスト付き）

【使い方】
python publish_light_article.py             # dry-run（デフォルト・公開なし）
python publish_light_article.py --publish   # 本番（予約投稿）
python publish_light_article.py --draft     # WP draft で投稿（テスト用）
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sheets_client import get_draft_rows, get_pending_rows, update_status, SPREADSHEET_ID, get_row_by_id
from content_builder import (build_title, build_content, build_photo_html,
                              build_x_caption, build_threads_caption,
                              build_instagram_caption, get_sub)
from eyecatch_generator import generate_eyecatch, generate_ig_feed
from generate_reel import generate_reel
from sns_clients import (post_threads, post_instagram_feed,
                          post_instagram_feed_carousel,
                          post_instagram_reel_resumable)
from notify import send_x_caption_mail, send_skip_notification

LIGHT_BASE = Path("G:/マイドライブ/ライト記事")
JST = timezone(timedelta(hours=9))


def log(msg: str, indent: int = 0):
    print("  " * indent + msg)


def parse_publish_date(s: str) -> date | None:
    """Sheets の日付文字列を柔軟にパース。
    対応形式：2026-05-28 / 2026/05/28 / 5/28 / 05-28 / 等
    年省略時は今年（実行年）として解釈。過去日付なら来年扱い。
    """
    s = s.strip().replace("/", "-").replace(".", "-")
    today = date.today()
    parts = [p for p in s.split("-") if p]
    try:
        if len(parts) == 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 100:
                y += 2000
            return date(y, m, d)
        elif len(parts) == 2:
            m, d = int(parts[0]), int(parts[1])
            candidate = date(today.year, m, d)
            # 過去日付なら来年（運用ミス防止）
            if candidate < today - timedelta(days=30):
                candidate = date(today.year + 1, m, d)
            return candidate
    except (ValueError, TypeError):
        pass
    return None


def find_article_folder(article_id: str, place: str) -> Path | None:
    """ライト記事/{ID} or {ID}_{場所}/ フォルダを探す（場所部分は任意・ローカルのみ）"""
    if not LIGHT_BASE.exists():
        return None
    # 1) 完全一致 LR001
    exact = LIGHT_BASE / article_id
    if exact.is_dir():
        return exact
    # 2) {ID}_* マッチ（LR001_とんやんラーメン跡地 等）
    candidates = list(LIGHT_BASE.glob(f"{article_id}_*"))
    if candidates:
        return candidates[0]
    return None


def get_article_photos(article_id: str, place: str) -> list[Path]:
    """記事ID の写真パスを返す（ローカル優先・なければDrive API経由）

    動作モード:
    1. ローカルモード（Windows・LIGHT_BASE存在）: G:\マイドライブ\ライト記事\{ID}_*\ から直接読込
    2. Drive API モード（GHA Linux）: Drive API でDL→_drive_cache に保存→そのパスを返す
    """
    folder = find_article_folder(article_id, place)
    if folder:
        # ローカルモード
        photos = get_photo_paths(folder)
        log(f"📸 写真: {len(photos)}枚 ({folder.name}) [ローカル]", 1)
        return photos

    # Drive API モード（GHA環境）
    try:
        from drive_client import fetch_article_photos
        cache_dir = ROOT / "_drive_cache" / article_id
        photos = fetch_article_photos(article_id, cache_dir)
        if photos:
            log(f"📸 写真: {len(photos)}枚 [Drive APIキャッシュ]", 1)
        else:
            log(f"📸 写真なし（Drive対象フォルダなし or 空）", 1)
        return photos
    except Exception as e:
        log(f"⚠ Drive API取得失敗（写真なしで続行）: {e}", 1)
        return []


def ensure_batch_watermarked(folder: Path) -> None:
    """番号付き原本 [0-9]*.jpg があって batch_*.jpg が未生成なら、
    自動で add_date_watermark を呼んで日付＋ロゴを焼き込む。
    既に batch_*.jpg があるファイルはスキップ（add_date_watermark側の重複防止）。

    社長が watermark スクリプト実行を忘れても事故らないための安全網。
    """
    if not folder.exists():
        return

    exts = ("jpg", "jpeg", "png")

    # 番号付き原本が存在するか
    has_raw_numbered = False
    for ext in exts:
        if any(folder.glob(f"[0-9]*.{ext}")) or any(folder.glob(f"[0-9]*.{ext.upper()}")):
            has_raw_numbered = True
            break

    if not has_raw_numbered:
        return  # 番号付き原本がない＝焼込対象なし

    # 番号付き原本が存在 → add_date_watermark を実行（既処理ファイルは自動スキップ）
    try:
        import sys as _sys
        wp_upload_dir = Path("C:/Users/Yoshida/Desktop/豊川ガイド/wordpress_upload")
        if str(wp_upload_dir) not in _sys.path:
            _sys.path.insert(0, str(wp_upload_dir))
        from add_date_watermark import run as watermark_run
        log(f"🏷️ 日付＋ロゴ自動焼込み実行: {folder.name}", 1)
        watermark_run(str(folder), test_limit=None, with_logo=True)
    except Exception as e:
        log(f"⚠ 自動焼込み失敗（原本でアップ継続）: {e}", 1)


def get_photo_paths(folder: Path) -> list[Path]:
    """番号のみのファイル(0.jpg, 1.jpg, 2.jpg…)だけを番号順に返す。
    batch_ や W1920Q75_ 等の余分なファイルは無視する（2026-06-22 社長指定）。

    運用：社長が日付＋ロゴを焼き付けた写真を「0」「1」「2」…と番号だけで置く。
    それ以外のファイル名（batch_*, IMG*, W1920Q75_* 等）は記事に使わない。
    """
    if not folder.exists():
        return []
    exts = (".jpg", ".jpeg", ".png")
    numbered = [p for p in folder.iterdir()
                if p.suffix.lower() in exts and p.stem.isdigit()]
    return sorted(numbered, key=lambda p: int(p.stem))


def process_one(row_index: int, row: dict, dry_run: bool = True,
                use_draft: bool = False,
                target_date: date = None,
                x_only: bool = False,
                skip_if_published: bool = False,
                wp_only: bool = False) -> dict:
    """1記事を処理

    x_only=True の場合：
    - WP投稿・SNS投稿を一切しない
    - X予約用テキスト＋想定URLだけ Gmail通知
    - 社長が記事入力直後に「X予約投稿の文面だけ先に取得」する用途
    """
    article_id = row.get("ID", "?")
    place = row.get("場所", "?")
    has_original = bool(row.get("元記事タイトル", "").strip())
    mode = "続報" if has_original else "お知らせ"

    log(f"📝 処理開始: {article_id} - {place} ({mode}モード・x_only={x_only})")

    # 公開日：CLI引数 --date > スプレッドシート「公開希望日」列（必須）
    if not target_date:
        sheet_date = row.get("公開希望日", "").strip()
        if not sheet_date:
            log(f"❌ 公開希望日（B列）が空欄。スキップ。", 1)
            return {"skipped": True, "reason": "no_publish_date"}
        target_date = parse_publish_date(sheet_date)
        if not target_date:
            log(f"❌ 公開希望日の形式不正: {sheet_date}（YYYY-MM-DD / YYYY/MM/DD / M/D 等）", 1)
            return {"skipped": True, "reason": "invalid_publish_date"}
        log(f"📅 公開希望日（B列）: {target_date}", 1)
    publish_dt = datetime.combine(target_date, time(19, 0), tzinfo=JST)

    # === x_only モード：X/Threads/IG用テキストをセッション内出力（コピペ用） ===
    if x_only:
        slug = article_id.lower()
        expected_wp_url = f"https://toyokawa-rentallife.com/{slug}/"
        title = build_title(row)
        x_text = build_x_caption(row, expected_wp_url)
        threads_text = build_threads_caption(row, expected_wp_url)
        ig_text = build_instagram_caption(row, expected_wp_url)

        print()
        print("=" * 60)
        print(f" {article_id} 予約投稿用テキスト（コピペ用）")
        print("=" * 60)
        print(f"記事ID: {article_id}")
        print(f"想定URL: {expected_wp_url}")
        print(f"公開予定: {publish_dt.isoformat()}")
        print(f"タイトル: {title}")
        print()
        print("---------- 📋 X / Threads 投稿用 ----------")
        print(x_text)
        print()
        print("---------- 📋 Instagram Feed 用 ----------")
        print(ig_text)
        print()
        print("=" * 60)
        print(" 上のテキストをコピペして各SNSの予約投稿セットしてください")
        print("=" * 60)

        return {
            "article_id": article_id,
            "title": title,
            "publish_at": publish_dt.isoformat(),
            "mode": "x_only",
            "wp_url": expected_wp_url,
            "wp_post_id": None,
            "dry_run": False,
        }

    # === Step 1: 写真ロード（ローカル or Drive API 自動判定） ===
    photos = get_article_photos(article_id, place)

    # === Step 2: アイキャッチ生成 ===
    # サブテキスト：「その後（1段目）」+ \n + 「その後（2段目）」で渡す
    # （eyecatch_generator が \n を見て2段に分割描画）
    sub1 = row.get("その後（1段目）", "").strip()
    sub2 = row.get("その後（2段目）", "").strip()
    # 場所と完全一致する1段目は省略（LR002のような新店オープン記事対応）
    if sub1 and sub1 == place:
        sub1 = ""
    if sub1 and sub2:
        eyecatch_sub = f"{sub1}\n{sub2}"
    elif sub1:
        eyecatch_sub = sub1
    elif sub2:
        eyecatch_sub = sub2
    else:
        eyecatch_sub = row.get("サブ", "お知らせ")  # 後方互換

    eyecatch_path = ROOT / "_sample" / f"_tmp_{article_id}_eyecatch.png"
    # アイキャッチ表示文言の上書き（空欄→None→続報デフォルト＝後方互換）
    _label   = (row.get("ラベル", "") or "").strip() or None
    _catch   = (row.get("見出し1", "") or "").strip() or None
    _tlabel  = (row.get("過去記事ラベル", "") or "").strip() or None
    _sub1    = (row.get("見出し2", "") or "").strip() or None
    _clabel  = (row.get("カードラベル", "") or "").strip() or None
    _lmlabel = (row.get("目印ラベル", "") or "").strip() or None
    generate_eyecatch(
        place_name=place,
        sub_text=eyecatch_sub,
        address=row.get("住所", "豊川市内"),
        landmark=row.get("目印", ""),
        original_title=row.get("元記事タイトル", ""),
        label_text=_label,
        lead_catch=_catch,
        title_label=_tlabel,
        sub_heading=_sub1,
        card_label=_clabel,
        landmark_label=_lmlabel,
        output_path=eyecatch_path,
    )
    log(f"🎨 アイキャッチ生成: {eyecatch_path.name}", 1)

    # IG Feed 用画像（1080×1350 縦長・別ファイル）
    ig_feed_path = ROOT / "_sample" / f"_tmp_{article_id}_ig_feed.png"
    generate_ig_feed(
        place_name=place,
        sub_text=eyecatch_sub,
        address=row.get("住所", "豊川市内"),
        landmark=row.get("目印", ""),
        original_title=row.get("元記事タイトル", ""),
        label_text=_label,
        lead_catch=_catch,
        title_label=_tlabel,
        sub_heading=_sub1,
        card_label=_clabel,
        landmark_label=_lmlabel,
        output_path=ig_feed_path,
    )
    log(f"📷 IG Feed画像生成: {ig_feed_path.name}", 1)

    # IG Reels 用動画（1080×1920・15秒・mp4）
    sub1 = row.get("その後（1段目）", "").strip()
    sub2 = row.get("その後（2段目）", "").strip()
    if sub1 and sub1 == place:
        sub1 = ""
    reel_sub_lines = [s for s in [sub1, sub2] if s]
    if not reel_sub_lines:
        reel_sub_lines = [row.get("サブ", "お知らせ")]
    week = ["月", "火", "水", "木", "金", "土", "日"][target_date.weekday()]
    pub_str = f"{target_date.year}年{target_date.month}月{target_date.day}日({week})"

    reel_path = ROOT / "_sample" / f"_tmp_{article_id}_reel.mp4"
    generate_reel(
        place=place,
        sub_lines=reel_sub_lines,
        address=row.get("住所", "豊川市内"),
        landmark=row.get("目印", ""),
        original_title=row.get("元記事タイトル", ""),
        tsubuyaki=row.get("管理人のつぶやき", "").strip(),
        publish_date_str=pub_str,
        output_path=reel_path,
    )
    log(f"🎬 リール動画生成: {reel_path.name} "
        f"({reel_path.stat().st_size/1024:.0f} KB)", 1)

    # === Step 3: タイトル＆本文 ===
    title = build_title(row)
    log(f"📰 タイトル: {title}", 1)

    # === Step 4: WP投稿 ===
    if dry_run:
        log(f"[DRY] WP投稿スキップ（dry-run）", 1)
        log(f"[DRY] 予定公開: {publish_dt.isoformat()}", 1)
        log(f"[DRY] アイキャッチ: {eyecatch_path}", 1)
        log(f"[DRY] IG Feed画像: {ig_feed_path}", 1)
        log(f"[DRY] 写真: {len(photos)}枚", 1)
        result = {
            "article_id": article_id,
            "title": title,
            "publish_at": publish_dt.isoformat(),
            "mode": mode,
            "dry_run": True,
            "wp_post_id": None,
            "wp_url": None,
        }
        ig_feed_url = None
    else:
        from wp_client import (check_manual_post_scheduled, upload_media,
                                create_scheduled_post, create_draft_post,
                                find_published_post_by_slug)

        # WP投稿（slug：{ID 小文字}・URL末尾を lr001 形式に統一）
        slug = article_id.lower()

        # === 重複公開防止チェック（占いと同じ保険cron救済パターン用） ===
        existing_wp = None
        if skip_if_published and not use_draft:
            existing_wp = find_published_post_by_slug(slug)
            if existing_wp:
                log(f"⏭️ WP既存（post_id={existing_wp['id']}）・WP工程スキップ→SNS だけ実行", 1)

        # 翌日19時 手動投稿チェック（draft時はスキップしない・WP既存時もスキップ）
        if not use_draft and not existing_wp:
            if check_manual_post_scheduled(target_date):
                log(f"⏭️ 翌日19時に手動投稿あり・スキップ", 1)
                return {"skipped": True, "reason": "manual_post_scheduled"}

        if existing_wp:
            # WP は既に publish 済み → 写真・本文アップ・WP投稿は全部スキップ
            # IG Feed 画像だけは必要なのでアップする（WP メディアにあるかも知れないが念のため再アップ）
            ig_feed_media = upload_media(ig_feed_path)
            ig_feed_url = ig_feed_media["source_url"]
            log(f"📷 IG Feed画像アップ（SNS用）: {ig_feed_media['id']}", 1)
            wp_result = {
                "id": existing_wp["id"],
                "link": existing_wp["link"],
            }
            log(f"✅ WP既存利用: post_id={wp_result['id']} {wp_result['link']}", 1)
        else:
            # 写真アップロード
            photo_urls = []
            for p in photos:
                media = upload_media(p)
                photo_urls.append(media["source_url"])
                log(f"  📤 写真アップ: {p.name} → {media['id']}", 2)

            # アイキャッチアップロード
            eyecatch_media = upload_media(eyecatch_path)
            log(f"🖼️ アイキャッチアップ: {eyecatch_media['id']}", 1)

            # IG Feed 画像アップロード（WP記事には埋め込まないが、IGに渡すURLとして必要）
            ig_feed_media = upload_media(ig_feed_path)
            ig_feed_url = ig_feed_media["source_url"]
            log(f"📷 IG Feed画像アップ: {ig_feed_media['id']}", 1)

            # 本文構築
            photo_html = build_photo_html(photo_urls)
            content = build_content(row, eyecatch_id=eyecatch_media["id"],
                                     photo_html=photo_html)

        if existing_wp:
            pass  # WP投稿スキップ（既に上で wp_result セット済み）
        elif use_draft:
            wp_result = create_draft_post(
                title=title, content=content,
                featured_media_id=eyecatch_media["id"], slug=slug)
            log(f"📝 WP draft 投稿: post_id={wp_result['id']}", 1)
        else:
            wp_result = create_scheduled_post(
                title=title, content=content,
                featured_media_id=eyecatch_media["id"],
                publish_at_jst=publish_dt, slug=slug)
            log(f"📅 WP予約投稿: post_id={wp_result['id']} ({publish_dt.isoformat()})", 1)

        result = {
            "article_id": article_id,
            "title": title,
            "publish_at": publish_dt.isoformat(),
            "mode": mode,
            "dry_run": False,
            "wp_post_id": wp_result["id"],
            "wp_url": wp_result.get("link", ""),
            "ig_feed_url": ig_feed_url,
        }

        # Sheets 状態更新は SNS結果を見てから後ろで実行
        # （存在しないトークン等で SNS失敗→draft のまま保持できるように）

    # === wp_only モード：WP予約投稿のみ実施・SNS スキップ ===
    # 朝5時 cron 用：WP予約投稿（status=future, post_date=19:00）だけ作成
    # WPが内部の予約投稿機能で19時に自動 publish
    # SNS は後で別 cron（19時）で実行
    if wp_only:
        log(f"📌 wp-only モード：SNS投稿はスキップ（WP予約投稿のみ完了）", 1)
        log(f"   WP公開予定：{publish_dt.isoformat()}（WP内部cronで自動publish）", 2)
        log(f"   SNS投稿は post_light_article.yml の19時 cron で実行されます", 2)
        # Sheets 状態は「予約済」に更新（SNSはまだだが WP予約は完了）
        update_status(row_index, "予約済")
        log(f"📊 Sheets 状態更新: {row_index} 行目 → 予約済（WP予約のみ）", 1)
        return result

    # === Step 5: SNS連携（dry-run時 OR draft時はログのみ・公開記事の時のみ本番投稿） ===
    # draft（下書き）状態の記事はSNS本番投稿しない（公開してない記事へのリンクが死ぬため）
    sns_dry = dry_run or use_draft
    wp_url = result.get("wp_url") or f"https://toyokawa-rentallife.com/?p={result.get('wp_post_id', 'XXXXX')}"
    # IG Feed には専用の縦長画像URL（dry-run時はプレースホルダ）
    ig_post_image_url = ig_feed_url or "[IG Feed画像URL]"

    threads_caption = build_threads_caption(row, wp_url)
    ig_caption = build_instagram_caption(row, wp_url)
    x_text = build_x_caption(row, wp_url)

    log(f"🧵 Threads 投稿（dry={sns_dry}）", 1)
    threads_result = post_threads(threads_caption, dry=sns_dry)
    log(f"  → {threads_result}", 2)

    # === IG Feed カルーセル：1枚目=生成カバー、2枚目以降=番号写真(1から・豊川ガイド枠付き) ===
    # 番号写真は通常SNS記事と同じ豊川ガイド枠(上下フレーム・1080×1350)に入れてからアップ
    carousel_photos = [p for p in photos if p.stem.isdigit() and int(p.stem) >= 1]
    ig_images = [ig_feed_url] if ig_feed_url else [ig_post_image_url]
    if not sns_dry and carousel_photos:
        from photo_frame import frame_photo
        frame_month = f"{publish_dt.year}年{publish_dt.month}月"
        frame_dir = ROOT / "_sample"
        frame_dir.mkdir(parents=True, exist_ok=True)
        for p in carousel_photos:
            framed = frame_dir / f"_framed_{article_id}_{p.stem}.png"
            frame_photo(str(p), str(framed), frame_month)
            ig_images.append(upload_media(framed)["source_url"])
            log(f"  🖼️ 枠付け→アップ: {p.name}", 2)
    log(f"📷 Instagram Feed カルーセル投稿（カバー＋番号写真{len(carousel_photos)}枚・dry={sns_dry}）", 1)
    ig_feed_result = post_instagram_feed_carousel(ig_caption, ig_images, dry=sns_dry)
    log(f"  → {ig_feed_result}", 2)

    log(f"🎬 Instagram Reels 投稿（1080×1920・dry={sns_dry}）", 1)
    reel_result = post_instagram_reel_resumable(ig_caption, reel_path, dry=sns_dry)
    log(f"  → {reel_result}", 2)

    # === SNS 結果判定 → 状態更新 ===
    sns_failures = []
    if not sns_dry:
        if threads_result.get("error"):
            sns_failures.append(f"Threads: {threads_result['error']}")
        if ig_feed_result.get("error"):
            sns_failures.append(f"IG Feed: {ig_feed_result['error']}")
        if reel_result.get("status") == "error":
            sns_failures.append(f"IG Reels: {reel_result.get('error', 'unknown')}")

    # Sheets 状態更新
    # - 完全成功 → 「予約済」
    # - SNS失敗 → 「draft」のまま保持（保険cronで自動再試行可能）
    # - draft投稿 → 「draft_test」
    if not dry_run:
        if use_draft:
            update_status(row_index, "draft_test")
            log(f"📊 Sheets 状態更新: {row_index} 行目 → draft_test", 1)
        elif sns_failures:
            log(f"⚠ SNS失敗あり・状態 'draft' のまま保持（次回cronで再試行可）", 1)
            for f in sns_failures:
                log(f"  ❌ {f}", 2)
        else:
            # SNS完全成功 → 「投稿済」に更新（get_pending_rows は draft/予約済 のみ拾うので、
            # cronが遅延多重発火しても投稿済はskip＝SNS重複投稿を根絶）
            update_status(row_index, "投稿済")
            log(f"📊 Sheets 状態更新: {row_index} 行目 → 投稿済（SNS投稿完了・cron再発火でも再投稿しない）", 1)

    # === Step 6: Gmail通知（X予約用テキスト） ===
    # draft時は X通知も送らない（公開予定が確定してないため）
    log(f"📧 Gmail通知（X予約用テキスト・dry={sns_dry}）", 1)
    send_x_caption_mail(
        article_id=article_id,
        title=title,
        x_text=x_text,
        publish_at=publish_dt.isoformat(),
        wp_url=wp_url,
        dry=sns_dry,
    )

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true",
                    help="本番モード（WP予約投稿＋Sheets更新）")
    ap.add_argument("--draft", action="store_true",
                    help="WP draft 投稿（テスト用・公開されない）")
    ap.add_argument("--x-only", action="store_true",
                    help="X予約用テキストだけGmail通知（WP/SNSは投稿しない）")
    ap.add_argument("--skip-if-published", action="store_true",
                    help="WPに同slug の publish 記事が既にあれば WP工程スキップ→SNSだけ実行（保険cron救済用）")
    ap.add_argument("--wp-only", action="store_true",
                    help="WP予約投稿のみ作成・SNS投稿はスキップ（朝5時 cron 用・WP内部で19時公開）")
    ap.add_argument("--date", help="target date (YYYY-MM-DD・指定なら翌日以外)")
    ap.add_argument("--max", type=int, default=1,
                    help="最大処理件数（デフォルト1）")
    ap.add_argument("--id", help="特定 ID のみ強制処理（状態無視・再生成用）")
    args = ap.parse_args()

    x_only = getattr(args, "x_only", False)
    skip_if_published = getattr(args, "skip_if_published", False)
    wp_only = getattr(args, "wp_only", False)
    # wp_only も実投稿モード扱い
    dry_run = not (args.publish or args.draft or x_only or wp_only)
    use_draft = args.draft

    # ─────────────────────────────────────────────────────────
    # 🚨 GHA cron 遅延発火ガード（2026-06-02 朝公開バグ対策）
    # ─────────────────────────────────────────────────────────
    # GHA schedule cron は最大5-6時間遅延で発火することがある。
    # 6/1 19:00 JST 予定の cron が 6/2 00:58/01:20/01:30/03:39 JST に発火し、
    # 「今日==6/2」と判定して LR006 を深夜に publish → IG/Threadsに朝公開された。
    #
    # 対策：publish モード時のみ、JST 18:30〜23:00 範囲外なら skip。
    # - wp_only モード（朝5時 占い cron 内）は対象外（WP予約投稿のみで SNS は出ない）
    # - dry-run / draft / x-only / workflow_dispatch / ローカル実行は対象外
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not (dry_run or use_draft or x_only or wp_only):
        now_jst = datetime.now(JST)
        # ライト記事 publish cron 想定範囲：JST 18:30 〜 23:00（多少の遅延許容）
        in_range = (now_jst.hour == 18 and now_jst.minute >= 30) or (19 <= now_jst.hour < 23)
        if not in_range:
            print("=" * 60)
            print(" 🚨 GHA cron 遅延発火検出 → スキップ")
            print("=" * 60)
            print(f"  現在JST時刻: {now_jst.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  publish許可範囲: JST 18:30〜23:00")
            print(f"  → GHA schedule cron が大幅遅延した可能性。SNS朝公開防止のため skip。")
            sys.exit(0)

    target_date = None
    if args.date:
        target_date = date.fromisoformat(args.date)

    print("=" * 60)
    if x_only:
        print(" ライト記事 X予約テキスト生成（記事未作成）")
    elif dry_run:
        print(" ライト記事 投稿パイプライン（DRY-RUN・公開なし）")
    elif use_draft:
        print(" ライト記事 投稿パイプライン（WP draft 投稿・公開なし）")
    elif wp_only:
        print(" ライト記事 投稿パイプライン（WP予約投稿のみ・SNSスキップ・朝5時 cron 用）")
    else:
        print(" ライト記事 投稿パイプライン（本番予約投稿）")
    print("=" * 60)

    # ターゲット取得
    if args.id:
        # --id 指定：特定 ID を強制処理（状態無視）
        found = get_row_by_id(args.id)
        if not found:
            log(f"⚠ ID={args.id} が Sheets に見つかりません")
            return
        targets = [found]
        log(f"🎯 強制処理: ID={args.id} (行{found[0]}) 状態={found[1].get('状態','')}")
    else:
        # 通常：公開希望日 == 今日（JST）の記事を拾う
        # - wp_only モード（朝5時 cron）→ 「draft」のみ（予約済は再登録不要）
        # - 19時 cron 等 → 「draft + 予約済」両方（朝5時で予約済になった記事もSNS投稿対象）
        if wp_only:
            drafts = get_draft_rows()
            log(f"📋 Sheets draft（全件・朝5時cron用）: {len(drafts)} 件")
        else:
            drafts = get_pending_rows()
            log(f"📋 Sheets draft+予約済（全件・19時cron用）: {len(drafts)} 件")
        today_jst = datetime.now(JST).date()
        if target_date:
            today_jst = target_date
        log(f"📅 対象日: {today_jst}")

        filtered = []
        for row_idx, row in drafts:
            sheet_date_str = row.get("公開希望日", "").strip()
            if not sheet_date_str:
                continue
            d = parse_publish_date(sheet_date_str)
            if d == today_jst:
                filtered.append((row_idx, row))

        log(f"✅ 今日が公開希望日: {len(filtered)} 件")
        if not filtered:
            log("⚠ 今日公開予定の記事なし・終了")
            return
        targets = filtered[:args.max]
    results = []
    for row_idx, row in targets:
        print()
        result = process_one(row_idx, row, dry_run=dry_run,
                              use_draft=use_draft,
                              target_date=target_date,
                              x_only=x_only,
                              skip_if_published=skip_if_published,
                              wp_only=wp_only)
        results.append(result)

    print()
    print("=" * 60)
    print(" 処理結果")
    print("=" * 60)
    for r in results:
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
