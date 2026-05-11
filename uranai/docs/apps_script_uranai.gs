/**
 * 豊川ガイド 占い配信用 Google Sheets API（Webhook）
 * ============================================================
 *
 * 【セットアップ手順】
 * 1. Google Sheet を新規作成（または既存）
 * 2. メニュー「拡張機能」→「Apps Script」
 * 3. 自動生成された Code.gs を**全消去**して、このコード全体を貼り付け
 * 4. SECRET_KEY を任意の文字列に変更（後で GitHub Secrets に登録）
 * 5. 上の「保存」（フロッピーアイコン）→「デプロイ」→「新しいデプロイ」
 *    - 種類：ウェブアプリ
 *    - 説明：占い配信API
 *    - 次のユーザーとして実行：自分
 *    - アクセスできるユーザー：全員
 *    - 「デプロイ」クリック
 * 6. 表示される「ウェブアプリの URL」をコピー
 *    → GitHub Secrets `URANAI_SHEETS_URL` に登録
 *    → GitHub Secrets `URANAI_SHEETS_SECRET` に SECRET_KEY と同じ値を登録
 *
 * 【テスト】
 *   curl "https://script.google.com/macros/s/XXX/exec?sheet=ラッキースポット入力&secret=YOUR_SECRET"
 *   → {"values": [[...], [...], ...]} が返れば成功
 */

const SECRET_KEY = "CHANGE_ME_TO_RANDOM_STRING_xY9z2Q";  // ← ここを変更（任意の長い文字列）

function doGet(e) {
  const secret = (e.parameter.secret || "").trim();
  if (secret !== SECRET_KEY) {
    return jsonResponse({error: "unauthorized"});
  }

  const sheetName = (e.parameter.sheet || "").trim();
  if (!sheetName) {
    return jsonResponse({error: "sheet parameter required"});
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ws = ss.getSheetByName(sheetName);
  if (!ws) {
    return jsonResponse({
      error: "sheet not found: " + sheetName,
      available: ss.getSheets().map(s => s.getName()),
    });
  }

  const data = ws.getDataRange().getValues();
  // Date オブジェクトを ISO 文字列に変換（JSON 化）
  const normalized = data.map(row =>
    row.map(cell => {
      if (cell instanceof Date) {
        return Utilities.formatDate(cell, "Asia/Tokyo", "yyyy-MM-dd");
      }
      return cell;
    })
  );

  return jsonResponse({sheet: sheetName, rows: normalized.length, values: normalized});
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
