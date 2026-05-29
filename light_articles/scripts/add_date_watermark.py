"""
add_date_watermark.py
写真のEXIF撮影日時を読み取り「YYYY年M月　撮影」テキストを下中央に入れて
batch_ファイル名で保存するスクリプト

使い方:
  python add_date_watermark.py --photo-dir "C:\\豊川ガイド\\仮フォルダ\\物件仮フォルダ"

  # ライト記事用：日付＋豊川ガイドロゴ透かしも焼き込む
  python add_date_watermark.py --photo-dir "..." --with-logo

オプション:
  --test       最初の3枚だけ処理（確認用）
  --with-logo  日付に加えて右上に豊川ガイドロゴを透明度15%で焼き込む
"""

import argparse
import os
import struct
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import piexif

# ─── テキストスタイル設定 ───────────────────────────────────────
TEXT_COLOR = (255, 50, 50)        # 赤
OUTLINE_COLOR = (255, 255, 255)   # そのまま
FONT_SIZE_RATIO = 0.08            # 画像高さに対するフォントサイズの比率
POSITION_Y_RATIO = 0.90           # 下から何%の位置（0.82=下から18%）
TEXT_TEMPLATE = "{year}年{month}月　撮影"

# ─── ロゴ透かし設定（--with-logo 指定時のみ使用）────────────────
def _resolve_logo_path() -> str:
    """Windows ローカル / GHA Linux 両対応のロゴパス解決"""
    # 1. ローカル運用の既存ロゴ（モノクロアイコン）
    win_logo = "C:/Users/Yoshida/Desktop/豊川ガイド/ﾓﾉｸﾛｱｲｺﾝ1.png"
    if Path(win_logo).exists():
        return win_logo
    # 2. ライト記事 _assets/logo.png（GHA・toyokawa-sns 配下）
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "_assets" / "logo.png",
        script_dir.parent / "_assets" / "logo.png",
        script_dir.parent.parent / "light_articles" / "_assets" / "logo.png",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return win_logo  # フォールバック（add_logo_watermark 側でガード）

LOGO_PATH = _resolve_logo_path()
LOGO_OPACITY = 0.15               # 透明度（0.0〜1.0・社長指定15%）
LOGO_SIZE_RATIO = 0.16            # 画像高さに対するロゴサイズの比率（大きめ）
LOGO_MARGIN_RATIO = 0.05          # 右端・上端からのマージン比率（左下寄り）

# Windows/Linux 両対応の日本語フォントパス候補
FONT_CANDIDATES = [
    "C:/Windows/Fonts/HGRSMP.TTF",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "C:/Windows/Fonts/YuGothR.ttc",
    "C:/Windows/Fonts/arial.ttf",
    # Linux (apt fonts-noto-cjk が入ってる場合)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

# GHA workflow の "日本語フォントセットアップ" ステップが LIGHT_FONT_DIR=/tmp/light_fonts を env に書く
# その配下を最優先で探す
_light_font_dir = os.environ.get("LIGHT_FONT_DIR")
if _light_font_dir:
    FONT_CANDIDATES = [
        f"{_light_font_dir}/NotoSansCJK-Bold.ttc",
        f"{_light_font_dir}/NotoSansCJK-Regular.ttc",
    ] + FONT_CANDIDATES

def get_font(size):
    for path in FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, size, index=0)
            print(f"使用フォント: {path}")
            return font
        except:
            continue
    return ImageFont.load_default()

def get_exif_date(image_path):
    """EXIF撮影日時を取得 → (year, month) を返す。取得できなければNone"""
    try:
        exif_data = piexif.load(str(image_path))
        date_str = exif_data.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if date_str:
            date_str = date_str.decode() if isinstance(date_str, bytes) else date_str
            # 形式: "2026:03:21 15:59:48"
            parts = date_str.split(" ")[0].split(":")
            return int(parts[0]), int(parts[1])
    except:
        pass

    # EXIFがない場合はファイルの更新日時を使う
    try:
        import os
        mtime = os.path.getmtime(str(image_path))
        import datetime
        dt = datetime.datetime.fromtimestamp(mtime)
        return dt.year, dt.month
    except:
        return None

def add_logo_watermark(img: Image.Image, logo_path: str = LOGO_PATH,
                        opacity: float = LOGO_OPACITY,
                        size_ratio: float = LOGO_SIZE_RATIO,
                        margin_ratio: float = LOGO_MARGIN_RATIO) -> Image.Image:
    """右上にロゴ透かしを焼き込む（半透明）"""
    if not Path(logo_path).exists():
        print(f"  ⚠️ ロゴ画像なし: {logo_path}")
        return img

    w, h = img.size
    logo = Image.open(logo_path).convert("RGBA")

    # サイズ調整
    target_h = int(h * size_ratio)
    ratio = target_h / logo.height
    target_w = int(logo.width * ratio)
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    # 透明度調整
    if opacity < 1.0:
        r, g, b, a = logo.split()
        a = a.point(lambda p: int(p * opacity))
        logo = Image.merge("RGBA", (r, g, b, a))

    # 配置：右上
    margin_px_x = int(w * margin_ratio)
    margin_px_y = int(h * margin_ratio)
    pos = (w - target_w - margin_px_x, margin_px_y)

    # RGBA で合成
    img_rgba = img.convert("RGBA")
    img_rgba.paste(logo, pos, logo)
    return img_rgba.convert("RGB")


def add_watermark(image_path: Path, output_path: Path, with_logo: bool = False):
    """写真に日付テキストを入れてoutput_pathに保存

    with_logo=True の場合、右上に豊川ガイドロゴ透かしも焼き込む
    """
    date = get_exif_date(image_path)
    if not date:
        print(f"  ⚠️  日付取得失敗: {image_path.name}")
        return False

    year, month = date
    text = TEXT_TEMPLATE.format(year=year, month=month)

    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    # ── ロゴ透かしを先に焼き込む（with_logo指定時のみ）──
    if with_logo:
        img = add_logo_watermark(img)

    font_size = max(30, int(h * FONT_SIZE_RATIO))
    font = get_font(font_size)

    draw = ImageDraw.Draw(img)

    # テキストサイズ取得
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (w - text_w) // 2
    y = int(h * POSITION_Y_RATIO) - text_h // 2

    # 縁取り（8方向）
    outline = max(4, font_size // 12)
    for dx in range(-outline, outline + 1):
        for dy in range(-outline, outline + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=OUTLINE_COLOR)

    # 本文
    draw.text((x, y), text, font=font, fill=TEXT_COLOR)

    # JPEG品質75で保存（元ファイルと同じ品質）
    img.save(str(output_path), "JPEG", quality=75)
    return True

def run(photo_dir: str, test_limit: int = None, with_logo: bool = False):
    base = Path(photo_dir)
    if not base.exists():
        print(f"❌ フォルダが見つかりません: {photo_dir}")
        return

    # 画像ファイルを全て収集
    exts = {".jpg", ".jpeg"}
    images = []
    for f in base.rglob("*"):
        if f.suffix.lower() in exts and not f.name.startswith("batch_"):
            images.append(f)

    print(f"✅ 対象画像: {len(images)}枚")
    if with_logo:
        print(f"🏷️ ロゴ透かしモード: ON（透明度{int(LOGO_OPACITY*100)}%・右上）")

    if test_limit:
        images = images[:test_limit]
        print(f"  （テストモード: {test_limit}枚のみ処理）")

    done = 0
    skip = 0
    for img_path in images:
        out_path = img_path.parent / f"batch_{img_path.name}"

        # すでに処理済みならスキップ
        if out_path.exists():
            skip += 1
            continue

        result = add_watermark(img_path, out_path, with_logo=with_logo)
        if result:
            done += 1
            if done % 50 == 0:
                print(f"  処理中... {done}枚完了")

    print(f"\n{'='*40}")
    print(f"✅ 完了: {done}枚")
    print(f"⏭️  スキップ（処理済み）: {skip}枚")
    print(f"{'='*40}")

# デフォルトの仮フォルダパス
DEFAULT_PHOTO_DIR = r"C:\Users\Yoshida\Desktop\豊川ガイド\仮フォルダ\物件仮フォルダ"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="物件写真に撮影年月を一括追加")
    parser.add_argument("--photo-dir", default=DEFAULT_PHOTO_DIR,
                        help=f"物件仮フォルダのパス（省略時は仮フォルダ全体）")
    parser.add_argument("--test", type=int, default=None, help="テスト枚数")
    parser.add_argument("--with-logo", action="store_true",
                        help="日付に加えて右上に豊川ガイドロゴを透明度15パーセントで焼き込む（ライト記事用）")
    args = parser.parse_args()
    print(f"対象フォルダ: {args.photo_dir}")
    run(args.photo_dir, args.test, with_logo=args.with_logo)
