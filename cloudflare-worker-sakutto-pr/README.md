# さくっとPR を毎朝 9:00 に時刻どおり配信する（Cloudflare Workers Cron）

## なにを直すのか

さくっとPR の配信は GitHub Actions の予約実行（schedule cron）で動かしていましたが、
この予約は **2026年7月の運用開始からずっと毎日 3〜6 時間遅れて**到着しています
（9:00 の予定が実際に動くのは 14:00〜18:00）。

- PR004 以降の配信は、ほぼ毎回「社長が気づく → Claude が手で起動」の手動運用になっていた
- 9:30 の確認メールも同じ予約実行なので、15:00 過ぎに届く＝確認の役目を果たしていなかった
- 予約の本数を増やしても（9:00 / 9:10 / 9:20 / 12:00）、GitHub 側の遅れは直らなかった

ライト記事（19:00）と通常記事SNS（7:00）は、2026年6月に同じ問題を
**Cloudflare の Cron → GitHub を即時起動** に切り替えて解決済みです。
さくっとPR にも同じ仕組みを入れます。

```
Cloudflare Cron 09:00 JST ──→ GitHub「さくっとPR配信」を即時起動 ──→ 記事・IG・リール・Threads 投稿
Cloudflare Cron 09:30 JST ──→ GitHub「9:30確認」を即時起動 ──→ 出ているか確認して社長へメール
                                                             （出ていなければ配信を起動して直す）
GitHub の予約実行（9:00/9:10/9:20/12:00）は保険としてそのまま残す（二重投稿はしない設計）
```

## 設定手順（約15分・一度だけ）

### 1. GitHub で「鍵」（Personal Access Token）を作る

1. GitHub にログイン → 右上の自分のアイコン → **Settings**
2. 左メニュー最下部 **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
3. 入力：
   - Token name: `sakutto-pr-cron`
   - Expiration: **1 year**（期限が来たら同じ手順で作り直す）
   - Repository access: **Only select repositories** → `toyokawaguide/toyokawa-sns` を選ぶ
   - Permissions → Repository permissions → **Actions** を **Read and write** にする（それ以外は触らない）
4. **Generate token** → 表示された `github_pat_...` を**この画面を閉じる前に**コピーしておく（二度と表示されません）

### 2. Cloudflare に Worker を作る

1. https://dash.cloudflare.com にログイン → 左メニュー **Workers & Pages** → **Create** → **Create Worker**
2. 名前を `sakutto-pr-cron` にして **Deploy**（中身はあとで差し替える）
3. **Edit code** を開き、エディタの中身を全部消して、このフォルダの `worker.js` の内容を貼り付け → **Deploy**
4. Worker の **Settings** タブ → **Variables and Secrets** → **Add**：
   - Type **Secret**／Variable name `GITHUB_PAT`／Value に手順1でコピーした `github_pat_...` → Save
   - Type **Secret**／Variable name `TRIGGER_KEY`／Value は好きな合言葉（例: `pr-2026`）→ Save
5. **Settings** タブ → **Triggers** → **Cron Triggers** → **Add Cron Trigger** を2回：
   - `0 0 * * *`（= 09:00 JST 配信）
   - `30 0 * * *`（= 09:30 JST 確認）

（ライト記事の Worker を作ったときと同じ画面です。コマンドで入れる場合は、このフォルダで
`wrangler deploy` → `wrangler secret put GITHUB_PAT` → `wrangler secret put TRIGGER_KEY`。）

### 3. 動作確認（本番投稿はしない安全な確認）

Worker の URL（`https://sakutto-pr-cron.<アカウント名>.workers.dev`）に合言葉を付けてブラウザで開く：

```
https://sakutto-pr-cron.<アカウント名>.workers.dev/?key=合言葉&job=check
```

- `check (pr_publish_check.yml) -> 204` と出れば成功。GitHub の Actions タブに
  「さくっとPR 9:30確認」が数秒で現れ、今日のPRが無い日は「ありません」で終わります（メールは出ません）。
- `401` や `404` が出たら、鍵の権限（Actions: Read and write）か対象リポジトリの選択が違います。
- `job=publish` にすると配信ワークフローが起動します。今日の対象（公開希望日=今日・状態=draft）が
  あれば**本当に投稿される**ので、試すなら対象が無い日に。

### 4. 翌朝の見かた

- 9:00 過ぎ：GitHub Actions の「さくっとPR配信」が `workflow_dispatch` で動いている
- 9:30〜9:35：Gmail に「【さくっとPR】M/D 9:30確認：すべてOK」が届く（今日のPRがある日だけ）
- 届かない／「⚠ 出ていないものがあります」のときだけ対応する

## 困ったとき

| 症状 | 見るところ |
|---|---|
| 9:00 に配信が動かない | Cloudflare → Worker → **Logs** に `publish -> 204` があるか。401/404 なら鍵、何も無ければ Cron Trigger の登録 |
| 鍵の期限切れ | GitHub の PAT を作り直し、Cloudflare の `GITHUB_PAT` を上書き（手順1→2-4） |
| 9:30 のメールが来ない | 今日のPRが無い日はメールしない仕様。ある日なのに来ないなら GitHub Actions「9:30確認」のログ |

## 補足

- 「9:30確認」は 2026-10-30 から **出ていなければ配信を自分で起動して直す**ようになりました（`--heal`）。
  起動するのは「状態=draft で、記事も SNS も何も出ていない」ときだけ。途中まで出ている場合は
  二重投稿を避けるため起動せず、メールで知らせます。
- GitHub の予約実行は保険として残しています。遅れて来ても「投稿済」の行は拾わないので二重投稿しません。
