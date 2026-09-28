"""
make_video.py — ブログ記事 → 掛け合い台本 → YouTube 動画 を一括で作る

【使い方】（音声エンジン VOICEVOX / AivisSpeech を起動してから・config.json の engine で選択）
python make_video.py --post-id 12345
python make_video.py --url https://toyokawa-rentallife.com/xxxx/
python make_video.py --html ../samples/sample_article.html   # 動作確認用

出力先: youtube/output/<記事ID or ファイル名>/
  script.json（台本・手直し可）/ video.mp4 / description.txt / thumbnail.png

台本を手直ししたいとき:
  1. 一度実行 → script.json を編集
  2. python make_video.py --script ../output/12345/script.json で動画だけ作り直し
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import article_to_script as a2s
import render_video as rv

OUTPUT = Path(__file__).resolve().parents[1] / "output"


def main():
    ap = argparse.ArgumentParser(description="ブログ記事から YouTube 掛け合い動画を作る")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--post-id", type=int)
    src.add_argument("--url")
    src.add_argument("--html", type=Path)
    src.add_argument("--script", type=Path, help="手直し済みの script.json から動画だけ作る")
    ap.add_argument("-o", "--out", type=Path, help="出力フォルダ（省略時 youtube/output/<ID>/）")
    ap.add_argument("--limit", type=int, help="先頭 N 台詞だけ作る（お試し用）")
    args = ap.parse_args()

    config = a2s.load_config()
    if args.script:
        script = json.loads(args.script.read_text(encoding="utf-8"))
        out = args.out or args.script.parent
    else:
        article = a2s.load_html_file(args.html) if args.html else a2s.fetch_post(args.post_id, args.url)
        script = a2s.build_script(article, config)
        out = args.out or OUTPUT / str(article["id"] or args.html.stem)
        out.mkdir(parents=True, exist_ok=True)
        (out / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        s = script["stats"]
        print(f"台本作成: {script['title']} / 台詞 {s['lines']} 件（吹き出し {s['balloons']} 個）")
    rv.render(script, out, config, args.limit)


if __name__ == "__main__":
    main()
