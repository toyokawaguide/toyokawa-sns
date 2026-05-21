"""
占い記事生成（Claude API Sonnet 4.5）+ 構造化抽出
==========================================================

各曜日のプロンプト + 共通システムプロンプト + ラッキースポット情報 + 文脈ヒント
を組み立てて Claude API に投げ、占い記事を生成する。
さらに応答を構造化抽出して画像生成・SNS投稿用データを返す。

【出力】
{
  "title": "...",
  "wp_content": "...",
  "items": [...],              # 画像生成用 構造化データ
  "x_text": "...",             # X 用 140字
  "threads_text": "...",       # Threads 用 500字
  "instagram_caption": "...",  # Instagram キャプション
  "raw_response": "..."        # Claude 応答原文
}

【dry-run】
- ANTHROPIC_API_KEY 未設定 or --dry オプションでダミー応答（曜日別にリアルな内容）

【使い方】
  python generate_text.py --date 2026-05-11 --dry
  python generate_text.py --date 2026-05-11 --show-prompt
  python generate_text.py --date 2026-05-11   # 実 API 呼び出し
"""
from __future__ import annotations
import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import date, datetime
from dataclasses import dataclass, field

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(override=True)

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

import config
from context_hints import build_context_hints
from select_lucky_spot import Spot

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

PROMPT_FILES = {
    "mon": "monday_zodiac.txt",
    "tue": "tuesday_blood.txt",
    "wed": "wednesday_birthmonth.txt",
    "thu": "thursday_eto.txt",
    "fri": "friday_birthyear.txt",
    "sat": "saturday_town.txt",
    "sun": "sunday_summary.txt",
}


# ============================================================
# プロンプト組み立て
# ============================================================

def load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def build_system_prompt(target_date: date) -> str:
    common = load_prompt("system_common.txt")
    hints = build_context_hints(target_date)
    return common + "\n\n" + hints


def build_user_prompt(*, weekday_key: str, target_date: date,
                     spot: Spot, extra: dict | None = None) -> str:
    weekday_prompt = load_prompt(PROMPT_FILES[weekday_key])

    spot_json = {
        "date": target_date.isoformat(),
        "weekday": WEEKDAY_JP[target_date.weekday()],
        "name": spot.name,
        "is_chain": spot.is_chain,
        "_note": "is_chain=true なら『お近くの【〇〇】』表記、false なら『【〇〇】』通常指名",
    }

    sections = [
        weekday_prompt,
        "",
        "## 今日のラッキースポット情報",
        "```json",
        json.dumps(spot_json, ensure_ascii=False, indent=2),
        "```",
    ]

    if extra:
        sections.extend([
            "",
            "## 追加情報",
            "```json",
            json.dumps(extra, ensure_ascii=False, indent=2),
            "```",
        ])

    return "\n".join(sections)


# ============================================================
# Claude API 呼び出し（実消費）
# ============================================================

def call_claude_api(system_prompt: str, user_prompt: str) -> str:
    """Claude API（Sonnet 4.5）を呼び出して本文を返す。料金発生注意。"""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が未設定")
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.ANTHROPIC_MAX_TOKENS,
        temperature=config.ANTHROPIC_TEMPERATURE,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


# ============================================================
# テンプレート方式（Phase 2.5・社長指示の固定/変動分離）
# ============================================================

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

WEEKDAY_JP_FULL = {
    "mon": "月", "tue": "火", "wed": "水", "thu": "木",
    "fri": "金", "sat": "土", "sun": "日",
}


def _format_date_jp(target_date: date) -> str:
    wd = WEEKDAY_JP_FULL[WEEKDAY_KEYS[target_date.weekday()]]
    return f"{target_date.year}年{target_date.month}月{target_date.day}日（{wd}）"


def _format_stars(n: int) -> str:
    """10段階表示（★N個＋☆で埋め＋N/10数値）"""
    n = max(0, min(10, int(n)))
    return "★" * n + "☆" * (10 - n) + f" {n}/10"


def _build_template_data_prompt(weekday_key: str, target_date: date, spot: Spot, extra: dict | None = None) -> tuple[str, str]:
    """テンプレート方式の system + user プロンプト構築

    Args:
        extra: 金/土のような追加入力（{"years": [...]} / {"towns": [...]}）
    """
    common = load_prompt("system_common.txt")
    hints = build_context_hints(target_date)
    weekday_full = {
        "mon": "monday", "tue": "tuesday", "wed": "wednesday",
        "thu": "thursday", "fri": "friday", "sat": "saturday", "sun": "sunday",
    }.get(weekday_key, weekday_key)
    template_prompt = load_prompt(f"template_data_{weekday_full}.txt")

    spot_json = {
        "date": target_date.isoformat(),
        "weekday": WEEKDAY_JP[target_date.weekday()],
        "name": spot.name,
        "is_chain": spot.is_chain,
    }
    user = template_prompt + "\n\n## 今日のラッキースポット情報\n```json\n" \
           + json.dumps(spot_json, ensure_ascii=False, indent=2) + "\n```"
    if extra:
        user += "\n\n## 今日の入力データ\n```json\n" + json.dumps(extra, ensure_ascii=False, indent=2) + "\n```"
    system = common + "\n\n" + hints
    return system, user


def _dummy_template_data_monday(spot: Spot) -> dict:
    """dry-run用の月曜ダミー JSON データ（10段階）
    comment は本番プロンプトと同じく各文18字以内・合計36字以内に厳守"""
    return {
        "intro_text": "新しい1週間が始まりますね。新月期に差しかかる頃かも。",
        "items": [
            {"label": "おひつじ座", "stars": 8, "comment": "行動力が冴える日。即実行が吉。"},
            {"label": "おうし座", "stars": 6, "comment": "のんびりペースで。リズム大切に。"},
            {"label": "ふたご座", "stars": 10, "comment": f"絶好調の予感。{spot.name} に寄ってみて。"},
            {"label": "かに座", "stars": 4, "comment": "感情が揺れる日。深呼吸して。"},
            {"label": "しし座", "stars": 10, "comment": "オーラ全開。思い切ってどうぞ。"},
            {"label": "おとめ座", "stars": 6, "comment": "細部に気を配って吉。完璧は控えめに。"},
            {"label": "てんびん座", "stars": 5, "comment": "判断は慎重に。急がず冷静に。"},
            {"label": "さそり座", "stars": 7, "comment": "直感が冴える日。動いてみて。"},
            {"label": "いて座", "stars": 8, "comment": "ノリと勢いの日。発見あるかも。"},
            {"label": "やぎ座", "stars": 6, "comment": "進展あり。焦らず一歩ずつ。"},
            {"label": "みずがめ座", "stars": 3, "comment": "整理が吉。デスクを片付けて。"},
            {"label": "うお座", "stars": 5, "comment": "感性が豊かに。音楽や映画を。"},
        ],
    }


def _dummy_template_data_wednesday(spot: Spot) -> dict:
    """dry-run用の水曜（誕生月12占い）ダミー JSON データ（10段階）
    comment は本番プロンプトと同じく各文18字以内・合計36字以内に厳守"""
    return {
        "intro_text": "週の真ん中、水曜日です。水星の支配日、思考が冴える頃かも。",
        "items": [
            {"label": "1月生まれ", "stars": 8, "comment": "落ち着いた行動が吉。じっくり考えて。"},
            {"label": "2月生まれ", "stars": 6, "comment": "穏やかな日に。自分のペースを大切に。"},
            {"label": "3月生まれ", "stars": 10, "comment": f"絶好調の予感。{spot.name} に寄ってみて。"},
            {"label": "4月生まれ", "stars": 4, "comment": "ペースが乱れがち。休憩を取って。"},
            {"label": "5月生まれ", "stars": 10, "comment": "創造力が冴える。アイデアはメモ。"},
            {"label": "6月生まれ", "stars": 6, "comment": "穏やかに進む日。耳を傾けて吉。"},
            {"label": "7月生まれ", "stars": 5, "comment": "ぼちぼちでOK。ほどほどに。"},
            {"label": "8月生まれ", "stars": 7, "comment": "新しい風が吹く。変化を楽しんで。"},
            {"label": "9月生まれ", "stars": 8, "comment": "段取り上手な日。リスト片付けて。"},
            {"label": "10月生まれ", "stars": 6, "comment": "判断は急がず、慎重に。"},
            {"label": "11月生まれ", "stars": 3, "comment": "感情が揺れる日。深呼吸して。"},
            {"label": "12月生まれ", "stars": 5, "comment": "進展あり。焦らず一歩ずつ。"},
        ],
    }


def _dummy_template_data_thursday(spot: Spot) -> dict:
    """dry-run用の木曜（干支12占い）ダミー JSON データ（10段階）
    comment は本番プロンプトと同じく各文18字以内・合計36字以内に厳守"""
    return {
        "intro_text": "今日は木曜、木星の支配日。大きな視点で動くといい頃かも。",
        "items": [
            {"label": "子（ねずみ）年", "stars": 8, "comment": "機転が利く日。即行動が吉。"},
            {"label": "丑（うし）年", "stars": 6, "comment": "手応えあり。地に足つけて。"},
            {"label": "寅（とら）年", "stars": 10, "comment": f"勢いに乗れる日。{spot.name} に寄ってみて。"},
            {"label": "卯（うさぎ）年", "stars": 4, "comment": "ペース乱れがち。深呼吸して。"},
            {"label": "辰（たつ）年", "stars": 10, "comment": "オーラ全開。うまくいきそう。"},
            {"label": "巳（へび）年", "stars": 6, "comment": "直感が冴える日。確かめてみて。"},
            {"label": "午（うま）年", "stars": 5, "comment": "急がず、冷静に判断を。"},
            {"label": "未（ひつじ）年", "stars": 7, "comment": "穏やかな運気。ヒントが得られそう。"},
            {"label": "申（さる）年", "stars": 8, "comment": "発想が豊かに。新しい角度から。"},
            {"label": "酉（とり）年", "stars": 6, "comment": "細部に気を配って吉。完璧は控えめ。"},
            {"label": "戌（いぬ）年", "stars": 3, "comment": "情熱が空回り。休憩を取って。"},
            {"label": "亥（いのしし）年", "stars": 5, "comment": "感情が動く日。身近な人と時間を。"},
        ],
    }


def _dummy_template_data_friday(spot: Spot) -> dict:
    """dry-run用の金曜（生まれ年TOP10）ダミー JSON データ
    comment は本番プロンプトと同じく各文18字以内・合計36字以内に厳守"""
    return {
        "intro_text": "今日は金曜、金星の支配日。ラッキー生まれ年TOP10を発表します。",
        "items": [
            {"label": "1990年（平成2年）生まれ", "comment": f"絶好調の予感。{spot.name} に寄ってみて。"},
            {"label": "2003年（平成15年）生まれ", "comment": "笑顔が連鎖する日。挨拶で運気UP。"},
            {"label": "1976年（昭和51年）生まれ", "comment": "落ち着いた行動が吉。じっくり考えて。"},
            {"label": "2020年（令和2年）生まれ", "comment": "可愛がられる1日。素直な気持ちで。"},
            {"label": "1984年（昭和59年）生まれ", "comment": "経験が活きる日。積み重ねが評価。"},
            {"label": "1996年（平成8年）生まれ", "comment": "新しい風が吹く日。直感を信じて。"},
            {"label": "1965年（昭和40年）生まれ", "comment": "穏やかな日。お気に入りの場所で。"},
            {"label": "1973年（昭和48年）生まれ", "comment": "段取り上手な日。計画的に動こう。"},
            {"label": "2008年（平成20年）生まれ", "comment": "好奇心が冴える日。挑戦してみて。"},
            {"label": "1959年（昭和34年）生まれ", "comment": "頼られる1日。一言が背中を押す。"},
        ],
    }


def _dummy_template_data_saturday(spot: Spot) -> dict:
    """dry-run用の土曜（町TOP10）ダミー JSON データ
    comment は本番プロンプトと同じく各文18字以内・合計36字以内に厳守"""
    return {
        "intro_text": "土曜、土星の支配日。ラッキータウンTOP10を発表します。",
        "items": [
            {"label": "門前町", "comment": f"絶好調の予感。{spot.name} に寄ってみて。"},
            {"label": "諏訪", "comment": "穏やかな運気。ゆっくり過ごして吉。"},
            {"label": "国府町", "comment": "新しい出会いの予感。笑顔を忘れずに。"},
            {"label": "牛久保町", "comment": "進展がある日。焦らず一歩ずつ。"},
            {"label": "桜ヶ丘町", "comment": "創造力が冴える日。アイデアはメモ。"},
            {"label": "御油町", "comment": "身近な人と時間を。心が満たされる。"},
            {"label": "為当町", "comment": "段取り上手な日。リスト片付けて。"},
            {"label": "三上町", "comment": "直感が冴える日。確かめてみて吉。"},
            {"label": "新道町", "comment": "頼られる1日。素直な気持ちで応えて。"},
            {"label": "千歳通", "comment": "ゆっくりペースでOK。リズム大切に。"},
        ],
    }


def _dummy_template_data_tuesday(spot: Spot) -> dict:
    """dry-run用の火曜（4血液型占い）ダミー JSON データ（10段階）
    comment は本番プロンプトと同じく各文18字以内・合計36字以内に厳守"""
    return {
        "intro_text": "今日は火曜、火星の支配日。血液型ランキングいきましょう。",
        "blood": {
            "A": {
                "stars": 8,
                "comment": "段取り上手な日。リスト片付けて。",
                "match": "O型 - ペース合わせてくれる相手",
                "action": "デスクまわりを片付ける",
                "caution": "完璧を求めすぎない",
            },
            "B": {
                "stars": 6,
                "comment": "マイペースが吉。リズム大切に。",
                "match": "AB型 - 違う角度から刺激の存在",
                "action": "いつもと違うランチを選ぶ",
                "caution": "周りに巻き込まれすぎない",
            },
            "O": {
                "stars": 10,
                "comment": f"絶好調の予感。{spot.name} に寄ってみて。",
                "match": "B型 - 笑顔が増える相手",
                "action": "会いたい人にLINEする",
                "caution": "お節介に注意",
            },
            "AB": {
                "stars": 7,
                "comment": "発想が冴える日。アイデアはメモ。",
                "match": "A型 - 落ち着きをくれる相手",
                "action": "本屋やカフェで一人時間",
                "caution": "考えすぎて動けなくならない",
            },
        },
    }


def _dummy_template_data_sunday(spot: Spot, target_date: date | None = None) -> dict:
    """dry-run用の日曜（週間総括）ダミー JSON データ
    target_date 指定時は入力シートから過去6日のスポットを実データで引く
    """
    spots_week = {}
    if target_date is not None:
        try:
            from select_lucky_spot import select_lucky_spot as _sel
            from datetime import timedelta as _td
            for i, key in enumerate(["mon", "tue", "wed", "thu", "fri", "sat"]):
                past_d = target_date - _td(days=6 - i)
                spots_week[key] = _sel(past_d).name
        except Exception:
            pass
    if not spots_week:
        spots_week = {
            "mon": "戸田のりショップ", "tue": "御油の松並木", "wed": "豊川稲荷門前",
            "thu": "桜トンネル", "fri": "ユニー豊川店", "sat": "イオンモール豊川",
        }
    return {
        "intro_text": "あっという間に1週間でしたね。日曜は太陽の支配日、ゆっくりと自分を労わるのにぴったりかも。",
        "spots_week": spots_week,
        "highlight_good_1": "木曜のいて座、ノリと勢いで動けてバッチリだった皆さん、お見事でした。",
        "highlight_good_2": "水曜の3月生まれ、創造力の冴える1日を満喫できたみたいです。",
        "highlight_tough_1": "火曜のB型、ペース乱れがちでお疲れ様でした。今日はゆっくり休んで。",
        "highlight_tough_2": "金曜の1959年生まれの皆さん、踏ん張りどころの1日でしたね。",
        "next_week_theme": "心の余裕",
        "next_week_message": "予定を詰め込みすぎず、ふと立ち止まれる隙間時間を意識してみると吉。意外な発見や偶然の出会いが、来週のあなたを支えてくれそうです。",
    }


def _dummy_template_data(weekday_key: str, target_date: date, spot: Spot) -> dict:
    if weekday_key == "mon":
        return _dummy_template_data_monday(spot)
    if weekday_key == "tue":
        return _dummy_template_data_tuesday(spot)
    if weekday_key == "wed":
        return _dummy_template_data_wednesday(spot)
    if weekday_key == "thu":
        return _dummy_template_data_thursday(spot)
    if weekday_key == "fri":
        return _dummy_template_data_friday(spot)
    if weekday_key == "sat":
        return _dummy_template_data_saturday(spot)
    if weekday_key == "sun":
        return _dummy_template_data_sunday(spot, target_date)
    return {"intro_text": "（dry-run）", "items": []}


def call_template_data_api(weekday_key: str, target_date: date, spot: Spot, extra: dict | None = None) -> dict:
    """Claude API でテンプレート用 JSON データを取得（実消費）"""
    system, user = _build_template_data_prompt(weekday_key, target_date, spot, extra)
    raw = call_claude_api(system, user)
    # JSONブロック抽出（```json ... ``` で包まれてても対応）
    raw_clean = raw.strip()
    if raw_clean.startswith("```"):
        raw_clean = re.sub(r"^```(?:json)?\s*", "", raw_clean)
        raw_clean = re.sub(r"\s*```$", "", raw_clean)
    return json.loads(raw_clean)


def fill_template(weekday_key: str, data: dict, target_date: date, spot: Spot) -> str:
    """テンプレートに data を流し込む（ランキング系曜日）"""
    weekday_full = {
        "mon": "monday", "tue": "tuesday", "wed": "wednesday",
        "thu": "thursday", "fri": "friday", "sat": "saturday", "sun": "sunday",
    }.get(weekday_key, weekday_key)
    template_path = TEMPLATES_DIR / f"template_{weekday_full}.html"
    if not template_path.exists():
        alt = TEMPLATES_DIR / f"template_{weekday_key}.html"
        if alt.exists():
            template_path = alt
        else:
            raise FileNotFoundError(f"template not found: {template_path}")
    template = template_path.read_text(encoding="utf-8")

    # intro_text 先頭の挨拶語（おはよう／こんにちは等）を自動除去
    intro = data.get("intro_text", "") or ""
    intro = re.sub(r"^(おはようございます|おはよう|こんにちは|こんばんは|やっほー)[、。！\s]*", "", intro)

    # ベータ期間（5/11〜5/17）はテスト配信中の注釈を冒頭に追加
    from datetime import date as _date
    beta_notice = ""
    if _date(2026, 5, 11) <= target_date <= _date(2026, 5, 17):
        beta_notice = (
            '<div style="background:#fff8e7; border-left:4px solid #d4a017; '
            'padding:14px 18px; margin:20px 0; border-radius:6px; font-size:0.95em;">'
            '📢 <strong>占いコーナーは現在テスト配信中です（〜5月17日）</strong><br>'
            '5月18日からの本格運用に向けて、皆さんの反応を見ながら調整中。'
            'お気付きの点があれば<a href="https://toyokawa-rentallife.com/inquiry/" '
            'target="_blank" rel="noopener noreferrer">お問い合わせ</a>からお気軽にどうぞ🙇'
            '</div>'
        )

    placeholders = {
        "{date_jp}": _format_date_jp(target_date),
        "{intro_text}": intro,
        "{spot_name}": spot.name,
        "{beta_notice}": beta_notice,
    }

    if weekday_key == "tue":
        # 火曜：血液型構造（A/B/O/AB）
        blood = data.get("blood", {})
        for key in ["A", "B", "O", "AB"]:
            b = blood.get(key, {})
            kl = key.lower()
            placeholders[f"{{blood_{kl}_stars}}"] = _format_stars(b.get("stars", 0))
            placeholders[f"{{blood_{kl}_comment}}"] = b.get("comment", "")
            placeholders[f"{{blood_{kl}_match}}"] = b.get("match", "")
            placeholders[f"{{blood_{kl}_action}}"] = b.get("action", "")
            placeholders[f"{{blood_{kl}_caution}}"] = b.get("caution", "")
    elif weekday_key == "sun":
        # 日曜：週間総括＋来週予告（来週のラッキースポット予告は削除済み）
        for key in ["highlight_good_1", "highlight_good_2",
                    "highlight_tough_1", "highlight_tough_2",
                    "next_week_theme", "next_week_message"]:
            placeholders[f"{{{key}}}"] = data.get(key, "")
        # spot_mon〜spot_sat（過去6日のラッキースポット名）+ date_mon〜date_sat（M/D形式）
        spots_week = data.get("spots_week", {})
        from datetime import timedelta as _td
        for i, key in enumerate(["mon", "tue", "wed", "thu", "fri", "sat"]):
            placeholders[f"{{spot_{key}}}"] = spots_week.get(key, "-")
            past_d = target_date - _td(days=6 - i)
            placeholders[f"{{date_{key}}}"] = f"{past_d.month}/{past_d.day}"
    elif weekday_key in ("fri", "sat"):
        # 金/土：TOP10（stars はアイキャッチと同じ get_top10_stars(seed) を使う）
        from uranai_fri_sat import get_top10_stars, format_star_score
        items = data.get("items", [])
        seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
        top10 = get_top10_stars(seed=seed)
        for i in range(10):
            item = items[i] if i < len(items) else {}
            placeholders[f"{{rank{i+1}_label}}"] = item.get("label", "-")
            placeholders[f"{{rank{i+1}_stars}}"] = format_star_score(top10[i])
            placeholders[f"{{rank{i+1}_comment}}"] = item.get("comment", "")
    else:
        # 月/水/木 共通：ランキング系（items 配列）
        items = data.get("items", [])
        # stars 降順で並び替え（stars 無し＝0扱いで原順保持）
        items_sorted = sorted(enumerate(items), key=lambda x: (-x[1].get("stars", 0), x[0]))
        items_sorted = [it for _, it in items_sorted]
        for i in range(12):
            item = items_sorted[i] if i < len(items_sorted) else {}
            placeholders[f"{{rank{i+1}_label}}"] = item.get("label", "-")
            placeholders[f"{{rank{i+1}_stars}}"] = _format_stars(item.get("stars", 0))
            placeholders[f"{{rank{i+1}_comment}}"] = item.get("comment", "")

    out = template
    for key, val in placeholders.items():
        out = out.replace(key, val)
    return out


def generate_uranai_article_template(
    *, target_date: date, weekday_key: str, spot: Spot, dry: bool = False,
    extra: dict | None = None
) -> dict:
    """テンプレート方式の記事生成

    Args:
        extra: 金/土の追加入力（{"years": [...]} / {"towns": [...]}）
    Returns: {"title", "wp_content", "items_for_image", "data"}
    """
    if dry:
        data = _dummy_template_data(weekday_key, target_date, spot)
    else:
        data = call_template_data_api(weekday_key, target_date, spot, extra)

    wp_content = fill_template(weekday_key, data, target_date, spot)

    items_for_image = []
    if weekday_key == "tue":
        # 火曜：blood 構造から ArticleItem 配列に変換（uranai_tuesday.py 互換）
        blood = data.get("blood", {})
        for i, key in enumerate(["A", "B", "O", "AB"]):
            b = blood.get(key, {})
            items_for_image.append(ArticleItem(
                rank=i + 1,
                label=f"【{key}型】",
                stars=b.get("stars", 0),
                comment=b.get("comment", ""),
                extras={"match": b.get("match", ""), "action": b.get("action", ""), "caution": b.get("caution", "")},
            ))
    else:
        # ランキング系：items 配列を ArticleItem に変換
        items_raw = data.get("items", [])

        if weekday_key in ("fri", "sat"):
            # 金/土はプロンプト側で順位確定済み・stars は seed ベースで別途生成
            # （caption.py 側と同じ get_top10_stars(seed) を使い、整合性を保つ）
            try:
                from uranai_fri_sat import get_top10_stars
                seed_v = target_date.year * 10000 + target_date.month * 100 + target_date.day
                top10_stars = get_top10_stars(seed=seed_v)
            except Exception:
                top10_stars = None
            for i, it in enumerate(items_raw):
                stars_val = it.get("stars")
                if not stars_val and top10_stars and i < len(top10_stars):
                    stars_val = top10_stars[i]
                items_for_image.append(ArticleItem(
                    rank=i + 1,
                    label=f"【{it.get('label', '-')}】",
                    stars=stars_val or 0,
                    comment=it.get("comment", ""),
                    extras={},
                ))
        else:
            # 月/水/木：stars 降順で並び替え＋rank 付与
            items_sorted = sorted(enumerate(items_raw), key=lambda x: (-x[1].get("stars", 0), x[0]))
            items_sorted = [it for _, it in items_sorted]
            for i, it in enumerate(items_sorted):
                items_for_image.append(ArticleItem(
                    rank=i + 1,
                    label=f"【{it.get('label', '-')}】",
                    stars=it.get("stars", 0),
                    comment=it.get("comment", ""),
                    extras={},
                ))

    # タイトルはテンプレ1行目（# 〜）を採用し、`# ` 接頭辞は除去
    first_line = wp_content.split("\n", 1)[0].strip()
    title = first_line[2:] if first_line.startswith("# ") else first_line

    return {
        "title": title,
        "wp_content": wp_content,
        "items_for_image": items_for_image,
        "data": data,
    }


# ============================================================
# dry-run 用の現実的なダミー応答（曜日別）
# ============================================================

ZODIAC = ["おひつじ", "おうし", "ふたご", "かに", "しし", "おとめ",
          "てんびん", "さそり", "いて", "やぎ", "みずがめ", "うお"]
BLOOD = ["A", "B", "O", "AB"]
ETO = [("子", "ねずみ"), ("丑", "うし"), ("寅", "とら"), ("卯", "うさぎ"),
       ("辰", "たつ"), ("巳", "へび"), ("午", "うま"), ("未", "ひつじ"),
       ("申", "さる"), ("酉", "とり"), ("戌", "いぬ"), ("亥", "いのしし")]


def _dummy_monday(target_date: date, spot: Spot) -> str:
    d = target_date
    lines = [
        f"# 【{d.year}年{d.month}月{d.day}日（月）】豊川ガイド的 今日の占い🔮全星座いっき見！",
        "",
        "おはようございます、豊川ガイドです🦊",
        "新しい1週間が始まりますね。今日は満月、感情が動きやすい日です。",
        "",
        f"## 🦊 本日のラッキースポット：【{spot.name}】" + (f"（{spot.area}）" if spot.area else ""),
        "",
        "## 🥇 第1位：【しし座】★★★★★",
        "オーラ全開。今日のあなた、ちょっと無敵かも。",
        "",
        "## 🥈 第2位：【おひつじ座】★★★★☆",
        "絶好調の予感。やりたいこと、ガンガン進めて。",
        f"{spot.name} に立ち寄れば、運気がさらに上がりそう。",
        "",
        "## 🥉 第3位：【いて座】★★★★☆",
        "ノリと勢いの日。考えるより先に、動いちゃおう。",
        "",
        "## 4位：【ふたご座】★★★★☆",
        "コミュニケーションが冴える日。連絡待ちの返事が来るかも。",
        "",
        "## 5位：【おうし座】★★★☆☆",
        "落ち着いて行動を。じっくり考える時間を大切に。",
        "",
        "## 6位：【おとめ座】★★★☆☆",
        "細部に気を配ると吉。完璧主義は控えめに。",
        "",
        "## 7位：【てんびん座】★★★☆☆",
        "バランス感覚が問われる日。判断は慎重に。",
        "",
        "## 8位：【やぎ座】★★★☆☆",
        "コツコツ続けていることに進展あり。",
        "",
        "## 9位：【みずがめ座】★★☆☆☆",
        "新しいアイデアより、既存の整理が吉。",
        "",
        "## 10位:【うお座】★★☆☆☆",
        "感情が揺れやすい日。深呼吸して。",
        "",
        "## 11位:【さそり座】★★☆☆☆",
        "情熱が空回りしがち。一旦休憩を。",
        "",
        "## 12位:【かに座】★★☆☆☆",
        "心配事は明日に持ち越さず、今日中に整理を。",
        "",
        "※ラッキースポットがお休みのときは、また別の日に行ってみてね！",
        "※管理人の独断と偏見でお届けする、ゆる〜い占いです",
        "",
        "明日の朝もお楽しみに！",
        "",
        "#豊川ガイド #豊川市 #今日の占い #星座占い",
    ]
    return "\n".join(lines)


def _dummy_tuesday(target_date: date, spot: Spot) -> str:
    d = target_date
    lines = [
        f"# 【{d.year}年{d.month}月{d.day}日（火）】豊川ガイド的 今日の占い🔮今日は血液型でいきます！",
        "",
        "今日は火曜・火星の日。エネルギー高めなので、思い切った行動が吉。",
        f"## 🦊 本日のラッキースポット：【{spot.name}】" + (f"（{spot.area}）" if spot.area else ""),
        "",
        "## 【A型】★★★★★",
        "完璧主義のあなたが今日は神。細かい仕事、サクサク片付きます。",
        "- 💝 今日の相性血液型: O型 - 大らかさが今日のあなたに必要",
        "- ✨ 今日のラッキーアクション: 朝イチでToDoリストを書き出す",
        "- ⚠️ 今日の注意点: 完璧を求めすぎず、6割でOKと割り切ろう",
        "",
        "## 【B型】★★★★☆",
        "マイペース全開でOKな日。周りに合わせず自分のリズムで。",
        "- 💝 今日の相性血液型: AB型 - 個性同士で良い化学反応",
        "- ✨ 今日のラッキーアクション: いつもと違う通勤ルートを試す",
        "- ⚠️ 今日の注意点: 約束の時間にはちゃんと間に合おう",
        "",
        "## 【O型】★★★☆☆",
        "穏やかな1日。社交的なあなたも今日はじっくり聞き役で。",
        "- 💝 今日の相性血液型: A型 - 細やかさに学ぼう",
        "- ✨ 今日のラッキーアクション: 久しぶりの友人にLINE",
        "- ⚠️ 今日の注意点: 大盤振る舞いは控えめに",
        "",
        "## 【AB型】★★★★☆",
        "二面性が良い方向に。柔軟な判断力で乗り切れます。",
        f"- 💝 今日の相性血液型: B型 - 感性が共鳴する日",
        f"- ✨ 今日のラッキーアクション: 【{spot.name}】に立ち寄って一息",
        "- ⚠️ 今日の注意点: 急な気分転換に注意",
        "",
        "## 相性・アクション・注意点はブログで→",
        "",
        "※管理人の独断と偏見でお届けする、ゆる〜い占いです",
        "明日の朝もお楽しみに！",
        "",
        "#豊川ガイド #豊川市 #今日の占い #血液型占い",
    ]
    return "\n".join(lines)


def _dummy_generic(target_date: date, weekday_key: str, spot: Spot) -> str:
    """水・木・金・土・日のダミー（生成構造のみ）"""
    d = target_date
    weekday_jp = WEEKDAY_JP[d.weekday()]
    theme_map = {
        "wed": "今日は誕生月でいきます！",
        "thu": "今日は干支でいきます！",
        "fri": "今日のラッキー生まれ年TOP10！🎂",
        "sat": "今日のラッキータウンはこちら！🏘️🎉",
        "sun": "今週占いまとめ&来週の運勢🔮",
    }
    # 金・土は本番ロジックで実データ取得（社長指示「ちゃんと本番のごとく選んで」）
    fri_units = []
    sat_units = []
    try:
        from load_groups import load_birthyear_for_date, load_town_for_date
        fri_years = load_birthyear_for_date(target_date)
        sat_towns = load_town_for_date(target_date)
        fri_units = [f"【{y['生まれ年']}（{y['和暦']}）生まれ】" for y in fri_years]
        sat_units = [f"【{t['町名']}】" for t in sat_towns]
    except Exception:
        # フォールバック（xlsx読込失敗時）
        fri_units = [f"【1990年（平成2年）生まれ】"] * 10
        sat_units = [f"【豊川町】", f"【諏訪】", f"【八幡町】",
                     f"【国府町】", f"【牛久保町】", f"【桜ヶ丘町】",
                     f"【御油町】", f"【為当町】", f"【新道町】", f"【千歳通】"]

    # 干支・誕生月もシードベースでシャッフル（社長指示「ちゃんとランダムに」）
    import random as _rnd
    _seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
    _eto_shuffled = list(ETO)
    _rnd.Random(_seed).shuffle(_eto_shuffled)
    _months_shuffled = list(range(1, 13))
    _rnd.Random(_seed + 1).shuffle(_months_shuffled)

    units_map = {
        "wed": [f"【{m}月生まれ】" for m in _months_shuffled],
        "thu": [f"【{kanji}（{kana}）年】" for kanji, kana in _eto_shuffled],
        "fri": fri_units,
        "sat": sat_units,
        "sun": [],
    }
    title = f"【{d.year}年{d.month}月{d.day}日（{weekday_jp}）】豊川ガイド的 {theme_map[weekday_key]}"

    lines = [f"# {title}", ""]
    lines.append(f"## 🦊 本日のラッキースポット：【{spot.name}】" + (f"（{spot.area}）" if spot.area else ""))
    lines.append("")

    if weekday_key == "sun":
        lines.extend([
            "## 今週のおさらい",
            "月曜：しし座が1位！",
            "火曜：A型が好調でした",
            "...",
            "",
            "## 来週のテーマ：人とのつながり",
            "金曜・金星の日に思い切って動いてみて。",
            "",
        ])
    else:
        units = units_map[weekday_key]
        ranks_emoji = ["🥇 第1位", "🥈 第2位", "🥉 第3位"] + [f"{i}位" for i in range(4, 13)]
        for i, unit in enumerate(units):
            stars = max(2, 5 - (i // 3))  # ★5から徐々に下がる
            lines.append(f"## {ranks_emoji[i]}：{unit}{'★' * stars}{'☆' * (5 - stars)}")
            if i == 0:
                lines.append(f"今日のあなた、絶好調！{spot.name} に立ち寄ると運気アップ。")
            elif i == 1:
                lines.append("良いことが起こりそうな予感です。チャンスを掴んで。")
            else:
                lines.append("いつも通りの一日。マイペースを大切に。")
            lines.append("")

    lines.extend([
        "※管理人の独断と偏見でお届けする、ゆる〜い占いです",
        "明日の朝もお楽しみに！",
        "",
        f"#豊川ガイド #豊川市 #今日の占い",
    ])
    return "\n".join(lines)


def dummy_claude_response(weekday_key: str, target_date: date, spot: Spot) -> str:
    """dry-run 用ダミー応答（曜日別）"""
    if weekday_key == "mon":
        return _dummy_monday(target_date, spot)
    if weekday_key == "tue":
        return _dummy_tuesday(target_date, spot)
    return _dummy_generic(target_date, weekday_key, spot)


# ============================================================
# Claude 応答の構造化抽出
# ============================================================

@dataclass
class ArticleItem:
    rank: int | None  # 1-10 / None なら個別ランク無し
    label: str        # 【しし座】 / 【A型】 / 【1990年（平成2年）生まれ】
    stars: int        # 0-5
    comment: str      # メインコメント
    extras: dict = field(default_factory=dict)  # 火曜の相性等


def _count_stars(text: str) -> int:
    """文字列中の★の数をカウント（最大5）"""
    return min(text.count("★"), 5)


def _extract_label(heading: str, weekday_key: str | None = None) -> str | None:
    """見出しから単位名を抽出（【...】優先・なければ曜日別キーワード検出）"""
    m = re.search(r"【([^】]+)】", heading)
    if m:
        return m.group(0)
    # フォールバック：曜日別キーワード検出
    KEYWORDS = {
        "mon": ["おひつじ座", "おうし座", "ふたご座", "かに座", "しし座", "おとめ座",
                "てんびん座", "さそり座", "いて座", "やぎ座", "みずがめ座", "うお座"],
        "tue": ["A型", "B型", "O型", "AB型"],
        "wed": [f"{m}月生まれ" for m in range(1, 13)],
        "thu": ["子年", "丑年", "寅年", "卯年", "辰年", "巳年",
                "午年", "未年", "申年", "酉年", "戌年", "亥年",
                "子（", "丑（", "寅（", "卯（", "辰（", "巳（",
                "午（", "未（", "申（", "酉（", "戌（", "亥（",
                "ねずみ", "うし", "とら", "うさぎ", "たつ", "へび",
                "うま", "ひつじ", "さる", "とり", "いぬ", "いのしし"],
    }
    if weekday_key and weekday_key in KEYWORDS:
        for kw in KEYWORDS[weekday_key]:
            if kw in heading:
                # 「kw」を【】で囲んで返す
                # ただし kw に「（」が入っている場合は手前まで（例: 「子（」→「子年」相当）
                clean = kw.rstrip("（")
                if not clean.endswith(("座", "型", "生まれ", "年")):
                    if weekday_key == "thu":
                        clean = clean + "年"
                return f"【{clean}】"
    return None


def parse_article_response(raw: str, weekday_key: str) -> dict:
    """Claude 応答から構造化抽出

    Returns:
        {
          "title": str,
          "items": list[ArticleItem],
          "lucky_spot_line": str,
        }
    """
    lines = raw.split("\n")

    # タイトル：先頭の "# " で始まる行
    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # ラッキースポット行（## 🦊 本日のラッキースポット...）
    lucky_spot_line = ""
    for line in lines:
        if "本日のラッキースポット" in line or "ラッキースポット" in line and line.startswith("##"):
            lucky_spot_line = line.lstrip("# ").strip()
            break

    # 各占い項目を抽出（## で始まる占いセクション）
    items: list[ArticleItem] = []
    current_heading = None
    current_lines = []

    def flush():
        nonlocal current_heading, current_lines
        if current_heading is None:
            current_lines = []
            return
        # 見出しから rank を抽出
        rank_match = re.search(r"(?:🥇|🥈|🥉|第)?(\d+)位|🥇|🥈|🥉", current_heading)
        rank = None
        if "🥇" in current_heading:
            rank = 1
        elif "🥈" in current_heading:
            rank = 2
        elif "🥉" in current_heading:
            rank = 3
        elif rank_match and rank_match.group(1):
            rank = int(rank_match.group(1))

        label = _extract_label(current_heading, weekday_key)
        if not label:
            current_heading = None
            current_lines = []
            return

        stars = _count_stars(current_heading)
        # 見出しから取れなかったら本文から★を探す（実APIは本文に書く傾向）
        if stars == 0:
            for ln in current_lines:
                cnt = _count_stars(ln)
                if cnt > 0:
                    stars = cnt
                    break
        # 本文（最初の非空行）：メタ行（総合運/恋愛運/★だけの行/サブ見出し）はスキップ
        META_KEYWORDS = ("総合運", "恋愛運", "仕事運", "金運", "健康運", "対人運")
        body_lines = []
        for l in current_lines:
            t = l.strip()
            if not t:
                continue
            if any(kw in t for kw in META_KEYWORDS):
                continue
            if t.startswith("**") and t.endswith("**") and any(kw in t for kw in META_KEYWORDS + ("：", ":")):
                continue
            if re.match(r"^[\*\s★☆\d/]+$", t):
                continue
            if t.startswith("- "):
                continue
            body_lines.append(t)
        comment = body_lines[0] if body_lines else ""

        # 火曜：相性・アクション・注意点を抽出
        extras = {}
        if weekday_key == "tue":
            for l in current_lines:
                if "💝" in l:
                    extras["compat"] = l.split(":", 1)[-1].strip(" 　")
                elif "✨" in l:
                    extras["action"] = l.split(":", 1)[-1].strip(" 　")
                elif "⚠️" in l:
                    extras["warning"] = l.split(":", 1)[-1].strip(" 　")

        items.append(ArticleItem(
            rank=rank, label=label, stars=stars,
            comment=comment, extras=extras,
        ))
        current_heading = None
        current_lines = []

    # 曜日別キーワード（柔軟検出用）
    UNIT_KEYWORDS = {
        "mon": ["座"],  # 「○○座」を含む見出し
        "tue": ["型"],  # 「A型」「B型」等
        "wed": ["月生まれ"],
        "thu": ["年", "（ねずみ）", "（うし）", "（とら）", "（うさぎ）",
                "（たつ）", "（へび）", "（うま）", "（ひつじ）",
                "（さる）", "（とり）", "（いぬ）", "（いのしし）"],
        "fri": ["生まれ", "年（", "西暦"],
        "sat": ["町", "区", "駅"],
    }
    weekday_kws = UNIT_KEYWORDS.get(weekday_key, [])

    def is_unit_heading(line: str) -> bool:
        """占いユニット見出しか判定"""
        if not line.startswith("## "):
            return False
        if "ラッキースポット" in line:
            return False
        # 既存条件
        if "【" in line or "🥇" in line or "🥈" in line or "🥉" in line:
            return True
        if re.search(r"\d+位", line):
            return True
        # 曜日別キーワードによる柔軟検出
        for kw in weekday_kws:
            if kw in line:
                return True
        return False

    for line in lines:
        if is_unit_heading(line):
            flush()
            current_heading = line
            current_lines = []
        elif current_heading:
            current_lines.append(line)
    flush()

    return {
        "title": title,
        "items": items,
        "lucky_spot_line": lucky_spot_line,
    }


# ============================================================
# SNS リライト（Phase 2 着手時に実装）
# ============================================================

def rewrite_for_x(wp_content: str, weekday_key: str,
                 target_date: date, spot: Spot, dry: bool = False) -> str:
    """X 用 140字テキスト生成"""
    if dry:
        wd_jp = WEEKDAY_JP[target_date.weekday()]
        return f"""【豊川ガイド的 今日の占い🔮{target_date.month}/{target_date.day}({wd_jp})】
TOP3はブログで！
🦊本日のラッキースポット
【{spot.name}】
https://toyokawa-rentallife.com/uranai/
#豊川ガイド #豊川市 #今日の占い"""
    # TODO: 実 API でリライト
    rewriter_prompt = load_prompt("rewriters/x_rewriter.txt")
    user = f"# 元記事\n{wp_content}\n\n{rewriter_prompt}"
    return call_claude_api("あなたは豊川ガイドのSNS担当です。", user)


def rewrite_for_threads(wp_content: str, weekday_key: str,
                       target_date: date, spot: Spot, dry: bool = False) -> str:
    """Threads 用 500字テキスト生成"""
    if dry:
        wd_jp = WEEKDAY_JP[target_date.weekday()]
        return f"""【豊川ガイド的 今日の占い🔮{target_date.month}/{target_date.day}({wd_jp})】

TOP5
🥇しし座 ★5
🥈おひつじ座 ★4
🥉いて座 ★4
4位 ふたご座 ★4
5位 おうし座 ★3

🦊本日のラッキースポット
【{spot.name}】
{spot.area or ''}

詳しくはブログで→
https://toyokawa-rentallife.com/uranai/

#豊川ガイド #豊川市 #今日の占い #星座占い"""
    rewriter_prompt = load_prompt("rewriters/threads_rewriter.txt")
    user = f"# 元記事\n{wp_content}\n\n{rewriter_prompt}"
    return call_claude_api("あなたは豊川ガイドのSNS担当です。", user)


def rewrite_for_instagram(wp_content: str, weekday_key: str,
                         target_date: date, spot: Spot, dry: bool = False) -> str:
    """Instagram キャプション生成"""
    if dry:
        return f"""🔮 豊川ガイド的 今日の占い

TOP3
🥇 しし座 ★5
🥈 おひつじ座 ★4
🥉 いて座 ★4

🦊 本日のラッキースポット
【{spot.name}】

全部の運勢はプロフィールのリンクから✨

#豊川ガイド #豊川市 #今日の占い #ご当地占い"""
    rewriter_prompt = load_prompt("rewriters/instagram_rewriter.txt")
    user = f"# 元記事\n{wp_content}\n\n{rewriter_prompt}"
    return call_claude_api("あなたは豊川ガイドのSNS担当です。", user)


# ============================================================
# メインエントリ
# ============================================================

def generate_uranai_article(
    *,
    target_date: date,
    weekday_key: str,
    spot: Spot,
    extra: dict | None = None,
    dry: bool = False,
) -> dict:
    """占い記事を生成・構造化抽出付き

    Returns:
        {
          "title", "wp_content", "raw_response",
          "items": [ArticleItem, ...],
          "lucky_spot_line",
          "x_text", "threads_text", "instagram_caption",
        }
    """
    system = build_system_prompt(target_date)
    user = build_user_prompt(
        weekday_key=weekday_key,
        target_date=target_date,
        spot=spot,
        extra=extra,
    )

    if dry:
        raw = dummy_claude_response(weekday_key, target_date, spot)
    else:
        raw = call_claude_api(system, user)

    # 構造化抽出
    parsed = parse_article_response(raw, weekday_key)

    # ランキング系曜日（月/水/木）は stars 降順で並び替え＋順位付与＋wp_content再構築
    items = parsed["items"]
    wp_content = raw
    if weekday_key in ("mon", "wed", "thu") and items:
        items = sorted(items, key=lambda x: -x.stars)
        for i, it in enumerate(items):
            it.rank = i + 1
        wp_content = _rebuild_wp_content_ranked(raw, items)

    # SNS リライト（並び替え後本文を渡す）
    x_text = rewrite_for_x(wp_content, weekday_key, target_date, spot, dry=dry)
    threads_text = rewrite_for_threads(wp_content, weekday_key, target_date, spot, dry=dry)
    instagram_caption = rewrite_for_instagram(wp_content, weekday_key, target_date, spot, dry=dry)

    return {
        "title": parsed["title"] or "豊川ガイド的 今日の占い",
        "wp_content": wp_content,
        "raw_response": raw,
        "items": items,
        "lucky_spot_line": parsed["lucky_spot_line"],
        "x_text": x_text,
        "threads_text": threads_text,
        "instagram_caption": instagram_caption,
    }


def _rebuild_wp_content_ranked(raw, items_sorted):
    rank_emoji = {1: "🥇 第1位", 2: "🥈 第2位", 3: "🥉 第3位"}
    HEADER_NOTE_PATTERNS = [r"^※この占い", r"^※管理人"]
    SPOT_NOTE_PATTERNS = [r"^※ラッキースポット"]
    END_NOTE_PATTERNS = [r"^明日の朝も", r"^それでは", r"^明日も6時", r"^明日も[0-9０-９]+時"]

    def classify_notes(section):
        lines = section.split(chr(10))
        keep, hn, sn, en = [], [], [], []
        for ln in lines:
            s = ln.strip()
            if any(re.match(p, s) for p in HEADER_NOTE_PATTERNS):
                hn.append(s)
            elif any(re.match(p, s) for p in SPOT_NOTE_PATTERNS):
                sn.append(s)
            elif any(re.match(p, s) for p in END_NOTE_PATTERNS):
                en.append(s)
            else:
                keep.append(ln)
        return chr(10).join(keep), hn, sn, en

    META_KEYWORDS = ("総合運", "恋愛運", "仕事運", "金運", "健康運", "対人運")

    def remove_meta_subheadings(section):
        lines = section.split(chr(10))
        keep = []
        for ln in lines:
            s = ln.strip()
            if s.startswith("**") and s.endswith("**") and any(kw in s for kw in META_KEYWORDS):
                continue
            keep.append(ln)
        return chr(10).join(keep)

    def compact_section(section):
        """各セクションのコメント段落を最大2段落に圧縮（読みやすく）"""
        lines = section.split(chr(10))
        if not lines:
            return section
        heading = lines[0]
        body_lines = lines[1:]
        # 段落（空行区切り）でグループ化
        paragraphs = []
        current = []
        for ln in body_lines:
            if ln.strip():
                current.append(ln)
            else:
                if current:
                    paragraphs.append(current)
                    current = []
        if current:
            paragraphs.append(current)
        # 最初の2段落だけ採用（不要な段落をカット・段落間の空行は入れず連続表示）
        kept = paragraphs[:2]
        out = [heading]
        for para in kept:
            out.extend(para)
        return chr(10).join(out)

    raw_clean, hn_all, sn_all, en_all = classify_notes(raw)
    sections = re.split(r"(?=^## )", raw_clean, flags=re.MULTILINE)
    header = sections[0]
    body_sections = sections[1:]

    unit_sections = []
    spot_section = None
    other_post = []

    for s in body_sections:
        first_line = s.split(chr(10), 1)[0]
        cleaned, hn, sn, en = classify_notes(s)
        hn_all.extend(hn); sn_all.extend(sn); en_all.extend(en)
        is_spot = ("ラッキースポット" in first_line) and ("募集" not in first_line)
        if is_spot:
            spot_section = cleaned
            continue
        if "募集" in first_line:
            other_post.append(cleaned)
            continue
        matched_label = None
        for it in items_sorted:
            core = it.label.strip("【】")
            if core in first_line:
                matched_label = it.label
                break
        if matched_label:
            cleaned = remove_meta_subheadings(cleaned)
            cleaned = compact_section(cleaned)
            unit_sections.append((matched_label, cleaned))
        else:
            other_post.append(cleaned)

    ordered_units = []
    for it in items_sorted:
        for label, s in unit_sections:
            if label == it.label:
                lines = s.split(chr(10))
                rank_label = rank_emoji.get(it.rank, str(it.rank) + "位")
                stars = "★" * it.stars + "☆" * (5 - it.stars)
                lines[0] = "## " + rank_label + "：" + it.label + stars
                ordered_units.append(chr(10).join(lines))
                break

    def dedup(lst):
        seen, out = set(), []
        for x in lst:
            if x and x not in seen:
                seen.add(x); out.append(x)
        return out

    hn_all, sn_all, en_all = dedup(hn_all), dedup(sn_all), dedup(en_all)

    NL = chr(10)
    result = header.rstrip() + NL + NL
    if hn_all:
        result += NL.join(hn_all) + NL + NL
    if spot_section:
        result += spot_section.rstrip() + NL + NL
        if sn_all:
            result += NL.join(sn_all) + NL + NL
    # 各順位セクション間に改行2つ・末尾も改行2つ
    result += (NL + NL).join(u.rstrip() for u in ordered_units) + NL + NL
    if en_all:
        result += NL.join(en_all) + NL + NL
    result += "".join(other_post)
    return result


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="対象日 YYYY-MM-DD")
    parser.add_argument("--weekday", choices=WEEKDAY_KEYS, help="曜日キー")
    parser.add_argument("--dry", action="store_true", help="dry-run")
    parser.add_argument("--show-prompt", action="store_true", help="プロンプトのみ表示")
    args = parser.parse_args()

    target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    weekday_key = args.weekday or WEEKDAY_KEYS[target_date.weekday()]

    from select_lucky_spot import select_lucky_spot
    spot = select_lucky_spot(target_date)

    if args.show_prompt:
        print("=== SYSTEM PROMPT ===")
        print(build_system_prompt(target_date))
        print("\n=== USER PROMPT ===")
        print(build_user_prompt(weekday_key=weekday_key, target_date=target_date, spot=spot))
        return

    print(f"\n=== 占い記事生成: {target_date} ({WEEKDAY_JP[target_date.weekday()]}) ===")
    print(f"ラッキースポット: {spot.name} (tier={spot.tier})")
    print(f"weekday_key: {weekday_key} / dry-run: {args.dry}")

    article = generate_uranai_article(
        target_date=target_date,
        weekday_key=weekday_key,
        spot=spot,
        dry=args.dry,
    )

    print(f"\n--- title ---")
    print(article["title"])
    print(f"\n--- lucky_spot_line ---")
    print(article["lucky_spot_line"])
    print(f"\n--- items ({len(article['items'])}件) ---")
    for it in article["items"][:5]:
        print(f"  rank={it.rank} stars={it.stars} {it.label}: {it.comment[:40]}")
        if it.extras:
            print(f"    extras: {it.extras}")
    if len(article["items"]) > 5:
        print(f"  ... 他 {len(article['items']) - 5} 件")
    print(f"\n--- x_text ({len(article['x_text'])}字) ---")
    print(article["x_text"][:200])
    print(f"\n--- threads_text ({len(article['threads_text'])}字) ---")
    print(article["threads_text"][:300])
    print(f"\n--- instagram_caption ({len(article['instagram_caption'])}字) ---")
    print(article["instagram_caption"][:300])
    print(f"\n--- wp_content ({len(article['wp_content'])}字) ---")
    print(article["wp_content"][:300])


if __name__ == "__main__":
    main()
