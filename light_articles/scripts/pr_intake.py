# -*- coding: utf-8 -*-
"""pr_intake.py — さくっとPR 申込フォームの受付処理（2026-08-02）

申込フォーム（Apps Script）が PRキュー に 状態=申込 で1行入れる。
これを拾って、

  1. 記事タイトル・本文・アイキャッチ画像をその場で生成
  2. 申込者へ「完成イメージ」をメールで送る（画像は添付・本文はテキストで）
  3. 状態を「プレビュー送信済」に更新

まで自動でやる。社長は内容を見て、公開希望日を入れて 状態=draft にするだけ。

⚠️ ここでは WP には一切書き込まない。公開は既存の publish_pr_article.py（朝10時）の仕事。

使い方:
  python pr_intake.py            本番（メール送信あり）
  python pr_intake.py --dry      送信せず、何を送るかだけ表示
  python pr_intake.py --id PR003 1件だけ処理
"""
from __future__ import annotations

import argparse
import os
import re
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import series
series.set_label("さくっとPR")            # 画像・文面すべてPRブランドで作る

from sheets_client import read_all_rows, update_status
import pr_builder
import eyecatch_generator
from notify import GMAIL_USER, GMAIL_PASS

SHEET = "PRキュー"
# ★2026-08-05 PRキューは専用スプレッドシートに分離（ライト記事の本番タブとの同居をやめた）
PR_SPREADSHEET_ID = "1grn6UiQf8HqxcRSB3tMiZBLWGQCT1H7fCUNqv5CBA7A"
STATUS_NEW = "申込"
STATUS_DONE = "プレビュー送信済"
SITE = "豊川ガイド"
OUT_DIR = Path(__file__).resolve().parent.parent / "_preview_out"


def log(m, i=0):
    print("  " * i + m, flush=True)


def strip_html(html: str) -> str:
    """記事HTMLを、メールに載せる読みやすいプレーンテキストにする"""
    t = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"</t[dh]>", "　", t)                     # 表のセットは「項目　値」で並べる
    t = re.sub(r"</tr>", "\n", t)
    t = re.sub(r"</(p|div|h[1-6]|li)>", "\n", t)
    t = re.sub(r"<li>", "・", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = (t.replace("&ldquo;", "“").replace("&rdquo;", "”")
          .replace("&amp;", "&").replace("&nbsp;", " ")
          .replace("&lt;", "<").replace("&gt;", ">"))
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def normalize_row(idx: int, row: dict):
    """備考パック（ラベル：/色：/公開希望日：）を専用列に展開する（2026-08-05 列を入力欄と1:1化）

    - ラベル → U列 / 色 → V列（既に値があれば触らない＝社長の手修正を上書きしない）
    - 公開希望日 → B列（B列が空のときだけ・最終決定は社長）
    row 辞書にも反映するので、直後のプレビュー生成から専用列の値が使われる。
    """
    biko = row.get("備考", "") or ""
    from sheets_client import get_service
    svc = get_service()
    updates = []

    def pick(key):
        m = re.search(rf"{key}：(.+)", biko)
        return m.group(1).strip() if m else ""

    if not (row.get("ラベル") or "").strip():
        v = pick("ラベル")
        if v:
            updates.append(("U", v)); row["ラベル"] = v
    if not (row.get("色") or "").strip():
        v = pick("色")
        if v:
            updates.append(("V", v)); row["色"] = v
    if not (row.get("公開希望日") or "").strip():
        v = pick("公開希望日") or pick("掲載希望日")
        if v:
            updates.append(("B", v)); row["公開希望日"] = v
    # 備考を1行に圧縮（行が縦に広がるのが嫌・2026-08-06社長指摘）
    # 専用列に移した項目と自動判定できる「かたち」は落とし、残り（写真・その他）だけ「／」区切りで残す
    if biko.startswith("【申込ページから】"):
        keep = []
        for key in ["写真", "その他"]:
            v = pick(key)
            if v:
                keep.append(f"{key}：{v}")
        compact = "【申込ページから】" + "／".join(keep) if keep else "【申込ページから】"
        if compact != biko:
            updates.append(("N", compact))
            row["備考"] = compact

    for col, val in updates:
        svc.spreadsheets().values().update(
            spreadsheetId=PR_SPREADSHEET_ID, range=f"{SHEET}!{col}{idx}",
            valueInputOption="RAW", body={"values": [[val]]}).execute()
    if updates:
        log(f"備考→専用列に展開＋圧縮: {', '.join(c for c, _ in updates)}", 1)


def build_preview(row: dict, photo_path=None):
    """(タイトル, 本文テキスト, アイキャッチのパス) を返す
    photo_path があれば写真入り（一枚の札）で生成（写真到着後の再送用・2026-08-06）"""
    title = pr_builder.build_pr_title(row)
    body = strip_html(pr_builder.build_pr_content(row))
    OUT_DIR.mkdir(exist_ok=True)
    img = OUT_DIR / f"{row.get('ID', 'PR')}_preview.png"
    # ★2026-08-05 確定デザイン（額ぶち／一枚の札）。申込ページのライブプレビューと同じ絵が届く
    import pr_eyecatch
    pr_eyecatch.render_45(row, photo_path=photo_path, output_path=img)
    return title, body, img


def send_preview(row: dict, title: str, body: str, img: Path, *, dry: bool,
                 extra_images: list[Path] | None = None) -> bool:
    to = (row.get("メールアドレス") or "").strip()
    if not to:
        log("メールアドレスが空 → スキップ", 1)
        return False
    pid = row.get("ID", "")
    shop = row.get("店名", "")
    name = row.get("申込者名") or "ご担当者"

    # 申込ページで「写真あり」を選んだ人への注意（フォームの写真は仕組み上届かない・2026-08-06）
    photo_notice = []
    if "写真：あり" in (row.get("備考", "") or ""):
        photo_notice = [
            "※お申し込みページで選択された写真は、仕組みの都合でこちらには届いていません。",
            "　このメールに返信で写真を添付いただければ、写真入りの完成イメージを改めてお送りします。",
            "",
        ]

    text = "\n".join([
        f"{name} 様",
        "",
        f"{SITE}です。「さくっとPR」の完成イメージができました。",
        f"受付番号：{pid}",
        "",
        *photo_notice,
        "▼ 記事タイトル",
        title,
        "",
        "▼ 記事本文（このまま掲載されます）",
        "───────────────",
        body,
        "───────────────",
        "",
        "▼ 添付画像について",
        ("Instagramに投稿される画像の並び（1枚目=カード・2枚目以降=お写真）を全部添付しています。"
         if extra_images else
         "アイキャッチ画像を添付しています。記事の先頭とSNSに使われます。"),
        "",
        "■ このままでよろしければ",
        "「OKです」とご返信ください。掲載日を調整してご連絡します。",
        "",
        "■ 直したいところがある場合",
        "このメールに返信して、修正箇所をお書きください。何度でも作り直します。",
        "",
        "■ 写真を追加したい場合",
        "このメールに添付して返信してください。記事とSNSに使わせていただきます。",
        "",
        "※この時点ではまだ公開されていません。ご確認いただいてから公開します。",
        "",
        SITE,
    ])

    if dry:
        log(f"[dry] 送信先 {to}", 1)
        log(f"[dry] 件名 【{SITE}】さくっとPR 完成イメージのご確認（{pid}・{shop}）", 1)
        log(f"[dry] 添付 {img.name} ＋ 追加{len(extra_images or [])}枚", 1)
        log("[dry] 本文 ----", 1)
        for ln in text.splitlines()[:24]:
            log(ln, 2)
        log("... 以下略", 2)
        return True

    msg = EmailMessage()
    msg["From"] = GMAIL_USER
    msg["To"] = to
    msg["Bcc"] = GMAIL_USER                      # 送った控えを社長にも残す
    msg["Subject"] = f"【{SITE}】さくっとPR 完成イメージのご確認（{pid}・{shop}）"
    msg.set_content(text)
    msg.add_attachment(img.read_bytes(), maintype="image", subtype="png",
                       filename=f"{pid}_1_カバー.png")
    for i, p in enumerate(extra_images or [], start=2):
        sub = "png" if p.suffix.lower() == ".png" else "jpeg"
        msg.add_attachment(p.read_bytes(), maintype="image", subtype=sub,
                           filename=f"{pid}_{i}枚目{p.suffix}")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_PASS)
        s.send_message(msg)
    log(f"送信しました → {to}", 1)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="送信せず内容だけ表示")
    ap.add_argument("--id", help="このIDだけ処理")
    args = ap.parse_args()

    rows = read_all_rows(SHEET, spreadsheet_id=PR_SPREADSHEET_ID)
    targets = []
    for i, r in enumerate(rows, start=2):          # 1行目はヘッダ
        if args.id:
            if (r.get("ID") or "").strip() == args.id:
                targets.append((i, r))
        elif (r.get("状態") or "").strip() == STATUS_NEW:
            targets.append((i, r))

    if not targets:
        log("📭 新しい申込はありません")
        return

    log(f"新しい申込 {len(targets)}件")
    ok = 0
    for idx, row in targets:
        pid = row.get("ID", f"row{idx}")
        log(f"■ {pid} {row.get('店名', '')}")
        try:
            if not args.dry:
                normalize_row(idx, row)
            title, body, img = build_preview(row)
            log(f"タイトル: {title}", 1)
            if send_preview(row, title, body, img, dry=args.dry):
                if not args.dry:
                    update_status(idx, STATUS_DONE, SHEET, spreadsheet_id=PR_SPREADSHEET_ID)
                    log(f"状態を「{STATUS_DONE}」に更新", 1)
                ok += 1
        except Exception as e:
            log(f"❌ 失敗: {e}", 1)

    log(f"\n完了: {ok} / {len(targets)}")


if __name__ == "__main__":
    main()
