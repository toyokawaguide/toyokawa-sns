# uranai-cron（占い配信の主トリガー・Cloudflare Workers）

GitHub Actions の schedule cron が毎朝 3〜4 時間遅れる問題の対策として、
通常記事（sns-cron）・ライト記事（light-article-cron）と同じ方式で、
Cloudflare Cron から `post_uranai.yml` を `workflow_dispatch` で定刻に起動する。

| Cloudflare cron (UTC) | JST | 起動モード | 内容 |
| --- | --- | --- | --- |
| `17 18 * * *` | 03:17 | `wp-only` | 記事生成＋WP公開＋bridge 保存 |
| `17 20 * * *` | 05:17 | `wp-only` | WP公開リトライ（公開済みなら何もしない） |
| `52 20 * * *` | 05:52 | `sns-only` | Threads / IG Feed / IG Reels / YouTube ショート |

GHA 側の schedule cron はそのまま残す（保険）。既投稿マーカー＋実投稿確認があるので、
遅れて来ても二重投稿にはならない。

## デプロイ手順（Cloudflare アカウントでの作業・1回だけ）

既存の `sns-cron` Worker と同じ手順。

```bash
cd cloudflare-worker/uranai-cron
npx wrangler login                       # 初回のみ
npx wrangler secret put GITHUB_PAT       # toyokawa-sns の Actions: read & write 権限の fine-grained PAT
npx wrangler secret put TRIGGER_KEY      # 手動テスト用の合言葉（任意の文字列）
npx wrangler deploy
```

- `GITHUB_PAT` は **toyokawa-sns** リポジトリに対して「Actions: Read and write」を持つ
  fine-grained PAT を新しく作るか、sns-cron 用の PAT の対象リポに toyokawa-sns を追加したものを使う。
  PAT には有効期限があるので、期限切れで止まったときはここを疑う。
- デプロイ後、Cloudflare ダッシュボードの Workers → uranai-cron → Triggers に 3 本の cron が
  表示されていれば完了。

## 動作確認

```
https://uranai-cron.<アカウント>.workers.dev/?key=<TRIGGER_KEY>&mode=sns-only
```

を開くと即時に dispatch される（`204` が返れば成功）。
`mode` は `wp-only` / `sns-only` / `publish`（WP＋SNS一括復旧）のいずれか。
GitHub Actions の実行一覧に `workflow_dispatch` の実行が増えていれば連携できている。

## 止めたいとき

Cloudflare ダッシュボードで Worker の Triggers を削除するか、Worker ごと削除する。
GHA 側の schedule cron は残っているので、従来どおり（遅れつつも）動き続ける。
