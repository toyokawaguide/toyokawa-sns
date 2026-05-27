"""
sheets_client.py — ライト記事キュー Sheets への OAuth 読み書きクライアント

【動作】
1. 既存 OAuth credentials.json (Search Console と共用) を読込
2. Sheets API スコープで token を取得（初回のみブラウザ認証）
3. 読み書き関数を提供

【スコープ】
- https://www.googleapis.com/auth/spreadsheets （読み書き両方）

【使い方】
python sheets_client.py --test     # 初回認証＋読み込みテスト
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import os

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("❌ Google libraries not installed.")
    print("   pip install google-api-python-client google-auth-oauthlib")
    sys.exit(1)

# ライト記事キュー Sheets
SPREADSHEET_ID = "155K-AQdLNUiYb4Z3MK-elyG1U7UIIxPeu397uZsVxdo"
SHEET_NAME = "キュー"

# 認証ファイル（環境変数優先・なければデフォルトパス）
ROOT = Path(__file__).resolve().parent
CREDENTIALS_FILE = Path(os.environ.get(
    "LIGHT_GOOGLE_CREDENTIALS",
    str(ROOT / "credentials.json")))
TOKEN_FILE = Path(os.environ.get(
    "LIGHT_GOOGLE_TOKEN",
    str(ROOT / "_assets" / "sheets_token.json")))

# Sheets + Drive 両方のスコープ（Drive は写真取得用）
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_service():
    """OAuth 認証して Sheets API service を返す"""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔑 Token を更新中...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"⚠ Token 更新失敗、再認証します: {e}")
                creds = None

        if not creds:
            if not CREDENTIALS_FILE.exists():
                print(f"❌ credentials.json が見つかりません: {CREDENTIALS_FILE}")
                sys.exit(1)
            print("🌐 初回 OAuth 認証中（ブラウザが自動で開きます）...")
            print("   Google アカウントでログインして「許可」をクリックしてください")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TOKEN_FILE.open("w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"✅ Token 保存: {TOKEN_FILE.name}")

    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_all_rows() -> list[dict]:
    """キューシートの全行を辞書のリストとして返す
    [{"id":"LR001", "状態":"draft", "場所":"...", ...}, ...]
    """
    service = get_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:Z1000",
    ).execute()
    values = result.get("values", [])
    if not values:
        return []
    headers = values[0]
    rows = []
    for row in values[1:]:
        # 各セルの値を取得（足りない列は空文字）
        padded = row + [""] * (len(headers) - len(row))
        rows.append(dict(zip(headers, padded)))
    return rows


def _column_letter(index: int) -> str:
    """1始まりの列番号を A, B, ..., Z, AA, AB, ... に変換"""
    result = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def update_status(row_index: int, new_status: str):
    """「状態」列（列順は変動するためヘッダー名で動的特定）を更新。

    社長が列を入れ替えても安全。
    """
    service = get_service()
    # まず1行目（ヘッダー）を取得して「状態」列の位置を特定
    h = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!1:1",
    ).execute()
    headers = h.get("values", [[]])[0]
    if "状態" not in headers:
        raise RuntimeError("「状態」列が見つかりません")
    col_idx = headers.index("状態") + 1  # 1-indexed
    col_letter = _column_letter(col_idx)
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!{col_letter}{row_index}",
        valueInputOption="USER_ENTERED",
        body={"values": [[new_status]]},
    ).execute()


def get_draft_rows() -> list[tuple[int, dict]]:
    """状態=draft の行を取得（古い順＝行番号昇順）
    戻り値: [(行番号, データ辞書), ...]
    """
    all_rows = read_all_rows()
    drafts = []
    for i, row in enumerate(all_rows, start=2):  # ヘッダーが行1なのでデータは行2から
        if row.get("状態", "").strip() == "draft":
            drafts.append((i, row))
    return drafts


def get_row_by_id(article_id: str) -> tuple[int, dict] | None:
    """指定 ID の行を取得（状態不問・再処理用）
    戻り値: (行番号, データ辞書) or None
    """
    all_rows = read_all_rows()
    target = article_id.strip().upper()
    for i, row in enumerate(all_rows, start=2):
        if row.get("ID", "").strip().upper() == target:
            return (i, row)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="認証＋読み込みテスト")
    args = ap.parse_args()

    if args.test:
        print("=" * 60)
        print(" Sheets 認証＋読み込みテスト")
        print("=" * 60)
        print(f"Spreadsheet ID: {SPREADSHEET_ID}")
        print(f"Token: {TOKEN_FILE}")
        print()

        rows = read_all_rows()
        print(f"\n✅ 全 {len(rows)} 行 読み込み成功\n")
        for i, row in enumerate(rows, start=1):
            print(f"--- 行 {i+1} ({row.get('ID', '?')}) ---")
            for k, v in row.items():
                v_short = (v[:50] + "...") if len(v) > 50 else v
                print(f"  {k}: {v_short}")
            print()

        drafts = get_draft_rows()
        print(f"\n📋 draft 状態の行: {len(drafts)} 件")
        for row_idx, row in drafts:
            print(f"  行{row_idx}: {row.get('ID', '?')} - {row.get('場所', '?')}")


if __name__ == "__main__":
    main()
