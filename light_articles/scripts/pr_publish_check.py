# -*- coding: utf-8 -*-
"""
pr_publish_check.py — さくっとPRが出ているか、毎朝9:30に確かめて社長へメールする（2026-10-28 社長指示）

社長「9時半の時点で、さくっとPRの記事、インスタ等が出てるかどうか確認して、メールを送るようにしてほしい」
→ 公開は9:00（9:10・9:20・12:00はやり直し）。社長はXを10:00に手動予約するので、その前に結果を知らせる。

確かめるもの（公開希望日=今日 の行だけ。取消・統合・サンプルは見ない）
  1) ホームページ … slug=prNNN の記事が公開されているか
  2) Instagram   … 今日の投稿に店名が入ったフィード投稿・リールがあるか
  3) Threads     … 今日の投稿に記事のアドレス（または店名）が入っているか
  4) PRキューの状態 … 投稿済 になっているか

全部そろっていればすぐ「OK」のメール。足りなければ5分おきに見直し、最大 --wait 分待ってから結果をメールする
（GHAの開始が遅れて、配信がまだ途中のことがあるため）。今日のPRが無い日はメールしない。

使い方
python pr_publish_check.py              # 本番（メールする）
python pr_publish_check.py --dry        # メールせず結果だけ表示
python pr_publish_check.py --date 2026-10-27 --dry
"""
from __future__ import annotations

import argparse
import os
import smtplib
import sys
import time as _time
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sheets_client import read_all_rows
from publish_light_article import parse_publish_date
from wp_client import find_published_post_by_slug
from pr_builder import build_pr_x_caption

PR_SHEET = "PRキュー"
PR_SPREADSHEET_ID = "1grn6UiQf8HqxcRSB3tMiZBLWGQCT1H7fCUNqv5CBA7A"
SKIP_STATES = ("取消", "統合", "サンプル")
GRAPH_API = "https://graph.facebook.com/v19.0"
THREADS_API = "https://graph.threads.net/v1.0"
JST = timezone(timedelta(hours=9))


def log(m: str, i: int = 0):
    print("  " * i + m, flush=True)


def _norm(s: str) -> str:
    return "".join((s or "").split()).lower()


def todays_rows(target: date) -> list[dict]:
    out = []
    for r in read_all_rows(sheet=PR_SHEET, spreadsheet_id=PR_SPREADSHEET_ID):
        st = (r.get("状態") or "").strip()
        if not r.get("ID") or any(s in st for s in SKIP_STATES):
            continue
        if parse_publish_date((r.get("公開希望日") or "").strip() or "") == target:
            out.append(r)
    return out


def ig_today(target: date) -> list[dict]:
    token = os.environ.get("META_ACCESS_TOKEN")
    from sns_clients import DEFAULT_IG_ACCOUNT_ID
    ig_id = os.environ.get("INSTAGRAM_ACCOUNT_ID") or os.environ.get("IG_USER_ID") or DEFAULT_IG_ACCOUNT_ID
    if not (token and ig_id):
        raise RuntimeError("META_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID が未設定")
    r = requests.get(f"{GRAPH_API}/{ig_id}/media", timeout=30, params={
        "fields": "caption,timestamp,permalink,media_type,media_product_type", "limit": 25,
        "access_token": token})
    r.raise_for_status()
    return [m for m in r.json().get("data", [])
            if datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")).astimezone(JST).date() == target]


def threads_today(target: date) -> list[dict]:
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    uid = os.environ.get("THREADS_USER_ID") or os.environ.get("THREADS_ACCOUNT_ID")
    if not (token and uid):
        raise RuntimeError("THREADS_ACCESS_TOKEN / THREADS_USER_ID が未設定")
    r = requests.get(f"{THREADS_API}/{uid}/threads", timeout=30, params={
        "fields": "text,timestamp,permalink", "limit": 25, "access_token": token})
    r.raise_for_status()
    return [m for m in r.json().get("data", [])
            if datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")).astimezone(JST).date() == target]


def check_one(row: dict, target: date) -> dict:
    pid = row["ID"].strip()
    shop = (row.get("店名") or "").strip()
    slug = pid.lower()
    res = {"ID": pid, "店名": shop, "状態": (row.get("状態") or "").strip()}

    try:
        wp = find_published_post_by_slug(slug)
        res["wp"] = wp["link"] if wp else None
    except Exception as e:
        res["wp"] = None
        res["wp_err"] = str(e)[:150]

    key = _norm(shop)
    try:
        media = [m for m in ig_today(target) if key and key in _norm(m.get("caption", ""))]
        res["ig_feed"] = next((m["permalink"] for m in media if m.get("media_product_type") != "REELS"), None)
        res["ig_reel"] = next((m["permalink"] for m in media if m.get("media_product_type") == "REELS"), None)
    except Exception as e:
        res["ig_feed"] = res["ig_reel"] = None
        res["ig_err"] = str(e)[:150]

    try:
        hits = [m for m in threads_today(target)
                if f"/{slug}/" in (m.get("text") or "") or (key and key in _norm(m.get("text", "")))]
        res["threads"] = hits[0]["permalink"] if hits else None
    except Exception as e:
        res["threads"] = None
        res["threads_err"] = str(e)[:150]

    res["ok"] = bool(res["wp"] and res["ig_feed"] and res["ig_reel"] and res["threads"] and res["状態"] == "投稿済")
    return res


def mark(v) -> str:
    return "✅ 出ています" if v else "❌ 見つかりません"


def build_mail(results: list[dict], rows: list[dict], target: date) -> tuple[str, str]:
    all_ok = all(r["ok"] for r in results)
    names = "・".join(f"{r['ID']} {r['店名']}" for r in results)
    subject = (f"【さくっとPR】{target.month}/{target.day} 9:30確認：{'すべてOK' if all_ok else '⚠ 出ていないものがあります'}（{names}）")
    lines = [f"{target.month}月{target.day}日のさくっとPRを確認しました（{datetime.now(JST):%H:%M} 時点）。", ""]
    by_id = {(r.get('ID') or '').strip(): r for r in rows}
    for r in results:
        lines += [f"■ {r['ID']} {r['店名']}",
                  f"・ホームページ：{mark(r['wp'])}" + (f"\n　{r['wp']}" if r['wp'] else ""),
                  f"・Instagram 投稿：{mark(r['ig_feed'])}" + (f"\n　{r['ig_feed']}" if r['ig_feed'] else ""),
                  f"・Instagram リール：{mark(r['ig_reel'])}" + (f"\n　{r['ig_reel']}" if r['ig_reel'] else ""),
                  f"・Threads：{mark(r['threads'])}" + (f"\n　{r['threads']}" if r['threads'] else ""),
                  f"・PRキューの状態：{r['状態'] or '空'}" + ("" if r['状態'] == "投稿済" else "（投稿済になっていません）")]
        for k, label in (("wp_err", "ホームページ"), ("ig_err", "Instagram"), ("threads_err", "Threads")):
            if r.get(k):
                lines.append(f"　※{label}の確認中にエラー：{r[k]}")
        lines.append("")
        if r["wp"]:
            lines += ["▼ Xの投稿文（10:00の予約はこのままで大丈夫です）",
                      build_pr_x_caption(by_id[r["ID"]], r["wp"]), ""]
        else:
            lines += ["⚠ 記事がまだ出ていないので、Xの10:00予約は止めておいてください（リンク先が開けません）。", ""]
    if not all_ok:
        lines += ["出ていないものがあるときは、Claude に「さくっとPR出てない」と伝えてください。",
                  "（手動でやり直すと、出ているSNSまで二重に投稿されることがあるので、どれが出ていないかを見てから直します）", ""]
    lines.append("— さくっとPR 自動確認")
    return subject, "\n".join(lines)


def send_mail(subject: str, body: str):
    user = os.environ["GMAIL_USER"]
    pw = os.environ["GMAIL_APP_PASSWORD"]
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = user          # 社長あて（申込者には送らない）
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="メールせず結果だけ表示")
    ap.add_argument("--date", help="確認する日 YYYY-MM-DD（省略=今日）")
    ap.add_argument("--wait", type=int, default=25, help="出ていないとき最大何分待つか（5分おきに見直す）")
    args = ap.parse_args()
    target = parse_publish_date(args.date) if args.date else datetime.now(JST).date()

    rows = todays_rows(target)
    if not rows:
        log(f"📭 {target} のさくっとPRはありません（メールしません）")
        return
    deadline = _time.time() + args.wait * 60
    while True:
        results = [check_one(r, target) for r in rows]
        for r in results:
            log(f"{r['ID']} {r['店名']}: wp={bool(r['wp'])} ig={bool(r['ig_feed'])} reel={bool(r['ig_reel'])} "
                f"threads={bool(r['threads'])} 状態={r['状態']} → {'OK' if r['ok'] else '未'}")
        if all(r["ok"] for r in results) or _time.time() + 300 > deadline:
            break
        log("…出ていないものがあるので5分後に見直します")
        _time.sleep(300)
        rows = todays_rows(target)   # 状態の変化（投稿済）も読み直す

    subject, body = build_mail(results, rows, target)
    log(subject)
    if args.dry:
        print(body)
        return
    send_mail(subject, body)
    log("📧 社長へメールしました")


if __name__ == "__main__":
    main()
