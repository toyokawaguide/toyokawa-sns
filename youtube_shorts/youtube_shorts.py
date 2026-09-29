# -*- coding: utf-8 -*-
"""リール動画を YouTube ショートにも出す（豊川ガイドチャンネル）  2026-09-29
   ★スイッチ：環境変数 YT_SHORTS_ENABLED=1 のときだけ動く（未設定なら何もしない＝既存の投稿に一切影響なし）
   ★認証：YT_TOKEN_JSON（yt_auth.py で作った yt_token.json の中身）。無ければ何もしない
   ★公開範囲：YT_PRIVACY（既定 private＝試運転。public にすると即公開）
   ★BGM：インスタ用は無音のまま。YouTube版だけ「豊川のうた」の切り抜きをランダムで乗せる
   ★重複防止：直近のアップロードに同じタイトルがあればアップしない（リトライ・再実行でも二重投稿しない）
   ★失敗しても例外を投げない（呼び出し側のインスタ・WP投稿を絶対に止めない）

   使い方（各パイプラインから）:
     import youtube_shorts
     res = youtube_shorts.post_short(reel_path, title, description, tags=[...], bgm="article", log=print)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BGM_DIR = HERE / "bgm"
POOL_DIR = BGM_DIR / "pool"
# BGMは「豊川のうた」（豊川ガイドの自作曲）6曲の切り抜き60本（歌い出しの頭から20秒）からランダム（社長指示 2026-09-29）
#   同じ日の3本（記事SNS・占い・ライト記事）は必ず別の曲。使う部分も日付ごとにランダム。
#   同じ日・同じ種類なら何度やり直しても同じ曲になる（再実行で変わらない）
STREAM_ORDER = {"article": 0, "uranai": 1, "light": 2}
DEFAULT_TAGS = ["豊川市", "豊川ガイド", "とよサポ", "愛知県", "東三河"]
FF = shutil.which("ffmpeg") or "ffmpeg"
FP = shutil.which("ffprobe") or "ffprobe"


def enabled() -> bool:
    return os.environ.get("YT_SHORTS_ENABLED", "").strip() == "1" and bool(_token_info())


def _token_info():
    raw = os.environ.get("YT_TOKEN_JSON", "").strip()
    if not raw and os.environ.get("YT_TOKEN_FILE"):
        p = Path(os.environ["YT_TOKEN_FILE"])
        raw = p.read_text(encoding="utf-8") if p.exists() else ""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _youtube():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    info = _token_info()
    creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
    if not creds.valid:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def clean_title(t: str) -> str:
    t = re.sub(r"[<>]", "", (t or "").replace("\n", " ")).strip()
    return t if len(t) <= 100 else t[:99] + "…"


def _duration(p: Path) -> float:
    r = subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 15.0


def pick_bgm(kind: str, day=None) -> Path | None:
    """その日・その種類のBGM切り抜きを選ぶ（kind = article / uranai / light）"""
    import random
    from datetime import datetime, timedelta, timezone
    try:
        pool = json.loads((POOL_DIR / "pool.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    day = day or (datetime.now(timezone(timedelta(hours=9))).date())
    songs = sorted({c["song"] for c in pool})
    random.Random(f"songs-{day}").shuffle(songs)                  # その日の曲の並び
    song = songs[STREAM_ORDER.get(kind, 0) % len(songs)]           # 種類ごとに別の曲
    clips = [c for c in pool if c["song"] == song]
    clip = random.Random(f"clip-{day}-{kind}").choice(clips)       # 使う部分もランダム
    return POOL_DIR / clip["file"]


def with_bgm(reel: Path, kind: str | None, lufs: float = -16.0) -> Path:
    """無音のリールに BGM を乗せた一時ファイルを返す（曲が無ければ元のまま）"""
    song = pick_bgm(kind) if kind else None
    if not song or not song.exists():
        return reel
    L = _duration(reel)
    out = Path(tempfile.gettempdir()) / f"yt_{reel.stem}_bgm.mp4"
    af = (f"atrim=start=0:duration={L},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.15,"
          f"afade=t=out:st={max(L - 1.2, 0)}:d=1.2,loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000")
    r = subprocess.run([FF, "-v", "error", "-y", "-i", str(reel), "-i", str(song), "-filter_complex", f"[1:a]{af}[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)],
                       capture_output=True, text=True)
    return out if r.returncode == 0 and out.exists() else reel


def _already_uploaded(yt, title: str):
    ch = yt.channels().list(part="contentDetails", mine=True).execute().get("items", [])
    if not ch:
        return None
    up = ch[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = yt.playlistItems().list(part="snippet", playlistId=up, maxResults=30).execute().get("items", [])
    for it in items:
        if it["snippet"]["title"].strip() == title.strip():
            return it["snippet"]["resourceId"]["videoId"]
    return None


def post_short(reel_path, title, description, tags=None, bgm=None, privacy=None, dry=False, log=print) -> dict:
    """YouTube ショートにアップ。戻り値 {"status": ok|skipped|error, "video_id", "url", ...}（例外は投げない）"""
    try:
        if not enabled():
            return {"status": "skipped", "reason": "無効（YT_SHORTS_ENABLED か YT_TOKEN_JSON が未設定）"}
        reel = Path(reel_path)
        if not reel.exists():
            return {"status": "skipped", "reason": f"動画が無い: {reel}"}
        title = clean_title(title)
        privacy = (privacy or os.environ.get("YT_PRIVACY") or "private").strip()
        if dry:
            return {"status": "dry", "title": title, "privacy": privacy}
        yt = _youtube()
        dup = _already_uploaded(yt, title)
        if dup:
            log(f"▶ YouTube ショート … 同じタイトルが既にあるのでスキップ（{dup}）")
            return {"status": "skipped", "reason": "既にアップ済み", "video_id": dup}
        video = with_bgm(reel, bgm)
        from googleapiclient.http import MediaFileUpload
        body = {
            "snippet": {"title": title, "description": (description or "")[:4900],
                        "tags": (tags or DEFAULT_TAGS)[:15], "categoryId": "19",
                        "defaultLanguage": "ja", "defaultAudioLanguage": "ja"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        }
        req = yt.videos().insert(part="snippet,status", body=body,
                                 media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True))
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
        vid = resp["id"]
        log(f"▶ YouTube ショート アップ完了（{privacy}）: https://youtube.com/shorts/{vid}")
        return {"status": "ok", "video_id": vid, "url": f"https://youtube.com/shorts/{vid}", "privacy": privacy}
    except Exception as e:
        log(f"⚠ YouTube ショートは失敗（インスタ等は影響なし）: {str(e)[:200]}")
        return {"status": "error", "error": str(e)[:300]}
