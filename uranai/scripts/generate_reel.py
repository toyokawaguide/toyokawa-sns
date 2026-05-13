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

def _scene_top6(target_date: date, items: list, *,
                rank_offset: int, rank_label: str,
                badge_text: str, sub_title: str,
                draw_planet_icon) -> Image.Image:
    """6枚のカードを縦並びで描画（ベース紺色背景・白文字＋白カード）"""
    img = Image.new("RGB", (REEL_W, REEL_H), BLUE)
    d = ImageDraw.Draw(img)

    header_h = _draw_header(d, img, target_date)
    content_y = _draw_title_section(d, header_h, badge_text, sub_title,
                                    rank_label=rank_label,
                                    draw_planet_icon=draw_planet_icon)

    # カード設定（コンテンツ領域内に収める）
    card_x = CONTENT_LEFT       # 40
    card_w = CONTENT_W          # 900
    card_h = 150
    card_gap = 14
    card_y0 = content_y

    rank_color = lambda r: GOLD if r == 1 else SILVER if r == 2 else BRONZE if r == 3 else (180, 200, 220)

    use_items = items[:6] if len(items) >= 6 else items
    while len(use_items) < 6:
        use_items.append({"name": "—", "c1": "", "c2": "", "filled": 0})

    for i, it in enumerate(use_items):
        rank = rank_offset + i + 1
        y = card_y0 + i * (card_h + card_gap)

        # カード枠
        d.rounded_rectangle([card_x, y, card_x + card_w, y + card_h],
                            radius=22, fill=WHITE, outline=BLUE, width=3)

        # 順位バッジ円
        cx = card_x + 85
        cy = y + card_h // 2
        cr = 52
        d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=rank_color(rank))
        rank_font = f(FB, 56 if rank < 10 else 44)
        draw_text_centered_in_circle(d, cx, cy, str(rank), rank_font, WHITE)

        # 名前
        nx = card_x + 165
        name = it.get("name", "")
        d.text((nx, y + 16), name, font=f(FB, 36), fill=BLUE)

        # 星評価（右上・空星は濃いめのグレー）
        STAR_EMPTY_DARK = (140, 150, 170)  # STAR_EMPTYを上書き・濃いブルーグレー
        filled = int(it.get("filled", 0))
        star_size = 13
        star_gap = 26
        stars_x_start = card_x + card_w - 5 * star_gap - 24
        for s in range(5):
            sx = stars_x_start + s * star_gap + star_size
            color = GOLD if s < filled else STAR_EMPTY_DARK
            draw_star(d, sx, y + 32, star_size, color)
        for s in range(5, 10):
            sx = stars_x_start + (s - 5) * star_gap + star_size
            color = GOLD if s < filled else STAR_EMPTY_DARK
            draw_star(d, sx, y + 64, star_size, color)
        score_text = f"{filled}/10"
        scf = f(FBd, 22)
        scb = d.textbbox((0, 0), score_text, font=scf)
        d.text((card_x + card_w - (scb[2] - scb[0]) - 24, y + 96),
               score_text, font=scf, fill=GOLD)

        # コメント（c1, c2 の2行）
        d.text((nx, y + 70), it.get("c1", ""), font=f(FM, 24), fill=TEXT_DARK)
        d.text((nx, y + 105), it.get("c2", ""), font=f(FM, 24), fill=TEXT_DARK)

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

def _normalize_item(it) -> dict:
    """ArticleItem (dataclass) or dict を {name, c1, c2, filled, rank} に正規化"""
    if isinstance(it, dict):
        return it
    # dataclass (ArticleItem: rank, label, stars 0-5, comment, extras)
    rank = getattr(it, "rank", None)
    label = getattr(it, "label", "") or ""
    stars = int(getattr(it, "stars", 0) or 0)
    comment = (getattr(it, "comment", "") or "").strip()
    # コメントを2行に分割（句点 → 読点 → 等分の優先順位）
    if "。" in comment:
        idx = comment.index("。")
        c1 = comment[:idx + 1]
        c2 = comment[idx + 1:].strip()
    elif "、" in comment:
        idx = comment.index("、")
        c1 = comment[:idx + 1]
        c2 = comment[idx + 1:].strip()
    else:
        half = len(comment) // 2
        c1 = comment[:half]
        c2 = comment[half:]
    return {
        "name": label,
        "c1": c1,
        "c2": c2,
        "filled": stars * 2,  # 0-5 → 0-10
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
                  output_path: Path) -> Path:
    """リール動画(15秒・3シーン・1080×1920)を生成"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    meta = WEEKDAY_META.get(weekday_key, WEEKDAY_META["thu"])
    badge_text = meta["badge"]
    sub_title = meta["sub"]
    planet_func = _planet_icon_func(meta["planet_icon"])

    # items を正規化（ArticleItem dataclass or dict → dict）
    normalized = [_normalize_item(it) for it in items]
    # filled 降順でソート（rank があれば優先）
    def _sort_key(it):
        if "rank" in it and it["rank"]:
            return (0, int(it["rank"]))
        return (1, -int(it.get("filled", 0)))
    sorted_items = sorted(normalized, key=_sort_key)

    # 12要素揃える（不足は空欄で埋める）
    while len(sorted_items) < 12:
        sorted_items.append({"name": "—", "c1": "", "c2": "", "filled": 0})

    # シーン生成
    img_top_first = _scene_top6(target_date, sorted_items[:6],
                                 rank_offset=0, rank_label="1〜6位",
                                 badge_text=badge_text, sub_title=sub_title,
                                 draw_planet_icon=planet_func)
    img_top_second = _scene_top6(target_date, sorted_items[6:12],
                                  rank_offset=6, rank_label="7〜12位",
                                  badge_text=badge_text, sub_title=sub_title,
                                  draw_planet_icon=planet_func)
    img_spot = _scene_spot(target_date, spot,
                            badge_text=badge_text, sub_title=sub_title,
                            draw_planet_icon=planet_func)

    scenes = [
        ("top_first", img_top_first, SCENE_DURATIONS["top_first"]),
        ("top_second", img_top_second, SCENE_DURATIONS["top_second"]),
        ("spot", img_spot, SCENE_DURATIONS["spot"]),
    ]
    total_dur = sum(s[2] for s in scenes)
    print(f"  reel: {weekday_key} 3シーン 計{total_dur:.1f}秒")

    # ffmpeg で MP4 出力
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
