"""
wp_client.py — WordPress REST API クライアント

【機能】
- 翌日19時 手動投稿チェック
- メディアアップロード
- 予約投稿作成
- 「お知らせ」(news) カテゴリ ID 取得
"""
from __future__ import annotations
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

# load .env from claude/ folder (1階層上)
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

WP_URL = os.environ.get("WP_URL", "https://toyokawa-rentallife.com")
WP_USER = os.environ.get("WP_USERNAME")
WP_PASS = os.environ.get("WP_PASSWORD")
JST = timezone(timedelta(hours=9))

# 「お知らせ」カテゴリ slug = news（既存・グノシー告知時に使用）
NEWS_CATEGORY_SLUG = "news"

# ライト記事専用タグ（手動投稿のお知らせと識別するため自動付与）
SAKUTTO_TAG_ID = 720  # slug=sakutto / name=さくっと


def get_auth():
    if not WP_USER or not WP_PASS:
        raise RuntimeError("WP_USERNAME / WP_PASSWORD が未設定です（.env）")
    return HTTPBasicAuth(WP_USER, WP_PASS)


def get_news_category_id() -> int:
    """お知らせカテゴリの ID を取得"""
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/categories",
        params={"slug": NEWS_CATEGORY_SLUG},
        auth=get_auth(),
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise RuntimeError(f"カテゴリ slug={NEWS_CATEGORY_SLUG} が見つかりません")
    return data[0]["id"]


def check_manual_post_scheduled(target_date: date) -> bool:
    """指定日19:00公開予定の future 投稿（手動）が「お知らせ」カテゴリに既にあるかチェック

    自動投稿は Sheets 経由で「予約済」状態が更新されるが、
    社長手動投稿は WP 管理画面から直接予約されるため、
    WP の future ステータス＋お知らせカテゴリ＋指定日19時 で検知する。
    """
    cat_id = get_news_category_id()

    # 検索範囲：target_date 18:30 〜 19:30 JST
    start_jst = datetime.combine(target_date, time(18, 30), tzinfo=JST)
    end_jst = datetime.combine(target_date, time(19, 30), tzinfo=JST)

    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts",
        params={
            "categories": cat_id,
            "status": "future",
            "after": start_jst.isoformat(),
            "before": end_jst.isoformat(),
            "per_page": 5,
        },
        auth=get_auth(),
        timeout=30,
    )
    r.raise_for_status()
    posts = r.json()
    return len(posts) > 0


def upload_media(image_path: Path, caption: str = "") -> dict:
    """画像をWPメディアにアップロード → {id, source_url} を返す"""
    if not image_path.exists():
        raise FileNotFoundError(image_path)

    headers = {
        "Content-Disposition": f'attachment; filename="{image_path.name}"',
        "Content-Type": "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg",
    }
    with image_path.open("rb") as f:
        r = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            headers=headers,
            data=f.read(),
            auth=get_auth(),
            timeout=120,
        )
    r.raise_for_status()
    data = r.json()
    return {"id": data["id"], "source_url": data["source_url"]}


def create_scheduled_post(*, title: str, content: str, featured_media_id: int,
                          publish_at_jst: datetime,
                          status: str = "future",
                          slug: str = None) -> dict:
    """お知らせカテゴリで予約投稿を作成・「さくっと」タグ自動付与"""
    cat_id = get_news_category_id()
    payload = {
        "title": title,
        "content": content,
        "status": status,  # "future" で予約 / "draft" で下書き
        "categories": [cat_id],
        "tags": [SAKUTTO_TAG_ID],  # ライト記事専用タグ
        "featured_media": featured_media_id,
        "date": publish_at_jst.isoformat(),
    }
    if slug:
        payload["slug"] = slug

    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts",
        json=payload,
        auth=get_auth(),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def find_published_post_by_slug(slug: str) -> dict | None:
    """slug で publish/future の WP 投稿を検索（重複公開防止用）

    publish だけでなく future（予約投稿）も検知することで、
    WP自動公開とcronのタイミングずれによる重複リスクをゼロにする。

    戻り値: {"id": post_id, "link": url, "title": ...} or None
    """
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts",
        params={"slug": slug, "status": "publish,future"},
        auth=get_auth(),
        timeout=30,
    )
    r.raise_for_status()
    posts = r.json()
    if not posts:
        return None
    p = posts[0]
    return {
        "id": p["id"],
        "link": p.get("link", ""),
        "title": p.get("title", {}).get("rendered", ""),
        "date": p.get("date", ""),
        "status": p.get("status", ""),
    }


def create_draft_post(*, title: str, content: str, featured_media_id: int,
                       slug: str = None) -> dict:
    """draft（下書き）で投稿を作成（テスト用）・「さくっと」タグ自動付与"""
    cat_id = get_news_category_id()
    payload = {
        "title": title,
        "content": content,
        "status": "draft",
        "categories": [cat_id],
        "tags": [SAKUTTO_TAG_ID],  # ライト記事専用タグ
        "featured_media": featured_media_id,
    }
    if slug:
        payload["slug"] = slug

    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts",
        json=payload,
        auth=get_auth(),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()
