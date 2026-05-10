"""
豊川ガイド占い 画像生成 - 火曜版(血液型A/B/O/AB)
順位なし・全4種コンパクト表示
"""
from PIL import Image, ImageDraw, ImageFont
import math
import random
from datetime import date

BLUE = (3, 58, 154)
BEIGE = (245, 239, 224)
WHITE = (255, 255, 255)
GOLD = (212, 175, 55)
TEXT_DARK = (40, 50, 80)
TEXT_GRAY = (110, 110, 120)
STAR_EMPTY = (215, 215, 220)

# 血液型カラー(各型の伝統的なイメージ)
BLOOD_A = (220, 80, 80)      # 赤系
BLOOD_B = (240, 180, 60)     # 黄系
BLOOD_O = (90, 170, 100)     # 緑系
BLOOD_AB = (120, 110, 200)   # 紫系

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
_LOGO_PATH = os.environ.get("URANAI_LOGO_PATH", str(Path(__file__).resolve().parent.parent / "assets" / "logo_white_trimmed.png"))
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

def draw_mars_icon(draw, cx, cy, size, color, bg_color):
    """火星アイコン:円+矢印(♂)"""
    # 円
    half = size // 2
    draw.ellipse([cx - half, cy - half + size//4, cx + half, cy + half + size//4],
                 outline=color, width=3, fill=bg_color)
    # 矢印(右上方向)
    arrow_start = (cx + half - 2, cy - half//2 - 2)
    arrow_end = (cx + half + size//2, cy - half - 4)
    draw.line([arrow_start, arrow_end], fill=color, width=3)
    # 矢印先端
    draw.polygon([
        (arrow_end[0] + 4, arrow_end[1]),
        (arrow_end[0] - 5, arrow_end[1]),
        (arrow_end[0], arrow_end[1] + 9)
    ], fill=color)

def date_to_str(target_date):
    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][target_date.weekday()]
    return f"{target_date.year}年{target_date.month}月{target_date.day}日({weekday_jp})"

def get_4_blood_stars(seed=None):
    """血液型4種の★配分・差を付ける"""
    if seed is not None:
        random.seed(seed)
    # 4つに差を付けてランダム
    base = [10, 8, 7, 5]
    random.shuffle(base)
    return base


def generate_tuesday_instagram(target_date, blood_data, lucky_spot, output_path):
    """火曜版IG (1080×1080)
    
    blood_data: dict
        {"A": {"c1": "...", "c2": "..."},
         "B": {...}, "O": {...}, "AB": {...}}
    """
    W, H = 1080, 1080
    img = Image.new("RGB", (W, H), BEIGE)
    d = ImageDraw.Draw(img)
    date_str = date_to_str(target_date)

    # === ヘッダー ===
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

    # === タイトル ===
    title_y = 195
    draw_star(d, 130, title_y + 38, 28, GOLD)
    draw_star(d, W - 130, title_y + 38, 28, GOLD)
    title = "豊川ガイド的　 今日の占い"
    tf = f(FB, 56)
    tb = d.textbbox((0, 0), title, font=tf)
    d.text(((W - (tb[2]-tb[0]))//2, title_y), title, font=tf, fill=BLUE)

    # バッジ「火星の日」
    badge_y = title_y + 85
    badge_text = "今日は火曜・火星の日"
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
    draw_mars_icon(d, badge_x + 22, badge_y + badge_h//2 - 2, icon_size, GOLD, WHITE)
    d.text((badge_x + 22 + icon_size//2 + icon_gap + 8, badge_y + 5), badge_text, font=bdf, fill=BLUE)

    # サブタイトル
    sub = "今日の血液型別運勢"
    sf = f(FM, 32)
    sb = d.textbbox((0, 0), sub, font=sf)
    d.text(((W - (sb[2]-sb[0]))//2, badge_y + badge_h + 8), sub, font=sf, fill=TEXT_DARK)

    yurusa = "〜当たるも八卦　当たらぬも八卦〜"
    yf = f(FM, 21)
    yb = d.textbbox((0, 0), yurusa, font=yf)
    d.text(((W - (yb[2]-yb[0]))//2, badge_y + badge_h + 48), yurusa, font=yf, fill=TEXT_DARK)

    line_y = badge_y + badge_h + 84
    d.rectangle([(W - 200)//2, line_y, (W + 200)//2, line_y + 5], fill=GOLD)

    # === 血液型カード4枚(2x2グリッド) ===
    seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
    star_dists_fallback = get_4_blood_stars(seed=seed)

    blood_types = [
        {"key": "A", "color": BLOOD_A},
        {"key": "B", "color": BLOOD_B},
        {"key": "O", "color": BLOOD_O},
        {"key": "AB", "color": BLOOD_AB},
    ]
    for i, bt in enumerate(blood_types):
        bt["c1"] = blood_data[bt["key"]]["c1"]
        bt["c2"] = blood_data[bt["key"]]["c2"]
        # blood_data に stars があればそれを使い、なければシード値にフォールバック
        bt["filled"] = blood_data[bt["key"]].get("stars") or star_dists_fallback[i]

    # 2x2 grid
    grid_x = 50
    grid_y = 440
    cell_w = (W - 100 - 20) // 2  # 隙間20
    cell_h = 175  # 200→175 高さ削減(詳しくは消えたので)
    cell_gap = 18

    for i, bt in enumerate(blood_types):
        row = i // 2
        col = i % 2
        x = grid_x + col * (cell_w + cell_gap)
        y = grid_y + row * (cell_h + cell_gap)
        
        # カード背景
        d.rounded_rectangle([x, y, x + cell_w, y + cell_h], radius=18,
                           fill=WHITE, outline=BLUE, width=3)
        
        # 血液型シンボル(円・色付き)
        sym_cx = x + 70
        sym_cy = y + cell_h // 2
        sym_r = 50
        d.ellipse([sym_cx - sym_r, sym_cy - sym_r, sym_cx + sym_r, sym_cy + sym_r],
                 fill=bt["color"])
        # 血液型文字
        bf = f(FB, 38) if bt["key"] != "AB" else f(FB, 30)
        draw_text_centered_in_circle(d, sym_cx, sym_cy, bt["key"], bf, WHITE)
        
        # 血液型ラベル
        d.text((x + 130, y + 18), f"【{bt['key']}型】", font=f(FB, 28), fill=BLUE)
        
        # ★(10段階・1段組5個 + 数値) - 大きくUP
        star_size = 13  # 10→13
        star_gap = 26   # 20→26
        stars_x_start = x + cell_w - 5 * star_gap - 25
        for s in range(5):
            sx = stars_x_start + s * star_gap + star_size
            color = GOLD if s < bt["filled"] else STAR_EMPTY
            draw_star(d, sx, y + 30, star_size, color)
        for s in range(5, 10):
            sx = stars_x_start + (s-5) * star_gap + star_size
            color = GOLD if s < bt["filled"] else STAR_EMPTY
            draw_star(d, sx, y + 58, star_size, color)
        score = f"{bt['filled']}/10"
        scf = f(FBd, 22)  # 16→22
        scb = d.textbbox((0, 0), score, font=scf)
        d.text((x + cell_w - (scb[2]-scb[0]) - 22, y + 82), score, font=scf, fill=GOLD)
        
        # コメント2行（はみ出し時に自動縮小・社長指示）
        c_max_w = cell_w - 130 - 20
        for ci, ckey in enumerate(["c1", "c2"]):
            ctxt = bt[ckey]
            cfsize = 19
            cf = f(FM, cfsize)
            while cfsize >= 13:
                cb = d.textbbox((0, 0), ctxt, font=cf)
                if (cb[2] - cb[0]) <= c_max_w:
                    break
                cfsize -= 2
                cf = f(FM, cfsize)
            d.text((x + 130, y + 95 + ci * 35), ctxt, font=cf, fill=TEXT_DARK)

    # === 4枚共通の誘導(1つにまとめる) ===
    guide_y = grid_y + 2 * (cell_h + cell_gap) - 5
    guide_text = "相性・ラッキーアクション・注意点はブログで →"
    gf = f(FBd, 22)
    gb = d.textbbox((0, 0), guide_text, font=gf)
    d.text(((W - (gb[2]-gb[0]))//2, guide_y), guide_text, font=gf, fill=BLUE)

    # === ラッキースポット ===
    spot_y = guide_y + 38
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


def generate_tuesday_wp(target_date, blood_data, lucky_spot, output_path):
    """火曜版WP(1024×576)"""
    W, H = 1024, 576
    img = Image.new("RGB", (W, H), BEIGE)
    d = ImageDraw.Draw(img)
    date_str = date_to_str(target_date)

    # 左カラム
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

    # バッジ「火星の日」
    badge_y = 200
    badge_text = "今日は火曜・火星の日"
    bdf = f(FM, 18)
    bdb = d.textbbox((0, 0), badge_text, font=bdf)
    text_w = bdb[2]-bdb[0]
    icon_size = 14
    icon_gap = 8
    badge_w = text_w + icon_size + icon_gap + 36
    badge_h = 30
    d.rounded_rectangle([25, badge_y, 25 + badge_w, badge_y + badge_h],
                        radius=15, fill=WHITE, outline=GOLD, width=2)
    draw_mars_icon(d, 25 + 18, badge_y + badge_h//2 - 2, icon_size, GOLD, WHITE)
    d.text((25 + 18 + icon_size//2 + icon_gap + 6, badge_y + 4), badge_text, font=bdf, fill=BLUE)

    d.text((25, 245), "今日は血液型でいきます！", font=f(FBd, 22), fill=WHITE)
    d.text((25, 275), "〜当たるも八卦　当たらぬも八卦〜", font=f(FM, 16), fill=GOLD)

    # ラッキースポット
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

    # 右カラム:血液型4種(2x2グリッド)
    seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
    star_dists_fallback = get_4_blood_stars(seed=seed)

    blood_types = [
        {"key": "A", "color": BLOOD_A},
        {"key": "B", "color": BLOOD_B},
        {"key": "O", "color": BLOOD_O},
        {"key": "AB", "color": BLOOD_AB},
    ]
    for i, bt in enumerate(blood_types):
        bt["c1"] = blood_data[bt["key"]]["c1"]
        bt["c2"] = blood_data[bt["key"]]["c2"]
        bt["filled"] = blood_data[bt["key"]].get("stars") or star_dists_fallback[i]

    grid_x = LEFT_W + 25
    grid_y = 30
    cell_w = (W - grid_x - 25 - 14) // 2
    cell_h = 230
    cell_gap = 14

    for i, bt in enumerate(blood_types):
        row = i // 2
        col = i % 2
        x = grid_x + col * (cell_w + cell_gap)
        y = grid_y + row * (cell_h + cell_gap)
        
        d.rounded_rectangle([x, y, x + cell_w, y + cell_h], radius=14,
                           fill=WHITE, outline=BLUE, width=2)
        
        sym_cx = x + 40
        sym_cy = y + 36
        sym_r = 24
        d.ellipse([sym_cx - sym_r, sym_cy - sym_r, sym_cx + sym_r, sym_cy + sym_r],
                 fill=bt["color"])
        bf = f(FB, 22) if bt["key"] != "AB" else f(FB, 16)
        draw_text_centered_in_circle(d, sym_cx, sym_cy, bt["key"], bf, WHITE)
        
        d.text((x + 75, y + 18), f"【{bt['key']}型】", font=f(FB, 22), fill=BLUE)
        
        # ★10段階(2段組) - 大きくUP
        star_size = 9  # 7→9
        star_gap = 18  # 14→18
        stars_x_start = x + 16
        for s in range(5):
            sx = stars_x_start + s * star_gap + star_size
            color = GOLD if s < bt["filled"] else STAR_EMPTY
            draw_star(d, sx, y + 80, star_size, color)
        for s in range(5, 10):
            sx = stars_x_start + (s-5) * star_gap + star_size
            color = GOLD if s < bt["filled"] else STAR_EMPTY
            draw_star(d, sx, y + 102, star_size, color)
        d.text((x + 120, y + 86), f"{bt['filled']}/10", font=f(FBd, 18), fill=GOLD)  # 14→18
        
        # コメント2行
        # WP版コメント自動縮小
        c_max_w_wp = cell_w - 16 - 14
        for ci, ckey in enumerate(["c1", "c2"]):
            ctxt = bt[ckey]
            cfsize = 14
            cf = f(FM, cfsize)
            while cfsize >= 10:
                cb = d.textbbox((0, 0), ctxt, font=cf)
                if (cb[2] - cb[0]) <= c_max_w_wp:
                    break
                cfsize -= 1
                cf = f(FM, cfsize)
            d.text((x + 16, y + 122 + ci * 23), ctxt, font=cf, fill=TEXT_DARK)

    # 全4種共通の誘導(1つにまとめる)
    guide_y_wp = grid_y + 2 * (cell_h + cell_gap) - 5
    d.text((grid_x, guide_y_wp), "相性・ラッキーアクション・注意点はブログで →",
           font=f(FBd, 16), fill=BLUE)

    img.save(output_path)


if __name__ == "__main__":
    os.makedirs("./output", exist_ok=True)
    target = date(2026, 5, 5)
    blood = {
        "A": {"c1": "完璧主義が今日は神。", "c2": "細かい仕事、サクサク片付くよ。"},
        "B": {"c1": "マイペースでOK。", "c2": "周りに合わせず自分のリズムで。"},
        "O": {"c1": "社交運◎。", "c2": "久しぶりの人から連絡が来るかも。"},
        "AB": {"c1": "頭の中ぐるぐる注意。", "c2": "深呼吸してから動きましょう。"},
    }
    spot = {"name": "コメダ珈琲店 豊川店", "area": "豊川市末広通"}
    generate_tuesday_instagram(target, blood, spot, './output/火曜_IG_v3.png')
    generate_tuesday_wp(target, blood, spot, './output/火曜_WP_v3.png')
    print("火曜版 IG+WP 完成")
