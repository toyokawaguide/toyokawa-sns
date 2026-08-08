# Tools Studio

無料の写真・PDF・QR お助けツール集（完全ブラウザ内処理・登録不要・データ送信なし）。

- 公開URL: https://internal-tools-c15.pages.dev/
- ホスティング: Cloudflare Pages（プロジェクト名: internal-tools-c15）

## このフォルダについて

Cloudflare Pages に直接デプロイされていたサイトのソースを、修正・機能追加できるように
GitHub に保存し直したもの。

### 保存済み

- `index.html` — トップページ（2026-08-08 時点の公開版スナップショット＋部分明るく補正のカード追加）
- `photo_partial_brightener/index.html` — **部分明るく補正（影だけ明るく）** ※2026-08-08 新規作成。
  影の部分をブラシでなぞると、その範囲＋周辺だけをガンマ補正で明るくする。境界は自動でぼかしてなじませる。
  賃貸物件の室内写真に入り込む影の補正用（社長要望）。完全ブラウザ内処理。
  ※ 公開サイトへの反映は未実施 — Cloudflare Pages のダイレクトアップロードはデプロイ全体を置き換えるため、
  先に既存の全ツールページのソースを回収してから一括デプロイすること。

### 未保存（今後、公開サイトから取得して追加が必要）

各ツールページ（全14ツール）:

| パス | ツール |
|---|---|
| `photo_studio/` | 写真まとめて編集（明るく＋リサイズ） |
| `photo_brightener/` | 写真補正（明るく） |
| `photo_resize/` | 写真リサイズ・圧縮 |
| `photo_mosaic/` | 写真モザイク |
| `pdf_organizer/` | PDF編成（並替・回転・削除・結合） |
| `pdf_page_numberer/` | PDFページ番号 |
| `pdf_merger/` | PDF結合 |
| `pdf_split/` | PDF分割 |
| `pdf_compress/` | PDF圧縮 |
| `pdf_rotate/` | PDF回転 |
| `pdf_to_jpg/` | PDF → JPG |
| `jpg_to_pdf/` | JPG → PDF |
| `pdf_trimmer/` | PDFトリミング |
| `pdf_watermark/` | PDF透かし挿入 |

その他のページ:

- `/guide/` 配下の使い方記事（photo-bright-fix, pdf-merge-quick, pdf-watermark-presets, qr-code-7scenes, pdf-page-numbers ほか）
- `/about/`, `/privacy/`, `/terms/`
- `qr_generator/`（QRコード生成）
- 画像アセット: `logo-96.png`, `favicon.ico`, `favicon-32.png`, `apple-touch-icon.png`
