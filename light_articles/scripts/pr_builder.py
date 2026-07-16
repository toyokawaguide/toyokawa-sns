# -*- coding: utf-8 -*-
"""pr_builder.py — さくっとPR（広告記事）のタイトル・本文・SNSキャプション生成

ライト記事の content_builder と対になる広告専用ビルダー。
⚠️ ステマ規制（景品表示法）対応：タイトル・本文・全SNSキャプションに広告表記を必ず入れる。
"""
from __future__ import annotations
import unicodedata

HASHTAGS_BASE = "#PR #豊川市 #豊川ガイド #とよサポ #さくっとPR"


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

    # ④ 写真
    if photo_urls:
        for u in photo_urls:
            parts.append(
                f'<figure class="wp-block-image size-large"><img src="{u}" alt="{shop}"/></figure>'
            )

    # ⑤ 店舗情報
    table = _info_table(row)
    if table:
        parts.append("<h2>お店の情報</h2>")
        parts.append(table)

    # ⑥ 特典
    if tokuten:
        parts.append(
            '<div style="border:2px dashed #c09a3e;border-radius:8px;padding:12px 16px;'
            'background:#fffbe8;margin:1.2em 0;">'
            f'<strong>🎁 特典：</strong>{tokuten}</div>'
        )

    # ⑦ 管理人のつぶやき（任意）
    if tsubuyaki:
        parts.append(f"<p>💬 管理人ひとこと：{tsubuyaki}</p>")

    # ⑧ closing（募集導線）
    parts.append("<hr/>")
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
    lines += ["▼ 詳細", wp_url, "", HASHTAGS_BASE]
    full = "\n".join(lines)
    if _x_weight(full) > 280 and tokuten:
        lines = [title, "", "▼ 詳細", wp_url, "", HASHTAGS_BASE]
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
    lines += ["▼ 詳細", wp_url, "", HASHTAGS_BASE]
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
        HASHTAGS_BASE + " #広告 #豊川グルメ #地域メディア",
    ]
    return "\n".join(lines)
