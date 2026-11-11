/**
 * さくっと物件紹介 掲載申込フォーム（2026-11-11）
 *
 * これを1回実行するだけで、
 *   ① 申込フォームを新規作成
 *   ② 送信されたら「さくっと物件紹介キュー」の 物件紹介キュー タブへ自動で1行追加（状態=申込・種別=依頼掲載）
 *   ③ 申込者へ受付メールを自動返信（控え付き・info@toyokawaguide.com 名義）
 *   ④ 社長へ「申込が入りました」通知
 * まで全部そろいます。
 *
 * ■ 使い方（1回だけ）
 *   1. ブラウザで https://script.google.com/home を開く
 *   2. 左上の「新しいプロジェクト」をクリック
 *   3. 出てきたコードを全部消して、このファイルの中身を貼り付けて保存
 *      （※さくっとPRのプロジェクトには貼らない。必ず「新しいプロジェクト」に）
 *   4. 関数 setupBukkenForm を選んで実行（初回だけ権限の確認 → 許可）
 *   5. 実行ログに出てくる「公開URL」を Claude に伝える
 */

var SPREADSHEET_ID = '1o0q3lvupz9MiKMYSmzfpvVNTdG-jY3juyfyrSkOoOR8';   // ★さくっと物件紹介キュー（専用シート）
var SHEET_NAME = '物件紹介キュー';   // ⚠️ 触るのはこのタブだけ
var OWNER_MAIL = 'toyokawa.rentallife@gmail.com';   // 社長への通知先
var SITE_NAME  = '豊川ガイド';
var PUBLIC_FROM = 'info@toyokawaguide.com';   // 申込者に見える差出人（Gmailの「他のアドレス」に登録済みのエイリアス）
var SERIES     = 'さくっと物件紹介';

/** このコーナーの決まり（フォームの説明にも、受付メールにも同じ文面を使う） */
var POLICY = [
  '【このコーナーの決まり】',
  '・記事の冒頭に「このコーナーは、良いことしか言いません。豊川ガイド、バリバリ忖度してます」と入ります',
  '・ご依頼による掲載には【PR】と「広告」の表示が入ります（無料でも入ります）',
  '・良いところだけを書きますが、事実と違うこと・大げさな表現（最高、日本一、格安 など）は書けません',
  '・豊川ガイドは、内見の手配・条件のご相談・お申し込みの受付は行いません（お問い合わせは、記事に載せるご依頼者さまの連絡先へ直接）',
  '・貸主ご本人、または貸主・管理会社の了承を得ている方からのお申し込みに限ります',
  '・お部屋が決まったら、ご連絡ください（記事に「募集終了」と表示します）',
  '',
  '【お断りする内容】',
  '・告知が必要な事項を隠す目的のもの',
  '・事実と異なる表示や、誇大な表現を含むもの',
  '・法令に違反する、または違反のおそれがあるもの',
  '・その他、当サイトが不適切と判断したもの',
  '',
  '※内容によっては掲載をお断りする場合があります。あらかじめご了承ください。'
].join('\n');

/** キューの列（publish_bukken_article.py / bukken_builder.py と同じ名前） */
var COLS = ['ID', '公開希望日', '状態', '種別', '物件名', '町名', 'ひとことキャッチ',
            'ほめ1見出し', 'ほめ1本文', 'ほめ2見出し', 'ほめ2本文', 'ほめ3見出し', 'ほめ3本文', 'ひとこと',
            '構造・階数', '完成年', '小学校区', '中学校区', '物件ページ', '募集情報', '問い合わせ', '依頼者から',
            '備考', '申込者名', 'メールアドレス', '受付日時'];

/** フォームの質問（title は回答のキーになるので、変えたら下の onBukkenFormSubmit も直すこと） */
var QUESTIONS = [
  {t: '物件名',               req: true,  help: '記事の見出しに使います。例：○○ハイツ'},
  {t: '所在地（町名まで）',   req: true,  help: '番地は載せません。例：豊川市諏訪／豊川市一宮町'},
  {t: 'あなたのお立場',       req: true,  choice: ['大家（貸主）', '管理会社', '仲介会社', 'その他']},
  {t: '会社名・お名前（広告主として記事に載せます）', req: true, help: '例：○○不動産／大家の○○'},
  {t: 'ほめてほしいところ①', req: true,  help: '事実を教えてください。例：「駐車場が1部屋に2台ついています」', long: true},
  {t: 'ほめてほしいところ②', req: false, help: '例：「スーパーまで約240m（歩いて3分）です」', long: true},
  {t: 'ほめてほしいところ③', req: false, help: '例：「全部屋、ベランダが南向きです」', long: true},
  {t: '構造・階数',           req: false, help: '例：木造・2階建'},
  {t: '完成した年（築年月）', req: false, help: '例：2020年3月'},
  {t: '募集情報（載せたい方だけ）', req: false, long: true,
   help: '家賃などを載せる場合は、次の項目を1行ずつ書いてください。\n交通：○○駅 徒歩○分\n間取り・面積：2LDK・55㎡\n賃料：○万○千円\n管理費など：○千円\n敷金・礼金：○ヶ月・○ヶ月\n※書かなければ、建物の紹介だけになります'},
  {t: 'お問い合わせ先（記事に載せます）', req: true, help: '電話番号・ホームページなど。読者はここへ直接連絡します', long: true},
  {t: '読者へのひとこと',     req: false, help: 'ご依頼者さまの言葉としてそのまま載せます', long: true},
  {t: 'ご担当者のお名前',     req: true,  help: '記事には載せません'},
  {t: 'メールアドレス',       req: true,  help: '完成イメージをこちらへお送りします。記事には載せません'}
];

// ───────────────────────────── セットアップ ─────────────────────────────

function setupBukkenForm() {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var props = PropertiesService.getScriptProperties();
  var existing = props.getProperty('BUKKEN_FORM_ID');
  if (existing) {
    var f = FormApp.openById(existing);
    Logger.log('すでに作成済みです。\n公開URL: ' + f.getPublishedUrl() + '\n編集URL: ' + f.getEditUrl());
    return;
  }
  ensureSheet(ss);   // 先に参照先を確かめる（間違っていたらフォームを作る前に止まる）

  var form = FormApp.create(SITE_NAME + '「' + SERIES + '」掲載のお申し込み');
  form.setDescription(
    SITE_NAME + 'の物件ほめコーナー「' + SERIES + '」への掲載申し込みフォームです（無料）。\n' +
    '送信いただくと、こちらで記事の下書きと画像を作り、完成イメージをメールでお送りします。\n' +
    '内容をご確認いただいてから公開しますので、送信した時点では公開されません。\n\n' +
    POLICY
  );
  form.setCollectEmail(false);
  form.setLimitOneResponsePerUser(false);
  form.setConfirmationMessage(
    'お申し込みありがとうございます。\n' +
    '受付メールをお送りしました（info@toyokawaguide.com から届きます。見当たらないときは迷惑メールもご確認ください）。\n' +
    '写真は、その受付メールに添付して返信してください。\n' +
    '完成イメージができ次第、メールでお送りします（通常数日以内）。'
  );

  QUESTIONS.forEach(function (q) {
    var item;
    if (q.choice) {
      item = form.addMultipleChoiceItem().setChoiceValues(q.choice);
    } else {
      item = q.long ? form.addParagraphTextItem() : form.addTextItem();
    }
    item.setTitle(q.t).setRequired(!!q.req);
    if (q.help) item.setHelpText(q.help);
  });

  form.addCheckboxItem()
      .setTitle('決まりの確認')
      .setChoiceValues(['上の「このコーナーの決まり」を確認し、同意します'])
      .setRequired(true);

  form.addParagraphTextItem()
      .setTitle('写真・そのほか')
      .setHelpText('写真は、このあと届く受付メールに添付して返信してください（外観・お部屋など最大9枚）。'
                 + '\n掲載の希望日やご要望があればこちらへ。')
      .setRequired(false);

  props.setProperty('BUKKEN_FORM_ID', form.getId());
  ScriptApp.newTrigger('onBukkenFormSubmit').forForm(form).onFormSubmit().create();
  Logger.log('できました。\n公開URL: ' + form.getPublishedUrl() + '\n編集URL: ' + form.getEditUrl());
}

function ensureSheet(ss) {
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {   // 勝手に作らない。タブが無い＝参照先が間違っている
    throw new Error(SHEET_NAME + ' タブが見つかりません。SPREADSHEET_ID が「さくっと物件紹介キュー」を指しているか確認: ' + SPREADSHEET_ID);
  }
  var head = sh.getRange(1, 1, 1, Math.max(sh.getLastColumn(), 1)).getValues()[0];
  COLS.forEach(function (c) {
    if (head.indexOf(c) === -1) throw new Error('列「' + c + '」がキューにありません（列名を変えていませんか）');
  });
  return sh;
}

// ───────────────────────────── 送信されたとき ─────────────────────────────

var MAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
function normMail(v) {
  return String(v || '').normalize('NFKC').replace(/[\s　]/g, '').replace(/＠/g, '@').replace(/。/g, '.').toLowerCase();
}

/** 「愛知県豊川市諏訪3丁目」→「諏訪」（豊川市は町名だけ・市外は市から残す・番地は落とす） */
function townOf(addr) {
  var s = String(addr || '').normalize('NFKC').replace(/[\s　]/g, '').replace(/^愛知県/, '');
  s = s.replace(/[0-9].*$/, '').replace(/[一二三四五六七八九十]+丁目.*$/, '');
  return s.replace(/^豊川市/, '');
}

function onBukkenFormSubmit(e) {
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
  var id = nextBkId(sh, head);
  var name = ans['物件名'] || '';
  var role = ans['あなたのお立場'] || '';
  var to = normMail(ans['メールアドレス'] || '');
  var mailNg = !MAIL_RE.test(to);
  var today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy年M月d日');

  // 募集情報の枠（不動産広告で必要な項目をここに集める。足りない項目は完成イメージの確認のときに聞く）
  var torihiki = role.indexOf('大家') === 0 ? '貸主' : (role === '仲介会社' ? '媒介' : '（要確認）');
  var bosyu = ['広告主：' + (ans['会社名・お名前（広告主として記事に載せます）'] || ''),
               '取引態様：' + torihiki,
               '所在地：' + (ans['所在地（町名まで）'] || '')];
  if (ans['完成した年（築年月）']) bosyu.push('築年月：' + ans['完成した年（築年月）']);
  if (ans['募集情報（載せたい方だけ）']) bosyu.push(ans['募集情報（載せたい方だけ）']);
  bosyu.push('情報の時点：' + today);

  put('ID', id);
  put('状態', '申込');
  put('種別', '依頼掲載');
  put('物件名', name);
  put('町名', townOf(ans['所在地（町名まで）']));
  put('ほめ1本文', ans['ほめてほしいところ①'] || '');
  put('ほめ2本文', ans['ほめてほしいところ②'] || '');
  put('ほめ3本文', ans['ほめてほしいところ③'] || '');
  put('構造・階数', ans['構造・階数'] || '');
  put('完成年', ans['完成した年（築年月）'] || '');
  put('募集情報', bosyu.join('\n'));
  put('問い合わせ', ans['お問い合わせ先（記事に載せます）'] || '');
  put('依頼者から', ans['読者へのひとこと'] || '');
  put('備考', (mailNg ? '⚠メールアドレス不正（届かない可能性）：' + (ans['メールアドレス'] || '') + '\n' : '')
            + '立場：' + role + (ans['写真・そのほか'] ? '\n' + ans['写真・そのほか'] : ''));
  put('申込者名', ans['ご担当者のお名前'] || '');
  put('メールアドレス', to);
  put('受付日時', Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm'));
  sh.appendRow(row);

  if (to && !mailNg) {
    sendToApplicant_({
      to: to,
      subject: '【' + SITE_NAME + '】' + SERIES + ' お申し込みを受け付けました（' + id + '）',
      body: [
        (ans['ご担当者のお名前'] || 'ご担当者') + ' 様',
        '',
        SITE_NAME + ' 管理人です。「' + SERIES + '」へのお申し込みありがとうございます。',
        '受付番号：' + id,
        '',
        '━━━━━━━━━━━━━━━━━━',
        '【写真をお送りください】',
        'このメールに写真を添付して、そのまま返信してください（外観・お部屋など最大9枚）',
        '・人、車のナンバー、表札、洗濯物が写っていない写真をお願いします',
        '━━━━━━━━━━━━━━━━━━',
        '',
        'これから記事の下書きと画像を作り、完成イメージをこのメールアドレスへお送りします（通常数日以内）。',
        '※管理人からのご連絡・作業は、基本的に夜の時間帯となります。',
        '　ご返信が遅い時間や翌日以降になる場合がありますが、必ずお返事いたします。',
        '内容をご確認いただいてから公開しますので、まだ公開はされていません。',
        '',
        '───────────────',
        '■ お申し込み内容',
        '物件名：' + name,
        '所在地：' + (ans['所在地（町名まで）'] || ''),
        'お立場：' + role,
        '広告主として載せるお名前：' + (ans['会社名・お名前（広告主として記事に載せます）'] || ''),
        '',
        'ほめてほしいところ①：' + (ans['ほめてほしいところ①'] || ''),
        'ほめてほしいところ②：' + (ans['ほめてほしいところ②'] || ''),
        'ほめてほしいところ③：' + (ans['ほめてほしいところ③'] || ''),
        '',
        '構造・階数：' + (ans['構造・階数'] || ''),
        '完成した年：' + (ans['完成した年（築年月）'] || ''),
        '募集情報：',
        (ans['募集情報（載せたい方だけ）'] || '（なし＝建物の紹介だけ）'),
        '',
        'お問い合わせ先：' + (ans['お問い合わせ先（記事に載せます）'] || ''),
        '読者へのひとこと：' + (ans['読者へのひとこと'] || ''),
        '───────────────',
        '',
        POLICY,
        '',
        SITE_NAME + ' 管理人'
      ].join('\n')
    });
  }

  MailApp.sendEmail(OWNER_MAIL,
    '【申込】' + SERIES + ' ' + id + '：' + (mailNg ? '⚠メール不達の可能性 ' : '') + name,
    [SERIES + 'の申し込みが入りました。',
     '',
     '受付番号：' + id,
     '物件：' + name + '（' + (ans['所在地（町名まで）'] || '') + '）',
     '立場：' + role + ' / ' + (ans['会社名・お名前（広告主として記事に載せます）'] || ''),
     '担当者：' + (ans['ご担当者のお名前'] || '') + ' / ' + to,
     '',
     '物件紹介キューの一番下に「状態=申込」で入っています。',
     '完成イメージは自動では送られません。Claude に「物件紹介の申込きた」と伝えてください。'
    ].join('\n'));
}

function nextBkId(sh, head) {
  var i = head.indexOf('ID');
  if (i < 0) throw new Error('ID 列がありません');
  var max = 0;
  if (sh.getLastRow() >= 2) {
    sh.getRange(2, i + 1, sh.getLastRow() - 1, 1).getValues().forEach(function (v) {
      var m = String(v[0] || '').match(/^BK(\d+)$/);
      if (m) max = Math.max(max, parseInt(m[1], 10));
    });
  }
  return 'BK' + ('00' + (max + 1)).slice(-3);
}

/** 申込者あてのメールを info@toyokawaguide.com 名義で送る。使えないときは通常送信に切り替える */
function sendToApplicant_(o) {
  try {
    GmailApp.sendEmail(o.to, o.subject, o.body, { from: PUBLIC_FROM, name: SITE_NAME });
  } catch (err) {
    console.warn('info@ 名義で送れなかったので通常送信に切り替え: ' + err);
    MailApp.sendEmail({ to: o.to, subject: o.subject, body: o.body, name: SITE_NAME });
  }
}
