"""
占い配信用 画像生成（uranai_*.py ラッパー・v4・本物のサンプル準拠）
======================================================================

claude.ai で作成したサンプル画像を生成した uranai_*.py を呼び出す
シンプルなラッパー。既存の main.py / integration_test.py から
generate_image() で互換呼び出し可能。

【実装方針】
- 各曜日の uranai_*.py を import
- ArticleItem の list を各 uranai_*.py の引数形式に変換
- generate_image() 関数で曜日別ディスパッチ

【入力】
- target_date: date
- weekday_key: "mon" / "tue" / "wed" / "thu" / "fri" / "sat" / "sun"
- format: "ig" or "wp"
- spot_name, spot_area: ラッキースポット情報
- items: ArticleItem の list（generate_text.py 出力）
- past_week_spots: 日曜のみ・過去6日のスポット情報（list[dict]）

【出力】
- 占い/output/{date}_{weekday}_{format}.png
"""
from __future__ import annotations
import sys
import re
from pathlib import Path
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

# 各曜日の生成関数を import
from uranai_monday import generate_monday_instagram, generate_monday_wp
from uranai_tuesday import generate_tuesday_instagram, generate_tuesday_wp
from uranai_wed_thu import (
    generate_wednesday_instagram, generate_wednesday_wp,
    generate_thursday_instagram, generate_thursday_wp,
)
from uranai_fri_sat import (
    generate_friday_instagram, generate_friday_wp,
    generate_saturday_instagram, generate_saturday_wp,
)
from uranai_sunday import generate_sunday_instagram, generate_sunday_wp

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

# 火曜の血液型 → 色マッピング（README より）
BLOOD_COLORS = {
    "A": (255, 100, 100),
    "B": (255, 180, 80),
    "O": (100, 180, 100),
    "AB": (160, 130, 200),
}


# ============================================================
# ArticleItem → uranai_*.py 引数変換
# ============================================================

def _split_comment(comment: str, max_per_line: int = 22) -> tuple[str, str]:
    """コメントを2行に分割（各行 max_per_line 字以内・自然な文末で切る・「…」は使わない）"""
    if not comment:
        return "", ""
    if len(comment) <= max_per_line:
        return comment, ""

    # 句点（。！？）で文単位に分割
    sentences = [s.strip() for s in re.split(r"(?<=[。！？])", comment) if s.strip()]

    # ① 最初の文を c1 に（max_per_line 超なら 、 で再分割）
    c1 = sentences[0] if sentences else comment
    if len(c1) > max_per_line:
        sub = re.split(r"(?<=、)", c1)
        new_c1 = ""
        for p in sub:
            if len(new_c1) + len(p) <= max_per_line:
                new_c1 += p
            else:
                break
        if new_c1:
            c1 = new_c1
        else:
            c1 = sub[0][:max_per_line]

    # ② 残りから c2 構築（句点・読点で自然に切る・…なし）
    used = c1
    remaining = comment[len(used):].strip() if comment.startswith(used) else "".join(sentences[1:])

    if not remaining:
        return c1, ""

    # 句点単位で max_per_line に収まる範囲で c2 構築
    rem_sentences = [s.strip() for s in re.split(r"(?<=[。！？])", remaining) if s.strip()]
    c2 = ""
    for s in rem_sentences:
        if len(c2) + len(s) <= max_per_line:
            c2 += s
        else:
            break

    # 句点で取れなかったら 、 で
    if not c2 and rem_sentences:
        sub = re.split(r"(?<=、)", rem_sentences[0])
        for p in sub:
            if len(c2) + len(p) <= max_per_line:
                c2 += p
            else:
                break

    # それでも空なら冒頭から max_per_line（…なし）
    if not c2:
        c2 = remaining[:max_per_line]

    return c1, c2


def _strip_brackets(label: str) -> str:
    """【ラベル】→ ラベル / 【A型】→ A"""
    m = re.match(r"【(.+?)】", label)
    if m:
        return m.group(1)
    return label


def _to_top3_format(items: list, count: int = 3) -> list[dict]:
    """ArticleItem → 月/水/木 用 top3 形式
    rank未設定の実API応答時は stars 降順 + 出現順でフォールバック
    """
    if items and all(it.rank is None for it in items):
        ordered = sorted(enumerate(items), key=lambda x: (-x[1].stars, x[0]))
        sorted_items = [it for _, it in ordered][:count]
    else:
        sorted_items = sorted(items, key=lambda x: (x.rank or 99))[:count]
    result = []
    for item in sorted_items:
        c1, c2 = _split_comment(item.comment)
        # stars は 0-10 範囲で来る前提（×2は廃止・stars=5を10と同列にする順位逆転を防ぐ）
        filled = item.stars
        result.append({
            "name": item.label,
            "c1": c1,
            "c2": c2,
            "filled": min(filled, 10),
        })
    while len(result) < count:
        result.append({"name": "-", "c1": "", "c2": "", "filled": 0})
    return result


def _to_blood_format(items: list) -> dict:
    """ArticleItem → 火曜 用 blood 形式（uranai_tuesday.py は dict 形式期待）
    {"A": {"c1": ..., "c2": ..., "stars": ...}, ...}
    stars は 0-5 ならx2 / 6-10 ならそのまま（10段階に正規化）
    """
    result = {"A": {"c1": "", "c2": "", "stars": 0},
              "B": {"c1": "", "c2": "", "stars": 0},
              "O": {"c1": "", "c2": "", "stars": 0},
              "AB": {"c1": "", "c2": "", "stars": 0}}
    for item in items[:4]:
        type_str = _strip_brackets(item.label).replace("型", "").strip()
        if type_str not in result:
            continue
        c1, c2 = _split_comment(item.comment)
        # stars は 0-10 範囲で来る前提（×2廃止）
        filled = min(item.stars, 10)
        result[type_str] = {"c1": c1, "c2": c2, "stars": filled}
    return result


def _to_year_list(items: list, count: int = 10) -> list[str]:
    """ArticleItem → 金曜用 生まれ年文字列リスト"""
    # 「【1990年（平成2年）生まれ】」 → 「1990年（平成2）」
    sorted_items = sorted(items, key=lambda x: (x.rank or 99))[:count]
    result = []
    for item in sorted_items:
        text = _strip_brackets(item.label)
        text = text.replace("生まれ", "").strip()
        # 「年）」を 「）」 に短縮
        text = text.replace("年）", "）").replace("年)", ")")
        result.append(text)
    while len(result) < count:
        result.append("-")
    return result


def _to_town_list(items: list, count: int = 10) -> list[str]:
    """ArticleItem → 土曜用 町名文字列リスト"""
    sorted_items = sorted(items, key=lambda x: (x.rank or 99))[:count]
    result = []
    for item in sorted_items:
        text = _strip_brackets(item.label)
        result.append(text)
    while len(result) < count:
        result.append("-")
    return result


def _spot_dict(spot_name: str, spot_area: str) -> dict:
    """ラッキースポット情報を共通 dict 形式に"""
    return {"name": spot_name, "area": spot_area or ""}


# ============================================================
# 公開エントリポイント（既存 main.py / integration_test.py 互換）
# ============================================================

def generate_image(*, target_date: date, weekday_key: str, format: str,
                   spot_name: str, spot_area: str = "",
                   items: list | None = None,
                   output_path: Path | None = None,
                   past_week_spots: list[dict] | None = None) -> Path:
    """画像生成エントリポイント（uranai_*.py 経由・サンプル100%再現）

    Args:
        target_date: 配信対象日
        weekday_key: "mon" / "tue" / ... / "sun"
        format: "ig" or "wp"
        spot_name: ラッキースポット名
        spot_area: エリア
        items: ArticleItem の list
        output_path: 出力先（None なら自動命名）
        past_week_spots: 日曜のみ使用・過去6日スポット
    """
    items = items or []

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        output_path = OUTPUT_DIR / f"{target_date.isoformat()}_{weekday_key}_{format}.png"
    output_path = Path(output_path)

    spot = _spot_dict(spot_name, spot_area)

    if weekday_key == "mon":
        top3 = _to_top3_format(items)
        if format == "ig":
            generate_monday_instagram(target_date, top3, spot, str(output_path))
        else:
            generate_monday_wp(target_date, top3, spot, str(output_path))

    elif weekday_key == "tue":
        blood = _to_blood_format(items)
        if format == "ig":
            generate_tuesday_instagram(target_date, blood, spot, str(output_path))
        else:
            generate_tuesday_wp(target_date, blood, spot, str(output_path))

    elif weekday_key == "wed":
        top3 = _to_top3_format(items)
        if format == "ig":
            generate_wednesday_instagram(target_date, top3, spot, str(output_path))
        else:
            generate_wednesday_wp(target_date, top3, spot, str(output_path))

    elif weekday_key == "thu":
        top3 = _to_top3_format(items)
        if format == "ig":
            generate_thursday_instagram(target_date, top3, spot, str(output_path))
        else:
            generate_thursday_wp(target_date, top3, spot, str(output_path))

    elif weekday_key == "fri":
        years = _to_year_list(items)
        if format == "ig":
            generate_friday_instagram(target_date, years, spot, str(output_path))
        else:
            generate_friday_wp(target_date, years, spot, str(output_path))

    elif weekday_key == "sat":
        towns = _to_town_list(items)
        if format == "ig":
            generate_saturday_instagram(target_date, towns, spot, str(output_path))
        else:
            generate_saturday_wp(target_date, towns, spot, str(output_path))

    elif weekday_key == "sun":
        # 過去6日スポット（target_date が日曜想定・前6日 = 月〜土を取得）
        if past_week_spots is None or not past_week_spots:
            past_week_spots = []
            try:
                from datetime import timedelta
                from select_lucky_spot import select_lucky_spot as _select_spot
                day_labels = ["月", "火", "水", "木", "金", "土"]
                for i in range(6, 0, -1):
                    past_d = target_date - timedelta(days=i)
                    p_spot = _select_spot(past_d)
                    past_week_spots.append({
                        "day": day_labels[past_d.weekday()],
                        "name": p_spot.name
                    })
            except Exception:
                # フォールバック（select_lucky_spot失敗時）
                past_week_spots = [
                    {"day": "月", "name": "門前そば 山彦"},
                    {"day": "火", "name": "コメダ珈琲店"},
                    {"day": "水", "name": "ベーカリーすみ"},
                    {"day": "木", "name": "豊川稲荷"},
                    {"day": "金", "name": "御油の松並木"},
                    {"day": "土", "name": "赤塚山公園"},
                ]
        summary = {}  # 将来拡張用
        # 注意：uranai_sunday.py は (target_date, summary, lucky_spots_week, output_path) の順
        if format == "ig":
            generate_sunday_instagram(target_date, summary, past_week_spots, str(output_path))
        else:
            generate_sunday_wp(target_date, summary, past_week_spots, str(output_path))

    else:
        raise ValueError(f"unsupported weekday_key: {weekday_key}")

    # IG画像は 1080x1080 → 1080x1350 (4:5) に変換・上下に紺色帯
    if format == "ig":
        _finalize_ig_image(output_path, target_date)

    # WP画像は 1024x576 → 1920x1080 にアップスケール（X カード summary_large_image 対応）
    if format == "wp":
        _finalize_wp_image(output_path)

    return output_path


def _finalize_wp_image(path: Path) -> None:
    """1024x576 で生成されたWP画像を 1920x1080 にアップスケールする。

    X (Twitter) の summary_large_image カードは画像サイズが小さい（1024×576）と
    軽量カード扱いされてアイキャッチが表示されないことがあるため、推奨サイズに拡大。
    LANCZOS 補完で文字の劣化はほぼなし。
    """
    from PIL import Image

    try:
        src = Image.open(str(path))
    except Exception:
        return
    # 1024x576 以外（既に大きい・小さい）の場合はスキップ
    if src.size != (1024, 576):
        return
    upscaled = src.resize((1920, 1080), Image.LANCZOS)
    upscaled.save(str(path), optimize=True)


def _finalize_ig_image(path: Path, target_date: date) -> None:
    """1080x1080 IG画像を 1080x1350 (4:5) に変換し、上下に紺色帯を追加"""
    import os
    import platform
    from PIL import Image, ImageDraw, ImageFont

    try:
        src = Image.open(str(path))
    except Exception:
        return
    if src.size != (1080, 1080):
        return

    BLUE = (3, 58, 154)
    WHITE = (255, 255, 255)

    font_dir = os.environ.get("URANAI_FONT_DIR", "/usr/share/fonts/opentype/noto")
    if platform.system() == "Windows" and "Windows/Fonts" in font_dir.replace("\\", "/"):
        FB = f"{font_dir}/meiryob.ttc"
        FR = f"{font_dir}/meiryo.ttc"
    else:
        FB = f"{font_dir}/NotoSansCJK-Bold.ttc"
        FR = f"{font_dir}/NotoSansCJK-Regular.ttc"

    def f(p, s):
        try:
            return ImageFont.truetype(p, s)
        except Exception:
            return ImageFont.load_default()

    canvas = Image.new("RGB", (1080, 1350), BLUE)
    canvas.paste(src, (0, 135))
    d = ImageDraw.Draw(canvas)

    # === ヘッダー (上 135px) ===
    d.text((40, 25), "豊川ガイド", font=f(FB, 56), fill=WHITE)
    d.text((44, 95), "toyokawaguide", font=f(FR, 22), fill=WHITE)
    # 右：年月（2行）
    year_str = f"{target_date.year}年"
    month_str = f"{target_date.month:02d}月"
    yf = f(FB, 34)
    yb = d.textbbox((0, 0), year_str, font=yf)
    mb = d.textbbox((0, 0), month_str, font=yf)
    d.text((1080 - (yb[2] - yb[0]) - 40, 25), year_str, font=yf, fill=WHITE)
    d.text((1080 - (mb[2] - mb[0]) - 40, 75), month_str, font=yf, fill=WHITE)

    # === フッター (下 135px・y=1215〜1350) ===
    footer_y = 1215
    line1 = "▶ プロフィールリンクから"
    line2 = "トップの「今日の占い」コーナーへ"
    ff = f(FB, 30)
    for i, line in enumerate([line1, line2]):
        lb = d.textbbox((0, 0), line, font=ff)
        d.text(((1080 - (lb[2] - lb[0])) // 2, footer_y + 25 + i * 45), line, font=ff, fill=WHITE)

    canvas.save(str(path))


# ============================================================
# CLI（既存互換・dry-run用）
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="対象日 YYYY-MM-DD")
    parser.add_argument("--weekday", choices=["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
    parser.add_argument("--format", choices=["ig", "wp"], default="ig")
    parser.add_argument("--spot", default="（テストスポット）")
    parser.add_argument("--area", default="豊川市内")
    parser.add_argument("--out", help="出力先パス")
    args = parser.parse_args()

    from datetime import datetime
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    weekday_key = args.weekday or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][target_date.weekday()]

    out_path = generate_image(
        target_date=target_date,
        weekday_key=weekday_key,
        format=args.format,
        spot_name=args.spot,
        spot_area=args.area,
        items=[],
        output_path=Path(args.out) if args.out else None,
    )
    print(f"[OK] 画像生成: {out_path}")


if __name__ == "__main__":
    main()
