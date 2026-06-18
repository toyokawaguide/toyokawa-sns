# -*- coding: utf-8 -*-
"""token_health_check.py — SNSトークンの毎日健康診断（再発防止・2026-06-16 新設）。

背景：2026-06-14 に Threads トークンが期限切れ→占い/記事SNSのThreads投稿が数日間停止。
当時の監視は weekly_reminder が META だけをチェックしており、Threads は無監視＝見落とした。
対策：毎日 META と Threads の両方を点検し、問題がある時だけ Gmail で大きく警告する。

判定：
  - META（Instagram用）：残り14日以内 or 無効 → 警告
  - Threads：実際にAPIを叩いて無効/期限切れ → 警告
問題が無ければ何も送らない（毎日のメール洪水を防ぐ）。

env: META_ACCESS_TOKEN / THREADS_ACCESS_TOKEN / THREADS_USER_ID / GMAIL_USER / GMAIL_APP_PASSWORD
"""
from __future__ import annotations
import os
import sys
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText

import requests

sys.stdout.reconfigure(encoding="utf-8")

# ローカル実行用 .env（GHA は env 注入済なので影響なし）
try:
    from dotenv import load_dotenv
    for _ep in (os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
                r"C:\Users\Yoshida\Desktop\豊川ガイド\占い\scripts\.env",
                r"C:\Users\Yoshida\Desktop\豊川ガイド\claude\.env"):
        if os.path.exists(_ep):
            load_dotenv(_ep, override=True)
except ImportError:
    pass

JST = timezone(timedelta(hours=9))
WARN_DAYS = 14


def check_meta() -> tuple[str, str, str | None]:
    token = os.getenv("META_ACCESS_TOKEN")
    if not token:
        return ("META(Instagram用)", "missing", "META_ACCESS_TOKEN が未設定")
    try:
        r = requests.get("https://graph.facebook.com/v19.0/debug_token",
                         params={"input_token": token, "access_token": token}, timeout=30)
        d = r.json().get("data", {})
        if not d.get("is_valid"):
            return ("META(Instagram用)", "invalid", "無効/期限切れ → Instagram投稿が停止します")
        exp = d.get("expires_at", 0)
        if exp == 0:
            return ("META(Instagram用)", "ok", None)
        expiry = datetime.fromtimestamp(exp, tz=JST).date()
        days = (expiry - datetime.now(JST).date()).days
        if days <= WARN_DAYS:
            return ("META(Instagram用)", "warn", f"残り {days} 日（{expiry}）→ 期限切れ前に再発行を")
        return ("META(Instagram用)", "ok", f"残り {days} 日（{expiry}）")
    except Exception as e:
        return ("META(Instagram用)", "error", str(e))


def check_threads() -> tuple[str, str, str | None]:
    token = os.getenv("THREADS_ACCESS_TOKEN")
    user = os.getenv("THREADS_USER_ID")
    if not token or not user:
        return ("Threads", "missing", "THREADS_ACCESS_TOKEN / THREADS_USER_ID が未設定")
    try:
        r = requests.get(f"https://graph.threads.net/v1.0/{user}/threads",
                         params={"fields": "id", "limit": 1, "access_token": token}, timeout=30)
        if r.status_code == 200:
            return ("Threads", "ok", None)
        msg = r.json().get("error", {}).get("message", r.text[:160])
        return ("Threads", "invalid", f"無効/期限切れ → Threads投稿が停止します: {msg}")
    except Exception as e:
        return ("Threads", "error", str(e))


def check_google_token(label: str, token_b64_env: str, local_token_path: str,
                       sheet_id: str) -> tuple[str, str, str | None]:
    """Google OAuthトークン（Sheets/Drive）の健康診断（2026-06-18 追加）。
    背景：2026-06-17 ライト記事・2026-06-18 記事SNS が GHA の Google トークン失効で
    数日サイレントに投稿停止。従来は META/Threads しか見ておらず Google は無監視だった。
    判定：b64環境変数(GHA) or ローカルtoken.json を読み、リフレッシュ＋簡単なSheets読みで生存確認。
          未設定なら 'skip'（誤警告しない）／失効・認証失敗なら 'invalid'（警告）。"""
    import base64
    import json
    raw = os.getenv(token_b64_env)
    info = None
    if raw:
        try:
            info = json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception as e:
            return (f"Google({label})", "error", f"{token_b64_env} のb64デコード失敗: {e}")
    elif local_token_path and os.path.exists(local_token_path):
        try:
            info = json.loads(open(local_token_path, encoding="utf-8").read())
        except Exception as e:
            return (f"Google({label})", "error", f"ローカルtoken読込失敗: {e}")
    else:
        # GHAでもローカルでもトークンが渡っていない＝この環境では点検対象外（誤警告しない）
        return (f"Google({label})", "skip", f"{token_b64_env}/ローカルtoken いずれも無し→点検対象外")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return (f"Google({label})", "skip", "googleライブラリ未導入→点検スキップ")
    try:
        scopes = info.get("scopes") or [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly"]
        creds = Credentials.from_authorized_user_info(info, scopes)
        if not creds.valid:
            creds.refresh(Request())  # invalid_grant（失効/取消）等はここで例外
        svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
        svc.spreadsheets().values().get(spreadsheetId=sheet_id, range="A1").execute()
        return (f"Google({label})", "ok", None)
    except Exception as e:
        return (f"Google({label})", "invalid", f"認証失敗→{label}のSheets読込/投稿が止まります: {str(e)[:160]}")


def send_gmail(subject: str, body: str) -> bool:
    user = os.getenv("GMAIL_USER")
    pwd = os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pwd:
        print("GMAIL 未設定。本文:\n" + body)
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
    results = [
        check_meta(),
        check_threads(),
        check_google_token(
            "ライト記事", "LIGHT_GOOGLE_TOKEN_B64",
            r"C:\Users\Yoshida\Desktop\toyokawa-sns\light_articles\scripts\_assets\sheets_token.json",
            "155K-AQdLNUiYb4Z3MK-elyG1U7UIIxPeu397uZsVxdo"),
        check_google_token(
            "記事SNS", "SNS_GOOGLE_TOKEN_B64",
            r"C:\Users\Yoshida\Desktop\toyokawa-article-sns\scripts\_assets\sheets_token.json",
            "1Z4flDlXdypPaXrbFW3tRjxk0XX4c-hVJxKkVODYOZRA"),
    ]
    for name, status, msg in results:
        print(f"{name}: {status}  {msg or ''}")

    problems = [r for r in results if r[1] in ("invalid", "warn", "missing", "error")]
    if not problems:
        print("✅ 全トークン健全。通知なし。")
        return

    hard = any(r[1] in ("invalid", "missing") for r in problems)
    lines = [
        "SNSトークンの健康診断で問題が見つかりました。",
        "（放置すると占い・記事SNSの Instagram / Threads 投稿が止まります）",
        "",
    ]
    for name, status, msg in problems:
        mark = "❌" if status in ("invalid", "missing") else ("⚠️" if status == "warn" else "❓")
        lines.append(f"{mark} {name}: {status}")
        lines.append(f"    {msg}")
        lines.append("")
    lines.append("【対応手順】")
    lines.append("  Threads: claude/トークン管理/Threadsトークン_再取得手順（保存版）.md")
    lines.append("  META   : Meta for Developers でトークン再発行 → GitHub Secrets 更新")
    lines.append("  更新先 : toyokawa-sns ＋ toyokawa-article-sns の Secrets 両方")
    body = "\n".join(lines)
    warn = "❌至急" if hard else "⚠️要注意"
    if send_gmail(f"[豊川ガイド]{warn} SNSトークン健康診断", body):
        print("Gmail通知 送信完了")


if __name__ == "__main__":
    main()
