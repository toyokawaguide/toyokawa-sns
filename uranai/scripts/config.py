"""
占い配信システム 設定集約
============================

テスト運用フラグ・各種定数を1箇所に集約。
Phase 4 で「※テスト運用中」注釈の有無を切り替える。

【主要設定】
- IS_BETA: テスト運用中フラグ（True=注釈付与・WP下書き保存）
- WP_POST_STATUS: 投稿ステータス（draft/publish）
- BETA_NOTICE_END_DATE: テスト運用終了日（2026-05-17）
"""
from __future__ import annotations
import os
from datetime import date
from pathlib import Path

# ============================================================
# テスト運用 / 本配信 切替
# ============================================================

# テスト運用期間：2026-05-11 〜 2026-05-17
# 本配信開始：2026-05-18
# 切替方法：環境変数 URANAI_BETA=0 で本配信モード（注釈削除）
IS_BETA: bool = os.getenv("URANAI_BETA", "1") == "1"

BETA_START_DATE = date(2026, 5, 11)
BETA_END_DATE = date(2026, 5, 17)
PRODUCTION_START_DATE = date(2026, 5, 18)


# ============================================================
# WP投稿モード（テスト中は draft 推奨・社長確認後 publish）
# ============================================================

# B2モード（テスト運用中）：下書き保存→社長確認後に手動公開
# 環境変数 URANAI_AUTO_PUBLISH=1 で即時公開モード
WP_POST_STATUS: str = "publish" if os.getenv("URANAI_AUTO_PUBLISH", "0") == "1" else "draft"

# 本配信時は強制 publish
if not IS_BETA:
    WP_POST_STATUS = "publish"


# ============================================================
# パス・ファイル
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
ASSETS_DIR = ROOT / "assets"
SCRIPTS_DIR = ROOT / "scripts"
PROMPTS_DIR = SCRIPTS_DIR / "prompts"
LOGO_PATH = ASSETS_DIR / "logo.png"

LUCKY_XLSX = DATA_DIR / "ラッキースポット管理.xlsx"
BIRTHYEAR_XLSX = DATA_DIR / "生まれ年グループ.xlsx"
TOWN_XLSX = DATA_DIR / "町名グループ.xlsx"


# ============================================================
# Claude API（02仕様書）
# ============================================================

ANTHROPIC_MODEL = "claude-sonnet-4-5"  # コスパ最強モデル
ANTHROPIC_MAX_TOKENS = 4096
ANTHROPIC_TEMPERATURE = 0.7  # ゆる〜い占いの多様性


# ============================================================
# WP / SNS
# ============================================================

WP_CATEGORY_SLUG = "uranai"
SITE_URL = "https://toyokawa-rentallife.com"


# ============================================================
# 占い設定
# ============================================================

# 配信時刻（参考・cron設定で実装）
DISTRIBUTION_TIME_JST = "06:00"

# 社長指示シート（社長が事前指名・空欄ならフォールバック）
INPUT_SHEET = "ラッキースポット入力"
MASTER_SHEET = "マスタ"
LOG_SHEET = "配信ログ"


# ============================================================
# テスト運用注釈テンプレ
# ============================================================

def get_beta_notice_wp() -> str:
    """WP記事末尾に挿入するテスト運用注釈"""
    if not IS_BETA:
        return ""
    return (PROMPTS_DIR / "footer_beta_notice.md").read_text(encoding="utf-8")


def get_beta_notice_sns_short() -> str:
    """X/Threads/Instagram 末尾の簡易注釈"""
    if not IS_BETA:
        return ""
    return f"\n※{BETA_END_DATE.strftime('%-m/%-d').replace('-', '/')}までテスト運用中"


# ============================================================
# CLI（設定確認）
# ============================================================

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("=== 占い配信 設定確認 ===\n")
    print(f"IS_BETA           : {IS_BETA}")
    print(f"WP_POST_STATUS    : {WP_POST_STATUS}")
    print(f"BETA_START_DATE   : {BETA_START_DATE}")
    print(f"BETA_END_DATE     : {BETA_END_DATE}")
    print(f"PRODUCTION_START  : {PRODUCTION_START_DATE}")
    print(f"ANTHROPIC_MODEL   : {ANTHROPIC_MODEL}")
    print(f"WP_CATEGORY_SLUG  : {WP_CATEGORY_SLUG}")
    print(f"\n--- ファイルパス ---")
    print(f"LUCKY_XLSX        : {LUCKY_XLSX} (exists={LUCKY_XLSX.exists()})")
    print(f"BIRTHYEAR_XLSX    : {BIRTHYEAR_XLSX} (exists={BIRTHYEAR_XLSX.exists()})")
    print(f"TOWN_XLSX         : {TOWN_XLSX} (exists={TOWN_XLSX.exists()})")
    print(f"LOGO_PATH         : {LOGO_PATH} (exists={LOGO_PATH.exists()})")
    print(f"PROMPTS_DIR       : {PROMPTS_DIR} (exists={PROMPTS_DIR.exists()})")
