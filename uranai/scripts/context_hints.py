"""
占い文脈ヒント生成（曜日支配星 + 月相）
==========================================

03_占いロジック仕様書 を実装。
generate_text.py で Claude API のシステムプロンプトに注入する。

依存ライブラリ：標準ライブラリのみ（datetime）。
コストゼロ・ライブラリインストール不要。

【公開関数】
- get_planetary_ruler(target_date) -> dict
- get_moon_phase(target_date) -> dict
- build_context_hints(target_date) -> str
"""
from __future__ import annotations
from datetime import date, datetime, timedelta


# ============================================================
# 曜日支配星
# ============================================================

PLANETARY_RULERS = [
    {"name": "月曜", "planet": "月",   "theme": "感情・直感・家庭・癒し",   "badge": "🌙 月の日"},
    {"name": "火曜", "planet": "火星", "theme": "行動・情熱・闘志",         "badge": "♂ 火星の日"},
    {"name": "水曜", "planet": "水星", "theme": "知性・コミュニケーション", "badge": "☿ 水星の日"},
    {"name": "木曜", "planet": "木星", "theme": "拡大・幸運・寛容",         "badge": "♃ 木星の日"},
    {"name": "金曜", "planet": "金星", "theme": "愛・美・お金",             "badge": "♀ 金星の日"},
    {"name": "土曜", "planet": "土星", "theme": "安定・忍耐・責任",         "badge": "♄ 土星の日"},
    {"name": "日曜", "planet": "太陽", "theme": "自己表現・活力・リセット", "badge": "☉ 太陽の日"},
]


def get_planetary_ruler(target_date: date) -> dict:
    """日付から曜日支配星情報を返す"""
    return PLANETARY_RULERS[target_date.weekday()]


# ============================================================
# 月相計算
# ============================================================

# 基準点：2000年1月6日 18:14 UTC = 新月（既知）
KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14)
LUNAR_CYCLE_DAYS = 29.53059

MOON_PHASES = [
    {"index": 0, "emoji": "🌑", "name": "新月期",     "theme": "始まり・新しい挑戦"},
    {"index": 1, "emoji": "🌒", "name": "三日月の頃", "theme": "育成・準備"},
    {"index": 2, "emoji": "🌓", "name": "上弦の頃",   "theme": "決断・行動"},
    {"index": 3, "emoji": "🌔", "name": "十三夜月の頃", "theme": "調整・前進"},
    {"index": 4, "emoji": "🌕", "name": "満月期",     "theme": "達成・解放・感情の高まり"},
    {"index": 5, "emoji": "🌖", "name": "居待月の頃", "theme": "振り返り・感謝"},
    {"index": 6, "emoji": "🌗", "name": "下弦の頃",   "theme": "整理・手放し"},
    {"index": 7, "emoji": "🌘", "name": "二十六夜月の頃", "theme": "浄化・休息"},
]


def get_moon_phase(target_date) -> dict:
    """月相を返す（0:新月 〜 7:二十六夜月）"""
    if isinstance(target_date, date) and not isinstance(target_date, datetime):
        target_dt = datetime(target_date.year, target_date.month, target_date.day, 12)
    else:
        target_dt = target_date
    days_since = (target_dt - KNOWN_NEW_MOON).total_seconds() / 86400
    phase = (days_since % LUNAR_CYCLE_DAYS) / LUNAR_CYCLE_DAYS
    phase_index = int(phase * 8) % 8
    return MOON_PHASES[phase_index]


# ============================================================
# プロンプトに注入するヒント文生成
# ============================================================

def build_context_hints(target_date: date) -> str:
    """Claude API へのシステムプロンプトに注入する文脈ヒントを生成"""
    ruler = get_planetary_ruler(target_date)
    moon = get_moon_phase(target_date)
    return f"""## 今日の文脈ヒント（さりげなく活用）

- 曜日：{ruler["name"]}・{ruler["planet"]}支配
- 曜日テーマ：{ruler["theme"]}
- 月相：{moon["name"]}（{moon["emoji"]}）
- 月相テーマ：{moon["theme"]}

これらを「ガチ占星術じゃない、ゆる〜い占い」として文中に1〜2回さりげなく織り込んでください。
専門用語の解説や押し付けがましさはNG。"""


# ============================================================
# 単体テスト
# ============================================================

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    # サンプル日付で動作確認
    samples = [
        date(2026, 5, 4),   # 月曜
        date(2026, 5, 11),  # 月曜
        date(2026, 5, 18),  # 月曜
        date(2026, 5, 22),  # 金曜
    ]
    for d in samples:
        ruler = get_planetary_ruler(d)
        moon = get_moon_phase(d)
        print(f"\n=== {d} ({ruler['name']}) ===")
        print(f"  支配星 : {ruler['planet']} {ruler['badge']}")
        print(f"  曜日テーマ: {ruler['theme']}")
        print(f"  月相    : {moon['emoji']} {moon['name']} ({moon['theme']})")
        print(f"\n  --- ヒント文 ---")
        print(build_context_hints(d))
