"""
article_to_script.py — ブログ記事（WordPress/SWELL）→ 掛け合い台本 JSON

【方針】
- SWELL の吹き出し（.c-balloon）を「話者＋台詞」としてそのまま使う（AIで書き換えない）
- 見出し(h2/h3) はチャプター、画像は「以降の台詞の背景写真」
- 吹き出し以外の段落は narration_speaker（既定：メイン）が読む（config で無効化可）
- 吹き出しのアイコン画像をキャラクター画像として台本に記録

【使い方】
python article_to_script.py --post-id 12345 -o ../output/12345/script.json
python article_to_script.py --url https://toyokawa-rentallife.com/xxxx/ -o script.json
python article_to_script.py --html ../samples/sample_article.html -o script.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT.parent / "config.json"
WP_URL = (os.environ.get("WP_URL") or "https://toyokawa-rentallife.com").rstrip("/")

# 本文から読まない部分（目次・関連記事・広告・シェアボタン等）
SKIP_CLASSES = {
    "p-toc", "swell-block-postLink", "p-blogCard", "c-shareBtns", "p-relatedPosts",
    "wp-block-embed", "swell-block-adBox", "p-adBox", "c-balloon__shapes",
    "wp-block-buttons", "swell-block-button",
}
TEXT_TAGS = {"p", "li", "blockquote"}
HEADING_TAGS = {"h2", "h3", "h4"}


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


# ───────────────────────── 記事取得 ─────────────────────────

def _auth():
    """下書き記事も読めるよう、認証情報があれば使う（公開記事なら不要）"""
    user, pw = os.environ.get("WP_USERNAME"), os.environ.get("WP_PASSWORD")
    return (user, pw) if user and pw else None


def fetch_post(post_id: int | None = None, url: str | None = None) -> dict:
    """WP REST API から {id, title, link, html} を取得"""
    fields = "id,link,title,content"
    if url and not post_id:
        q = parse_qs(urlparse(url).query)
        if "p" in q:
            post_id = int(q["p"][0])
    if post_id:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
                         params={"_fields": fields, "context": "view"},
                         auth=_auth(), timeout=30)
        r.raise_for_status()
        data = r.json()
    else:
        slug = [s for s in urlparse(url).path.split("/") if s][-1]
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts",
                         params={"slug": slug, "_fields": fields},
                         auth=_auth(), timeout=30)
        r.raise_for_status()
        if not r.json():
            raise RuntimeError(f"記事が見つかりません: slug={slug}")
        data = r.json()[0]
    title = BeautifulSoup(data["title"]["rendered"], "html.parser").get_text()
    return {"id": data["id"], "title": title, "link": data["link"],
            "html": data["content"]["rendered"], "base": data["link"]}


def load_html_file(path: Path) -> dict:
    """ローカル HTML（テスト用）。<title> を記事タイトルとして扱う"""
    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else path.stem
    body = soup.body or soup
    return {"id": None, "title": title, "link": "", "html": str(body),
            "base": path.resolve().as_uri()}


# ───────────────────────── 解析 ─────────────────────────

def _clean(text: str) -> str:
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _img_src(img: Tag, base: str) -> str | None:
    """遅延読み込み(data-src)・srcset を考慮して一番大きい画像 URL を返す"""
    srcset = img.get("data-srcset") or img.get("srcset")
    if srcset:
        cands = []
        for part in srcset.split(","):
            bits = part.strip().split()
            if bits:
                w = int(bits[1][:-1]) if len(bits) > 1 and bits[1].endswith("w") else 0
                cands.append((w, bits[0]))
        if cands:
            return urljoin(base, max(cands)[1])
    src = img.get("data-src") or img.get("src")
    if not src or src.startswith("data:"):
        return None
    return urljoin(base, src)


def _has_skip_class(el: Tag) -> bool:
    return bool(SKIP_CLASSES.intersection(el.get("class") or []))


def _parse_balloon(el: Tag, base: str) -> dict | None:
    bln = el if "c-balloon" in (el.get("class") or []) else el.select_one(".c-balloon")
    if bln is None:
        return None
    name_el = bln.select_one(".c-balloon__iconName")
    icon_el = bln.select_one(".c-balloon__iconImg, .c-balloon__icon img")
    text_el = bln.select_one(".c-balloon__text") or bln.select_one(".c-balloon__body")
    if text_el is None:
        return None
    for shp in text_el.select(".c-balloon__shapes"):
        shp.decompose()
    paras = [_clean(p.get_text()) for p in text_el.find_all(["p", "li"])] or [_clean(text_el.get_text("\n"))]
    classes = bln.get("class") or []
    return {
        "name": name_el.get_text(strip=True) if name_el else "",
        "side": "right" if "-bln-right" in classes else "left",
        "icon": _img_src(icon_el, base) if icon_el else None,
        "texts": [p for p in paras if p],
    }


def _walk(node: Tag, base: str, out: list):
    """本文を文書順にたどり、balloon / heading / image / text を out に積む"""
    for child in node.children:
        if isinstance(child, NavigableString) or not isinstance(child, Tag):
            continue
        cls = child.get("class") or []
        if _has_skip_class(child) or child.name in ("script", "style", "noscript"):
            continue
        if "swell-block-balloon" in cls or "c-balloon" in cls:
            b = _parse_balloon(child, base)
            if b:
                out.append({"kind": "balloon", **b})
            continue
        if child.name in HEADING_TAGS:
            t = _clean(child.get_text())
            if t:
                out.append({"kind": "heading", "text": t})
            continue
        if child.name == "img":
            src = _img_src(child, base)
            if src:
                out.append({"kind": "image", "src": src})
            continue
        if child.name == "figure" or "wp-block-image" in cls:
            img = child.find("img")
            if img is not None:
                src = _img_src(img, base)
                if src:
                    out.append({"kind": "image", "src": src})
            continue
        if child.name in TEXT_TAGS:
            # 段落内の画像（クラシックエディタ）
            for img in child.find_all("img"):
                src = _img_src(img, base)
                if src:
                    out.append({"kind": "image", "src": src})
            t = _clean(child.get_text())
            if t:
                out.append({"kind": "text", "text": t})
            continue
        _walk(child, base, out)


# ───────────────────────── 話者の割り当て ─────────────────────────

def _resolve_speaker(name: str, side: str, config: dict) -> str:
    chars = config["characters"]
    for c in chars:
        if name and name in c.get("aliases", []):
            return c["key"]
    for c in chars:
        if c.get("side") == side:
            return c["key"]
    return chars[0]["key"]


def build_script(article: dict, config: dict) -> dict:
    blocks: list[dict] = []
    _walk(BeautifulSoup(article["html"], "html.parser"), article["base"], blocks)

    chars = {c["key"]: {**c, "display_name": "", "icon": None} for c in config["characters"]}
    for ch in chars.values():
        # 立ち絵画像は youtube/ フォルダからの相対パスで書ける
        if ch.get("image") and not Path(ch["image"]).is_absolute():
            ch["image"] = str((CONFIG_PATH.parent / ch["image"]).resolve())
    narr = config.get("narration_speaker", "main")
    items: list[dict] = []
    for b in blocks:
        if b["kind"] == "balloon":
            key = _resolve_speaker(b["name"], b["side"], config)
            ch = chars[key]
            # 記事内で最初に出た名前・アイコンを、そのキャラの表示名・画像にする
            ch["display_name"] = ch["display_name"] or b["name"]
            ch["icon"] = ch["icon"] or b["icon"]
            for t in b["texts"]:
                items.append({"type": "line", "speaker": key, "text": t})
        elif b["kind"] == "heading":
            items.append({"type": "chapter", "text": b["text"]})
        elif b["kind"] == "image":
            items.append({"type": "image", "src": b["src"]})
        elif b["kind"] == "text" and config.get("include_narration", True):
            items.append({"type": "line", "speaker": narr, "text": b["text"]})

    for ch in chars.values():
        ch["display_name"] = ch["display_name"] or ch["voice_name"]

    n_lines = sum(1 for i in items if i["type"] == "line")
    n_bln = sum(1 for b in blocks if b["kind"] == "balloon")
    if n_bln == 0:
        print("  [注意] 吹き出しブロックが見つかりませんでした（地の文のみで台本化）", file=sys.stderr)
    return {
        "title": article["title"],
        "url": article["link"],
        "post_id": article["id"],
        "characters": chars,
        "items": items,
        "stats": {"lines": n_lines, "balloons": n_bln},
    }


def main():
    ap = argparse.ArgumentParser(description="ブログ記事を掛け合い台本 JSON にする")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--post-id", type=int)
    src.add_argument("--url")
    src.add_argument("--html", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    article = load_html_file(args.html) if args.html else fetch_post(args.post_id, args.url)
    script = build_script(article, load_config())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    s = script["stats"]
    print(f"台本作成: {script['title']} / 台詞 {s['lines']} 件（吹き出し {s['balloons']} 個）→ {args.out}")


if __name__ == "__main__":
    main()
