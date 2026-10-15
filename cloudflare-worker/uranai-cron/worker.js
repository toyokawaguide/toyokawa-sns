/**
 * 占い配信 自動起動トリガー（Cloudflare Workers Cron）
 *
 * 通常記事の sns-cron / ライト記事の light-article-cron と同じ作り。
 * 目的：GitHub Actions の schedule cron が混雑時間帯で 3〜4 時間遅れるため、
 *       Cloudflare の正確な Cron Trigger から定刻に GitHub workflow_dispatch を叩く。
 *
 * 仕組み（UTC cron → JST → 起動モード）：
 *   17 18 * * *  03:17 JST → mode=wp-only   WP 公開（記事生成＋公開＋bridge 保存）
 *   17 20 * * *  05:17 JST → mode=wp-only   WP 公開リトライ（公開済みなら skip-if-published で何もしない）
 *   52 20 * * *  05:52 JST → mode=sns-only  Threads / IG Feed / IG Reels / YouTube ショート投稿
 *
 * 二重投稿対策：post_uranai.yml 側の既投稿マーカー（GHA キャッシュ）＋ Threads/IG の実投稿確認で
 *   GHA の保険 cron が遅れて来ても再投稿されない（main.py run_sns_only 参照）。
 *
 * 必要な Secret（Cloudflare ダッシュボードで設定・コードには書かない）：
 *   GITHUB_PAT  … toyokawa-sns リポの Actions read&write 権限を持つ fine-grained PAT
 *   TRIGGER_KEY … 手動テスト URL 用の合言葉（任意の文字列）
 */

const OWNER = "toyokawaguide";
const REPO = "toyokawa-sns";
const WORKFLOW = "post_uranai.yml";
const REF = "main";

// Cloudflare の cron 文字列 → post_uranai.yml の mode 入力
const MODE_BY_CRON = {
  "17 18 * * *": "wp-only",
  "17 20 * * *": "wp-only",
  "52 20 * * *": "sns-only",
};

async function dispatch(env, mode) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_PAT}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "uranai-cron-worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: REF, inputs: { mode } }),
  });
  const text = await res.text();
  // GitHub は成功時 204 No Content を返す
  return { status: res.status, body: text };
}

export default {
  // Cron Trigger から自動起動
  async scheduled(event, env, ctx) {
    const mode = MODE_BY_CRON[event.cron];
    if (!mode) {
      console.log(`[cron ${event.cron}] 未知の cron → 何もしない`);
      return;
    }
    const r = await dispatch(env, mode);
    console.log(`[cron ${event.cron}] mode=${mode} dispatch -> ${r.status} ${r.body}`);
  },

  // 手動テスト用：Worker の URL を ?key=...&mode=wp-only|sns-only 付きで叩くと即発火
  async fetch(request, env, ctx) {
    const u = new URL(request.url);
    if (u.searchParams.get("key") !== env.TRIGGER_KEY) {
      return new Response("forbidden", { status: 403 });
    }
    const mode = u.searchParams.get("mode") || "sns-only";
    if (!["wp-only", "sns-only", "publish"].includes(mode)) {
      return new Response("mode は wp-only / sns-only / publish のいずれか", { status: 400 });
    }
    const r = await dispatch(env, mode);
    return new Response(
      `mode=${mode} dispatch -> ${r.status}\n${r.body || "(empty = 204 success)"}`,
      { status: 200, headers: { "Content-Type": "text/plain; charset=utf-8" } }
    );
  },
};
