"""
voicevox_tts.py — VOICEVOX ENGINE（HTTP API）で台詞を wav にする

【前提】VOICEVOX ENGINE を起動しておく
  docker run --rm -p 50021:50021 voicevox/voicevox_engine:cpu-latest
  （Windows ならアプリ版 VOICEVOX を起動するだけで OK）

- 同じ台詞・話者・速度は output 内のキャッシュを再利用
- 読み間違える言葉は config の readings で「読み」に置き換えてから合成
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import requests

VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")


def wait_engine(timeout: int = 120):
    """エンジン起動待ち（Docker 起動直後はモデル読み込みに時間がかかる）"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            r = requests.get(f"{VOICEVOX_URL}/version", timeout=5)
            if r.ok:
                return r.text.strip('"')
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError(f"VOICEVOX ENGINE に接続できません: {VOICEVOX_URL}")


def load_readings(config: dict) -> dict[str, str]:
    """読み替え辞書（config.json の readings）。
    ※ schedule.csv の地名→読み は自動では使わない（クイズ記事で答えを先に読んでしまうため）"""
    return dict(config.get("readings", {}))


def apply_readings(text: str, readings: dict[str, str]) -> str:
    # 長い語から置換（「豊川稲荷」が「豊川」より先に当たるように）
    for k in sorted(readings, key=len, reverse=True):
        text = text.replace(k, readings[k])
    return text


def synthesize(text: str, speaker: int, speed: float, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{speaker}|{speed}|{text}".encode("utf-8")).hexdigest()[:16]
    out = cache_dir / f"{key}.wav"
    if out.exists():
        return out
    q = requests.post(f"{VOICEVOX_URL}/audio_query",
                      params={"text": text, "speaker": speaker}, timeout=60)
    q.raise_for_status()
    query = q.json()
    query["speedScale"] = speed
    query["prePhonemeLength"] = 0.05
    query["postPhonemeLength"] = 0.05
    s = requests.post(f"{VOICEVOX_URL}/synthesis", params={"speaker": speaker},
                      json=query, timeout=180)
    s.raise_for_status()
    out.write_bytes(s.content)
    return out
