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

        # Step1.5: コンテナが FINISHED になるまで待つ（2026-10-02 事故：作成直後に publish → 400 "Media Not Found"
        #   code 24 / subcode 4279009。Threads公式も「公開前に状態確認・数秒待つ」を推奨）
        import time as _t
        for _ in range(12):
            try:
                st = requests.get(f"{API_BASE}/{container_id}", params={"fields": "status,error_message", "access_token": token}, timeout=30).json()
                if st.get("status") in ("FINISHED", "PUBLISHED"):
                    break
                if st.get("status") == "ERROR":
                    return {"status": "error", "post_id": None, "caption": caption, "error": f"container error: {st.get('error_message')}"}
            except Exception:
                pass
            _t.sleep(5)

        # Step2: 公開（Media Not Found 等の一時エラーは 10秒おきに最大5回やり直す）
        last = None
        for i in range(5):
            r2 = requests.post(f"{API_BASE}/{user_id}/threads_publish", params={
                "creation_id": container_id,
                "access_token": token,
            }, timeout=30)
            if r2.status_code == 200:
                post_id = str(r2.json()["id"])
                return {"status": "ok", "post_id": post_id, "caption": caption}
            last = f"publish failed: {r2.status_code} {r2.text[:200]}"
            if r2.status_code not in (400, 500, 502, 503, 504):
                break
            _t.sleep(10)
        return {"status": "error", "post_id": None, "caption": caption, "error": last}
    except Exception as e:
        return {"status": "error", "post_id": None, "caption": caption, "error": str(e)}
