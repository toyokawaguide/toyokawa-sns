# -*- coding: utf-8 -*-
"""ライト記事：これから配信される行の写真フォルダを、前もって照合する。
  python precheck_photo_folders.py            … 今日〜3日先の draft 行
  python precheck_photo_folders.py --days 7   … 7日先まで

配信本番（publish_light_article）は folder_match.verify で
「フォルダ名と記事内容（場所欄）が合わない」と止まる安全装置がある。
2026-09-21 LR117 は場所欄が「ご多分に漏れず豊川市も…」、フォルダ名が「カメムシ大量発生！…」で
一致0%となり 19:00 の配信が3回とも止まった（記事は1時間半遅れで手動公開）。
止まるなら前夜に知りたいので、毎晩の「キャプション」点検でこれを回す。
"""
import sys, glob, argparse
from datetime import date, timedelta
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import folder_match
from sheets_client import read_all_rows

LIGHT_BASE = Path(r"G:\マイドライブ\ライト記事")

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=3)
a = ap.parse_args()

today = date.today()
targets = {(today + timedelta(days=i)).strftime("%Y/%m/%d") for i in range(a.days + 1)}

rows = read_all_rows()
ng = 0
print(f"=== 写真フォルダ 事前照合（{today} 〜 {a.days}日先・draft 行） ===")
for r in rows:
    ID = (r.get("ID") or "").strip()
    d = (r.get("公開希望日") or "").replace("-", "/").strip()[:10]
    st = (r.get("状態") or "").strip()
    if not ID or d not in targets or st != "draft":
        continue
    place = (r.get("場所") or "").strip()
    cands = [Path(p) for p in glob.glob(str(LIGHT_BASE / f"{ID}_*"))] + \
            ([LIGHT_BASE / ID] if (LIGHT_BASE / ID).is_dir() else [])
    cands = [c for c in cands if c.is_dir()]
    if not cands:
        print(f"  ・ {ID} {d}  写真フォルダなし（写真なし記事ならOK）  場所={place}")
        continue
    folder = cands[0]
    photos = [p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png") and p.stem.isdigit()]
    ok, msg = folder_match.verify(ID, folder.name, place, raise_on_fail=False)
    if ok:
        print(f"  ✅ {ID} {d}  {folder.name}（番号写真 {len(photos)}枚）")
    else:
        ng += 1
        print(f"  ❌ {ID} {d}  このままだと本番で止まります")
        print(f"       フォルダ: {folder.name}")
        print(f"       場所欄  : {place}")
        print(f"       → フォルダ名に場所欄の言葉を入れる（例: {ID}_{place}）か、場所欄を直す")
    if len(photos) > 9:
        print(f"       ⚠ 番号写真が{len(photos)}枚。Instagramはカバー＋9枚までで、{len(photos)-9}枚は載りません")
print(f"=== 問題 {ng}件 ===")
sys.exit(1 if ng else 0)
