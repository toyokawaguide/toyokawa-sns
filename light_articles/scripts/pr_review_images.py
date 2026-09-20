# -*- coding: utf-8 -*-
"""さくっとPR 先方確認用の画像2枚を作る（2026-09-15 PR005 で確立）
  python pr_review_images.py --id PR005 [--date 2026-09-20]
  A: {ID} 各SNS確認用-1.png  … X / Threads / Instagram の投稿文を1枚に（URLの日付は「（公開日）」表示）
  B: {ID} Instagram確認用-N.png … IG 1枚目（額ぶちカード）＋2枚目（ポスター等のポラロイド枠）を左右に
出力先＝ G:\マイドライブ\さくっとPR\{ID}_*\ （_完成イメージ_{ID}.png と _完成イメージ_{ID}_IGカルーセル2枚目.png が必要）
絵文字は Segoe UI Emoji（単色）で描く。日本語は游ゴシック。
"""
import argparse, glob, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_builder, pr_intake
from sheets_client import read_all_rows
NL = chr(10)
FB = r"C:\Windows\Fonts\YuGothB.ttc"; FM = r"C:\Windows\Fonts\YuGothM.ttc"; FE = r"C:\Windows\Fonts\seguiemj.ttf"

def is_emoji(ch):
    o = ord(ch); return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or o == 0xFE0F
def runs(text):
    out = []
    for ch in text:
        k = "e" if is_emoji(ch) else "t"
        if out and out[-1][0] == k: out[-1][1] += ch
        else: out.append([k, ch])
    return out
def draw_runs(d, x, y, text, size, fill, bold=False):
    ft = ImageFont.truetype(FB if bold else FM, size); fe = ImageFont.truetype(FE, int(size * 0.92))
    for k, seg in runs(text):
        f = fe if k == "e" else ft
        d.text((x, y), seg, font=f, fill=fill); x += d.textlength(seg, font=f) + (4 if k == "e" else 0)
def width_of(d, text, size):
    ft = ImageFont.truetype(FM, size); fe = ImageFont.truetype(FE, int(size * 0.92))
    return sum(d.textlength(seg, font=(fe if k == "e" else ft)) + (4 if k == "e" else 0) for k, seg in runs(text))
def wrap(d, text, size, maxw):
    lines = []
    for para in text.split(NL):
        if not para: lines.append(""); continue
        cur = ""
        for ch in para:
            if width_of(d, cur + ch, size) > maxw and cur: lines.append(cur); cur = ch
            else: cur += ch
        lines.append(cur)
    return lines

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--id", required=True); ap.add_argument("--date", default="2026/01/01")
    a = ap.parse_args(); ID = a.id; ymd = a.date.replace("-", "/")
    row = next(r for r in read_all_rows(pr_intake.SHEET, spreadsheet_id=pr_intake.PR_SPREADSHEET_ID) if (r.get("ID") or "").strip() == ID)
    url = f"https://toyokawa-rentallife.com/{ymd}/{ID.lower()}/"
    caps = [("X（旧Twitter）", pr_builder.build_pr_x_caption(row, url)), ("Threads", pr_builder.build_pr_threads_caption(row, url)),
            ("Instagram（画像＋この文章）", pr_builder.build_pr_instagram_caption(row, url))]
    caps = [(h, t.replace(ymd, "（公開日）")) for h, t in caps]
    base = Path(r"G:/マイドライブ/さくっとPR"); D = Path(next(iter(sorted(glob.glob(str(base / f"{ID}_*"))))))
    W, PAD, SZ, LH = 1200, 60, 28, 44
    d0 = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    blocks = [(h, wrap(d0, t, SZ, W - PAD * 2 - 60)) for h, t in caps]
    H = PAD + 130 + sum(160 + len(ls) * LH for _, ls in blocks) + PAD
    im = Image.new("RGB", (W, H), (255, 255, 255)); d = ImageDraw.Draw(im); y = PAD
    draw_runs(d, PAD, y, "各SNSの投稿文（ご確認用）", 40, (20, 40, 90), bold=True); y += 60
    draw_runs(d, PAD, y, "※URLの「（公開日）」は、公開日が決まった時点で確定します。", 22, (110, 110, 110)); y += 70
    for h, ls in blocks:
        ph = 90 + len(ls) * LH + 40
        d.rounded_rectangle((PAD, y, W - PAD, y + ph), 18, fill=(246, 247, 250), outline=(205, 210, 220), width=2)
        d.rounded_rectangle((PAD, y, W - PAD, y + 60), 18, fill=(26, 58, 138)); d.rectangle((PAD, y + 30, W - PAD, y + 60), fill=(26, 58, 138))
        draw_runs(d, PAD + 24, y + 12, h, 30, (255, 255, 255), bold=True)
        yy = y + 90
        for ln in ls: draw_runs(d, PAD + 30, yy, ln, SZ, (30, 30, 30)); yy += LH
        y += ph + 30
    draw_runs(d, PAD, H - PAD - 10, "豊川ガイド｜さくっとPR", 22, (120, 120, 120))
    # ★ 社長が毎回手で付け直していた名前に合わせた（2026-09-21）
    outA = D / f"{ID} 各SNS確認用-1.png"; im.save(outA); print("A:", outA)
    card = Image.open(D / f"_完成イメージ_{ID}.png").convert("RGB")
    slides = sorted(D.glob(f"_完成イメージ_{ID}_IGカルーセル*.png"))
    G, T = 40, 70
    pics = [card] + [Image.open(s).convert("RGB") for s in slides]
    # 2026-09-18 社長指示「二つに分けて。見づらい」→ 1枚あたり最大4枚（カード＋写真3 …）に分割して出力
    PER = 4
    chunks = [pics[i:i + PER] for i in range(0, len(pics), PER)]
    for ci, chunk in enumerate(chunks):
        B = Image.new("RGB", (card.width * len(chunk) + G * (len(chunk) + 1), card.height + T + G * 2), (255, 255, 255)); db = ImageDraw.Draw(B)
        a0, a1 = ci * PER + 1, ci * PER + len(chunk)
        ttl = f"Instagramで使う画像（{a0}枚目〜{a1}枚目）" if len(chunks) > 1 else "Instagramで使う画像（左から1枚目・2枚目…）"
        draw_runs(db, G, 22, ttl, 32, (20, 40, 90), bold=True)
        for k, pic in enumerate(chunk): B.paste(pic, (G + k * (card.width + G), T + G))
        outB = D / f"{ID} Instagram確認用-{ci + 1}.png"
        B.save(outB); print("B:", outB)

if __name__ == "__main__":
    main()
