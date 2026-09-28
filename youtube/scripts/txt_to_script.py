"""
txt_to_script.py — 手書きの掛け合い台本（txt）を script.json に変換する

台本の書式（1行1台詞）:
  話者｜台詞｜読みメモ（任意・人が見る用。音声には readings を使う）
  【チャプター名】
  ［画面：ファイル名］          … 以降の台詞の背景に出す画像（projects/<ID>/img/ 内のファイル名）
  # で始まる行はコメント

使い方:
  python txt_to_script.py ../projects/36171/project.json
  → ../projects/36171/script.json ができる → python make_video.py --script ../projects/36171/script.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import article_to_script as a2s


def convert(project_path: Path) -> Path:
    proj = json.loads(project_path.read_text(encoding="utf-8"))
    base = project_path.parent
    config = a2s.load_config()
    speakers = proj["speakers"]            # {"管理人": {"key": "main", "image": "img/..."}, ...}

    chars = {}
    for c in config["characters"]:
        chars[c["key"]] = {**c, "display_name": "", "icon": None}
    for name, s in speakers.items():
        ch = chars[s["key"]]
        ch["display_name"] = name
        if s.get("image"):
            ch["image"] = str(base / s["image"])

    items = []
    lines = 0
    for raw in (base / proj["script_txt"]).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"【(.+)】", line)
        if m:
            items.append({"type": "chapter", "text": m.group(1)})
            continue
        m = re.fullmatch(r"［画面：(.+)］", line)
        if m:
            items.append({"type": "image", "src": str(base / "img" / m.group(1).strip())})
            continue
        parts = line.split("｜")
        if len(parts) < 2 or parts[0] not in speakers:
            print(f"[注意] 読めない行を飛ばしました: {line}", file=sys.stderr)
            continue
        items.append({"type": "line", "speaker": speakers[parts[0]]["key"], "text": parts[1]})
        lines += 1

    script = {
        "title": proj["title"],
        "url": proj.get("url", ""),
        "post_id": proj.get("post_id"),
        "opening_say": proj.get("opening_say"),
        "readings": proj.get("readings", {}),
        "characters": chars,
        "items": items,
        "stats": {"lines": lines, "balloons": 0},
    }
    out = base / "script.json"
    out.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"台本変換: 台詞 {lines} 件 → {out}")
    return out


if __name__ == "__main__":
    convert(Path(sys.argv[1]).resolve())
