# -*- coding: utf-8 -*-
"""さくっとPR「プレビュー」シート生成（ライト記事の build_preview_sheet.py と同方式）

B1 に行番号（2＝1件目）→ 画像カードのイメージ＋記事のながれ＋X投稿文が組み上がる。
ついでに PRキュー T1 に「豊川ガイドから一言」列ヘッダーを追加する（任意記入・記事にだけ出る）。

実行: python build_pr_preview_sheet.py（再実行OK・タブは作り直される）
"""
import sys
from sheets_client import get_service

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SID = "1grn6UiQf8HqxcRSB3tMiZBLWGQCT1H7fCUNqv5CBA7A"   # さくっとPRキュー
PREVIEW = "プレビュー"
Q = "'PRキュー'"

GOLD = {"red": 0.769, "green": 0.604, "blue": 0.235}
CREAM = {"red": 0.992, "green": 0.965, "blue": 0.925}
INK = {"red": 0.227, "green": 0.192, "blue": 0.157}
GRAY = {"red": 0.55, "green": 0.52, "blue": 0.47}
WHITE = {"red": 1, "green": 1, "blue": 1}


def C(v):
    return {"userEnteredValue": {"formulaValue": v} if v.startswith("=") else {"stringValue": v}}


service = get_service()
meta = service.spreadsheets().get(spreadsheetId=SID).execute()
sheets = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
if PREVIEW in sheets:
    pid = sheets[PREVIEW]
    service.spreadsheets().batchUpdate(spreadsheetId=SID, body={"requests": [
        {"unmergeCells": {"range": {"sheetId": pid}}},
        {"updateCells": {"range": {"sheetId": pid}, "fields": "userEnteredValue,userEnteredFormat"}}]}).execute()
else:
    r = service.spreadsheets().batchUpdate(spreadsheetId=SID, body={"requests": [
        {"addSheet": {"properties": {"title": PREVIEW, "gridProperties": {"rowCount": 40, "columnCount": 6}}}}]}).execute()
    pid = r["replies"][0]["addSheet"]["properties"]["sheetId"]

IDX = lambda col: f"INDEX({Q}!{col}:{col},$B$1)"

rows = [
    ["プレビュー行番号 →", "2", "（2＝1件目）", "", "", ""],                              # 0
    ["", "", "", "", "", ""],                                                             # 1
    ["豊川ガイド ｜ さくっとPR", "", "", "", "", ""],                                      # 2 帯
    [f'=IFERROR(REGEXEXTRACT({IDX("N")},"ラベル：(.+)"),"PR")'
     f'&"　／　色："&IFERROR(REGEXEXTRACT({IDX("N")},"色：([^（\\n]+)"),"おまかせ")', "", "", "", "", ""],  # 3 ラベル・色
    [f'={IDX("E")}', "", "", "", "", ""],                                                 # 4 ひとこと（大）
    [f'={IDX("D")}', "", "", "", "", ""],                                                 # 5 店名
    [f'="● "&{IDX("G")}', "", "", "", "", ""],                                            # 6 住所
    ["", "", "", "", "", ""],                                                             # 7
    ["〈 記事タイトル 〉", "", "", "", "", ""],                                            # 8
    [f'="【PR】"&{IDX("D")}&"｜"&{IDX("E")}', "", "", "", "", ""],                        # 9
    ["〈 記事のながれ 〉", "", "", "", "", ""],                                            # 10
    [f'="豊川ガイドの広告コーナー「さくっとPR」。今回は、"&IF({IDX("F")}="","",{IDX("F")}&"の")&{IDX("D")}&"さんをご紹介します！"', "", "", "", "", ""],  # 11
    [f'=IF({IDX("L")}="","（紹介文メモ・未入力）",{IDX("L")})', "", "", "", "", ""],       # 12
    [f'=IF({IDX("K")}="","（特典なし）","🎁 特典："&{IDX("K")})', "", "", "", "", ""],     # 13
    [f'=IF({IDX("M")}="","（お店からのひとこと：なし）","💬 お店から："&{IDX("M")})', "", "", "", "", ""],  # 14
    [f'=IF({IDX("T")}="","（豊川ガイドから一言：なし・T列に書くと記事に載ります）","🦊 豊川ガイドから："&{IDX("T")})', "", "", "", "", ""],  # 15
    ["", "", "", "", "", ""],                                                             # 16
    ["〈 X投稿文（そのままコピペ可・URLは公開時に確定） 〉", "", "", "", "", ""],           # 17
    [f'="【PR】"&{IDX("D")}&"｜"&{IDX("E")}&CHAR(10)&IF({IDX("K")}="","","🎁 "&{IDX("K")}&CHAR(10))&"▼ 詳細"&CHAR(10)&"https://toyokawa-rentallife.com/"&LOWER({IDX("A")})&"/"&CHAR(10)&IF(ISNUMBER(SEARCH("豊川市",{IDX("G")})),"#PR #豊川市 #豊川ガイド #とよサポ #さくっとPR","#PR #豊川ガイド #さくっとPR")', "", "", "", "", ""],  # 18
    ["", "", "", "", "", ""],                                                             # 19
    [f'="📁 写真フォルダ名（マイドライブ＞ライト記事 の中に作る）： "&{IDX("A")}&"_"&{IDX("D")}', "", "", "", "", ""],  # 20
    [f'="状態： "&{IDX("C")}&" ／ 公開希望日： "&{IDX("B")}&"（朝10時に自動配信）"', "", "", "", "", ""],  # 21
]
grid = [{"values": [C(c) for c in row]} for row in rows]
service.spreadsheets().batchUpdate(spreadsheetId=SID, body={"requests": [
    {"updateCells": {"rows": grid, "fields": "userEnteredValue",
                     "start": {"sheetId": pid, "rowIndex": 0, "columnIndex": 0}}}]}).execute()


def fmt(r0, r1, bg=None, fg=None, bold=False, size=None, center=False):
    cf = {"textFormat": {}, "wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}
    if bg: cf["backgroundColor"] = bg
    if fg: cf["textFormat"]["foregroundColor"] = fg
    if bold: cf["textFormat"]["bold"] = True
    if size: cf["textFormat"]["fontSize"] = size
    if center: cf["horizontalAlignment"] = "CENTER"
    return {"repeatCell": {"range": {"sheetId": pid, "startRowIndex": r0, "endRowIndex": r1,
                                     "startColumnIndex": 0, "endColumnIndex": 6},
                           "cell": {"userEnteredFormat": cf}, "fields": "userEnteredFormat"}}


def mg(r0, r1):
    return {"mergeCells": {"range": {"sheetId": pid, "startRowIndex": r0, "endRowIndex": r1,
                                     "startColumnIndex": 0, "endColumnIndex": 6}, "mergeType": "MERGE_ALL"}}


reqs = [
    fmt(2, 3, bg=GOLD, fg=WHITE, bold=True, size=12, center=True),
    fmt(3, 4, bg=CREAM, fg=GRAY, size=10, center=True),
    fmt(4, 5, bg=CREAM, fg=INK, bold=True, size=20, center=True),
    fmt(5, 6, bg=CREAM, fg=INK, bold=True, size=13, center=True),
    fmt(6, 7, bg=CREAM, fg=GRAY, size=10, center=True),
    fmt(8, 9, fg=GRAY, bold=True, size=10),
    fmt(9, 10, fg=INK, bold=True, size=12),
    fmt(10, 11, fg=GRAY, bold=True, size=10),
    fmt(11, 16, fg=INK, size=10),
    fmt(17, 18, fg=GRAY, bold=True, size=10),
    fmt(18, 19, bg={"red": 0.96, "green": 0.96, "blue": 0.96}, fg=INK, size=10),
    fmt(20, 22, fg=GRAY, size=10),
]
reqs += [mg(r, r + 1) for r in [2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 21]]
reqs.append({"updateDimensionProperties": {
    "range": {"sheetId": pid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 6},
    "properties": {"pixelSize": 130}, "fields": "pixelSize"}})
reqs.append({"updateDimensionProperties": {
    "range": {"sheetId": pid, "dimension": "ROWS", "startIndex": 18, "endIndex": 19},
    "properties": {"pixelSize": 150}, "fields": "pixelSize"}})
service.spreadsheets().batchUpdate(spreadsheetId=SID, body={"requests": reqs}).execute()

# ── PRキュー T1 に「豊川ガイドから一言」列ヘッダー ──
hdr = service.spreadsheets().values().get(spreadsheetId=SID, range="PRキュー!T1").execute()
if not hdr.get("values"):
    service.spreadsheets().values().update(
        spreadsheetId=SID, range="PRキュー!T1", valueInputOption="RAW",
        body={"values": [["豊川ガイドから一言"]]}).execute()
    print("✅ PRキュー T1 に「豊川ガイドから一言」列を追加")
else:
    print(f"T1 は既に「{hdr['values'][0][0]}」")

print("✅ プレビュータブ完成（B1に行番号を入れて使う・2＝1件目）")
