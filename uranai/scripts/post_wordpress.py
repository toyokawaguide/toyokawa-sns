"""
占い記事の WordPress 投稿（claude/wp_post.py 流用）
=====================================================

占いカテゴリ（slug=uranai）付きで記事を投稿する。
認証情報は .env の WP_URL / WP_USERNAME / WP_PASSWORD を使用。

【公開関数】
- post_uranai_to_wp(title, content, image_path, status="publish") -> str  (記事URL)

Phase 3 で main.py から import して使う想定。
GitHub Actions 上では toyokawa-sns/uranai/ 配下に配置して動かす。
"""
from __future__ import annotations
import os
import sys
import json
import base64
from pathlib import Path
import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(override=True)  # OS環境変数干渉を避ける（feedback_python_dotenv_override.md）

WP_URL = os.getenv("WP_URL")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_PASSWORD = os.getenv("WP_PASSWORD")

CACHE_FILE = Path(__file__).resolve().parent / "_wp_category_cache.json"


def _auth_headers(content_type: str = "application/json") -> dict:
    creds = f"{WP_USERNAME}:{WP_PASSWORD}"
    token = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": content_type}


def get_uranai_category_id() -> int:
    """占いカテゴリ（slug=uranai）の ID を取得（キャッシュあり）"""
    if CACHE_FILE.exists():
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if "uranai" in cache:
            return cache["uranai"]

    response = requests.get(
        f"{WP_URL}/wp-json/wp/v2/categories",
        params={"slug": "uranai"},
        headers=_auth_headers(),
        timeout=15,
    )
    response.raise_for_status()
    items = response.json()
    if not items:
        raise RuntimeError("WordPress に占いカテゴリ（slug=uranai）が存在しません。setup_wp_category.py を先に実行してください")

    cat_id = items[0]["id"]
    CACHE_FILE.write_text(json.dumps({"uranai": cat_id}), encoding="utf-8")
    return cat_id


def upload_image(image_path: str | Path) -> int:
    """画像をWP メディアライブラリにアップロード → media_id を返す"""
    image_path = Path(image_path)
    with open(image_path, "rb") as f:
        data = f.read()
    headers = _auth_headers("image/png")
    headers["Content-Disposition"] = f'attachment; filename="{image_path.name}"'
    response = requests.post(
        f"{WP_URL}/wp-json/wp/v2/media",
        headers=headers,
        data=data,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["id"]


def post_uranai_to_wp(
    title: str,
    content: str,
    image_path: str | Path | None = None,
    status: str = "publish",
    slug: str | None = None,
) -> dict:
    """占い記事を WP に投稿する

    Args:
        title: 記事タイトル
        content: 本文（HTML or Markdown）
        image_path: アイキャッチ画像のローカルパス
        status: "publish" or "draft"
        slug: パーマリンク用スラッグ（A案: uranai-YYYYMMDD）

    Returns:
        {"id": int, "url": str, "status": str}
    """
    media_id = upload_image(image_path) if image_path else None
    cat_id = get_uranai_category_id()

    data = {
        "title": title,
        "content": content,
        "status": status,
        "categories": [cat_id],
    }
    if media_id:
        data["featured_media"] = media_id
    if slug:
        data["slug"] = slug

    response = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts",
        json=data,
        headers=_auth_headers(),
        timeout=60,
    )
    response.raise_for_status()
    post = response.json()
    return {
        "id": post["id"],
        "url": post["link"],
        "status": post["status"],
    }


if __name__ == "__main__":
    # 簡易テスト（dry-run・実際の投稿はしない）
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-cat", action="store_true", help="占いカテゴリIDを取得")
    args = parser.parse_args()
    if args.check_cat:
        try:
            cid = get_uranai_category_id()
            print(f"占いカテゴリID: {cid}")
        except Exception as e:
            print(f"[ERROR] {e}")
    else:
        print("usage: python post_wordpress.py --check-cat")
