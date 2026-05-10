"""
豊川ガイド占い 画像生成 - 金曜(生まれ年TOP10)・土曜(ラッキータウンTOP10)
TOP10ランキング表(コメントなし・順位+名前+★)
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

def draw_venus_icon(draw, cx, cy, size, color, bg_color):
    """金星マーク♀:円+下に十字"""
    half = size // 2
    # 円
    draw.ellipse([cx - half, cy - half - 2, cx + half, cy + half - 2],
                 outline=color, width=3, fill=bg_color)
    # 下の縦線
    draw.line([(cx, cy + half - 2), (cx, cy + half + 8)], fill=color, width=3)
    # 横線
    draw.line([(cx - 5, cy + half + 3), (cx + 5, cy + half + 3)], fill=color, width=3)

def draw_saturn_icon(draw, cx, cy, size, color, bg_color):
    """土星マーク♄:hの下に輪・簡略化"""
    half = size // 2
    # 縦棒(左)
    draw.line([(cx - 4, cy - half - 2), (cx - 4, cy + half - 2)], fill=color, width=2)
    # 縦棒(右)
    draw.line([(cx + 5, cy - 2), (cx + 5, cy + half + 2)], fill=color, width=2)
    # 上の横棒(突き出し)
    draw.line([(cx - 8, cy - half - 2), (cx, cy - half - 2)], fill=color, width=2)
    # 横線(中央)
    draw.line([(cx - 4, cy - 2), (cx + 5, cy - 2)], fill=color, width=2)
    # 下の輪
    draw.arc([cx - 5, cy + half - 2, cx + 8, cy + half + 8],
            start=0, end=180, fill=color, width=2)

def date_to_str(target_date):
    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][target_date.weekday()]
    return f"{target_date.year}年{target_date.month}月{target_date.day}日({weekday_jp})"


def get_top10_stars(seed=None):
    """TOP10の★配分:
    1-2位:★10
    3-5位:★10〜★9 (0.5刻み)
    6-10位:★9〜★8 (0.5刻み)
    
    順位ガード:必ず1位 ≥ 2位 ≥ 3位 ≥ ... ≥ 10位
    """
    if seed is not None:
        random.seed(seed)
    stars = []
    # 1-2位は固定で★10
    stars.append(10.0)
    stars.append(10.0)
    # 3-5位は10, 9.5, 9 のランダム → 順位降順保証のためソート
    g2 = sorted([random.choice([10.0, 9.5, 9.0]) for _ in range(3)], reverse=True)
    # 2位(10)以下になるよう調整(2位より高くなることはないが念のため)
    g2 = [min(v, stars[-1]) for v in g2]
    # ただしこの方式だと前の値より下がる可能性があるので、累積最小値で再構築
    fixed_g2 = []
    prev = stars[-1]
    for v in g2:
        v = min(v, prev)
        fixed_g2.append(v)
        prev = v
    stars.extend(fixed_g2)
    
    # 6-10位は9, 8.5, 8 のランダム → 5位以下になるよう調整
    g3 = sorted([random.choice([9.0, 8.5, 8.0]) for _ in range(5)], reverse=True)
    fixed_g3 = []
    prev = stars[-1]
    for v in g3:
        v = min(v, prev)
        fixed_g3.append(v)
        prev = v
    stars.extend(fixed_g3)
    
    return stars


def format_star_score(score):
    """10.0→'★10' / 9.5→'★9.5' / 9.0→'★9' の表記"""
    if score == int(score):
        return f"★{int(score)}"
    return f"★{score}"


def _generate_top10_instagram(target_date, items, lucky_spot, output_path,
                               badge_text, sub_title, draw_planet_icon,
                               item_label_func=None,
                               extra_subtitle=None):
    """金曜・土曜共通のTOP10 IGテンプレ
    
    items: list[str] - 10項目の名前(例: ["1990年(平成2年)", ...] or ["○○町", ...])
    item_label_func: 表示時の【】処理を行う関数(無ければそのまま)
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
    title = "豊川ガイド的　 今日の占い"
    tf = f(FB, 56)
    tb = d.textbbox((0, 0), title, font=tf)
    d.text(((W - (tb[2]-tb[0]))//2, title_y), title, font=tf, fill=BLUE)

    # バッジ
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

    # サブ
    sf = f(FM, 32)
    sb = d.textbbox((0, 0), sub_title, font=sf)
    d.text(((W - (sb[2]-sb[0]))//2, badge_y + badge_h + 8), sub_title, font=sf, fill=TEXT_DARK)

    # 新文言(extra_subtitle):金土だけ存在
    if extra_subtitle:
        ef = f(FM, 22)
        eb = d.textbbox((0, 0), extra_subtitle, font=ef)
        d.text(((W - (eb[2]-eb[0]))//2, badge_y + badge_h + 50), extra_subtitle, font=ef, fill=TEXT_DARK)
        yurusa_y_offset = 86  # 新文言ありの場合は下に
    else:
        yurusa_y_offset = 48  # 通常位置

    yurusa = "〜当たるも八卦　当たらぬも八卦〜"
    yf = f(FM, 21)
    yb = d.textbbox((0, 0), yurusa, font=yf)
    d.text(((W - (yb[2]-yb[0]))//2, badge_y + badge_h + yurusa_y_offset), yurusa, font=yf, fill=TEXT_DARK)

    line_y = badge_y + badge_h + yurusa_y_offset + 36
    d.rectangle([(W - 200)//2, line_y, (W + 200)//2, line_y + 5], fill=GOLD)

    # === TOP10ランキング(2列×5行) ===
    seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
    stars = get_top10_stars(seed=seed)
    
    grid_x = 50
    # line_y(金線)の下から余白を取って開始
    grid_y = line_y + 30
    cell_w = (W - 100 - 16) // 2
    cell_h = 65
    cell_gap_y = 10
    cell_gap_x = 16

    for i in range(10):
        col = i // 5  # 0=左列(1-5位), 1=右列(6-10位)
        row = i % 5
        x = grid_x + col * (cell_w + cell_gap_x)
        y = grid_y + row * (cell_h + cell_gap_y)
        
        rank = i + 1
        # 1-3位はメダルカラー、4-10位は紺色(ブランドカラー寄り)
        if rank == 1:
            rank_color = GOLD
        elif rank == 2:
            rank_color = SILVER
        elif rank == 3:
            rank_color = BRONZE
        else:
            rank_color = (60, 80, 140)  # 紺色(ブランドカラー寄り)
        
        # 行カード
        d.rounded_rectangle([x, y, x + cell_w, y + cell_h], radius=10,
                           fill=WHITE, outline=BLUE, width=2)
        
        # 順位サークル
        rank_cx = x + 32
        rank_cy = y + cell_h // 2
        rank_r = 22
        d.ellipse([rank_cx - rank_r, rank_cy - rank_r,
                  rank_cx + rank_r, rank_cy + rank_r], fill=rank_color)
        # 順位数字
        rank_str = str(rank)
        rank_font = f(FB, 24)
        text_color = WHITE
        draw_text_centered_in_circle(d, rank_cx, rank_cy, rank_str, rank_font, text_color)
        
        # 名前(フォントUP: 20→24)
        name = items[i] if not item_label_func else item_label_func(items[i])
        name_font = f(FB, 24)
        nb = d.textbbox((0, 0), name, font=name_font)
        # スコア領域分(★10:約60px)を考慮して名前領域を確保
        name_max_w = cell_w - 70 - 90  # サークル分70 + スコア分90
        if (nb[2]-nb[0]) > name_max_w:
            name_font = f(FB, 20)
            nb = d.textbbox((0, 0), name, font=name_font)
        if (nb[2]-nb[0]) > name_max_w:
            name_font = f(FB, 17)
        nb = d.textbbox((0, 0), name, font=name_font)
        name_h = nb[3] - nb[1]
        name_y = y + (cell_h - name_h) // 2 - nb[1]
        d.text((x + 62, name_y), name, font=name_font, fill=BLUE)
        
        # ★スコア(★N表記・もっと大きく)
        score = format_star_score(stars[i])
        scf = f(FBd, 26)  # 18→26にUP
        scb = d.textbbox((0, 0), score, font=scf)
        sc_y = y + (cell_h - (scb[3]-scb[1])) // 2 - scb[1]
        d.text((x + cell_w - (scb[2]-scb[0]) - 14, sc_y), score, font=scf, fill=GOLD)

    # ラッキースポット
    spot_y = grid_y + 5 * cell_h + 4 * cell_gap_y + 18
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

    # 注釈
    note_y = spot_y + spot_h + 10
    note = "※ラッキースポットがお休みのときはまた別の日に行ってみてね！"
    nof = f(FR, 19)
    nob = d.textbbox((0, 0), note, font=nof)
    d.text(((W - (nob[2]-nob[0]))//2, note_y), note, font=nof, fill=TEXT_GRAY)

    img.save(output_path)


def _generate_top10_wp(target_date, items, lucky_spot, output_path,
                       badge_text, sub_title, draw_planet_icon,
                       item_label_func=None,
                       extra_subtitle=None):
    """金・土曜共通のTOP10 WPテンプレ"""
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
    # 新文言(extra_subtitle):金土だけ存在
    if extra_subtitle:
        d.text((25, 275), extra_subtitle, font=f(FM, 13), fill=WHITE)
        d.text((25, 297), "〜当たるも八卦　当たらぬも八卦〜", font=f(FM, 14), fill=GOLD)
    else:
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

    # === 右カラム:TOP10 (2列×5行) ===
    seed = target_date.year * 10000 + target_date.month * 100 + target_date.day
    stars = get_top10_stars(seed=seed)
    
    grid_x = LEFT_W + 20
    grid_y = 25
    cell_w = (W - grid_x - 20 - 10) // 2
    cell_h = 100
    cell_gap_y = 5
    cell_gap_x = 10

    for i in range(10):
        col = i // 5
        row = i % 5
        x = grid_x + col * (cell_w + cell_gap_x)
        y = grid_y + row * (cell_h + cell_gap_y)
        
        rank = i + 1
        if rank == 1: rank_color = GOLD
        elif rank == 2: rank_color = SILVER
        elif rank == 3: rank_color = BRONZE
        else: rank_color = (60, 80, 140)  # 紺色
        
        d.rounded_rectangle([x, y, x + cell_w, y + cell_h], radius=8,
                           fill=WHITE, outline=BLUE, width=2)
        
        rank_cx = x + 26
        rank_cy = y + cell_h // 2
        rank_r = 18
        d.ellipse([rank_cx - rank_r, rank_cy - rank_r,
                  rank_cx + rank_r, rank_cy + rank_r], fill=rank_color)
        rank_font = f(FB, 20)
        draw_text_centered_in_circle(d, rank_cx, rank_cy, str(rank), rank_font, WHITE)
        
        # 名前(フォントUP: 18→22 社長指示)
        name = items[i] if not item_label_func else item_label_func(items[i])
        name_font = f(FB, 22)
        nb = d.textbbox((0, 0), name, font=name_font)
        name_max_w = cell_w - 50 - 70  # サークル分50 + スコア分70
        if (nb[2]-nb[0]) > name_max_w:
            name_font = f(FB, 20)
            nb = d.textbbox((0, 0), name, font=name_font)
        if (nb[2]-nb[0]) > name_max_w:
            name_font = f(FB, 17)
        nb = d.textbbox((0, 0), name, font=name_font)
        name_y = y + (cell_h - (nb[3]-nb[1])) // 2 - nb[1]
        d.text((x + 50, name_y), name, font=name_font, fill=BLUE)
        
        score = format_star_score(stars[i])
        scf = f(FBd, 19)  # 14→19にUP
        scb = d.textbbox((0, 0), score, font=scf)
        sc_y = y + (cell_h - (scb[3]-scb[1])) // 2 - scb[1]
        d.text((x + cell_w - (scb[2]-scb[0]) - 10, sc_y), score, font=scf, fill=GOLD)

    img.save(output_path)


# === 公開関数 ===

def label_year(year_data):
    """生まれ年のラベル化"""
    if isinstance(year_data, dict):
        return f"【{year_data['western']}年({year_data['era']})】"
    return f"【{year_data}】"

def label_town(town_name):
    """町名のラベル化"""
    return f"【{town_name}】"

def generate_friday_instagram(target_date, years, lucky_spot, output_path):
    """金曜版IG"""
    _generate_top10_instagram(
        target_date, years, lucky_spot, output_path,
        badge_text="今日は金曜・金星の日",
        sub_title="今日のラッキー生まれ年TOP10",
        draw_planet_icon=draw_venus_icon,
        item_label_func=label_year,
        extra_subtitle="〜この年生まれの方、今日は特にラッキーかも〜"
    )

def generate_friday_wp(target_date, years, lucky_spot, output_path):
    _generate_top10_wp(
        target_date, years, lucky_spot, output_path,
        badge_text="今日は金曜・金星の日",
        sub_title="今日のラッキー生まれ年TOP10",
        draw_planet_icon=draw_venus_icon,
        item_label_func=label_year,
        extra_subtitle="〜この年生まれの方、今日は特にラッキーかも〜"
    )

def generate_saturday_instagram(target_date, towns, lucky_spot, output_path):
    """土曜版IG"""
    _generate_top10_instagram(
        target_date, towns, lucky_spot, output_path,
        badge_text="今日は土曜・土星の日",
        sub_title="今日のラッキータウンTOP10",
        draw_planet_icon=draw_saturn_icon,
        item_label_func=label_town,
        extra_subtitle="〜この町にお住まいの方、今日は特にラッキーかも〜"
    )

def generate_saturday_wp(target_date, towns, lucky_spot, output_path):
    _generate_top10_wp(
        target_date, towns, lucky_spot, output_path,
        badge_text="今日は土曜・土星の日",
        sub_title="今日のラッキータウンTOP10",
        draw_planet_icon=draw_saturn_icon,
        item_label_func=label_town,
        extra_subtitle="〜この町にお住まいの方、今日は特にラッキーかも〜"
    )


if __name__ == "__main__":
    os.makedirs("./output", exist_ok=True)
    # 金曜
    target_fri = date(2026, 5, 8)
    years_fri = [
        {"western": 1990, "era": "平成2"},
        {"western": 1984, "era": "昭和59"},
        {"western": 2003, "era": "平成15"},
        {"western": 1976, "era": "昭和51"},
        {"western": 2020, "era": "令和2"},
        {"western": 1965, "era": "昭和40"},
        {"western": 1996, "era": "平成8"},
        {"western": 1973, "era": "昭和48"},
        {"western": 2008, "era": "平成20"},
        {"western": 1959, "era": "昭和34"},
    ]
    spot_fri = {"name": "御油の松並木", "area": "豊川市御油町"}
    generate_friday_instagram(target_fri, years_fri, spot_fri,
                              './output/金曜_IG_v6.png')
    generate_friday_wp(target_fri, years_fri, spot_fri,
                       './output/金曜_WP_v6.png')
    
    # 土曜
    target_sat = date(2026, 5, 9)
    towns_sat = ["門前町", "諏訪", "国府町", "牛久保町", "桜ヶ丘町",
                 "御油町", "為当町", "三上町", "新道町", "千歳通"]
    spot_sat = {"name": "豊川稲荷", "area": "豊川市門前町"}
    generate_saturday_instagram(target_sat, towns_sat, spot_sat,
                                 './output/土曜_IG_v6.png')
    generate_saturday_wp(target_sat, towns_sat, spot_sat,
                         './output/土曜_WP_v6.png')
    
    print("金曜・土曜版 IG+WP 完成")
