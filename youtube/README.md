# ブログ記事 → YouTube 掛け合い動画

SWELL の吹き出しブロックをそのまま台本にして、VOICEVOX の2人の掛け合い動画（1920×1080）を作ります。
**YouTube への公開は自動では行いません。** できた動画を確認してから手動でアップロードしてください。

## GitHub で作る（おすすめ）

1. Actions →「ブログ記事 → YouTube掛け合い動画 作成」→ Run workflow
2. `post_id`（記事ID）か `url` を入れて実行（まず `limit` に `10` を入れてお試しも可）
3. 終わったら実行結果ページ下の **Artifacts** から zip をダウンロード
   - `video.mp4` … 動画本体
   - `description.txt` … 概要欄（元記事リンク・チャプター・VOICEVOX クレジット）
   - `thumbnail.png` … サムネイル案
   - `script.json` … 台本（誰が何を話すか）

## PC で作る

```bash
# 1) VOICEVOX を起動（アプリ版を起動するだけでも OK）
docker run --rm -p 50021:50021 voicevox/voicevox_engine:cpu-latest
# 2) 動画作成
cd youtube/scripts
pip install -r requirements.txt
python make_video.py --post-id 12345
# 台本(script.json)を手直ししてから作り直す
python make_video.py --script ../output/12345/script.json
```

## 設定（config.json）

| 項目 | 内容 |
|---|---|
| `characters[].aliases` | 吹き出しの名前（例：「管理人」）→ このキャラの声になる |
| `characters[].side` | 名前で決まらないとき、吹き出しの左右で声を決める |
| `characters[].voicevox_speaker` | VOICEVOX の話者ID（2=四国めたん, 3=ずんだもん など） |
| `characters[].image` | 立ち絵画像のパス（未設定なら記事の吹き出しアイコン → それも無ければ仮アイコン） |
| `include_narration` | 吹き出し以外の段落も読むか（読む人は `narration_speaker`） |
| `speed` | 話す速さ |
| `readings` | 読み間違える言葉の読み（例：`"国府": "こう"`） |

## 注意

- VOICEVOX の利用規約により、動画内と概要欄に `VOICEVOX:キャラ名` のクレジットが必要です（自動で入ります）。
- キャラクター画像を使う場合は、各キャラクターの利用規約を確認してください。
