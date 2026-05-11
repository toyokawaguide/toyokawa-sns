"""週次リマインダー：META期限チェック＋X週次予約投稿用文面の生成

毎週日曜 21:00 JST に GHA から実行される。
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

JST = timezone(timedelta(hours=9))


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


def generate_x_captions(start_date: date) -> list[tuple[date, str, str]]:
    """翌週7日分の X 予約投稿用文面を生成（dry-run dummy data ベース）"""
    from caption import make_x_caption
    from select_lucky_spot import select_lucky_spot
    from generate_text import _dummy_template_data

    weekday_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    results = []
    for i in range(7):
        d = start_date + timedelta(days=i)
        wd = weekday_keys[d.weekday()]
        try:
            spot = select_lucky_spot(d)
        except Exception:
            continue
        data = _dummy_template_data(wd, d, spot)
        # 日曜は spots_week 補完
        if wd == "sun":
            spots_week = data.get("spots_week", {})
            if not spots_week:
                spots_week = {}
                for j, k in enumerate(["mon", "tue", "wed", "thu", "fri", "sat"]):
                    past_d = d - timedelta(days=6 - j)
                    try:
                        spots_week[k] = select_lucky_spot(past_d).name
                    except Exception:
                        pass
                data["spots_week"] = spots_week
        ymd = d.strftime("%Y%m%d")
        post_url = f"https://toyokawa-rentallife.com/{d.year}/{d.month:02d}/{d.day:02d}/uranai-{ymd}/"
        cap = make_x_caption(wd, data, spot, d, post_url)
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

    lines = []
    lines.append(f"豊川ガイド占い 週次リマインダー  {today_jst} 配信")
    lines.append("=" * 60)
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

    captions = generate_x_captions(next_monday)
    for d, wd, cap in captions:
        wd_jp = ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
        lines.append(f"━━━ {d}（{wd_jp}）— 予約 6:00 ━━━")
        lines.append(cap)
        lines.append("")

    lines.append("=" * 60)
    lines.append("自動配信：toyokawa-sns/weekly_reminder")

    body = "\n".join(lines)
    subject = f"[豊川ガイド占い] 週次リマインダー {today_jst}（X翌週分＋META期限）"
    if send_gmail(subject, body):
        print(f"OK: Gmail送信完了 → {os.getenv('GMAIL_USER')}")
    else:
        print("FAIL: Gmail送信失敗")
        print(body)


if __name__ == "__main__":
    main()
