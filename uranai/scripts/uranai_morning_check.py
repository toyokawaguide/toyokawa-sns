# -*- coding: utf-8 -*-
"""占い・朝の自動見張り番（毎朝 06:05 JST・Windowsタスクでスリープ解除実行）

【2026-10-01 全面改修】原因究明の結果：
  - GitHub Actions の cron は毎時 :00/:30 が大混雑で、9/21〜10/1 の11日間すべて 3〜4時間遅れ
    （06:00 の SNS 投稿が実際には 09:00〜10:00 に到着）。
  - 旧見張り番（8:15 起動）は「GHAがまだ来るかも」と 10分おきに待ち続け、
    Windowsタスクの実行上限 45 分で強制終了（結果コード 267014）→ メールも出ず沈黙していた。

新しい動き（沈黙しない・待たない・PCで再生成しない）：
  1. 06:05 に起動 → WP記事 / Threads / Instagram の死活チェック
  2. 全部OK → 「✅正常」メール1通（毎朝必ず送る）
  3. 欠けあり → すぐ GitHub Actions を workflow_dispatch で起こす（cronと違って即時実行）
       - WPが無い      → mode=publish  （フル生成・Claude API 約¥6＝通常の1日分と同じ・遅れて来るcronは公開済みスキップ）
       - WPはあるがSNS無 → mode=sns-only（bridgeキャッシュ利用・¥0。無ければGHA側で1回だけ再生成）
     → 最大25分、1分おきに Threads/IG を確認。出たら「🔧復旧」メール。
  4. dispatch できない／25分待っても出ない → 最後の手段でローカル main.py --sns-only（従来どおり）
  5. どの経路でも必ずメール。ログは uranai/output/morning_check_YYYY-MM-DD.log に全部残す
  二重投稿：main.py 側が Threads/IG の実投稿を見てスキップするので、遅れて来た cron と衝突しない（9/28対策）。
"""
import sys, os, re, json, subprocess, smtplib, time
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
OUT = HERE.parent / "output"; OUT.mkdir(exist_ok=True)
LOG = OUT / f"morning_check_{today}.log"
REPO = "toyokawaguide/toyokawa-sns"
WF = "post_uranai.yml"

import requests


def log(*a):
    line = f"[{datetime.now(JST):%H:%M:%S}] " + " ".join(str(x) for x in a)
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def gmail(subject, body):
    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and pw):
        log("Gmail認証なし・通知スキップ"); return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject; msg["From"] = user; msg["To"] = user
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pw); s.send_message(msg)
        log("Gmail送信:", subject)
    except Exception as e:
        log("Gmail送信失敗:", e)


def check_wp():
    try:
        return requests.get(url, timeout=30).status_code == 200
    except Exception:
        return False


def _key():
    wd = "月火水木金土日"[today.weekday()]
    return f"{today.month}/{today.day}({wd})"


def check_threads():
    tok = os.environ.get("THREADS_ACCESS_TOKEN")
    if not tok:
        return None
    try:
        r = requests.get("https://graph.threads.net/v1.0/me/threads",
                         params={"fields": "text,timestamp", "limit": 10, "access_token": tok}, timeout=30)
        return any(_key() in (m.get("text") or "") for m in r.json().get("data", []))
    except Exception:
        return None


def check_ig():
    tok = os.environ.get("META_ACCESS_TOKEN")
    if not tok:
        return None
    try:
        ig = os.environ.get("INSTAGRAM_ACCOUNT_ID") or os.environ.get("IG_USER_ID") or "17841467629335560"
        r = requests.get(f"https://graph.facebook.com/v21.0/{ig}/media",
                         params={"fields": "caption", "limit": 10, "access_token": tok}, timeout=30)
        return any(_key() in (m.get("caption") or "") for m in r.json().get("data", []))
    except Exception:
        return None


def status_line():
    wp, th, ig = check_wp(), check_threads(), check_ig()
    return wp, th, ig, f"WP: {'OK' if wp else 'NG'} / Threads: {th} / Instagram: {ig}"


# ── GitHub Actions を即時起動（cron遅延の回避） ──
def gh_token():
    """Windows資格情報マネージャーに保存済みの GitHub トークン（git credential fill）。秘密は表示しない"""
    try:
        r = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\nusername=toyokawaguide\n\n",
                           capture_output=True, text=True, timeout=30)
        for ln in r.stdout.splitlines():
            if ln.startswith("password="):
                return ln.split("=", 1)[1].strip()
    except Exception as e:
        log("トークン取得失敗:", e)
    return None


def gha_dispatch(mode):
    tok = gh_token()
    if not tok:
        return False, "トークンなし"
    try:
        r = requests.post(f"https://api.github.com/repos/{REPO}/actions/workflows/{WF}/dispatches",
                          headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"},
                          json={"ref": "main", "inputs": {"mode": mode}}, timeout=30)
        return r.status_code == 204, f"HTTP {r.status_code} {r.text[:120]}"
    except Exception as e:
        return False, str(e)


def gha_today_summary():
    """今日の定時実行が何回来ているか（遅延の記録用・判断には使わない）"""
    try:
        since = datetime.combine(today, datetime.min.time(), JST).astimezone(timezone.utc)
        r = requests.get(f"https://api.github.com/repos/{REPO}/actions/workflows/{WF}/runs",
                         params={"per_page": 30, "created": ">=" + since.strftime("%Y-%m-%dT%H:%M:%SZ"), "event": "schedule"},
                         headers={"Accept": "application/vnd.github+json"}, timeout=30)
        runs = r.json().get("workflow_runs", [])
        times = sorted((datetime.fromisoformat(x["created_at"].replace("Z", "+00:00")).astimezone(JST)).strftime("%H:%M") for x in runs)
        return f"GHA定時実行 今日 {len(runs)}/10 回（到着: {' '.join(times) or 'まだ0回'}）"
    except Exception as e:
        return f"GHA確認失敗: {e}"


# ── 本体 ──
log("=== 占い 朝の見張り番 開始 ===", url)
wp_ok, th_ok, ig_ok, st = status_line()
gha = gha_today_summary()
log(st, "|", gha)

if wp_ok and th_ok and ig_ok:
    gmail(f"✅占い正常 {today.month}/{today.day}", f"今朝の占いはWP・Threads・Instagramとも確認できました。\n{url}\n{gha}")
    sys.exit(0)

# 欠けあり → GHA を即時起動
mode = "sns-only" if wp_ok else "publish"
log(f"欠けを検知 → GitHub Actions を即時起動 (mode={mode})")
ok, info = gha_dispatch(mode)
log("dispatch:", ok, info)
gmail(f"⏳占い 欠けを検知→復旧中 {today.month}/{today.day}",
      f"06:05時点: {st}\n{gha}\n\nGitHub Actions を即時起動しました（mode={mode} / 結果: {info}）。\n"
      f"最大25分 待って確認し、結果をもう1通送ります。\n{url}")

deadline = time.time() + 25 * 60
while ok and time.time() < deadline:
    time.sleep(60)
    wp_ok, th_ok, ig_ok, st = status_line()
    log("待機中:", st)
    if wp_ok and th_ok and ig_ok:
        gmail(f"🔧占い自動復旧 成功（GHA即時起動） {today.month}/{today.day}", f"{st}\n{url}\n{gha}\n\n※Xは手動予約のまま")
        sys.exit(0)

# ── 最後の手段：ローカル復旧（従来どおり） ──
if wp_ok and ig_ok and not th_ok:
    gmail(f"⚠占い Threadsだけ未確認 {today.month}/{today.day}",
          "WPとInstagramは出ていますが、Threadsに今日の占いが見当たりません。\n二重投稿を避けるため自動復旧はしていません。必要ならThreadsだけ手動で投稿してください。\n" + url)
    sys.exit(0)

log("GHA即時起動で復旧できず → ローカル復旧（main.py --sns-only）")
r = subprocess.run([sys.executable, "-u", "main.py", "--date", str(today), "--sns-only"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
out = (r.stdout or "") + (r.stderr or "")
try:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(out[-6000:] + "\n")
except Exception:
    pass
statuses = dict(re.findall(r'"(threads|instagram|instagram_reel)"\s*:\s*\{\s*"status"\s*:\s*"([^"]+)"', out))
wp_after = check_wp()
body = [f"GHA即時起動で復旧できなかったため、ローカルで復旧を実行しました（bridgeが無い場合 Claude API 約6円・包括承認済み）。", "",
        f"検知: {st}", f"{gha}", "", "復旧結果:", f"  WP: {'OK' if wp_after else 'NG'} {url}"]
for k in ("threads", "instagram", "instagram_reel"):
    body.append(f"  {k}: {statuses.get(k, '不明')}")
body += ["", "※Xは手動予約のまま（自動投稿対象外）", "", "ログ末尾:", out[-1200:]]
ok_all = wp_after and all(statuses.get(k) == "ok" for k in ("threads", "instagram", "instagram_reel"))
gmail(("🔧占い自動復旧 成功（ローカル）" if ok_all else "🚨占い自動復旧 失敗あり・要確認") + f" {today.month}/{today.day}", "\n".join(body))
