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
import json
import os
import random
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


def pick_style(ch: dict, text: str) -> int:
    """台詞の雰囲気で声色（スタイル）を切り替える。config の characters[].styles で指定
      exclaim: 「！」で終わる・「！？」を含む（驚き・ツッコミ・盛り上がり）
      question: 「？」で終わる
    指定がなければノーマル（voicevox_speaker）"""
    styles = ch.get("styles") or {}
    t = text.rstrip("」』）)♪ 　")
    if "！？" in t or "!?" in t or t.endswith(("！", "!")):
        return styles.get("exclaim", ch["voicevox_speaker"])
    if t.endswith(("？", "?")):
        return styles.get("question", ch["voicevox_speaker"])
    return ch["voicevox_speaker"]


def _humanize(query: dict, text: str, tuning: dict):
    """棒読み感を減らす調整
    - 抑揚（intonationScale）を強めに
    - 読点の間を少し詰める（会話はテンポが速い）
    - 1文ごとに声の高さ・速さをほんの少し揺らす（毎回同じ調子にならないように）
    - 「〜ね」「〜よ」などの語尾を少し伸ばす"""
    rnd = random.Random(hashlib.sha1(text.encode("utf-8")).digest())   # 同じ台詞は同じ結果
    query["intonationScale"] = float(tuning.get("intonation", 1.0))
    if "pauseLengthScale" in query:
        query["pauseLengthScale"] = float(tuning.get("pause_scale", 1.0))
    pj, sj = float(tuning.get("pitch_jitter", 0)), float(tuning.get("speed_jitter", 0))
    query["pitchScale"] = query.get("pitchScale", 0.0) + rnd.uniform(-pj, pj)
    query["speedScale"] *= 1 + rnd.uniform(-sj, sj)
    stretch = float(tuning.get("ending_stretch", 1.0))
    phrases = query.get("accent_phrases") or []
    if stretch != 1.0 and phrases and phrases[-1]["moras"]:
        last = phrases[-1]["moras"][-1]
        if last.get("text") in ("ネ", "ヨ", "ナ", "ノ", "ワ", "サ"):
            last["vowel_length"] *= stretch


def synthesize(text: str, speaker: int, speed: float, cache_dir: Path,
               tuning: dict | None = None) -> Path:
    tuning = tuning or {}
    cache_dir.mkdir(parents=True, exist_ok=True)
    sig = json.dumps(tuning, sort_keys=True)
    key = hashlib.sha1(f"{speaker}|{speed}|{sig}|{text}".encode("utf-8")).hexdigest()[:16]
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
    query["outputSamplingRate"] = 24000   # エンジンを替えても形式をそろえる
    query["outputStereo"] = False
    _humanize(query, text, tuning)
    s = requests.post(f"{VOICEVOX_URL}/synthesis", params={"speaker": speaker},
                      json=query, timeout=180)
    s.raise_for_status()
    out.write_bytes(s.content)
    return out
