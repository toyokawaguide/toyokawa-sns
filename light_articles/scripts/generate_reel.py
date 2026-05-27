"""
generate_reel.py — ライト記事用リール動画生成（1080×1920・15秒）

【方針】
- アイキャッチの構造（ヘッダー＋ベージュ帯＋続報ラベル＋過去記事＋カード）を縦長リールで再構築
- 上180・下320 を空けて IG UI 回避
- 「豊川ガイド」見出しを大きく
- 静止画＋15秒動画（FFmpeg・無音オーディオ）

【使い方】
python generate_reel.py --id LR001
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

import os
import platform

ROOT = Path(__file__).resolve().parent
# scripts/ の1階層上に _assets/ を置く（toyokawa-sns/light_articles/_assets/）
ASSETS = ROOT.parent / "_assets" if (ROOT.parent / "_assets").exists() else ROOT / "_assets"
LOGO_WHITE = ASSETS / "toyokawaguide-logo white.png"

# Canvas
W, H = 1080, 1920
DURATION = 15

# Safe area
SAFE_TOP = 180
SAFE_BOTTOM = 320

# Colors
COLOR_BG = (26, 58, 138)
COLOR_BEIGE = (252, 245, 230)
COLOR_ACCENT = (212, 160, 23)
COLOR_TEXT_WHITE = (255, 255, 255)
COLOR_TEXT_SUB = (240, 220, 160)
COLOR_TEXT_DARK = (60, 50, 30)

if platform.system() == "Windows":
    FONT_BOLD = "C:/Windows/Fonts/yugothb.ttc"
    FONT_REG = "C:/Windows/Fonts/yugothm.ttc"
    FALLBACK = "C:/Windows/Fonts/msgothic.ttc"
else:
    _font_dir = os.environ.get("LIGHT_FONT_DIR", "/tmp/light_fonts")
    FONT_BOLD = f"{_font_dir}/NotoSansCJK-Bold.ttc"
    FONT_REG = f"{_font_dir}/NotoSansCJK-Regular.ttc"
    FALLBACK = FONT_BOLD


def load_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype(FALLBACK, size)


def fit_text(text: str, font_path: str, max_width: int,
              max_size: int, min_size: int) -> int:
    for size in range(max_size, min_size - 1, -2):
        font = load_font(font_path, size)
        bbox = font.getbbox(text)
        if bbox[2] - bbox[0] <= max_width:
            return size
    return min_size


def wrap_for_width(text: str, font, max_width: int, draw) -> list:
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


def draw_centered_x(draw, y, text, font, fill, cx=W // 2):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, y), text, font=font, fill=fill)


def build_reel_frame(*, place: str, sub_lines: list[str],
                      address: str, landmark: str,
                      original_title: str,
                      tsubuyaki: str = "",
                      publish_date_str: str = "") -> Image.Image:
    """占いリール構造をライト記事用に流用"""
    img = Image.new("RGB", (W, H), color=COLOR_BG)
    draw = ImageDraw.Draw(img)
    has_original = bool(original_title)

    margin_x = 40
    # 右側にサイドバー（縦書きロゴ）あり、コンテンツ領域は CONTENT_RIGHT まで
    content_right = W - 200  # 880
    card_w = content_right - margin_x  # 840
    cx = (margin_x + content_right) // 2  # 460（コンテンツ領域の中央）

    # ─── 1. 左上ヘッダー：豊川ガイド (大)＋toyokawaguide (小)＋日付 ───
    top = SAFE_TOP
    brand_font = load_font(FONT_BOLD, 96)
    draw.text((40, top - 10), "豊川ガイド", font=brand_font,
              fill=COLOR_TEXT_WHITE)
    tw_font = load_font(FONT_REG, 26)
    draw.text((48, top + 110), "toyokawaguide", font=tw_font,
              fill=COLOR_TEXT_WHITE)
    # 日付
    if publish_date_str:
        date_font = load_font(FONT_BOLD, 50)
        draw.text((40, top + 160), publish_date_str,
                  font=date_font, fill=COLOR_TEXT_WHITE)

    # ─── 2. 右側サイドバー：ロゴ（白）＋縦書き「豊川市の地域メディア」 ───
    sidebar_cx = W - 100
    if LOGO_WHITE.exists():
        logo = Image.open(LOGO_WHITE).convert("RGBA")
        logo.thumbnail((130, 130), Image.LANCZOS)
        img.paste(logo, (sidebar_cx - logo.width // 2, SAFE_TOP), logo)
    # 縦書き「豊川市の地域メディア」（太字）
    vert_font = load_font(FONT_BOLD, 36)
    vert_text = "豊川市の地域メディア"
    vert_y = SAFE_TOP + 160
    for ch in vert_text:
        b = draw.textbbox((0, 0), ch, font=vert_font)
        cw = b[2] - b[0]
        draw.text((sidebar_cx - cw // 2, vert_y), ch,
                  font=vert_font, fill=COLOR_TEXT_WHITE)
        vert_y += 46

    # ─── 3. 「★ 豊川ガイド的　さくっとお知らせ ★」見出し ───
    # ★だけ金色（COLOR_ACCENT）、本体テキストは白
    y = top + 260
    catch_font_size = 60
    catch_font = load_font(FONT_BOLD, catch_font_size)
    star = "★"
    middle = " 豊川ガイド的　さくっとお知らせ "
    content_cx = (margin_x + content_right) // 2
    sw_bbox = draw.textbbox((0, 0), star, font=catch_font)
    mw_bbox = draw.textbbox((0, 0), middle, font=catch_font)
    sw = sw_bbox[2] - sw_bbox[0]
    mw = mw_bbox[2] - mw_bbox[0]
    total_w = sw + mw + sw
    if total_w > content_right - margin_x:
        catch_font_size = 48
        catch_font = load_font(FONT_BOLD, catch_font_size)
        sw_bbox = draw.textbbox((0, 0), star, font=catch_font)
        mw_bbox = draw.textbbox((0, 0), middle, font=catch_font)
        sw = sw_bbox[2] - sw_bbox[0]
        mw = mw_bbox[2] - mw_bbox[0]
        total_w = sw + mw + sw
    start_x = content_cx - total_w // 2
    draw.text((start_x, y), star, font=catch_font, fill=COLOR_ACCENT)
    draw.text((start_x + sw, y), middle, font=catch_font, fill=COLOR_TEXT_WHITE)
    draw.text((start_x + sw + mw, y), star, font=catch_font, fill=COLOR_ACCENT)
    y += 130

    # ─── 4. 【続報】ラベル ＋ キャッチ（少し小さく） ───
    if has_original:
        label_text = "【続報】"
        catch_text2 = "あの記事の答え合わせ"
    else:
        label_text = "【お知らせ】"
        catch_text2 = "管理人のひとり言"
    label_font = load_font(FONT_BOLD, 32)
    catch2_font = load_font(FONT_REG, 32)
    lbl_bbox = draw.textbbox((0, 0), label_text, font=label_font)
    lbl_w = lbl_bbox[2] - lbl_bbox[0]
    lbl_h = lbl_bbox[3] - lbl_bbox[1]
    pad_x, pad_y = 20, 10
    bar_x = margin_x
    bar_y = y
    bar_w = lbl_w + pad_x * 2
    bar_h = lbl_h + pad_y * 2 + 8
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                            radius=8, fill=COLOR_ACCENT)
    draw.text((bar_x + pad_x, bar_y + pad_y), label_text,
              font=label_font, fill=COLOR_TEXT_WHITE)
    draw.text((bar_x + bar_w + 20, bar_y + 16), catch_text2,
              font=catch2_font, fill=COLOR_TEXT_SUB)
    y = bar_y + bar_h + 24

    # ─── 5. 過去記事タイトル枠（小さく） ───
    if has_original:
        box_x = margin_x
        box_y = y
        box_w = card_w
        box_h = 170
        draw.rounded_rectangle([box_x, box_y, box_x + box_w, box_y + box_h],
                                radius=10, outline=COLOR_TEXT_SUB, width=2)
        ptag_font = load_font(FONT_BOLD, 24)
        draw.text((box_x + 20, box_y + 14), "▼ 過去記事",
                  font=ptag_font, fill=COLOR_TEXT_SUB)

        title_font = load_font(FONT_BOLD, 28)
        title_lines = wrap_for_width(original_title, title_font,
                                       box_w - 40, draw)[:3]
        ml_block = "\n".join(title_lines)
        ml_bbox = draw.multiline_textbbox((0, 0), ml_block,
                                           font=title_font, spacing=8)
        ml_h = ml_bbox[3] - ml_bbox[1]
        text_y = box_y + 54 + ((box_h - 54) - ml_h) // 2 - 4
        draw.multiline_text((box_x + 20, text_y), ml_block,
                            font=title_font, fill=COLOR_TEXT_WHITE, spacing=8)
        y = box_y + box_h + 28

    # ─── 6. 【続報情報】カード（動的高さ・上下ゆったり・フォント大きめ） ───
    # レイアウト用定数（つぶやき廃止で余裕ができたぶん上下を広く取る）
    PAD_TOP = 24
    PAD_BTM = 28
    GAP_CHEAD = 14
    GAP_BEFORE_LINE = 22
    GAP_AFTER_LINE = 20
    GAP_AFTER_LABEL = 18
    CHEAD_SIZE = 28
    LABEL_SMALL_SIZE = 26

    chead_font = load_font(FONT_BOLD, CHEAD_SIZE)
    chead_text = "【続報情報】" if has_original else "【お知らせ】"
    label_small = load_font(FONT_BOLD, LABEL_SMALL_SIZE)

    place_max_w = card_w - 50
    place_size = fit_text(place, FONT_BOLD, place_max_w,
                           max_size=64, min_size=36)
    place_font = load_font(FONT_BOLD, place_size)

    longest_sub = max(sub_lines, key=len) if sub_lines else ""
    sub_size = fit_text(longest_sub, FONT_BOLD, place_max_w,
                         max_size=50, min_size=30) if sub_lines else 36
    sub_font_obj = load_font(FONT_BOLD, sub_size)
    sub_lines_count = max(1, len(sub_lines))
    sub_block_h = sub_lines_count * (sub_size + 8) - 8

    card_h = (PAD_TOP + CHEAD_SIZE + GAP_CHEAD + place_size +
              GAP_BEFORE_LINE + 2 + GAP_AFTER_LINE + LABEL_SMALL_SIZE +
              GAP_AFTER_LABEL + sub_block_h + PAD_BTM)

    card_y = y
    draw.rounded_rectangle([margin_x, card_y, margin_x + card_w, card_y + card_h],
                            radius=12, outline=COLOR_ACCENT, width=3)

    chead_y = card_y + PAD_TOP
    draw.text((margin_x + 20, chead_y), chead_text,
              font=chead_font, fill=COLOR_ACCENT)

    place_y = chead_y + CHEAD_SIZE + GAP_CHEAD
    bbox = draw.textbbox((0, 0), place, font=place_font)
    pw = bbox[2] - bbox[0]
    draw.text((cx - pw // 2, place_y), place,
              font=place_font, fill=COLOR_TEXT_WHITE)

    line_y = place_y + place_size + GAP_BEFORE_LINE
    draw.rectangle([margin_x + 50, line_y, margin_x + card_w - 50, line_y + 2],
                   fill=COLOR_ACCENT)

    sub_label_y = line_y + GAP_AFTER_LINE
    draw_centered_x(draw, sub_label_y, "▼ その後、どうなった？",
                    label_small, COLOR_ACCENT, cx=cx)

    if sub_lines:
        sub_y = sub_label_y + LABEL_SMALL_SIZE + GAP_AFTER_LABEL
        sub_block = "\n".join(sub_lines)
        ml_bbox = draw.multiline_textbbox((0, 0), sub_block,
                                           font=sub_font_obj, spacing=8)
        sub_w = ml_bbox[2] - ml_bbox[0]
        draw.multiline_text((cx - sub_w // 2, sub_y),
                            sub_block, font=sub_font_obj,
                            fill=COLOR_TEXT_WHITE, spacing=8, align="center")

    y = card_y + card_h + 28

    # ─── 7. 【場所】カード（動的高さ・上下ゆったり・フォント大きめ） ───
    if address or landmark:
        addr_size = fit_text(address, FONT_BOLD, place_max_w,
                              max_size=56, min_size=32)
        addr_font = load_font(FONT_BOLD, addr_size)

        lm_text = landmark or "豊川市内"
        lm_size = fit_text(lm_text, FONT_BOLD, place_max_w,
                            max_size=42, min_size=26)
        lm_font = load_font(FONT_BOLD, lm_size)

        card2_h = (PAD_TOP + CHEAD_SIZE + GAP_CHEAD + addr_size +
                   GAP_BEFORE_LINE + 2 + GAP_AFTER_LINE + LABEL_SMALL_SIZE +
                   GAP_AFTER_LABEL + lm_size + PAD_BTM)

        card2_y = y
        draw.rounded_rectangle([margin_x, card2_y, margin_x + card_w, card2_y + card2_h],
                                radius=12, outline=COLOR_ACCENT, width=3)

        chead2_y = card2_y + PAD_TOP
        draw.text((margin_x + 20, chead2_y), "【場所】",
                  font=chead_font, fill=COLOR_ACCENT)

        addr_y = chead2_y + CHEAD_SIZE + GAP_CHEAD
        bbox = draw.textbbox((0, 0), address, font=addr_font)
        aw = bbox[2] - bbox[0]
        draw.text((cx - aw // 2, addr_y), address,
                  font=addr_font, fill=COLOR_TEXT_WHITE)

        addr_line_y = addr_y + addr_size + GAP_BEFORE_LINE
        draw.rectangle([margin_x + 50, addr_line_y, margin_x + card_w - 50, addr_line_y + 2],
                       fill=COLOR_ACCENT)

        lm_label_y = addr_line_y + GAP_AFTER_LINE
        draw_centered_x(draw, lm_label_y, "▼ 目印",
                        label_small, COLOR_ACCENT, cx=cx)

        lm_y = lm_label_y + LABEL_SMALL_SIZE + GAP_AFTER_LABEL
        bbox = draw.textbbox((0, 0), lm_text, font=lm_font)
        lmw = bbox[2] - bbox[0]
        draw.text((cx - lmw // 2, lm_y), lm_text,
                  font=lm_font, fill=COLOR_TEXT_WHITE)

        y = card2_y + card2_h + 28

    # 管理人のつぶやきはリール画面では描画しない（キャプションに記載）
    _ = tsubuyaki  # 引数互換のため受け取りだけしておく

    return img


def render_static_reel(static_image: Image.Image, output_path: Path,
                        duration: int = DURATION) -> Path:
    tmp_png = output_path.parent / f"_tmp_{output_path.stem}_frame.png"
    static_image.save(tmp_png, "PNG")
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(duration), "-i", str(tmp_png),
        "-f", "lavfi", "-t", str(duration),
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264", "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-vf", f"scale={W}:{H}",
        "-b:v", "3M", "-minrate", "3M", "-maxrate", "3M",
        "-bufsize", "3M",
        "-x264-params", "nal-hrd=cbr",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ]
    print(f"▶ FFmpeg: {output_path.name}")
    subprocess.run(cmd, check=True, capture_output=True)
    tmp_png.unlink(missing_ok=True)
    return output_path


def generate_reel(*, place: str, sub_lines: list[str],
                   address: str, landmark: str, original_title: str,
                   tsubuyaki: str = "",
                   publish_date_str: str = "",
                   output_path: Path) -> Path:
    frame = build_reel_frame(place=place, sub_lines=sub_lines,
                              address=address, landmark=landmark,
                              original_title=original_title,
                              tsubuyaki=tsubuyaki,
                              publish_date_str=publish_date_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    render_static_reel(frame, output_path)
    print(f"✅ Reel生成: {output_path} ({output_path.stat().st_size/1024:.0f} KB)")
    return output_path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--output")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from sheets_client import get_row_by_id

    found = get_row_by_id(args.id)
    if not found:
        print(f"❌ ID={args.id} が見つかりません")
        sys.exit(1)
    _, row = found

    place = row.get("場所", "")
    sub1 = row.get("その後（1段目）", "").strip()
    sub2 = row.get("その後（2段目）", "").strip()
    if sub1 and sub1 == place:
        sub1 = ""
    sub_lines = [s for s in [sub1, sub2] if s]
    if not sub_lines:
        sub_lines = [row.get("サブ", "お知らせ").strip()]

    output_path = Path(args.output) if args.output else (
        ROOT / "_sample" / f"_tmp_{args.id}_reel.mp4"
    )
    # 公開希望日を「2026年5月28日(木)」形式に整形
    from datetime import date as _date
    pub_str = ""
    pd = row.get("公開希望日", "").strip()
    if pd:
        sys.path.insert(0, str(ROOT))
        from publish_light_article import parse_publish_date
        d_obj = parse_publish_date(pd)
        if d_obj:
            week = ["月", "火", "水", "木", "金", "土", "日"][d_obj.weekday()]
            pub_str = f"{d_obj.year}年{d_obj.month}月{d_obj.day}日({week})"

    generate_reel(
        place=place,
        sub_lines=sub_lines,
        address=row.get("住所", "豊川市内"),
        landmark=row.get("目印", ""),
        original_title=row.get("元記事タイトル", ""),
        tsubuyaki=row.get("管理人のつぶやき", "").strip(),
        publish_date_str=pub_str,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()
