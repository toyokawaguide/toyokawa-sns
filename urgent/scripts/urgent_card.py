# -*- coding: utf-8 -*-
"""
urgent_card.py — 緊急告知の画像（「緊急告知」見出し＋タイトルだけのシンプルなカード）

  render(title, W, H, out)  … 任意サイズで1枚つくる
  サイズは publish_urgent.py が使う3種類：
    16:9 1280×720  … WPアイキャッチ
    4:5  1080×1350 … Instagram フィード／Threads
    9:16 1080×1920 … Instagram リール（静止画動画）／ストーリーズ
"""
from __future__ import annotations
import os
import platform
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
LOGO_WHITE = ROOT.parents[1] / "light_articles" / "scripts" / "_assets" / "toyokawaguide-logo-white.png"
JST = timezone(timedelta(hours=9))

# フォント：ライト記事と同じ（GHA はワークフローが LIGHT_FONT_DIR に NotoSansCJK を用意する）
if platform.system() == "Windows":
    FONT_BOLD = "C:/Windows/Fonts/yugothb.ttc"
    FONT_REG = "C:/Windows/Fonts/yugothm.ttc"
else:
    _font_dir = os.environ.get("LIGHT_FONT_DIR", "/tmp/light_fonts")
    FONT_BOLD = f"{_font_dir}/NotoSansCJK-Bold.ttc"
    FONT_REG = f"{_font_dir}/NotoSansCJK-Regular.ttc"

# 2026-10-13 社長「毒々しすぎる、もっとライトに」→ 赤帯をやめ、明るい生成り地＋紺文字＋やわらかい橙の札に
COLOR_BG = (250, 247, 240)      # 生成り
COLOR_NAVY = (26, 58, 138)      # 豊川ガイドの紺（文字・ロゴ）
COLOR_TAG = (238, 132, 72)      # 「緊急告知」の札（やわらかい橙）
COLOR_WHITE = (255, 255, 255)
COLOR_SUB = (110, 120, 140)     # 発信日時（グレー）
COLOR_ACCENT = (212, 160, 23)   # ゴールドの細線

HEADING = "緊急告知"

try:
    import budoux
    _PARSER = budoux.load_default_japanese_parser()
except Exception:   # budoux が無くても1文字ずつ折り返して動く
    _PARSER = None


def _font(path: str, size: int):
    return ImageFont.truetype(path, size)


def _text_w(d, text, f):
    b = d.textbbox((0, 0), text, font=f)
    return b[2] - b[0]


def _wrap(d, text: str, f, max_w: int) -> list[str]:
    """文節（budoux）を守って折り返す。社長が入れた改行はそのまま残す"""
    lines = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        words = _PARSER.parse(para) if _PARSER else list(para)
        cur = ""
        for w in words:
            if _text_w(d, cur + w, f) <= max_w:
                cur += w
                continue
            if cur:
                lines.append(cur)
            # 1文節だけで幅を超える時は1文字ずつ
            cur = ""
            for ch in w:
                if _text_w(d, cur + ch, f) > max_w and cur:
                    lines.append(cur)
                    cur = ""
                cur += ch
        if cur:
            lines.append(cur)
    return lines


def _fit(d, text, max_w, max_h, start, min_size):
    """枠（max_w × max_h）に収まる一番大きい文字サイズで折り返す"""
    size = start
    while True:
        f = _font(FONT_BOLD, size)
        lines = _wrap(d, text, f, max_w)
        line_h = int(size * 1.35)
        if len(lines) * line_h <= max_h or size <= min_size:
            return f, lines, line_h
        size -= 4


def render(title: str, W: int, H: int, output_path: Path, posted_at: datetime = None) -> Path:
    posted_at = posted_at or datetime.now(JST)
    s = min(W, H) / 1080          # 基準（1080幅）からの拡大率
    img = Image.new("RGB", (W, H), COLOR_BG)
    d = ImageDraw.Draw(img)
    pad = int(60 * s)

    # ── ヘッダー：ロゴ＋豊川ガイド ──
    y = int(H * 0.06) if H > W else int(30 * s)
    x = pad
    logo_h = int(90 * s)
    if LOGO_WHITE.exists():
        logo = Image.open(LOGO_WHITE).convert("RGBA")
        logo.thumbnail((logo_h, logo_h), Image.LANCZOS)
        navy = Image.new("RGBA", logo.size, COLOR_NAVY + (255,))   # 白ロゴを紺に塗り替え
        navy.putalpha(logo.getchannel("A"))
        logo = navy
        img.paste(logo, (x, y), logo)
        x += logo.width + int(20 * s)
    fb = _font(FONT_BOLD, int(48 * s))
    d.text((x, y + logo_h / 2), "豊川ガイド", font=fb, fill=COLOR_NAVY, anchor="lm")

    # ── 札：緊急告知（角丸・中央） ──
    band_top = y + logo_h + int(60 * s)
    band_h = int(110 * s)
    fh = _font(FONT_BOLD, int(64 * s))
    tw = _text_w(d, HEADING, fh) + int(110 * s)
    d.rounded_rectangle([W / 2 - tw / 2, band_top, W / 2 + tw / 2, band_top + band_h],
                        radius=band_h // 2, fill=COLOR_TAG)
    d.text((W / 2, band_top + band_h / 2), HEADING, font=fh, fill=COLOR_WHITE, anchor="mm")

    # ── フッター：発信日時 ──
    week = "月火水木金土日"[posted_at.weekday()]
    stamp = f"{posted_at.year}年{posted_at.month}月{posted_at.day}日({week}) {posted_at:%H:%M} 発信"
    fs = _font(FONT_REG, int(38 * s))
    foot_y = H - pad - int(10 * s)
    d.text((W / 2, foot_y), stamp, font=fs, fill=COLOR_SUB, anchor="ms")
    d.line([pad, foot_y - int(70 * s), W - pad, foot_y - int(70 * s)], fill=COLOR_ACCENT, width=max(2, int(4 * s)))

    # ── タイトル（真ん中の空きにできるだけ大きく） ──
    area_top = band_top + band_h + int(50 * s)
    area_bottom = foot_y - int(100 * s)
    f, lines, line_h = _fit(d, title, W - pad * 2, area_bottom - area_top,
                            start=int(96 * s), min_size=int(40 * s))
    total = len(lines) * line_h
    ty = area_top + (area_bottom - area_top - total) / 2
    for ln in lines:
        d.text((W / 2, ty + line_h / 2), ln, font=f, fill=COLOR_NAVY, anchor="mm")
        ty += line_h

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "本日の豊川稲荷周辺は\n交通規制があります"
    out = ROOT / "_sample"
    for name, (w, h) in {"eyecatch": (1280, 720), "feed": (1080, 1350), "tall": (1080, 1920)}.items():
        print(render(t, w, h, out / f"sample_{name}.png"))
