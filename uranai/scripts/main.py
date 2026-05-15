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


def run_pipeline(target_date: date, dry: bool = False, publish: bool = False, skip_wp: bool = False) -> dict:
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
        from post_x_uranai import post_x_uranai
        from post_threads_uranai import post_threads_uranai
        from post_instagram_uranai import post_instagram_uranai

        print("  [X]")
        x_res = post_x_uranai(
            weekday_key=weekday_key, data=article.get("data", {}), spot=spot,
            target_date=target_date, post_url=post_url, dry=False,
        )
        print(f"     status={x_res['status']}  url={x_res.get('url')}")
        sns_results["x"] = x_res

        print("  [Threads]")
        th_res = post_threads_uranai(
            weekday_key=weekday_key, data=article.get("data", {}), spot=spot,
            target_date=target_date, post_url=post_url, dry=False,
        )
        print(f"     status={th_res['status']}  post_id={th_res.get('post_id')}")
        sns_results["threads"] = th_res

        print("  [Instagram Feed]")
        if not ig_image_url:
            print("     [skip] IG画像URL未取得（WP メディアアップ失敗）")
            sns_results["instagram"] = {"status": "skipped", "reason": "no_ig_url"}
        else:
            ig_res = post_instagram_uranai(
                weekday_key=weekday_key, data=article.get("data", {}), spot=spot,
                target_date=target_date, ig_image_url=ig_image_url, dry=False,
            )
            print(f"     status={ig_res['status']}  post_id={ig_res.get('post_id')}")
            sns_results["instagram"] = ig_res

        # Reels 投稿（動画URL取得済みなら追加）
        print("  [Instagram Reels]")
        if not reel_video_url:
            print("     [skip] Reel動画URL未取得（生成失敗 or WP アップ失敗）")
            sns_results["instagram_reel"] = {"status": "skipped", "reason": "no_reel_url"}
        else:
            from post_instagram_uranai import post_instagram_uranai_reel
            ig_reel_res = post_instagram_uranai_reel(
                weekday_key=weekday_key, data=article.get("data", {}), spot=spot,
                target_date=target_date, video_url=reel_video_url,
                cover_url=None,  # Instagramが動画の1フレーム目を自動サムネ化（再生時の切替が自然・グリッドでもフィード画像と差別化）
                dry=False,
            )
            print(f"     status={ig_reel_res['status']}  post_id={ig_reel_res.get('post_id')}")
            sns_results["instagram_reel"] = ig_reel_res

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
    args = parser.parse_args()

    target_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else get_today_jst()
    )

    try:
        result = run_pipeline(target_date, dry=args.dry, publish=args.publish, skip_wp=args.skip_wp)
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
