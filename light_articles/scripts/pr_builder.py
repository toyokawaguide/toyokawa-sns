# -*- coding: utf-8 -*-
"""pr_builder.py — さくっとPR（広告記事）のタイトル・本文・SNSキャプション生成

ライト記事の content_builder と対になる広告専用ビルダー。
⚠️ ステマ規制（景品表示法）対応：タイトル・本文・全SNSキャプションに広告表記を必ず入れる。
"""
from __future__ import annotations
import re
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

def _flatten_catch(catch: str) -> str:
    """カード用の手動改行入りキャッチを1行にする（タイトル/X/Threads/IG共通・2026-09-15）。
    行末の句読点は二重にしない。【…】や：、助詞（を・に・の…）で終わる行の直後は句の途中なので「、」を入れない。"""
    catch = (catch or "").strip()
    if chr(10) not in catch:
        return catch
    out = ""
    for part in [l.strip().rstrip("、。") for l in catch.splitlines() if l.strip()]:
        joiner = "" if (not out or out.endswith(("】", "：", ":", "を", "に", "が", "の", "と", "で", "へ", "は", "も", "や", "から"))) else "、"
        out += joiner + part
    return out


def _catch_head(catch: str) -> str:
    """空行で区切ったキャッチの前半だけ（例:【主演】寺島しのぶ・常盤貴子）。空行が無ければ全体"""
    c = (catch or "").strip()
    if chr(10) + chr(10) in c:
        c = c.split(chr(10) + chr(10))[0]
    return _flatten_catch(c)

def _when_short(when: str) -> str:
    """日時から（…）の補足を外す（X の字数対策）"""
    return re.sub("[（(][^）)]{4,}[）)]", "", when or "").strip()   # （日）のような短い補足は残す


def _extra_tags(row: dict) -> str:
    """備考の「タグ：#映画 #〇〇」行 → そのまま。無ければ イベント系は「#ジャンル」、お店は「#豊川グルメ」（従来）（2026-09-15 社長指摘）"""
    biko = (row.get("備考", "") or "")
    for mark in ("タグ：", "タグ:"):          # ★ 備考は1行に圧縮されるので行頭限定にしない（2026-09-21 PR009）
        i = biko.find(mark)
        if i < 0:
            continue
        v = biko[i + len(mark):]
        for stop in ("／", chr(10), chr(13)):     # 「／」か改行まで
            j = v.find(stop)
            if j >= 0:
                v = v[:j]
        return " ".join(t if t.startswith("#") else "#" + t for t in v.split())
    genre = (row.get("ジャンル", "") or "").strip()
    if _is_event(row.get("店名", "")):
        return ("#" + genre) if genre else ""
    return "#豊川グルメ"


def build_pr_title(row: dict) -> str:
    shop = row.get("店名", "").strip()
    catch = _flatten_catch(row.get("ひとことキャッチ", ""))
    if catch:
        return f"【PR】{shop}｜{catch}"
    return f"【PR】{shop}のご紹介"


def _links_of(row: dict) -> list:
    """リンク欄（改行/空白区切りで複数可）→ [(ラベル, URL)]。YouTubeは「▶ 予告編」、最初の通常URLは「🔗 公式サイト」（2026-09-15）"""
    urls = [u for u in re.split("[" + chr(10) + chr(13) + " 　]+", (row.get("リンク", "") or "").strip()) if u.startswith("http")]
    out, first = [], True
    for u in urls:
        if "youtube.com" in u or "youtu.be" in u:
            out.append(("▶ 予告編", u))
        elif "instagram.com" in u:
            out.append(("📷 Instagram", u))          # ★ 2026-09-21 SNSのURLはそれと分かるラベルに（PR009）
        elif "twitter.com" in u or "://x.com" in u:
            out.append(("𝕏 X", u))
        elif "facebook.com" in u:
            out.append(("📘 Facebook", u))
        elif "lin.ee" in u or "line.me" in u:
            out.append(("💬 LINE", u))
        else:
            out.append(("🔗 公式サイト" if first else "🔗 詳細ページ", u)); first = False   # ★2026-09-22 2本目はキャンペーン等の詳細ページが多い（PR009）
    return out

def _youtube_url(row: dict) -> str:
    for label, u in _links_of(row):
        if label.startswith("▶"):
            return u
    return ""


def _info_table(row: dict) -> str:
    """店舗情報テーブル（空欄の行は出さない）"""
    items = [
        ("📍 場所", row.get("エリア・住所", "")),
        ("📅 日時" if _is_event(row.get("店名", "")) else "🕐 営業時間", row.get("営業時間", "")),
        ("", "") if _is_event(row.get("店名", "")) else ("📅 定休日", row.get("定休日", "")),
    ] + _links_of(row)
    rows_html = []
    for label, val in items:
        val = (val or "").strip()
        if not val:
            continue
        if label.startswith(("🔗", "▶")) and val.startswith("http"):
            val = f'<a href="{val}" target="_blank" rel="noopener nofollow sponsored">{val}</a>'
        rows_html.append(
            f'<tr><th style="width:9em;text-align:left;padding:8px 12px;background:#f5efe0;">{label}</th>'
            f'<td style="padding:8px 12px;">{val}</td></tr>'
        )
    if not rows_html:
        return ""
    return ('<figure class="wp-block-table"><table style="border-collapse:collapse;width:100%;">'
            + "".join(rows_html) + "</table></figure>")


_EVENT_WORDS = ("上映会", "講演会", "イベント", "フェス", "祭り", "まつり", "コンサート", "発表会", "展示会", "作品展", "個展", "説明会", "体験会", "ワークショップ", "マルシェ")

def _is_event(shop: str) -> bool:
    """店名欄が「〇〇上映会」「〇〇フェス」のようなイベント名なら True（2026-09-15）"""
    s = (shop or "").strip()
    return any(s.endswith(w) or s.endswith(w + "！") for w in _EVENT_WORDS)


def _event_when(row: dict) -> str:
    """イベント系は「営業時間」欄を日時として使う（2026-09-15）"""
    return (row.get("営業時間", "") or "").strip() if _is_event(row.get("店名", "")) else ""

def _venue_short(row: dict) -> str:
    """住所の（…）内＝会場名。無ければ住所そのもの"""
    addr = (row.get("エリア・住所", "") or "").strip()
    m = re.search("[（(]([^）)]+)[）)]" + chr(92) + "s*$", addr)
    return m.group(1) if m else addr

def _credit_line(row: dict) -> str:
    """法定表示(W列)に「©」を含む行があればSNSにも出す（例: 掲載画像 ©現代ぷろだくしょん）"""
    for l in (row.get("法定表示", "") or "").splitlines():
        if "©" in l or "(c)" in l.lower():
            return l.strip()
    return ""


def _caveat(row: dict) -> tuple:
    """備考の「注意書き：〜」→ (SNS用の本文, X用の短い形)
    特典や支援額だけを大きく書いて条件を書かないと、実際より有利に見えてしまう。
    X は280制限があるので、入らないときは「※ 適用条件あり」だけに落とす（2026-09-21 社長）
    """
    biko = (row.get("備考", "") or "")
    for mark in ("注意書き：", "注意書き:"):
        i = biko.find(mark)
        if i < 0:
            continue
        v = biko[i + len(mark):]
        for stop in ("／", chr(10), chr(13)):
            j = v.find(stop)
            if j >= 0:
                v = v[:j]
        v = v.strip()
        if v:
            # 「長い説明｜Xに入れる短い説明」と書けば、Xでは後半を使う
            if "｜" in v:
                lo, sh = v.split("｜", 1)
                return ("※ " + lo.strip(), "※ " + sh.strip())
            return ("※ " + v, "※ 適用条件あり")
    return ("", "")


def _contact(row: dict, medium: str = "") -> str:
    """備考の「問い合わせ：〜」→ 各SNSの締めに出す誘導文（2026-09-21）
    申込者が「DMで」「プロフィールのリンクから」と書いてきても、投稿するのは豊川ガイドの
    アカウントなので、読者は豊川ガイド側を見てしまう。先方のアカウントを明記して逃がす。
    """
    biko = (row.get("備考", "") or "")
    marks = ("問い合わせ：", "問い合わせ:", "お問い合わせ：", "お問い合わせ:")
    if medium == "ig":   # ★2026-09-22 IGはURLが押せないので別の案内（DM等）を備考「問い合わせIG：」で指定できる（PR009）
        marks = ("問い合わせIG：", "問い合わせIG:") + marks
    for mark in marks:
        i = biko.find(mark)
        if i < 0:
            continue
        v = biko[i + len(mark):]
        for stop in ("／", chr(10), chr(13)):
            j = v.find(stop)
            if j >= 0:
                v = v[:j]
        v = v.strip()
        if v:
            return "📩 " + v
    return ""


ARTICLE_ONLY_MARK = "[記事のみ]"

def _memo_lines_for_sns(memo: str) -> list:
    """紹介文メモのうちSNSに載せる行。[記事のみ] で始まる行から次の「◆」見出しの手前までは除く
    （2026-09-22 PR009：条件の詳細は記事だけに残し、SNSは短い注記だけにしたい先方要望）"""
    out, skipping = [], False
    for l in (memo or '').splitlines():
        t = l.strip()
        if not t:
            continue
        if t.startswith(ARTICLE_ONLY_MARK):
            skipping = True
            continue
        if skipping and t.startswith('◆'):
            skipping = False
        if not skipping:
            out.append(t)
    return out

def build_pr_content(row: dict, photo_urls: list[str] | None = None) -> str:
    shop = row.get("店名", "").strip()
    catch = row.get("ひとことキャッチ", "").strip()
    genre = row.get("ジャンル", "").strip()
    memo = (row.get("紹介文メモ", "") or "").replace(ARTICLE_ONLY_MARK, "").strip()
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
    # ★2026-09-15 イベント系（上映会/講演会/展/フェス等）は「〇〇さん」「映画の映画…」にならない言い回しにする（PR005 上映会）
    if _is_event(shop):
        lead = f"豊川ガイドの広告コーナー「さくっとPR」。今回は<strong>{shop}</strong>のご案内です！"
    else:
        lead = f"豊川ガイドの広告コーナー「さくっとPR」。今回は{('、' + genre + 'の' if genre else '、')}<strong>{shop}</strong>さんをご紹介します！"
    parts.append(f"<p>{lead}</p>")
    if catch:
        _h2 = _flatten_catch(catch)   # ★2026-09-16 手動改行はカード画像専用。本文の見出しはタイトルと同じ1行にする（PR005 社長指摘）
        parts.append(f"<h2>{_h2}</h2>")

    # ③ 紹介文（社長・お店からのメモをそのまま整形）
    if memo:
        for para in memo.split("\n"):
            para = para.strip()
            if para:
                parts.append(f"<p>{para}</p>")

    # ③b 予告編（リンク欄にYouTubeがあれば本文に埋め込む・2026-09-15）
    yt = _youtube_url(row)
    if yt:
        parts.append("<p><strong>▶ 予告編</strong></p>")
        parts.append(
            '<!-- wp:embed {"url":"' + yt + '","type":"video","providerNameSlug":"youtube","responsive":true,'
            '"className":"wp-embed-aspect-16-9 wp-has-aspect-ratio"} -->'
            '<figure class="wp-block-embed is-type-video is-provider-youtube wp-block-embed-youtube '
            'wp-embed-aspect-16-9 wp-has-aspect-ratio"><div class="wp-block-embed__wrapper">' + chr(10) + yt + chr(10) + '</div></figure>'
            '<!-- /wp:embed -->'
        )   # Gutenbergの埋め込みブロック（他の要素と同じブロック形式・表示時にYouTubeプレーヤーになる）

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
        parts.append(f"<p>💬 {'主催者から' if _is_event(shop) else 'お店から'}：{tsubuyaki}</p>")

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
        "内容は掲載時点の情報です。最新の営業時間・価格・サービス内容は" + ("主催者" if _is_event(shop) else "各店舗") + "にご確認ください。</small></p>"
    )
    parts.append(
        "<p><small>「さくっとPR」は豊川ガイドの広告枠です。"
        "お店やサービスの宣伝をご希望の方は、豊川ガイドのSNSのDMからお気軽にご相談ください。</small></p>"
    )
    return "\n".join(parts)


def build_pr_x_caption(row: dict, wp_url: str) -> str:
    """X投稿文（2026-09-01 社長確定形式）
    タイトル1行（キャッチの手動改行は除去）＋紹介文メモ＋つぶやき＋詳細＋タグ。
    280 weight 超過時は 紹介文メモの後ろの行→つぶやき→特典 の順で落とす。"""
    shop = row.get("店名", "").strip()
    catch = _flatten_catch(row.get("ひとことキャッチ", ""))
    tokuten = (row.get("特典・クーポン", "") or "").strip()
    memo_lines = _memo_lines_for_sns(row.get("紹介文メモ", ""))
    tweet = (row.get("つぶやき", "") or "").strip()
    title = f"【PR】{shop}" + (f"｜{catch}" if catch else "")

    when, venue, credit = _event_when(row), _venue_short(row), _credit_line(row)
    when_ref = [when]
    cav_full, cav_short = _caveat(row)   # ★ 条件の注記（2026-09-21 社長）
    cav_ref = [cav_full]
    contact = _contact(row)
    def assemble(memos, tw, tk, ttl=None):
        lines = [ttl or title, ""]
        if when:   # ★イベント系：日時と会場を最優先（2026-09-15 社長）
            lines += [f"📅 {when_ref[0]}", f"📍 {venue}", ""]
        body = list(memos) + ([tw] if tw else [])
        if body:
            lines += body + [""]
        if tk:
            lines += [f"🎁 {tk}", ""]
        if cav_ref[0]:
            lines += [cav_ref[0], ""]
        if contact and contact[2:] not in chr(10).join(lines):   # ★X はカードが「最後のURL」に付くので、問い合わせ先は記事URLより前に置く（2026-09-22 社長「記事に飛んでほしい」）
            lines += [contact, ""]
        lines += ["▼ 詳細", wp_url, ""]
        if credit:
            lines += [f"📷 {credit}"]
        lines += [_hashtags(row)]
        return chr(10).join(lines)

    memos = [] if when else list(memo_lines)   # イベントは日時/会場で言い切る（メモは記事で）
    full = assemble(memos, tweet, tokuten)
    while _x_weight(full) > 280 and memos:
        memos.pop()
        full = assemble(memos, tweet, tokuten)
    if _x_weight(full) > 280 and tweet:
        full = assemble(memos, "", tokuten)
    if _x_weight(full) > 280 and tokuten:
        full = assemble(memos, "", "")
    if _x_weight(full) > 280 and when:   # ★イベント系：日時の（…）を外す → キャッチを前半だけに → それでも超えたら店名だけ
        when_ref[0] = _when_short(when)
        full = assemble(memos, "", "")
    if _x_weight(full) > 280 and when and catch:
        head = _catch_head(row.get("ひとことキャッチ", ""))
        full = assemble(memos, "", "", ttl=f"【PR】{shop}｜{head}")
    if _x_weight(full) > 280 and when and catch:
        full = assemble(memos, "", "", ttl=f"【PR】{shop}")
    if _x_weight(full) > 280 and cav_ref[0] and cav_short:
        cav_ref[0] = cav_short          # ★ 注記は消さずに短くする
        full = assemble(memos, "", "")
    return full


def build_pr_threads_caption(row: dict, wp_url: str) -> str:
    shop = row.get("店名", "").strip()
    catch = _flatten_catch(row.get("ひとことキャッチ", ""))
    genre = row.get("ジャンル", "").strip()
    tokuten = (row.get("特典・クーポン", "") or "").strip()
    lines = [f"【PR】{shop}" + (f"｜{catch}" if catch else ""), ""]
    when, venue, credit = _event_when(row), _venue_short(row), _credit_line(row)
    note = (row.get("豊川ガイドから一言", "") or "").strip()
    if genre:
        lines += [f"豊川ガイドの広告コーナー「さくっとPR」。" + (f"{shop}のご案内です！" if _is_event(shop) else f"{genre}の{shop}さんの紹介です！"), ""]
    if when:
        lines += [f"📅 {when}", f"📍 {venue}", ""]
    if tokuten:
        lines += [f"🎁 {tokuten}", ""]
    cav, _ = _caveat(row)
    if cav:
        lines += [cav, ""]
    lines += ["▼ 詳細", wp_url, ""]
    contact = _contact(row)
    if contact and contact[2:] not in chr(10).join(lines):
        lines += [contact, ""]
    if note:
        lines += [f"💬 豊川ガイドから：{note}", ""]
    if credit:
        lines += [f"📷 {credit}", ""]
    lines += [(_hashtags(row) + " " + _extra_tags(row)).strip()]
    return "\n".join(lines)


def build_pr_instagram_caption(row: dict, wp_url: str) -> str:
    shop = row.get("店名", "").strip()
    catch = _flatten_catch(row.get("ひとことキャッチ", ""))
    genre = row.get("ジャンル", "").strip()
    addr = (row.get("エリア・住所", "") or "").strip()
    tokuten = (row.get("特典・クーポン", "") or "").strip()
    lines = [f"【PR】{shop}" + (f"｜{catch}" if catch else ""), ""]
    when, venue, credit = _event_when(row), _venue_short(row), _credit_line(row)
    note = (row.get("豊川ガイドから一言", "") or "").strip()
    memo_lines = _memo_lines_for_sns(row.get("紹介文メモ", ""))   # ★[記事のみ]区間は載せない
    if genre:
        lines += [f"豊川ガイドの広告コーナー「さくっとPR」。" + (f"{shop}のご案内です！" if _is_event(shop) else f"{genre}の{shop}さんの紹介です！"), ""]
    if when and not any("日時" in l for l in memo_lines):
        lines += [f"📅 {when}", ""]
    if memo_lines:   # ★IGは字数に余裕があるので紹介文メモを全部載せる（2026-09-15 社長「なるべく情報を」）
        lines += memo_lines + [""]
    if tokuten:
        lines += [f"🎁 {tokuten}", ""]
    if addr:
        lines += [f"📍 {addr}", ""]
    if note:
        lines += [f"💬 豊川ガイドから：{note}", ""]
    if credit:
        lines += [f"📷 {credit}", ""]
    cav, _ = _caveat(row)
    if cav:
        lines += [cav, ""]
    contact = _contact(row, medium="ig")
    if contact and contact[2:] not in chr(10).join(lines):
        lines += [contact, ""]
    lines += [
        "▼ この記事の全文は",
        "豊川ガイド @toyokawaguide の",
        "プロフィールのリンクから",
        "",
        "📣 さくっとPRへの掲載をご希望の方は",
        "豊川ガイド @toyokawaguide のDMへ",
        "",
        _hashtags(row) + " #広告 " + _extra_tags(row) + " #地域メディア",
    ]
    return "\n".join(lines)
