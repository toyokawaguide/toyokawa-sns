"""
notify.py — Gmail通知（X予約用テキスト含む・社長手動投稿用）
"""
from __future__ import annotations
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD")


def send_x_caption_mail(article_id: str, title: str, x_text: str,
                         publish_at: str, wp_url: str = "",
                         dry: bool = True) -> dict:
    """X予約用テキストを Gmail で送信（社長がスマホからコピペ用）"""
    subject = f"【ライト記事】{publish_at[:10]} 19:00 公開・X予約用テキスト"
    body = f"""明日 {publish_at} 公開予定のライト記事のX投稿用テキストです。
スマホからコピーして、X公式アプリの予約投稿機能で {publish_at[:10]} 19:00 にセットしてください。

記事ID: {article_id}
タイトル: {title}
WP URL: {wp_url}

------------ コピペ用 ------------
{x_text}
------------ ここまで ------------

スマホでサクッと予約しちゃってください。
"""
    if dry:
        print(f"[DRY][Gmail] subject={subject}")
        print(f"[DRY][Gmail] body preview:\n{body[:300]}...")
        return {"dry": True}

    if not GMAIL_USER or not GMAIL_PASS:
        return {"error": "GMAIL_USER / GMAIL_APP_PASSWORD 未設定"}

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER  # 自分宛て

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_PASS)
        s.send_message(msg)

    return {"sent": True}


def send_skip_notification(reason: str, dry: bool = True) -> dict:
    """スキップ通知（手動投稿あり・ストック切れ等）"""
    subject = f"【ライト記事】本日の自動投稿をスキップ"
    body = f"""ライト記事の自動投稿をスキップしました。

理由: {reason}

詳細は GitHub Actions のログを確認してください。
"""
    if dry:
        print(f"[DRY][Gmail Skip] reason={reason}")
        return {"dry": True}

    if not GMAIL_USER or not GMAIL_PASS:
        return {"error": "GMAIL_USER / GMAIL_APP_PASSWORD 未設定"}

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_PASS)
        s.send_message(msg)
    return {"sent": True}
