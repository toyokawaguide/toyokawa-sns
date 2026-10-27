# -*- coding: utf-8 -*-
"""さくっとPR：お客さま（申込者）へのメール送信の安全装置（2026-10-27 新設・社長指示「二度と起きないように」）

事故: pr_photo_intake.py の本番実行で、処理済み記録に無い過去の返信すべてに完成イメージを再送し、
      9月に掲載済みの PR007（はらや）へ古い完成イメージが届いた。

申込者へのメールは必ず pr_intake.send_preview() を通る。そこで毎回この check() を呼び、
1つでも当てはまれば「送らない」（失敗側に倒す＝読めない・分からないときも送らない）。

  1) 状態ゲート: PRキューの状態が 申込／プレビュー送信済／手動対応 のときだけ送れる。
     draft・投稿済・取消・統合・サンプル など、プレビュー段階を過ぎた・終わった行には絶対に送らない。
  2) 連投ゲート: 同じIDへ30分以内に送っていたら送らない（二重実行・暴走ループ対策）。
  3) 回数ゲート: 同じIDへの送信が通算5回に達したら送らない（それ以上は社長が手で判断）。
  3b) 古さゲート: 受付から45日を過ぎた申込には送らない（やりとりが止まったままの古い申込を拾わない）。
  4) 記録: 送ったら PRキューのスプレッドシートの「送信記録」タブに1行残す（GHAとローカルで共有）。
     記録を読めない・書けないときは送らない。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

PR_SPREADSHEET_ID = "1grn6UiQf8HqxcRSB3tMiZBLWGQCT1H7fCUNqv5CBA7A"
LOG_TAB = "送信記録"
ALLOWED_STATES = {"申込", "プレビュー送信済", "手動対応"}
MIN_INTERVAL = timedelta(minutes=30)
MAX_SENDS_PER_ID = 5
MAX_AGE = timedelta(days=45)
JST = timezone(timedelta(hours=9))


def _svc():
    from sheets_client import get_service
    return get_service()


def _ensure_tab(svc):
    meta = svc.spreadsheets().get(spreadsheetId=PR_SPREADSHEET_ID, fields="sheets.properties.title").execute()
    titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if LOG_TAB not in titles:
        svc.spreadsheets().batchUpdate(spreadsheetId=PR_SPREADSHEET_ID, body={
            "requests": [{"addSheet": {"properties": {"title": LOG_TAB}}}]}).execute()
        svc.spreadsheets().values().update(
            spreadsheetId=PR_SPREADSHEET_ID, range=f"{LOG_TAB}!A1:E1", valueInputOption="RAW",
            body={"values": [["ID", "送信日時(JST)", "種類", "その時の状態", "実行場所"]]}).execute()


def _history(svc, pid: str) -> list[datetime]:
    vals = svc.spreadsheets().values().get(
        spreadsheetId=PR_SPREADSHEET_ID, range=f"{LOG_TAB}!A2:B5000").execute().get("values", [])
    out = []
    for r in vals:
        if len(r) >= 2 and r[0].strip() == pid:
            try:
                out.append(datetime.strptime(r[1].strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST))
            except ValueError:
                out.append(datetime.now(JST))   # 読めない日時は「たった今送った」扱い（安全側）
    return out


def check(row: dict) -> tuple[bool, str]:
    """送ってよいか。(OK, 理由)。例外が出たら送らない。"""
    pid = (row.get("ID") or "").strip()
    state = (row.get("状態") or "").strip()
    if not pid:
        return False, "IDが空"
    if state not in ALLOWED_STATES:
        return False, f"状態が「{state or '空'}」（送れるのは {'／'.join(sorted(ALLOWED_STATES))} だけ）"
    got = (row.get("受付日時") or "").strip()
    if got:
        try:
            g = datetime.strptime(got.split()[0].replace("/", "-"), "%Y-%m-%d").replace(tzinfo=JST)
            if datetime.now(JST) - g > MAX_AGE:
                return False, f"受付が{got.split()[0]}で{MAX_AGE.days}日を過ぎている（古い申込には送らない）"
        except ValueError:
            return False, f"受付日時「{got}」を読めない"
    try:
        svc = _svc()
        _ensure_tab(svc)
        hist = _history(svc, pid)
    except Exception as e:
        return False, f"送信記録を読めない（{e}）"
    now = datetime.now(JST)
    recent = [t for t in hist if now - t < MIN_INTERVAL]
    if recent:
        return False, f"{int(MIN_INTERVAL.total_seconds() // 60)}分以内に送信済み（最後 {max(recent):%H:%M}）"
    if len(hist) >= MAX_SENDS_PER_ID:
        return False, f"このIDへの送信が通算{len(hist)}回（上限{MAX_SENDS_PER_ID}回）。続けるなら社長が手で判断"
    return True, "OK"


def record(row: dict, kind: str) -> None:
    import os
    where = "GitHub Actions" if os.environ.get("GITHUB_ACTIONS") else "ローカルPC"
    svc = _svc()
    _ensure_tab(svc)
    svc.spreadsheets().values().append(
        spreadsheetId=PR_SPREADSHEET_ID, range=f"{LOG_TAB}!A:E", valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[(row.get("ID") or "").strip(), datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
                          kind, (row.get("状態") or "").strip(), where]]}).execute()
