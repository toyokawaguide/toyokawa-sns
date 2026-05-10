"""
元号換算ユーティリティ（02仕様書 §金曜）
==========================================

西暦 ↔ 和暦 の変換。
昭和→平成→令和の境界年（1989・2019）は両元号併記。

【公開関数】
- to_wareki(year) -> str
- to_wareki_combined(year) -> str  # 両元号併記対応版

【元号換算表（02仕様書より）】
- 昭和：1926年〜1989年（昭和64年/1月7日まで）
- 平成：1989年（平成元年/1月8日）〜2019年（平成31年/4月30日）
- 令和：2019年（令和元年/5月1日）〜
"""
from __future__ import annotations


def to_wareki(year: int) -> str:
    """通常年の和暦を返す（境界年は1元号のみ・主元号で）

    例:
        1990 → "平成2年"
        1976 → "昭和51年"
        2020 → "令和2年"
        1989 → "昭和64年"  # 境界年は to_wareki_combined を使うのが推奨
        2019 → "平成31年"
    """
    if 1926 <= year <= 1989:
        return f"昭和{year - 1925}年"
    if 1990 <= year <= 2018:
        return f"平成{year - 1988}年"
    if year == 1989:
        return "昭和64年"  # ほぼ昭和扱い
    if year == 2019:
        return "平成31年"  # ほぼ平成扱い
    if year >= 2019:
        return f"令和{year - 2018}年"
    raise ValueError(f"unsupported year: {year}（昭和元年=1926以前は未対応）")


def to_wareki_combined(year: int) -> str:
    """境界年は両元号併記（02仕様書 §金曜「元号換算ルール」厳守版）

    例:
        1990 → "平成2年"
        1976 → "昭和51年"
        2020 → "令和2年"
        1989 → "昭和64年/平成元年"  # 境界年
        2019 → "平成31年/令和元年"  # 境界年
    """
    if year == 1989:
        return "昭和64年/平成元年"
    if year == 2019:
        return "平成31年/令和元年"
    return to_wareki(year)


def format_birthyear(year: int) -> str:
    """記事用フォーマット「YYYY年（和暦）生まれ」"""
    return f"{year}年（{to_wareki_combined(year)}）生まれ"


# ============================================================
# 単体テスト
# ============================================================

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    test_cases = [
        # (year, expected_combined, expected_format)
        (1950, "昭和25年", "1950年（昭和25年）生まれ"),
        (1976, "昭和51年", "1976年（昭和51年）生まれ"),
        (1988, "昭和63年", "1988年（昭和63年）生まれ"),
        (1989, "昭和64年/平成元年", "1989年（昭和64年/平成元年）生まれ"),
        (1990, "平成2年", "1990年（平成2年）生まれ"),
        (2018, "平成30年", "2018年（平成30年）生まれ"),
        (2019, "平成31年/令和元年", "2019年（平成31年/令和元年）生まれ"),
        (2020, "令和2年", "2020年（令和2年）生まれ"),
        (2025, "令和7年", "2025年（令和7年）生まれ"),
    ]
    print("=== 元号換算テスト ===\n")
    pass_count = 0
    for year, expected_w, expected_f in test_cases:
        w = to_wareki_combined(year)
        f = format_birthyear(year)
        ok = (w == expected_w) and (f == expected_f)
        mark = "✅" if ok else "❌"
        if ok:
            pass_count += 1
        print(f"{mark} {year}: {w}  →  {f}")
        if not ok:
            print(f"   expected: {expected_w} / {expected_f}")
    print(f"\n結果: {pass_count}/{len(test_cases)} 件 PASS")
