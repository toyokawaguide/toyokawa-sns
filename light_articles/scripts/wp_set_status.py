# -*- coding: utf-8 -*-
"""
wp_set_status.py — WordPress 記事のステータス変更（非公開化・下書き戻し・再公開）

【用途】
誤投稿・急ぎの取り下げ時に、WP管理画面を開かずに GHA から記事を
private（非公開）/ draft（下書き）/ publish（公開）へ切り替える。
本文・画像・SNS投稿には一切触れない。

【使い方】
python wp_set_status.py --post-id 36017 --status private
python wp_set_status.py --slug pr008 --status private
python wp_set_status.py --slug pr008 --status private --dry-run
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from wp_client import WP_URL, _request, get_auth  # noqa: E402

ALLOWED_STATUS = ("private", "draft", "publish")


def find_post(post_id: int | None, slug: str | None) -> dict:
    """post_id または slug で記事を1件取得（全ステータス対象）"""
    if post_id:
        r = _request("GET", f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
                     params={"context": "edit"},
                     auth=get_auth(), timeout=30, what="記事取得")
        r.raise_for_status()
        return r.json()
    r = _request("GET", f"{WP_URL}/wp-json/wp/v2/posts",
                 params={"slug": slug, "status": "any", "context": "edit",
                         "per_page": 5},
                 auth=get_auth(), timeout=30, what="記事検索")
    r.raise_for_status()
    posts = r.json()
    if not posts:
        raise RuntimeError(f"slug={slug} の記事が見つかりません")
    if len(posts) > 1:
        ids = ", ".join(f"{p['id']}({p['status']})" for p in posts)
        raise RuntimeError(f"slug={slug} が複数あります → --post-id で指定してください: {ids}")
    return posts[0]


def set_status(post_id: int, status: str) -> dict:
    r = _request("POST", f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
                 json={"status": status},
                 auth=get_auth(), timeout=60, what="ステータス変更")
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser(description="WP記事のステータス変更")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--post-id", type=int, help="WP投稿ID（例: 36017）")
    g.add_argument("--slug", help="記事slug（例: pr008）")
    ap.add_argument("--status", required=True, choices=ALLOWED_STATUS,
                    help="private=非公開 / draft=下書き / publish=公開")
    ap.add_argument("--dry-run", action="store_true", help="変更せず対象確認のみ")
    args = ap.parse_args()

    post = find_post(args.post_id, args.slug)
    title = post.get("title", {}).get("rendered") or post.get("title", {}).get("raw", "")
    print(f"📰 対象: id={post['id']} slug={post.get('slug')} status={post['status']}")
    print(f"   タイトル: {title}")
    print(f"   日時: {post.get('date')}  URL: {post.get('link')}")

    if post["status"] == args.status:
        print(f"ℹ️ 既に status={args.status} です。変更なし。")
        return 0
    if args.dry_run:
        print(f"🔍 dry-run: {post['status']} → {args.status}（未実行）")
        return 0

    updated = set_status(post["id"], args.status)
    print(f"✅ 変更完了: {post['status']} → {updated['status']}  (id={updated['id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
