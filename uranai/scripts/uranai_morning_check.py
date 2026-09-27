# -*- coding: utf-8 -*-
"""占い・朝の自動見張り番（毎朝8:15 JST・Windowsタスクでスリープ解除実行）

やること:
  1. 今日の占いWP記事とThreads投稿の死活チェック
  2. 両方OK → 「✅正常」をGmailで1通（毎朝必ず送る＝沈黙障害の検知）
  3. どちらか欠け → main.py --sns-only でローカル復旧（WP冪等・SNSマーカーで二重防止・
     再生成は1日1回ガード・Claude API 約¥6は社長包括承認済み 2026-08-28）→ 結果をGmail報告
  4. 復旧後は「GHAの遅延発火で二重になったら1件削除」の注意もメールに記載

GHAの正規リトライ(〜8:00 JST)が全部終わった後に走る設計。
"""
import sys, os, re, json, subprocess, smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
os.chdir(HERE)

from dotenv import load_dotenv
for env in [HERE.parent / ".env", HERE.parent.parent / "claude" / ".env"]:
    if env.exists():
        load_dotenv(env, override=True)

JST = timezone(timedelta(hours=9))
today = datetime.now(JST).date()
url = f"https://toyokawa-rentallife.com/{today.year}/{today.month:02d}/{today.day:02d}/uranai-{today.strftime('%Y%m%d')}/"

import requests

def gmail(subject, body):
    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and pw):
        print("Gmail認証なし・通知スキップ")
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = user
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)
    print("Gmail送信:", subject)

def check_wp():
    try:
        r = requests.get(url, timeout=30)
        return r.status_code == 200
    except Exception:
        return False

def check_threads():
    tok = os.environ.get("THREADS_ACCESS_TOKEN")
    if not tok:
        return None
    try:
        r = requests.get("https://graph.threads.net/v1.0/me/threads",
                         params={"fields": "text,timestamp", "limit": 10, "access_token": tok}, timeout=30)
        # 曜日付き日付キー（占いキャプション共通・金曜「ラッキー生まれ年」等「占い」の
        # 文字が無い曜日も正しく検知する。2026-08-28修正）
        wd = "月火水木金土日"[today.weekday()]
        key = f"{today.month}/{today.day}({wd})"
        for m in r.json().get("data", []):
            if key in (m.get("text") or ""):
                return True
        return False
    except Exception:
        return None

def check_ig():
    """Instagramに今日の占いがあるか（2026-09-28追加）"""
    tok = os.environ.get("META_ACCESS_TOKEN")
    if not tok:
        return None
    try:
        ig = os.environ.get("INSTAGRAM_ACCOUNT_ID") or os.environ.get("IG_USER_ID")
        if not ig:
            pg = requests.get("https://graph.facebook.com/v21.0/me", params={"fields": "instagram_business_account", "access_token": tok}, timeout=30).json()
            ig = (pg.get("instagram_business_account") or {}).get("id")
        r = requests.get(f"https://graph.facebook.com/v21.0/{ig}/media",
                         params={"fields": "caption", "limit": 10, "access_token": tok}, timeout=30)
        wd = "月火水木金土日"[today.weekday()]
        key = f"{today.month}/{today.day}({wd})"
        return any(key in (m.get("caption") or "") for m in r.json().get("data", []))
    except Exception:
        return None


def gha_still_coming():
    """GitHub側の今日の占いジョブが、まだ全部終わっていなければ True（2026-09-28追加）。
    9/27はGitHubのcronが2時間以上遅れ（6:00のSNS投稿が8:23に発火）、8:15にこの見張り番が
    「欠けている」と判断して自分で投稿→遅れて来たGHAがもう一度投稿して、Instagramが二重になった。
    今日のcronは10回（3:30〜8:00）。全部発火して、実行中・待機中が無くなるまでは手を出さない。"""
    try:
        since = datetime.combine(today, datetime.min.time(), JST).astimezone(timezone.utc)
        r = requests.get("https://api.github.com/repos/toyokawaguide/toyokawa-sns/actions/workflows/post_uranai.yml/runs",
                         params={"per_page": 30, "created": ">=" + since.strftime("%Y-%m-%dT%H:%M:%SZ"), "event": "schedule"},
                         headers={"Accept": "application/vnd.github+json"}, timeout=30)
        runs = r.json().get("workflow_runs", [])
        active = [x for x in runs if x.get("status") in ("queued", "in_progress", "waiting", "requested", "pending")]
        print(f"GHA: 今日の定時実行 {len(runs)}/10 回・実行中/待機中 {len(active)}")
        return len(runs) < 10 or bool(active)
    except Exception as e:
        print("GHA確認失敗（従来どおり判断）:", e)
        return False


import time
DEADLINE = datetime.combine(today, datetime.min.time(), JST) + timedelta(hours=11)   # 11:00 JST までは待つ
waited = 0
while True:
    wp_ok = check_wp()
    th_ok = check_threads()
    ig_ok = check_ig()
    print(f"WP: {'OK' if wp_ok else 'NG'} / Threads: {th_ok} / Instagram: {ig_ok}")
    if wp_ok and th_ok:
        gmail(f"✅占い正常 {today.month}/{today.day}", f"今朝の占いはWP・Threadsとも確認できました。\n{url}"
              + (f"\n（GitHubの遅れを {waited} 分待ってから確認）" if waited else ""))
        sys.exit(0)
    if wp_ok and ig_ok:
        # IGは出ているのにThreadsだけ無い → ここで復旧するとIGが二重になる。触らずに知らせるだけ
        gmail(f"⚠占い Threadsだけ未確認 {today.month}/{today.day}",
              "WPとInstagramは出ていますが、Threadsに今日の占いが見当たりません。\n"
              "二重投稿を避けるため自動復旧はしていません。必要ならThreadsだけ手動で投稿してください。\n" + url)
        sys.exit(0)
    if gha_still_coming() and datetime.now(JST) < DEADLINE:
        print("GitHubの定時実行がまだ残っている（遅延中）→ 10分待って再確認")
        time.sleep(600)
        waited += 10
        continue
    break

# ── 復旧実行 ──
print("欠けを検知 → ローカル復旧を実行")
r = subprocess.run([sys.executable, "-u", "main.py", "--date", str(today), "--sns-only"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
out = (r.stdout or "") + (r.stderr or "")
statuses = dict(re.findall(r'"(threads|instagram|instagram_reel)"\s*:\s*\{\s*"status"\s*:\s*"([^"]+)"', out))
wp_after = check_wp()

body = [f"今朝の占いが欠けていたため、自動復旧を実行しました（Claude API 約6円・包括承認済み）。", "",
        f"検知: WP={'OK' if wp_ok else 'NG'} / Threads={th_ok}", "",
        f"復旧結果:", f"  WP: {'OK' if wp_after else 'NG'} {url}"]
for k in ("threads", "instagram", "instagram_reel"):
    body.append(f"  {k}: {statuses.get(k, '不明')}")
body += ["", "※Xは手動予約のまま（自動投稿対象外）",
         "※もしThreadsに同じ占いが2件並んでいたら、GHAの遅延発火との衝突です。後の1件を削除してください。",
         "", "ログ末尾:", out[-1200:]]
ok_all = wp_after and all(statuses.get(k) == "ok" for k in ("threads", "instagram", "instagram_reel"))
gmail(("🔧占い自動復旧 成功" if ok_all else "🚨占い自動復旧 失敗あり・要確認") + f" {today.month}/{today.day}",
      "\n".join(body))
