"""週次リマインダー：META期限チェック＋X週次予約投稿用文面の生成

毎週土曜 21:00 JST に GHA から実行される。
Gmail で社長に：
1. META_ACCESS_TOKEN の有効期限（残り日数）
2. 期限7日以内なら警告
3. 翌週7日分の X 予約投稿用文面（コピペ可能）
4. Google カレンダー追加用リンク

を送信。
"""
from __future__ import annotations
import os
import sys
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from urllib.parse import quote

import requests

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ローカル実行用：.env 読み込み（GHA は環境変数 export 済なので影響なし）
# 探索順：toyokawa-sns側→豊川ガイド側（開発機ローカルにのみ存在）
try:
    from dotenv import load_dotenv
    _env_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        r"C:\Users\Yoshida\Desktop\豊川ガイド\占い\scripts\.env",
    ]
    for _ep in _env_paths:
        if os.path.exists(_ep):
            load_dotenv(_ep, override=True)
            break
except ImportError:
    pass

JST = timezone(timedelta(hours=9))

WEEKDAY_JP_FULL = ["月", "火", "水", "木", "金", "土", "日"]

# 曜日テーマ（社長確定 X予約投稿フォーマット用・2026-05-17確定）
WEEKDAY_THEME = {
    "mon": ("星座占い", "♈♉♊♋♌", "#星座占い"),
    "tue": ("血液型占い", "🩸🅰️🅱️🆎🅾️", "#血液型占い"),
    "wed": ("誕生月占い", "🎂🌸🌻🍁❄️", "#誕生月占い"),
    "thu": ("干支占い", "🐉🐯🐰🐍🐴", "#干支占い"),
    "fri": ("生まれ年占い", "🎂🎉🎁🎊", "#生まれ年占い"),
    "sat": ("ラッキータウン占い", "🏘️🗺️📍", "#豊川市"),
}


def _normalize_row_date(v):
    """シル/xlsx いずれの行先頭セルも date に正規化（失敗時 None）"""
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


def fetch_input_sheet_rows():
    """ラッキースポット入力シートを取得（Sheets のみ・xlsx 廃止）

    2026-05-25 案A：xlsx フォールバック完全削除。Sheets 取得失敗時は明確にエラー。

    Returns: (rows | None, source: "sheets"/"none")
    """
    try:
        import load_sheets
        if not load_sheets.is_enabled():
            print("[error] URANAI_SHEETS_URL / URANAI_SHEETS_SECRET が未設定。"
                  "GitHub Secrets と workflow.yml の env を確認してください。")
            return None, "none"
        rows = load_sheets.fetch_sheet_normalized("ラッキースポット入力")
        if rows is None:
            print("[error] Sheets から「ラッキースポット入力」取得失敗")
            return None, "none"
        return rows, "sheets"
    except Exception as e:
        print(f"[error] 入力シート取得失敗: {e}")
        return None, "none"


def check_lucky_spot_input(next_monday: date):
    """翌週 月〜土（6日）の入力状況をチェック

    Returns:
        (spot_map, source)
        spot_map = {date: {"name": str|None, "is_chain": bool}}
    """
    rows, source = fetch_input_sheet_rows()
    targets = [next_monday + timedelta(days=i) for i in range(6)]  # 月〜土
    if rows is None:
        return {d: {"name": None, "is_chain": False} for d in targets}, "none"
    found = {}
    # データ部は index 5 以降（select_lucky_spot.lookup_input_sheet 準拠）
    for r in rows[5:]:
        if not r or r[0] is None:
            continue
        rd = _normalize_row_date(r[0])
        if rd is None or rd not in targets:
            continue
        name = str(r[1]).strip() if len(r) > 1 and r[1] else None
        is_chain = bool(str(r[2]).strip()) if len(r) > 2 and r[2] else False
        found[rd] = {"name": name or None, "is_chain": is_chain}
    spot_map = {d: found.get(d, {"name": None, "is_chain": False}) for d in targets}
    return spot_map, source


def build_x_reservation_text(d: date, wd: str, name: str | None, is_chain: bool) -> str:
    """社長確定フォーマット（2026-05-17）のX予約投稿文面を生成"""
    md = f"{d.month}/{d.day}"
    wd_jp = WEEKDAY_JP_FULL[d.weekday()]
    ymd = d.strftime("%Y%m%d")
    url = f"https://toyokawa-rentallife.com/{d.year}/{d.month:02d}/{d.day:02d}/uranai-{ymd}/"
    if wd == "sun":
        return (
            f"🔮{md}({wd_jp})今週まとめ&来週運勢\n\n"
            f"今週も1週間お疲れさまでした!\n\n"
            f"🌱今週のラッキースポット6選まとめと\n"
            f"来週の運勢のヒントは記事で👇\n\n"
            f"{url}\n\n"
            f"明日からまた毎朝のお楽しみに✨\n\n"
            f"#豊川ガイド #とよサポ #今週のまとめ #占い"
        )
    label, theme_emoji, tag3 = WEEKDAY_THEME[wd]
    if name:
        spot_disp = f"お近くの{name}" if is_chain else name
    else:
        spot_disp = "⚠️未入力（Sheetsに記入してください）"
    return (
        f"🔮 {md}({wd_jp})の占い\n\n"
        f"今日は「{label}」{theme_emoji}\n"
        f"詳しくは豊川ガイドで👇\n"
        f"{url}\n\n"
        f"🦊 管理人の独断と偏見と忖度による\n"
        f"本日のラッキースポット\n"
        f"👉 {spot_disp}\n\n"
        f"#豊川ガイド #とよサポ #今日の占い {tag3}"
    )


def check_meta_token() -> dict:
    """META_ACCESS_TOKEN の有効期限をチェック"""
    token = os.getenv("META_ACCESS_TOKEN")
    if not token:
        return {"status": "missing"}

    try:
        r = requests.get(
            "https://graph.facebook.com/v19.0/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=30,
        )
        if r.status_code != 200:
            return {"status": "error", "error": r.text[:200]}
        data = r.json().get("data", {})
        is_valid = data.get("is_valid", False)
        expires_at = data.get("expires_at", 0)
        if not is_valid:
            return {"status": "invalid"}
        if expires_at == 0:
            return {"status": "never_expires"}
        expiry = datetime.fromtimestamp(expires_at, tz=JST).date()
        days_left = (expiry - datetime.now(JST).date()).days
        return {"status": "ok", "expiry": str(expiry), "days_left": days_left}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def check_threads_token() -> dict:
    """THREADS_ACCESS_TOKEN の有効性チェック（2026-06-16 追加）。
    Threads は debug_token で残り日数が取りにくいので「有効/無効」を実コールで判定。
    6/14 にトークンが期限切れしたのを META チェックだけでは検知できなかった対策。"""
    token = os.getenv("THREADS_ACCESS_TOKEN")
    user = os.getenv("THREADS_USER_ID")
    if not token or not user:
        return {"status": "missing"}
    try:
        r = requests.get(
            f"https://graph.threads.net/v1.0/{user}/threads",
            params={"fields": "id", "limit": 1, "access_token": token},
            timeout=30,
        )
        if r.status_code == 200:
            return {"status": "ok"}
        err = r.json().get("error", {})
        return {"status": "invalid", "message": err.get("message", r.text[:160])}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def generate_x_captions(start_date: date) -> list[tuple[date, str, str]]:
    """翌週7日分の X 予約投稿用文面を生成。
    ⚠️ 予約投稿には占いTOP3（ダミー変動値）を載せない。build_x_reservation_text の
    安全版（テーマ名＋リンク誘導＋確定ラッキースポットのみ）を使う。
    予約時点では実配信の順位が未確定 → TOP3を書くと実配信と食い違うため。
    （2026-06-07 ダミーTOP3版から切替・feedback_scheduled_post_safe_content 準拠）"""
    from select_lucky_spot import select_lucky_spot

    weekday_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    results = []
    for i in range(7):
        d = start_date + timedelta(days=i)
        wd = weekday_keys[d.weekday()]
        try:
            spot = select_lucky_spot(d)
            name = getattr(spot, "name", None)
            is_chain = getattr(spot, "is_chain", False)
        except Exception:
            name, is_chain = None, False
        cap = build_x_reservation_text(d, wd, name, is_chain)
        results.append((d, wd, cap))
    return results


def make_calendar_link(title: str, dt: datetime, duration_min: int = 10, details: str = "") -> str:
    """Google カレンダーにイベント追加するURL"""
    start = dt.strftime("%Y%m%dT%H%M%S")
    end = (dt + timedelta(minutes=duration_min)).strftime("%Y%m%dT%H%M%S")
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start}/{end}",
        "details": details,
        "ctz": "Asia/Tokyo",
    }
    qs = "&".join(f"{k}={quote(v)}" for k, v in params.items())
    return f"https://calendar.google.com/calendar/render?{qs}"


def send_gmail(subject: str, body: str) -> bool:
    user = os.getenv("GMAIL_USER")
    pwd = os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pwd:
        print("GMAIL_USER / GMAIL_APP_PASSWORD 未設定")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = user
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pwd)
        s.send_message(msg)
    return True


def main():
    today_jst = datetime.now(JST).date()
    # 翌週月曜（今日が日曜ならその日+1）
    days_to_monday = (7 - today_jst.weekday()) % 7 or 7
    next_monday = today_jst + timedelta(days=days_to_monday)
    next_sunday = next_monday + timedelta(days=6)
    next_saturday = next_monday + timedelta(days=5)

    # 翌週 月〜土 のラッキースポット入力チェック（最優先）
    spot_map, src = check_lucky_spot_input(next_monday)
    missing = [d for d in sorted(spot_map) if not spot_map[d]["name"]]

    lines = []
    lines.append(f"豊川ガイド占い 週次リマインダー  {today_jst} 配信")
    lines.append("=" * 60)
    lines.append("")

    # 0. ラッキースポット入力チェック（社長が見落とさないよう冒頭配置）
    lines.append("【0】翌週ラッキースポット入力チェック（月〜土）")
    lines.append("-" * 40)
    lines.append(f"  対象: {next_monday}（月）〜 {next_saturday}（土） ※日曜は週まとめのため不要")
    src_label = {"sheets": "Google Sheets"}.get(src, "🚨 取得失敗（Sheets参照不可）")
    lines.append(f"  データソース: {src_label}")
    if src != "sheets":
        lines.append("  🚨🚨 Sheets取得失敗。GitHub Secrets URANAI_SHEETS_URL / URANAI_SHEETS_SECRET と")
        lines.append("       weekly_reminder.yml / daily_diff_check.yml の env: を確認")
    if missing:
        lines.append("")
        lines.append("  🚨🚨🚨 未入力あり！下記をSheetsに記入してください 🚨🚨🚨")
        for d in missing:
            wd_jp = WEEKDAY_JP_FULL[d.weekday()]
            lines.append(f"    ・{d}（{wd_jp}）が空欄です")
        lines.append("  → Google Sheets「ラッキースポット入力」シートのB列に記入")
    else:
        lines.append("  ✅ 月〜土の6日すべて入力済み")
        for d in sorted(spot_map):
            wd_jp = WEEKDAY_JP_FULL[d.weekday()]
            info = spot_map[d]
            disp = f"お近くの{info['name']}" if info["is_chain"] else info["name"]
            lines.append(f"    {d}（{wd_jp}）: {disp}")
    lines.append("")

    # 1. META トークン期限チェック
    lines.append("【1】META_ACCESS_TOKEN 期限チェック")
    lines.append("-" * 40)
    token_info = check_meta_token()
    if token_info["status"] == "ok":
        days = token_info["days_left"]
        expiry = token_info["expiry"]
        lines.append(f"  期限: {expiry}（残り {days} 日）")
        if days <= 7:
            lines.append("  ⚠️⚠️⚠️ 7日以内に期限切れ！至急再発行してください ⚠️⚠️⚠️")
            lines.append("  手順：https://developers.facebook.com/tools/explorer/")
            lines.append("  詳細：memory/project_uranai_reminders.md")
            # カレンダー追加リンク
            cal_link = make_calendar_link(
                title="[要対応] META_ACCESS_TOKEN 再発行",
                dt=datetime.combine(today_jst + timedelta(days=1), datetime.min.time().replace(hour=10), tzinfo=JST),
                duration_min=30,
                details="Meta for Developers でトークン再発行 → GitHub Secrets 更新",
            )
            lines.append(f"  📅 カレンダー追加: {cal_link}")
        elif days <= 14:
            lines.append(f"  ⚠️ 期限まで {days} 日です。そろそろ再発行を検討")
        else:
            lines.append(f"  ✅ 余裕あり（{days} 日後）")
    elif token_info["status"] == "never_expires":
        lines.append("  ✅ 無期限トークン")
    elif token_info["status"] == "invalid":
        lines.append("  ❌ トークンが無効です！再発行が必要")
    elif token_info["status"] == "missing":
        lines.append("  ⚠️ META_ACCESS_TOKEN が GitHub Secrets に未設定")
    else:
        lines.append(f"  ❓ 状態不明: {token_info}")
    lines.append("")

    # 1.5 Threads トークン有効性チェック（2026-06-16 追加・6/14期限切れ見落とし対策）
    lines.append("【1.5】THREADS_ACCESS_TOKEN 有効性チェック")
    lines.append("-" * 40)
    th_info = check_threads_token()
    if th_info["status"] == "ok":
        lines.append("  ✅ Threadsトークン有効")
    elif th_info["status"] == "invalid":
        lines.append("  ❌❌❌ Threadsトークンが無効/期限切れ！至急 再発行してください ❌❌❌")
        lines.append(f"     {th_info.get('message', '')}")
        lines.append("     → 占い・記事SNS 両方の Threads 投稿が停止します")
        lines.append("     更新先：GitHub Secrets THREADS_ACCESS_TOKEN（toyokawa-sns ＋ toyokawa-article-sns 両方）")
        lines.append("     手順：memory/project_uranai_reminders.md")
    elif th_info["status"] == "missing":
        lines.append("  ⚠️ THREADS_ACCESS_TOKEN / THREADS_USER_ID が未設定（env を確認）")
    else:
        lines.append(f"  ❓ 状態不明: {th_info}")
    lines.append("")

    # 2. 翌週 X 予約投稿用文面
    lines.append("【2】X 予約投稿用文面（翌週分）")
    lines.append("-" * 40)
    lines.append(f"  対象期間: {next_monday}（月）〜 {next_sunday}（日）")
    lines.append("  予約手順: https://x.com/compose/post で予約投稿登録")
    lines.append("")
    # 翌週月曜の予約セットアップ用カレンダー追加リンク
    cal_link = make_calendar_link(
        title="[占い] X 予約投稿登録（翌週分）",
        dt=datetime.combine(today_jst, datetime.min.time().replace(hour=21), tzinfo=JST),
        duration_min=15,
        details="このメールから7日分の X 文面をコピペして予約投稿登録",
    )
    lines.append(f"  📅 カレンダー追加: {cal_link}")
    lines.append("")

    weekday_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    for i in range(7):
        d = next_monday + timedelta(days=i)
        wd = weekday_keys[d.weekday()]
        wd_jp = WEEKDAY_JP_FULL[d.weekday()]
        if wd == "sun":
            txt = build_x_reservation_text(d, wd, None, False)
        else:
            info = spot_map.get(d, {"name": None, "is_chain": False})
            txt = build_x_reservation_text(d, wd, info["name"], info["is_chain"])
        lines.append(f"━━━ {d}（{wd_jp}）— 予約 6:00 ━━━")
        lines.append(txt)
        lines.append("")

    lines.append("=" * 60)
    lines.append("自動配信：toyokawa-sns/weekly_reminder")

    body = "\n".join(lines)
    warn = "【⚠️要記入】" if missing else ""
    subject = f"[豊川ガイド占い]{warn} 週次リマインダー {today_jst}（X翌週分＋入力チェック）"
    if send_gmail(subject, body):
        print(f"OK: Gmail送信完了 → {os.getenv('GMAIL_USER')}")
    else:
        print("FAIL: Gmail送信失敗")
        print(body)


if __name__ == "__main__":
    main()
