# -*- coding: utf-8 -*-
"""さくっとPR 写真自動取り込み（ローカル実行専用・G:ドライブ必須）

受付メールへの返信（件名に「さくっとPR」または PR番号・画像添付あり）を Gmail IMAP で拾い、
G:\\マイドライブ\\さくっとPR\\PR番号_店名\\ フォルダに連番(1.jpg, 2.jpg…)で保存する。
★ライト記事とはフォルダ分離（2026-08-06 社長指示）

- フォルダ名は ID だけ（例: PR003）。folder_match は ID一致のみで通過する仕様確認済み
- Google Drive Desktop が自動同期 → 配信(GHA)は Drive API 読み取りで同じ写真を見る
- EXIF回転を実画素に反映（スマホ縦撮り対策）・長辺1920px超は縮小・JPEG q85
- 処理済みメールは状態ファイルに記録（何度実行しても二重保存しない）

使い方（2026-10-27 誤送信事故のあと変更）:
  python pr_photo_intake.py --dry                    # 保存も送信もせず、見つけた返信を表示
  python pr_photo_intake.py --id PR016               # PR016 の返信だけ、写真を保存（送信しない）
  python pr_photo_intake.py --id PR016 --send        # 保存して、写真入り完成イメージを再送（1通まで）
  ※ 状態が 申込／プレビュー送信済／手動対応 以外のPRは触らない。送信は pr_send_guard の確認を通ったときだけ
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
PR_BASE = Path("G:/マイドライブ/さくっとPR")   # ★ライト記事とフォルダ分離（2026-08-06社長指示）
STATE_FILE = PR_BASE / "_pr_photo_intake_state.json"
PR_RE = re.compile(r"\bPR\d{3}\b")
SINCE_DAYS = 14   # ★2026-10-27 60→14日（古い返信を拾って過去のお客さまに再送した事故）
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


def load_shop_names() -> dict:
    """PRキューから ID→店名 の対応表を取得（フォルダ名 PR000_店名 用）"""
    try:
        from sheets_client import read_all_rows
        rows = read_all_rows(sheet="PRキュー",
                             spreadsheet_id="1grn6UiQf8HqxcRSB3tMiZBLWGQCT1H7fCUNqv5CBA7A")
        return {(r.get("ID") or "").strip(): (r.get("店名") or "").strip()
                for r in rows if (r.get("ID") or "").strip()}
    except Exception as e:
        print(f"⚠ PRキュー読込失敗（フォルダ名はID単独になります）: {e}")
        return {}


def target_folder(pr_id: str, shop_names: dict) -> Path:
    """保存先フォルダ＝ PR000_店名（既存の PR000* フォルダがあればそれを使う）"""
    existing = sorted(PR_BASE.glob(f"{pr_id}*"))
    for d in existing:
        if d.is_dir():
            return d
    shop = shop_names.get(pr_id, "")
    shop = re.sub(r'[\\/:*?"<>|]', "", shop).strip()      # Windowsフォルダ名に使えない文字を除去
    return PR_BASE / (f"{pr_id}_{shop}" if shop else pr_id)


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


def resend_preview_with_photo(pr_id: str, folder: Path):
    """写真到着後、写真入りの完成イメージを申込者に自動再送（2026-08-06）"""
    try:
        from sheets_client import read_all_rows
        import pr_intake
        rows = read_all_rows(sheet="PRキュー",
                             spreadsheet_id="1grn6UiQf8HqxcRSB3tMiZBLWGQCT1H7fCUNqv5CBA7A")
        row = next((r for r in rows if (r.get("ID") or "").strip() == pr_id), None)
        if not row:
            print(f"  ⚠ {pr_id} がキューに見つからず再送スキップ")
            return
        nums = sorted([f for f in folder.iterdir() if f.stem.isdigit()],
                      key=lambda f: int(f.stem))
        if not nums:
            return
        title, body, img = pr_intake.build_preview(row, photo_path=nums[0])
        # インスタのカルーセル並びをそのまま添付（2枚目以降=PR専用枠・テーマ色連動・店名入り）
        import pr_eyecatch
        framed_list = []
        for p in nums:
            framed = pr_intake.OUT_DIR / f"_framed_{pr_id}_{p.stem}.png"
            pr_eyecatch.render_carousel_photo(row, p, framed)
            framed_list.append(framed)
        ok = pr_intake.send_preview(row, title, body, img, dry=False,
                                    extra_images=framed_list)
        if ok:
            print(f"  📧 写真入り完成イメージ（カバー＋枠付き{len(framed_list)}枚）を再送しました")
    except Exception as e:
        print(f"  ⚠ 写真入りプレビュー再送失敗（写真保存は完了済み）: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--id", help="このPR番号の返信だけ処理する（--dry 以外では必須）")
    ap.add_argument("--send", action="store_true",
                    help="写真入りの完成イメージを申込者へ再送する（指定しなければ写真の保存だけ）")
    args = ap.parse_args()
    # ★2026-10-27 誤送信事故の再発防止: 本番実行は必ず1件（--id）に絞る。再送は --send を付けたときだけ・1回の実行で1通まで
    if not args.dry and not args.id:
        print("❌ 本番実行には --id PR000 の指定が必要です（全件を一度に処理すると、過去のお客さまへ再送してしまうため）")
        sys.exit(1)
    try:
        from sheets_client import read_all_rows
        import pr_send_guard
        pr_states = {(r.get("ID") or "").strip(): (r.get("状態") or "").strip()
                     for r in read_all_rows(sheet="PRキュー", spreadsheet_id=pr_send_guard.PR_SPREADSHEET_ID)}
    except Exception as e:
        print(f"❌ PRキューの状態を読めないので止めます: {e}")
        sys.exit(1)
    resent = 0

    if not GMAIL_USER or not GMAIL_PASS:
        print("❌ GMAIL_USER / GMAIL_APP_PASSWORD 未設定")
        sys.exit(1)
    PR_BASE.mkdir(exist_ok=True)
    if not PR_BASE.exists():
        print(f"❌ {PR_BASE} がありません（G:ドライブ未接続？）")
        sys.exit(1)

    state = load_state()
    shop_names = load_shop_names()
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
        if args.id and pr_id != args.id:
            continue
        if pr_states.get(pr_id, "") not in pr_send_guard.ALLOWED_STATES:
            # 掲載済み・取消などの古い申込への返信は触らない（保存も再送もしない）。二度と拾わないよう記録だけ残す
            print(f"  ⏭ {pr_id} は状態「{pr_states.get(pr_id, '不明')}」なので対象外")
            if msg_id and not args.dry:
                state[msg_id] = {"pr": pr_id, "saved": 0, "at": datetime.now().isoformat(timespec="seconds"),
                                 "note": "状態が対象外のためスキップ"}
                STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
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

        folder = target_folder(pr_id, shop_names)
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
        if msg_id:     # ★2026-10-27 1通ごとにすぐ記録（途中で止まっても、次に同じ返信を拾わない）
            state[msg_id] = {"pr": pr_id, "saved": len(saved),
                             "at": datetime.now().isoformat(timespec="seconds")}
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        if saved and args.send and resent == 0:
            resend_preview_with_photo(pr_id, folder)
            resent += 1
        elif saved:
            print("  ℹ 完成イメージの再送はしていません（送るときは --send を付けて、もう一度この1件だけ実行）")

    imap.logout()
    if not args.dry:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完了: 新規保存 {total_saved}枚")


if __name__ == "__main__":
    main()
