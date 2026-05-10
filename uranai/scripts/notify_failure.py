"""
エラー通知（Gmail SMTP）
=========================

占い配信スクリプトがエラーで落ちた時に社長へ自動メール送信。
toyokawa-chintai/scrape_news_sources.py の send_email() パターンを流用。

【公開関数】
- notify_failure(subject, body) -> bool

【環境変数】
- GMAIL_USER: 送信元アドレス（例: toyokawa.rentallife@gmail.com）
- GMAIL_APP_PASSWORD: Gmailアプリパスワード（2段階認証必須）

【使い方】
  # スクリプト内から
  from notify_failure import notify_failure
  try:
      ...
  except Exception as e:
      notify_failure("[占い配信] エラー発生", str(e))
      raise

  # CLI でテスト
  python notify_failure.py --subject "テスト" --body "本文"
"""
from __future__ import annotations
import os
import sys
import smtplib
import traceback
from email.mime.text import MIMEText
from email.utils import formatdate
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(override=True)

JST = timezone(timedelta(hours=9))


def notify_failure(subject: str, body: str) -> bool:
    """Gmail で社長にエラー通知メール送信

    Args:
        subject: メール件名
        body: メール本文

    Returns:
        送信成功なら True、未設定/失敗なら False
    """
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        print("[warn] GMAIL_USER / GMAIL_APP_PASSWORD 未設定 → メール送信スキップ", file=sys.stderr)
        print(body)
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = user
    msg["To"] = user
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        print(f"[OK] エラー通知送信: {subject}")
        return True
    except Exception as e:
        print(f"[ERROR] メール送信失敗: {e}", file=sys.stderr)
        return False


def notify_uranai_failure(error: BaseException, context: dict | None = None) -> bool:
    """占い配信専用のエラー通知ヘルパー

    Args:
        error: 発生した例外
        context: 補足情報（target_date, weekday, step 等）

    Returns:
        送信成功なら True
    """
    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    context = context or {}

    subject = f"🚨 [占い配信] エラー発生 - {now_jst[:10]}"
    body_lines = [
        f"占い配信スクリプトでエラーが発生しました。",
        f"",
        f"発生時刻: {now_jst}",
        f"エラー: {type(error).__name__}: {error}",
        f"",
    ]
    if context:
        body_lines.append("--- 文脈 ---")
        for k, v in context.items():
            body_lines.append(f"  {k}: {v}")
        body_lines.append("")

    body_lines.append("--- スタックトレース ---")
    body_lines.append(traceback.format_exc())
    body_lines.append("")
    body_lines.append("--- 確認方法 ---")
    body_lines.append("1. GitHub Actionsのログでエラー詳細を確認")
    body_lines.append("2. 必要なら手動再実行（workflow_dispatch）")
    body_lines.append("")
    body_lines.append("このメールは自動送信です。")

    return notify_failure(subject, "\n".join(body_lines))


# ============================================================
# CLI（テスト用）
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", default="[占い配信テスト] 通知動作確認", help="メール件名")
    parser.add_argument("--body", default="このメールは notify_failure.py の動作確認です。", help="メール本文")
    args = parser.parse_args()
    ok = notify_failure(args.subject, args.body)
    sys.exit(0 if ok else 1)
