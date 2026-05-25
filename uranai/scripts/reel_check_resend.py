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
    """IG 最新25投稿のうち、target_date 表記を caption に含む VIDEO/REELS があるか判定

    タイムスタンプベースの判定は Meta の UTC タイムゾーン解釈で誤検出するため、
    caption に「YYYY年M月D日」または「YYYY-MM-DD」が含まれているかで厳密判定する。
    """
    token = os.environ["META_ACCESS_TOKEN"]
    ig_id = os.getenv("INSTAGRAM_ACCOUNT_ID") or "17841467629335560"

    r = requests.get(
        f"https://graph.facebook.com/v19.0/{ig_id}/media",
        params={
            "fields": "id,media_type,timestamp,permalink,caption",
            "limit": 25,
            "access_token": token,
        },
        timeout=30,
    )
    if r.status_code != 200:
        return False, f"IG API エラー: {r.status_code} {r.text[:200]}"

    # 日付文字列パターン（caption内検索用）
    date_str_jp = f"{target_date.year}年{target_date.month}月{target_date.day}日"
    date_str_iso = target_date.strftime("%Y-%m-%d")

    for m in r.json().get("data", []):
        if m.get("media_type") not in ("VIDEO", "REELS"):
            continue
        cap = m.get("caption") or ""
        if date_str_jp in cap or date_str_iso in cap:
            return True, f"検出: {m['permalink']} (caption内に {date_str_jp})"

    return False, f"今日の Reel 未投稿（caption内に '{date_str_jp}' を持つ Reel/Video なし）"


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
    """WP メディアから 今日の Reel mp4 URL を取得（既存）"""
    fname = f"{target_date.strftime('%Y-%m-%d')}_{WD_KEY[target_date.weekday()]}_reel"
    r = requests.get(
        f"{os.environ['WP_URL']}/wp-json/wp/v2/media",
        params={"search": fname, "per_page": 5, "_fields": "id,source_url,mime_type"},
        auth=(os.environ["WP_USERNAME"], os.environ["WP_PASSWORD"]),
        timeout=30,
    )
    # ファイル名末尾に -数字が無い「元動画」を優先
    candidates = [m for m in r.json() if "video" in m.get("mime_type", "")]
    if not candidates:
        return None
    for m in candidates:
        url = m["source_url"]
        base = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if not re.search(r"-\d+$", base):
            return url
    return candidates[0]["source_url"]


def reupload_video_to_wp(original_url: str) -> str | None:
    """既存動画を新しいファイル名で WP に再アップロード（Meta キャッシュ回避）

    Meta API は失敗した URL を一定時間 blacklist する仕様（推定）。
    同じ動画を別ファイル名で再アップして、新URLで投稿し直すと成功する
    （5/24 同パターンで実証済み）。

    Returns: 新しい source_url（失敗時 None）
    """
    print(f"  → 元動画 DL: {original_url}")
    r = requests.get(original_url, timeout=120)
    if r.status_code != 200:
        print(f"  ❌ 元動画 DL 失敗: {r.status_code}")
        return None
    video_bytes = r.content
    print(f"  → 元動画 DL 成功: {len(video_bytes) / 1024 / 1024:.1f} MB")

    # 新ファイル名（タイムスタンプ付きでユニーク化）
    orig_name = original_url.rsplit("/", 1)[-1]  # 例: 2026-05-25_mon_reel.mp4
    base, ext = orig_name.rsplit(".", 1)
    # 既存に -数字 がある場合は剥がしてから付け直す
    base_clean = re.sub(r"-\d+$", "", base)
    ts_suffix = datetime.now(JST).strftime("%H%M")  # 例: 1130
    new_name = f"{base_clean}-retry{ts_suffix}.{ext}"
    print(f"  → 新ファイル名: {new_name}")

    headers = {
        "Authorization": _basic_auth_header(),
        "Content-Disposition": f'attachment; filename="{new_name}"',
        "Content-Type": "video/mp4",
    }
    r2 = requests.post(
        f"{os.environ['WP_URL']}/wp-json/wp/v2/media",
        headers=headers, data=video_bytes, timeout=300,
    )
    if r2.status_code not in (200, 201):
        print(f"  ❌ WP メディア再アップ失敗: {r2.status_code} {r2.text[:300]}")
        return None
    new_url = r2.json().get("source_url")
    print(f"  ✅ WP メディア再アップ成功: {new_url}")
    return new_url


def _basic_auth_header() -> str:
    """Basic Auth ヘッダー生成"""
    import base64
    u = os.environ["WP_USERNAME"]
    p = os.environ["WP_PASSWORD"]
    token = base64.b64encode(f"{u}:{p}".encode()).decode()
    return f"Basic {token}"


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


def resend_reel(target_date: date, reupload: bool = True) -> dict:
    """Reels 単独再投稿実行（Resumable Upload 経由）

    Args:
        reupload: 互換性のため引数残すが、Resumable Upload 採用以降は WP 再アップ不要

    2026-05-25: External URL 方式が連続失敗 → Resumable Upload に切替。
    WP から動画 DL → 一時パスに保存 → Resumable で Meta に直接 POST。
    """
    import tempfile

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

    # 3. 動画URL取得 → ローカルに DL（一時ファイル）
    original_url = find_reel_video_url(target_date)
    if not original_url:
        return {"status": "error", "error": "WP に Reel mp4 が見つからない"}

    print(f"\n[動画DL] {original_url}")
    r = requests.get(original_url, timeout=180)
    if r.status_code != 200:
        return {"status": "error", "error": f"動画DL失敗: {r.status_code}"}

    tmp_dir = Path(tempfile.gettempdir()) / "uranai_reel_resend"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{target_date}_reel.mp4"
    tmp_path.write_bytes(r.content)
    print(f"  → 一時保存: {tmp_path} ({len(r.content) / 1024 / 1024:.1f} MB)")

    # 4. Spot, data 準備
    class Spot:
        def __init__(self, name, is_chain=False):
            self.name = name
            self.is_chain = is_chain

    spot = Spot(name=spot_name, is_chain=False)
    article_data = {"items": items}
    weekday_key = WD_KEY[target_date.weekday()]

    # 5. Reels 投稿（Resumable Upload）
    from post_instagram_uranai import post_instagram_uranai_reel_resumable
    print(f"  → Reels 投稿開始（Resumable Upload）")
    result = post_instagram_uranai_reel_resumable(
        weekday_key=weekday_key,
        data=article_data,
        spot=spot,
        target_date=target_date,
        video_path=tmp_path,
        cover_path=None,
        dry=False,
    )

    # 一時ファイル削除
    try:
        tmp_path.unlink()
    except Exception:
        pass

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
