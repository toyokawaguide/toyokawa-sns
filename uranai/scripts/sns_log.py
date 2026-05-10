"""
SNS配信ログ（Google Sheet）に1行追加するヘルパー。

使い方:
    from sns_log import append_log
    append_log(
        title="記事タイトル",
        url="https://toyokawa-rentallife.com/2026/04/19/slug/",
        time="07:00",
        memo="",
    )

配信日は JST の当日、公開日はURLの /YYYY/MM/DD/ から抽出。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_URL = os.getenv("SNS_LOG_WEBHOOK_URL")
SECRET      = os.getenv("SNS_LOG_SECRET")

JST = timezone(timedelta(hours=9))
URL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")


def _extract_publish_date(url: str) -> str:
    m = URL_DATE_RE.search(url)
    if not m:
        return ""
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def append_log(title: str, url: str, time: str, memo: str = "") -> dict:
    """配信ログに1行追加する。返り値はWebhookのレスポンス(JSON)。"""
    if not WEBHOOK_URL or not SECRET:
        raise RuntimeError("SNS_LOG_WEBHOOK_URL / SNS_LOG_SECRET が .env に設定されていません")

    payload = {
        "secret":     SECRET,
        "配信日":      datetime.now(JST).strftime("%Y-%m-%d"),
        "時刻":        time,
        "記事タイトル": title,
        "URL":         url,
        "公開日":      _extract_publish_date(url),
        "配信回":      "",
        "X":           "✓",
        "Instagram":   "✓",
        "Threads":     "✓",
        "Facebook":    "✓",
        "Gunosy":      "",
        "備考":        memo,
    }
    r = requests.post(WEBHOOK_URL, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()
