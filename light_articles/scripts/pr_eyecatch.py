# -*- coding: utf-8 -*-
"""pr_eyecatch.py — さくっとPR アイキャッチ（2026-08-05 確定デザイン）

かたち（自動切替）:
  写真なし → 「額ぶち」   … 色面にひとことキャッチが主役・B風の丸角枠
  写真あり → 「一枚の札」 … 外枠1本・キャッチ大→店名→写真→住所

出力:
  render_45()  … 1080×1350（IG Feed・プレビューメール・申込ページのライブプレビューと同じ絵）
  render_169() … 1280×720 （WPアイキャッチ・Xカード用の横長版）

デザインの正は 申込ページ sakutto_pr/index.html（JS）と claude/sakutto_pr_form/render_pr.py。
ここを変えたら向こうも合わせること。

色は申込時に備考へ「色：おまかせ（クリーム）」の形で入る。指定が無ければ
店名から自動で決める（申込ページのJSと同じ計算＝プレビューと同じ色になる）。

  py pr_eyecatch.py --sample   … 見本を _sample/ に出力
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent

# フォントは既存 eyecatch_generator と同じ解決方法（Windows=游ゴシック / GHA=Noto）
from eyecatch_generator import FONT_BOLD, FONT_REG

# ── テーマ（申込ページのJSと同じ並び・同じ値。順番を変えると「おまかせ」の色がズレる）──
THEMES = [
    dict(id="cream", name="クリーム", bg="#fdf6ec", ink="#3a3128", accent="#e08a3c", sub="#8a7a66"),
    dict(id="mint",  name="ミント",   bg="#f0f7f3", ink="#25453a", accent="#3f9d7a", sub="#6f8f83"),
    dict(id="sky",   name="スカイ",   bg="#eef4fb", ink="#1f3b57", accent="#3d86c6", sub="#6d8299"),
    dict(id="peach", name="ピーチ",   bg="#fdf0ee", ink="#4a2b28", accent="#e0705f", sub="#95736e"),
    dict(id="lemon", name="レモン",   bg="#fdfaea", ink="#453d1f", accent="#d8a72a", sub="#8b8055"),
    dict(id="white", name="ホワイト", bg="#ffffff", ink="#2b2b2b", accent="#c8a15a", sub="#8a8a8a"),
]
NAME2THEME = {t["name"]: t for t in THEMES}

try:
    import budoux
    _PARSER = budoux.load_default_japanese_parser()
except Exception:                                      # GHAで入っていなくても止めない
    _PARSER = None


# ───────────────────────── row からの取り出し ─────────────────────────

def hash_theme(name: str) -> dict:
    """申込ページJSの hashTheme() と同じ計算（プレビューと同じ色を出すため）"""
    h = 0
    for ch in name:
        h = (h + ord(ch)) % 9973
    return THEMES[h % len(THEMES)]


def style_from_row(row: dict) -> tuple[dict, str]:
    """備考から (テーマ, ラベル) を読む。無ければ店名ハッシュ＋'PR'"""
    biko = row.get("備考", "") or ""
    theme = None
    m = re.search(r"色：([^\n（(]+)", biko)
    if m:
        name = m.group(1).strip()
        if name in NAME2THEME:
            theme = NAME2THEME[name]
    if theme is None:                                  # おまかせ（◯◯） の◯◯を拾う
        m = re.search(r"色：おまかせ（([^）]+)）", biko)
        if m and m.group(1) in NAME2THEME:
            theme = NAME2THEME[m.group(1)]
    if theme is None:
        theme = hash_theme(row.get("店名", "") or "とよかわ")
    m = re.search(r"ラベル：(.+)", biko)
    badge = m.group(1).strip() if m else "PR"
    return theme, badge


def data_from_row(row: dict) -> dict:
    theme, badge = style_from_row(row)
    return dict(
        shop=(row.get("店名") or "").strip(),
        catch=(row.get("ひとことキャッチ") or "").strip(),
        addr=(row.get("エリア・住所") or "").strip(),
        badge=badge, theme=theme,
    )


# ───────────────────────── 描画部品 ─────────────────────────

def hx(s: str, a: int = 255):
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), a)


def font(path: str, size: int):
    return ImageFont.truetype(path, size)


def wrap_fit(d, text, fpath, max_w, max_lines, start, min_s):
    """budouxで文節を守って折り返し（語割れ「やって/ます」防止）"""
    words = _PARSER.parse(text) if _PARSER else list(text)
    for s in range(start, min_s - 1, -2):
        f = font(fpath, s)
        lines, cur = [], ""
        for wd in words:
            while d.textlength(wd, font=f) > max_w:
                seg = ""
                for ch in wd:
                    if seg and d.textlength(seg + ch, font=f) > max_w:
                        break
                    seg += ch
                if cur:
                    lines.append(cur); cur = ""
                lines.append(seg); wd = wd[len(seg):]
            if cur and d.textlength(cur + wd, font=f) > max_w:
                lines.append(cur); cur = wd
            else:
                cur += wd
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines:
            return s, lines
    return min_s, [text[:24] + "…"]


def fit_one(d, text, fpath, start, max_w, min_s):
    s = start
    while s > min_s and d.textlength(text, font=font(fpath, s)) > max_w:
        s -= 2
    return font(fpath, s)


def cover(im: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / im.width, h / im.height)
    nw, nh = int(im.width * s), int(im.height * s)
    im2 = im.resize((nw, nh), Image.LANCZOS)
    return im2.crop(((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h))


def rounded_photo(base, photo, x, y, w, h, r):
    tile = cover(photo, w, h)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    base.paste(tile, (x, y), mask)


def grad_dark(base, x, y, w, h, bottom=170):
    g = Image.new("L", (1, h))
    for i in range(h):
        g.putpixel((0, i), int(bottom * i / max(1, h - 1)))
    black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    black.putalpha(g.resize((w, h)))
    base.alpha_composite(black, (x, y))


def inner_border(base, FX, FY, FW, FH, R):
    """背景かざり＝D 白い内線（社長確定 2026-08-05）"""
    ov = Image.new("RGBA", (FW, FH), (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle((26, 26, FW - 27, FH - 27), max(4, R - 8),
                                         outline=(255, 255, 255, 120), width=3)
    m = Image.new("L", (FW, FH), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, FW - 1, FH - 1), R, fill=255)
    ov.putalpha(Image.composite(ov.getchannel("A"), Image.new("L", (FW, FH), 0), m))
    base.alpha_composite(ov, (FX, FY))


def pill(d, text, x, y, bg, fg, size=36):
    f = font(FONT_BOLD, size)
    w = d.textlength(text, font=f) + size * 1.33
    h = size + 28
    d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=bg)
    d.text((x + size * 0.66, y + h / 2 + 2), text, font=f, fill=fg, anchor="lm")


def addr_line(d, t, text, x, y, max_w, color=None, stroke=0):
    if not text:
        return
    d.ellipse((x, y - 24, x + 22, y - 2), fill=hx(t["accent"]))
    f = fit_one(d, text, FONT_BOLD, 34, max_w - 36, 22)
    d.text((x + 36, y), text, font=f, fill=color or hx(t["sub"]), anchor="ls",
           stroke_width=stroke, stroke_fill=(25, 25, 25))


def brand(d, t, W, H, color=None):
    d.text((W - 60, H - 36), "豊川ガイド｜さくっとPR",
           font=font(FONT_BOLD, 26), fill=color or hx(t["sub"]), anchor="rs")


# ───────────────────────── 4:5（1080×1350）─────────────────────────

def render_45(row: dict, photo_path=None, output_path=None):
    W, H, M = 1080, 1350, 72
    st = data_from_row(row)
    t = st["theme"]
    photo = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB") if photo_path else None
    im = Image.new("RGBA", (W, H), hx(t["bg"]))
    d = ImageDraw.Draw(im)

    if not photo:                                      # ─ 額ぶち ─
        FX, FY, FW, FH, R = 48, 48, W - 96, 772, 26
        d.rounded_rectangle((FX, FY, FX + FW, FY + FH), R, fill=hx(t["accent"]))
        inner_border(im, FX, FY, FW, FH, R)
        d = ImageDraw.Draw(im)
        s, lines = wrap_fit(d, st["catch"], FONT_BOLD, FW - 96, 3, 92, 42)
        bh = len(lines) * int(s * 1.34)
        y = FY + 170 + ((FH - 260) - bh) // 2 + s
        for ln in lines:
            d.text((FX + 48, y), ln, font=font(FONT_BOLD, s), fill="white", anchor="ls")
            y += int(s * 1.34)
        d.rounded_rectangle((FX, FY, FX + FW, FY + FH), R, outline=hx(t["accent"]), width=5)
        pill(d, st["badge"], FX + 26, FY + 26, "white", hx(t["accent"]))
        f = fit_one(d, st["shop"], FONT_BOLD, 80, W - M * 2, 40)
        d.text((M, 950), st["shop"], font=f, fill=hx(t["ink"]), anchor="ls")
        addr_line(d, t, st["addr"], M, 1032, W - M * 2)
        brand(d, t, W, H)
    else:                                              # ─ 一枚の札 ─
        d.rounded_rectangle((40, 40, W - 40, H - 40), 22, outline=hx(t["accent"]), width=6)
        d.text((W // 2, 158), st["badge"], font=font(FONT_BOLD, 34),
               fill=hx(t["accent"]), anchor="ms")
        s, lines = wrap_fit(d, st["catch"], FONT_BOLD, W - 200, 2, 84, 44)
        y = 310
        for ln in lines:
            d.text((W // 2, y), ln, font=font(FONT_BOLD, s), fill=hx(t["ink"]), anchor="ms")
            y += int(s * 1.3)
        yd = y - int(s * 1.3) + 46
        d.line((W // 2 - 90, yd, W // 2 + 90, yd), fill=hx(t["accent"]), width=3)
        f = fit_one(d, st["shop"], FONT_BOLD, 52, W - 300, 34)
        d.text((W // 2, yd + 84), st["shop"], font=f, fill=hx(t["ink"]), anchor="ms")
        PX, PY, PW, PH = 140, 600, W - 280, 500
        rounded_photo(im, photo, PX, PY, PW, PH, 18)
        d.rounded_rectangle((PX, PY, PX + PW, PY + PH), 18, outline=hx(t["accent"]), width=4)
        if st["addr"]:
            f = fit_one(d, st["addr"], FONT_BOLD, 34, W - 300, 22)
            d.text((W // 2, 1180), st["addr"], font=f, fill=hx(t["sub"]), anchor="ms")
        # クレジットは札の枠の内側に（枠かぶり対策 2026-08-05）
        d.text((W - 78, H - 72), "豊川ガイド｜さくっとPR",
               font=font(FONT_BOLD, 26), fill=hx(t["sub"]), anchor="rs")

    out = im.convert("RGB")
    if output_path:
        out.save(output_path)
    return out


# ───────────────────────── 16:9（1280×720）─────────────────────────

def render_169(row: dict, photo_path=None, output_path=None):
    W, H = 1280, 720
    st = data_from_row(row)
    t = st["theme"]
    photo = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB") if photo_path else None
    im = Image.new("RGBA", (W, H), hx(t["bg"]))
    d = ImageDraw.Draw(im)

    if not photo:                                      # ─ 額ぶち（左＝色面・右＝店名）─
        FX, FY, FW, FH, R = 40, 40, 700, H - 80, 24
        d.rounded_rectangle((FX, FY, FX + FW, FY + FH), R, fill=hx(t["accent"]))
        inner_border(im, FX, FY, FW, FH, R)
        d = ImageDraw.Draw(im)
        s, lines = wrap_fit(d, st["catch"], FONT_BOLD, FW - 96, 3, 72, 36)
        bh = len(lines) * int(s * 1.34)
        y = FY + 120 + ((FH - 200) - bh) // 2 + s
        for ln in lines:
            d.text((FX + 48, y), ln, font=font(FONT_BOLD, s), fill="white", anchor="ls")
            y += int(s * 1.34)
        d.rounded_rectangle((FX, FY, FX + FW, FY + FH), R, outline=hx(t["accent"]), width=5)
        pill(d, st["badge"], FX + 22, FY + 22, "white", hx(t["accent"]), size=30)
        tx = FX + FW + 44
        f = fit_one(d, st["shop"], FONT_BOLD, 60, W - tx - 50, 30)
        d.text((tx, 300), st["shop"], font=f, fill=hx(t["ink"]), anchor="ls")
        addr_line(d, t, st["addr"], tx, 370, W - tx - 50)
        brand(d, t, W, H)
    else:                                              # ─ 写真全面（2026-08-05・見切れ対策）─
        # 1920×1080は16:9そのままなので切れゼロ。文字はテーマ色の座布団＋白文字
        # （額ぶち版と同じ「アクセント色に白文字」＝どんな写真でも読める・社長指定 2026-08-05）
        im.paste(cover(photo, W, H), (0, 0))
        d = ImageDraw.Draw(im)
        pill(d, st["badge"], 48, 44, hx(t["accent"]), "white", size=30)

        def box(text, f, x, y, pad_x=26, pad_y=13, r=10, right=False):
            tw = d.textlength(text, font=f)
            bw, bh = tw + pad_x * 2, f.size + pad_y * 2
            if right:
                x -= bw
            d.rounded_rectangle((x, y, x + bw, y + bh), r, fill=hx(t["accent"]))
            d.text((x + pad_x, y + bh / 2 + 2), text, font=f, fill="white", anchor="lm")
            return bh

        tx = 48
        s, lines = wrap_fit(d, st["catch"], FONT_BOLD, W - 96 - 56, 2, 66, 40)
        f_c = font(FONT_BOLD, s)
        f_s = fit_one(d, st["shop"], FONT_BOLD, 38, W - 560, 26)
        f_a = fit_one(d, st["addr"], FONT_BOLD, 28, W - 560, 20) if st["addr"] else None
        h_c, h_s = f_c.size + 26, f_s.size + 22
        h_a = (f_a.size + 18) if f_a else 0
        gap = 12
        total = len(lines) * h_c + (len(lines) - 1) * 8 + gap + h_s + ((gap + h_a) if f_a else 0)
        y = H - 52 - total
        for ln in lines:
            box(ln, f_c, tx, y, pad_x=28, pad_y=13)
            y += h_c + 8
        y += gap - 8
        box(st["shop"], f_s, tx, y, pad_x=22, pad_y=11)
        y += h_s + gap
        if f_a:
            box(st["addr"], f_a, tx, y, pad_x=20, pad_y=9)
        d.rounded_rectangle((16, 16, W - 17, H - 17), 14, outline=hx(t["accent"]), width=6)
        box("豊川ガイド｜さくっとPR", font(FONT_BOLD, 22), W - 48, H - 52 - 40,
            pad_x=16, pad_y=9, r=8, right=True)

    out = im.convert("RGB")
    if output_path:
        out.save(output_path)
    return out


# ───────────────────────── 動作見本 ─────────────────────────

if __name__ == "__main__":
    outdir = ROOT / "_sample"
    outdir.mkdir(exist_ok=True)
    row = {
        "店名": "喫茶 とよかわ",
        "ひとことキャッチ": "朝7時から、やってます",
        "エリア・住所": "豊川市諏訪3丁目1-2",
        "備考": "【申込ページから】\n色：おまかせ（クリーム）\nかたち：額ぶち（写真なし）\nラベル：NEW OPEN",
    }
    render_45(row, output_path=outdir / "_pr_sample_45.png")
    render_169(row, output_path=outdir / "_pr_sample_169.png")
    print(f"  出力: {outdir}/_pr_sample_45.png / _pr_sample_169.png")
    # 写真ありの見本（リポ内の既存画像を流用）
    ph = next((ROOT.parent.parent / "images" / "feed").glob("*.png"), None)
    if ph:
        render_45(row, photo_path=ph, output_path=outdir / "_pr_sample_45_photo.png")
        render_169(row, photo_path=ph, output_path=outdir / "_pr_sample_169_photo.png")
        print(f"  出力: 写真あり版 ×2（サンプル写真: {ph.name}）")
