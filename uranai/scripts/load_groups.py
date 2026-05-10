"""
配信スケジュール（生まれ年・町名）の読み込み
================================================

毎週金曜（生まれ年TOP10）・毎週土曜（町TOP10）で使う 10年/10町を
配信スケジュールシートから week 番号で取得する。

【データソース】
- data/生まれ年グループ.xlsx の「配信スケジュール」シート
  カラム: 週 / 順番 / 生まれ年 / 和暦 / 備考
- data/町名グループ.xlsx の「配信スケジュール」シート
  カラム: 週 / 順番 / 町名 / カナ / 備考（想定）

【公開関数】
- load_birthyear_group(week_num) -> list[dict]   # 10年
- load_town_group(week_num) -> list[dict]        # 10町

【週番号の計算】
- 生まれ年: 8週周期（1〜8）
- 町名: 16週周期（1〜16）
- 配信開始日（2026-05-08 金曜・第1週）から経過した週数で計算
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date

import openpyxl

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
BIRTHYEAR_XLSX = ROOT / "data" / "生まれ年グループ.xlsx"
TOWN_XLSX = ROOT / "data" / "町名グループ.xlsx"
SHEET_NAME = "配信スケジュール"

# 配信開始日（第1週の金曜 / 土曜）
# テスト運用初週：2026-05-11 月〜2026-05-17 日
# 第1週の金曜 = 2026-05-15、第1週の土曜 = 2026-05-16
WEEK1_FRIDAY = date(2026, 5, 15)
WEEK1_SATURDAY = date(2026, 5, 16)


def get_week_number(target_date: date, *, weekday_kind: str) -> int:
    """target_date がどの週にあたるかを返す（1始まり）

    weekday_kind:
        "fri" → 金曜の週（生まれ年・8週周期）
        "sat" → 土曜の週（町名・16週周期）
    """
    if weekday_kind == "fri":
        base = WEEK1_FRIDAY
        cycle = 8
    elif weekday_kind == "sat":
        base = WEEK1_SATURDAY
        cycle = 16
    else:
        raise ValueError(f"unsupported weekday_kind: {weekday_kind}")

    days_diff = (target_date - base).days
    week_offset = days_diff // 7
    # 1始まり、cycle で循環
    return ((week_offset) % cycle) + 1


def _load_schedule(xlsx_path: Path, week_num: int) -> list[dict]:
    """配信スケジュールシートから week_num の行を抽出

    Returns:
        各行の dict（生 row データ）
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb[SHEET_NAME]
    rows = list(ws.iter_rows(values_only=True))
    # ヘッダーは行4 (index 3)。データは index 4 以降
    headers = rows[3]
    items = []
    for r in rows[4:]:
        if not r or r[0] is None:
            continue
        if r[0] == week_num:
            row_dict = {}
            for i, h in enumerate(headers):
                if h is None:
                    continue
                row_dict[str(h).strip()] = r[i] if i < len(r) else None
            items.append(row_dict)
    return items


def load_birthyear_group(week_num: int) -> list[dict]:
    """指定週の生まれ年10件を返す

    Returns:
        [{"順番": 1, "生まれ年": "1983年", "和暦": "昭和58年", "備考": ""}, ...]
        順番（2列目）でソート済
    """
    items = _load_schedule(BIRTHYEAR_XLSX, week_num)
    # 順番列でソート
    items.sort(key=lambda x: x.get("順番", 0) or 0)
    return items


def load_town_group(week_num: int) -> list[dict]:
    """指定週の町名10件を返す

    Returns:
        [{"順番": 1, "町名": "南大通", ...}, ...]
        順番（2列目）でソート済
    """
    items = _load_schedule(TOWN_XLSX, week_num)
    items.sort(key=lambda x: x.get("順番", 0) or 0)
    return items


def load_birthyear_for_date(target_date: date) -> list[dict]:
    """target_date（金曜想定）の生まれ年10件を返す"""
    week_num = get_week_number(target_date, weekday_kind="fri")
    return load_birthyear_group(week_num)


def load_town_for_date(target_date: date) -> list[dict]:
    """target_date（土曜想定）の町名10件を返す"""
    week_num = get_week_number(target_date, weekday_kind="sat")
    return load_town_group(week_num)


# ============================================================
# 単体テスト
# ============================================================

if __name__ == "__main__":
    print("=== 生まれ年グループ（第1週）===")
    items = load_birthyear_group(1)
    for r in items:
        print(f"  {r}")

    print(f"\n=== 町名グループ（第1週）===")
    items = load_town_group(1)
    for r in items:
        print(f"  {r}")

    # 日付指定でも確認
    print(f"\n=== 2026-05-15（金曜）の生まれ年（自動週判定） ===")
    items = load_birthyear_for_date(date(2026, 5, 15))
    print(f"  週番号: {get_week_number(date(2026, 5, 15), weekday_kind='fri')}")
    for r in items[:3]:
        print(f"  {r}")

    print(f"\n=== 2026-05-16（土曜）の町名（自動週判定） ===")
    items = load_town_for_date(date(2026, 5, 16))
    print(f"  週番号: {get_week_number(date(2026, 5, 16), weekday_kind='sat')}")
    for r in items[:3]:
        print(f"  {r}")
