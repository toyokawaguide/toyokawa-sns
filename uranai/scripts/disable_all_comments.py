"""既存の全投稿・固定ページのコメント/ピンを一括で締め切る（一回限りメンテ）

2026-05-18 社長判断B：地域情報サイトで読者コメント実績ゼロ・スパムのみ→
サイト全体コメント無効化。設定の新規既定は別途closed済。本スクリプトは
既存記事（占いdraft含む全status）を comment_status=closed に揃える。
既にclosedはスキップ（冪等）。
"""
from __future__ import annotations
import sys
import os
import time
from pathlib import Path

import requests
import base64
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(Path("C:/Users/Yoshida/Desktop/豊川ガイド/占い/scripts/.env"), override=True)

WP = os.getenv("WP_URL")
U = os.getenv("WP_USERNAME")
P = os.getenv("WP_PASSWORD")
H = {"Authorization": "Basic " + base64.b64encode(f"{U}:{P}".encode()).decode()}
HJ = {**H, "Content-Type": "application/json"}


def process(endpoint: str) -> tuple[int, int, int]:
    """endpoint(posts|pages) を全status走査し comment/ping を closed に"""
    page = 1
    seen = updated = skipped = 0
    while True:
        r = requests.get(
            f"{WP}/wp-json/wp/v2/{endpoint}",
            params={"per_page": 100, "page": page, "status": "any",
                    "context": "edit", "_fields": "id,comment_status,ping_status"},
            headers=H, timeout=30,
        )
        if r.status_code != 200:
            print(f"[{endpoint}] page{page} GET {r.status_code} {r.text[:120]}")
            break
        items = r.json()
        if not items:
            break
        for it in items:
            seen += 1
            if it.get("comment_status") == "closed" and it.get("ping_status") == "closed":
                skipped += 1
                continue
            pid = it["id"]
            u = requests.post(
                f"{WP}/wp-json/wp/v2/{endpoint}/{pid}",
                json={"comment_status": "closed", "ping_status": "closed"},
                headers=HJ, timeout=30,
            )
            if u.status_code == 200:
                updated += 1
            else:
                print(f"[{endpoint}] id={pid} 更新失敗 {u.status_code}")
            time.sleep(0.15)  # WAF/負荷配慮
        print(f"[{endpoint}] page{page} 済 (seen={seen} updated={updated} skipped={skipped})")
        page += 1
    return seen, updated, skipped


def main() -> None:
    if not (WP and U and P):
        print("WP認証情報なし")
        sys.exit(1)
    total_seen = total_upd = total_skip = 0
    for ep in ("posts", "pages"):
        s, u, k = process(ep)
        total_seen += s
        total_upd += u
        total_skip += k
        print(f"=== {ep} 完了: 走査{s} 更新{u} スキップ{k} ===")
    print(f"\n=== 全完了: 走査{total_seen} 更新{total_upd} 既closed{total_skip} ===")


if __name__ == "__main__":
    main()
