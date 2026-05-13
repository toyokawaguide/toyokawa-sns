"""
SNS用キャプション生成（X / Threads / Instagram 共通）
======================================================

全曜日・3SNS分のキャプションを一元生成。

【構成】
- make_x_caption()        : X用（140日本語字制限）
- make_threads_caption()  : Threads用（500字）
- make_instagram_caption(): Instagram用（2200字）

【入力】
- weekday_key: 'mon' / 'tue' / ... / 'sun'
- data       : generate_text の data dict（items / blood / spots_week 等）
- spot       : Spot オブジェクト
- target_date: 配信対象日
- post_url   : WP記事URL（Instagram は使わない）

【ベータ期間（2026-05-11〜2026-05-17）】自動でテスト配信中表記を付与
"""
from __future__ import annotations
import re
from datetime import date, timedelta

from uranai_fri_sat import get_top10_stars, format_star_score


BETA_START = date(2026, 5, 11)
BETA_END = date(2026, 5, 17)
BETA_NOTICE_SHORT = "※5/17までテスト配信中"
BETA_NOTICE_LONG = (
    "⚠️5/17までテスト配信中\n"
    "本格運用に向けて調整中です。\n"
    "お気付きの点はお問い合わせから🙇"
)


def _first_sentence(s: str) -> str:
    if not s:
        return ""
    parts = re.split(r"(?<=[。！？])", s)
    return parts[0] if parts else s


def _trim(s: str, n: int = 30) -> str:
    s = _first_sentence(s)
    return s if len(s) <= n else s[:n].rstrip("、。") + "…"


def _chain(name: str, is_chain: bool) -> str:
    return f"お近くの{name}" if is_chain else name


def _is_beta(target_date: date) -> bool:
    return BETA_START <= target_date <= BETA_END


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _wd_jp(d: date) -> str:
    return ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]


# ============================================================
# X（140日本語字制限）
# ============================================================

def make_x_caption(weekday_key: str, data: dict, spot, target_date: date, post_url: str) -> str:
    md = _md(target_date)
    wd = _wd_jp(target_date)
    sp = _chain(spot.name, spot.is_chain)
    head = f"{BETA_NOTICE_SHORT}\n\n" if _is_beta(target_date) else ""

    if weekday_key == "mon":
        items = sorted(data.get("items", []), key=lambda x: -x.get("stars", 0))
        return (
            f"{head}"
            f"🔮{md}({wd})の占い・全12星座いっき見!\n\n"
            f"🥇{items[0]['label']} ★{items[0]['stars']}\n"
            f"🥈{items[1]['label']} ★{items[1]['stars']}\n"
            f"🥉{items[2]['label']} ★{items[2]['stars']}\n\n"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{post_url}\n"
            f"#豊川ガイド #今日の占い #星座占い"
        )

    if weekday_key == "tue":
        blood = data.get("blood", {})
        order = sorted(["A", "B", "O", "AB"], key=lambda k: -blood.get(k, {}).get("stars", 0))
        return (
            f"{head}"
            f"🔮{md}({wd})の占い・血液型!\n\n"
            f"🥇{order[0]}型 ★{blood[order[0]]['stars']}\n"
            f"🥈{order[1]}型 ★{blood[order[1]]['stars']}\n"
            f"🥉{order[2]}型 ★{blood[order[2]]['stars']}\n"
            f"4位:{order[3]}型 ★{blood[order[3]]['stars']}\n\n"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{post_url}\n"
            f"#豊川ガイド #今日の占い #血液型占い"
        )

    if weekday_key in ("wed", "thu"):
        items = sorted(data.get("items", []), key=lambda x: -x.get("stars", 0))
        kind = {"wed": "誕生月", "thu": "干支"}[weekday_key]
        tag = {"wed": "#誕生月占い", "thu": "#干支占い"}[weekday_key]
        return (
            f"{head}"
            f"🔮{md}({wd})の占い・{kind}!\n\n"
            f"🥇{items[0]['label']} ★{items[0]['stars']}\n"
            f"🥈{items[1]['label']} ★{items[1]['stars']}\n"
            f"🥉{items[2]['label']} ★{items[2]['stars']}\n\n"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{post_url}\n"
            f"#豊川ガイド #今日の占い {tag}"
        )

    if weekday_key in ("fri", "sat"):
        items = data.get("items", [])
        seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
        stars = get_top10_stars(seed=seed)
        emo = {"fri": "🎂", "sat": "🏘️"}[weekday_key]
        kind = {"fri": "ラッキー生まれ年TOP10", "sat": "ラッキータウンTOP10"}[weekday_key]
        tag = {"fri": "#生まれ年占い", "sat": "#ラッキータウン"}[weekday_key]
        return (
            f"{head}"
            f"{emo}{md}({wd}){kind}!\n\n"
            f"🥇{items[0]['label']} {format_star_score(stars[0])}\n"
            f"🥈{items[1]['label']} {format_star_score(stars[1])}\n"
            f"🥉{items[2]['label']} {format_star_score(stars[2])}\n"
            f"…続きはブログで\n\n"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{post_url}\n"
            f"#豊川ガイド {tag}"
        )

    if weekday_key == "sun":
        theme = data.get("next_week_theme", "-")
        msg = _first_sentence(data.get("next_week_message", ""))
        return (
            f"{head}"
            f"🔮{md}({wd})今週まとめ&来週運勢\n\n"
            f"今週も1週間お疲れさまでした!\n\n"
            f"🌱来週のテーマは「{theme}」\n"
            f"{msg}\n\n"
            f"明日からまた毎朝6時にお届けします🦊\n\n"
            f"{post_url}\n"
            f"#豊川ガイド #今週のまとめ #占い"
        )

    return ""


# ============================================================
# Threads（500字制限・X より少し詳しく）
# ============================================================

def make_threads_caption(weekday_key: str, data: dict, spot, target_date: date, post_url: str) -> str:
    md = _md(target_date)
    wd = _wd_jp(target_date)
    sp = _chain(spot.name, spot.is_chain)
    head = f"{BETA_NOTICE_SHORT}\n\n" if _is_beta(target_date) else ""

    if weekday_key in ("mon", "wed", "thu"):
        items = sorted(data.get("items", []), key=lambda x: -x.get("stars", 0))
        kind = {"mon": "全12星座いっき見", "wed": "誕生月", "thu": "干支"}[weekday_key]
        tag = {"mon": "#星座占い", "wed": "#誕生月占い", "thu": "#干支占い"}[weekday_key]
        return (
            f"{head}"
            f"🔮{md}({wd})の占い・{kind}!\n\n"
            f"🥇{items[0]['label']} ★{items[0]['stars']}\n{_trim(items[0]['comment'])}\n\n"
            f"🥈{items[1]['label']} ★{items[1]['stars']}\n{_trim(items[1]['comment'])}\n\n"
            f"🥉{items[2]['label']} ★{items[2]['stars']}\n{_trim(items[2]['comment'])}\n\n"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"→詳細はブログで\n{post_url}\n\n"
            f"#豊川ガイド #豊川市 #今日の占い {tag}"
        )

    if weekday_key == "tue":
        blood = data.get("blood", {})
        order = sorted(["A", "B", "O", "AB"], key=lambda k: -blood.get(k, {}).get("stars", 0))
        labels = ["🥇", "🥈", "🥉", "4位:"]
        body = ""
        for i, k in enumerate(order):
            b = blood[k]
            body += f"{labels[i]}{k}型 ★{b['stars']}\n{_trim(b['comment'])}\n\n"
        return (
            f"{head}"
            f"🔮{md}({wd})の占い・血液型!\n\n"
            f"{body}"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"→詳細はブログで\n{post_url}\n\n"
            f"#豊川ガイド #豊川市 #今日の占い #血液型占い"
        )

    if weekday_key in ("fri", "sat"):
        items = data.get("items", [])
        seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
        stars = get_top10_stars(seed=seed)
        emo = {"fri": "🎂", "sat": "🏘️"}[weekday_key]
        kind = {"fri": "ラッキー生まれ年TOP10", "sat": "ラッキータウンTOP10"}[weekday_key]
        tag = {"fri": "#生まれ年占い", "sat": "#ラッキータウン #ご当地占い"}[weekday_key]
        return (
            f"{head}"
            f"{emo}{md}({wd}){kind}!\n\n"
            f"🥇{items[0]['label']} {format_star_score(stars[0])}\n{_trim(items[0]['comment'])}\n\n"
            f"🥈{items[1]['label']} {format_star_score(stars[1])}\n{_trim(items[1]['comment'])}\n\n"
            f"🥉{items[2]['label']} {format_star_score(stars[2])}\n{_trim(items[2]['comment'])}\n\n"
            f"…続きはブログで全10位!\n\n"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{post_url}\n\n"
            f"#豊川ガイド #豊川市 {tag}"
        )

    if weekday_key == "sun":
        theme = data.get("next_week_theme", "-")
        msg = _first_sentence(data.get("next_week_message", ""))
        spots_week = data.get("spots_week", {})
        wd_jp = ["月", "火", "水", "木", "金", "土"]
        spot_lines = []
        for i, key in enumerate(["mon", "tue", "wed", "thu", "fri", "sat"]):
            past_d = target_date - timedelta(days=6 - i)
            md_p = f"{past_d.month}/{past_d.day}"
            spot_lines.append(f"・{md_p}({wd_jp[i]}) {spots_week.get(key, '-')}")
        spots_block = "\n".join(spot_lines)
        return (
            f"{head}"
            f"🔮{md}({wd})今週まとめ&来週運勢\n\n"
            f"今週も1週間お疲れさまでした!\n\n"
            f"🦊今週のラッキースポット振り返り\n{spots_block}\n\n"
            f"🌱来週のテーマは「{theme}」\n{msg}\n\n"
            f"明日からまた毎朝6時に🦊\n\n"
            f"{post_url}\n\n"
            f"#豊川ガイド #豊川市 #今週のまとめ #占い"
        )

    return ""


# ============================================================
# Instagram（2200字制限・URL クリック不可・プロフィール経由案内）
# ============================================================

def make_instagram_caption(weekday_key: str, data: dict, spot, target_date: date) -> str:
    md = _md(target_date)
    wd = _wd_jp(target_date)
    sp = _chain(spot.name, spot.is_chain)
    head = f"{BETA_NOTICE_LONG}\n\n" if _is_beta(target_date) else ""
    common_tags = "#豊川ガイド #豊川市 #toyokawa #愛知県 #朝の占い #占い好き #ご当地"
    cta = "📌全項目はブログで\n@toyokawaguide → プロフィールのリンクから\nトップページの「🔮 今日の占い」をチェック！"

    def _block(rank, label, stars_text, comment):
        return f"{rank}{label} {stars_text}\n{_first_sentence(comment)}\n\n"

    if weekday_key in ("mon", "wed", "thu"):
        items = sorted(data.get("items", []), key=lambda x: -x.get("stars", 0))
        kind = {"mon": "全12星座", "wed": "誕生月", "thu": "干支"}[weekday_key]
        tag = {"mon": "#星座占い", "wed": "#誕生月占い", "thu": "#干支占い"}[weekday_key]
        b0 = _block("🥇", items[0]["label"], f"★{items[0]['stars']}", items[0]["comment"])
        b1 = _block("🥈", items[1]["label"], f"★{items[1]['stars']}", items[1]["comment"])
        b2 = _block("🥉", items[2]["label"], f"★{items[2]['stars']}", items[2]["comment"])
        return (
            f"{head}"
            f"✨{target_date.year}年{md}({wd})の占い・{kind}✨\n\n"
            f"📖今日のTOP3\n\n"
            f"{b0}{b1}{b2}"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{cta}\n\n"
            f"{common_tags} #今日の占い {tag}"
        )

    if weekday_key == "tue":
        blood = data.get("blood", {})
        order = sorted(["A", "B", "O", "AB"], key=lambda k: -blood.get(k, {}).get("stars", 0))
        rank_emojis = ["🥇", "🥈", "🥉", "4位:"]
        body = ""
        for i, k in enumerate(order):
            b = blood[k]
            body += _block(rank_emojis[i], f"{k}型", f"★{b['stars']}", b["comment"])
        return (
            f"{head}"
            f"✨{target_date.year}年{md}({wd})の占い・血液型✨\n\n"
            f"📖今日の運勢\n\n"
            f"{body}"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{cta}\n\n"
            f"{common_tags} #今日の占い #血液型占い"
        )

    if weekday_key in ("fri", "sat"):
        items = data.get("items", [])
        seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
        stars = get_top10_stars(seed=seed)
        emo = {"fri": "🎂", "sat": "🏘️"}[weekday_key]
        kind = {"fri": "ラッキー生まれ年TOP10", "sat": "ラッキータウンTOP10"}[weekday_key]
        tag = {"fri": "#生まれ年占い", "sat": "#ラッキータウン #ご当地占い"}[weekday_key]
        b0 = _block("🥇", items[0]["label"], format_star_score(stars[0]), items[0]["comment"])
        b1 = _block("🥈", items[1]["label"], format_star_score(stars[1]), items[1]["comment"])
        b2 = _block("🥉", items[2]["label"], format_star_score(stars[2]), items[2]["comment"])
        return (
            f"{head}"
            f"{emo}{target_date.year}年{md}({wd}) {kind}{emo}\n\n"
            f"📖今日のTOP3\n\n"
            f"{b0}{b1}{b2}"
            f"…続きはブログで全10位!\n\n"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{cta}\n\n"
            f"{common_tags} {tag}"
        )

    if weekday_key == "sun":
        theme = data.get("next_week_theme", "-")
        msg = _first_sentence(data.get("next_week_message", ""))
        spots_week = data.get("spots_week", {})
        wd_jp = ["月", "火", "水", "木", "金", "土"]
        spot_lines = []
        for i, key in enumerate(["mon", "tue", "wed", "thu", "fri", "sat"]):
            past_d = target_date - timedelta(days=6 - i)
            md_p = f"{past_d.month}/{past_d.day}"
            spot_lines.append(f"・{md_p}({wd_jp[i]}) {spots_week.get(key, '-')}")
        spots_block = "\n".join(spot_lines)
        return (
            f"{head}"
            f"🔮{target_date.year}年{md}({wd}) 今週まとめ&来週運勢🔮\n\n"
            f"今週も1週間お疲れさまでした!\n\n"
            f"🦊今週のラッキースポット振り返り\n{spots_block}\n\n"
            f"🌱来週のテーマは「{theme}」\n{msg}\n\n"
            f"明日からまた毎朝6時にお届けします🦊\n\n"
            f"{cta}\n\n"
            f"{common_tags} #今週のまとめ #占い"
        )

    return ""


# ============================================================
# Instagram Reels（フィードより詳細・全位掲載版）
# ============================================================
# 動画内で全位表示しているリールに合わせ、キャプションでも全位を掲載。
# TOP3はコメント付き / 4位以下は星評価のみの簡易表示。
# 狙い：検索性UP・保存価値UP・再生時間UPでアルゴリズム評価改善。

def make_instagram_reel_caption(weekday_key: str, data: dict, spot, target_date: date) -> str:
    md = _md(target_date)
    wd = _wd_jp(target_date)
    sp = _chain(spot.name, spot.is_chain)
    head = f"{BETA_NOTICE_LONG}\n\n" if _is_beta(target_date) else ""
    common_tags = "#豊川ガイド #豊川市 #toyokawa #愛知県 #朝の占い #占い好き #ご当地"
    cta = "📌全文＋スポット詳細はブログで\n@toyokawaguide → プロフィールのリンクから\nトップページの「🔮 今日の占い」をチェック！"

    def _block(rank, label, stars_text, comment):
        return f"{rank}{label} {stars_text}\n{_first_sentence(comment)}\n\n"

    def _short(rank_label, label, stars_text):
        return f"{rank_label} {label} {stars_text}\n"

    if weekday_key in ("mon", "wed", "thu"):
        items = sorted(data.get("items", []), key=lambda x: -x.get("stars", 0))
        kind = {"mon": "全12星座", "wed": "誕生月", "thu": "干支"}[weekday_key]
        tag = {"mon": "#星座占い", "wed": "#誕生月占い", "thu": "#干支占い"}[weekday_key]

        b0 = _block("🥇", items[0]["label"], f"★{items[0]['stars']}", items[0]["comment"])
        b1 = _block("🥈", items[1]["label"], f"★{items[1]['stars']}", items[1]["comment"])
        b2 = _block("🥉", items[2]["label"], f"★{items[2]['stars']}", items[2]["comment"])

        rank_labels = ["4位", "5位", "6位", "7位", "8位", "9位", "10位", "11位", "12位"]
        rest = ""
        for i, item in enumerate(items[3:]):
            rest += _short(rank_labels[i], item["label"], f"★{item['stars']}")

        return (
            f"{head}"
            f"✨{target_date.year}年{md}({wd})の占い・{kind}✨\n\n"
            f"📖今日のTOP3\n\n"
            f"{b0}{b1}{b2}"
            f"📊全ランキング\n"
            f"{rest}\n"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{cta}\n\n"
            f"{common_tags} #今日の占い {tag}"
        )

    if weekday_key == "tue":
        # 血液型は4種なので元々全部記載・フィード版と同じ内容
        return make_instagram_caption(weekday_key, data, spot, target_date)

    if weekday_key in ("fri", "sat"):
        items = data.get("items", [])
        seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
        stars = get_top10_stars(seed=seed)
        emo = {"fri": "🎂", "sat": "🏘️"}[weekday_key]
        kind = {"fri": "ラッキー生まれ年TOP10", "sat": "ラッキータウンTOP10"}[weekday_key]
        tag = {"fri": "#生まれ年占い", "sat": "#ラッキータウン #ご当地占い"}[weekday_key]

        b0 = _block("🥇", items[0]["label"], format_star_score(stars[0]), items[0]["comment"])
        b1 = _block("🥈", items[1]["label"], format_star_score(stars[1]), items[1]["comment"])
        b2 = _block("🥉", items[2]["label"], format_star_score(stars[2]), items[2]["comment"])

        rank_labels = ["4位", "5位", "6位", "7位", "8位", "9位", "10位"]
        rest = ""
        for i, item in enumerate(items[3:]):
            rest += _short(rank_labels[i], item["label"], format_star_score(stars[i + 3]))

        return (
            f"{head}"
            f"{emo}{target_date.year}年{md}({wd}) {kind}{emo}\n\n"
            f"📖今日のTOP3\n\n"
            f"{b0}{b1}{b2}"
            f"📊全ランキング\n"
            f"{rest}\n"
            f"🦊本日のラッキースポット\n{sp}\n\n"
            f"{cta}\n\n"
            f"{common_tags} {tag}"
        )

    if weekday_key == "sun":
        # 日曜は週まとめでフィード版と内容差別化の余地が少ない
        return make_instagram_caption(weekday_key, data, spot, target_date)

    return ""
