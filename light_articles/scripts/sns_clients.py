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
DEFAULT_IG_ACCOUNT_ID = "17841467629335560"  # toyokawaguide 既存（占いと同じフォールバック）
IG_ACCOUNT_ID = (os.environ.get("INSTAGRAM_ACCOUNT_ID")
                  or os.environ.get("IG_USER_ID")
                  or DEFAULT_IG_ACCOUNT_ID)
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
    """Instagram Feed 投稿（占い post_instagram_uranai と同じ実装）"""
    if dry:
        print(f"[DRY][IG Feed] caption preview:\n{'-'*40}\n{caption[:200]}...\n{'-'*40}")
        print(f"[DRY][IG Feed] image: {image_url}")
        return {"dry": True}

    # 関数内で os.environ を再取得（module global での取り違え防止・占い実装と同じパターン）
    token = os.environ.get("META_ACCESS_TOKEN") or META_TOKEN
    ig_id = (os.environ.get("INSTAGRAM_ACCOUNT_ID")
              or os.environ.get("IG_USER_ID")
              or DEFAULT_IG_ACCOUNT_ID)

    if not token:
        return {"error": f"META_ACCESS_TOKEN 未設定（os.environ len={len(os.environ.get('META_ACCESS_TOKEN') or '')}）"}
    if not ig_id:
        return {"error": "INSTAGRAM_ACCOUNT_ID 未設定（DEFAULTフォールバックも失敗）"}

    try:
        # Step 1: コンテナ作成
        r1 = requests.post(f"{GRAPH_API}/{ig_id}/media",
                            data={"image_url": image_url, "caption": caption,
                                  "access_token": token}, timeout=60)
        if r1.status_code != 200:
            return {"error": f"container failed: {r1.status_code} {r1.text[:300]}",
                    "image_url": image_url}
        container_id = r1.json()["id"]

        # Step 2: 公開
        time.sleep(3)
        r2 = requests.post(f"{GRAPH_API}/{ig_id}/media_publish",
                            data={"creation_id": container_id,
                                  "access_token": token}, timeout=60)
        if r2.status_code != 200:
            return {"error": f"publish failed: {r2.status_code} {r2.text[:300]}"}
        return {"post_id": r2.json().get("id"), "dry": False}
    except Exception as e:
        return {"error": str(e)}


def post_instagram_feed_carousel(caption: str, image_urls: list, dry: bool = True) -> dict:
    """IG Feed カルーセル投稿。image_urls[0]=生成カバー、以降=番号写真。
    画像1枚なら単一投稿にフォールバック（IGカルーセルは2枚以上必須）。最大10枚。"""
    image_urls = [u for u in image_urls if u][:10]
    if dry:
        print(f"[DRY][IG Feed carousel] {len(image_urls)}枚")
        for i, u in enumerate(image_urls):
            print(f"  [{i+1}] {u}")
        print(f"[DRY][IG Feed carousel] caption:\n{caption[:160]}...")
        return {"dry": True}
    if len(image_urls) <= 1:
        return post_instagram_feed(caption, image_urls[0] if image_urls else "", dry=False)

    token = os.environ.get("META_ACCESS_TOKEN") or META_TOKEN
    ig_id = (os.environ.get("INSTAGRAM_ACCOUNT_ID")
             or os.environ.get("IG_USER_ID")
             or DEFAULT_IG_ACCOUNT_ID)
    if not token:
        return {"error": "META_ACCESS_TOKEN 未設定"}
    if not ig_id:
        return {"error": "INSTAGRAM_ACCOUNT_ID 未設定"}
    try:
        # Step 1: 子コンテナ（各画像・is_carousel_item=true）
        children = []
        for u in image_urls:
            rc = requests.post(f"{GRAPH_API}/{ig_id}/media",
                               data={"image_url": u, "is_carousel_item": "true",
                                     "access_token": token}, timeout=60)
            if rc.status_code != 200:
                return {"error": f"child failed: {rc.status_code} {rc.text[:300]}", "image_url": u}
            children.append(rc.json()["id"])
            time.sleep(1)
        # Step 2: カルーセル親コンテナ
        r1 = requests.post(f"{GRAPH_API}/{ig_id}/media",
                           data={"media_type": "CAROUSEL", "children": ",".join(children),
                                 "caption": caption, "access_token": token}, timeout=60)
        if r1.status_code != 200:
            return {"error": f"carousel container failed: {r1.status_code} {r1.text[:300]}"}
        container_id = r1.json()["id"]
        # Step 3: 公開
        time.sleep(3)
        r2 = requests.post(f"{GRAPH_API}/{ig_id}/media_publish",
                           data={"creation_id": container_id, "access_token": token}, timeout=60)
        if r2.status_code != 200:
            return {"error": f"publish failed: {r2.status_code} {r2.text[:300]}"}
        return {"post_id": r2.json().get("id"), "dry": False, "count": len(image_urls)}
    except Exception as e:
        return {"error": str(e)}


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

    # 関数内で os.environ を再取得（占い実装と同じパターン）
    token = os.environ.get("META_ACCESS_TOKEN") or META_TOKEN
    ig_id = (os.environ.get("INSTAGRAM_ACCOUNT_ID")
              or os.environ.get("IG_USER_ID")
              or DEFAULT_IG_ACCOUNT_ID)

    if not token:
        return {"status": "error", "post_id": None,
                "error": f"META_ACCESS_TOKEN 未設定（os.environ len={len(os.environ.get('META_ACCESS_TOKEN') or '')}）"}
    if not ig_id:
        return {"status": "error", "post_id": None,
                "error": "INSTAGRAM_ACCOUNT_ID 未設定（DEFAULTフォールバックも失敗）"}

    file_size = video_path.stat().st_size
    MAX_RETRIES = 5
    RETRY_WAIT = 90
    last_error = None

    for retry_idx in range(MAX_RETRIES):
        try:
            # Step1: Resumable container 作成
            r1 = requests.post(
                f"{GRAPH_API}/{ig_id}/media",
                data={
                    "media_type": "REELS",
                    "upload_type": "resumable",
                    "caption": caption,
                    "access_token": token,
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
                headers={"Authorization": f"OAuth {token}",
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
                    params={"fields": "status_code,status", "access_token": token},
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
                f"{GRAPH_API}/{ig_id}/media_publish",
                data={"creation_id": container_id, "access_token": token},
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


def post_instagram_reel_by_url(caption: str, video_url: str, dry: bool = True) -> dict:
    """Instagram Reels（公開URL方式）— Resumable Upload が ProcessingFailedError で
    弾かれた時のフォールバック。2026-07-19 LR053 で Resumable が5回とも
    400 ProcessingFailedError になった事故を受けて追加。

    Args:
        caption: Reels キャプション
        video_url: 公開アクセス可能な mp4 の URL（WPメディア等）
    Returns: {"status": "ok"/"dry"/"error", "post_id": str|None}
    """
    if dry:
        print(f"[DRY][IG Reels URL] {video_url}")
        return {"status": "dry", "post_id": None, "caption": caption}

    token = os.environ.get("META_ACCESS_TOKEN") or META_TOKEN
    ig_id = (os.environ.get("INSTAGRAM_ACCOUNT_ID")
              or os.environ.get("IG_USER_ID")
              or DEFAULT_IG_ACCOUNT_ID)
    if not token:
        return {"status": "error", "post_id": None, "error": "META_ACCESS_TOKEN 未設定"}
    if not ig_id:
        return {"status": "error", "post_id": None, "error": "INSTAGRAM_ACCOUNT_ID 未設定"}

    try:
        r1 = requests.post(
            f"{GRAPH_API}/{ig_id}/media",
            data={"media_type": "REELS", "video_url": video_url,
                  "caption": caption, "access_token": token},
            timeout=120,
        )
        if r1.status_code != 200:
            return {"status": "error", "post_id": None,
                    "error": f"container failed: {r1.status_code} {r1.text[:200]}"}
        container_id = r1.json()["id"]
        print(f"  [URL方式] container_id={container_id}", flush=True)

        # 処理完了までポーリング（最大5分）
        status = None
        for _ in range(30):
            time.sleep(10)
            rs = requests.get(f"{GRAPH_API}/{container_id}",
                              params={"fields": "status_code,status", "access_token": token},
                              timeout=60)
            if rs.status_code == 200:
                status = rs.json().get("status_code")
                if status == "FINISHED":
                    break
                if status == "ERROR":
                    return {"status": "error", "post_id": None,
                            "error": f"processing error: {rs.json()}"}
        if status != "FINISHED":
            return {"status": "error", "post_id": None, "error": "processing timeout (5 min)"}

        r2 = requests.post(f"{GRAPH_API}/{ig_id}/media_publish",
                           data={"creation_id": container_id, "access_token": token},
                           timeout=60)
        if r2.status_code != 200:
            return {"status": "error", "post_id": None,
                    "error": f"publish failed: {r2.status_code} {r2.text[:200]}"}
        return {"status": "ok", "post_id": str(r2.json()["id"]), "media_type": "REELS_URL"}
    except Exception as e:
        return {"status": "error", "post_id": None, "error": str(e)}
