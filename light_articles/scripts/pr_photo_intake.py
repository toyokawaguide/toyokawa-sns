# -*- coding: utf-8 -*-
"""さくっとPR 写真自動取り込み（ローカル実行専用・G:ドライブ必須）

受付メールへの返信（件名に「さくっとPR」または PR番号・画像添付あり）を Gmail IMAP で拾い、
G:\\マイドライブ\\ライト記事\\PR番号\\ フォルダに連番(1.jpg, 2.jpg…)で保存する。

- フォルダ名は ID だけ（例: PR003）。folder_match は ID一致のみで通過する仕様確認済み
- Google Drive Desktop が自動同期 → 配信(GHA)は Drive API 読み取りで同じ写真を見る
- EXIF回転を実画素に反映（スマホ縦撮り対策）・長辺1920px超は縮小・JPEG q85
- 処理済みメールは状態ファイルに記録（何度実行しても二重保存しない）

使い方:
  python pr_photo_intake.py          # 取り込み実行
  python pr_photo_intake.py --dry    # 保存せず、見つけたメールと枚数だけ表示
"""
from __future__ import annotations

import argparse
import email
import imaplib
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageOps

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env", override=True)
load_dotenv(Path(r"C:/Users/Yoshida/Desktop/豊川ガイド/claude/.env"), override=False)

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD")
LIGHT_BASE = Path("G:/マイドライブ/ライト記事")
STATE_FILE = LIGHT_BASE / "_pr_photo_intake_state.json"
PR_RE = re.compile(r"\bPR\d{3}\b")
SINCE_DAYS = 60
MAX_SIDE = 1920


def dec(s) -> str:
    """メールヘッダーのデコード"""
    if not s:
        return ""
    out = []
    for part, enc in decode_header(s):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def next_number(folder: Path) -> int:
    nums = [int(f.stem) for f in folder.iterdir()
            if f.is_file() and f.stem.isdigit()] if folder.exists() else []
    return max(nums) + 1 if nums else 1


def save_image(data: bytes, folder: Path, n: int) -> Path | None:
    try:
        im = Image.open(io.BytesIO(data))
    except Exception:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            im = Image.open(io.BytesIO(data))
        except Exception:
            return None
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = folder / f"{n}.jpg"
    im.save(out, quality=85)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not GMAIL_USER or not GMAIL_PASS:
        print("❌ GMAIL_USER / GMAIL_APP_PASSWORD 未設定")
        sys.exit(1)
    if not LIGHT_BASE.exists():
        print(f"❌ {LIGHT_BASE} がありません（G:ドライブ未接続？）")
        sys.exit(1)

    state = load_state()
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(GMAIL_USER, GMAIL_PASS)
    imap.select("INBOX", readonly=True)

    since = (datetime.now() - timedelta(days=SINCE_DAYS)).strftime("%d-%b-%Y")
    _, data = imap.search(None, "SINCE", since)
    ids = data[0].split()
    print(f"📥 直近{SINCE_DAYS}日のメール {len(ids)}件をチェック")

    total_saved = 0
    for mid in ids:
        # ヘッダーだけ先に見て絞り込む（軽量）
        _, hd = imap.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM MESSAGE-ID)])")
        head = email.message_from_bytes(hd[0][1])
        subject = dec(head.get("Subject"))
        sender = dec(head.get("From"))
        msg_id = (head.get("Message-ID") or "").strip()

        if GMAIL_USER in sender:                 # 自分の送信控え(Bcc)は対象外
            continue
        m = PR_RE.search(subject)
        if not m:                                # 件名にPR番号がなければ対象外
            continue
        pr_id = m.group(0)
        if msg_id and msg_id in state:
            continue

        # 本文を取得して画像添付を集める
        _, full = imap.fetch(mid, "(BODY.PEEK[])")
        msg = email.message_from_bytes(full[0][1])
        atts = []
        for part in msg.walk():
            fn = dec(part.get_filename() or "")
            ct = part.get_content_type()
            if ct.startswith("image/") or re.search(r"\.(jpe?g|png|heic|webp)$", fn, re.I):
                payload = part.get_payload(decode=True)
                if payload and len(payload) > 10_000:      # 署名アイコン等の極小画像は無視
                    atts.append((fn or "attachment", payload))
        if not atts:
            continue

        folder = LIGHT_BASE / pr_id
        print(f"\n■ {pr_id} ← {sender}")
        print(f"  件名: {subject[:60]}")
        print(f"  画像添付: {len(atts)}枚 → {folder}")
        if args.dry:
            continue

        folder.mkdir(exist_ok=True)
        n = next_number(folder)
        saved = []
        for fn, payload in atts:
            out = save_image(payload, folder, n)
            if out:
                saved.append(out.name)
                n += 1
            else:
                print(f"  ⚠ 読めない画像をスキップ: {fn}")
        print(f"  ✅ 保存: {', '.join(saved)}")
        total_saved += len(saved)
        if msg_id:
            state[msg_id] = {"pr": pr_id, "saved": len(saved),
                             "at": datetime.now().isoformat(timespec="seconds")}

    imap.logout()
    if not args.dry:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完了: 新規保存 {total_saved}枚")


if __name__ == "__main__":
    main()
