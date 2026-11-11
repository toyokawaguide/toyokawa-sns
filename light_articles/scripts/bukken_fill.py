# -*- coding: utf-8 -*-
"""bukken_fill.py — さくっと物件紹介：ほめポイントと写真をキューに入れ、完成イメージを作る（ローカル実行）

使い方:
  python bukken_fill.py --id BK001 --json 入力.json     … 文と写真の割り当てを入れて 状態=確認待ち に
  python bukken_fill.py --id BK001 --preview            … 完成イメージだけ作り直す（キューは変えない）
  python bukken_fill.py --id BK001 --go 2026-11-20      … 公開希望日を入れて 状態=draft（その日の13時に自動配信）

入力.json の形:
  {"ひとことキャッチ": "...", "ほめ": [["見出し", "本文（改行で段落）"], ["..", ".."], ["..", ".."]],
   "ひとこと": "...", "写真": [4, 1, 3], "表紙": 1, "表紙の切り出し": "上"}
   写真 = ほめ①②③に使う「候補_N.jpg」の番号（→ 1.jpg 2.jpg 3.jpg に写す）
   表紙 = アイキャッチなどに使う候補の番号（→ 0.jpg）。"表紙の切り出し":"上" は、写真の下にある日付を避けて上側を切り出す
完成イメージ: 写真フォルダに _完成イメージ_{ID}.png（アイキャッチ＋インスタ1枚目）と _本文_{ID}.html・_SNS文_{ID}.txt
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import sheets_client as sc
import bukken_builder as bb
import pr_eyecatch
pr_eyecatch.SERIES_NAME = bb.LABEL

SHEET = "物件紹介キュー"
SPREADSHEET_ID = (ROOT / "_bukken_sheet_id.txt").read_text(encoding="utf-8").strip()
PHOTO_BASE = Path("G:/マイドライブ/さくっと物件紹介")


def find_row(bid: str):
    rows = sc.read_all_rows(sheet=SHEET, spreadsheet_id=SPREADSHEET_ID)
    for i, r in enumerate(rows, start=2):
        if (r.get("ID") or "").strip().upper() == bid.upper():
            return i, r
    raise SystemExit(f"❌ {bid} がキューにありません")


def folder_of(bid: str) -> Path:
    c = [p for p in sorted(PHOTO_BASE.glob(f"{bid}_*")) if p.is_dir()]
    if not c:
        raise SystemExit(f"❌ 写真フォルダがありません: {PHOTO_BASE}\\{bid}_…")
    return c[0]


def write_cells(row_index: int, values: dict):
    svc = sc.get_service()
    H = svc.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET}!1:1").execute()["values"][0]
    data = []
    for k, v in values.items():
        if k not in H:
            raise SystemExit(f"❌ 列「{k}」がキューにありません")
        col = sc._column_letter(H.index(k) + 1)      # 列番号は1始まり
        data.append({"range": f"{SHEET}!{col}{row_index}", "values": [[v]]})
    svc.spreadsheets().values().batchUpdate(spreadsheetId=SPREADSHEET_ID,
                                            body={"valueInputOption": "RAW", "data": data}).execute()


def put_photo(folder: Path, n: int, dst_name: str, crop_top: bool = False):
    src = folder / f"候補_{n}.jpg"
    if not src.exists():
        raise SystemExit(f"❌ {src.name} がありません")
    dst = folder / dst_name
    if dst.exists():
        dst.replace(folder / f"_旧_{dst_name}")      # 上書きせず退避
    if not crop_top:
        shutil.copy2(src, dst)
        return
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    w, h = im.size
    nh = round(h * 0.833)            # 下の約17%（日付の焼き込み）を外す
    nw = round(nh * 16 / 9)
    x0 = (w - nw) // 2
    im.crop((x0, 0, x0 + nw, nh)).save(dst, quality=92)


def preview(bid: str, row: dict, folder: Path):
    from publish_light_article import get_photo_paths
    photos = get_photo_paths(folder)
    cover = next((p for p in photos if int(p.stem) == 0), None) or next((p for p in photos if int(p.stem) >= 1), None)
    cr = bb.card_row(row)
    a = pr_eyecatch.render_169(cr, photo_path=cover)
    b = pr_eyecatch.render_45(cr, photo_path=cover)
    b2 = b.resize((round(b.width * 720 / b.height), 720))
    sheet = Image.new("RGB", (a.width + 20 + b2.width, 720), "white")
    sheet.paste(a, (0, 0))
    sheet.paste(b2, (a.width + 20, 0))
    out = folder / f"_完成イメージ_{bid}.png"
    sheet.save(out)
    body_photos = [p.resolve().as_uri() for p in photos if int(p.stem) >= 1]
    url = f"https://toyokawa-rentallife.com/（公開日）/{bid.lower()}/"
    (folder / f"_本文_{bid}.html").write_text(
        '<meta charset="utf-8"><div style="max-width:720px;margin:24px auto;font-family:sans-serif;line-height:1.8;">'
        f"<h1>{bb.build_title(row)}</h1>{bb.build_content(row, body_photos)}</div>", encoding="utf-8")
    sns = "\n\n".join(f"━━ {k} ━━\n{v}" for k, v in (("X", bb.build_x_caption(row, url)),
                                                     ("Threads", bb.build_threads_caption(row, url)),
                                                     ("Instagram", bb.build_instagram_caption(row, url))))
    (folder / f"_SNS文_{bid}.txt").write_text(sns, encoding="utf-8")
    ng = bb.find_ng_words(row)
    print(f"🖼 完成イメージ: {out}")
    print(f"   タイトル: {bb.build_title(row)}")
    print(f"   X字数: {bb.x_weight(bb.build_x_caption(row, url))}/280")
    print("   言葉チェック: " + ("❌ " + "・".join(ng) if ng else "OK"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--json")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--go", help="公開希望日 YYYY-MM-DD を入れて 状態=draft にする")
    a = ap.parse_args()
    bid = a.id.upper()
    idx, row = find_row(bid)

    if a.go:
        from publish_bukken_article import check_row
        errs = check_row(row)
        if errs:
            raise SystemExit("❌ まだ出せません: " + " / ".join(errs))
        write_cells(idx, {"公開希望日": a.go, "状態": "draft"})
        print(f"✅ {bid} → {a.go} 13:00 に配信（状態=draft）")
        return

    folder = folder_of(bid)
    if a.json:
        d = json.loads(Path(a.json).read_text(encoding="utf-8"))
        vals = {"ひとことキャッチ": d["ひとことキャッチ"], "ひとこと": d.get("ひとこと", ""), "状態": "確認待ち"}
        for i, (h, b) in enumerate(d["ほめ"][:3], start=1):
            vals[f"ほめ{i}見出し"], vals[f"ほめ{i}本文"] = h, b
        for i, n in enumerate(d.get("写真", [])[:3], start=1):
            put_photo(folder, n, f"{i}.jpg")
        if d.get("表紙"):
            put_photo(folder, d["表紙"], "0.jpg", crop_top=(d.get("表紙の切り出し") == "上"))
        write_cells(idx, vals)
        idx, row = find_row(bid)
        print(f"✅ {bid} キュー更新（状態=確認待ち）")
    preview(bid, row, folder)


if __name__ == "__main__":
    main()
