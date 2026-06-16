"""
占い配信オーケストレーター（メインエントリポイント）
====================================================

毎朝6時 JST に GitHub Actions cron から起動される。

【実行フロー】
1. 今日の日付・曜日を確定
2. ラッキースポット選定（select_lucky_spot.py）
3. 文脈ヒント生成（context_hints.py）
4. 占い記事生成（generate_text.py：テンプレ＋プレースホルダ方式）
5. 画像生成（generate_image.py：曜日別レイアウト・WP+IG）
6. WP 投稿（post_wordpress.py）※--publish 時のみ。それ以外は下書き保存
7. SNS 投稿・配信ログ記録 ※Phase 3 で実装

【使い方】
  # dry-run（ダミーデータ・¥0・WP下書き更新あり）
  python main.py --date 2026-05-11 --dry

  # 実API（Anthropic API課金あり・WP下書きに保存）
  python main.py --date 2026-05-11

  # 実API＋本番公開（Phase 3 で実装予定）
  python main.py --date 2026-05-11 --publish

【現状】
- Phase 2 完了：記事生成＋画像生成＋WP下書き保存
- Phase 3 未実装：本番公開・SNS投稿・配信ログ記録
"""
from __future__ import annotations
import os
import sys
import json
import argparse
import base64
import html
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
RAW_DIR = OUTPUT_DIR / "raw"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

# .env 読み込み（claude/.env を優先・占い/.env もフォールバック）
from dotenv import load_dotenv
for env_path in [
    ROOT.parent / "claude" / ".env",
    ROOT / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path, override=True)
        break

# ローカルモジュール
import config
from select_lucky_spot import select_lucky_spot
from context_hints import build_context_hints, get_planetary_ruler, get_moon_phase
from notify_failure import notify_uranai_failure
from generate_text import generate_uranai_article_template
from generate_image import generate_image

JST = timezone(timedelta(hours=9))
WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

# WP下書き付け先（dry-run/通常時に使用）
DRAFT_POST_IDS = {
    "mon": 30318, "tue": 30370, "wed": 30372, "thu": 30374,
    "fri": 30376, "sat": 30378, "sun": 30380,
}


def get_today_jst() -> date:
    return datetime.now(JST).date()


def build_extra(weekday_key: str, target_date: date) -> dict | None:
    """金/土/日 用の追加入力を構築"""
    if weekday_key == "fri":
        try:
            from load_groups import load_birthyear_group, get_week_number
            week = get_week_number(target_date, weekday_kind="fri")
            rows = load_birthyear_group(week)
            years = [r.get("生まれ年") for r in rows if r.get("生まれ年")]
            return {"years": years} if years else None
        except Exception as e:
            print(f"  [warn] load_birthyear_group failed: {e}")
            return None
    if weekday_key == "sat":
        try:
            from load_groups import load_town_group, get_week_number
            week = get_week_number(target_date, weekday_kind="sat")
            rows = load_town_group(week)
            towns = [r.get("町名") for r in rows if r.get("町名")]
            return {"towns": towns} if towns else None
        except Exception as e:
            print(f"  [warn] load_town_group failed: {e}")
            return None
    if weekday_key == "sun":
        # 過去6日（月〜土）のスポットを weekly_logs として渡す
        weekly_logs = []
        for i in range(6, 0, -1):
            past_d = target_date - timedelta(days=i)
            try:
                past_spot = select_lucky_spot(past_d)
                weekly_logs.append({
                    "date": past_d.isoformat(),
                    "weekday": WEEKDAY_JP[past_d.weekday()],
                    "lucky_spot": past_spot.name,
                })
            except Exception:
                pass
        return {"weekly_logs": weekly_logs} if weekly_logs else None
    return None


def fix_sunday_spots_week(data: dict, target_date: date) -> dict:
    """日曜の data に spots_week が無ければ補完"""
    if data.get("spots_week"):
        return data
    spots_week = {}
    for i, key in enumerate(["mon", "tue", "wed", "thu", "fri", "sat"]):
        past_d = target_date - timedelta(days=6 - i)
        try:
            spots_week[key] = select_lucky_spot(past_d).name
        except Exception:
            spots_week[key] = "-"
    data["spots_week"] = spots_week
    return data


def check_already_published(target_date: date) -> bool:
    """今日の占い記事が既にWPで公開済みか判定（保険cron冪等チェック用）

    今日の post_id が status=publish かつ slug=uranai-YYYYMMDD なら True。
    06:00 が成功済みの時に 09:00 保険cron が二重投稿しないためのガード。
    判定不能（認証無し・API失敗等）は False を返し、配信を試みる側に倒す。
    """
    wk = WEEKDAY_KEYS[target_date.weekday()]
    post_id = DRAFT_POST_IDS.get(wk)
    if not post_id:
        return False
    WP_URL = os.getenv("WP_URL")
    if not (WP_URL and os.getenv("WP_USERNAME") and os.getenv("WP_PASSWORD")):
        return False
    creds = f"{os.getenv('WP_USERNAME')}:{os.getenv('WP_PASSWORD')}"
    token = base64.b64encode(creds.encode()).decode()
    try:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
            params={"context": "edit"},
            headers={"Authorization": f"Basic {token}"},
            timeout=30,
        )
        if r.status_code != 200:
            return False
        j = r.json()
        expect_slug = f"uranai-{target_date.strftime('%Y%m%d')}"
        return j.get("status") == "publish" and j.get("slug") == expect_slug
    except Exception:
        return False


def update_wp_post(post_id: int, title: str, content: str,
                    eyecatch_path: Path | None = None,
                    *, publish: bool = False,
                    ig_eyecatch_path: Path | None = None,
                    reel_video_path: Path | None = None,
                    slug: str | None = None) -> dict:
    """WP の指定 post を更新（status=draft or publish）

    Returns: {"preview_url"|"link", "wp_image_url", "ig_image_url", "reel_video_url"}
    """
    WP_URL = os.getenv("WP_URL")
    if not WP_URL:
        return {"error": "WP_URL not set"}
    creds = f"{os.getenv('WP_USERNAME')}:{os.getenv('WP_PASSWORD')}"
    token = base64.b64encode(creds.encode()).decode()
    headers_post = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    headers_up = {"Authorization": f"Basic {token}"}

    def _content_type(name: str) -> str:
        n = name.lower()
        if n.endswith(".mp4"):
            return "video/mp4"
        if n.endswith(".jpg") or n.endswith(".jpeg"):
            return "image/jpeg"
        if n.endswith(".gif"):
            return "image/gif"
        return "image/png"

    def _upload_media(p: Path) -> tuple[int | None, str | None]:
        with open(p, "rb") as f:
            uph = {**headers_up,
                   "Content-Disposition": f'attachment; filename="{p.name}"',
                   "Content-Type": _content_type(p.name)}
            r = requests.post(f"{WP_URL}/wp-json/wp/v2/media", headers=uph, data=f.read(), timeout=120)
        if r.status_code in (200, 201):
            j = r.json()
            return j["id"], j.get("source_url")
        return None, None

    wp_media_id = None
    wp_image_url = None
    if eyecatch_path and eyecatch_path.exists():
        wp_media_id, wp_image_url = _upload_media(eyecatch_path)

    ig_image_url = None
    if ig_eyecatch_path and ig_eyecatch_path.exists():
        _, ig_image_url = _upload_media(ig_eyecatch_path)

    reel_video_url = None
    if reel_video_path and reel_video_path.exists():
        _, reel_video_url = _upload_media(reel_video_path)

    # XSERVER WAF対策：content + status を1回で送ると 403 になることがあるため、
    # ①content・タイトル・アイキャッチを draft で更新 → ②publish なら status だけ別リクエスト で切替
    payload1 = {"title": title, "content": content, "status": "draft"}
    if slug:
        payload1["slug"] = slug
        # slug=uranai-YYYYMMDD から公開日を配信日に設定。
        # これが無いと draft作成日のまま公開され URL(/YYYY/MM/DD/)がズレ
        # X予約投稿リンク404＋トップ最新非表示になる（2026-05-19 障害の真因）
        #
        # 2026-05-25 修正：時刻部分を「現在時刻」に変更（旧: 06:00 固定）。
        # 旧仕様だと cron 5:00 発火時に date=06:00（未来）となり、WPが
        # status=publish 送っても future に強制→ WP_CRON 待ちになる。
        # 06:00 前後にサイトアクセス無いと WP_CRON が動かず future 残留→
        # 「予約投稿失敗」マーク。現在時刻にすれば必ず過去時刻＝即 publish。
        ymd = slug.split("uranai-")[-1]
        if len(ymd) == 8 and ymd.isdigit():
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            _jst = _tz(_td(hours=9))
            _now = _dt.now(_jst)
            payload1["date"] = (
                f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                f"T{_now.strftime('%H:%M:%S')}"
            )
    if wp_media_id:
        payload1["featured_media"] = wp_media_id
    body1 = json.dumps(payload1, ensure_ascii=False).encode("utf-8")
    r1 = requests.post(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}", headers=headers_post, data=body1, timeout=30)
    if r1.status_code != 200:
        return {"error": f"WP draft update failed: {r1.status_code} {r1.text[:200]}"}

    if publish:
        body2 = json.dumps({"status": "publish"}, ensure_ascii=False).encode("utf-8")
        r2 = requests.post(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}", headers=headers_post, data=body2, timeout=30)
        if r2.status_code != 200:
            return {"error": f"WP publish failed: {r2.status_code} {r2.text[:200]}"}
        j = r2.json()
    else:
        j = r1.json()

    return {
        "preview_url": f"{WP_URL}/?p={post_id}&preview=true",
        "link": j.get("link") or f"{WP_URL}/?p={post_id}",
        "wp_image_url": wp_image_url,
        "ig_image_url": ig_image_url,
        "reel_video_url": reel_video_url,
        "status": j.get("status"),
    }


def update_homepage_uranai_card(post_url: str, title: str, image_url: str | None,
                                 target_date: date, *, page_id: int = 25,
                                 dry: bool = False) -> dict:
    """トップ固定ページ(ID=25)の「占いコーナー」カードを当日の記事に更新する。

    占いカテゴリ(711)はSWELLの「投稿リスト除外」設定のため動的ブロックでは表示
    できない（"記事が見つかりませんでした"になる）。そこで .uranai-spot-card
    グループの中身を、当日記事を指す静的カードHTMLで毎日上書きして最新化する。
    ※メイン配信フローを絶対に止めないよう、呼び出し側で try/except する前提。
    """
    WP_URL = os.getenv("WP_URL")
    if not (WP_URL and os.getenv("WP_USERNAME") and os.getenv("WP_PASSWORD")):
        return {"status": "skip", "reason": "no_creds"}
    if not (post_url and image_url and title):
        return {"status": "skip", "reason": "missing_data"}

    creds = f"{os.getenv('WP_USERNAME')}:{os.getenv('WP_PASSWORD')}"
    token = base64.b64encode(creds.encode()).decode()
    auth_header = {"Authorization": f"Basic {token}"}

    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/pages/{page_id}",
        params={"context": "edit", "_fields": "content"},
        headers=auth_header, timeout=30,
    )
    if r.status_code != 200:
        return {"status": "failed", "error": f"fetch {r.status_code}"}
    raw = r.json()["content"]["raw"]

    GROUP_OPEN = '<!-- wp:group {"className":"uranai-spot-card"} -->'
    gstart = raw.find(GROUP_OPEN)
    if gstart < 0:
        return {"status": "skip", "reason": "spot_card_group_not_found"}
    gend = raw.find("<!-- /wp:group -->", gstart)
    if gend < 0:
        return {"status": "skip", "reason": "group_end_not_found"}
    gend_full = gend + len("<!-- /wp:group -->")

    e_url = html.escape(post_url, quote=True)
    e_img = html.escape(image_url, quote=True)
    e_title = html.escape(title)
    date_iso = target_date.strftime("%Y-%m-%d")
    date_jp = f"{target_date.year}年{target_date.month:02d}月{target_date.day:02d}日"

    new_group = (
        GROUP_OPEN + "\n"
        '<div class="wp-block-group uranai-spot-card">\n'
        "<!-- wp:html -->\n"
        '<div class="uranai-feature-wrap">\n'
        '<ul class="p-postList -type-card -pc-col1 -sp-col1">\n'
        '<li class="p-postList__item">\n'
        f'<a href="{e_url}" class="p-postList__link">\n'
        '<div class="p-postList__thumb c-postThumb">\n'
        '<figure class="c-postThumb__figure">\n'
        f'<img src="{e_img}" alt="" class="c-postThumb__img u-obf-cover" width="1024" height="576" loading="lazy">\n'
        "</figure>\n</div>\n"
        '<div class="p-postList__body">\n'
        f'<h2 class="p-postList__title">{e_title}</h2>\n'
        '<div class="p-postList__meta">\n'
        '<div class="p-postList__times c-postTimes u-thin">\n'
        f'<time class="c-postTimes__posted icon-posted" datetime="{date_iso}" aria-label="公開日">{date_jp}</time>\n'
        "</div>\n"
        '<span class="p-postList__cat u-thin icon-folder">占い</span>\n'
        "</div>\n</div>\n</a>\n</li>\n</ul>\n</div>\n"
        "<style>\n"
        ".uranai-feature-wrap{max-width:800px;margin:0 auto;}\n"
        ".uranai-feature-wrap .p-postList__item{width:100%!important;float:none!important;}\n"
        "</style>\n"
        "<!-- /wp:html -->\n"
        "</div>\n"
        "<!-- /wp:group -->"
    )
    new_raw = raw[:gstart] + new_group + raw[gend_full:]
    if new_raw == raw:
        return {"status": "nochange"}
    if dry:
        return {"status": "dry_ok", "new_len": len(new_raw)}

    headers_post = {**auth_header, "Content-Type": "application/json"}
    body = json.dumps({"content": new_raw}, ensure_ascii=False).encode("utf-8")
    resp = requests.post(f"{WP_URL}/wp-json/wp/v2/pages/{page_id}",
                         headers=headers_post, data=body, timeout=30)
    if resp.status_code != 200:
        return {"status": "failed", "error": f"{resp.status_code} {resp.text[:150]}"}
    return {"status": "ok", "post_url": post_url}


def post_all_sns(weekday_key, data, spot, target_date, post_url, ig_image_url, reel_video):
    """X / Threads / Instagram(Feed+Reels) へ投稿。run_pipeline と run_sns_only 共通。
    ★既投稿マーカー(sns_done_{date}.json) で、リトライ時に成功済みの媒体は再投稿しない
      （= 朝6:00/6:30/7:00/8:00 を何度走らせても二重投稿にならない自動リトライの要）。
      マーカーは GHA キャッシュで各リトライ間に引き継ぐ。"""
    from post_x_uranai import post_x_uranai
    from post_threads_uranai import post_threads_uranai
    from post_instagram_uranai import (post_instagram_uranai,
                                        post_instagram_uranai_reel_resumable)
    done_file = OUTPUT_DIR / f"sns_done_{target_date}.json"
    done = {}
    if done_file.exists():
        try:
            done = json.loads(done_file.read_text(encoding="utf-8"))
            posted = [k for k, v in done.items() if v == "ok"]
            if posted:
                print(f"  ✅ 既投稿マーカー: {posted} は再投稿しません（リトライ二重投稿防止）")
        except Exception:
            done = {}
    def mark(platform):
        done[platform] = "ok"
        try:
            done_file.parent.mkdir(parents=True, exist_ok=True)
            done_file.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    sns_results = {}

    print("  [X]")
    if done.get("x") == "ok":
        print("     [skip] 既投稿済み"); sns_results["x"] = {"status": "already_posted"}
    else:
        x_res = post_x_uranai(weekday_key=weekday_key, data=data, spot=spot,
                              target_date=target_date, post_url=post_url, dry=False)
        print(f"     status={x_res['status']}  url={x_res.get('url')}")
        sns_results["x"] = x_res
        if x_res.get("status") == "ok": mark("x")

    print("  [Threads]")
    if done.get("threads") == "ok":
        print("     [skip] 既投稿済み"); sns_results["threads"] = {"status": "already_posted"}
    else:
        th_res = post_threads_uranai(weekday_key=weekday_key, data=data, spot=spot,
                                     target_date=target_date, post_url=post_url, dry=False)
        print(f"     status={th_res['status']}  post_id={th_res.get('post_id')}")
        sns_results["threads"] = th_res
        if th_res.get("status") == "ok": mark("threads")

    print("  [Instagram Feed]")
    if done.get("instagram") == "ok":
        print("     [skip] 既投稿済み"); sns_results["instagram"] = {"status": "already_posted"}
    elif not ig_image_url:
        print("     [skip] IG画像URL未取得")
        sns_results["instagram"] = {"status": "skipped", "reason": "no_ig_url"}
    else:
        ig_res = post_instagram_uranai(weekday_key=weekday_key, data=data, spot=spot,
                                       target_date=target_date, ig_image_url=ig_image_url, dry=False)
        print(f"     status={ig_res['status']}  post_id={ig_res.get('post_id')}")
        sns_results["instagram"] = ig_res
        if ig_res.get("status") == "ok": mark("instagram")

    print("  [Instagram Reels（Resumable Upload）]")
    if done.get("instagram_reel") == "ok":
        print("     [skip] 既投稿済み"); sns_results["instagram_reel"] = {"status": "already_posted"}
    elif not (reel_video and Path(reel_video).exists()):
        print(f"     [skip] Reel動画ファイル未生成: {reel_video}")
        sns_results["instagram_reel"] = {"status": "skipped", "reason": "no_reel_file"}
    else:
        ig_reel_res = post_instagram_uranai_reel_resumable(
            weekday_key=weekday_key, data=data, spot=spot,
            target_date=target_date, video_path=reel_video, cover_path=None, dry=False)
        print(f"     status={ig_reel_res['status']}  post_id={ig_reel_res.get('post_id')}")
        sns_results["instagram_reel"] = ig_reel_res
        if ig_reel_res.get("status") == "ok": mark("instagram_reel")

    return sns_results


def run_sns_only(target_date: date) -> dict:
    """別ジョブ（6:00）：WP公開ジョブが保存した bridge を読み、SNSのみ投稿する。
    bridge が無ければSNSはスキップ（記事は既に公開済＝Xリンクは生きてる）＋失敗通知。"""
    from types import SimpleNamespace
    weekday_key = WEEKDAY_KEYS[target_date.weekday()]
    weekday_jp = WEEKDAY_JP[target_date.weekday()]
    print(f"\n{'='*60}\n占い SNS投稿のみ  {target_date} ({weekday_jp})\n{'='*60}\n")

    bridge_file = OUTPUT_DIR / f"bridge_{target_date}.json"
    if not bridge_file.exists():
        # ── bridge未連携フォールバック（根本対策 2026-06-17）──
        # Plan Bのbridge受け渡し(GHAキャッシュ)が不発でも、SNSを必ず出す。
        # 旧実装は「SNSスキップ＋失敗通知」で静かに止まり、6/15〜17の占いSNSが
        # 3日間サイレント欠落した（記事=WPは出るのにSNSだけ出ない）。
        print(f"  [warn] bridge未連携: {bridge_file.name}（キャッシュ未連携 or WP公開ジョブ未完）")
        # 既に主要SNS投稿済み(マーカー)なら再生成しない＝¥0・二重投稿防止・無駄な再課金回避
        done_file = OUTPUT_DIR / f"sns_done_{target_date}.json"
        done = {}
        if done_file.exists():
            try:
                done = json.loads(done_file.read_text(encoding="utf-8"))
            except Exception:
                done = {}
        core = ("threads", "instagram", "instagram_reel")
        if all(done.get(k) == "ok" for k in core):
            print("  ✅ 主要SNSは既に投稿済み(マーカー) → 再生成せず終了")
            return {"status": "already_posted_no_bridge"}
        # ── 再生成は1日1回まで（コスト暴走ガード）──
        # bridge欠落＋SNS失敗が重なる異常日に、06:00/06:30/07:00/08:00 の4リトライが
        # それぞれ記事を再生成(Claude API)すると最悪4倍課金。トークン切れ等の持続的失敗は
        # リトライ再生成では直らないので、再生成は本日1回に制限する。
        # フラグは sns_done に同居させGHAキャッシュで次リトライへ引き継ぐ。
        if done.get("_fallback_regen_done"):
            print("  ⏭ 本日フォールバック再生成は実施済み → 再課金せず終了（bridge復活/トークン復旧待ち）")
            return {"status": "fallback_capped"}
        done["_fallback_regen_done"] = True
        try:
            done_file.parent.mkdir(parents=True, exist_ok=True)
            done_file.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        # 未投稿あり → フルパイプライン再実行で再生成して直接SNS投稿（本日1回限り）。
        #   WP更新はDRAFT_POST_IDS+slugで冪等／SNSはsns_doneマーカーで二重投稿しない。
        print("  → フォールバック: フルパイプライン再実行（再生成して直接SNS投稿・本日1回限り）")
        return run_pipeline(target_date, publish=True)

    bridge = json.loads(bridge_file.read_text(encoding="utf-8"))
    data = bridge.get("data", {})
    items = bridge.get("items", [])
    spot = SimpleNamespace(**bridge.get("spot", {"name": "", "is_chain": False, "source": "", "area": ""}))
    post_url = bridge.get("post_url")
    ig_image_url = bridge.get("ig_image_url")
    print(f"  bridge読込OK: spot={spot.name}  post_url={post_url}")

    # Reel動画をローカル再生成（¥0・Claude非使用）
    reel_video = OUTPUT_DIR / f"{target_date}_{weekday_key}_reel.mp4"
    try:
        from generate_reel import generate_reel
        generate_reel(target_date=target_date, weekday_key=weekday_key, items=items,
                      spot={"name": spot.name, "area": getattr(spot, "area", "")},
                      output_path=reel_video, data=data)
        print(f"  Reel再生成: {reel_video.name} ({reel_video.stat().st_size/1024:.0f}KB)")
    except Exception as e:
        print(f"  [warn] Reel再生成失敗（Feed等は継続）: {e}")
        reel_video = None

    sns_results = post_all_sns(weekday_key, data, spot, target_date, post_url, ig_image_url, reel_video)

    # 配信ログ
    try:
        claude_path = ROOT.parent / "claude"
        if str(claude_path) not in sys.path:
            sys.path.insert(0, str(claude_path))
        from sns_log import append_log
        memo_parts = ["占い", weekday_key]
        from datetime import date as _date
        if _date(2026, 5, 11) <= target_date <= _date(2026, 5, 17):
            memo_parts.append("テスト配信中")
        append_log(title=bridge.get("title") or f"今日の占い {target_date}",
                   url=post_url, time="06:00", memo=" / ".join(memo_parts))
        print("  → 配信ログ追記OK")
    except Exception as e:
        print(f"  [warn] 配信ログ失敗: {e}")

    print(f"\n{'='*60}\nSNS投稿完了: {target_date}\n{'='*60}")
    return {"status": "ok", "sns": sns_results}


def run_pipeline(target_date: date, dry: bool = False, publish: bool = False,
                 skip_wp: bool = False, wp_only: bool = False) -> dict:
    weekday_idx = target_date.weekday()
    weekday_key = WEEKDAY_KEYS[weekday_idx]
    weekday_jp = WEEKDAY_JP[weekday_idx]

    print(f"\n{'='*60}")
    print(f"占い配信パイプライン  {target_date} ({weekday_jp})")
    print(f"  dry={dry}  publish={publish}  IS_BETA={getattr(config, 'IS_BETA', False)}")
    print(f"{'='*60}\n")

    result = {"date": str(target_date), "weekday": weekday_key, "dry": dry, "steps": {}}

    # ---------- Step 1: ラッキースポット選定 ----------
    print("[1/7] ラッキースポット選定")
    spot = select_lucky_spot(target_date)
    print(f"  → {spot.name} (is_chain={spot.is_chain}, source={spot.source})")
    result["steps"]["spot"] = {"name": spot.name, "is_chain": spot.is_chain, "source": spot.source}

    # ---------- Step 2: 文脈ヒント生成 ----------
    print("\n[2/7] 文脈ヒント生成")
    ruler = get_planetary_ruler(target_date)
    moon = get_moon_phase(target_date)
    print(f"  → {ruler['name']}・{ruler['planet']}支配 / 月相: {moon['emoji']} {moon['name']}")
    result["steps"]["context"] = {"ruler": ruler["planet"], "moon": moon["name"]}

    # ---------- Step 3: 占い記事生成 ----------
    print("\n[3/7] 占い記事生成（テンプレ＋プレースホルダ方式）")
    extra = build_extra(weekday_key, target_date)
    if extra:
        ext_keys = ", ".join(extra.keys())
        print(f"  追加入力: {ext_keys}")

    article = generate_uranai_article_template(
        target_date=target_date, weekday_key=weekday_key, spot=spot, dry=dry, extra=extra,
    )

    # 日曜はテンプレ側で spots_week を必須にしているので補完
    if weekday_key == "sun":
        article["data"] = fix_sunday_spots_week(article.get("data", {}), target_date)
        from generate_text import fill_template
        article["wp_content"] = fill_template("sun", article["data"], target_date, spot)

    # raw 保存
    raw_file = RAW_DIR / f"{weekday_key}_{target_date}_data.json"
    raw_file.write_text(json.dumps(article.get("data", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  raw保存: {raw_file.name}  / 本文 {len(article['wp_content'])}字")
    result["steps"]["article"] = {"title": article["title"], "wp_chars": len(article["wp_content"]),
                                   "raw_file": str(raw_file)}

    # ---------- Step 4: 画像生成（WP + IG + Reel動画） ----------
    print("\n[4/7] 画像生成（WP + IG + Reel）")
    items = article.get("items_for_image", [])
    wp_img = OUTPUT_DIR / f"{target_date}_{weekday_key}_wp.png"
    ig_img = OUTPUT_DIR / f"{target_date}_{weekday_key}_ig.png"
    reel_video = OUTPUT_DIR / f"{target_date}_{weekday_key}_reel.mp4"
    try:
        generate_image(target_date=target_date, weekday_key=weekday_key, format="wp",
                       spot_name=spot.name, items=items, output_path=wp_img)
        generate_image(target_date=target_date, weekday_key=weekday_key, format="ig",
                       spot_name=spot.name, items=items, output_path=ig_img)
        print(f"  WP画像: {wp_img.name}")
        print(f"  IG画像: {ig_img.name}")
        # Reel動画生成（失敗してもメインフローは止めない）
        try:
            from generate_reel import generate_reel
            generate_reel(
                target_date=target_date, weekday_key=weekday_key,
                items=items,
                spot={"name": spot.name, "area": getattr(spot, "area", "")},
                output_path=reel_video,
                data=article.get("data", {}),  # 日曜の spots_week 用
            )
            print(f"  Reel動画: {reel_video.name} ({reel_video.stat().st_size/1024:.0f}KB)")
            result["steps"]["image"] = {"wp": str(wp_img), "ig": str(ig_img), "reel": str(reel_video)}
        except Exception as e_reel:
            print(f"  [warn] Reel動画生成失敗（メインフロー継続）: {e_reel}")
            result["steps"]["image"] = {"wp": str(wp_img), "ig": str(ig_img),
                                          "reel_error": str(e_reel)}
            reel_video = None
    except Exception as e:
        print(f"  [error] 画像生成失敗: {e}")
        result["steps"]["image"] = {"error": str(e)}
        wp_img = None
        reel_video = None

    # ---------- Step 5: WP投稿（draft or publish） ----------
    label = "WP公開投稿" if publish else "WP下書き保存"
    print(f"\n[5/7] {label}")
    wp_image_url = None
    ig_image_url = None
    reel_video_url = None
    post_url = None
    if skip_wp:
        print("  → [skip] --skip-wp 指定")
        result["steps"]["wp"] = {"status": "skipped"}
    else:
        post_id = DRAFT_POST_IDS.get(weekday_key)
        if not post_id:
            print(f"  [skip] {weekday_key} の DRAFT_POST_IDS 未定義")
            result["steps"]["wp"] = {"status": "no_post_id"}
        else:
            slug = f"uranai-{target_date.strftime('%Y%m%d')}"
            wp_res = update_wp_post(
                post_id, article["title"], article["wp_content"],
                eyecatch_path=wp_img, publish=publish,
                ig_eyecatch_path=ig_img,
                reel_video_path=reel_video,
                slug=slug,
            )
            if "error" in wp_res:
                print(f"  [error] {wp_res['error']}")
                result["steps"]["wp"] = {"status": "failed", "error": wp_res["error"]}
            else:
                wp_image_url = wp_res.get("wp_image_url")
                ig_image_url = wp_res.get("ig_image_url")
                reel_video_url = wp_res.get("reel_video_url")
                post_url = wp_res.get("link") if publish else wp_res.get("preview_url")
                print(f"  → {wp_res.get('link')}  status={wp_res.get('status')}")
                if publish:
                    print(f"     公開URL: {wp_res.get('link')}")
                else:
                    print(f"     プレビュー: {wp_res.get('preview_url')}")
                result["steps"]["wp"] = {
                    "status": wp_res.get("status"),
                    "post_id": post_id,
                    "link": wp_res.get("link"),
                    "preview_url": wp_res.get("preview_url"),
                }

    # ---------- Step 5.5: トップページの占いカードを最新記事へ更新 ----------
    if publish and post_url:
        print("\n[5.5] トップページ占いカード更新")
        try:
            hp_res = update_homepage_uranai_card(
                post_url=post_url, title=article["title"],
                image_url=wp_image_url, target_date=target_date,
            )
            print(f"  → {hp_res.get('status')} {hp_res.get('reason', '')}{hp_res.get('error', '')}")
            result["steps"]["homepage_card"] = hp_res
        except Exception as e:
            print(f"  [warn] トップ占いカード更新失敗（メインフロー継続）: {e}")
            result["steps"]["homepage_card"] = {"status": "failed", "error": str(e)}

    # ---------- WP-only モード：bridge を保存して SNS/ログは別ジョブ(6:00)へ委譲 ----------
    if wp_only:
        if post_url:
            bridge = {
                "weekday_key": weekday_key,
                "title": article["title"],
                "data": article.get("data", {}),
                "items": items,
                "spot": {"name": spot.name, "is_chain": getattr(spot, "is_chain", False),
                          "source": getattr(spot, "source", ""), "area": getattr(spot, "area", "")},
                "post_url": post_url,
                "ig_image_url": ig_image_url,
            }
            (OUTPUT_DIR / f"bridge_{target_date}.json").write_text(
                json.dumps(bridge, ensure_ascii=False), encoding="utf-8")
            print("\n  [wp-only] bridge保存 → SNSは6:00の別ジョブで投稿")
            result["steps"]["sns"] = {"status": "deferred", "reason": "wp_only"}
        else:
            print("\n  [wp-only] WP未公開のため bridge保存せず（次リトライへ）")
            result["steps"]["sns"] = {"status": "deferred", "reason": "wp_not_published"}
        result["steps"]["log"] = {"status": "deferred"}
        print(f"\n{'='*60}\nパイプライン完了(wp-only): {target_date}\n{'='*60}")
        return result

    # ---------- Step 6: SNS 投稿 ----------
    print("\n[6/7] SNS投稿（X / Threads / Instagram）")
    sns_results = {}
    if not publish:
        # dry-run時はキャプションだけ生成して txt 保存（artifact 確認用）
        print("  → [skip] publish=False（dry-run時は SNS投稿なし）")
        print("     ただしキャプションは txt として保存します")
        try:
            from caption import (
                make_x_caption, make_threads_caption,
                make_instagram_caption, make_instagram_reel_caption,
            )
            dummy_url = f"https://toyokawa-rentallife.com/dry-run/{target_date}/"
            captions_to_save = {
                "x": make_x_caption(weekday_key, article.get("data", {}), spot,
                                      target_date, dummy_url),
                "threads": make_threads_caption(weekday_key, article.get("data", {}),
                                                  spot, target_date, dummy_url),
                "instagram_feed": make_instagram_caption(weekday_key,
                                                          article.get("data", {}),
                                                          spot, target_date),
                "instagram_reel": make_instagram_reel_caption(weekday_key,
                                                                article.get("data", {}),
                                                                spot, target_date),
            }
            for sns_name, cap_text in captions_to_save.items():
                cap_file = OUTPUT_DIR / f"{target_date}_{weekday_key}_caption_{sns_name}.txt"
                cap_file.write_text(cap_text, encoding="utf-8")
                print(f"     キャプション保存: {cap_file.name} ({len(cap_text)}字)")
            result["steps"]["sns"] = {"status": "skipped", "reason": "publish=False",
                                       "captions_saved": True}
        except Exception as e:
            print(f"     [warn] キャプション生成失敗: {e}")
            result["steps"]["sns"] = {"status": "skipped", "reason": "publish=False",
                                       "caption_error": str(e)}
    elif not post_url:
        print("  → [skip] WP投稿失敗のため SNS投稿スキップ")
        result["steps"]["sns"] = {"status": "skipped", "reason": "wp_failed"}
    else:
        sns_results = post_all_sns(weekday_key, article.get("data", {}), spot,
                                   target_date, post_url, ig_image_url, reel_video)
        result["steps"]["sns"] = sns_results

    # ---------- Step 7: 配信ログ ----------
    print("\n[7/7] 配信ログ記録")
    if not publish:
        print("  → [skip] publish=False")
        result["steps"]["log"] = {"status": "skipped"}
    elif not post_url:
        print("  → [skip] WP投稿失敗")
        result["steps"]["log"] = {"status": "skipped"}
    else:
        try:
            # claude/sns_log.py を import
            claude_path = ROOT.parent / "claude"
            if str(claude_path) not in sys.path:
                sys.path.insert(0, str(claude_path))
            from sns_log import append_log
            ok_x = sns_results.get("x", {}).get("status") == "ok"
            ok_th = sns_results.get("threads", {}).get("status") == "ok"
            ok_ig = sns_results.get("instagram", {}).get("status") == "ok"
            memo_parts = ["占い", weekday_key]
            from datetime import date as _date
            if _date(2026, 5, 11) <= target_date <= _date(2026, 5, 17):
                memo_parts.append("テスト配信中")
            append_log(
                title=article["title"],
                url=post_url,
                time="06:00",
                memo=" / ".join(memo_parts),
            )
            print("  → 配信ログ追記OK")
            result["steps"]["log"] = {"status": "ok"}
        except Exception as e:
            print(f"  [warn] 配信ログ失敗: {e}")
            result["steps"]["log"] = {"status": "failed", "error": str(e)}

    print(f"\n{'='*60}")
    print(f"パイプライン完了: {target_date}")
    print(f"{'='*60}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="対象日 YYYY-MM-DD（未指定時は JST の今日）")
    parser.add_argument("--dry", action="store_true", help="ダミーデータで実行（実API課金なし・¥0）")
    parser.add_argument("--publish", action="store_true", help="本番公開＋SNS投稿（Phase 3 で実装）")
    parser.add_argument("--skip-wp", action="store_true", help="WP下書き保存もスキップ（ローカル生成のみ）")
    parser.add_argument("--skip-if-published", action="store_true",
                        help="今日の記事が既にWP公開済みなら何もせず終了（リトライ用・二重公開防止）")
    parser.add_argument("--wp-only", action="store_true",
                        help="WP公開のみ（SNS無し）＋bridge保存。早朝リトライ安全（SNS二重投稿なし）")
    parser.add_argument("--sns-only", action="store_true",
                        help="bridge を読み SNS投稿のみ（6:00別ジョブ用）")
    args = parser.parse_args()

    target_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else get_today_jst()
    )

    # SNS-only モード（6:00 別ジョブ）：bridge から SNS投稿のみ
    if args.sns_only:
        try:
            res = run_sns_only(target_date)
            print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        except Exception as e:
            try:
                notify_uranai_failure(e, context={"target_date": str(target_date), "phase": "sns_only"})
            except Exception:
                pass
            raise
        return

    # 冪等ガード：既にWP公開済みなら何もしない（wp-only 早朝リトライ用）
    if args.skip_if_published and check_already_published(target_date):
        print(f"[skip] {target_date} は既にWP公開済み → 冪等スキップ（二重公開回避）")
        return

    try:
        result = run_pipeline(target_date, dry=args.dry, publish=args.publish,
                              skip_wp=args.skip_wp, wp_only=args.wp_only)
        print()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        try:
            notify_uranai_failure(e, context={
                "target_date": str(target_date),
                "dry": args.dry,
            })
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
