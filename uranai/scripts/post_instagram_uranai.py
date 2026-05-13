"""
Instagram への占い投稿
========================

main.py から呼ばれる。Meta Graph API で feed 投稿。
.env から認証情報読込：META_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID

WP にアップした画像URLをそのまま image_url として渡す（GitHub Pages 不要）。
"""
from __future__ import annotations
import os
import time
from datetime import date

import requests

from caption import make_instagram_caption, make_instagram_reel_caption

GRAPH_API = "https://graph.facebook.com/v19.0"
DEFAULT_IG_ACCOUNT_ID = "17841467629335560"  # toyokawa-sns 既存と同じ


def post_instagram_uranai(*, weekday_key: str, data: dict, spot, target_date: date,
                           ig_image_url: str, dry: bool = False) -> dict:
    """Instagram feed に投稿
    Args:
        ig_image_url: 公開アクセス可能な IG 用画像URL（WPメディアURL）
    Returns: {"status": "ok"/"dry"/"error", "post_id": str|None, "caption": str}
    """
    caption = make_instagram_caption(weekday_key, data, spot, target_date)

    if dry:
        return {"status": "dry", "post_id": None, "caption": caption,
                "image_url": ig_image_url}

    token = os.getenv("META_ACCESS_TOKEN")
    ig_account_id = (os.getenv("INSTAGRAM_ACCOUNT_ID")
                     or os.getenv("IG_USER_ID")
                     or DEFAULT_IG_ACCOUNT_ID)
    if not token or not ig_account_id:
        return {"status": "error", "post_id": None, "caption": caption,
                "error": "META_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID 未設定"}

    try:
        # Step1: メディアコンテナ作成
        r1 = requests.post(
            f"{GRAPH_API}/{ig_account_id}/media",
            data={"image_url": ig_image_url, "caption": caption, "access_token": token},
            timeout=60,
        )
        if r1.status_code != 200:
            return {"status": "error", "post_id": None, "caption": caption,
                    "error": f"container failed: {r1.status_code} {r1.text[:200]}"}
        container_id = r1.json()["id"]

        # Instagram は処理に数秒かかる
        time.sleep(3)

        # Step2: 公開
        r2 = requests.post(
            f"{GRAPH_API}/{ig_account_id}/media_publish",
            data={"creation_id": container_id, "access_token": token},
            timeout=60,
        )
        if r2.status_code != 200:
            return {"status": "error", "post_id": None, "caption": caption,
                    "error": f"publish failed: {r2.status_code} {r2.text[:200]}"}

        post_id = str(r2.json()["id"])
        return {"status": "ok", "post_id": post_id, "caption": caption}
    except Exception as e:
        return {"status": "error", "post_id": None, "caption": caption, "error": str(e)}


def post_instagram_uranai_reel(*, weekday_key: str, data: dict, spot, target_date: date,
                                video_url: str, cover_url: str | None = None,
                                dry: bool = False) -> dict:
    """Instagram Reels に動画投稿

    Args:
        video_url: 公開アクセス可能な動画URL（WPメディアの mp4 URL）
        cover_url: カバー画像URL（任意・指定なしなら動画1フレーム目）

    Returns: {"status": "ok"/"dry"/"error", "post_id": str|None, "caption": str}
    """
    caption = make_instagram_reel_caption(weekday_key, data, spot, target_date)

    if dry:
        return {"status": "dry", "post_id": None, "caption": caption,
                "video_url": video_url, "media_type": "REELS"}

    token = os.getenv("META_ACCESS_TOKEN")
    ig_account_id = (os.getenv("INSTAGRAM_ACCOUNT_ID")
                     or os.getenv("IG_USER_ID")
                     or DEFAULT_IG_ACCOUNT_ID)
    if not token or not ig_account_id:
        return {"status": "error", "post_id": None, "caption": caption,
                "error": "META_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID 未設定"}

    try:
        # Step1: Reels メディアコンテナ作成
        params = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": token,
            "share_to_feed": "true",  # フィード（プロフィール）にも表示
        }
        if cover_url:
            params["cover_url"] = cover_url

        r1 = requests.post(
            f"{GRAPH_API}/{ig_account_id}/media",
            data=params,
            timeout=120,
        )
        if r1.status_code != 200:
            return {"status": "error", "post_id": None, "caption": caption,
                    "error": f"reel container failed: {r1.status_code} {r1.text[:300]}"}
        container_id = r1.json()["id"]

        # Step2: 動画処理完了までポーリング（最大3分・5秒間隔）
        for attempt in range(36):
            time.sleep(5)
            rs = requests.get(
                f"{GRAPH_API}/{container_id}",
                params={"fields": "status_code,status", "access_token": token},
                timeout=30,
            )
            if rs.status_code == 200:
                status_code = rs.json().get("status_code", "")
                if status_code == "FINISHED":
                    break
                if status_code == "ERROR":
                    return {"status": "error", "post_id": None, "caption": caption,
                            "error": f"reel processing error: {rs.json()}"}
        else:
            return {"status": "error", "post_id": None, "caption": caption,
                    "error": "reel processing timeout (3 min)"}

        # Step3: 公開
        r2 = requests.post(
            f"{GRAPH_API}/{ig_account_id}/media_publish",
            data={"creation_id": container_id, "access_token": token},
            timeout=60,
        )
        if r2.status_code != 200:
            return {"status": "error", "post_id": None, "caption": caption,
                    "error": f"reel publish failed: {r2.status_code} {r2.text[:200]}"}

        post_id = str(r2.json()["id"])
        return {"status": "ok", "post_id": post_id, "caption": caption,
                "media_type": "REELS"}
    except Exception as e:
        return {"status": "error", "post_id": None, "caption": caption, "error": str(e)}
