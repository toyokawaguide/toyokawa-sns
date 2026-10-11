# -*- coding: utf-8 -*-
"""IGフィード カルーセル2枚目「4位〜最下位の一覧」(1080×1350)
2026-10-11 社長指示「インスタのフィード投稿も全部出す」→ A案(カルーセル2枚目)。
並び順と★はキャプション(caption.make_instagram_reel_caption)と完全に同じロジックで作る:
  月/水/木 = data["items"] を stars 降順 / 金/土 = data["items"] の順＋get_top10_stars(seed)
火曜(4種)・日曜(週まとめ)は2枚目なし → None を返す。
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
from PIL import Image, ImageDraw

from uranai_monday import (BLUE, BEIGE, WHITE, GOLD, TEXT_DARK, STAR_EMPTY,
                           FB, FBd, FR, FM, f, draw_star, draw_text_centered_in_circle)
from uranai_fri_sat import get_top10_stars, format_star_score

W, H = 1080, 1350
HEADER_H = 135
FOOTER_Y = 1215
INCLUDE_FRI_SAT = False


def _first_sentence(s: str, n: int = 22) -> str:
    s = (s or "").strip()
    for sep in ("。", "！", "!", "？", "?"):
        i = s.find(sep)
        if 0 <= i < n:
            return s[: i + 1]
    return s if len(s) <= n else s[: n - 1] + "…"


def _ranked(weekday_key: str, data: dict, target_date: date):
    items = list(data.get("items", []))
    if weekday_key in ("mon", "wed", "thu"):
        items = sorted(items, key=lambda x: -x.get("stars", 0))
        return [(i + 1, it["label"], int(it.get("stars", 0)), None, it.get("comment", "")) for i, it in enumerate(items)]
    if weekday_key in ("fri", "sat") and not INCLUDE_FRI_SAT:
        return []   # 金土は1枚目にTOP10が全部載っているので2枚目は出さない（2026-10-11）
    if weekday_key in ("fri", "sat"):
        seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
        stars = get_top10_stars(seed=seed)
        return [(i + 1, it["label"], None, stars[i] if i < len(stars) else 0, it.get("comment", ""))
                for i, it in enumerate(items[:10])]
    return []


def generate_ig_ranking_slide(target_date: date, weekday_key: str, data: dict, output_path) -> Path | None:
    rows = _ranked(weekday_key, data, target_date)[3:]
    if not rows:
        return None
    img = Image.new("RGB", (W, H), BEIGE)
    d = ImageDraw.Draw(img)

    # ヘッダー（1枚目の _finalize_ig_image と同じ）
    d.rectangle([0, 0, W, HEADER_H], fill=BLUE)
    d.text((40, 25), "豊川ガイド", font=f(FB, 56), fill=WHITE)
    d.text((44, 95), "toyokawaguide", font=f(FR, 22), fill=WHITE)
    yf = f(FB, 34)
    for k, txt in enumerate([f"{target_date.year}年", f"{target_date.month:02d}月"]):
        b = d.textbbox((0, 0), txt, font=yf)
        d.text((W - (b[2] - b[0]) - 40, 25 + k * 50), txt, font=yf, fill=WHITE)

    # タイトル
    last = rows[-1][0]
    title = f"今日のランキング　4位〜{last}位"
    tf = f(FB, 44)
    tb = d.textbbox((0, 0), title, font=tf)
    ty = HEADER_H + 34
    d.text(((W - (tb[2] - tb[0])) // 2, ty), title, font=tf, fill=BLUE)
    draw_star(d, (W - (tb[2] - tb[0])) // 2 - 40, ty + 30, 20, GOLD)
    draw_star(d, (W + (tb[2] - tb[0])) // 2 + 40, ty + 30, 20, GOLD)
    d.rectangle([(W - 200) // 2, ty + 78, (W + 200) // 2, ty + 83], fill=GOLD)

    # 行
    top = ty + 110
    avail = FOOTER_Y - 20 - top
    gap = 10
    rh = min(118, (avail - gap * (len(rows) - 1)) // len(rows))
    x0, x1 = 50, W - 50
    name_f = f(FB, 36 if rh >= 100 else 32)
    cm_f = f(FM, 23)
    for k, (rank, label, s10, s_top10, comment) in enumerate(rows):
        y = top + k * (rh + gap)
        d.rounded_rectangle([x0, y, x1, y + rh], radius=18, fill=WHITE, outline=BLUE, width=3)
        cx, cy, cr = x0 + 62, y + rh // 2, min(38, rh // 2 - 8)
        d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=BLUE)
        draw_text_centered_in_circle(d, cx, cy, str(rank), f(FB, 38 if rank < 10 else 32), WHITE)
        nx = x0 + 125
        d.text((nx, y + 10), label, font=name_f, fill=BLUE)
        d.text((nx, y + rh - 38), _first_sentence(comment), font=cm_f, fill=TEXT_DARK)
        # 右側の★
        if s10 is not None:
            ss, sg = 11, 23
            sx0 = x1 - 10 * sg - 22
            for s in range(10):
                draw_star(d, sx0 + s * sg + ss, y + 30, ss, GOLD if s < s10 else STAR_EMPTY)
            sc = f"{s10}/10"
        else:
            sc = format_star_score(s_top10)
        scf = f(FBd, 28 if s10 is None else 22)
        sb = d.textbbox((0, 0), sc, font=scf)
        d.text((x1 - (sb[2] - sb[0]) - 24, y + rh - 40 if s10 is not None else cy - 18), sc, font=scf, fill=GOLD)

    # フッター（1枚目と同じ）
    d.rectangle([0, FOOTER_Y, W, H], fill=BLUE)
    ff = f(FB, 30)
    for i, line in enumerate(["▶ プロフィールリンクから", "トップの「今日の占い」コーナーへ"]):
        lb = d.textbbox((0, 0), line, font=ff)
        d.text(((W - (lb[2] - lb[0])) // 2, FOOTER_Y + 25 + i * 45), line, font=ff, fill=WHITE)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out))
    return out
