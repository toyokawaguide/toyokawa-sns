# -*- coding: utf-8 -*-
"""
publish_bukken_article.py — さくっと物件紹介 自動投稿（2026-11-11・さくっとPRの配信を土台にした別系統）

【動作】毎日13:00 JST（GHA cron）。キューに 状態=draft かつ 公開希望日=今日 の行がある日だけ動く
1. Sheets「物件紹介キュー」から対象の行を1件
2. 写真（G:\\マイドライブ\\さくっと物件紹介\\{ID}_{物件名}\\ または Drive API）
   0番＝カード類の表紙専用（任意）／1〜3番＝ほめポイント①②③の写真／4番以降＝おまけ
3. アイキャッチ16:9・IG 4:5・リール（さくっとPRと同じ絵・色はすみれ）
4. WP予約投稿（カテゴリ=chintai・13:00・slug=bk001 形式）
5. Threads／IGフィード（カルーセル）／IGリール
6. Sheets 状態=投稿済＋X投稿文をGmailで自分あてに送る

【止めるとき】ほめ言葉に「最高」「日本一」「格安」など根拠なしで使えない言葉がある／必須の項目が空
   → 何も投稿せずエラー終了（GHAの失敗メールが届く）。確認済みなら備考に「言葉チェック済」と書く

【使い方】
python publish_bukken_article.py                    # dry-run（何も投稿しない）
python publish_bukken_article.py --draft --id BK001 # WPに下書きだけ作る（SNSなし）
python publish_bukken_article.py --publish          # 本番
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sheets_client import read_all_rows, update_status
import bukken_builder as bb
import series
series.set_label(bb.LABEL)
import pr_eyecatch
pr_eyecatch.SERIES_NAME = bb.LABEL          # 画像の右下などのシリーズ名
from sns_clients import (post_threads, post_instagram_feed,
                         post_instagram_feed_carousel,
                         post_instagram_reel_resumable,
                         post_instagram_reel_by_url)
from generate_reel import render_static_reel
from publish_light_article import get_photo_paths, parse_publish_date

SHEET = "物件紹介キュー"
SPREADSHEET_ID = (ROOT / "_bukken_sheet_id.txt").read_text(encoding="utf-8").strip()
PHOTO_BASE = Path("G:/マイドライブ/さくっと物件紹介")
DRIVE_ROOT_NAME = "さくっと物件紹介"
CATEGORY_SLUG = "chintai"
JST = timezone(timedelta(hours=9))
PUBLISH_HOUR = 13


def log(msg: str, indent: int = 0):
    print("  " * indent + msg)


def get_photos(article_id: str, name: str) -> list[Path]:
    if PHOTO_BASE.exists():
        cands = [c for c in sorted(PHOTO_BASE.glob(f"{article_id}_*")) if c.is_dir()]
        if cands:
            import folder_match
            folder_match.verify(article_id, cands[0].name, name)
            photos = get_photo_paths(cands[0])
            log(f"📸 写真: {len(photos)}枚 ({cands[0].name}) [ローカル]", 1)
            return photos
        log("📸 写真なし（フォルダなし）", 1)
        return []
    try:
        from drive_client import fetch_article_photos
        photos = fetch_article_photos(article_id, ROOT / "_drive_cache" / article_id, title=name,
                                      root_name=DRIVE_ROOT_NAME)
        log(f"📸 写真: {len(photos)}枚 [Drive]", 1)
        return photos
    except RuntimeError:
        raise               # フォルダ名と物件名が合わない → 中止（別の物件の写真を載せない）
    except Exception as e:
        log(f"⚠ Drive取得失敗（写真なしで続行）: {e}", 1)
        return []


def rows_for(target: date) -> list[tuple[int, dict]]:
    out = []
    for i, row in enumerate(read_all_rows(sheet=SHEET, spreadsheet_id=SPREADSHEET_ID), start=2):
        if (row.get("状態") or "").strip() != "draft":
            continue
        if parse_publish_date((row.get("公開希望日") or "").strip()) == target:
            out.append((i, row))
    return out


def check_row(row: dict) -> list:
    """配信してよい中身か。問題の一覧を返す（空ならOK）"""
    errs = []
    for k in ("物件名", "ひとことキャッチ", "ほめ1見出し", "ほめ1本文"):
        if not (row.get(k) or "").strip():
            errs.append(f"「{k}」が空です")
    if (row.get("種別") or "").strip() not in ("勝手に紹介", "依頼掲載"):
        errs.append("「種別」は 勝手に紹介 か 依頼掲載 のどちらかにしてください")
    if bb.is_ad(row) and not (row.get("問い合わせ") or "").strip():
        errs.append("依頼掲載なのに「問い合わせ」が空です")
    ng = bb.find_ng_words(row)
    if ng and "言葉チェック済" not in (row.get("備考") or ""):
        errs.append("根拠なしでは使えない言葉が入っています: " + "・".join(ng) + "（問題なければ備考に「言葉チェック済」）")
    return errs


def send_x_mail(article_id: str, title: str, x_text: str, wp_url: str, dry: bool):
    subject = f"【{bb.LABEL}】{article_id} 公開しました・X投稿文"
    body = (f"{bb.LABEL}を公開しました。Xは手動です（下の文をコピーして投稿・予約してください）。\n\n"
            f"ID: {article_id}\nタイトル: {title}\n記事: {wp_url}\n\n"
            f"------------ コピペ用 ------------\n{x_text}\n------------ ここまで ------------\n")
    if dry:
        log(f"[DRY][Gmail] {subject}", 1)
        return
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not pw:
        log("⚠ GMAIL_USER / GMAIL_APP_PASSWORD 未設定 → メールなし", 1)
        return
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"], msg["From"], msg["To"] = subject, user, user
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(user, pw)
            s.send_message(msg)
        log("📧 X投稿文をメール送信", 1)
    except Exception as e:
        log(f"⚠ メール失敗（続行）: {e}", 1)


def render_images(row: dict, photos: list[Path], article_id: str) -> dict:
    """表紙類を作る。0番があればカード類は0番、無ければ1番を使う"""
    out = ROOT / "_sample"
    out.mkdir(exist_ok=True)
    cr = bb.card_row(row)
    cover = next((p for p in photos if int(p.stem) == 0), None) or next((p for p in photos if int(p.stem) >= 1), None)
    paths = {"eyecatch": out / f"_tmp_{article_id}_eyecatch.png", "ig": out / f"_tmp_{article_id}_ig_feed.png",
             "reel": out / f"_tmp_{article_id}_reel.mp4", "card_row": cr, "cover": cover}
    pr_eyecatch.render_169(cr, photo_path=cover, output_path=paths["eyecatch"])
    pr_eyecatch.render_45(cr, photo_path=cover, output_path=paths["ig"])
    render_static_reel(pr_eyecatch.render_reel_frame(cr, photo_path=cover), paths["reel"])
    log(f"🎨 アイキャッチ・IG 4:5・リール（表紙の写真: {cover.name if cover else 'なし'}）", 1)
    return paths


def process_row(row_index: int, row: dict, *, dry_run: bool, use_draft: bool, target_date: date) -> dict:
    article_id = (row.get("ID") or "?").strip()
    name = (row.get("物件名") or "?").strip()
    log(f"📝 {bb.LABEL} 処理開始: {article_id} - {name}（{(row.get('種別') or '').strip()}）")

    errs = check_row(row)
    if errs:
        for e in errs:
            log(f"❌ {e}", 1)
        raise SystemExit(f"❌ {article_id}: 中身に問題があるので配信しません（上の内容を直してください）")

    publish_dt = datetime.combine(target_date, time(PUBLISH_HOUR, 0), tzinfo=JST)
    photos = get_photos(article_id, name)
    body_photos = [p for p in photos if int(p.stem) >= 1]
    img = render_images(row, photos, article_id)
    title = bb.build_title(row)
    slug = article_id.lower()
    log(f"📰 タイトル: {title}", 1)

    if dry_run:
        url = f"https://toyokawa-rentallife.com/{publish_dt:%Y/%m/%d}/{slug}/"
        content = bb.build_content(row, photo_urls=["(dry-photo)"] * len(body_photos))
        for label, text in (("X", bb.build_x_caption(row, url)), ("Threads", bb.build_threads_caption(row, url)),
                            ("Instagram", bb.build_instagram_caption(row, url))):
            print(f"\n---------- [DRY] {label} ----------\n{text}")
        print(f"\n[DRY] X字数 {bb.x_weight(bb.build_x_caption(row, url))}/280・本文 {len(content)}字・公開予定 {publish_dt.isoformat()}")
        return {"article_id": article_id, "dry_run": True, "title": title}

    from wp_client import upload_media, find_published_post_by_slug, create_scheduled_post_generic

    existing = None if use_draft else find_published_post_by_slug(slug)
    if existing:
        log(f"⏭️ WP既存（post_id={existing['id']}）→ SNSのみ実行", 1)
        wp_result = {"id": existing["id"], "link": existing["link"]}
    else:
        photo_urls = []
        for p in body_photos:
            m = upload_media(p)
            photo_urls.append(m["source_url"])
            log(f"📤 写真アップ: {p.name} → {m['id']}", 2)
        eyecatch_media = upload_media(img["eyecatch"])
        wp_result = create_scheduled_post_generic(
            title=title, content=bb.build_content(row, photo_urls=photo_urls),
            featured_media_id=eyecatch_media["id"], publish_at_jst=publish_dt,
            category_slug=CATEGORY_SLUG, status="draft" if use_draft else "future", slug=slug,
        )
        log(f"✅ WP{'下書き' if use_draft else '予約'}投稿: post_id={wp_result['id']}", 1)
    wp_url = wp_result.get("link") or f"https://toyokawa-rentallife.com/{slug}/"
    x_text = bb.build_x_caption(row, wp_url)

    if use_draft:
        log("（下書きテストなのでSNSは投稿しません）", 1)
        print(f"\n---------- X 投稿用 ----------\n{x_text}")
        return {"article_id": article_id, "wp_post_id": wp_result["id"], "wp_url": wp_url, "title": title}

    ig_feed_url = upload_media(img["ig"])["source_url"]
    ig_text = bb.build_instagram_caption(row, wp_url)
    try:
        log(f"🧵 Threads: {post_threads(bb.build_threads_caption(row, wp_url), image_url=ig_feed_url, dry=False)}", 1)
    except Exception as e:
        log(f"⚠ Threads失敗（続行）: {e}", 1)
    try:
        ig_images = [ig_feed_url]
        for p in body_photos[:9]:          # カルーセルは表紙＋9枚まで
            framed = ROOT / "_sample" / f"_framed_{article_id}_{p.stem}.png"
            pr_eyecatch.render_carousel_photo(img["card_row"], p, framed)
            ig_images.append(upload_media(framed)["source_url"])
        if len(ig_images) > 1:
            r2 = post_instagram_feed_carousel(ig_text, ig_images, dry=False)
        else:
            r2 = post_instagram_feed(ig_text, image_url=ig_feed_url, dry=False)
        log(f"📷 IGフィード（{len(ig_images)}枚）: {r2}", 1)
    except Exception as e:
        log(f"⚠ IGフィード失敗（続行）: {e}", 1)
    try:
        rr = post_instagram_reel_resumable(ig_text, img["reel"], dry=False)
        log(f"🎬 IGリール: {rr}", 1)
        if rr.get("error"):
            fb = post_instagram_reel_by_url(ig_text, upload_media(Path(img["reel"]))["source_url"], dry=False)
            log(f"  ↻ 公開URL方式でやり直し: {fb}", 2)
    except Exception as e:
        log(f"⚠ リール失敗（続行）: {e}", 1)

    try:
        update_status(row_index, "投稿済", sheet=SHEET, spreadsheet_id=SPREADSHEET_ID)
        log("📋 Sheets 状態=投稿済", 1)
    except Exception as e:
        log(f"⚠ Sheets更新失敗（続行）: {e}", 1)
    send_x_mail(article_id, title, x_text, wp_url, dry=False)
    print(f"\n---------- X 投稿用 ----------\n{x_text}")
    return {"article_id": article_id, "wp_post_id": wp_result["id"], "wp_url": wp_url, "title": title}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="本番投稿")
    ap.add_argument("--draft", action="store_true", help="WPに下書きだけ作る（SNSなし）")
    ap.add_argument("--id", help="特定のIDだけ処理（状態・日付を見ない）")
    ap.add_argument("--date", help="公開日の上書き YYYY-MM-DD")
    a = ap.parse_args()
    dry_run = not (a.publish or a.draft)
    target = parse_publish_date(a.date) if a.date else datetime.now(JST).date()

    if a.id:
        rows = read_all_rows(sheet=SHEET, spreadsheet_id=SPREADSHEET_ID)
        targets = [(i, r) for i, r in enumerate(rows, start=2) if (r.get("ID") or "").strip().upper() == a.id.upper()][:1]
        if not targets:
            print(f"❌ {a.id} がキューに見つかりません")
            return
    else:
        targets = rows_for(target)
    if not targets:
        print(f"📭 {target} の{bb.LABEL}はありません（正常終了）")
        return
    for row_index, row in targets[:1]:      # 1日1件
        process_row(row_index, row, dry_run=dry_run, use_draft=a.draft, target_date=target)


if __name__ == "__main__":
    main()
