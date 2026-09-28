"""
tts_engine.py — 音声合成エンジン（VOICEVOX / AivisSpeech）で台詞を wav にする

どちらも同じ HTTP API（/audio_query → /synthesis）なので、config.json の "engine" で切り替える。
  VOICEVOX    : docker run --rm -p 50021:50021 voicevox/voicevox_engine:cpu-latest
  AivisSpeech : docker run --rm -p 10101:10101 ghcr.io/aivis-project/aivisspeech-engine:cpu-latest
  （Windows ならアプリ版を起動するだけで OK）

- 声は「話者名＋スタイル名」で指定（ID はエンジンに問い合わせて解決）
- 同じ台詞・声・設定は output 内のキャッシュを再利用
- 読み間違える言葉は config の readings で「読み」に置き換えてから合成
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

import requests

SAMPLE_RATE = 24000
DEFAULT_URLS = {"voicevox": "http://127.0.0.1:50021", "aivisspeech": "http://127.0.0.1:10101"}


class Engine:
    def __init__(self, config: dict):
        # 環境変数 TTS_ENGINE / TTS_URL があれば config より優先（Actions から切り替える用）
        self.name = os.environ.get("TTS_ENGINE") or config.get("engine", "voicevox")
        eng = config.get("engines", {}).get(self.name, {})
        self.url = (os.environ.get("TTS_URL") or eng.get("url") or DEFAULT_URLS[self.name]).rstrip("/")
        self.credit_prefix = eng.get("credit_prefix", self.name)
        self.tuning = eng.get("voice_tuning", {})

    def wait(self, timeout: int = 600) -> str:
        """エンジン起動待ち（AivisSpeech は初回にモデルをダウンロードするので長め）"""
        end = time.time() + timeout
        while time.time() < end:
            try:
                r = requests.get(f"{self.url}/version", timeout=5)
                if r.ok:
                    return f"{self.name} {r.text.strip(chr(34))}"
            except requests.exceptions.RequestException:
                pass
            time.sleep(3)
        raise RuntimeError(f"音声エンジンに接続できません: {self.name} {self.url}")

    def resolve_voices(self, characters: dict) -> dict[str, dict]:
        """characters[].voices[engine] の話者名・スタイル名 → スタイル ID
        戻り値: {キャラkey: {"speaker": 話者名, "id": 通常ID, "styles": {"exclaim": ID, ...}}}"""
        speakers = requests.get(f"{self.url}/speakers", timeout=30).json()
        table = {s["name"]: {st["name"]: st["id"] for st in s["styles"]} for s in speakers}
        print("  使える声: " + " / ".join(f"{n}({','.join(st)})" for n, st in table.items()))
        out = {}
        for key, ch in characters.items():
            v = (ch.get("voices") or {}).get(self.name, {})
            name = v.get("speaker")
            if name not in table:
                fallback = next(iter(table))
                print(f"  [注意] {key}: 声「{name}」が見つからないので「{fallback}」で代用", file=sys.stderr)
                name = fallback
            styles = table[name]

            def sid(style_name, _styles=styles):
                return _styles.get(style_name, next(iter(_styles.values())))

            out[key] = {
                "speaker": name,
                "id": sid(v.get("style", "ノーマル")),
                "styles": {k: sid(s) for k, s in (v.get("styles") or {}).items()},
                "pitch": float(v.get("pitch", 0.0)),
            }
        return out

    def synthesize(self, text: str, voice: dict, style_id: int, speed: float, cache_dir: Path) -> Path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        sig = json.dumps([self.name, voice.get("pitch"), self.tuning], sort_keys=True)
        key = hashlib.sha1(f"{style_id}|{speed}|{sig}|{text}".encode("utf-8")).hexdigest()[:16]
        out = cache_dir / f"{key}.wav"
        if out.exists():
            return out
        q = requests.post(f"{self.url}/audio_query",
                          params={"text": text, "speaker": style_id}, timeout=60)
        q.raise_for_status()
        query = q.json()
        query["speedScale"] = speed
        query["prePhonemeLength"] = 0.05
        query["postPhonemeLength"] = 0.05
        query["outputSamplingRate"] = SAMPLE_RATE   # エンジンを替えても形式をそろえる
        query["outputStereo"] = False
        if voice.get("pitch"):
            query["pitchScale"] = query.get("pitchScale", 0.0) + voice["pitch"]
        _humanize(query, text, self.tuning)
        s = requests.post(f"{self.url}/synthesis", params={"speaker": style_id},
                          json=query, timeout=300)
        s.raise_for_status()
        out.write_bytes(s.content)
        return out


def load_readings(config: dict) -> dict[str, str]:
    """読み替え辞書（config.json の readings）。
    ※ schedule.csv の地名→読み は自動では使わない（クイズ記事で答えを先に読んでしまうため）"""
    return dict(config.get("readings", {}))


def apply_readings(text: str, readings: dict[str, str]) -> str:
    # 長い語から置換（「豊川稲荷」が「豊川」より先に当たるように）
    for k in sorted(readings, key=len, reverse=True):
        text = text.replace(k, readings[k])
    return text


def pick_style(voice: dict, text: str) -> int:
    """台詞の雰囲気で声色（スタイル）を切り替える。config の voices[engine].styles で指定
      exclaim: 「！」で終わる・「！？」を含む（驚き・ツッコミ・盛り上がり）
      question: 「？」で終わる
    指定がなければ通常の style"""
    styles = voice["styles"]
    t = text.rstrip("」』）)♪ 　")
    if "！？" in t or "!?" in t or t.endswith(("！", "!")):
        return styles.get("exclaim", voice["id"])
    if t.endswith(("？", "?")):
        return styles.get("question", voice["id"])
    return voice["id"]


def _humanize(query: dict, text: str, tuning: dict):
    """棒読み感を減らす調整（config の engines[engine].voice_tuning にある項目だけ適用）
    - intonation     : 抑揚の強さ（AivisSpeech では「感情表現の強さ」）
    - tempo_dynamics : 話す速さの緩急（AivisSpeech のみ）
    - pause_scale    : 読点の間
    - pitch_jitter / speed_jitter : 1文ごとに声の高さ・速さをほんの少し揺らす
    - ending_stretch : 「〜ね」「〜よ」などの語尾を少し伸ばす（VOICEVOX のみ効果あり）"""
    rnd = random.Random(hashlib.sha1(text.encode("utf-8")).digest())   # 同じ台詞は同じ結果
    if "intonation" in tuning:
        query["intonationScale"] = float(tuning["intonation"])
    if "tempo_dynamics" in tuning and "tempoDynamicsScale" in query:
        query["tempoDynamicsScale"] = float(tuning["tempo_dynamics"])
    if "pause_scale" in tuning and "pauseLengthScale" in query:
        query["pauseLengthScale"] = float(tuning["pause_scale"])
    pj, sj = float(tuning.get("pitch_jitter", 0)), float(tuning.get("speed_jitter", 0))
    if pj:
        query["pitchScale"] = query.get("pitchScale", 0.0) + rnd.uniform(-pj, pj)
    if sj:
        query["speedScale"] *= 1 + rnd.uniform(-sj, sj)
    stretch = float(tuning.get("ending_stretch", 1.0))
    phrases = query.get("accent_phrases") or []
    if stretch != 1.0 and phrases and phrases[-1]["moras"]:
        last = phrases[-1]["moras"][-1]
        if last.get("text") in ("ネ", "ヨ", "ナ", "ノ", "ワ", "サ"):
            last["vowel_length"] *= stretch
