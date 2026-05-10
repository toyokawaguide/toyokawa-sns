"""
Threads への占い投稿
======================

main.py から呼ばれる。Threads API で投稿。
.env から認証情報読込：THREADS_ACCESS_TOKEN / THREADS_USER_ID

API は2段階：①コンテナ作成 ②公開
"""
from __future__ import annotations
import os
from datetime import date

import requests

from caption import make_threads_caption

API_BASE = "https://graph.threads.net/v1.0"


def post_threads_uranai(*, weekday_key: str, data: dict, spot, target_date: date,
                         post_url: str, dry: bool = False) -> dict:
    """Threads に投稿
    Returns: {"status": "ok"/"dry"/"error", "post_id": str|None, "caption": str}
    """
    caption = make_threads_caption(weekday_key, data, spot, target_date, post_url)

    if dry:
        return {"status": "dry", "post_id": None, "caption": caption}

    token = os.getenv("THREADS_ACCESS_TOKEN")
    user_id = os.getenv("THREADS_USER_ID")
    if not token or not user_id:
        return {"status": "error", "post_id": None, "caption": caption,
                "error": "THREADS_ACCESS_TOKEN / THREADS_USER_ID 未設定"}

    try:
        # Step1: コンテナ作成
        r1 = requests.post(f"{API_BASE}/{user_id}/threads", params={
            "media_type": "TEXT",
            "text": caption,
            "access_token": token,
        }, timeout=30)
        if r1.status_code != 200:
            return {"status": "error", "post_id": None, "caption": caption,
                    "error": f"container failed: {r1.status_code} {r1.text[:200]}"}
        container_id = r1.json()["id"]

        # Step2: 公開
        r2 = requests.post(f"{API_BASE}/{user_id}/threads_publish", params={
            "creation_id": container_id,
            "access_token": token,
        }, timeout=30)
        if r2.status_code != 200:
            return {"status": "error", "post_id": None, "caption": caption,
                    "error": f"publish failed: {r2.status_code} {r2.text[:200]}"}

        post_id = str(r2.json()["id"])
        return {"status": "ok", "post_id": post_id, "caption": caption}
    except Exception as e:
        return {"status": "error", "post_id": None, "caption": caption, "error": str(e)}
