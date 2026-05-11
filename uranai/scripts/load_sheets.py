"""Google Sheets からデータ取得（Apps Script Webhook 経由）

xlsx（openpyxl）と同じ形式（list[tuple]）で返すことで、
select_lucky_spot.py / load_groups.py から差し替え可能にする。

【環境変数】
- URANAI_SHEETS_URL: Apps Script Web App URL (https://script.google.com/macros/s/.../exec)
- URANAI_SHEETS_SECRET: シート操作用の認証秘密値（Apps Script 側と一致）

【動作】
- URANAI_SHEETS_URL 未設定なら全関数 None を返す → 呼び出し側で xlsx フォールバック
- 設定済みなら Sheets から取得

【Apps Script 側 API 仕様】
  GET /exec?sheet=<シート名>&secret=<SECRET>
  → JSON: {"values": [[row1col1, row1col2, ...], ...]}
"""
from __future__ import annotations
import os
import json
from datetime import date, datetime
from typing import Any

import requests


def is_enabled() -> bool:
    return bool(os.getenv("URANAI_SHEETS_URL"))


def fetch_sheet(sheet_name: str, timeout: int = 30) -> list[list] | None:
    """指定シートの全行を取得（A1〜最終行）

    Returns:
        2次元配列（xlsx の iter_rows と同じイメージ・list of list）
        失敗時は None
    """
    url = os.getenv("URANAI_SHEETS_URL")
    secret = os.getenv("URANAI_SHEETS_SECRET", "")
    if not url:
        return None

    try:
        r = requests.get(url, params={"sheet": sheet_name, "secret": secret}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            print(f"[load_sheets] error from Apps Script: {data['error']}")
            return None
        return data.get("values", [])
    except Exception as e:
        print(f"[load_sheets] fetch '{sheet_name}' failed: {e}")
        return None


def normalize_cell(v: Any) -> Any:
    """Apps Script から返ってきた値を Python ネイティブ型に正規化

    Apps Script は日付を ISO 文字列 or epoch ms で返すことがある。
    """
    if v is None or v == "":
        return None
    if isinstance(v, str):
        # ISO 日付っぽい？
        if len(v) >= 10 and v[4] == "-" and v[7] == "-":
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
            except ValueError:
                pass
        return v
    if isinstance(v, (int, float)):
        return v
    return v


def fetch_sheet_normalized(sheet_name: str) -> list[tuple] | None:
    """fetch_sheet + 値の正規化（日付など）"""
    rows = fetch_sheet(sheet_name)
    if rows is None:
        return None
    return [tuple(normalize_cell(c) for c in row) for row in rows]


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if not is_enabled():
        print("URANAI_SHEETS_URL 未設定 - Sheets モード無効")
        sys.exit(0)
    name = sys.argv[1] if len(sys.argv) > 1 else "ラッキースポット入力"
    rows = fetch_sheet_normalized(name)
    if rows is None:
        print(f"[FAIL] {name}")
        sys.exit(1)
    print(f"[OK] {name}: {len(rows)} 行取得")
    for i, r in enumerate(rows[:5]):
        print(f"  row{i}: {r}")
