# -*- coding: utf-8 -*-
"""pr_builder.py — さくっとPR（広告記事）のタイトル・本文・SNSキャプション生成

ライト記事の content_builder と対になる広告専用ビルダー。
⚠️ ステマ規制（景品表示法）対応：タイトル・本文・全SNSキャプションに広告表記を必ず入れる。
"""
from __future__ import annotations
import unicodedata

HASHTAGS_BASE = "#PR #豊川市 #豊川ガイド #とよサポ #さくっとPR"
HASHTAGS_OUTSIDE = "#PR #豊川ガイド #さくっとPR"


def _hashtags(row: dict) -> str:
    """#とよサポ（とよかわ応援サポーター）と #豊川市 は住所が豊川市のときだけ。
    市外の申込に付けると制度趣旨とズレるため（2026-08-05 社長方針）"""
    addr = (row.get("エリア・住所", "") or "")
    return HASHTAGS_BASE if "豊川市" in addr else HASHTAGS_OUTSIDE


def _x_weight(text: str) -> int:
    """X の文字数weight（CJK=2, 半角=1, URL=23固定）"""
    import re
    t = re.sub(r"https?://\S+", "x" * 23, text)
    return sum(1 if unicodedata.east_asian_width(c) in ("Na", "H", "N") else 2 for c in t)


def build_pr_title(row: dict) -> str:
    shop = row.get("店名", "").strip()
    catch = row.get("ひとことキャッチ", "").strip()
    if catch:
        return f"【PR】{shop}｜{catch}"
    return f"【PR】{shop}のご紹介"


def _info_table(row: dict) -> str:
    """店舗情報テーブル（空欄の行は出さない）"""
    items = [
        ("📍 場所", row.get("エリア・住所", "")),
        ("🕐 営業時間", row.get("営業時間", "")),
        ("📅 定休日", row.get("定休日", "")),
        ("🔗 リンク", row.get("リンク", "")),
    ]
    rows_html = []
    for label, val in items:
        val = (val or "").strip()
        if not val:
            continue
        if label.startswith("🔗") and val.startswith("http"):
            val = f'<a href="{val}" target="_blank" rel="noopener nofollow sponsored">{val}</a>'
        rows_html.append(
            f'<tr><th style="width:9em;text-align:left;padding:8px 12px;background:#f5efe0;">{label}</th>'
            f'<td style="padding:8px 12px;">{val}</td></tr>'
        )
    if not rows_html:
        return ""
    return ('<figure class="wp-block-table"><table style="border-collapse:collapse;width:100%;">'
            + "".join(rows_html) + "</table></figure>")


def build_pr_content(row: dict, photo_urls: list[str] | None = None) -> str:
    shop = row.get("店名", "").strip()
    catch = row.get("ひとことキャッチ", "").strip()
    genre = row.get("ジャンル", "").strip()
    memo = (row.get("紹介文メモ", "") or "").strip()
    tokuten = (row.get("特典・クーポン", "") or "").strip()
    tsubuyaki = (row.get("つぶやき", "") or "").strip()

    parts: list[str] = []

    # ① 広告開示（ステマ規制対応・冒頭固定）
    parts.append(
        '<div style="border:2px solid #1a3a8a;border-radius:8px;padding:10px 16px;'
        'background:#f0f4ff;font-size:0.9em;margin-bottom:1.5em;">'
        '<strong>【広告】</strong>この記事は「さくっとPR」＝お店・事業者さまからのご依頼による広告記事です。'
        '</div>'
    )

    # ② リード
    lead = f"豊川ガイドの広告コーナー「さくっとPR」。今回は{('、' + genre + 'の' if genre else '、')}<strong>{shop}</strong>さんをご紹介します！"
    parts.append(f"<p>{lead}</p>")
    if catch:
        parts.append(f"<h2>{catch}</h2>")

    # ③ 紹介文（社長・お店からのメモをそのまま整形）
    if memo:
        for para in memo.split("\n"):
            para = para.strip()
            if para:
                parts.append(f"<p>{para}</p>")

    # ④ 写真（連続で詰まらないよう1枚ごとに下マージン・2026-08-06社長指摘）
    if photo_urls:
        for u in photo_urls:
            parts.append(
                f'<figure class="wp-block-image size-large" style="margin:0 0 2em;">'
                f'<img src="{u}" alt="{shop}"/></figure>'
            )
        # 写真の出所を明示（提供許諾があることの表明・2026-08-19 PR002を機に全記事標準化）
        parts.append(
            '<p style="font-size:0.85em;color:#666;">'
            '※掲載写真はご依頼者さまより提供いただいたものです。無断転載はご遠慮ください。</p>'
        )

    # ⑤ 基本情報（お店以外＝サークル・イベント等でも自然な見出しに・2026-08-05）
    #    空欄の項目は行ごと出ない。全部空なら表も見出しも出ない
    table = _info_table(row)
    if table:
        parts.append("<h2>基本情報</h2>")
        parts.append(table)

    # ⑥ 特典
    if tokuten:
        parts.append(
            '<div style="border:2px dashed #c09a3e;border-radius:8px;padding:12px 16px;'
            'background:#fffbe8;margin:1.2em 0;">'
            f'<strong>🎁 特典：</strong>{tokuten}</div>'
        )

    # ⑦ お店からのひとこと（任意）
    #    ※申込フォームで集めるのは「店主さんの言葉」なので、管理人の言葉として出さない。
    #      広告記事で媒体が推薦しているように読めると、ステマ規制の観点で問題になる（社長判断 2026-08-02）
    if tsubuyaki:
        parts.append(f"<p>💬 お店から：{tsubuyaki}</p>")

    # ⑦b 豊川ガイドから一言（任意・シートT列に書いた時だけ・2026-08-05社長発案）
    #     広告記事内の媒体コメントなので、体験・事実ベースの言い回し推奨（過度な絶賛は優良誤認リスク）
    guide_note = (row.get("豊川ガイドから一言", "") or "").strip()
    if guide_note:
        parts.append(
            '<div style="border-left:4px solid #1a3a8a;background:#f0f4ff;'
            'border-radius:0 8px 8px 0;padding:10px 16px;margin:1.2em 0;">'
            f'<strong>🦊 豊川ガイドから：</strong>{guide_note}</div>'
        )

    # ⑦c 法定表示（任意・シート「法定表示」列に書いた時だけ・2026-08-19 PR003動物取扱業を機に新設）
    #     1行目=見出し・2行目以降=表示項目。動物取扱業の標識など、広告に表示義務がある情報をそのまま載せる
    houtei = (row.get("法定表示", "") or "").strip()
    if houtei:
        h_lines = [ln.strip() for ln in houtei.split("\n") if ln.strip()]
        if h_lines:
            body_lines = "<br/>".join(h_lines[1:])
            parts.append(
                '<div style="border:1px solid #999;border-radius:8px;padding:12px 16px;'
                'background:#fafafa;font-size:0.85em;margin:1.2em 0;">'
                f'<strong>{h_lines[0]}</strong><br/>{body_lines}</div>'
            )

    # ⑧ closing（読者向けの注意書き＋募集導線）
    #    ※「事業者様」に限定しない表現＝「豊川ガイドのユーザー様」（社長確定 2026-08-05）
    parts.append("<hr/>")
    parts.append(
        "<p><small>※本記事は「さくっとPR」（豊川ガイドのユーザー様からのお申し込みによる掲載）です。"
        "内容は掲載時点の情報です。最新の営業時間・価格・サービス内容は各店舗にご確認ください。</small></p>"
    )
    parts.append(
        "<p><small>「さくっとPR」は豊川ガイドの広告枠です。"
        "お店やサービスの宣伝をご希望の方は、豊川ガイドのSNSのDMからお気軽にご相談ください。</small></p>"
    )
    return "\n".join(parts)


def build_pr_x_caption(row: dict, wp_url: str) -> str:
    shop = row.get("店名", "").strip()
    catch = row.get("ひとことキャッチ", "").strip()
    tokuten = (row.get("特典・クーポン", "") or "").strip()
    title = f"【PR】{shop}" + (f"｜{catch}" if catch else "")
    lines = [title, ""]
    if tokuten:
        lines += [f"🎁 {tokuten}", ""]
    lines += ["▼ 詳細", wp_url, "", _hashtags(row)]
    full = "\n".join(lines)
    if _x_weight(full) > 280 and tokuten:
        lines = [title, "", "▼ 詳細", wp_url, "", _hashtags(row)]
        full = "\n".join(lines)
    return full


def build_pr_threads_caption(row: dict, wp_url: str) -> str:
    shop = row.get("店名", "").strip()
    catch = row.get("ひとことキャッチ", "").strip()
    genre = row.get("ジャンル", "").strip()
    tokuten = (row.get("特典・クーポン", "") or "").strip()
    lines = [f"【PR】{shop}" + (f"｜{catch}" if catch else ""), ""]
    if genre:
        lines += [f"豊川ガイドの広告コーナー「さくっとPR」。{genre}の{shop}さんの紹介です！", ""]
    if tokuten:
        lines += [f"🎁 {tokuten}", ""]
    lines += ["▼ 詳細", wp_url, "", _hashtags(row)]
    return "\n".join(lines)


def build_pr_instagram_caption(row: dict, wp_url: str) -> str:
    shop = row.get("店名", "").strip()
    catch = row.get("ひとことキャッチ", "").strip()
    genre = row.get("ジャンル", "").strip()
    addr = (row.get("エリア・住所", "") or "").strip()
    tokuten = (row.get("特典・クーポン", "") or "").strip()
    lines = [f"【PR】{shop}" + (f"｜{catch}" if catch else ""), ""]
    if genre:
        lines += [f"豊川ガイドの広告コーナー「さくっとPR」。{genre}の{shop}さんの紹介です！", ""]
    if tokuten:
        lines += [f"🎁 {tokuten}", ""]
    if addr:
        lines += [f"📍 {addr}", ""]
    lines += [
        "▼ 詳細",
        "プロフィールのリンクから本文をどうぞ",
        "",
        "📣 お店の宣伝をご希望の方はDMへ",
        "",
        _hashtags(row) + " #広告 #豊川グルメ #地域メディア",
    ]
    return "\n".join(lines)
