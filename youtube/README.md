# ブログ記事 → YouTube 掛け合い動画

SWELL の吹き出しブロックをそのまま台本にして、2人の掛け合い動画（1920×1080）を作ります。
音声エンジンは **AivisSpeech**（より人間らしい）と **VOICEVOX** を選べます。
**YouTube への公開は自動では行いません。** できた動画を確認してから手動でアップロードしてください。

## GitHub で作る（おすすめ）

1. Actions →「ブログ記事 → YouTube掛け合い動画 作成」→ Run workflow
2. `post_id`（記事ID）か `url` を入れ、`engine` を選んで実行（まず `limit` に `10` を入れてお試しも可）
   - AivisSpeech で別の声を使うときは `aivis_models` に AivisHub のモデル UUID を入れ、`config.json` の `voices.aivisspeech.speaker` をその話者名にする
3. 終わったら実行結果ページ下の **Artifacts** から zip をダウンロード
   - `video.mp4` … 動画本体
   - `description.txt` … 概要欄（元記事リンク・チャプター・音声クレジット）
   - `thumbnail.png` … サムネイル案
   - `script.json` … 台本（誰が何を話すか）

## PC で作る

```bash
# 1) 音声エンジンを起動（アプリ版を起動するだけでも OK）
docker run --rm -p 10101:10101 ghcr.io/aivis-project/aivisspeech-engine:cpu-latest   # AivisSpeech
docker run --rm -p 50021:50021 voicevox/voicevox_engine:cpu-latest                  # VOICEVOX
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
| `engine` | `aivisspeech` か `voicevox`（Actions では実行時に選択） |
| `characters[].voices.<エンジン>` | 話者名・スタイル名（`styles.exclaim` は「！」の台詞で使う声色）。使える名前は実行ログの「使える声」に出る |
| `engines.<エンジン>.voice_tuning` | 抑揚・間・声の揺らぎの調整 |
| `characters[].image` | 立ち絵画像のパス（未設定なら記事の吹き出しアイコン → それも無ければ仮アイコン） |
| `include_narration` | 吹き出し以外の段落も読むか（読む人は `narration_speaker`） |
| `speed` | 話す速さ |
| `timing` | 台詞と台詞の間（短いリアクションは食い気味に重ねる） |
| `readings` | 読み間違える言葉の読み（例：`"国府": "こう"`） |

## 注意

- VOICEVOX は利用規約により `VOICEVOX:キャラ名` のクレジットが必要です（自動で入ります）。
- AivisSpeech はモデルごとにライセンス（ACML / ACML-NC / CC0）が違います。収益化するなら ACML-NC（非商用）のモデルは使わないでください。クレジットは `AivisSpeech:話者名` で自動で入ります。
- キャラクター画像を使う場合は、各キャラクターの利用規約を確認してください。
