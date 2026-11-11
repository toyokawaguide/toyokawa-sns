# -*- coding: utf-8 -*-
"""bukken_lottery.py — さくっと物件紹介：紹介する物件をくじ引きで選ぶ（ローカル実行・G:ドライブ必須）

サイトの物件ページ（/room/・約3,200件）から、写真が3枚以上ある物件を1つランダムに選び、
  ・キューに1行足す（状態=ほめ待ち・種別=勝手に紹介・物件名/町名/構造/完成年/学区/物件ページ）
  ・写真フォルダ G:\\マイドライブ\\さくっと物件紹介\\{ID}_{物件名}\\ を作り、物件ページの写真を「候補_N.jpg」で保存
  ・写真の一覧 _候補一覧.jpg を作る（Claudeが目で見てほめポイントを書くため）
どこの会社の物件かでは選ばない（社長決定 2026-11-11）。一度出した物件は二度選ばない。

使い方:
  python bukken_lottery.py              … 1件選ぶ
  python bukken_lottery.py --dry        … 選ぶだけ（キューにもフォルダにも書かない）
  python bukken_lottery.py --slug xxx   … くじ引きせず、この物件ページ（/room/xxx/）を入れる
このあと bukken_fill.py で、ほめポイント・写真の割り当てを入れる。
"""
from __future__ import annotations
import argparse
import html
import io
import random
import re
import sys
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import sheets_client as sc

API = "https://toyokawa-rentallife.com/wp-json/wp/v2/room"
SHEET = "物件紹介キュー"
SPREADSHEET_ID = (ROOT / "_bukken_sheet_id.txt").read_text(encoding="utf-8").strip()
PHOTO_BASE = Path("G:/マイドライブ/さくっと物件紹介")
MIN_PHOTOS = 3
UA = {"User-Agent": "Mozilla/5.0 (toyokawaguide bukken lottery)"}


def parse_room(r: dict) -> dict:
    c = r["content"]["rendered"]
    cells = dict(re.findall(r"<tr><td>(.*?)</td><td>(.*?)</td></tr>", c, flags=re.S))
    clean = lambda v: html.unescape(re.sub(r"<[^>]+>", "", v or "")).strip()
    info = {k: clean(v) for k, v in cells.items()}
    addr = info.get("住所", "")
    m = re.search(r"豊川市(.+?町|[^\d０-９]+?)(?=[\d０-９]|$)", addr)
    town = m.group(1) if m else ""
    town = re.sub(r"(.+町).*", r"\1", town) if "町" in town else town   # 「一宮町旭」→「一宮町」
    imgs = []
    for tag in re.findall(r"<img[^>]+>", c):
        s = re.search(r'src="([^"]+)"', tag)
        if s:
            imgs.append(re.sub(r"-\d+x\d+(\.\w+)$", r"\1", s.group(1)))   # 縮小版→元の大きさ
    name = clean(r["title"]["rendered"]).replace("物件名：", "").replace("物件名:", "").strip()
    kaidate = info.get("階建", "")
    return {"room_id": r["id"], "slug": r["slug"], "link": r["link"], "物件名": info.get("物件名") or name,
            "町名": town, "住所": addr, "構造・階数": "・".join(x for x in (info.get("構造", ""), kaidate) if x),
            "完成年": info.get("完成年", ""), "小学校区": info.get("小学校区", ""), "中学校区": info.get("中学校区", ""),
            "写真": list(dict.fromkeys(imgs))}


def fetch(page: int = None, slug: str = None) -> dict | None:
    params = {"per_page": 1, "_fields": "id,slug,title,content,link"}
    params.update({"slug": slug} if slug else {"page": page})
    r = requests.get(API, params=params, headers=UA, timeout=40)
    r.raise_for_status()
    return (r.json() or [None])[0]


def total() -> int:
    r = requests.get(API, params={"per_page": 1, "_fields": "id"}, headers=UA, timeout=40)
    return int(r.headers["X-WP-Total"])


def next_id(rows: list) -> str:
    nums = [int(m.group(1)) for r in rows if (m := re.match(r"BK(\d+)$", (r.get("ID") or "").strip()))]
    return f"BK{(max(nums) if nums else 0) + 1:03d}"


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--slug")
    a = ap.parse_args()

    rows = sc.read_all_rows(sheet=SHEET, spreadsheet_id=SPREADSHEET_ID)
    used = {(r.get("物件ページ") or "").strip().rstrip("/") for r in rows}
    if a.slug:
        room = fetch(slug=a.slug)
        if not room:
            raise SystemExit(f"❌ /room/{a.slug}/ が見つかりません")
        info = parse_room(room)
    else:
        n, info = total(), None
        for _ in range(40):
            room = fetch(page=random.SystemRandom().randint(1, n))
            cand = parse_room(room)
            if len(cand["写真"]) < MIN_PHOTOS:
                print(f"  ・見送り（写真{len(cand['写真'])}枚）: {cand['物件名']}")
                continue
            if cand["link"].rstrip("/") in used:
                print(f"  ・見送り（紹介済み）: {cand['物件名']}")
                continue
            info = cand
            break
        if not info:
            raise SystemExit("❌ 40回引いても条件に合う物件が出ませんでした")
    if info["link"].rstrip("/") in used:
        raise SystemExit(f"❌ {info['物件名']} は既にキューにあります")

    bid = next_id(rows)
    print(f"🎯 {bid}: {info['物件名']}（{info['町名']}）  {info['link']}")
    for k in ("住所", "構造・階数", "完成年", "小学校区", "中学校区"):
        print(f"   {k}: {info[k]}")
    print(f"   写真: {len(info['写真'])}枚")
    if a.dry:
        return

    if not PHOTO_BASE.parent.exists():
        raise SystemExit("❌ G:\\マイドライブ が見えません（Googleドライブを起動してください）")
    folder = PHOTO_BASE / f"{bid}_{safe_name(info['物件名'])}"
    folder.mkdir(parents=True, exist_ok=True)
    thumbs = []
    for i, u in enumerate(info["写真"], start=1):
        b = requests.get(u, headers=UA, timeout=60).content
        dst = folder / f"候補_{i}.jpg"
        if not dst.exists():
            dst.write_bytes(b)
        im = Image.open(io.BytesIO(b)).convert("RGB")
        thumbs.append(im.resize((640, round(im.height * 640 / im.width))))
    hh = max(t.height for t in thumbs)
    cols = 3
    sheet = Image.new("RGB", (640 * cols, hh * ((len(thumbs) + cols - 1) // cols)), "white")
    for k, t in enumerate(thumbs):
        sheet.paste(t, ((k % cols) * 640, (k // cols) * hh))
    sheet.save(folder / "_候補一覧.jpg", quality=85)

    H = sc.get_service().spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET}!1:1").execute()["values"][0]
    rowd = {"ID": bid, "状態": "ほめ待ち", "種別": "勝手に紹介", "物件名": info["物件名"], "町名": info["町名"],
            "構造・階数": info["構造・階数"], "完成年": info["完成年"], "小学校区": info["小学校区"],
            "中学校区": info["中学校区"], "物件ページ": info["link"]}
    sc.get_service().spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET}!A1", valueInputOption="RAW", insertDataOption="INSERT_ROWS",
        body={"values": [[rowd.get(h, "") for h in H]]}).execute()
    print(f"✅ キューに追加（状態=ほめ待ち）／写真フォルダ: {folder}")
    print(f"   一覧: {folder / '_候補一覧.jpg'}")


if __name__ == "__main__":
    main()
