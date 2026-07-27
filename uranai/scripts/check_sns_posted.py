"""SNS投稿 実在チェッカー（読み取り専用・投稿は一切しない）

「GitHub Actions のログは status=ok で post_id も返っているのに、
  アカウントを見ると投稿が無い」を切り分けるための診断ツール。

API が ok を返したのに実物が無い場合、原因はだいたい次のどれか：
  (a) 投稿先が想定と違うアカウント（トークンが別のIGアカウントに紐づいた）
  (b) Meta 側で削除・非公開化された（スパム判定など）
  (c) media_publish は通ったが処理が完了していない（Reelsの処理待ち）
本スクリプトは (a)(b)(c) を区別できるだけの情報を出力する。

【出力内容】
  1. META トークンの正体（app_id / 有効期限 / スコープ / 紐づくFBユーザー）
  2. トークンから到達できる FBページと IGビジネスアカウントの一覧
     → ここに @toyokawaguide が居ない／別IDなら原因は (a)
  3. 投稿先として使われている IG アカウントの素性（username / media_count）
  4. その IG アカウントの最新メディア一覧（JST表示・permalink付き）
     → 対象日の投稿が並んでいなければ原因は (b)
  5. 指定した post_id が実在するかの直接照会
     → 「取得できない」なら削除済み、「取得できるが一覧に無い」なら (c)
  6. Threads も同様（本人確認 → 最新投稿一覧 → post_id 直接照会）

【使い方】
  python check_sns_posted.py
  python check_sns_posted.py --date 2026-07-27
  python check_sns_posted.py --ig-post-id 18118271731894297 --ig-post-id 18097497725338184 \
                             --threads-post-id 18096589946204737

【環境変数】
  META_ACCESS_TOKEN（必須） / INSTAGRAM_ACCOUNT_ID（任意・未設定ならデフォルトID）
  THREADS_ACCESS_TOKEN / THREADS_USER_ID（任意・未設定ならThreads章はスキップ）

投稿系のAPIは呼ばないので、何度実行しても二重投稿は起きない。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

GRAPH_API = "https://graph.facebook.com/v19.0"
THREADS_API = "https://graph.threads.net/v1.0"
DEFAULT_IG_ACCOUNT_ID = "17841467629335560"  # post_instagram_uranai.py と同じ既定値

JST = timezone(timedelta(hours=9))
TIMEOUT = 30


def hr(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def to_jst(iso_ts: str | None) -> str:
    """Graph API の timestamp（+0000）を JST 表記に変換"""
    if not iso_ts:
        return "-"
    try:
        return (datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%S%z")
                .astimezone(JST).strftime("%Y-%m-%d %H:%M JST"))
    except ValueError:
        return iso_ts


def get(url: str, params: dict) -> tuple[dict | None, str | None]:
    """GET して (json, エラー文字列) を返す。トークンは絶対に出力しない。"""
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
    except Exception as e:
        return None, f"リクエスト失敗: {type(e).__name__}: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:300]}"
    return r.json(), None


def check_meta_token(token: str) -> None:
    hr("1. META アクセストークンの正体")

    me, err = get(f"{GRAPH_API}/me", {"fields": "id,name", "access_token": token})
    if err:
        print(f"  ❌ /me 取得失敗 → {err}")
        print("     ※ トークン失効の可能性。token_health ワークフローも確認のこと")
    else:
        print(f"  紐づくFBユーザー: {me.get('name')} (id={me.get('id')})")

    dbg, err = get(f"{GRAPH_API}/debug_token",
                   {"input_token": token, "access_token": token})
    if err:
        print(f"  ⚠ debug_token 取得失敗 → {err}")
        return
    d = (dbg or {}).get("data", {})
    exp = d.get("expires_at")
    exp_txt = "無期限" if exp in (0, None) else \
        datetime.fromtimestamp(exp, JST).strftime("%Y-%m-%d %H:%M JST")
    print(f"  app_id   : {d.get('app_id')}")
    print(f"  type     : {d.get('type')}")
    print(f"  is_valid : {d.get('is_valid')}")
    print(f"  有効期限 : {exp_txt}")
    print(f"  scopes   : {', '.join(d.get('scopes') or []) or '-'}")


def check_reachable_accounts(token: str, configured_ig_id: str) -> None:
    hr("2. このトークンから到達できる FBページ / IGアカウント")
    print("  ※ ここに実際の運用アカウントが居ない、またはIDが違えば")
    print("     『投稿は成功しているが別アカウントに入っている』が確定する")
    print()

    data, err = get(f"{GRAPH_API}/me/accounts", {
        "fields": "id,name,instagram_business_account{id,username,name}",
        "limit": 50,
        "access_token": token,
    })
    if err:
        print(f"  ⚠ /me/accounts 取得失敗 → {err}")
        print("     （ユーザートークンでない場合は取得できないことがある）")
        return

    pages = (data or {}).get("data", [])
    if not pages:
        print("  ⚠ 到達できるFBページが0件")
        return

    for p in pages:
        ig = p.get("instagram_business_account") or {}
        mark = ""
        if ig.get("id") == configured_ig_id:
            mark = "  ← ★投稿先として使用中"
        print(f"  FBページ: {p.get('name')} (id={p.get('id')})")
        if ig:
            print(f"    └ IG: @{ig.get('username')} ({ig.get('name')}) id={ig.get('id')}{mark}")
        else:
            print("    └ IG: 紐づけなし")

    known = {(p.get("instagram_business_account") or {}).get("id") for p in pages}
    if configured_ig_id not in known:
        print()
        print(f"  🚨 投稿先IG ID {configured_ig_id} が上の一覧に存在しない。")
        print("     投稿先アカウントの取り違え、またはページ連携が外れた可能性が高い。")


def check_instagram(token: str, ig_id: str, target: date, limit: int,
                    post_ids: list[str]) -> int:
    """Returns: 対象日に実在した IG メディア件数（-1 = 確認できなかった）"""
    hr(f"3. 投稿先 Instagram アカウント (id={ig_id})")

    prof, err = get(f"{GRAPH_API}/{ig_id}", {
        "fields": "id,username,name,media_count,followers_count",
        "access_token": token,
    })
    if err:
        print(f"  ❌ アカウント情報取得失敗 → {err}")
        return -1
    print(f"  @{prof.get('username')} ({prof.get('name')})")
    print(f"  メディア総数: {prof.get('media_count')} / フォロワー: {prof.get('followers_count')}")

    hr(f"4. 最新メディア {limit} 件（対象日: {target} JST）")
    media, err = get(f"{GRAPH_API}/{ig_id}/media", {
        "fields": "id,media_type,timestamp,permalink,caption",
        "limit": limit,
        "access_token": token,
    })
    if err:
        print(f"  ❌ メディア一覧取得失敗 → {err}")
        return -1

    items = (media or {}).get("data", [])
    if not items:
        print("  ⚠ メディアが1件も返ってこない（アカウントが空、または権限不足）")
        return 0

    hits = 0
    for m in items:
        ts = m.get("timestamp")
        jst = to_jst(ts)
        on_target = jst.startswith(target.strftime("%Y-%m-%d"))
        if on_target:
            hits += 1
        head = (m.get("caption") or "").replace("\n", " ")[:40]
        print(f"  {'▶' if on_target else ' '} {jst}  {m.get('media_type'):<10} "
              f"id={m.get('id')}")
        print(f"      {m.get('permalink')}")
        if head:
            print(f"      {head}…")

    print()
    if hits:
        print(f"  ✅ 対象日 {target} の投稿が {hits} 件 実在する")
    else:
        print(f"  🚨 対象日 {target} の投稿が最新{len(items)}件の中に1件も無い")
        print("     → API が ok を返していたなら、公開後に削除／非公開化された疑い")

    if post_ids:
        hr("5. 指定 post_id の直接照会（Instagram）")
        for pid in post_ids:
            one, err = get(f"{GRAPH_API}/{pid}", {
                "fields": "id,media_type,timestamp,permalink,username",
                "access_token": token,
            })
            if err:
                print(f"  ❌ {pid} → 取得できない（削除済みの可能性）")
                print(f"     {err}")
            else:
                print(f"  ✅ {pid} → 実在 @{one.get('username')} "
                      f"{to_jst(one.get('timestamp'))} {one.get('media_type')}")
                print(f"     {one.get('permalink')}")

    return hits


def check_threads(token: str, user_id: str, target: date, limit: int,
                  post_ids: list[str]) -> int:
    """Returns: 対象日に実在した Threads 投稿件数（-1 = 確認できなかった）"""
    hr("6. Threads")

    me, err = get(f"{THREADS_API}/me", {"fields": "id,username,name", "access_token": token})
    if err:
        print(f"  ❌ 本人情報取得失敗 → {err}")
        print("     ※ THREADS_ACCESS_TOKEN 失効の可能性")
        return -1
    print(f"  @{me.get('username')} ({me.get('name')}) id={me.get('id')}")
    if str(me.get("id")) != str(user_id):
        print(f"  🚨 THREADS_USER_ID({user_id}) とトークンの本人ID({me.get('id')})が不一致")

    posts, err = get(f"{THREADS_API}/{user_id}/threads", {
        "fields": "id,text,timestamp,permalink,media_type",
        "limit": limit,
        "access_token": token,
    })
    if err:
        print(f"  ❌ 投稿一覧取得失敗 → {err}")
        return -1

    items = (posts or {}).get("data", [])
    print(f"\n  最新 {len(items)} 件（対象日: {target} JST）")
    hits = 0
    for p in items:
        jst = to_jst(p.get("timestamp"))
        on_target = jst.startswith(target.strftime("%Y-%m-%d"))
        if on_target:
            hits += 1
        head = (p.get("text") or "").replace("\n", " ")[:40]
        print(f"  {'▶' if on_target else ' '} {jst}  id={p.get('id')}")
        print(f"      {p.get('permalink')}")
        if head:
            print(f"      {head}…")

    print()
    if hits:
        print(f"  ✅ 対象日 {target} の Threads 投稿が {hits} 件 実在する")
    else:
        print(f"  🚨 対象日 {target} の Threads 投稿が最新{len(items)}件の中に1件も無い")

    if post_ids:
        print("\n  --- 指定 post_id の直接照会（Threads） ---")
        for pid in post_ids:
            one, err = get(f"{THREADS_API}/{pid}",
                           {"fields": "id,timestamp,permalink", "access_token": token})
            if err:
                print(f"  ❌ {pid} → 取得できない（削除済みの可能性）")
                print(f"     {err}")
            else:
                print(f"  ✅ {pid} → 実在 {to_jst(one.get('timestamp'))}")
                print(f"     {one.get('permalink')}")

    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="SNS投稿 実在チェック（読み取り専用）")
    ap.add_argument("--date", help="対象日 YYYY-MM-DD（空ならJSTの今日）")
    ap.add_argument("--limit", type=int, default=25, help="取得する最新件数（既定25）")
    ap.add_argument("--ig-post-id", action="append", default=[],
                    help="実在確認したい IG post_id（複数指定可）")
    ap.add_argument("--threads-post-id", action="append", default=[],
                    help="実在確認したい Threads post_id（複数指定可）")
    ap.add_argument("--abort-if-posted", action="store_true",
                    help="対象日の投稿が1件でも実在したら exit 9。"
                         "強制再投稿の前段に置いて二重投稿を止めるためのガード")
    args = ap.parse_args()

    target = (datetime.strptime(args.date, "%Y-%m-%d").date() if args.date
              else datetime.now(JST).date())

    print("SNS投稿 実在チェック（読み取り専用・投稿は行いません）")
    print(f"対象日: {target} / 実行時刻: {datetime.now(JST):%Y-%m-%d %H:%M JST}")

    ig_hits = th_hits = -1

    meta_token = os.getenv("META_ACCESS_TOKEN")
    if not meta_token:
        print("\n❌ META_ACCESS_TOKEN 未設定のため Instagram の確認をスキップ")
    else:
        ig_id = (os.getenv("INSTAGRAM_ACCOUNT_ID")
                 or os.getenv("IG_USER_ID")
                 or DEFAULT_IG_ACCOUNT_ID)
        if not os.getenv("INSTAGRAM_ACCOUNT_ID"):
            print(f"\n⚠ INSTAGRAM_ACCOUNT_ID が未設定 → 既定値 {DEFAULT_IG_ACCOUNT_ID} を使用中")
            print("  （実際の投稿処理も同じ既定値にフォールバックしている）")
        check_meta_token(meta_token)
        check_reachable_accounts(meta_token, ig_id)
        ig_hits = check_instagram(meta_token, ig_id, target, args.limit, args.ig_post_id)

    th_token = os.getenv("THREADS_ACCESS_TOKEN")
    th_user = os.getenv("THREADS_USER_ID")
    if not th_token or not th_user:
        print("\n⚠ THREADS_ACCESS_TOKEN / THREADS_USER_ID 未設定のため Threads 確認をスキップ")
    else:
        th_hits = check_threads(th_token, th_user, target, args.limit, args.threads_post_id)

    hr("チェック完了")

    if args.abort_if_posted:
        # 強制再投稿の前段ガード。「確認できなかった(-1)」も通さない：
        # 実在するのに確認できないまま投稿すると二重投稿になるため、安全側に倒す。
        if ig_hits > 0 or th_hits > 0:
            print(f"🛑 対象日 {target} の投稿が既に実在する（IG {ig_hits}件 / Threads {th_hits}件）")
            print("   二重投稿になるため強制再投稿を中止します。")
            return 9
        if ig_hits < 0 or th_hits < 0:
            print(f"🛑 実在確認ができなかった（IG {ig_hits} / Threads {th_hits}）")
            print("   投稿済みか判断できないため、安全側に倒して強制再投稿を中止します。")
            return 9
        print(f"✅ 対象日 {target} の投稿は IG・Threads とも実在しない → 再投稿して問題なし")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
