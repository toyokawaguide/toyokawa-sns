"""
sns_clients.py — Threads / Instagram Feed / Instagram Reels 投稿

【dry-run モード必須】公開前提だが、テスト時は dry=True で実体投稿せず

【占いシステムの post_threads.py / post_instagram_uranai.py から流用】
"""
from __future__ import annotations
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

META_TOKEN = os.environ.get("META_ACCESS_TOKEN")
IG_ACCOUNT_ID = os.environ.get("INSTAGRAM_ACCOUNT_ID")
# Threads は独自APIを使う（占いと同じ仕組み）
THREADS_TOKEN = os.environ.get("THREADS_ACCESS_TOKEN")
THREADS_USER_ID = (os.environ.get("THREADS_USER_ID")
                    or os.environ.get("THREADS_ACCOUNT_ID"))  # 後方互換
GRAPH_API = "https://graph.facebook.com/v19.0"      # IG用
THREADS_API = "https://graph.threads.net/v1.0"       # Threads用（占いと同じ）


def post_threads(caption: str, image_url: str = None, dry: bool = True) -> dict:
    """Threads 投稿（占い post_threads_uranai.py と同じ実装）"""
    if dry:
        print(f"[DRY][Threads] caption preview:\n{'-'*40}\n{caption}\n{'-'*40}")
        if image_url:
            print(f"[DRY][Threads] image: {image_url}")
        return {"dry": True}

    if not THREADS_TOKEN or not THREADS_USER_ID:
        return {"error": "THREADS_ACCESS_TOKEN / THREADS_USER_ID 未設定"}

    # Step 1: コンテナ作成（Threads専用API使用）
    params = {"media_type": "IMAGE" if image_url else "TEXT",
              "text": caption,
              "access_token": THREADS_TOKEN}
    if image_url:
        params["image_url"] = image_url
    r1 = requests.post(f"{THREADS_API}/{THREADS_USER_ID}/threads",
                       params=params, timeout=60)
    if r1.status_code != 200:
        return {"error": f"container failed: {r1.status_code} {r1.text[:200]}"}
    container_id = r1.json()["id"]

    # Step 2: 公開
    time.sleep(2)
    r2 = requests.post(f"{THREADS_API}/{THREADS_USER_ID}/threads_publish",
                       params={"creation_id": container_id,
                                "access_token": THREADS_TOKEN}, timeout=60)
    if r2.status_code != 200:
        return {"error": f"publish failed: {r2.status_code} {r2.text[:200]}"}
    return {"post_id": r2.json().get("id"), "dry": False}


def post_instagram_feed(caption: str, image_url: str, dry: bool = True) -> dict:
    """Instagram Feed 投稿"""
    if dry:
        print(f"[DRY][IG Feed] caption preview:\n{'-'*40}\n{caption[:200]}...\n{'-'*40}")
        print(f"[DRY][IG Feed] image: {image_url}")
        return {"dry": True}

    if not META_TOKEN or not IG_ACCOUNT_ID:
        return {"error": "META_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID 未設定"}

    # Step 1: コンテナ作成
    r1 = requests.post(f"{GRAPH_API}/{IG_ACCOUNT_ID}/media",
                       data={"image_url": image_url, "caption": caption,
                             "access_token": META_TOKEN}, timeout=60)
    r1.raise_for_status()
    container_id = r1.json()["id"]

    # Step 2: 公開
    time.sleep(3)
    r2 = requests.post(f"{GRAPH_API}/{IG_ACCOUNT_ID}/media_publish",
                       data={"creation_id": container_id,
                             "access_token": META_TOKEN}, timeout=60)
    r2.raise_for_status()
    return {"post_id": r2.json().get("id"), "dry": False}


def post_instagram_reel_resumable(caption: str, video_path: Path,
                                    dry: bool = True) -> dict:
    """Instagram Reels Resumable Upload（占い post_instagram_uranai_reel_resumable() から流用）

    Args:
        caption: Reels キャプション
        video_path: ローカル mp4 ファイルパス
    Returns: {"status": "ok"/"dry"/"error", "post_id": str|None}
    """
    video_path = Path(video_path)

    if dry:
        print(f"[DRY][IG Reels] caption preview:\n{'-'*40}\n{caption[:200]}...\n{'-'*40}")
        print(f"[DRY][IG Reels] video_path: {video_path}")
        return {"status": "dry", "post_id": None, "caption": caption}

    if not video_path.exists():
        return {"status": "error", "post_id": None,
                "error": f"video file not found: {video_path}"}

    if not META_TOKEN or not IG_ACCOUNT_ID:
        return {"status": "error", "post_id": None,
                "error": "META_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID 未設定"}

    file_size = video_path.stat().st_size
    MAX_RETRIES = 5
    RETRY_WAIT = 90
    last_error = None

    for retry_idx in range(MAX_RETRIES):
        try:
            # Step1: Resumable container 作成
            r1 = requests.post(
                f"{GRAPH_API}/{IG_ACCOUNT_ID}/media",
                data={
                    "media_type": "REELS",
                    "upload_type": "resumable",
                    "caption": caption,
                    "access_token": META_TOKEN,
                    "share_to_feed": "true",
                },
                timeout=60,
            )
            if r1.status_code != 200:
                last_error = f"container failed: {r1.status_code} {r1.text[:300]}"
                if retry_idx < MAX_RETRIES - 1:
                    print(f"  [retry {retry_idx+1}] {last_error[:100]}, wait {RETRY_WAIT}s")
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "error": last_error}

            cr = r1.json()
            container_id, upload_uri = cr.get("id"), cr.get("uri")
            print(f"  container_id={container_id} file_size={file_size:,} bytes")

            # Step2: 動画 binary を Meta に直接 POST
            with video_path.open("rb") as f:
                video_bytes = f.read()
            ru = requests.post(
                upload_uri,
                headers={"Authorization": f"OAuth {META_TOKEN}",
                         "offset": "0", "file_size": str(file_size)},
                data=video_bytes,
                timeout=300,
            )
            if ru.status_code != 200:
                last_error = f"upload failed: {ru.status_code} {ru.text[:300]}"
                if retry_idx < MAX_RETRIES - 1:
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "error": last_error}
            print(f"  upload OK")

            # Step3: 動画処理完了までポーリング（最大5分）
            polling_status = None
            for attempt in range(60):
                time.sleep(5)
                rs = requests.get(
                    f"{GRAPH_API}/{container_id}",
                    params={"fields": "status_code,status", "access_token": META_TOKEN},
                    timeout=30,
                )
                if rs.status_code == 200:
                    sc = rs.json().get("status_code", "")
                    if sc == "FINISHED":
                        polling_status = "FINISHED"
                        break
                    if sc == "ERROR":
                        polling_status = "ERROR"
                        last_error = f"processing error: {rs.json()}"
                        break

            if polling_status != "FINISHED":
                if not last_error:
                    last_error = "processing timeout (5 min)"
                if retry_idx < MAX_RETRIES - 1:
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "error": last_error}

            # Step4: 公開
            r2 = requests.post(
                f"{GRAPH_API}/{IG_ACCOUNT_ID}/media_publish",
                data={"creation_id": container_id, "access_token": META_TOKEN},
                timeout=60,
            )
            if r2.status_code != 200:
                last_error = f"publish failed: {r2.status_code} {r2.text[:200]}"
                if retry_idx < MAX_RETRIES - 1:
                    time.sleep(RETRY_WAIT)
                    continue
                return {"status": "error", "post_id": None, "error": last_error}

            return {"status": "ok", "post_id": str(r2.json()["id"]),
                    "media_type": "REELS"}

        except Exception as e:
            last_error = str(e)
            if retry_idx < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
                continue
            return {"status": "error", "post_id": None, "error": last_error}

    return {"status": "error", "post_id": None,
            "error": f"exhausted {MAX_RETRIES} retries: {last_error}"}
