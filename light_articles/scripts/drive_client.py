"""
drive_client.py — Google Drive 読み込みクライアント（GHA Linux環境用）

【動作】
1. 既存 OAuth credentials.json を共用（Sheets と同じ）
2. drive.readonly スコープ追加
3. 「ライト記事」フォルダ配下の {ID}_* サブフォルダから画像を取得

【ローカル/GHA 切替】
- LIGHT_BASE (G:/マイドライブ/ライト記事) が存在すれば: ローカルパス直接アクセス（高速）
- 存在しなければ: Drive API 経由でダウンロード（GHA Linux環境）

【使い方】
python drive_client.py --test     # 認証＋一覧テスト
"""
from __future__ import annotations
import argparse
import io
import os
import sys
from pathlib import Path

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    print("❌ Google libraries not installed.")
    print("   pip install google-api-python-client google-auth-oauthlib")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
CREDENTIALS_FILE = Path(os.environ.get(
    "LIGHT_GOOGLE_CREDENTIALS",
    str(ROOT / "credentials.json")))
TOKEN_FILE = Path(os.environ.get(
    "LIGHT_GOOGLE_TOKEN",
    str(ROOT / "_assets" / "sheets_token.json")))

# Sheets と Drive 両方のスコープ
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# 親フォルダ名（マイドライブ直下の「ライト記事」フォルダを探す）
ROOT_FOLDER_NAME = "ライト記事"

# 画像 MIME タイプ
IMAGE_MIMES = ("image/jpeg", "image/png", "image/jpg")


def get_drive_service():
    """OAuth 認証して Drive API service を返す（sheets_client と同じトークン使用）"""
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
                raise FileNotFoundError(
                    f"credentials.json が見つかりません: {CREDENTIALS_FILE}")
            print("🌐 OAuth 認証中（ブラウザが自動で開きます）...")
            print("   Google アカウントでログインして「許可」をクリックしてください")
            print("   ※ Drive 読み込み権限の追加承認が必要です")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TOKEN_FILE.open("w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"✅ Token 保存: {TOKEN_FILE.name}")

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def find_folder_id(folder_name: str, parent_id: str = None) -> str | None:
    """フォルダ名でフォルダIDを検索（マイドライブ直下 or 指定親フォルダ配下）"""
    service = get_drive_service()
    q_parts = [
        f"name = '{folder_name}'",
        "mimeType = 'application/vnd.google-apps.folder'",
        "trashed = false",
    ]
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")
    q = " and ".join(q_parts)
    results = service.files().list(
        q=q,
        fields="files(id, name)",
        pageSize=10,
        spaces="drive",
    ).execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def find_subfolder_by_prefix(parent_id: str, prefix: str) -> dict | None:
    """親フォルダ配下から prefix で始まるフォルダを探す
    例: prefix="LR001_" → LR001_ナチュラルカフェ はつね を返す
    戻り値: {"id": ..., "name": ...} or None
    """
    service = get_drive_service()
    # Drive API の name contains は前方一致でないため、全件取って前方一致でフィルタ
    q = (f"'{parent_id}' in parents "
         f"and mimeType = 'application/vnd.google-apps.folder' "
         f"and trashed = false")
    results = service.files().list(
        q=q,
        fields="files(id, name)",
        pageSize=100,
        spaces="drive",
    ).execute()
    for f in results.get("files", []):
        if f["name"].startswith(prefix):
            return f
    return None


def list_images_in_folder(folder_id: str) -> list[dict]:
    """フォルダ内の画像ファイル一覧を返す（名前昇順）
    戻り値: [{"id": "...", "name": "1.jpg", "mimeType": "..."}, ...]
    """
    service = get_drive_service()
    mime_q = " or ".join(f"mimeType = '{m}'" for m in IMAGE_MIMES)
    q = f"'{folder_id}' in parents and ({mime_q}) and trashed = false"
    results = service.files().list(
        q=q,
        fields="files(id, name, mimeType, size)",
        pageSize=100,
        orderBy="name",
        spaces="drive",
    ).execute()
    return results.get("files", [])


def download_file(file_id: str, output_path: Path) -> Path:
    """ファイルをDLしてローカル保存"""
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return output_path


def fetch_article_photos(article_id: str, cache_dir: Path) -> list[Path]:
    """記事ID の写真を Drive からDLして cache_dir に保存・パスリストを返す

    番号のみのファイル(0.jpg, 1.jpg, 2.jpg…)だけを番号順に使う。
    batch_ や W1920Q75_ 等の余分なファイルは無視（2026-06-22 社長指定）。
    """
    print(f"🔍 Drive: ライト記事フォルダ検索中...")
    root_id = find_folder_id(ROOT_FOLDER_NAME)
    if not root_id:
        print(f"❌ Drive: {ROOT_FOLDER_NAME} フォルダが見つかりません")
        return []

    print(f"🔍 Drive: {article_id}_* サブフォルダ検索中...")
    subfolder = find_subfolder_by_prefix(root_id, f"{article_id}_")
    if not subfolder:
        subfolder = find_subfolder_by_prefix(root_id, article_id)
    if not subfolder:
        print(f"⚠ Drive: {article_id} 用フォルダが見つかりません（写真なしで続行）")
        return []

    print(f"✅ Drive: {subfolder['name']} (id={subfolder['id'][:10]}...)")
    images = list_images_in_folder(subfolder["id"])
    if not images:
        print(f"⚠ Drive: 画像なし")
        return []

    # 番号のみのファイル(0.jpg, 1.jpg, 2.jpg…)だけ使う。
    # batch_ や W1920Q75_ 等の余分なファイルは無視（2026-06-22 社長指定）。
    numbered = [im for im in images if im["name"].rsplit(".", 1)[0].isdigit()]
    if numbered:
        images_sorted = sorted(numbered, key=lambda im: int(im["name"].rsplit(".", 1)[0]))
    else:
        print("⚠ Drive: 番号付き写真(0.jpg等)なし → 本文写真なしで続行")
        images_sorted = []

    paths = []
    cache_dir.mkdir(parents=True, exist_ok=True)
    for img in images_sorted:
        local_path = cache_dir / img["name"]
        if not local_path.exists():
            print(f"  📥 DL: {img['name']} ({int(img.get('size', 0))/1024:.0f} KB)")
            download_file(img["id"], local_path)
        paths.append(local_path)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="認証＋一覧テスト")
    ap.add_argument("--id", help="記事IDで写真DLテスト（例: LR001）")
    args = ap.parse_args()

    if args.test:
        print("=" * 60)
        print(" Drive API 認証＋一覧テスト")
        print("=" * 60)
        print(f"Token: {TOKEN_FILE}")
        print()
        root_id = find_folder_id(ROOT_FOLDER_NAME)
        print(f"ライト記事フォルダID: {root_id}")
        if root_id:
            service = get_drive_service()
            q = (f"'{root_id}' in parents "
                 f"and mimeType = 'application/vnd.google-apps.folder' "
                 f"and trashed = false")
            r = service.files().list(q=q, fields="files(id, name)",
                                      pageSize=20, spaces="drive").execute()
            print(f"\nサブフォルダ ({len(r.get('files', []))}件):")
            for f in r.get("files", []):
                print(f"  - {f['name']}")

    if args.id:
        cache = ROOT / "_drive_cache" / args.id
        paths = fetch_article_photos(args.id, cache)
        print(f"\n📸 取得写真: {len(paths)}枚")
        for p in paths:
            print(f"  {p}")


if __name__ == "__main__":
    main()
