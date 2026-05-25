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

    # 関数内リトライ：error code 2207077 等の一時的失敗を救済
    # フィード投稿/Threads/WP には触らず、Reels投稿だけ再試行する
    # 2026-05-25 強化：3回→5回・60s→90s。間欠失敗多発（5/24 朝も失敗→13時手動復旧）
    MAX_RETRIES = 5
    RETRY_WAIT = 90  # 失敗後の待機秒
    last_error = None

    for retry_idx in range(MAX_RETRIES):
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
                last_error = f"reel container failed: {r1.status_code} {r1.text[:300]}"
                if retry_idx < MAX_RETRIES - 1:
                    print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] container failed, wait {RETRY_WAIT}s")
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "caption": caption,
                        "error": last_error, "attempts": retry_idx + 1}
            container_id = r1.json()["id"]

            # Step2: 動画処理完了までポーリング（最大5分・5秒間隔）
            # 2026-05-24 3分→5分に延長。Meta側のReel処理が3分超えるケース多発のため
            polling_status = None
            polling_error_detail = None
            for attempt in range(60):
                time.sleep(5)
                rs = requests.get(
                    f"{GRAPH_API}/{container_id}",
                    params={"fields": "status_code,status", "access_token": token},
                    timeout=30,
                )
                if rs.status_code == 200:
                    status_code = rs.json().get("status_code", "")
                    if status_code == "FINISHED":
                        polling_status = "FINISHED"
                        break
                    if status_code == "ERROR":
                        polling_status = "ERROR"
                        polling_error_detail = rs.json()
                        break

            if polling_status != "FINISHED":
                # ERROR or timeout
                if polling_status == "ERROR":
                    last_error = f"reel processing error: {polling_error_detail}"
                else:
                    last_error = "reel processing timeout (5 min)"
                if retry_idx < MAX_RETRIES - 1:
                    print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] {last_error[:100]}, wait {RETRY_WAIT}s")
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "caption": caption,
                        "error": last_error, "attempts": retry_idx + 1}

            # Step3: 公開
            r2 = requests.post(
                f"{GRAPH_API}/{ig_account_id}/media_publish",
                data={"creation_id": container_id, "access_token": token},
                timeout=60,
            )
            if r2.status_code != 200:
                last_error = f"reel publish failed: {r2.status_code} {r2.text[:200]}"
                if retry_idx < MAX_RETRIES - 1:
                    print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] publish failed, wait {RETRY_WAIT}s")
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "caption": caption,
                        "error": last_error, "attempts": retry_idx + 1}

            # 成功
            post_id = str(r2.json()["id"])
            return {"status": "ok", "post_id": post_id, "caption": caption,
                    "media_type": "REELS", "attempts": retry_idx + 1}

        except Exception as e:
            last_error = str(e)
            if retry_idx < MAX_RETRIES - 1:
                print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] exception: {last_error[:100]}, wait {RETRY_WAIT}s")
                time.sleep(RETRY_WAIT)
                continue
            return {"status": "error", "post_id": None, "caption": caption,
                    "error": last_error, "attempts": retry_idx + 1}

    # ループ抜けた場合（理論上来ない）
    return {"status": "error", "post_id": None, "caption": caption,
            "error": f"exhausted {MAX_RETRIES} retries: {last_error}",
            "attempts": MAX_RETRIES}


# ============================================================
# Resumable Upload 版（2026-05-25 追加）
# ============================================================
# 背景：External URL 方式（video_url= で WP の mp4 URL を渡す）が 5/24-25 で連続失敗。
# Meta の external fetcher が WP の動画 DL に失敗 or 遅延する状況が頻発。
# Resumable Upload は動画 binary を Meta に直接 POST するため、外部 URL 依存ゼロ。
#
# 仕様: https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/media
# 1) container 作成 (media_type=REELS, upload_type=resumable) → id + uri 取得
# 2) uri に動画 binary を POST (Authorization: OAuth, offset: 0, file_size: N)
# 3) container status を polling（FINISHED まで）
# 4) /media_publish で公開
# ============================================================

UPLOAD_API = "https://rupload.facebook.com/ig-api-upload/v19.0"


def post_instagram_uranai_reel_resumable(
    *, weekday_key: str, data: dict, spot, target_date: date,
    video_path, cover_path=None, dry: bool = False,
) -> dict:
    """Instagram Reels に動画投稿（Resumable Upload 方式）

    Args:
        video_path: ローカル mp4 ファイルパス（Path or str）
        cover_path: カバー画像パス（任意・指定なしなら動画1フレーム目）

    Returns: {"status": "ok"/"dry"/"error", "post_id": str|None, "caption": str}
    """
    from pathlib import Path
    video_path = Path(video_path)
    caption = make_instagram_reel_caption(weekday_key, data, spot, target_date)

    if dry:
        return {"status": "dry", "post_id": None, "caption": caption,
                "video_path": str(video_path), "media_type": "REELS"}

    if not video_path.exists():
        return {"status": "error", "post_id": None, "caption": caption,
                "error": f"video file not found: {video_path}"}

    token = os.getenv("META_ACCESS_TOKEN")
    ig_account_id = (os.getenv("INSTAGRAM_ACCOUNT_ID")
                     or os.getenv("IG_USER_ID")
                     or DEFAULT_IG_ACCOUNT_ID)
    if not token or not ig_account_id:
        return {"status": "error", "post_id": None, "caption": caption,
                "error": "META_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID 未設定"}

    file_size = video_path.stat().st_size

    # リトライ機構（External URL 版と同じ）
    MAX_RETRIES = 5
    RETRY_WAIT = 90
    last_error = None

    for retry_idx in range(MAX_RETRIES):
        try:
            # Step1: Resumable container 作成
            params = {
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": caption,
                "access_token": token,
                "share_to_feed": "true",
            }
            r1 = requests.post(
                f"{GRAPH_API}/{ig_account_id}/media",
                data=params,
                timeout=60,
            )
            if r1.status_code != 200:
                last_error = f"resumable container failed: {r1.status_code} {r1.text[:300]}"
                if retry_idx < MAX_RETRIES - 1:
                    print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] container failed, wait {RETRY_WAIT}s")
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "caption": caption,
                        "error": last_error, "attempts": retry_idx + 1}
            container_resp = r1.json()
            container_id = container_resp.get("id")
            upload_uri = container_resp.get("uri")
            if not container_id or not upload_uri:
                last_error = f"resumable response missing id/uri: {container_resp}"
                if retry_idx < MAX_RETRIES - 1:
                    print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] {last_error[:150]}, wait {RETRY_WAIT}s")
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "caption": caption,
                        "error": last_error, "attempts": retry_idx + 1}
            print(f"     container_id={container_id} / file_size={file_size} bytes")

            # Step2: 動画 binary を Meta に直接 POST
            with video_path.open("rb") as f:
                video_bytes = f.read()
            upload_headers = {
                "Authorization": f"OAuth {token}",
                "offset": "0",
                "file_size": str(file_size),
            }
            ru = requests.post(
                upload_uri,
                headers=upload_headers,
                data=video_bytes,
                timeout=300,  # 大きい動画でも 5分以内に upload 完了想定
            )
            if ru.status_code != 200:
                last_error = f"resumable upload failed: {ru.status_code} {ru.text[:300]}"
                if retry_idx < MAX_RETRIES - 1:
                    print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] upload failed, wait {RETRY_WAIT}s")
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "caption": caption,
                        "error": last_error, "attempts": retry_idx + 1}
            print(f"     upload OK: {ru.json()}")

            # Step3: 動画処理完了までポーリング（最大5分・5秒間隔）
            polling_status = None
            polling_error_detail = None
            for attempt in range(60):
                time.sleep(5)
                rs = requests.get(
                    f"{GRAPH_API}/{container_id}",
                    params={"fields": "status_code,status", "access_token": token},
                    timeout=30,
                )
                if rs.status_code == 200:
                    status_code = rs.json().get("status_code", "")
                    if status_code == "FINISHED":
                        polling_status = "FINISHED"
                        break
                    if status_code == "ERROR":
                        polling_status = "ERROR"
                        polling_error_detail = rs.json()
                        break

            if polling_status != "FINISHED":
                if polling_status == "ERROR":
                    last_error = f"resumable processing error: {polling_error_detail}"
                else:
                    last_error = "resumable processing timeout (5 min)"
                if retry_idx < MAX_RETRIES - 1:
                    print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] {last_error[:100]}, wait {RETRY_WAIT}s")
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "caption": caption,
                        "error": last_error, "attempts": retry_idx + 1}

            # Step4: 公開
            r2 = requests.post(
                f"{GRAPH_API}/{ig_account_id}/media_publish",
                data={"creation_id": container_id, "access_token": token},
                timeout=60,
            )
            if r2.status_code != 200:
                last_error = f"resumable publish failed: {r2.status_code} {r2.text[:200]}"
                if retry_idx < MAX_RETRIES - 1:
                    print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] publish failed, wait {RETRY_WAIT}s")
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "caption": caption,
                        "error": last_error, "attempts": retry_idx + 1}

            # 成功
            post_id = str(r2.json()["id"])
            return {"status": "ok", "post_id": post_id, "caption": caption,
                    "media_type": "REELS", "attempts": retry_idx + 1,
                    "upload_method": "resumable"}

        except Exception as e:
            last_error = str(e)
            if retry_idx < MAX_RETRIES - 1:
                print(f"     [retry {retry_idx+1}/{MAX_RETRIES}] exception: {last_error[:100]}, wait {RETRY_WAIT}s")
                time.sleep(RETRY_WAIT)
                continue
            return {"status": "error", "post_id": None, "caption": caption,
                    "error": last_error, "attempts": retry_idx + 1}

    return {"status": "error", "post_id": None, "caption": caption,
            "error": f"exhausted {MAX_RETRIES} retries: {last_error}",
            "attempts": MAX_RETRIES}
