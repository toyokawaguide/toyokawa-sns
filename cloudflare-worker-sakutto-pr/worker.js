/**
 * さくっとPR 配信トリガー（Cloudflare Workers Cron）
 *
 * ライト記事（light-article-cron）・通常記事SNS（sns-cron）と全く同じ作り。
 *
 * なぜ必要か（2026-10-30 調査）：
 *   toyokawa-sns の GitHub Actions schedule cron は、2026-07 の運用開始からずっと
 *   毎日 3〜6 時間遅れて到着している（9:00 の配信が実際に動くのは 14:00〜18:00）。
 *   そのため さくっとPR は PR004 以降ほぼ毎回、社長の「出てない」→ Claude が手で
 *   workflow_dispatch という手動運用になっていた。9:30 の確認メールも同じ cron で
 *   動くので 15:00 過ぎに届き、確認の役目を果たしていなかった。
 *   Cloudflare の Cron Trigger は時刻どおりに発火するので、ここから GitHub の
 *   workflow_dispatch を叩いて GHA を即時起動する（GHA 側の cron は保険として残す）。
 *
 * 仕組み：
 *   09:00 JST（UTC 00:00）… post_pr_article.yml を mode=publish で起動
 *                           → PRキューの「公開希望日=今日・状態=draft」を1件配信
 *                             （該当なしの日は「本日のさくっとPRはありません」で正常終了）
 *   09:30 JST（UTC 00:30）… pr_publish_check.yml を起動
 *                           → 記事・IG投稿・IGリール・Threads・状態を確認し社長へメール。
 *                             9:00 の配信が動いていなければ、この中から配信を起動して直す（--heal）
 *
 * 必要な Secret（Cloudflare ダッシュボードで設定・コードには書かない）：
 *   GITHUB_PAT  … toyokawa-sns リポの Actions: Read and write 権限を持つ fine-grained PAT
 *   TRIGGER_KEY … 手動テストURL用の合言葉（任意の文字列）
 *
 * 二重発火対策：publish_pr_article.py が WP 既存チェック＋状態「投稿済」で重複を弾く。
 *               post_pr_article.yml の concurrency で同時実行もしない。
 */

const OWNER = "toyokawaguide";
const REPO = "toyokawa-sns";
const REF = "main";

// どの cron でどのワークフローを起こすか（wrangler.toml の crons と一致させる）
const JOBS = {
  publish: { workflow: "post_pr_article.yml", inputs: { mode: "publish" } },
  check:   { workflow: "pr_publish_check.yml", inputs: {} },
};
const CRON_TO_JOB = {
  "0 0 * * *":  "publish",   // 09:00 JST
  "30 0 * * *": "check",     // 09:30 JST
};

async function dispatch(env, jobName) {
  const job = JOBS[jobName];
  if (!job) {
    return { status: 400, body: `unknown job: ${jobName}（publish / check のどちらか）` };
  }
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${job.workflow}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_PAT}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "sakutto-pr-cron-worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: REF, inputs: job.inputs }),
  });
  const text = await res.text();
  // GitHub は成功時 204 No Content を返す
  return { status: res.status, body: text, workflow: job.workflow };
}

export default {
  // Cron Trigger から自動起動
  async scheduled(event, env, ctx) {
    const jobName = CRON_TO_JOB[event.cron] || "publish";
    const r = await dispatch(env, jobName);
    console.log(`[cron ${event.cron}] ${jobName} (${r.workflow}) -> ${r.status} ${r.body}`);
  },

  // 手動テスト用：Worker の URL を ?key=合言葉&job=publish（または check）付きで叩くと即発火
  async fetch(request, env, ctx) {
    const u = new URL(request.url);
    if (u.searchParams.get("key") !== env.TRIGGER_KEY) {
      return new Response("forbidden", { status: 403 });
    }
    const jobName = u.searchParams.get("job") || "publish";
    const r = await dispatch(env, jobName);
    return new Response(
      `${jobName} (${r.workflow || "-"}) -> ${r.status}\n${r.body || "(empty = 204 success)"}`,
      { status: 200, headers: { "Content-Type": "text/plain; charset=utf-8" } }
    );
  },
};
