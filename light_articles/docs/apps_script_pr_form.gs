/**
 * さくっとPR 掲載申込フォーム（2026-08-02）
 *
 * これを1回実行するだけで、
 *   ① 申込フォームを新規作成
 *   ② 送信されたら「ライト記事キュー_v2」の PRキュー タブへ自動で1行追加（状態=申込）
 *   ③ 申込者へ受付メールを自動返信（控え付き）
 *   ④ 社長へ「申込が入りました」通知
 * まで全部そろいます。
 *
 * ■ 使い方（1回だけ）
 *   1. ブラウザで https://script.google.com/home を開く
 *   2. 左上の「新しいプロジェクト」をクリック
 *   3. 出てきたコードを全部消して、このファイルの中身を貼り付けて保存
 *      （※スプレッドシート側の Apps Script は開かない。既存コードに触れないため）
 *   4. 関数 setupPrForm を選んで実行（初回だけ権限の確認 → 許可）
 *   5. 実行ログに出てくる「公開URL」を、WPの募集ページに貼る
 *
 * ■ 2回目以降
 *   もう実行しなくてOK。項目を変えたいときだけ、フォームを直接編集してください。
 */

// ★このスクリプトは「ライト記事キュー」とは独立した単体プロジェクトとして動く。
//   スプレッドシートに付いている既存のスクリプトには一切触れない。
var SPREADSHEET_ID = '155K-AQdLNUiYb4Z3MK-elyG1U7UIIxPeu397uZsVxdo';   // ライト記事キュー

// ⚠️ 触るのはこのタブだけ。ライト記事の本番タブ「キュー」には絶対に触れない。
var SHEET_NAME = 'PRキュー';
var OWNER_MAIL = 'toyokawa.rentallife@gmail.com';   // 社長への通知先
var SITE_NAME  = '豊川ガイド';
var SERIES     = 'さくっとPR';

/** 掲載基準（フォームの説明にも、受付メールにも同じ文面を使う） */
var POLICY = [
  '【お断りする内容】',
  '・アダルト、性風俗に関するもの',
  '・反社会的勢力に関係するもの',
  '・宗教の勧誘を目的とするもの',
  '・公序良俗に反する内容',
  '・特定の個人、団体への誹謗中傷を含むもの',
  '・法令に違反する、または違反のおそれがあるもの',
  '・事実と異なる表示や、誇大な表現を含むもの',
  '・その他、当サイトが不適切と判断したもの',
  '',
  '※内容によっては掲載をお断りする場合があります。あらかじめご了承ください。'
].join('\n');

/** PRキューの列（既存の並びに合わせる。後ろの5列は今回の申込フォーム用に追加） */
var COLS = ['ID', '公開希望日', '状態', '店名', 'ひとことキャッチ', 'ジャンル',
            'エリア・住所', '営業時間', '定休日', 'リンク', '特典・クーポン',
            '紹介文メモ', 'つぶやき', '備考',
            '申込者名', 'メールアドレス', '電話番号', '受付日時', '料金区分'];

/** フォームの質問（title は回答オブジェクトのキーになるので、変えたら MAP も直すこと） */
var QUESTIONS = [
  {t: 'お店・教室のお名前', req: true,  help: '記事の見出しに使います'},
  {t: 'ジャンル',           req: true,  help: '例：カフェ／美容室／学習塾／整体'},
  {t: 'ひとことキャッチ',   req: true,  help: '20文字くらい。例：「朝7時から開いてます」／改行するとその位置で行が変わります', long: true},
  {t: 'エリア・住所',       req: true,  help: '例：豊川市諏訪3丁目○○'},
  {t: '営業時間',           req: false, help: '空欄でもOK'},
  {t: '定休日',             req: false, help: '空欄でもOK'},
  {t: 'ホームページ・SNSのURL', req: false, help: '複数ある場合は改行で'},
  {t: '特典・クーポン',     req: false, help: '例：「この記事を見たと言うと1ドリンク無料」'},
  {t: '紹介してほしい内容', req: true,  help: '箇条書きで構いません。ここをもとに記事を書きます', long: true},
  {t: '読者へのひとこと',   req: false, help: '店主さんの言葉としてそのまま載せます', long: true},
  {t: 'ご担当者のお名前',   req: true,  help: ''},
  {t: 'メールアドレス',     req: true,  help: '完成イメージ（プレビュー）をこちらへお送りします'},
  {t: '電話番号',           req: false, help: ''}
];

/** 質問タイトル → PRキューの列名 */
var MAP = {
  'お店・教室のお名前': '店名',
  'ジャンル': 'ジャンル',
  'ひとことキャッチ': 'ひとことキャッチ',
  'エリア・住所': 'エリア・住所',
  '営業時間': '営業時間',
  '定休日': '定休日',
  'ホームページ・SNSのURL': 'リンク',
  '特典・クーポン': '特典・クーポン',
  '紹介してほしい内容': '紹介文メモ',
  '読者へのひとこと': 'つぶやき',
  'ご担当者のお名前': '申込者名',
  'メールアドレス': 'メールアドレス',
  '電話番号': '電話番号'
};

// ───────────────────────────── セットアップ ─────────────────────────────

function setupPrForm() {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var props = PropertiesService.getScriptProperties();
  var existing = props.getProperty('PR_FORM_ID');
  if (existing) {
    var f = FormApp.openById(existing);
    Logger.log('すでに作成済みです。\n公開URL: ' + f.getPublishedUrl() + '\n編集URL: ' + f.getEditUrl());
    return;
  }

  var form = FormApp.create(SITE_NAME + '「' + SERIES + '」掲載のお申し込み');
  form.setDescription(
    SITE_NAME + 'の広告コーナー「' + SERIES + '」への掲載申し込みフォームです。\n' +
    '送信いただくと、こちらで記事の下書きと画像を作り、完成イメージをメールでお送りします。\n' +
    '内容をご確認いただいてから公開しますので、送信した時点では公開されません。\n\n' +
    POLICY
  );
  form.setCollectEmail(false);
  form.setLimitOneResponsePerUser(false);
  form.setConfirmationMessage(
    'お申し込みありがとうございます。\n' +
    '完成イメージができ次第、ご入力のメールアドレスへお送りします（通常1〜2日以内・まれに数日いただく場合があります）。\n' +
    '内容の修正はメールへの返信でお受けします。'
  );

  QUESTIONS.forEach(function (q) {
    var item = q.long ? form.addParagraphTextItem() : form.addTextItem();
    item.setTitle(q.t).setRequired(!!q.req);
    if (q.help) item.setHelpText(q.help);
  });

  form.addCheckboxItem()
      .setTitle('掲載基準の確認')
      .setChoiceValues(['上記の掲載基準を確認し、同意します'])
      .setRequired(true);

  form.addParagraphTextItem()
      .setTitle('写真について')
      .setHelpText('写真がある場合は、このあと届く受付メールに添付して返信してください。'
                 + '（写真が無くてもカード型の画像で掲載できます）\nご要望があればこちらへ。')
      .setRequired(false);

  ensureSheet(ss);
  props.setProperty('PR_FORM_ID', form.getId());

  ScriptApp.newTrigger('onPrFormSubmit').forForm(form).onFormSubmit().create();

  Logger.log('できました。\n公開URL: ' + form.getPublishedUrl() + '\n編集URL: ' + form.getEditUrl());
}

function ensureSheet(ss) {
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(SHEET_NAME);
    sh.getRange(1, 1, 1, COLS.length).setValues([COLS]);
    return sh;
  }
  var head = sh.getRange(1, 1, 1, Math.max(sh.getLastColumn(), 1)).getValues()[0];
  COLS.forEach(function (c) {                       // 足りない列だけ後ろに追加（既存は触らない）
    if (head.indexOf(c) === -1) {
      sh.getRange(1, head.length + 1).setValue(c);
      head.push(c);
    }
  });
  return sh;
}

// ───────────────────────────── 送信されたとき ─────────────────────────────

function onPrFormSubmit(e) {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sh = ensureSheet(ss);
  var head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];

  var ans = {};
  e.response.getItemResponses().forEach(function (r) {
    ans[r.getItem().getTitle()] = String(r.getResponse() || '').trim();
  });

  var row = new Array(head.length).fill('');
  function put(col, val) {
    var i = head.indexOf(col);
    if (i >= 0) row[i] = val;
  }
  Object.keys(MAP).forEach(function (q) { put(MAP[q], ans[q] || ''); });

  put('ID', nextPrId(sh, head));
  put('状態', '申込');                 // 社長が確認して draft に変えると配信対象になる
  put('受付日時', Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm'));
  put('料金区分', '無料');        // 当面すべて無料枠。有料商品は別途つくる予定（社長方針 2026-08-02）
  put('備考', ans['写真について'] || '');

  sh.appendRow(row);

  var id = row[head.indexOf('ID')];
  var shop = ans['お店・教室のお名前'] || '';
  var to = ans['メールアドレス'] || '';

  if (to) {
    MailApp.sendEmail({
      to: to,
      subject: '【' + SITE_NAME + '】' + SERIES + ' お申し込みを受け付けました（' + id + '）',
      body: [
        (ans['ご担当者のお名前'] || 'ご担当者') + ' 様',
        '',
        SITE_NAME + 'です。「' + SERIES + '」へのお申し込みありがとうございます。',
        '受付番号：' + id,
        '',
        '━━━━━━━━━━━━━━━━━━',
        '【重要】写真を載せたい方へ',
        'このメールに写真を添付して、そのまま返信してください（最大5枚・1枚でもOK）',
        '※お申し込みページで選んだ写真は、仕組みの都合で送信されていません',
        '（写真が無くてもカード型の画像で掲載できます）',
        '━━━━━━━━━━━━━━━━━━',
        '',
        'これから記事の下書きと画像を作り、完成イメージをこのメールアドレスへお送りします。',
        '（通常1〜2日以内・まれに数日いただく場合があります）',
        '※管理人からのご連絡・作業は、基本的に夜の時間帯となります。',
        '　ご返信が遅い時間や翌日以降になる場合がありますが、必ずお返事いたします。',
        '内容をご確認いただいてから公開しますので、まだ公開はされていません。',
        '',
        '───────────────',
        '■ お申し込み内容',
        'お店・教室：' + shop,
        'ジャンル：' + (ans['ジャンル'] || ''),
        'ひとことキャッチ：' + (ans['ひとことキャッチ'] || ''),
        'エリア・住所：' + (ans['エリア・住所'] || ''),
        '営業時間：' + (ans['営業時間'] || ''),
        '定休日：' + (ans['定休日'] || ''),
        'リンク：' + (ans['ホームページ・SNSのURL'] || ''),
        '特典・クーポン：' + (ans['特典・クーポン'] || ''),
        '',
        '紹介してほしい内容：',
        (ans['紹介してほしい内容'] || ''),
        '',
        '読者へのひとこと：',
        (ans['読者へのひとこと'] || ''),
        '───────────────',
        '',
        POLICY,
        '',
        SITE_NAME
      ].join('\n')
    });
  }

  MailApp.sendEmail(OWNER_MAIL,
    '【申込】' + SERIES + ' ' + id + '：' + shop,
    ['さくっとPRの申し込みが入りました。',
     '',
     '受付番号：' + id,
     'お店：' + shop + '（' + (ans['ジャンル'] || '') + '）',
     '担当者：' + (ans['ご担当者のお名前'] || '') + ' / ' + to,
     '',
     'PRキュータブの一番下に「状態=申込」で入っています。',
     'プレビューは自動で申込者へ送られます。',
     '内容を確認して問題なければ、公開希望日を入れて 状態を draft にしてください。'
    ].join('\n'));
}

function nextPrId(sh, head) {
  var i = head.indexOf('ID');
  if (i < 0 || sh.getLastRow() < 2) return 'PR001';
  var vals = sh.getRange(2, i + 1, sh.getLastRow() - 1, 1).getValues();
  var max = 0;
  vals.forEach(function (v) {
    var m = String(v[0] || '').match(/^PR(\d+)$/);
    if (m) max = Math.max(max, parseInt(m[1], 10));
  });
  return 'PR' + ('00' + (max + 1)).slice(-3);
}
