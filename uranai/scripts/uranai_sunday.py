"""
豊川ガイド占い 画像生成 - 日曜版(週まとめ&来週予告)
独自レイアウト:
- 今週よかった/大変だった星座
- 1週間のラッキースポットおさらい
- 来週のテーマ
"""
from PIL import Image, ImageDraw, ImageFont
import math
import random
from datetime import date

BLUE = (3, 58, 154)
BEIGE = (245, 239, 224)
WHITE = (255, 255, 255)
GOLD = (212, 175, 55)
SILVER = (180, 180, 180)
BRONZE = (205, 127, 50)
TEXT_DARK = (40, 50, 80)
TEXT_GRAY = (110, 110, 120)
GREEN_GOOD = (90, 170, 100)
ORANGE_TIRED = (230, 140, 70)

# === 環境設定(claude.codeで実行する際に変更してください) ===
# Linux環境のデフォルト。Windowsの場合は下記コメントを参照
import os
# .env から URANAI_FONT_DIR / URANAI_LOGO_PATH を読み込み（単体実行・モジュール経由いずれも対応）
try:
    from dotenv import load_dotenv
    from pathlib import Path as _P
    load_dotenv(_P(__file__).resolve().parent / ".env", override=True)
except ImportError:
    pass
_FONT_DIR = os.environ.get("URANAI_FONT_DIR", "/usr/share/fonts/opentype/noto")
_LOGO_PATH = os.environ.get("URANAI_LOGO_PATH", "/home/claude/logo_white_trimmed.png")
# Windows例: URANAI_FONT_DIR="C:/Windows/Fonts" + フォントファイル名を変更
# macOS例: URANAI_FONT_DIR="/System/Library/Fonts"
# ============================================================

import platform
if platform.system() == "Windows" and "Windows/Fonts" in _FONT_DIR.replace(chr(92), "/"):
    FB = f"{_FONT_DIR}/meiryob.ttc"   # Bold (太め)
    FBd = f"{_FONT_DIR}/meiryob.ttc"  # Bold
    FR = f"{_FONT_DIR}/meiryo.ttc"    # Regular
    FM = f"{_FONT_DIR}/meiryob.ttc"   # Medium代替→Bold (太く見せる)
else:
    FB = f"{_FONT_DIR}/NotoSansCJK-Black.ttc"
    FBd = f"{_FONT_DIR}/NotoSansCJK-Bold.ttc"
    FR = f"{_FONT_DIR}/NotoSansCJK-Regular.ttc"
    FM = f"{_FONT_DIR}/NotoSansCJK-Medium.ttc"

def f(p, s): return ImageFont.truetype(p, s)

def draw_star(draw, cx, cy, size, color):
    pts = []
    for i in range(10):
        a = math.pi/2 + i*math.pi/5
        r = size if i%2==0 else size*0.4
        pts.append((cx + r*math.cos(a), cy - r*math.sin(a)))
    draw.polygon(pts, fill=color)

def draw_text_centered_in_circle(draw, cx, cy, text, font, fill):
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = cx - text_w/2 - bbox[0]
    y = cy - text_h/2 - bbox[1]
    draw.text((x, y), text, font=font, fill=fill)

def draw_sun_icon(draw, cx, cy, size, color, bg_color):
    """太陽マーク☉:円+中心点"""
    half = size // 2
    # 外円
    draw.ellipse([cx - half, cy - half, cx + half, cy + half],
                 outline=color, width=3, fill=bg_color)
    # 中心の点
    draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=color)

def date_to_str(target_date):
    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][target_date.weekday()]
    return f"{target_date.year}年{target_date.month}月{target_date.day}日({weekday_jp})"


def generate_sunday_instagram(target_date, summary, lucky_spots_week, output_path):
    """日曜版IG (1080×1080)
    
    summary: dict
        {
          "good_signs": ["しし座", "おひつじ座"],  # 今週よかった2つ
          "tired_signs": ["かに座", "うお座"],   # 今週大変だった2つ
          "next_week_theme": "新しい挑戦の週"      # 来週のテーマ
        }
    lucky_spots_week: list[dict] - 月〜土の6つのスポット
        [{"day": "月", "name": "○○"}, ...]
    """
    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), BEIGE)
    d = ImageDraw.Draw(img)
    date_str = date_to_str(target_date)

    # ヘッダー
    HEADER_H = 160
    d.rectangle([0, 0, W, HEADER_H], fill=BLUE)
    
    date_font = f(FBd, 52)
    date_bbox = date_font.getbbox(date_str)
    date_y = (HEADER_H - (date_bbox[3] - date_bbox[1])) // 2 - date_bbox[1]
    d.text((50, date_y), date_str, font=date_font, fill=WHITE)
    
    logo_orig = Image.open(_LOGO_PATH)
    target_h = 110
    ratio = target_h / logo_orig.size[1]
    target_w = int(logo_orig.size[0] * ratio)
    logo = logo_orig.resize((target_w, target_h))
    img.paste(logo, (W - target_w - 35, (HEADER_H - target_h) // 2), logo)

    # タイトル
    title_y = 195
    draw_star(d, 130, title_y + 38, 28, GOLD)
    draw_star(d, W - 130, title_y + 38, 28, GOLD)
    title = "豊川ガイド的　 今週のまとめ"
    tf = f(FB, 54)
    tb = d.textbbox((0, 0), title, font=tf)
    d.text(((W - (tb[2]-tb[0]))//2, title_y), title, font=tf, fill=BLUE)

    # バッジ
    badge_y = title_y + 85
    badge_text = "今日は日曜・太陽の日"
    bdf = f(FM, 22)
    bdb = d.textbbox((0, 0), badge_text, font=bdf)
    text_w = bdb[2]-bdb[0]
    icon_size = 18
    icon_gap = 10
    badge_w = text_w + icon_size + icon_gap + 50
    badge_h = 38
    badge_x = (W - badge_w) // 2
    d.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                        radius=19, fill=WHITE, outline=GOLD, width=2)
    draw_sun_icon(d, badge_x + 22, badge_y + badge_h//2, icon_size, GOLD, WHITE)
    d.text((badge_x + 22 + icon_size//2 + icon_gap + 6, badge_y + 5), badge_text, font=bdf, fill=BLUE)

    sub = "今週のおさらい&ラッキースポット募集中!"
    sf = f(FM, 28)
    sb = d.textbbox((0, 0), sub, font=sf)
    d.text(((W - (sb[2]-sb[0]))//2, badge_y + badge_h + 8), sub, font=sf, fill=TEXT_DARK)

    yurusa = "〜当たるも八卦　当たらぬも八卦〜"
    yf = f(FM, 21)
    yb = d.textbbox((0, 0), yurusa, font=yf)
    d.text(((W - (yb[2]-yb[0]))//2, badge_y + badge_h + 44), yurusa, font=yf, fill=TEXT_DARK)

    line_y = badge_y + badge_h + 80
    d.rectangle([(W - 200)//2, line_y, (W + 200)//2, line_y + 5], fill=GOLD)

    # === ブロック1:今週のラッキースポットおさらい(上半分) ===
    sp_y = 425
    sp_h = 260  # 280→260 募集ブロック分を確保
    d.rounded_rectangle([50, sp_y, W - 50, sp_y + sp_h], radius=18,
                       fill=WHITE, outline=BLUE, width=3)
    d.text((70, sp_y + 18), "◆ 今週のラッキースポットおさらい", font=f(FBd, 26), fill=BLUE)
    d.rectangle([70, sp_y + 56, 200, sp_y + 60], fill=GOLD)
    
    # 6個のスポットを2列x3行で(店名大きく)
    sp_grid_x = 70
    sp_grid_y = sp_y + 80
    sp_cell_w = (W - 140 - 20) // 2
    sp_cell_h = 60
    
    for i, sp in enumerate(lucky_spots_week):
        col = i // 3
        row = i % 3
        sx = sp_grid_x + col * (sp_cell_w + 20)
        sy = sp_grid_y + row * sp_cell_h
        # 曜日ピル
        d.rounded_rectangle([sx, sy, sx + 50, sy + 40], radius=8, fill=BLUE)
        df = f(FB, 24)
        db = d.textbbox((0, 0), sp['day'], font=df)
        d.text((sx + 25 - (db[2]-db[0])//2, sy + 4), sp['day'], font=df, fill=WHITE)
        # スポット名(さらに大きく: 22→28)
        sn_font = f(FB, 28)
        snb = d.textbbox((0, 0), sp['name'], font=sn_font)
        if (snb[2]-snb[0]) > sp_cell_w - 65:
            sn_font = f(FB, 22)
            snb = d.textbbox((0, 0), sp['name'], font=sn_font)
        if (snb[2]-snb[0]) > sp_cell_w - 65:
            sn_font = f(FB, 18)
        d.text((sx + 62, sy + 4), sp['name'], font=sn_font, fill=TEXT_DARK)

    # === ブロック2:ラッキースポット募集告知(下半分・案B:上中下分割) ===
    tm_y = sp_y + sp_h + 16
    tm_h = 300  # 280→300 署名分の余白
    d.rounded_rectangle([50, tm_y, W - 50, tm_y + tm_h], radius=18, fill=BLUE)
    
    # 上段:ヘッダー
    header_text = "★ ラッキースポット、絶賛募集中!"
    hf = f(FBd, 26)
    hb = d.textbbox((0, 0), header_text, font=hf)
    d.text(((W - (hb[2]-hb[0]))//2, tm_y + 22), header_text, font=hf, fill=GOLD)
    # 区切り線(細い金線)
    d.rectangle([100, tm_y + 65, W - 100, tm_y + 67], fill=GOLD)
    
    # 中段:キャッチコピー(2行・大きく中央)
    catch1 = "自分がそう思ったら"
    catch2 = "もうラッキースポットでいいんじゃない?"
    cf = f(FBd, 32)
    cb1 = d.textbbox((0, 0), catch1, font=cf)
    cb2 = d.textbbox((0, 0), catch2, font=cf)
    d.text(((W - (cb1[2]-cb1[0]))//2, tm_y + 100), catch1, font=cf, fill=WHITE)
    d.text(((W - (cb2[2]-cb2[0]))//2, tm_y + 152), catch2, font=cf, fill=WHITE)
    
    # 名言の署名(右寄せ・もう少し内側に)
    sign = "— by 豊川ガイド"
    sf_sign = f(FM, 22)
    sb_sign = d.textbbox((0, 0), sign, font=sf_sign)
    # 右端から180pxの位置に(80→180)
    d.text((W - 180 - (sb_sign[2]-sb_sign[0]), tm_y + 205), sign, font=sf_sign, fill=GOLD)
    
    # 区切り線(細い金線)
    d.rectangle([100, tm_y + 246, W - 100, tm_y + 248], fill=GOLD)
    
    # 下段:案内(自薦・他薦)
    bottom = "自薦・他薦どっちもOK!お気軽にどうぞ"
    bf = f(FBd, 20)
    bb = d.textbbox((0, 0), bottom, font=bf)
    d.text(((W - (bb[2]-bb[0]))//2, tm_y + 256), bottom, font=bf, fill=GOLD)

    # 注釈
    note_y = tm_y + tm_h + 12
    note = "※プロフィールのリンクから、お気軽に教えてくださいませ"
    nof = f(FR, 19)
    nob = d.textbbox((0, 0), note, font=nof)
    d.text(((W - (nob[2]-nob[0]))//2, note_y), note, font=nof, fill=TEXT_GRAY)

    img.save(output_path)


def generate_sunday_wp(target_date, summary, lucky_spots_week, output_path):
    """日曜版WP (1024×576)"""
    W, H = 1024, 576
    img = Image.new("RGB", (W, H), BEIGE)
    d = ImageDraw.Draw(img)
    date_str = date_to_str(target_date)

    LEFT_W = 380
    d.rectangle([0, 0, LEFT_W, H], fill=BLUE)

    d.text((25, 25), date_str, font=f(FBd, 26), fill=WHITE)
    
    logo_orig = Image.open(_LOGO_PATH)
    target_h = 50
    ratio = target_h / logo_orig.size[1]
    target_w = int(logo_orig.size[0] * ratio)
    logo = logo_orig.resize((target_w, target_h))
    img.paste(logo, (LEFT_W - target_w - 20, 18), logo)

    d.text((25, 80), "豊川ガイド的", font=f(FB, 32), fill=GOLD)
    d.text((25, 122), "今週のまとめ", font=f(FB, 38), fill=WHITE)
    d.rectangle([25, 178, 200, 183], fill=GOLD)

    badge_y = 200
    badge_text = "今日は日曜・太陽の日"
    bdf = f(FM, 18)
    bdb = d.textbbox((0, 0), badge_text, font=bdf)
    text_w = bdb[2]-bdb[0]
    icon_size = 14
    icon_gap = 8
    badge_w = text_w + icon_size + icon_gap + 36
    badge_h = 30
    d.rounded_rectangle([25, badge_y, 25 + badge_w, badge_y + badge_h],
                        radius=15, fill=WHITE, outline=GOLD, width=2)
    draw_sun_icon(d, 25 + 18, badge_y + badge_h//2, icon_size, GOLD, WHITE)
    d.text((25 + 18 + icon_size//2 + icon_gap + 6, badge_y + 4), badge_text, font=bdf, fill=BLUE)

    d.text((25, 245), "今週のおさらい＆", font=f(FBd, 19), fill=WHITE)
    d.text((25, 270), "ラッキースポット募集中!", font=f(FBd, 19), fill=WHITE)
    d.text((25, 305), "〜当たるも八卦　当たらぬも八卦〜", font=f(FM, 14), fill=GOLD)

    # 占い曜日メニュー紹介(左カラム下部)
    tm_y = 360
    tm_h = 195
    d.rounded_rectangle([20, tm_y, LEFT_W - 20, tm_y + tm_h], radius=14,
                       fill=WHITE, outline=GOLD, width=2)
    d.text((35, tm_y + 14), "◆ 毎朝6時にお届け!", font=f(FBd, 16), fill=BLUE)
    d.rectangle([35, tm_y + 42, 100, tm_y + 45], fill=GOLD)
    
    # 曜日別メニュー(2列で簡潔に)
    menu = [
        ("月", "12星座"),
        ("火", "血液型"),
        ("水", "誕生月"),
        ("木", "干支"),
        ("金", "生まれ年"),
        ("土", "ラッキータウン"),
    ]
    for i, (day, theme) in enumerate(menu):
        col = i // 3
        row = i % 3
        mx = 35 + col * 165
        my = tm_y + 60 + row * 38
        # 曜日ピル
        d.rounded_rectangle([mx, my, mx + 28, my + 26], radius=5, fill=BLUE)
        df = f(FB, 14)
        db = d.textbbox((0, 0), day, font=df)
        d.text((mx + 14 - (db[2]-db[0])//2, my + 4), day, font=df, fill=WHITE)
        # テーマ
        d.text((mx + 36, my + 4), theme, font=f(FBd, 14), fill=TEXT_DARK)
    
    # 日曜の説明(下部)
    d.text((35, tm_y + 178), "日:今週のおさらい(今読んでるやつ!)", font=f(FM, 11), fill=TEXT_GRAY)

    # === 右カラム ===
    rx = LEFT_W + 25
    rw = W - rx - 25
    
    # ブロック1:今週のラッキースポットおさらい(上半分・店名大きく)
    sp_y = 25
    sp_h = (H - 50 - 14) // 2  # 半分
    d.rounded_rectangle([rx, sp_y, rx + rw, sp_y + sp_h], radius=12,
                       fill=WHITE, outline=BLUE, width=2)
    d.text((rx + 18, sp_y + 12), "◆ 今週のラッキースポットおさらい", font=f(FBd, 18), fill=BLUE)
    d.rectangle([rx + 18, sp_y + 40, rx + 90, sp_y + 43], fill=GOLD)
    
    # 6個を2列x3行
    sp_grid_x = rx + 18
    sp_grid_y = sp_y + 56
    sp_cell_w = (rw - 36 - 10) // 2
    sp_cell_h = (sp_h - 70) // 3
    
    for i, sp in enumerate(lucky_spots_week):
        col = i // 3
        row = i % 3
        sx = sp_grid_x + col * (sp_cell_w + 10)
        sy = sp_grid_y + row * sp_cell_h
        # 曜日ピル
        d.rounded_rectangle([sx, sy, sx + 36, sy + 28], radius=6, fill=BLUE)
        df = f(FB, 16)
        db = d.textbbox((0, 0), sp['day'], font=df)
        d.text((sx + 18 - (db[2]-db[0])//2, sy + 3), sp['day'], font=df, fill=WHITE)
        # スポット名(大きく:14→18)
        sn_font = f(FB, 18)
        snb = d.textbbox((0, 0), sp['name'], font=sn_font)
        if (snb[2]-snb[0]) > sp_cell_w - 50:
            sn_font = f(FB, 15)
            snb = d.textbbox((0, 0), sp['name'], font=sn_font)
        if (snb[2]-snb[0]) > sp_cell_w - 50:
            sn_font = f(FB, 13)
        d.text((sx + 44, sy + 4), sp['name'], font=sn_font, fill=TEXT_DARK)

    # ブロック2:ラッキースポット募集告知(下半分・案B 上中下分割)
    pm_y = sp_y + sp_h + 14
    pm_h = sp_h
    d.rounded_rectangle([rx, pm_y, rx + rw, pm_y + pm_h], radius=12, fill=BLUE)
    
    # 上段:ヘッダー(中央寄せ)
    header = "★ ラッキースポット、絶賛募集中!"
    hf = f(FBd, 18)
    hb = d.textbbox((0, 0), header, font=hf)
    d.text((rx + (rw - (hb[2]-hb[0]))//2, pm_y + 14), header, font=hf, fill=GOLD)
    # 区切り線
    d.rectangle([rx + 50, pm_y + 44, rx + rw - 50, pm_y + 46], fill=GOLD)
    
    # 中段:キャッチコピー(2行・中央寄せ・大きめ・名言風)
    cf = f(FBd, 22)
    catch1 = "自分がそう思ったら"
    catch2 = "もうラッキースポットでいいんじゃない?"
    cb1 = d.textbbox((0, 0), catch1, font=cf)
    cb2 = d.textbbox((0, 0), catch2, font=cf)
    d.text((rx + (rw - (cb1[2]-cb1[0]))//2, pm_y + 70), catch1, font=cf, fill=WHITE)
    d.text((rx + (rw - (cb2[2]-cb2[0]))//2, pm_y + 110), catch2, font=cf, fill=WHITE)
    
    # 署名(右寄せ・もう少し内側)
    sign = "— by 豊川ガイド"
    sf_sign = f(FM, 15)
    sb_sign = d.textbbox((0, 0), sign, font=sf_sign)
    # 右端から80px内側に(30→80)
    d.text((rx + rw - 80 - (sb_sign[2]-sb_sign[0]), pm_y + 150), sign, font=sf_sign, fill=GOLD)
    
    # 区切り線
    d.rectangle([rx + 50, pm_y + 184, rx + rw - 50, pm_y + 186], fill=GOLD)
    
    # 下段:案内
    bottom = "自薦・他薦どっちもOK!お気軽にどうぞ"
    bf = f(FBd, 16)
    bb = d.textbbox((0, 0), bottom, font=bf)
    d.text((rx + (rw - (bb[2]-bb[0]))//2, pm_y + 196), bottom, font=bf, fill=GOLD)

    img.save(output_path)


if __name__ == "__main__":
    os.makedirs("./output", exist_ok=True)
    target = date(2026, 5, 10)
    summary = {
        "good_signs": ["しし座", "おひつじ座"],
        "tired_signs": ["かに座", "うお座"],
        "next_week_theme": "新しい挑戦の週",
    }
    spots_week = [
        {"day": "月", "name": "門前そば 山彦"},
        {"day": "火", "name": "コメダ珈琲店"},
        {"day": "水", "name": "ベーカリーすみ"},
        {"day": "木", "name": "豊川稲荷"},
        {"day": "金", "name": "御油の松並木"},
        {"day": "土", "name": "赤塚山公園"},
    ]
    generate_sunday_instagram(target, summary, spots_week,
                              './output/日曜_IG_v7.png')
    generate_sunday_wp(target, summary, spots_week,
                       './output/日曜_WP_v7.png')
    print("日曜版 IG+WP 完成")
