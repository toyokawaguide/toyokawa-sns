"""
eyecatch_generator.py — ライト記事のアイキャッチ自動生成 v5
ベージュ帯＋元記事タイトル枠＋2カード横並び構成
"""
from __future__ import annotations
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

import os
import platform

ROOT = Path(__file__).resolve().parent
# scripts/ の1階層上に _assets/ を置く（toyokawa-sns/light_articles/_assets/）
ASSETS = ROOT.parent / "_assets" if (ROOT.parent / "_assets").exists() else ROOT / "_assets"
LOGO_PATH = ASSETS / "logo.png"
LOGO_WHITE_PATH = ASSETS / "toyokawaguide-logo white.png"
LIGHT_BASE = Path(os.environ.get("LIGHT_BASE", "G:/マイドライブ/ライト記事"))

# フォント：ローカル(Windows)とGHA(Linux)で切替
if platform.system() == "Windows":
    FONT_BOLD = "C:/Windows/Fonts/yugothb.ttc"
    FONT_REG = "C:/Windows/Fonts/yugothm.ttc"
    FONT_FALLBACK = "C:/Windows/Fonts/msgothic.ttc"
else:
    # GHA Linux - workflow が Noto Sans CJK を /tmp/light_fonts に配置
    _font_dir = os.environ.get("LIGHT_FONT_DIR", "/tmp/light_fonts")
    FONT_BOLD = f"{_font_dir}/NotoSansCJK-Bold.ttc"
    FONT_REG = f"{_font_dir}/NotoSansCJK-Regular.ttc"
    FONT_FALLBACK = FONT_BOLD

COLOR_BG = (26, 58, 138)             # 深い紺
COLOR_BEIGE = (252, 245, 230)        # ベージュ（帯用）
COLOR_ACCENT = (212, 160, 23)        # ゴールド
COLOR_TEXT_WHITE = (255, 255, 255)
COLOR_TEXT_SUB = (240, 220, 160)     # ライトゴールド
COLOR_TEXT_DARK = (60, 50, 30)       # ベージュ帯の上の文字色

BRAND_CATCH = "豊川市の地域メディア"

# モードは元記事タイトルの有無で自動判定（パターン辞書は廃止）
# 続報モード（元記事あり）: ラベル「【続報】」・キャッチ「あの記事の答え合わせ」・カードラベル「【続報情報】」
# お知らせモード（元記事なし）: ラベル「【お知らせ】」・キャッチ「管理人のひとり言」・カードラベル「【お知らせ】」
MODE_ZOKUHOU = {
    "label":       "【続報】",
    "lead":        "あの記事の答え合わせ",
    "card_label":  "【続報情報】",
    "title_label": "▼ 過去記事",
}
MODE_OSHIRASE = {
    "label":       "【お知らせ】",
    "lead":        "管理人のひとり言",
    "card_label":  "【お知らせ】",
    "title_label": "▼ お知らせ内容",
}


def load_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype(FONT_FALLBACK, size)


def fit_text_to_width(text: str, font_path: str, max_width: int,
                      max_size: int, min_size: int = None) -> int:
    min_size = min_size or int(max_size * 0.5)
    for size in range(max_size, min_size, -2):
        font = load_font(font_path, size)
        bbox = font.getbbox(text)
        if bbox[2] - bbox[0] <= max_width:
            return size
    return min_size


def wrap_text(text: str, font, max_width: int, draw) -> list:
    """テキストを max_width に収まるように改行で分割"""
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width:
            if current:
                lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def truncate_text(text: str, font, max_width: int, draw, max_lines: int = 2) -> str:
    """max_lines 行に収まらない場合は「…」で省略"""
    lines = wrap_text(text, font, max_width, draw)
    if len(lines) <= max_lines:
        return "\n".join(lines)
    # 上限を超えた場合：max_lines 行目を「…」付きに
    truncated = lines[:max_lines]
    last_line = truncated[-1]
    # 末尾を1文字ずつ削って「…」を追加
    while True:
        test_line = last_line + "…"
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            truncated[-1] = test_line
            break
        if len(last_line) <= 1:
            truncated[-1] = "…"
            break
        last_line = last_line[:-1]
    return "\n".join(truncated)


def draw_centered_text(draw, y, text, font, fill, width):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((width - tw) // 2, y), text, font=font, fill=fill)


def generate_eyecatch(place_name: str,
                      sub_text: str = "お知らせ",
                      address: str = "豊川市内",
                      landmark: str = "",
                      original_title: str = "",
                      lead_catch: str = None,
                      output_path: Path = None) -> Path:
    """ライト記事アイキャッチ v6：ベージュ帯拡張＋過去記事太字2段＋場所カードに目印追加"""
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), color=COLOR_BG)
    draw = ImageDraw.Draw(img)

    # ============ ヘッダー（0-100）横並び1行・大きく ============
    if LOGO_WHITE_PATH.exists():
        logo = Image.open(LOGO_WHITE_PATH).convert("RGBA")
        logo.thumbnail((72, 72), Image.LANCZOS)
        img.paste(logo, (45, 22), logo)
        text_x = 130
    else:
        text_x = 45

    # 「豊川ガイド ｜ 豊川市の地域メディア」横並び1行
    brand_font = load_font(FONT_BOLD, 36)
    sep_font = load_font(FONT_REG, 30)
    catch_font = load_font(FONT_REG, 26)

    brand_text = "豊川ガイド"
    sep_text = " ｜ "
    catch_text = BRAND_CATCH

    bbox_b = draw.textbbox((0, 0), brand_text, font=brand_font)
    brand_w_px = bbox_b[2] - bbox_b[0]
    bbox_s = draw.textbbox((0, 0), sep_text, font=sep_font)
    sep_w_px = bbox_s[2] - bbox_s[0]

    # ベースライン揃え（縦中央）
    base_y = 38
    draw.text((text_x, base_y), brand_text, font=brand_font, fill=COLOR_TEXT_WHITE)
    draw.text((text_x + brand_w_px, base_y + 4), sep_text, font=sep_font, fill=COLOR_TEXT_SUB)
    draw.text((text_x + brand_w_px + sep_w_px, base_y + 6),
              catch_text, font=catch_font, fill=COLOR_TEXT_SUB)

    # ============ ベージュ帯「さくっとお知らせ」（上下中央揃え：105-265） ============
    band_y_top = 105
    band_y_bottom = 265
    band_h = band_y_bottom - band_y_top  # 160
    draw.rectangle([0, band_y_top, W, band_y_bottom], fill=COLOR_BEIGE)
    draw.rectangle([0, band_y_top - 3, W, band_y_top], fill=COLOR_ACCENT)
    draw.rectangle([0, band_y_bottom, W, band_y_bottom + 3], fill=COLOR_ACCENT)

    # 「豊川ガイド的」（小）＋「さくっとお知らせ」（大）を縦合計→帯の縦中央に配置
    sec_font = load_font(FONT_REG, 24)
    sec_lg_font = load_font(FONT_BOLD, 56)

    sb_top = draw.textbbox((0, 0), "豊川ガイド的", font=sec_font)
    sb_btm = draw.textbbox((0, 0), "さくっとお知らせ", font=sec_lg_font)
    h_top = sb_top[3] - sb_top[1]
    h_btm = sb_btm[3] - sb_btm[1]
    gap_between = 10
    total_h = h_top + gap_between + h_btm
    start_y = band_y_top + (band_h - total_h) // 2 - 4  # 微調整

    draw_centered_text(draw, start_y, "豊川ガイド的",
                       sec_font, COLOR_TEXT_DARK, W)
    draw_centered_text(draw, start_y + h_top + gap_between,
                       "さくっとお知らせ", sec_lg_font, COLOR_BG, W)

    # ============ モード判定（元記事タイトルの有無） ============
    has_original = bool(original_title)
    mode = MODE_ZOKUHOU if has_original else MODE_OSHIRASE

    # ============ ラベル帯＋キャッチ（275-315） ============
    label_text = mode["label"]
    label_font = load_font(FONT_BOLD, 22)
    lbl_bbox = draw.textbbox((0, 0), label_text, font=label_font)
    lbl_w = lbl_bbox[2] - lbl_bbox[0]
    lbl_h = lbl_bbox[3] - lbl_bbox[1]

    pad_x, pad_y = 16, 6
    bar_x = 55
    bar_y = 285
    bar_w = lbl_w + pad_x * 2
    bar_h = lbl_h + pad_y * 2 + 6
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                            radius=8, fill=COLOR_ACCENT)
    draw.text((bar_x + pad_x, bar_y + pad_y), label_text,
              font=label_font, fill=COLOR_TEXT_WHITE)

    catch_text = lead_catch or mode["lead"]
    catch_lead_font = load_font(FONT_REG, 22)
    draw.text((bar_x + bar_w + 14, bar_y + 9), catch_text,
              font=catch_lead_font, fill=COLOR_TEXT_SUB)

    # ============ 元記事タイトル枠（335-430） ============
    # 元記事あり: F列の内容
    # 元記事なし: 「管理人が気になった、{場所}の話」を自動生成
    title_to_show = original_title if has_original else f"管理人が気になった、{place_name}の話"
    card_label_text = mode["card_label"]

    title_x = 55
    title_y = 335
    title_w = W - 110
    title_h = 95
    draw.rounded_rectangle([title_x, title_y, title_x + title_w, title_y + title_h],
                            radius=8, outline=COLOR_TEXT_SUB, width=2)

    ptag_font = load_font(FONT_BOLD, 14)
    ptag_text = mode["title_label"]
    draw.text((title_x + 14, title_y + 8), ptag_text,
              font=ptag_font, fill=COLOR_TEXT_SUB)

    # 本文（太字・2段まで・縦中央揃え）
    if True:
        title_font = load_font(FONT_BOLD, 18)
        truncated = truncate_text(title_to_show, title_font,
                                   title_w - 28, draw, max_lines=2)

        # multiline_text 全体の高さを計測して縦中央配置
        ml_bbox = draw.multiline_textbbox((0, 0), truncated,
                                           font=title_font, spacing=6)
        ml_h = ml_bbox[3] - ml_bbox[1]
        # ラベル領域（上部28px）を除いた残りの中央に配置
        label_zone = 28
        avail_top = title_y + label_zone
        avail_h = title_h - label_zone
        text_y = avail_top + (avail_h - ml_h) // 2 - 4
        draw.multiline_text((title_x + 14, text_y), truncated,
                            font=title_font, fill=COLOR_TEXT_WHITE,
                            spacing=6)

    # ============ メインカード 2枚横並び（440-680） ============
    cards_y = 445
    cards_h = 220
    gap = 30
    card_w = (W - 110 - gap) // 2

    # 左右カード共通の区切り線 y 座標（両カードでラベル位置を揃える）
    COMMON_LINE_Y = cards_y + 95

    # ===== 左カード：【続報情報】 =====
    left_x = 55
    draw.rounded_rectangle([left_x, cards_y, left_x + card_w, cards_y + cards_h],
                            radius=12, outline=COLOR_ACCENT, width=3)

    chead_font = load_font(FONT_BOLD, 17)
    draw.text((left_x + 18, cards_y + 14), card_label_text,
              font=chead_font, fill=COLOR_ACCENT)

    place_max_w = card_w - 36
    place_size = fit_text_to_width(place_name, FONT_BOLD, place_max_w,
                                    max_size=30, min_size=18)
    place_font = load_font(FONT_BOLD, place_size)
    bbox = draw.textbbox((0, 0), place_name, font=place_font)
    pw = bbox[2] - bbox[0]
    # 場所名：上ラベル下〜共通区切り線の中央に縦中央寄せ
    place_zone_top = cards_y + 36
    place_zone_h = COMMON_LINE_Y - place_zone_top
    place_y = place_zone_top + (place_zone_h - place_size) // 2 - 2
    draw.text((left_x + (card_w - pw) // 2, place_y), place_name,
              font=place_font, fill=COLOR_TEXT_WHITE)

    # 共通区切り線
    line_y = COMMON_LINE_Y
    draw.rectangle([left_x + 30, line_y, left_x + card_w - 30, line_y + 2],
                   fill=COLOR_ACCENT)

    end_label_font = load_font(FONT_BOLD, 14)
    end_label = "▼ その後、どうなった？"
    bbox = draw.textbbox((0, 0), end_label, font=end_label_font)
    elw = bbox[2] - bbox[0]
    draw.text((left_x + (card_w - elw) // 2, line_y + 12),
              end_label, font=end_label_font, fill=COLOR_ACCENT)

    # サブテキスト：場所/目印と同じ仕様で自動縮小（max_size=28, min_size=16）
    # 1段 or 2段（"\n" 区切り）対応
    # 2段の場合は両段が place_max_w に収まる最大サイズで統一
    if "\n" in sub_text:
        sub_lines = [s.strip() for s in sub_text.split("\n") if s.strip()][:2]
    elif "|" in sub_text:
        sub_lines = [s.strip() for s in sub_text.split("|") if s.strip()][:2]
    else:
        sub_lines = [sub_text]

    # 各段ごとに fit_text_to_width で最大サイズ計算 → 小さい方で揃える
    sizes = [fit_text_to_width(line, FONT_BOLD, place_max_w,
                                max_size=28, min_size=16)
             for line in sub_lines]
    sub_size = min(sizes)
    sub_font = load_font(FONT_BOLD, sub_size)

    # 描画：1段・2段とも line_y + 36 を上端に固定（左右両カードで揃える）
    SUB_TEXT_TOP = line_y + 36
    if len(sub_lines) == 1:
        # 1段：上端固定・左右中央
        bbox = draw.textbbox((0, 0), sub_lines[0], font=sub_font)
        sw = bbox[2] - bbox[0]
        draw.text((left_x + (card_w - sw) // 2, SUB_TEXT_TOP),
                  sub_lines[0], font=sub_font, fill=COLOR_TEXT_WHITE)
    else:
        # 2段：上端固定・各行左右中央
        sub_block = "\n".join(sub_lines)
        ml_bbox = draw.multiline_textbbox((0, 0), sub_block,
                                          font=sub_font, spacing=4)
        sub_w = ml_bbox[2] - ml_bbox[0]
        draw.multiline_text((left_x + (card_w - sub_w) // 2, SUB_TEXT_TOP),
                            sub_block, font=sub_font,
                            fill=COLOR_TEXT_WHITE, spacing=4, align="center")

    # ===== 右カード：【場所】＋【目印】 =====
    right_x = left_x + card_w + gap
    draw.rounded_rectangle([right_x, cards_y, right_x + card_w, cards_y + cards_h],
                            radius=12, outline=COLOR_ACCENT, width=3)

    draw.text((right_x + 18, cards_y + 14), "【場所】",
              font=chead_font, fill=COLOR_ACCENT)

    # 住所（中央寄せ・上段）
    addr_max_w = card_w - 36
    addr_size = fit_text_to_width(address, FONT_BOLD, addr_max_w,
                                   max_size=30, min_size=18)
    addr_font = load_font(FONT_BOLD, addr_size)
    bbox = draw.textbbox((0, 0), address, font=addr_font)
    aw = bbox[2] - bbox[0]
    # 住所：上ラベル下〜共通区切り線の中央に縦中央寄せ（左カードの場所名と同じ位置）
    addr_zone_top = cards_y + 36
    addr_zone_h = COMMON_LINE_Y - addr_zone_top
    addr_y = addr_zone_top + (addr_zone_h - addr_size) // 2 - 2
    draw.text((right_x + (card_w - aw) // 2, addr_y), address,
              font=addr_font, fill=COLOR_TEXT_WHITE)

    # 中央線（左カードと同じ y 座標）
    addr_line_y = COMMON_LINE_Y
    draw.rectangle([right_x + 30, addr_line_y, right_x + card_w - 30, addr_line_y + 2],
                   fill=COLOR_ACCENT)

    # 「目印」ラベル＋テキスト
    lm_label = "▼ 目印"
    bbox = draw.textbbox((0, 0), lm_label, font=end_label_font)
    llw = bbox[2] - bbox[0]
    draw.text((right_x + (card_w - llw) // 2, addr_line_y + 12),
              lm_label, font=end_label_font, fill=COLOR_ACCENT)

    # 左カードの「事務所として活用」と同じスタイル（白文字・FONT_BOLD・同サイズロジック）
    landmark_text = landmark or "豊川市内"
    lm_size = fit_text_to_width(landmark_text, FONT_BOLD, addr_max_w,
                                 max_size=28, min_size=16)
    lm_font = load_font(FONT_BOLD, lm_size)
    bbox = draw.textbbox((0, 0), landmark_text, font=lm_font)
    lmw = bbox[2] - bbox[0]
    draw.text((right_x + (card_w - lmw) // 2, addr_line_y + 36),
              landmark_text, font=lm_font, fill=COLOR_TEXT_WHITE)

    # ============ 枠外注釈 ============
    note_font = load_font(FONT_REG, 16)
    note_text = "※ 詳しくは記事本文をどうぞ"
    bbox = draw.textbbox((0, 0), note_text, font=note_font)
    nw = bbox[2] - bbox[0]
    draw.text(((W - nw) // 2, cards_y + cards_h + 10),
              note_text, font=note_font, fill=COLOR_TEXT_SUB)

    # === 保存 ===
    if output_path is None:
        output_path = ROOT / "_sample" / "eyecatch_sample.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)

    img.save(output_path, "PNG")
    return output_path


def generate_ig_feed(place_name: str,
                      sub_text: str = "お知らせ",
                      address: str = "豊川市内",
                      landmark: str = "",
                      original_title: str = "",
                      lead_catch: str = None,
                      output_path: Path = None) -> Path:
    """Instagram Feed 用画像 1080×1350（4:5 縦長）
    リールと同じ縦積み構造（ブランドヘッダー＋ベージュ帯＋【続報】＋過去記事＋2カード縦積み）
    """
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), color=COLOR_BG)
    draw = ImageDraw.Draw(img)

    has_original = bool(original_title)
    mode = MODE_ZOKUHOU if has_original else MODE_OSHIRASE

    margin_x = 60
    content_w = W - margin_x * 2  # 960

    # ============ ヘッダー（0-115） ============
    if LOGO_WHITE_PATH.exists():
        logo = Image.open(LOGO_WHITE_PATH).convert("RGBA")
        logo.thumbnail((78, 78), Image.LANCZOS)
        img.paste(logo, (50, 28), logo)
        text_x = 140
    else:
        text_x = 50

    brand_font = load_font(FONT_BOLD, 44)
    sep_font = load_font(FONT_REG, 36)
    catch_font = load_font(FONT_REG, 30)

    base_y = 42
    bbox_b = draw.textbbox((0, 0), "豊川ガイド", font=brand_font)
    brand_w_px = bbox_b[2] - bbox_b[0]
    sep_text = " ｜ "
    bbox_s = draw.textbbox((0, 0), sep_text, font=sep_font)
    sep_w_px = bbox_s[2] - bbox_s[0]

    draw.text((text_x, base_y), "豊川ガイド",
              font=brand_font, fill=COLOR_TEXT_WHITE)
    draw.text((text_x + brand_w_px, base_y + 6), sep_text,
              font=sep_font, fill=COLOR_TEXT_SUB)
    draw.text((text_x + brand_w_px + sep_w_px, base_y + 8),
              BRAND_CATCH, font=catch_font, fill=COLOR_TEXT_SUB)

    # ============ ベージュ帯「豊川ガイド的 さくっとお知らせ」（125-335） ============
    band_y_top = 125
    band_y_bottom = 335
    band_h = band_y_bottom - band_y_top
    draw.rectangle([0, band_y_top, W, band_y_bottom], fill=COLOR_BEIGE)
    draw.rectangle([0, band_y_top - 4, W, band_y_top], fill=COLOR_ACCENT)
    draw.rectangle([0, band_y_bottom, W, band_y_bottom + 4], fill=COLOR_ACCENT)

    sec_font = load_font(FONT_REG, 36)
    sec_lg_font = load_font(FONT_BOLD, 88)
    sb_top = draw.textbbox((0, 0), "豊川ガイド的", font=sec_font)
    sb_btm = draw.textbbox((0, 0), "さくっとお知らせ", font=sec_lg_font)
    h_top = sb_top[3] - sb_top[1]
    h_btm = sb_btm[3] - sb_btm[1]
    gap_between = 12
    total_h = h_top + gap_between + h_btm
    start_y = band_y_top + (band_h - total_h) // 2 - 6

    draw_centered_text(draw, start_y, "豊川ガイド的",
                       sec_font, COLOR_TEXT_DARK, W)
    draw_centered_text(draw, start_y + h_top + gap_between,
                       "さくっとお知らせ", sec_lg_font, COLOR_BG, W)

    # ============ ラベル帯＋キャッチ ============
    y = band_y_bottom + 30
    label_text = mode["label"]
    label_font = load_font(FONT_BOLD, 30)
    lbl_bbox = draw.textbbox((0, 0), label_text, font=label_font)
    lbl_w = lbl_bbox[2] - lbl_bbox[0]
    lbl_h = lbl_bbox[3] - lbl_bbox[1]

    pad_x, pad_y = 22, 10
    bar_x = margin_x
    bar_y = y
    bar_w = lbl_w + pad_x * 2
    bar_h = lbl_h + pad_y * 2 + 8
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                            radius=10, fill=COLOR_ACCENT)
    draw.text((bar_x + pad_x, bar_y + pad_y), label_text,
              font=label_font, fill=COLOR_TEXT_WHITE)

    catch_text = lead_catch or mode["lead"]
    catch_lead_font = load_font(FONT_REG, 30)
    draw.text((bar_x + bar_w + 18, bar_y + 14), catch_text,
              font=catch_lead_font, fill=COLOR_TEXT_SUB)
    y = bar_y + bar_h + 24

    # ============ 過去記事タイトル枠 ============
    title_to_show = original_title if has_original else f"管理人が気になった、{place_name}の話"
    ptag_text = mode["title_label"]

    title_x = margin_x
    title_w = content_w
    title_h_box = 145
    draw.rounded_rectangle([title_x, y, title_x + title_w, y + title_h_box],
                            radius=10, outline=COLOR_TEXT_SUB, width=2)

    ptag_font = load_font(FONT_BOLD, 22)
    draw.text((title_x + 20, y + 14), ptag_text,
              font=ptag_font, fill=COLOR_TEXT_SUB)

    title_font = load_font(FONT_BOLD, 30)
    truncated = truncate_text(title_to_show, title_font,
                               title_w - 40, draw, max_lines=3)
    ml_bbox = draw.multiline_textbbox((0, 0), truncated,
                                       font=title_font, spacing=8)
    ml_h = ml_bbox[3] - ml_bbox[1]
    label_zone = 44
    avail_top = y + label_zone
    avail_h = title_h_box - label_zone
    text_y_pos = avail_top + (avail_h - ml_h) // 2 - 6
    draw.multiline_text((title_x + 20, text_y_pos), truncated,
                        font=title_font, fill=COLOR_TEXT_WHITE, spacing=8)
    y += title_h_box + 28

    # ============ サブテキスト分解（"\n" / "|" / "／" 対応） ============
    if "\n" in sub_text:
        sub_lines = [s.strip() for s in sub_text.split("\n") if s.strip()][:2]
    elif "|" in sub_text:
        sub_lines = [s.strip() for s in sub_text.split("|") if s.strip()][:2]
    elif "／" in sub_text:
        sub_lines = [s.strip() for s in sub_text.split("／") if s.strip()][:2]
    else:
        sub_lines = [sub_text]
    # 「場所」と同じ1段目は除外
    if sub_lines and sub_lines[0] == place_name and len(sub_lines) > 1:
        sub_lines = sub_lines[1:]

    # ============ Card 1: 【続報情報】 ============
    PAD_TOP = 22
    PAD_BTM = 26
    GAP_CHEAD = 12
    GAP_BEFORE_LINE = 20
    GAP_AFTER_LINE = 18
    GAP_AFTER_LABEL = 16
    CHEAD_SIZE = 26
    LABEL_SMALL_SIZE = 24

    chead_font_c = load_font(FONT_BOLD, CHEAD_SIZE)
    label_small_c = load_font(FONT_BOLD, LABEL_SMALL_SIZE)

    place_max_w = content_w - 50
    place_size = fit_text_to_width(place_name, FONT_BOLD, place_max_w,
                                    max_size=60, min_size=34)
    place_font_c = load_font(FONT_BOLD, place_size)

    longest_sub = max(sub_lines, key=len) if sub_lines else ""
    sub_size_c = fit_text_to_width(longest_sub, FONT_BOLD, place_max_w,
                                    max_size=46, min_size=28) if sub_lines else 32
    sub_font_c = load_font(FONT_BOLD, sub_size_c)
    sub_count = max(1, len(sub_lines))
    sub_block_h = sub_count * (sub_size_c + 8) - 8

    card_h = (PAD_TOP + CHEAD_SIZE + GAP_CHEAD + place_size +
              GAP_BEFORE_LINE + 2 + GAP_AFTER_LINE + LABEL_SMALL_SIZE +
              GAP_AFTER_LABEL + sub_block_h + PAD_BTM)

    card_y = y
    draw.rounded_rectangle([margin_x, card_y, margin_x + content_w, card_y + card_h],
                            radius=12, outline=COLOR_ACCENT, width=3)
    draw.text((margin_x + 22, card_y + PAD_TOP),
              mode["card_label"], font=chead_font_c, fill=COLOR_ACCENT)

    place_y = card_y + PAD_TOP + CHEAD_SIZE + GAP_CHEAD
    bbox = draw.textbbox((0, 0), place_name, font=place_font_c)
    pw = bbox[2] - bbox[0]
    cx_card = margin_x + content_w // 2
    draw.text((cx_card - pw // 2, place_y), place_name,
              font=place_font_c, fill=COLOR_TEXT_WHITE)

    line_y = place_y + place_size + GAP_BEFORE_LINE
    draw.rectangle([margin_x + 60, line_y, margin_x + content_w - 60, line_y + 2],
                   fill=COLOR_ACCENT)

    sub_label_y = line_y + GAP_AFTER_LINE
    end_label = "▼ その後、どうなった？"
    bbox = draw.textbbox((0, 0), end_label, font=label_small_c)
    elw = bbox[2] - bbox[0]
    draw.text((cx_card - elw // 2, sub_label_y), end_label,
              font=label_small_c, fill=COLOR_ACCENT)

    if sub_lines:
        sub_y_pos = sub_label_y + LABEL_SMALL_SIZE + GAP_AFTER_LABEL
        sub_block = "\n".join(sub_lines)
        ml_bbox = draw.multiline_textbbox((0, 0), sub_block,
                                           font=sub_font_c, spacing=8)
        sub_w = ml_bbox[2] - ml_bbox[0]
        draw.multiline_text((cx_card - sub_w // 2, sub_y_pos),
                            sub_block, font=sub_font_c,
                            fill=COLOR_TEXT_WHITE, spacing=8, align="center")
    y = card_y + card_h + 26

    # ============ Card 2: 【場所】 ============
    if address or landmark:
        addr_size = fit_text_to_width(address, FONT_BOLD, place_max_w,
                                       max_size=52, min_size=30)
        addr_font_c = load_font(FONT_BOLD, addr_size)

        lm_text = landmark or "豊川市内"
        lm_size = fit_text_to_width(lm_text, FONT_BOLD, place_max_w,
                                     max_size=40, min_size=24)
        lm_font_c = load_font(FONT_BOLD, lm_size)

        card2_h = (PAD_TOP + CHEAD_SIZE + GAP_CHEAD + addr_size +
                   GAP_BEFORE_LINE + 2 + GAP_AFTER_LINE + LABEL_SMALL_SIZE +
                   GAP_AFTER_LABEL + lm_size + PAD_BTM)

        card2_y = y
        draw.rounded_rectangle([margin_x, card2_y, margin_x + content_w, card2_y + card2_h],
                                radius=12, outline=COLOR_ACCENT, width=3)
        draw.text((margin_x + 22, card2_y + PAD_TOP), "【場所】",
                  font=chead_font_c, fill=COLOR_ACCENT)

        addr_y = card2_y + PAD_TOP + CHEAD_SIZE + GAP_CHEAD
        bbox = draw.textbbox((0, 0), address, font=addr_font_c)
        aw = bbox[2] - bbox[0]
        draw.text((cx_card - aw // 2, addr_y), address,
                  font=addr_font_c, fill=COLOR_TEXT_WHITE)

        addr_line_y = addr_y + addr_size + GAP_BEFORE_LINE
        draw.rectangle([margin_x + 60, addr_line_y, margin_x + content_w - 60, addr_line_y + 2],
                       fill=COLOR_ACCENT)

        lm_label_y = addr_line_y + GAP_AFTER_LINE
        lm_label = "▼ 目印"
        bbox = draw.textbbox((0, 0), lm_label, font=label_small_c)
        llw = bbox[2] - bbox[0]
        draw.text((cx_card - llw // 2, lm_label_y), lm_label,
                  font=label_small_c, fill=COLOR_ACCENT)

        lm_y_pos = lm_label_y + LABEL_SMALL_SIZE + GAP_AFTER_LABEL
        bbox = draw.textbbox((0, 0), lm_text, font=lm_font_c)
        lmw = bbox[2] - bbox[0]
        draw.text((cx_card - lmw // 2, lm_y_pos), lm_text,
                  font=lm_font_c, fill=COLOR_TEXT_WHITE)
        y = card2_y + card2_h + 20

    # ============ 枠外注釈 ============
    note_font = load_font(FONT_REG, 22)
    note_text = "※ 詳しくはプロフィールのリンクから本文をどうぞ"
    bbox = draw.textbbox((0, 0), note_text, font=note_font)
    nw = bbox[2] - bbox[0]
    note_y = min(y + 14, H - 60)
    draw.text(((W - nw) // 2, note_y),
              note_text, font=note_font, fill=COLOR_TEXT_SUB)

    if output_path is None:
        output_path = ROOT / "_sample" / "ig_feed_sample.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="記事ID（例: LR001）")
    ap.add_argument("--place", required=True, help="場所名")
    ap.add_argument("--sub", default="お知らせ", help="サブテキスト（事務所として活用 等）")
    ap.add_argument("--address", default="豊川市内")
    ap.add_argument("--landmark", default="", help="目印（国道151号線沿い 等）")
    ap.add_argument("--title", default="", help="元記事タイトル（あれば続報モード）")
    ap.add_argument("--lead", help="キャッチコピー上書き")
    ap.add_argument("--output", help="出力パス")
    ap.add_argument("--ig", action="store_true", help="IG Feed版（1080×1350）を生成")
    args = ap.parse_args()

    if args.output:
        out = Path(args.output)
    elif args.id:
        suffix = "ig_feed.png" if args.ig else "eyecatch.png"
        out = LIGHT_BASE / f"{args.id}_{args.place}" / suffix
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        out = None

    if args.ig:
        result = generate_ig_feed(args.place,
                                   sub_text=args.sub,
                                   address=args.address,
                                   landmark=args.landmark,
                                   original_title=args.title,
                                   lead_catch=args.lead,
                                   output_path=out)
        print(f"✅ IG Feed画像生成: {result}")
    else:
        result = generate_eyecatch(args.place,
                                    sub_text=args.sub,
                                    address=args.address,
                                    landmark=args.landmark,
                                    original_title=args.title,
                                    lead_catch=args.lead,
                                    output_path=out)
        print(f"✅ アイキャッチ生成: {result}")


if __name__ == "__main__":
    main()
