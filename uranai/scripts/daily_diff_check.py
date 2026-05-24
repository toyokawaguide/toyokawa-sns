"""ラッキースポット 日次差分検知＋Gmail通知

毎日 JST 00:00 に GHA から実行。
ラッキースポット入力シートの「今日以降〜先30日」を読み、前日朝のスナップショットと比較。
追記・変更があれば社長にGmail通知（Xの予約投稿と齟齬しないよう気づきを促す）。

【動作】
- 初回（snapshot無し）: 保存のみ・メールなし
- 2回目以降: 差分があればメール送信、なければ静か
- 差分: 追加(新規入力)・変更(値が変わった)・削除(値が消えた)

【環境変数（GHAから）】
- URANAI_SHEETS_URL / URANAI_SHEETS_SECRET（シート取得）
- GMAIL_USER / GMAIL_APP_PASSWORD（送信）

スナップショット: uranai/data/spot_daily_snapshot.json （GHAがcommit&push）
"""
from __future__ import annotations
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

JST = timezone(timedelta(hours=9))
WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]
LOOKAHEAD_DAYS = 30  # 今日以降の検知範囲
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "spot_daily_snapshot.json"


def _normalize_row_date(v):
    """先頭セルを date に正規化"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def fetch_current_spots(today: date) -> dict[str, dict]:
    """ラッキースポット入力シートから 今日〜+30日 のスポット情報を取得

    Returns: {"YYYY-MM-DD": {"name": str|None, "is_chain": bool}}
    """
    from weekly_reminder import fetch_input_sheet_rows
    rows, source = fetch_input_sheet_rows()
    print(f"[daily_diff] データソース: {source}")
    if rows is None:
        return {}
    horizon = today + timedelta(days=LOOKAHEAD_DAYS)
    result: dict[str, dict] = {}
    # データ部は index 5 以降（weekly_reminder.check_lucky_spot_input 準拠）
    for r in rows[5:]:
        if not r or r[0] is None:
            continue
        rd = _normalize_row_date(r[0])
        if rd is None:
            continue
        if rd < today or rd > horizon:
            continue
        name = str(r[1]).strip() if len(r) > 1 and r[1] else None
        is_chain = bool(str(r[2]).strip()) if len(r) > 2 and r[2] else False
        result[rd.strftime("%Y-%m-%d")] = {
            "name": name or None,
            "is_chain": is_chain,
        }
    return result


def load_snapshot() -> dict | None:
    """前回スナップショット読込（無ければ None）"""
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        with SNAPSHOT_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[daily_diff] snapshot 読込失敗: {e}")
        return None


def save_snapshot(spots: dict[str, dict], today: date) -> None:
    """今日分のスナップショットを保存"""
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": datetime.now(JST).isoformat(),
        "captured_date": today.strftime("%Y-%m-%d"),
        "lookahead_days": LOOKAHEAD_DAYS,
        "spots": spots,
    }
    with SNAPSHOT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[daily_diff] snapshot 保存: {SNAPSHOT_PATH.name} ({len(spots)}件)")


def compute_diff(current: dict[str, dict], previous: dict[str, dict],
                  today_iso: str) -> list[dict]:
    """current vs previous の差分を返す（今日以降のみ）

    snapshot が古い場合に過去日が previous に残っていると「削除」と誤判定するため、
    today_iso（今日のISO日付）より前の日付は比較対象から除外する。

    各要素: {"date": "YYYY-MM-DD", "kind": "added/changed/removed", "from": str|None, "to": str|None}
    """
    diffs = []
    # 今日以降の日付のみ比較対象
    all_dates = sorted({d for d in (set(current) | set(previous)) if d >= today_iso})
    for d in all_dates:
        cur = current.get(d)
        prv = previous.get(d)
        cur_name = cur["name"] if cur else None
        prv_name = prv["name"] if prv else None
        if cur_name == prv_name:
            continue
        if prv_name is None and cur_name is not None:
            kind = "added"
        elif cur_name is None and prv_name is not None:
            kind = "removed"
        else:
            kind = "changed"
        diffs.append({"date": d, "kind": kind, "from": prv_name, "to": cur_name})
    return diffs


def format_diff_email(diffs: list[dict], today: date) -> tuple[str, str]:
    kind_emoji = {"added": "🆕", "changed": "🔁", "removed": "❌"}
    kind_label = {"added": "追加", "changed": "変更", "removed": "削除"}
    subject = f"⚠️【占い】ラッキースポット変更検知 {today.strftime('%Y-%m-%d')}（{len(diffs)}件）"

    lines = []
    lines.append(f"スプレッドシートの「ラッキースポット入力」が前日朝と比較して変わっています。")
    lines.append(f"検知日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}（JST）")
    lines.append(f"検知範囲: 今日〜先{LOOKAHEAD_DAYS}日（{today} 〜 {today + timedelta(days=LOOKAHEAD_DAYS)}）")
    lines.append("")
    lines.append("=" * 60)
    lines.append(f"変更内容（{len(diffs)}件）")
    lines.append("=" * 60)
    for d in diffs:
        try:
            dt = datetime.strptime(d["date"], "%Y-%m-%d").date()
            wd = WEEKDAY_JP[dt.weekday()]
        except Exception:
            wd = "?"
        emj = kind_emoji.get(d["kind"], "・")
        lbl = kind_label.get(d["kind"], d["kind"])
        if d["kind"] == "added":
            lines.append(f"  {emj} {d['date']}（{wd}）{lbl}: → {d['to']}")
        elif d["kind"] == "removed":
            lines.append(f"  {emj} {d['date']}（{wd}）{lbl}: {d['from']} →（空）")
        else:
            lines.append(f"  {emj} {d['date']}（{wd}）{lbl}: {d['from']} → {d['to']}")
    lines.append("")
    lines.append("=" * 60)
    lines.append("【次のアクション】")
    lines.append("=" * 60)
    lines.append("Xの予約投稿も同じ内容になっているか確認してください。")
    lines.append("違っていれば X Web UI（https://x.com/scheduled_posts）")
    lines.append("で該当日の予約投稿を編集してください。")
    lines.append("")
    lines.append("---")
    lines.append("自動配信: toyokawa-sns/daily_diff_check（毎日 JST 00:00）")
    return subject, "\n".join(lines)


def send_email(subject: str, body: str) -> bool:
    from weekly_reminder import send_gmail
    return send_gmail(subject, body)


def main():
    today = datetime.now(JST).date()
    print(f"[daily_diff] 起動: {today} (JST 00:00 想定)")

    current = fetch_current_spots(today)
    if not current:
        print("[daily_diff] 現在のスポット取得失敗または0件→処理中止（スナップショットは更新しない）")
        return

    previous = load_snapshot()
    if previous is None:
        print("[daily_diff] 初回実行：スナップショット保存のみ、メールなし")
        save_snapshot(current, today)
        return

    prev_spots = previous.get("spots", {})
    diffs = compute_diff(current, prev_spots, today.strftime("%Y-%m-%d"))
    print(f"[daily_diff] 差分: {len(diffs)}件")

    if diffs:
        subject, body = format_diff_email(diffs, today)
        if send_email(subject, body):
            print(f"[daily_diff] Gmail送信完了 → {os.getenv('GMAIL_USER')}")
        else:
            print("[daily_diff] Gmail送信失敗")
            print(subject)
            print(body)
    else:
        print("[daily_diff] 変更なし・メール送信なし")

    save_snapshot(current, today)


if __name__ == "__main__":
    main()
