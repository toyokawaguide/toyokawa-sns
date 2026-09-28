"""
render_video.py — 掛け合い台本 JSON → 横長 YouTube 動画（1920×1080 mp4）

【画面構成】
- 上：ヘッダー帯（豊川ガイドロゴ＋記事タイトル＋VOICEVOX クレジット）
- 中央：記事の写真（なければチャプター名カード）
- 左右：キャラクター（話している方を強調・もう一方は薄く）
- 下：字幕（話者カラーの枠＋名前タグ）

【出力】video.mp4 / description.txt（チャプター・クレジット入り概要欄）/ thumbnail.png

【使い方】
python render_video.py script.json -o ../output/12345/
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import voicevox_tts as tts

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
CONFIG_PATH = ROOT.parent / "config.json"
LOGO_WHITE = REPO_ROOT / "light_articles" / "_assets" / "toyokawaguide-logo white.png"

W, H = 1920, 1080
FPS = 30

# Colors（ライト記事リールと同系統）
COLOR_BG = (252, 245, 230)
COLOR_NAVY = (26, 58, 138)
COLOR_ACCENT = (212, 160, 23)
COLOR_WHITE = (255, 255, 255)
COLOR_TEXT = (40, 34, 24)
COLOR_SUB = (240, 220, 160)

# レイアウト
HEADER_H = 96
PANEL = (400, 124, 1520, 754)            # 写真エリア（1120×630＝16:9）
ICON_D = 280
ICON_Y = 470
ICON_X = {"left": 60, "right": W - 60 - ICON_D}
SUB_BOX = (60, 806, W - 60, 1050)        # 字幕エリア

END_CARD_SEC = 4.0

if platform.system() == "Windows":
    FONT_CANDIDATES = ["C:/Windows/Fonts/yugothb.ttc", "C:/Windows/Fonts/meiryob.ttc",
                       "C:/Windows/Fonts/msgothic.ttc"]
else:
    _font_dir = os.environ.get("LIGHT_FONT_DIR", "/tmp/light_fonts")
    FONT_CANDIDATES = [f"{_font_dir}/NotoSansCJK-Bold.ttc",
                       "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                       "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
                       "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"]

try:
    import budoux
    _PARSER = budoux.load_default_japanese_parser()
except Exception:
    _PARSER = None

_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _font_cache:
        for p in FONT_CANDIDATES:
            try:
                _font_cache[size] = ImageFont.truetype(p, size)
                break
            except OSError:
                continue
        else:
            raise RuntimeError("日本語フォントが見つかりません（LIGHT_FONT_DIR を確認）")
    return _font_cache[size]


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ───────────────────────── テキスト処理 ─────────────────────────

def split_units(text: str, max_chars: int = 48) -> list[str]:
    """台詞を字幕1枚ぶんの単位に分ける（文末で区切り、短い文はまとめる）"""
    sents = [s.strip() for s in re.split(r"(?<=[。！？!?♪])|\n", text) if s and s.strip()]
    units: list[str] = []
    for s in sents:
        # 長すぎる1文は読点で分割
        while len(s) > max_chars * 2:
            cut = s.rfind("、", 0, max_chars + 10)
            cut = cut + 1 if cut > 10 else max_chars
            units.append(s[:cut])
            s = s[cut:]
        # 「えっ！」「なるほど。」のような短い文は次の文とまとめて1枚に
        if units and len(units[-1]) < 16 and len(units[-1]) + len(s) <= max_chars:
            units[-1] += s
        else:
            units.append(s)
    return units or [text]


def _phrases(text: str) -> list[str]:
    return _PARSER.parse(text) if _PARSER else list(text)


def wrap(draw: ImageDraw.ImageDraw, text: str, f, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ph in _phrases(text):
        if draw.textlength(cur + ph, font=f) <= max_w:
            cur += ph
            continue
        if cur:
            lines.append(cur)
        cur = ""
        # 1文節が長すぎる場合は文字単位で
        for ch in ph:
            if draw.textlength(cur + ch, font=f) > max_w and cur:
                lines.append(cur)
                cur = ""
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def fit_wrap(draw, text: str, max_w: int, max_lines: int, sizes: range):
    for s in sizes:
        f = font(s)
        lines = wrap(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    f = font(sizes[-1])
    return f, wrap(draw, text, f, max_w)[:max_lines]


# ───────────────────────── 画像素材 ─────────────────────────

class Assets:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self._mem: dict[str, Image.Image | None] = {}

    def load(self, src: str | None) -> Image.Image | None:
        if not src:
            return None
        if src in self._mem:
            return self._mem[src]
        img = None
        try:
            if src.startswith("file://"):
                img = Image.open(requests.utils.unquote(src[7:]))
            elif src.startswith(("http://", "https://")):
                r = requests.get(src, timeout=30)
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content))
            else:
                img = Image.open(src)
            img = img.convert("RGBA")
        except Exception as e:
            print(f"  [注意] 画像を読めませんでした: {src[:100]} ({e})", file=sys.stderr)
        self._mem[src] = img
        return img


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    im = img.resize((max(tw, round(img.width * scale)), max(th, round(img.height * scale))), Image.LANCZOS)
    l, t = (im.width - tw) // 2, (im.height - th) // 2
    return im.crop((l, t, l + tw, t + th))


def contain(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    tw, th = size
    scale = min(tw / img.width, th / img.height)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)


def rounded_mask(size: tuple[int, int], r: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), r, fill=255)
    return m


def circle_icon(ch: dict, assets: Assets, d: int) -> Image.Image:
    """キャラクターの丸アイコン（吹き出しアイコン画像 → なければ名前1文字の仮アイコン）"""
    color = hex_rgb(ch["color"])
    out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
    src = assets.load(ch.get("image") or ch.get("icon"))
    if src is not None:
        face = Image.new("RGBA", (d, d), COLOR_WHITE + (255,))
        face.alpha_composite(cover(src, (d, d)))
    else:
        face = Image.new("RGBA", (d, d), color + (255,))
        dr = ImageDraw.Draw(face)
        label = (ch.get("display_name") or "?")[0]
        f = font(int(d * 0.5))
        dr.text((d / 2, d / 2), label, font=f, fill=COLOR_WHITE, anchor="mm")
    out.paste(face, (0, 0), mask)
    ring = ImageDraw.Draw(out)
    ring.ellipse((3, 3, d - 4, d - 4), outline=color + (255,), width=10)
    return out


# ───────────────────────── フレーム描画 ─────────────────────────

class Renderer:
    def __init__(self, script: dict, assets: Assets, credit: str):
        self.script = script
        self.assets = assets
        self.credit = credit
        self.chars = script["characters"]
        self.icons = {k: circle_icon(c, assets, ICON_D) for k, c in self.chars.items()}
        self.logo = Image.open(LOGO_WHITE).convert("RGBA") if LOGO_WHITE.exists() else None
        self._base_cache: dict[tuple, Image.Image] = {}

    def _header(self, im: Image.Image):
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, W, HEADER_H), fill=COLOR_NAVY)
        d.rectangle((0, HEADER_H, W, HEADER_H + 6), fill=COLOR_ACCENT)
        x = 30
        if self.logo is not None:
            lg = contain(self.logo, (260, HEADER_H - 30))
            im.alpha_composite(lg, (x, (HEADER_H - lg.height) // 2))
            x += lg.width + 30
        cf = font(22)
        cw = d.textlength(self.credit, font=cf)
        d.text((W - 30 - cw, HEADER_H / 2), self.credit, font=cf, fill=COLOR_SUB, anchor="lm")
        tf, lines = fit_wrap(d, self.script["title"], int(W - x - cw - 90), 1, range(40, 25, -2))
        d.text((x, HEADER_H / 2), lines[0] if lines else "", font=tf, fill=COLOR_WHITE, anchor="lm")

    def _panel(self, im: Image.Image, image_src: str | None, chapter: str | None):
        x0, y0, x1, y1 = PANEL
        pw, ph = x1 - x0, y1 - y0
        photo = self.assets.load(image_src)
        if photo is not None:
            bg = cover(photo, (pw, ph)).filter(ImageFilter.GaussianBlur(28))
            bg = Image.blend(bg, Image.new("RGBA", bg.size, (0, 0, 0, 255)), 0.35)
            fg = contain(photo, (pw, ph))
            bg.alpha_composite(fg, ((pw - fg.width) // 2, (ph - fg.height) // 2))
            panel = bg
        else:
            panel = Image.new("RGBA", (pw, ph), COLOR_NAVY + (255,))
            d = ImageDraw.Draw(panel)
            f, lines = fit_wrap(d, chapter or self.script["title"], pw - 140, 3, range(72, 39, -4))
            lh = f.size * 1.35
            top = ph / 2 - lh * len(lines) / 2
            for i, ln in enumerate(lines):
                d.text((pw / 2, top + lh * i + lh / 2), ln, font=f, fill=COLOR_WHITE, anchor="mm")
        shadow = Image.new("RGBA", (pw, ph), (0, 0, 0, 60))
        im.paste(shadow, (x0 + 8, y0 + 10), rounded_mask((pw, ph), 24))
        im.paste(panel, (x0, y0), rounded_mask((pw, ph), 24))
        if chapter and photo is not None:
            d = ImageDraw.Draw(im)
            f = font(30)
            tw = d.textlength(chapter, font=f)
            tw = min(tw, pw - 60)
            d.rounded_rectangle((x0 + 20, y0 + 20, x0 + 60 + tw, y0 + 74), 14, fill=COLOR_ACCENT)
            d.text((x0 + 40, y0 + 47), chapter, font=f, fill=COLOR_WHITE, anchor="lm")

    def base(self, image_src: str | None, chapter: str | None) -> Image.Image:
        key = (image_src, chapter)
        if key not in self._base_cache:
            im = Image.new("RGBA", (W, H), COLOR_BG + (255,))
            self._header(im)
            self._panel(im, image_src, chapter)
            self._base_cache = {key: im}   # 直前の1枚だけ保持（メモリ節約）
        return self._base_cache[key].copy()

    def frame(self, speaker: str, text: str, image_src: str | None, chapter: str | None) -> Image.Image:
        im = self.base(image_src, chapter)
        d = ImageDraw.Draw(im)
        ch = self.chars[speaker]
        color = hex_rgb(ch["color"])

        # キャラクター（話者を強調）
        for key, c in self.chars.items():
            side = c.get("side", "left")
            icon = self.icons[key]
            y = ICON_Y
            if key != speaker:
                icon = icon.copy()
                icon.putalpha(icon.getchannel("A").point(lambda a: int(a * 0.45)))
                y += 16
            im.alpha_composite(icon, (ICON_X[side], y))

        # 字幕
        x0, y0, x1, y1 = SUB_BOX
        d.rounded_rectangle((x0, y0, x1, y1), 28, fill=COLOR_WHITE, outline=color, width=8)
        nf = font(34)
        name = ch.get("display_name") or ch["voice_name"]
        nw = d.textlength(name, font=nf)
        side = ch.get("side", "left")
        nx = x0 + 40 if side == "left" else x1 - 40 - nw - 48
        d.rounded_rectangle((nx, y0 - 30, nx + nw + 48, y0 + 26), 18, fill=color)
        d.text((nx + 24, y0 - 2), name, font=nf, fill=COLOR_WHITE, anchor="lm")

        f, lines = fit_wrap(d, text, x1 - x0 - 120, 3, range(62, 41, -2))
        lh = f.size * 1.4
        top = (y0 + y1) / 2 - lh * len(lines) / 2 + 8
        for i, ln in enumerate(lines):
            d.text((x0 + 60, top + lh * i + lh / 2), ln, font=f, fill=COLOR_TEXT, anchor="lm",
                   stroke_width=0)
        return im

    def title_card(self) -> Image.Image:
        im = Image.new("RGBA", (W, H), COLOR_NAVY + (255,))
        d = ImageDraw.Draw(im)
        d.rectangle((0, H - 120, W, H), fill=COLOR_ACCENT)
        if self.logo is not None:
            lg = contain(self.logo, (560, 130))
            im.alpha_composite(lg, ((W - lg.width) // 2, 120))
        f, lines = fit_wrap(d, self.script["title"], W - 360, 3, range(96, 55, -4))
        lh = f.size * 1.35
        top = H / 2 - lh * len(lines) / 2 + 30
        for i, ln in enumerate(lines):
            d.text((W / 2, top + lh * i + lh / 2), ln, font=f, fill=COLOR_WHITE, anchor="mm")
        for key, c in self.chars.items():
            ic = contain(self.icons[key], (220, 220))
            x = 70 if c.get("side") == "left" else W - 70 - ic.width
            im.alpha_composite(ic, (x, H - 120 - ic.height - 30))
        d.text((W / 2, H - 60), self.credit, font=font(30), fill=COLOR_WHITE, anchor="mm")
        return im

    def end_card(self) -> Image.Image:
        im = Image.new("RGBA", (W, H), COLOR_BG + (255,))
        d = ImageDraw.Draw(im)
        d.text((W / 2, 380), "くわしくはブログで！", font=font(96), fill=COLOR_NAVY, anchor="mm")
        f, lines = fit_wrap(d, self.script["title"], W - 300, 2, range(56, 35, -4))
        for i, ln in enumerate(lines):
            d.text((W / 2, 530 + i * f.size * 1.4), ln, font=f, fill=COLOR_TEXT, anchor="mm")
        if self.script.get("url"):
            d.text((W / 2, 720), self.script["url"], font=font(36), fill=COLOR_NAVY, anchor="mm")
        d.text((W / 2, H - 70), self.credit, font=font(30), fill=COLOR_TEXT, anchor="mm")
        return im


# ───────────────────────── 音声 ─────────────────────────

class AudioTrack:
    def __init__(self):
        self.params = None
        self.chunks: list[bytes] = []
        self.frames = 0

    @property
    def rate(self) -> int:
        return self.params.framerate if self.params else 24000

    def add_wav(self, path: Path) -> float:
        with wave.open(str(path), "rb") as w:
            if self.params is None:
                self.params = w.getparams()
            n = w.getnframes()
            self.chunks.append(w.readframes(n))
        self.frames += n
        return n / self.rate

    def add_silence(self, sec: float) -> float:
        n = int(round(sec * self.rate))
        width = (self.params.sampwidth * self.params.nchannels) if self.params else 2
        self.chunks.append(b"\x00" * n * width)
        self.frames += n
        return n / self.rate

    def save(self, path: Path):
        with wave.open(str(path), "wb") as w:
            if self.params is not None:
                w.setparams(self.params)
            else:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.rate)
            for c in self.chunks:
                w.writeframes(c)


# ───────────────────────── メイン ─────────────────────────

def fmt_ts(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def render(script: dict, out_dir: Path, config: dict, limit: int | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir()
    cache = out_dir.parent / "_cache"
    assets = Assets(cache / "img")
    readings = tts.load_readings(config)
    speed = float(config.get("speed", 1.0))
    gap = float(config.get("gap_seconds", 0.25))

    voices = []
    for c in script["characters"].values():
        if c["voice_name"] not in voices:
            voices.append(c["voice_name"])
    credit = " / ".join(f"VOICEVOX:{v}" for v in voices)

    print(f"VOICEVOX ENGINE {tts.wait_engine()} に接続")
    r = Renderer(script, assets, credit)
    audio = AudioTrack()
    segs: list[tuple[str, float]] = []   # (frame file, duration)
    chapters: list[tuple[float, str]] = [(0.0, "オープニング")]
    t = 0.0

    def add_frame(img: Image.Image, dur: float):
        nonlocal t
        p = frames_dir / f"f{len(segs):05d}.png"
        img.convert("RGB").save(p, optimize=False, compress_level=1)
        segs.append((p.name, dur))
        t += dur

    # オープニング：タイトルカードをメインが読み上げ
    main_key = config.get("narration_speaker", "main")
    main = script["characters"][main_key]
    tc = r.title_card()
    tc.convert("RGB").save(out_dir / "thumbnail.png")
    wav = tts.synthesize(tts.apply_readings(script["title"], readings),
                         main["voicevox_speaker"], speed, cache / "tts")
    dur = audio.add_wav(wav) + audio.add_silence(0.8)
    add_frame(tc, dur)

    image_src, chapter = None, None
    lines = [i for i in script["items"] if i["type"] == "line"]
    done = 0
    for item in script["items"]:
        if item["type"] == "image":
            image_src = item["src"]
            continue
        if item["type"] == "chapter":
            chapter = item["text"]
            chapters.append((t, chapter))
            continue
        if limit is not None and done >= limit:
            break
        ch = script["characters"][item["speaker"]]
        for unit in split_units(item["text"]):
            wav = tts.synthesize(tts.apply_readings(unit, readings),
                                 ch["voicevox_speaker"], speed, cache / "tts")
            dur = audio.add_wav(wav) + audio.add_silence(gap)
            add_frame(r.frame(item["speaker"], unit, image_src, chapter), dur)
        done += 1
        print(f"\r  台詞 {done}/{len(lines)}", end="", flush=True)
    print()

    add_frame(r.end_card(), audio.add_silence(END_CARD_SEC))
    audio.save(out_dir / "audio.wav")

    # ffmpeg concat（静止画＋長さ）
    lst = frames_dir / "list.txt"
    with lst.open("w", encoding="utf-8") as f:
        for name, dur in segs:
            f.write(f"file '{name}'\nduration {dur:.4f}\n")
        f.write(f"file '{segs[-1][0]}'\n")
    video = out_dir / "video.mp4"
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(lst),
           "-i", str(out_dir / "audio.wav"),
           "-fps_mode", "cfr", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "medium", "-tune", "stillimage", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-shortest", "-movflags", "+faststart", str(video)]
    subprocess.run(cmd, check=True)

    # 概要欄（チャプター＋クレジット）
    desc = [script["title"], ""]
    if script.get("url"):
        desc += ["▼ 元記事はこちら", script["url"], ""]
    # YouTube のチャプターは「0:00 始まり・3個以上・各10秒以上」が条件
    chap = [(s, n) for i, (s, n) in enumerate(chapters)
            if i == 0 or s - chapters[i - 1][0] >= 10]
    if len(chap) >= 3:
        desc += ["▼ チャプター"] + [f"{fmt_ts(s)} {n}" for s, n in chap] + [""]
    desc += ["▼ 使用音声"] + [f"VOICEVOX:{v}" for v in voices]
    (out_dir / "description.txt").write_text("\n".join(desc) + "\n", encoding="utf-8")

    shutil.rmtree(frames_dir)
    print(f"動画作成: {video}（{fmt_ts(t)}・{len(segs)} カット）")
    return video


def main():
    ap = argparse.ArgumentParser(description="掛け合い台本 JSON から YouTube 用動画を作る")
    ap.add_argument("script", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, help="先頭 N 台詞だけ作る（お試し用）")
    args = ap.parse_args()
    script = json.loads(args.script.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    render(script, args.out, config, args.limit)


if __name__ == "__main__":
    main()
