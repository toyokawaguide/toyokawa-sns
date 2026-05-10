"""
豊川ガイド占い 画像生成 - 水曜(誕生月)・木曜(干支)
月曜版TOP3レイアウトを流用、バッジ/サブ/ラベルだけ変更
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
STAR_EMPTY = (215, 215, 220)

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

def draw_mercury_icon(draw, cx, cy, size, color, bg_color):
    """水星マーク(☿):上に角・下に十字・円"""
    half = size // 2
    # 上の角(半円)
    draw.arc([cx - half//2, cy - half - half//2, cx + half//2, cy - half + half//2],
            start=180, end=360, fill=color, width=2)
    # 円
    draw.ellipse([cx - half + 2, cy - half + 2, cx + half - 2, cy + half - 2],
                outline=color, width=2, fill=bg_color)
    # 下の十字
    draw.line([(cx, cy + half - 2), (cx, cy + half + 4)], fill=color, width=2)
    draw.line([(cx - 3, cy + half + 2), (cx + 4, cy + half + 2)], fill=color, width=2)

def draw_jupiter_icon(draw, cx, cy, size, color, bg_color):
    """木星マーク(♃):4を変形した形・簡略化"""
    half = size // 2
    # 横線
    draw.line([(cx - half, cy + 2), (cx + half - 2, cy + 2)], fill=color, width=2)
    # 縦線
    draw.line([(cx + 4, cy - half + 2), (cx + 4, cy + half)], fill=color, width=2)
    # 上のループ(左上→右上→下)
    draw.arc([cx - half, cy - half + 2, cx + 2, cy + 4],
            start=90, end=270, fill=color, width=2)

def date_to_str(target_date):
    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][target_date.weekday()]
    return f"{target_date.year}年{target_date.month}月{target_date.day}日({weekday_jp})"

def get_star_distribution(seed=None):
    if seed is not None:
        random.seed(seed)
    rank1 = random.randint(9, 10)
    rank2 = random.randint(8, min(9, rank1))
    rank3 = random.randint(7, min(9, rank2))
    return [rank1, rank2, rank3]


def _generate_top3_instagram(target_date, top3, lucky_spot, output_path,
                             badge_text, sub_title, bracket_emoji,
                             draw_planet_icon, hashtag_keyword):
    """月曜・水曜・木曜共通のIGテンプレ"""
    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), BEIGE)
    d = ImageDraw.Draw(img)
    date_str = date_to_str(target_date)

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

    title_y = 195
    draw_star(d, 130, title_y + 38, 28, GOLD)
    draw_star(d, W - 130, title_y + 38, 28, GOLD)
    title = "豊川ガイド的　 今日の占い"
    tf = f(FB, 56)
    tb = d.textbbox((0, 0), title, font=tf)
    d.text(((W - (tb[2]-tb[0]))//2, title_y), title, font=tf, fill=BLUE)

    badge_y = title_y + 85
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
    draw_planet_icon(d, badge_x + 22, badge_y + badge_h//2 - 2, icon_size, GOLD, WHITE)
    d.text((badge_x + 22 + icon_size//2 + icon_gap + 6, badge_y + 5), badge_text, font=bdf, fill=BLUE)

    sf = f(FM, 32)
    sb = d.textbbox((0, 0), sub_title, font=sf)
    d.text(((W - (sb[2]-sb[0]))//2, badge_y + badge_h + 8), sub_title, font=sf, fill=TEXT_DARK)

    yurusa = "〜当たるも八卦　当たらぬも八卦〜"
    yf = f(FM, 21)
    yb = d.textbbox((0, 0), yurusa, font=yf)
    d.text(((W - (yb[2]-yb[0]))//2, badge_y + badge_h + 48), yurusa, font=yf, fill=TEXT_DARK)

    line_y = badge_y + badge_h + 84
    d.rectangle([(W - 200)//2, line_y, (W + 200)//2, line_y + 5], fill=GOLD)

    cards = []
    rank_colors = [GOLD, SILVER, BRONZE]
    for i, item in enumerate(top3):
        cards.append({
            "rank": i + 1, "color": rank_colors[i],
            "name": item["name"], "c1": item["c1"], "c2": item["c2"],
            "filled": item.get("filled", 0),
        })

    card_x = 60
    card_w = W - 120
    card_h = 135
    card_gap = 14
    card_y0 = 432

    for i, c in enumerate(cards):
        y = card_y0 + i * (card_h + card_gap)
        d.rounded_rectangle([card_x, y, card_x + card_w, y + card_h],
                            radius=20, fill=WHITE, outline=BLUE, width=3)
        cx = card_x + 85
        cy = y + card_h // 2
        cr = 50
        d.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=c["color"])
        rank_font = f(FB, 56)
        draw_text_centered_in_circle(d, cx, cy, str(c["rank"]), rank_font, WHITE)

        nx = card_x + 175
        d.text((nx, y + 18), c["name"], font=f(FB, 38), fill=BLUE)
        
        star_size = 13
        star_gap = 28
        stars_x_start = card_x + card_w - 5 * star_gap - 25
        for s in range(5):
            sx = stars_x_start + s * star_gap + star_size
            color = GOLD if s < c["filled"] else STAR_EMPTY
            draw_star(d, sx, y + 32, star_size, color)
        for s in range(5, 10):
            sx = stars_x_start + (s-5) * star_gap + star_size
            color = GOLD if s < c["filled"] else STAR_EMPTY
            draw_star(d, sx, y + 64, star_size, color)
        score_text = f"{c['filled']}/10"
        scf = f(FBd, 22)
        scb = d.textbbox((0, 0), score_text, font=scf)
        d.text((card_x + card_w - (scb[2]-scb[0]) - 30, y + 92),
               score_text, font=scf, fill=GOLD)
        
        d.text((nx, y + 65), c["c1"], font=f(FM, 25), fill=TEXT_DARK)
        d.text((nx, y + 96), c["c2"], font=f(FM, 25), fill=TEXT_DARK)

    guide_y = card_y0 + 3 * card_h + 2 * card_gap + 14
    guide_text = f"他の{hashtag_keyword}の運勢は、ブログでチェック →"
    gf = f(FBd, 22)
    gb = d.textbbox((0, 0), guide_text, font=gf)
    d.text(((W - (gb[2]-gb[0]))//2, guide_y), guide_text, font=gf, fill=BLUE)

    spot_y = guide_y + 32
    spot_h = 110
    d.rounded_rectangle([60, spot_y, W-60, spot_y + spot_h], radius=18, fill=BLUE)
    
    header_line = "管理人の独断と偏見と忖度による【本日のラッキースポット】"
    hf = f(FBd, 23)
    hb = d.textbbox((0, 0), header_line, font=hf)
    if (hb[2]-hb[0]) > W - 160:
        hf = f(FBd, 21)
        hb = d.textbbox((0, 0), header_line, font=hf)
    d.text(((W - (hb[2]-hb[0]))//2, spot_y + 12), header_line, font=hf, fill=GOLD)
    
    name_text = f"{lucky_spot['name']}"
    nf = f(FB, 38)
    nb = d.textbbox((0, 0), name_text, font=nf)
    if (nb[2]-nb[0]) > W - 160:
        nf = f(FB, 32)
        nb = d.textbbox((0, 0), name_text, font=nf)
    d.text(((W - (nb[2]-nb[0]))//2, spot_y + 52), name_text, font=nf, fill=WHITE)

    note_y = spot_y + spot_h + 10
    note = "※ラッキースポットがお休みのときはまた別の日に行ってみてね！"
    nof = f(FR, 21)
    nob = d.textbbox((0, 0), note, font=nof)
    d.text(((W - (nob[2]-nob[0]))//2, note_y), note, font=nof, fill=TEXT_GRAY)

    img.save(output_path)


def _generate_top3_wp(target_date, top3, lucky_spot, output_path,
                     badge_text, sub_title, draw_planet_icon):
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
    d.text((25, 122), "今日の占い", font=f(FB, 44), fill=WHITE)
    d.rectangle([25, 178, 200, 183], fill=GOLD)

    badge_y = 200
    bdf = f(FM, 18)
    bdb = d.textbbox((0, 0), badge_text, font=bdf)
    text_w = bdb[2]-bdb[0]
    icon_size = 14
    icon_gap = 8
    badge_w = text_w + icon_size + icon_gap + 36
    badge_h = 30
    d.rounded_rectangle([25, badge_y, 25 + badge_w, badge_y + badge_h],
                        radius=15, fill=WHITE, outline=GOLD, width=2)
    draw_planet_icon(d, 25 + 18, badge_y + badge_h//2 - 2, icon_size, GOLD, WHITE)
    d.text((25 + 18 + icon_size//2 + icon_gap + 6, badge_y + 4), badge_text, font=bdf, fill=BLUE)

    d.text((25, 245), sub_title, font=f(FBd, 22), fill=WHITE)
    d.text((25, 275), "〜当たるも八卦　当たらぬも八卦〜", font=f(FM, 16), fill=GOLD)

    spot_y = 350
    spot_h = 200
    d.rounded_rectangle([20, spot_y, LEFT_W - 20, spot_y + spot_h], radius=14,
                       fill=WHITE, outline=GOLD, width=2)
    d.text((35, spot_y + 18), "管理人の独断と偏見と忖度による", font=f(FBd, 14), fill=BLUE)
    d.text((35, spot_y + 40), "【本日のラッキースポット】", font=f(FBd, 17), fill=BLUE)
    d.rectangle([35, spot_y + 70, 100, spot_y + 73], fill=GOLD)
    
    name_main = lucky_spot['name']
    nf = f(FB, 28)
    nb = d.textbbox((0, 0), name_main, font=nf)
    if (nb[2]-nb[0]) > LEFT_W - 70:
        nf = f(FB, 24)
        nb = d.textbbox((0, 0), name_main, font=nf)
    if (nb[2]-nb[0]) > LEFT_W - 70:
        nf = f(FB, 20)
    d.text((35, spot_y + 80), name_main, font=nf, fill=BLUE)
    # (area) 表示は削除（社長指示）
    d.text((35, spot_y + 152), "※ラッキースポットがお休みのときは", font=f(FR, 16), fill=(70,70,80))
    d.text((35, spot_y + 174), "　また別の日に行ってみてね！", font=f(FR, 16), fill=(70,70,80))

    cards = []
    rank_colors = [GOLD, SILVER, BRONZE]
    for i, item in enumerate(top3):
        cards.append({
            "rank": i + 1, "color": rank_colors[i],
            "name": item["name"], "c1": item["c1"], "c2": item["c2"],
            "filled": item.get("filled", 0),
        })

    card_x = LEFT_W + 25
    card_w = W - card_x - 25
    card_h = 158
    card_gap = 14
    card_y0 = 30

    for i, c in enumerate(cards):
        y = card_y0 + i * (card_h + card_gap)
        d.rounded_rectangle([card_x, y, card_x + card_w, y + card_h], radius=15,
                           fill=WHITE, outline=BLUE, width=3)
        cx = card_x + 55
        cy = y + card_h // 2
        cr = 38
        d.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=c["color"])
        rank_font = f(FB, 42)
        draw_text_centered_in_circle(d, cx, cy, str(c["rank"]), rank_font, WHITE)
        nx = card_x + 105
        d.text((nx, y + 18), c["name"], font=f(FB, 28), fill=BLUE)
        
        star_size = 10
        star_gap = 22
        stars_x_start = card_x + card_w - 5 * star_gap - 18
        for s in range(5):
            sx = stars_x_start + s * star_gap + star_size
            color = GOLD if s < c["filled"] else STAR_EMPTY
            draw_star(d, sx, y + 28, star_size, color)
        for s in range(5, 10):
            sx = stars_x_start + (s-5) * star_gap + star_size
            color = GOLD if s < c["filled"] else STAR_EMPTY
            draw_star(d, sx, y + 52, star_size, color)
        score_text = f"{c['filled']}/10"
        scf = f(FBd, 18)
        scb = d.textbbox((0, 0), score_text, font=scf)
        d.text((card_x + card_w - (scb[2]-scb[0]) - 22, y + 70),
               score_text, font=scf, fill=GOLD)
        # コメント2行（自動縮小・枠はみ出し防止）
        c_max_w_wp = card_w - 105 - 90
        for ci, ckey in enumerate(["c1", "c2"]):
            ctxt = c[ckey]
            cfsize = 18
            cf = f(FM, cfsize)
            while cfsize >= 12:
                cb = d.textbbox((0, 0), ctxt, font=cf)
                if (cb[2] - cb[0]) <= c_max_w_wp:
                    break
                cfsize -= 1
                cf = f(FM, cfsize)
            d.text((nx, y + 65 + ci * 27), ctxt, font=cf, fill=TEXT_DARK)
        if i == 2:
            d.text((card_x + 8, y + card_h + 8), "※他の項目はブログ本文へ", font=f(FR, 16), fill=TEXT_GRAY)

    img.save(output_path)


# === 公開関数 ===
def generate_wednesday_instagram(target_date, top3, lucky_spot, output_path):
    """水曜版IG"""
    _generate_top3_instagram(
        target_date, top3, lucky_spot, output_path,
        badge_text="今日は水曜・水星の日",
        sub_title="今日のラッキー誕生月TOP3",
        bracket_emoji="🎂",
        draw_planet_icon=draw_mercury_icon,
        hashtag_keyword="月生まれ"
    )

def generate_wednesday_wp(target_date, top3, lucky_spot, output_path):
    _generate_top3_wp(
        target_date, top3, lucky_spot, output_path,
        badge_text="今日は水曜・水星の日",
        sub_title="今日のラッキー誕生月TOP3",
        draw_planet_icon=draw_mercury_icon
    )

def generate_thursday_instagram(target_date, top3, lucky_spot, output_path):
    """木曜版IG"""
    _generate_top3_instagram(
        target_date, top3, lucky_spot, output_path,
        badge_text="今日は木曜・木星の日",
        sub_title="今日のラッキー干支TOP3",
        bracket_emoji="🐲",
        draw_planet_icon=draw_jupiter_icon,
        hashtag_keyword="干支"
    )

def generate_thursday_wp(target_date, top3, lucky_spot, output_path):
    _generate_top3_wp(
        target_date, top3, lucky_spot, output_path,
        badge_text="今日は木曜・木星の日",
        sub_title="今日のラッキー干支TOP3",
        draw_planet_icon=draw_jupiter_icon
    )


if __name__ == "__main__":
    os.makedirs("./output", exist_ok=True)
    # 水曜
    target_wed = date(2026, 5, 6)
    top3_wed = [
        {"name": "【3月生まれ】", "c1": "人気運MAX。", "c2": "ばったり知り合いに会うかも。"},
        {"name": "【7月生まれ】", "c1": "ひらめきの日。", "c2": "新しいアイデアが舞い込むよ。"},
        {"name": "【11月生まれ】", "c1": "直感が冴える。", "c2": "ピンときたら、すぐ動こう。"},
    ]
    spot_wed = {"name": "ベーカリーすみ", "area": "豊川市諏訪"}
    generate_wednesday_instagram(target_wed, top3_wed, spot_wed, './output/水曜_IG_v2.png')
    generate_wednesday_wp(target_wed, top3_wed, spot_wed, './output/水曜_WP_v2.png')
    
    # 木曜
    target_thu = date(2026, 5, 7)
    top3_thu = [
        {"name": "【寅(とら)年】", "c1": "攻めの姿勢が吉。", "c2": "今日のあなた、止められません。"},
        {"name": "【辰(たつ)年】", "c1": "夢を語る日。", "c2": "周りに想いを伝えてみよう。"},
        {"name": "【戌(いぬ)年】", "c1": "信頼運MAX。", "c2": "誠実な対応で評価UP間違いなし。"},
    ]
    spot_thu = {"name": "豊川稲荷", "area": "豊川市門前町"}
    generate_thursday_instagram(target_thu, top3_thu, spot_thu, './output/木曜_IG_v2.png')
    generate_thursday_wp(target_thu, top3_thu, spot_thu, './output/木曜_WP_v2.png')
    
    print("水曜・木曜版 IG+WP 完成")
