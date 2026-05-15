"""
豊川ガイド占い Instagram Reels 動画生成
========================================

既存の `_generate_top3_instagram` (1080×1080・IG feed) のレイアウトを流用し、
1080×1920縦長・3シーン構成のリール動画を生成する。

シーン構成（15秒・各5秒）:
  シーン1: 1〜6位カードリスト
  シーン2: 7〜12位カードリスト
  シーン3: ラッキースポット拡大表示

使い方:
  from generate_reel import generate_reel
  generate_reel(target_date=date(...), weekday_key="thu",
                items=items_list, spot=lucky_spot_dict,
                output_path=Path("output.mp4"),
                badge_text="今日は木曜・木星の日",
                sub_title="今日のラッキー干支ランキング",
                hashtag_keyword="干支")
"""
from __future__ import annotations
import glob
import os
import platform
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 既存IG画像関数の定数・ヘルパーを再利用
from uranai_wed_thu import (
    BLUE, BEIGE, WHITE, GOLD, SILVER, BRONZE,
    TEXT_DARK, TEXT_GRAY, STAR_EMPTY,
    FB, FBd, FR, FM, f, draw_star, draw_text_centered_in_circle,
    draw_jupiter_icon, draw_mercury_icon, date_to_str,
    _LOGO_PATH,
)

# ============================================================
# キャンバス設定
# ============================================================

REEL_W = 1080
REEL_H = 1920
FPS = 30

# IG Reels のUIオーバーレイ安全エリア
# 上: 「リール」テキスト・戻る・カメラアイコンが重なる帯
# 右: いいね/コメント/シェア/保存/プロフ ボタンが重なる帯
# 下: キャプション・ユーザー名・音源情報が重なる帯
SAFE_TOP = 180     # 上部UI被り回避
SAFE_RIGHT = 200   # 1080-200=880 までがコンテンツ領域（右の縦書きロゴ用を広め確保）
SAFE_BOTTOM = 320  # 1920-320=1600 までがコンテンツ領域
SIDEBAR_W = 100    # （未使用・互換のため残置）
CONTENT_LEFT = 40
CONTENT_RIGHT = REEL_W - SAFE_RIGHT   # 940
CONTENT_W = CONTENT_RIGHT - CONTENT_LEFT  # 900
CONTENT_BOTTOM = REEL_H - SAFE_BOTTOM  # 1600
CONTENT_CX = (CONTENT_LEFT + CONTENT_RIGHT) // 2  # 490（コンテンツ領域の中央X）

# 各シーンの表示秒数
SCENE_DURATIONS = {"top_first": 5.0, "top_second": 5.0, "spot": 5.0}


# ============================================================
# 共通ヘルパー（既存IG画像と統一）
# ============================================================

def _draw_header(d: ImageDraw.ImageDraw, img: Image.Image,
                 target_date: date) -> int:
    """画面上部のロゴ・タイトル・日付（紺背景上に白文字）。

    SAFE_TOPぶん下げて上部IGUI被り回避。
    ロゴは CONTENT_RIGHT(940) より左に置く（右側のIGアイコンに被らないように）。
    返り値は次の描画開始Y（ヘッダー下端）。"""
    HEADER_H = 240
    top = SAFE_TOP
    # ベース背景がBLUEなので帯描画は不要

    # 「豊川ガイド」と「toyokawaguide」を左上（大きくドカン）
    d.text((40, top - 10), "豊川ガイド", font=f(FBd, 96), fill=WHITE)
    d.text((48, top + 110), "toyokawaguide", font=f(FR, 26), fill=WHITE)

    # 日付（左下大きく）
    date_str = date_to_str(target_date)
    d.text((40, top + 160), date_str, font=f(FBd, 50), fill=WHITE)

    # ロゴは _draw_vertical_sidebar() 側で右側に配置するためここでは描かない

    return top + HEADER_H


def _draw_vertical_sidebar(d: ImageDraw.ImageDraw, img: Image.Image) -> None:
    """右側のロゴ＋縦書き「豊川市の地域メディア」（白文字）を縦並びで描画。

    レイアウト:
      - ロゴ: SAFE_TOP直下、右側エリア中央x
      - 縦書き: 左の日付と同じ高さから開始（top+150 ≈ y=330）
    """
    # x位置: SAFE_RIGHT(200px)エリアの中央
    cx = REEL_W - SAFE_RIGHT // 2

    # ロゴを右側エリア上部に配置
    try:
        logo_orig = Image.open(_LOGO_PATH)
        target_h = 130
        ratio = target_h / logo_orig.size[1]
        target_w = int(logo_orig.size[0] * ratio)
        logo = logo_orig.resize((target_w, target_h))
        # 縦位置: SAFE_TOP の少し下（y=190付近）
        logo_y = SAFE_TOP + 10
        logo_x = cx - target_w // 2
        img.paste(logo, (logo_x, logo_y),
                  logo if logo.mode == "RGBA" else None)
    except Exception:
        pass

    # 縦書きテキスト（コンパクトに）
    text = "豊川市の地域メディア"
    fnt = f(FBd, 34)
    char_h = 55
    # 縦書き開始Y: 左の日付と同じ高さ（SAFE_TOP+160 = 340）
    start_y = SAFE_TOP + 160
    for i, ch in enumerate(text):
        cb = d.textbbox((0, 0), ch, font=fnt)
        cw = cb[2] - cb[0]
        d.text((cx - cw // 2, start_y + i * char_h), ch, font=fnt, fill=WHITE)


def _draw_title_section(d: ImageDraw.ImageDraw, top_y: int,
                        badge_text: str, sub_title: str,
                        rank_label: str = "1〜6位",
                        draw_planet_icon=draw_jupiter_icon) -> int:
    """タイトル＋バッジ＋サブタイトル（既存IGテンプレ準拠）

    すべてコンテンツ領域(CONTENT_LEFT〜CONTENT_RIGHT)内に収める。

    Args:
        top_y: 描画開始Y
        rank_label: "1〜6位" or "7〜12位" or "本日のスポット"
    Returns:
        次の描画開始Y
    """
    # タイトル「豊川ガイド的　今日の占い」★装飾付き（紺背景なので白文字）
    title_y = top_y + 20
    draw_star(d, CONTENT_LEFT + 90, title_y + 35, 26, GOLD)
    draw_star(d, CONTENT_RIGHT - 90, title_y + 35, 26, GOLD)
    title = "豊川ガイド的　 今日の占い"
    tf = f(FB, 50)
    tb = d.textbbox((0, 0), title, font=tf)
    d.text((CONTENT_CX - (tb[2] - tb[0]) // 2, title_y), title, font=tf, fill=WHITE)

    # バッジ（白いピル・中の文字は紺のまま）
    badge_y = title_y + 85
    bdf = f(FM, 22)
    bdb = d.textbbox((0, 0), badge_text, font=bdf)
    text_w = bdb[2] - bdb[0]
    icon_size = 18
    icon_gap = 10
    badge_w = text_w + icon_size + icon_gap + 50
    badge_h = 38
    badge_x = CONTENT_CX - badge_w // 2
    d.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                        radius=19, fill=WHITE, outline=GOLD, width=2)
    draw_planet_icon(d, badge_x + 22, badge_y + badge_h // 2 - 2,
                     icon_size, GOLD, WHITE)
    d.text((badge_x + 22 + icon_size // 2 + icon_gap + 6, badge_y + 5),
           badge_text, font=bdf, fill=BLUE)

    # サブタイトル（紺背景なので白文字）
    sf = f(FM, 30)
    sub_with_rank = f"{sub_title}　〜{rank_label}〜"
    sb = d.textbbox((0, 0), sub_with_rank, font=sf)
    d.text((CONTENT_CX - (sb[2] - sb[0]) // 2, badge_y + badge_h + 12),
           sub_with_rank, font=sf, fill=WHITE)

    # 「当たるも八卦」（紺背景なのでベージュ系で）
    yurusa = "〜当たるも八卦　当たらぬも八卦〜"
    yf = f(FM, 21)
    yb = d.textbbox((0, 0), yurusa, font=yf)
    d.text((CONTENT_CX - (yb[2] - yb[0]) // 2, badge_y + badge_h + 56),
           yurusa, font=yf, fill=BEIGE)

    # 金色ライン
    line_y = badge_y + badge_h + 92
    d.rectangle([CONTENT_CX - 100, line_y, CONTENT_CX + 100, line_y + 5],
                fill=GOLD)

    return line_y + 30


# ============================================================
# シーン: TOP6 カードリスト（1-6位 or 7-12位）
# ============================================================

def _scene_top5(target_date: date, items: list, *,
                rank_offset: int, rank_label: str,
                badge_text: str, sub_title: str,
                draw_planet_icon,
                weekday_key: str | None = None) -> Image.Image:
    """5枚のカードを縦並びで描画（ベース紺色背景・白文字＋白カード）
    社長要望：1ページ5位ずつ・統一感保持・不足は「—」表示の同サイズカード"""
    img = Image.new("RGB", (REEL_W, REEL_H), BLUE)
    d = ImageDraw.Draw(img)

    header_h = _draw_header(d, img, target_date)
    content_y = _draw_title_section(d, header_h, badge_text, sub_title,
                                    rank_label=rank_label,
                                    draw_planet_icon=draw_planet_icon)

    # カード設定（5枚化で縦に余裕ができるためカード高さを大きくし読みやすく）
    card_x = CONTENT_LEFT       # 40
    card_w = CONTENT_W          # 900
    card_h = 180
    card_gap = 18
    card_y0 = content_y

    rank_color = lambda r: GOLD if r == 1 else SILVER if r == 2 else BRONZE if r == 3 else (180, 200, 220)

    # 渡された分のカードだけ描画（5枠固定にせず・空欄カードを追加しない）
    # 例：シーン3「11〜12位」は2枚カードのみ／火曜の血液型は4枚のみ
    use_items = items[:5]

    for i, it in enumerate(use_items):
        rank = rank_offset + i + 1
        y = card_y0 + i * (card_h + card_gap)

        # カード枠
        d.rounded_rectangle([card_x, y, card_x + card_w, y + card_h],
                            radius=22, fill=WHITE, outline=BLUE, width=3)

        # 順位バッジ円
        cx = card_x + 85
        cy = y + card_h // 2
        cr = 58
        d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=rank_color(rank))
        rank_font = f(FB, 62 if rank < 10 else 48)
        draw_text_centered_in_circle(d, cx, cy, str(rank), rank_font, WHITE)

        # 名前（金/土は文字数多いのでテキストブロックを上下中央配置）
        nx = card_x + 170
        name = it.get("name", "")
        if weekday_key in ("fri", "sat"):
            # 名前(38px) + c1(26px) + c2(26px) ≒ 130px 高のブロックを card 中央に
            name_y = y + (card_h - 130) // 2
            c1_y = name_y + 50
            c2_y = c1_y + 42
        else:
            name_y = y + 22
            c1_y = y + 86
            c2_y = y + 128
        d.text((nx, name_y), name, font=f(FB, 38), fill=BLUE)

        # filled は dict 経由でも 0-10 範囲（_normalize_item で正規化済）・小数許容
        filled_raw = it.get("filled", 0)
        try:
            filled = float(filled_raw)
        except (TypeError, ValueError):
            filled = 0.0
        filled_disp = int(filled) if filled == int(filled) else round(filled, 1)

        if weekday_key in ("fri", "sat"):
            # 金/土：星マーク列は表示せず「★N」を大きく中央配置（社長要望）
            score_text = f"★{filled_disp}"
            scf = f(FBd, 50)
            scb = d.textbbox((0, 0), score_text, font=scf)
            sw = scb[2] - scb[0]
            sh = scb[3] - scb[1]
            d.text((card_x + card_w - sw - 36,
                    y + (card_h - sh) // 2 - scb[1]),
                   score_text, font=scf, fill=GOLD)
        else:
            # 月/水/木：星マーク列＋N/10 表記
            STAR_EMPTY_DARK = (140, 150, 170)
            star_size = 14
            star_gap = 28
            stars_x_start = card_x + card_w - 5 * star_gap - 28
            for s in range(5):
                sx = stars_x_start + s * star_gap + star_size
                color = GOLD if s < filled else STAR_EMPTY_DARK
                draw_star(d, sx, y + 38, star_size, color)
            for s in range(5, 10):
                sx = stars_x_start + (s - 5) * star_gap + star_size
                color = GOLD if s < filled else STAR_EMPTY_DARK
                draw_star(d, sx, y + 74, star_size, color)
            score_text = f"{filled_disp}/10"
            scf = f(FBd, 24)
            scb = d.textbbox((0, 0), score_text, font=scf)
            d.text((card_x + card_w - (scb[2] - scb[0]) - 28, y + 115),
                   score_text, font=scf, fill=GOLD)

        # コメント（c1, c2 の2行・固定フォントサイズ26px）
        comment_font = f(FM, 26)
        d.text((nx, c1_y), it.get("c1", ""), font=comment_font, fill=TEXT_DARK)
        d.text((nx, c2_y), it.get("c2", ""), font=comment_font, fill=TEXT_DARK)

    _draw_vertical_sidebar(d, img)
    return img


# ============================================================
# シーン: 日曜・今週まとめ（フィード投稿準拠）
# ============================================================

def _scene_sunday_summary(target_date: date, data: dict, *,
                          badge_text: str, draw_planet_icon) -> Image.Image:
    """日曜版：今週のラッキースポット振り返り＋スポット募集
    サイドバー（縦書きロゴ）を除いた領域の中央に全要素を配置（社長要望）"""
    img = Image.new("RGB", (REEL_W, REEL_H), BLUE)
    d = ImageDraw.Draw(img)

    header_h = _draw_header(d, img, target_date)
    # サイドバー（縦書きロゴ）を除いた表示領域
    # 左 CONTENT_LEFT (40) 〜 右 REEL_W - SAFE_RIGHT (880・SAFE_RIGHT=200)
    CW = REEL_W - SAFE_RIGHT  # = 880（サイドバー左端）
    content_x_left = CONTENT_LEFT  # 40
    content_x_right = CW  # 880
    center_x = CW // 2  # 440 = サイドバーを除いた領域の中央

    # ---------- メインタイトル ----------
    title_y = header_h + 40
    title = "豊川ガイド的　今週のまとめ"
    tf = f(FB, 54)
    tb = d.textbbox((0, 0), title, font=tf)
    title_w = tb[2] - tb[0]
    title_x = (CONTENT_LEFT + CW - title_w) // 2
    # 左右の星（タイトル幅基準で配置）
    star_size = 28
    star_y = title_y + tf.size // 2 - star_size // 2
    draw_star(d, title_x - 50, star_y + star_size, star_size, GOLD)
    draw_star(d, title_x + title_w + 50, star_y + star_size, star_size, GOLD)
    d.text((title_x, title_y), title, font=tf, fill=WHITE)

    # ---------- バッジ ----------
    badge_y = title_y + 92
    bdf = f(FM, 22)
    bdb = d.textbbox((0, 0), badge_text, font=bdf)
    text_w = bdb[2] - bdb[0]
    icon_size = 18
    icon_gap = 10
    badge_w = text_w + icon_size + icon_gap + 50
    badge_h = 40
    badge_x = (CONTENT_LEFT + CW - badge_w) // 2
    d.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                        radius=20, fill=WHITE, outline=GOLD, width=2)
    draw_planet_icon(d, badge_x + 22, badge_y + badge_h // 2 - 2, icon_size, GOLD, WHITE)
    d.text((badge_x + 22 + icon_size // 2 + icon_gap + 6, badge_y + 6),
           badge_text, font=bdf, fill=BLUE)

    # ---------- サブテキスト ----------
    sub_y = badge_y + badge_h + 18
    sub = "今週のおさらい&ラッキースポット募集中!"
    sf = f(FBd, 30)
    sb = d.textbbox((0, 0), sub, font=sf)
    d.text(((CONTENT_LEFT + CW - (sb[2] - sb[0])) // 2, sub_y), sub, font=sf, fill=WHITE)

    # 金線（タイトル幅程度・中央配置）
    line_y = sub_y + 50
    d.rectangle([(CONTENT_LEFT + CW - 200) // 2, line_y, (CW + 200) // 2, line_y + 4], fill=GOLD)

    # ===== セクション1: 今週のラッキースポットおさらい =====
    sec1_y = line_y + 30
    sec1_h = 560
    sec1_r = 24
    d.rounded_rectangle([content_x_left, sec1_y, content_x_right, sec1_y + sec1_h],
                        radius=sec1_r, fill=WHITE, outline=GOLD, width=3)

    sec1_title = "◆ 今週のラッキースポットおさらい"
    s1tf = f(FBd, 32)
    d.text((content_x_left + 36, sec1_y + 24), sec1_title, font=s1tf, fill=BLUE)
    s1tb = d.textbbox((0, 0), sec1_title, font=s1tf)
    # 下線：タイトル全幅に引く（最後の「い」まで覆う）
    d.rectangle([content_x_left + 36, sec1_y + 64,
                 content_x_left + 36 + (s1tb[2] - s1tb[0]), sec1_y + 68], fill=GOLD)

    spots_week = data.get("spots_week", {})
    # 日付 = 日曜から逆算（月=6日前、火=5日前、…、土=1日前）
    day_labels = [("月", "mon", 6), ("火", "tue", 5), ("水", "wed", 4),
                  ("木", "thu", 3), ("金", "fri", 2), ("土", "sat", 1)]
    spot_y_start = sec1_y + 110
    spot_h = 62
    spot_gap = 10
    badge_size = 48
    from datetime import timedelta as _td
    # 日付フィールドを右揃えで揃える: 5/24 など最大幅を計算
    date_font = f(FBd, 26)
    max_date_w = 0
    for _, _, days_ago in day_labels:
        pd = target_date - _td(days=days_ago)
        bbox = d.textbbox((0, 0), f"{pd.month}/{pd.day}", font=date_font)
        max_date_w = max(max_date_w, bbox[2] - bbox[0])
    date_x_start = content_x_left + 36
    badge_x = date_x_start + max_date_w + 20  # 日付の右に余白20pxとってバッジ
    for i, (jp, key, days_ago) in enumerate(day_labels):
        sy = spot_y_start + i * (spot_h + spot_gap)
        past_date = target_date - _td(days=days_ago)
        md = f"{past_date.month}/{past_date.day}"
        # 日付（右揃え：max_date_w 内で右寄せ・白ボックス上なので紺色文字）
        dbox = d.textbbox((0, 0), md, font=date_font)
        md_w = dbox[2] - dbox[0]
        d.text((date_x_start + max_date_w - md_w,
                sy + (spot_h - 26) // 2),
               md, font=date_font, fill=BLUE)
        # 曜日バッジ
        by = sy + (spot_h - badge_size) // 2
        d.rounded_rectangle([badge_x, by, badge_x + badge_size, by + badge_size],
                            radius=10, fill=BLUE)
        bf = f(FB, 30)
        bbox = d.textbbox((0, 0), jp, font=bf)
        d.text((badge_x + (badge_size - (bbox[2] - bbox[0])) // 2,
                by + (badge_size - (bbox[3] - bbox[1])) // 2 - bbox[1]),
               jp, font=bf, fill=WHITE)
        # スポット名
        spot_name = spots_week.get(key, "—")
        spf = f(FBd, 30)
        d.text((badge_x + badge_size + 22, sy + (spot_h - 30) // 2),
               spot_name, font=spf, fill=TEXT_DARK)

    # ===== セクション2: 募集ボックス（青基調・既存通り） =====
    sec2_y = sec1_y + sec1_h + 30
    sec2_h = 340
    d.rounded_rectangle([content_x_left, sec2_y, content_x_right, sec2_y + sec2_h],
                        radius=24, fill=BLUE, outline=GOLD, width=3)

    sec2_title = "★ ラッキースポット、絶賛募集中!"
    s2tf = f(FBd, 32)
    s2tb = d.textbbox((0, 0), sec2_title, font=s2tf)
    d.text(((CONTENT_LEFT + CW - (s2tb[2] - s2tb[0])) // 2, sec2_y + 28),
           sec2_title, font=s2tf, fill=GOLD)
    d.rectangle([content_x_left + 70, sec2_y + 80,
                 content_x_right - 70, sec2_y + 82], fill=GOLD)

    quote1 = "自分がそう思ったら"
    quote2 = "もうラッキースポットでいいんじゃない?"
    qf = f(FB, 32)
    q1b = d.textbbox((0, 0), quote1, font=qf)
    q2b = d.textbbox((0, 0), quote2, font=qf)
    d.text(((CONTENT_LEFT + CW - (q1b[2] - q1b[0])) // 2, sec2_y + 110),
           quote1, font=qf, fill=WHITE)
    d.text(((CONTENT_LEFT + CW - (q2b[2] - q2b[0])) // 2, sec2_y + 158),
           quote2, font=qf, fill=WHITE)

    byline = "— by 豊川ガイド"
    bynf = f(FM, 24)
    bynb = d.textbbox((0, 0), byline, font=bynf)
    # 右端を下罫線の右端（content_x_right - 70）に合わせて枠内に収める
    d.text((content_x_right - (bynb[2] - bynb[0]) - 70, sec2_y + 210),
           byline, font=bynf, fill=GOLD)

    # 下の罫線：byline の下端より十分下に配置（byline をしっかり枠内に収める）
    d.rectangle([content_x_left + 70, sec2_y + 252,
                 content_x_right - 70, sec2_y + 254], fill=GOLD)

    foot_msg = "自薦・他薦どっちもOK!お気軽にどうぞ"
    fmf = f(FBd, 26)
    fmb = d.textbbox((0, 0), foot_msg, font=fmf)
    d.text(((CONTENT_LEFT + CW - (fmb[2] - fmb[0])) // 2, sec2_y + 274),
           foot_msg, font=fmf, fill=GOLD)

    # ---------- フッター注釈 + プロフィール誘導 ----------
    note_y = sec2_y + sec2_h + 30
    note = "※プロフィールのリンクから、お気軽に教えてくださいませ"
    nf = f(FM, 22)
    nb = d.textbbox((0, 0), note, font=nf)
    d.text(((CONTENT_LEFT + CW - (nb[2] - nb[0])) // 2, note_y),
           note, font=nf, fill=GOLD)

    foot_text1 = "▶ プロフィールリンクから"
    foot_text2 = "トップの「今日の占い」コーナーへ"
    ftf = f(FBd, 30)
    ft1b = d.textbbox((0, 0), foot_text1, font=ftf)
    ft2b = d.textbbox((0, 0), foot_text2, font=ftf)
    d.text(((CONTENT_LEFT + CW - (ft1b[2] - ft1b[0])) // 2, note_y + 50),
           foot_text1, font=ftf, fill=WHITE)
    d.text(((CONTENT_LEFT + CW - (ft2b[2] - ft2b[0])) // 2, note_y + 100),
           foot_text2, font=ftf, fill=WHITE)

    _draw_vertical_sidebar(d, img)
    return img


# ============================================================
# シーン: ラッキースポット拡大
# ============================================================

def _scene_spot(target_date: date, lucky_spot: dict, *,
                badge_text: str, sub_title: str,
                draw_planet_icon) -> Image.Image:
    """ラッキースポットだけを大きく見せるシーン（紺背景＋白カードボックス）"""
    img = Image.new("RGB", (REEL_W, REEL_H), BLUE)
    d = ImageDraw.Draw(img)

    header_h = _draw_header(d, img, target_date)

    # シンプルな中央タイトル「本日のラッキースポット」
    content_y = header_h + 40

    # 大タイトル（紺背景なので白文字）
    title = "豊川ガイド的　今日の占い"
    tf = f(FB, 50)
    tb = d.textbbox((0, 0), title, font=tf)
    draw_star(d, CONTENT_LEFT + 90, content_y + 35, 26, GOLD)
    draw_star(d, CONTENT_RIGHT - 90, content_y + 35, 26, GOLD)
    d.text((CONTENT_CX - (tb[2] - tb[0]) // 2, content_y), title, font=tf, fill=WHITE)

    # 金色ライン（タイトル下のセパレータ）
    d.rectangle([CONTENT_CX - 120, content_y + 110,
                 CONTENT_CX + 120, content_y + 115], fill=GOLD)

    # 白色ボックス＋ゴールド枠（コンテンツ領域内・紺背景から浮き立つ）
    box_x0 = CONTENT_LEFT + 20
    box_x1 = CONTENT_RIGHT - 20
    box_y = content_y + 150
    box_h = 420
    d.rounded_rectangle([box_x0, box_y, box_x1, box_y + box_h],
                        radius=28, fill=WHITE, outline=GOLD, width=5)
    box_cx = (box_x0 + box_x1) // 2

    # ボックス内ヘッダー（白背景なので紺文字）
    header_line = "管理人の独断と偏見と忖度による"
    hf = f(FBd, 34)
    hb = d.textbbox((0, 0), header_line, font=hf)
    d.text((box_cx - (hb[2] - hb[0]) // 2, box_y + 40),
           header_line, font=hf, fill=BLUE)

    sub_header = "【本日のラッキースポット】"
    hf2 = f(FBd, 38)
    hb2 = d.textbbox((0, 0), sub_header, font=hf2)
    d.text((box_cx - (hb2[2] - hb2[0]) // 2, box_y + 100),
           sub_header, font=hf2, fill=BLUE)

    # スポット名（大きく・白背景なので紺文字）
    name = lucky_spot.get("name", "")
    max_w = box_x1 - box_x0 - 60
    name_size = 110 if len(name) <= 6 else 90 if len(name) <= 10 else 64
    nf = f(FB, name_size)
    nb = d.textbbox((0, 0), name, font=nf)
    if (nb[2] - nb[0]) > max_w:
        name_size = max(48, name_size - 20)
        nf = f(FB, name_size)
        nb = d.textbbox((0, 0), name, font=nf)
    d.text((box_cx - (nb[2] - nb[0]) // 2, box_y + 220),
           name, font=nf, fill=BLUE)
    # エリア表示は削除

    # 注意書き（紺背景なのでベージュ・大きく）
    note = "※ラッキースポットがお休みのときは"
    note2 = "また別の日に行ってみてね！"
    nof = f(FM, 30)
    for i, ln in enumerate([note, note2]):
        nob = d.textbbox((0, 0), ln, font=nof)
        d.text((CONTENT_CX - (nob[2] - nob[0]) // 2, box_y + box_h + 45 + i * 46),
               ln, font=nof, fill=BEIGE)

    # 「ラッキースポット絶賛募集中」コールアウト
    cb_x0 = CONTENT_LEFT + 40
    cb_x1 = CONTENT_RIGHT - 40
    cb_y = box_y + box_h + 170
    cb_h = 130
    d.rounded_rectangle([cb_x0, cb_y, cb_x1, cb_y + cb_h],
                        radius=20, fill=BLUE, outline=GOLD, width=4)
    cb_cx = (cb_x0 + cb_x1) // 2

    # メインコピー
    main_msg = "ラッキースポット絶賛募集中！"
    mf = f(FBd, 36)
    mb = d.textbbox((0, 0), main_msg, font=mf)
    # 左右に★を添える
    star_offset = 26
    draw_star(d, cb_cx - (mb[2] - mb[0]) // 2 - star_offset, cb_y + 38, 18, GOLD)
    draw_star(d, cb_cx + (mb[2] - mb[0]) // 2 + star_offset, cb_y + 38, 18, GOLD)
    d.text((cb_cx - (mb[2] - mb[0]) // 2, cb_y + 22),
           main_msg, font=mf, fill=GOLD)

    # サブコピー
    sub_msg = "DMでこっそり教えてね♪"
    sf2 = f(FM, 26)
    sb2 = d.textbbox((0, 0), sub_msg, font=sf2)
    d.text((cb_cx - (sb2[2] - sb2[0]) // 2, cb_y + 78),
           sub_msg, font=sf2, fill=WHITE)

    _draw_vertical_sidebar(d, img)
    return img


# ============================================================
# 公開エントリポイント
# ============================================================

def _split_comment_for_card(comment: str) -> tuple[str, str]:
    """コメントを2行に分割（句点 → 読点 → 等分の優先順位）"""
    comment = (comment or "").strip()
    if "。" in comment:
        idx = comment.index("。")
        return comment[:idx + 1], comment[idx + 1:].strip()
    if "、" in comment:
        idx = comment.index("、")
        return comment[:idx + 1], comment[idx + 1:].strip()
    half = len(comment) // 2
    return comment[:half], comment[half:]


def _normalize_item(it) -> dict:
    """ArticleItem (dataclass) or dict を {name, c1, c2, filled, rank} に正規化

    dict が来た場合も、name/c1/c2/filled キーが無ければ label/comment/stars から
    生成する。raw data の items は dict 形式（label/stars/comment）で来るため、
    そのままだと _scene で filled=0 として描画されてしまうのを防ぐ。
    """
    if isinstance(it, dict):
        out = dict(it)  # 元の dict は変更しない
        if "name" not in out and "label" in out:
            out["name"] = out["label"]
        if ("c1" not in out or "c2" not in out) and "comment" in out:
            c1, c2 = _split_comment_for_card(out["comment"])
            out.setdefault("c1", c1)
            out.setdefault("c2", c2)
        if "filled" not in out and "stars" in out:
            s = out["stars"]
            try:
                s_num = float(s) if s is not None else 0
            except (TypeError, ValueError):
                s_num = 0
            # stars は generate_text.py が 0-10 範囲で出力する前提（×2はしない）
            # 旧仕様の×2は stars=5 を stars=10 と同列にして順位逆転を起こすため廃止
            out["filled"] = s_num
        return out
    # dataclass (ArticleItem: rank, label, stars 0-10, comment, extras)
    rank = getattr(it, "rank", None)
    label = getattr(it, "label", "") or ""
    stars = float(getattr(it, "stars", 0) or 0)
    comment = (getattr(it, "comment", "") or "").strip()
    c1, c2 = _split_comment_for_card(comment)
    return {
        "name": label,
        "c1": c1,
        "c2": c2,
        "filled": stars,
        "rank": rank,
    }


# 曜日別のメタ情報（generate_image.py と統一）
WEEKDAY_META = {
    "mon": {"badge": "今日は月曜・月の日", "sub": "今日のラッキー星座ランキング", "hashtag": "星座",
            "planet_icon": "moon"},
    "tue": {"badge": "今日は火曜・火星の日", "sub": "今日のラッキー血液型ランキング", "hashtag": "血液型",
            "planet_icon": "mars"},
    "wed": {"badge": "今日は水曜・水星の日", "sub": "今日のラッキー誕生月ランキング", "hashtag": "月生まれ",
            "planet_icon": "mercury"},
    "thu": {"badge": "今日は木曜・木星の日", "sub": "今日のラッキー干支ランキング", "hashtag": "干支",
            "planet_icon": "jupiter"},
    "fri": {"badge": "今日は金曜・金星の日", "sub": "今日のラッキー生まれ年ランキング", "hashtag": "生まれ年",
            "planet_icon": "venus"},
    "sat": {"badge": "今日は土曜・土星の日", "sub": "今日のラッキー町名ランキング", "hashtag": "町名",
            "planet_icon": "saturn"},
    "sun": {"badge": "今日は日曜・太陽の日", "sub": "今週のラッキースポット振り返り", "hashtag": "週まとめ",
            "planet_icon": "sun"},
}


def _planet_icon_func(name: str):
    # uranai_wed_thu に jupiter/mercury 以外も入っていれば import
    if name == "mercury":
        return draw_mercury_icon
    # 他の惑星は後で uranai_*.py から import 追加可能
    return draw_jupiter_icon  # デフォルト


def generate_reel(*, target_date: date, weekday_key: str,
                  items: list, spot: dict,
                  output_path: Path,
                  data: dict | None = None) -> Path:
    """リール動画(15秒・3シーン・1080×1920)を生成"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    meta = WEEKDAY_META.get(weekday_key, WEEKDAY_META["thu"])
    badge_text = meta["badge"]
    sub_title = meta["sub"]
    planet_func = _planet_icon_func(meta["planet_icon"])

    # 日曜は週まとめ専用シーン（フィード投稿準拠）
    if weekday_key == "sun":
        if not data or not data.get("spots_week"):
            raise ValueError("日曜は data['spots_week'] が必須です")
        sun_img = _scene_sunday_summary(target_date, data,
                                          badge_text=badge_text,
                                          draw_planet_icon=planet_func)
        scenes = [("sunday_summary", sun_img,
                    SCENE_DURATIONS.get("top_first", 5.0) * 2)]  # 1シーンで10秒
        # ラッキースポット拡大シーン（今週のスポット振り返り風）はスキップ
        total_dur = sum(s[2] for s in scenes)
        print(f"  reel: {weekday_key} {len(scenes)}シーン 計{total_dur:.1f}秒")
        # ffmpeg で MP4 出力（既存ロジックへフォールスルー）
        return _render_scenes_to_mp4(scenes, output_path)

    # 金/土の stars 注入は generate_text.py 側（items_for_image生成時）で完結済み
    # generate_reel に渡される items は ArticleItem (dataclass) のリストで stars が入っている

    # items を正規化（ArticleItem dataclass or dict → dict）
    normalized = [_normalize_item(it) for it in items]
    # filled (stars) 降順で強制ソート → 「ランキング上位=stars多い」を保証
    # （Claude API応答は rank と stars が必ずしも対応しないため、stars 優先で再ソート）
    # 同点の場合は元の rank で安定ソート（rank があれば若い方が上）
    def _sort_key(it):
        rank = it.get("rank")
        rank_val = int(rank) if rank else 999
        return (-float(it.get("filled", 0)), rank_val)
    sorted_items = sorted(normalized, key=_sort_key)
    # 表示用に rank を1から振り直す（描画時の番号と stars の整合性を保証）
    for i, it in enumerate(sorted_items):
        it["rank"] = i + 1

    # 曜日別シーン構成（社長要望：1ページ5位ずつ・同サイズカード固定）
    # mon/wed/thu (12位): 1-5 / 6-10 / 11-12 / ラッキー = 4シーン
    # fri/sat (10位):    1-5 / 6-10 / ラッキー = 3シーン
    # tue (4種):         1-4(+空1) / ラッキー = 2シーン
    # sun:               別構成・現状は fri/sat と同じ（将来カスタマイズ可）
    def _pad(items_, n):
        out = list(items_)
        while len(out) < n:
            out.append({"name": "—", "c1": "", "c2": "", "filled": 0})
        return out

    if weekday_key == "tue":
        items_pad = _pad(sorted_items, 4)
        scenes_spec = [("rank_only", items_pad[:5], 0, "ランキング")]  # 5枠目は自動で「—」
    elif weekday_key in ("fri", "sat"):
        items_pad = _pad(sorted_items, 10)
        scenes_spec = [
            ("rank_1_5", items_pad[:5], 0, "1〜5位"),
            ("rank_6_10", items_pad[5:10], 5, "6〜10位"),
        ]
    elif weekday_key in ("mon", "wed", "thu"):
        items_pad = _pad(sorted_items, 12)
        scenes_spec = [
            ("rank_1_5", items_pad[:5], 0, "1〜5位"),
            ("rank_6_10", items_pad[5:10], 5, "6〜10位"),
            ("rank_11_12", items_pad[10:12], 10, "11〜12位"),
        ]
    else:
        # 日曜・その他（暫定で fri/sat と同じ）
        items_pad = _pad(sorted_items, 10)
        scenes_spec = [
            ("rank_1_5", items_pad[:5], 0, "1〜5位"),
            ("rank_6_10", items_pad[5:10], 5, "6〜10位"),
        ]

    # シーン画像生成
    scenes = []
    scene_dur = SCENE_DURATIONS.get("top_first", 5.0)
    for name, scene_items, rank_offset, rank_label in scenes_spec:
        img = _scene_top5(target_date, scene_items,
                          rank_offset=rank_offset, rank_label=rank_label,
                          badge_text=badge_text, sub_title=sub_title,
                          draw_planet_icon=planet_func,
                          weekday_key=weekday_key)
        scenes.append((name, img, scene_dur))

    # ラッキースポットは最後に
    img_spot = _scene_spot(target_date, spot,
                            badge_text=badge_text, sub_title=sub_title,
                            draw_planet_icon=planet_func)
    scenes.append(("spot", img_spot, SCENE_DURATIONS.get("spot", 5.0)))

    total_dur = sum(s[2] for s in scenes)
    print(f"  reel: {weekday_key} {len(scenes)}シーン 計{total_dur:.1f}秒")

    return _render_scenes_to_mp4(scenes, output_path)


def _render_scenes_to_mp4(scenes: list, output_path: Path) -> Path:
    """scenes リスト[(name, PIL.Image, duration_sec), ...] を mp4 にレンダリング"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        png_paths = []
        for name, img, dur in scenes:
            p = tmp_dir / f"{name}.png"
            img.save(str(p), "PNG", optimize=True)
            png_paths.append((p, dur))

        concat_file = tmp_dir / "concat.txt"
        with concat_file.open("w", encoding="utf-8") as fh:
            for p, dur in png_paths:
                fh.write(f"file '{p.as_posix()}'\n")
                fh.write(f"duration {dur}\n")
            fh.write(f"file '{png_paths[-1][0].as_posix()}'\n")

        cmd = [
            _ffmpeg_bin(),
            "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", f"fps={FPS},scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=decrease,pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:color=0x1a3a8e,format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-r", str(FPS),
            "-c:a", "aac", "-b:a", "128k", "-shortest",
            "-movflags", "+faststart", "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-1000:]}")

    return output_path


def _ffmpeg_bin() -> str:
    env = os.environ.get("FFMPEG_BIN")
    if env:
        return env
    candidates = ["ffmpeg"]
    winget_glob = "C:/Users/Yoshida/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_*/ffmpeg-*-full_build/bin/ffmpeg.exe"
    candidates.extend(sorted(glob.glob(winget_glob), reverse=True))
    for c in candidates:
        try:
            subprocess.run([c, "-version"], capture_output=True, timeout=5)
            return c
        except Exception:
            continue
    return "ffmpeg"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--weekday", default="thu")
    parser.add_argument("--out", default="test_reel.mp4")
    args = parser.parse_args()

    # ダミー：12干支
    ETO = ["寅（とら）年", "辰（たつ）年", "子（ねずみ）年",
           "卯（うさぎ）年", "巳（へび）年", "未（ひつじ）年",
           "申（さる）年", "酉（とり）年", "戌（いぬ）年",
           "亥（いのしし）年", "丑（うし）年", "午（うま）年"]
    dummy_items = []
    for i, name in enumerate(ETO):
        dummy_items.append({
            "name": f"【{name}】",
            "c1": "勢いに乗れる日。" if i == 0 else "オーラ全開。" if i == 1 else "落ち着いた一日。",
            "c2": "やりたいことに迷わずGO。" if i == 0 else "何をやってもうまくいきそう。" if i == 1 else "慎重に進めば吉。",
            "filled": max(2, 10 - i),
            "rank": i + 1,
        })
    dummy_spot = {"name": "spicy._.smile", "area": "豊川市"}

    y, m, d = map(int, args.date.split("-"))
    out = generate_reel(
        target_date=date(y, m, d),
        weekday_key=args.weekday,
        items=dummy_items,
        spot=dummy_spot,
        output_path=Path(args.out),
    )
    print(f"OK: {out}  ({os.path.getsize(out)/1024:.1f} KB)")
