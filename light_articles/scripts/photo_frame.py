# -*- coding: utf-8 -*-
"""ライト記事の番号写真を豊川ガイド枠に入れる。
上＝元の豊川ガイドヘッダー(header_202606.png)＋投稿年月／下＝キツネ＋「さくっとお知らせ」(footer_sakutto.png)。
写真の上下は金(ゴールド)ライン（さくっとお知らせ帯と同じ金色）。
写真には既に日付＋ロゴが焼き込まれている前提（add_date_watermark 済み）。"""
import os, re
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
HEADER_H = 359
FOOTER_H = 359
CY0 = HEADER_H          # 写真 上端
CY1 = H - FOOTER_H      # 写真 下端（=991）
NAVY = (0, 58, 140)
GOLD = (212, 160, 23)   # さくっとお知らせ帯と同じ金
WHITE = (255, 255, 255)

_HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(_HERE, "_assets")
HEADER_IMG = os.path.join(ASSETS, "header_202606.png")
FOOTER_IMG = os.path.join(ASSETS, "footer_sakutto.png")   # キツネ＋「さくっとお知らせ」
HGMIN_E = os.path.join(ASSETS, "fonts", "HGRME.TTC")      # 年月用（HGS明朝E = index 2）


def _F(path, size, index=0):
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:
        return ImageFont.load_default()


def _cover(img, w, h):
    """アスペクト維持で w×h を埋めるようにリサイズ→中央クロップ"""
    iw, ih = img.size
    sc = max(w / iw, h / ih)
    nw, nh = int(iw * sc + 1), int(ih * sc + 1)
    im = img.resize((nw, nh), Image.LANCZOS)
    return im.crop(((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h))


def _put_frame(base, month=None):
    base.paste(Image.open(HEADER_IMG).convert("RGB"), (0, 0))
    base.paste(Image.open(FOOTER_IMG).convert("RGB"), (0, CY1))
    d = ImageDraw.Draw(base)
    # 写真の上下＝ゴールドの装飾ライン
    d.rectangle([0, CY0, W, CY0 + 6], fill=GOLD)
    d.rectangle([0, CY1 - 6, W, CY1], fill=GOLD)
    if month:   # 右上の年月ボックスを投稿月に差し替え
        m = re.search(r"(\d{4})\D+(\d{1,2})", month)
        if m:
            d.rectangle([606, 142, 1006, 320], fill=NAVY)
            d.line([(620, 151), (990, 151)], fill=WHITE, width=3)
            d.line([(620, 312), (990, 312)], fill=WHITE, width=3)
            df = _F(HGMIN_E, 58, index=2)
            t1 = f"{m.group(1)} 年"
            t2 = f"{int(m.group(2)):02d} 月"
            cx = 805
            b1 = d.textbbox((0, 0), t1, font=df)
            b2 = d.textbbox((0, 0), t2, font=df)
            d.text((cx - (b1[2] - b1[0]) / 2, 166), t1, font=df, fill=WHITE)
            d.text((cx - (b2[2] - b2[0]) / 2, 240), t2, font=df, fill=WHITE)


def frame_photo(src_path, out_path, month=None):
    """1枚の写真を豊川ガイド枠(1080×1350)に入れて out_path に保存し、そのパスを返す。
    month="2026年7月" のように渡すと右上の年月を差し替える。"""
    base = Image.new("RGB", (W, H), NAVY)
    base.paste(_cover(Image.open(src_path).convert("RGB"), W, CY1 - CY0), (0, CY0))
    _put_frame(base, month)
    base.save(out_path, quality=95)
    return out_path


if __name__ == "__main__":
    import sys
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "_frame_test.png"
    month = sys.argv[3] if len(sys.argv) > 3 else None
    print("SAVED", frame_photo(src, out, month))
