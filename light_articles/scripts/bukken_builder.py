# -*- coding: utf-8 -*-
"""bukken_builder.py — さくっと物件紹介：タイトル・記事本文・X/Threads/IG の文面（2026-11-11）

「このコーナーは、良いことしか言いません。豊川ガイド、バリバリ忖度してます」と先に宣言して物件をほめるコーナー。
種別で2つに分かれる:
  勝手に紹介 … 依頼も報酬もなし。家賃・空室・問い合わせ先は出さない（建物の紹介だけ）
  依頼掲載   … 【PR】。冒頭に広告の表示、末尾に「募集情報」の枠と問い合わせ先

守る線（企画まとめ 3章）:
  ・嘘・大げさは書かない（事実＋感想でほめる。「最高」「日本一」「格安」などは使わない → find_ng_words で点検）
  ・豊川ガイドは仲介に入らない（内見の手配・条件交渉・申込の受付はしない）と記事に明記
  ・依頼掲載は無料でも広告の表示を外さない（ステマ規制は「依頼による表示か」で判断される）

キューの列: ID / 公開希望日 / 状態 / 種別 / 物件名 / 町名 / ひとことキャッチ /
            ほめ1見出し / ほめ1本文 / ほめ2見出し / ほめ2本文 / ほめ3見出し / ほめ3本文 / ひとこと /
            構造・階数 / 完成年 / 小学校区 / 中学校区 / 物件ページ / 募集情報 / 問い合わせ / 依頼者から /
            備考 / 申込者名 / メールアドレス / 受付日時
※WPのサニタイザ対策で style 属性は必ず1行で書く
"""
from __future__ import annotations
import re
import unicodedata

LABEL = "さくっと物件紹介"
ACCENT = "#7a5cc0"      # すみれ色（さくっとお知らせ=紺／さくっとPR=ゴールドと見分ける）
BG = "#f7f3fd"
NL = chr(10)

DECLARATION_1 = "このコーナーは、良いことしか言いません。"
DECLARATION_2 = "豊川ガイド、バリバリ忖度してます。"
DECLARATION_3 = "気になるところは、ご自身の目で確かめてください。"
NOTE_KATTE = "※この記事は、依頼も報酬も受けていない、管理人の勝手な紹介です。"
NOTE_IRAI = "※この記事は、大家さん・不動産会社さまからのご依頼による掲載（広告）です。"

# 不動産広告のきまり（表示規約）で、根拠なしに使えない言葉。見つけたら配信を止める
NG_WORDS = ("最高", "日本一", "日本初", "業界一", "抜群", "完璧", "完全", "絶対", "万全", "当社だけ",
            "格安", "破格", "激安", "掘り出し", "掘出", "特選", "厳選", "最高級", "超一流", "買得", "お買い得",
            "No.1", "ナンバーワン", "一番", "いちばん安", "最安", "最上級", "極上")
_NG_OK = ("いちばん近い", "一番近い")   # 距離の事実を言うだけの言い回しは通す


def _g(row: dict, key: str) -> str:
    return (row.get(key, "") or "").strip()


def is_ad(row: dict) -> bool:
    return _g(row, "種別") == "依頼掲載"


def points(row: dict) -> list:
    """[(見出し, 本文), ...]。見出しが空のものは出さない"""
    out = []
    for i in (1, 2, 3):
        h, b = _g(row, f"ほめ{i}見出し"), _g(row, f"ほめ{i}本文")
        if h:
            out.append((h, b))
    return out


def area(row: dict) -> str:
    """所在地の表示。町名に「市」が入っていればそのまま、無ければ豊川市を付ける"""
    t = _g(row, "町名")
    if not t:
        return ""
    return t if "市" in t else "豊川市" + t


def in_toyokawa(row: dict) -> bool:
    return area(row).startswith("豊川市")


def find_ng_words(row: dict) -> list:
    """ほめ言葉の中に、根拠なしでは使えない言葉が入っていないか。入っていた言葉のリストを返す"""
    text = " ".join(_g(row, k) for k in ("ひとことキャッチ", "ほめ1見出し", "ほめ1本文", "ほめ2見出し", "ほめ2本文",
                                           "ほめ3見出し", "ほめ3本文", "ひとこと", "依頼者から"))
    for ok in _NG_OK:
        text = text.replace(ok, "")
    return [w for w in NG_WORDS if w in text]


def build_title(row: dict) -> str:
    head = "【PR】" if is_ad(row) else ""
    town = _g(row, "町名")
    catch = _g(row, "ひとことキャッチ").replace(NL, "")
    return f"{head}【{LABEL}】{_g(row, '物件名')}" + (f"（{town}）" if town else "") + (f"｜{catch}" if catch else "")


def _table(pairs) -> str:
    rows = "".join(
        f'<tr><th style="width:32%;text-align:left;background:{BG};">{k}</th><td>{v}</td></tr>'
        for k, v in pairs if str(v).strip()
    )
    return f'<figure class="wp-block-table"><table><tbody>{rows}</tbody></table></figure>' if rows else ""


def _pairs(text: str) -> list:
    """「項目：値」を1行ずつ書いたセル → [(項目, 値), ...]"""
    out = []
    for ln in (text or "").split(NL):
        ln = ln.strip()
        if not ln:
            continue
        m = re.match(r"(.+?)[：:](.+)$", ln)
        out.append((m.group(1).strip(), m.group(2).strip()) if m else ("", ln))
    return out


def basic_pairs(row: dict) -> list:
    return [("所在地", area(row)), ("構造・階数", _g(row, "構造・階数")), ("完成年", _g(row, "完成年")),
            ("小学校区", _g(row, "小学校区")), ("中学校区", _g(row, "中学校区"))]


def build_content(row: dict, photo_urls=None) -> str:
    ad = is_ad(row)
    name = _g(row, "物件名")
    photos = list(photo_urls or [])
    p = []

    # ① 広告の表示（依頼掲載だけ・冒頭固定）
    if ad:
        p.append(
            '<div style="border:2px solid #1a3a8a;border-radius:8px;padding:10px 16px;background:#f0f4ff;font-size:0.9em;margin-bottom:1em;">'
            f'<strong>【広告】</strong>この記事は「{LABEL}」＝大家さん・不動産会社さまからのご依頼による広告記事です。</div>'
        )

    # ② 宣言ボックス（毎回同じ文）
    p.append(
        f'<div style="border:3px double {ACCENT};border-radius:10px;padding:14px 18px;background:{BG};margin-bottom:1.5em;">'
        f'<p style="margin:0 0 0.4em;font-weight:bold;font-size:1.1em;">📣 {DECLARATION_1}</p>'
        f'<p style="margin:0;">豊川ガイド、<strong>バリバリ忖度してます。</strong>{DECLARATION_3}</p>'
        f'<p style="margin:0.6em 0 0;font-size:0.85em;color:#555;">{NOTE_IRAI if ad else NOTE_KATTE}</p>'
        '</div>'
    )

    # ③ リード
    where = (_g(row, "町名") + "の") if _g(row, "町名") else ""
    p.append(f'<p>豊川ガイドの忖度コーナー「{LABEL}」。今回は、{where}<strong>{name}</strong>を、全力でほめます！</p>')

    # ④ ほめポイント（事実＋感想）。写真は 1番=ほめ1、2番=ほめ2、3番=ほめ3。4番以降はその後ろに並べる
    marks = "①②③"
    alt = name + (f"（{_g(row, '町名')}）" if _g(row, "町名") else "")
    fig = '<figure class="wp-block-image size-large" style="margin:0 0 1.2em;"><img src="{}" alt="{}"/></figure>'
    pts = points(row)
    for i, (head, body) in enumerate(pts):
        p.append(f"<h2>ほめポイント{marks[i]}　{head}</h2>")
        if i < len(photos):
            p.append(fig.format(photos[i], alt))
        for para in body.split(NL):
            if para.strip():
                p.append(f"<p>{para.strip()}</p>")
    for u in photos[len(pts):]:
        p.append(fig.format(u, alt))
    if photos:
        p.append(
            '<p style="font-size:0.85em;color:#666;">'
            + ("※掲載写真はご依頼者さまより提供いただいたものです。" if ad else "※写真は豊川ガイドが撮影したものです。")
            + "無断転載はご遠慮ください。</p>"
        )

    # ⑤ 管理人のひとこと（偏見）
    if _g(row, "ひとこと"):
        p.append(
            f'<div style="border-left:4px solid {ACCENT};background:{BG};border-radius:0 8px 8px 0;padding:10px 16px;margin:1.2em 0;">'
            f'<strong>🦊 管理人のひとこと（偏見）：</strong>{_g(row, "ひとこと")}</div>'
        )

    # ⑥ 基本データ
    table = _table(basic_pairs(row))
    if table:
        p.append("<h2>基本データ</h2>")
        p.append(table)
    if _g(row, "物件ページ"):
        p.append(f'<p>▶ 建物のくわしいデータ・地図は <a href="{_g(row, "物件ページ")}">{name}の物件ページ</a> へ</p>')

    # ⑦ 募集情報・問い合わせ（依頼掲載だけ）
    if ad:
        bosyu = _table(_pairs(_g(row, "募集情報")))
        if bosyu:
            p.append("<h2>募集情報</h2>")
            p.append(bosyu)
            p.append(
                '<p style="font-size:0.85em;color:#666;">※募集情報はご依頼者さまから提供いただいた、掲載時点の内容です。'
                "最新の状況は必ずご依頼者さまにご確認ください。お部屋が決まり次第「募集終了」と表示します。</p>"
            )
        if _g(row, "依頼者から"):
            p.append(f'<p>💬 ご依頼者さまから：{_g(row, "依頼者から")}</p>')
        if _g(row, "問い合わせ"):
            p.append(
                '<div style="border:2px dashed #c09a3e;border-radius:8px;padding:12px 16px;background:#fffbe8;margin:1.2em 0;">'
                f'<strong>📞 お問い合わせ先：</strong>{_g(row, "問い合わせ").replace(NL, "<br/>")}<br/>'
                '<span style="font-size:0.85em;">※豊川ガイドでは、内見の手配・条件のご相談・お申し込みの受付は行っていません。</span></div>'
            )

    # ⑧ しめ
    p.append("<hr/>")
    p.append("<p><strong>住んでみないと、分かりません。最後は、自分の目で。</strong></p>")
    p.append(
        f"<p><small>※「{LABEL}」は、建物の良いところだけを紹介するコーナーです。気になる点・最新の状況は、現地や"
        + ("ご依頼者さま" if ad else "管理会社さん")
        + "でご確認ください。内容は掲載時点の情報です。</small></p>"
    )
    p.append("<p><small>「うちの物件もほめてほしい」という大家さん・不動産会社さまは、豊川ガイドのSNSのDMからお気軽にどうぞ。</small></p>")
    return NL.join(p)


def hashtags(row: dict) -> str:
    """#とよサポ・#豊川市 は豊川市の物件だけ（さくっとPRと同じ方針）"""
    tags = (["#PR"] if is_ad(row) else []) + (["#豊川市", "#豊川ガイド", "#とよサポ"] if in_toyokawa(row) else ["#豊川ガイド"])
    return " ".join(tags + ["#" + LABEL])


def x_weight(text: str) -> int:
    """X の字数（全角=2・半角=1・URL=23固定）。pr_builder._x_weight と同じ数え方"""
    t = re.sub(r"https?://\S+", "x" * 23, text)
    return sum(1 if unicodedata.east_asian_width(c) in ("Na", "H", "N") else 2 for c in t)


def build_x_caption(row: dict, wp_url: str) -> str:
    """280に収まらないときは ほめポイントを後ろから落とす → キャッチを落とす"""
    heads = [h for h, _ in points(row)]
    name = _g(row, "物件名") + (f"（{_g(row, '町名')}）" if _g(row, "町名") else "")
    full_title, short_title = build_title(row), ("【PR】" if is_ad(row) else "") + f"【{LABEL}】{name}"

    def assemble(title, hs):
        lines = [title, ""]
        lines += [f"・{h}" for h in hs]
        lines += ([""] if hs else []) + ["※良いことしか言いません（忖度してます）", "", "▼ 詳細", wp_url, "", hashtags(row)]
        return NL.join(lines)

    for title in (full_title, short_title):
        for n in range(len(heads), -1, -1):
            text = assemble(title, heads[:n])
            if x_weight(text) <= 280:
                return text
    return assemble(short_title, [])


def build_threads_caption(row: dict, wp_url: str) -> str:
    marks = "①②③"
    lines = [build_title(row), "", f"📣 {DECLARATION_1}", f"{DECLARATION_2}", ""]
    if is_ad(row):
        lines += ["※ご依頼による掲載（広告）です", ""]
    lines += [f"{marks[i]} {h}" for i, (h, _) in enumerate(points(row))]
    lines += ["", "▼ くわしくは", wp_url, "", hashtags(row)]
    text = NL.join(lines)
    return text if len(text) <= 480 else NL.join([build_title(row), "", f"📣 {DECLARATION_1}", "", "▼ くわしくは", wp_url, "", hashtags(row)])


def build_instagram_caption(row: dict, wp_url: str) -> str:
    """IGはURLを押せないので、必ず「プロフィールのリンクから」と案内する"""
    ad = is_ad(row)
    marks = "①②③"
    lines = [build_title(row), "", f"📣 {DECLARATION_1}", f"{DECLARATION_2}", DECLARATION_3, ""]
    lines += [NOTE_IRAI if ad else NOTE_KATTE, ""]
    for i, (h, b) in enumerate(points(row)):
        lines += [f"{marks[i]} {h}"] + [x.strip() for x in b.split(NL) if x.strip()] + [""]
    if _g(row, "ひとこと"):
        lines += [f"🦊 管理人のひとこと（偏見）：{_g(row, 'ひとこと')}", ""]
    if area(row):
        lines += [f"📍 {area(row)}", ""]
    if ad and _g(row, "問い合わせ"):
        lines += [f"📞 お問い合わせ先：{_g(row, '問い合わせ').replace(NL, ' ')}", "※豊川ガイドでは、内見の手配・お申し込みの受付は行っていません", ""]
    lines += [
        "住んでみないと、分かりません。最後は、自分の目で。",
        "",
        "▼ この記事の全文は",
        "豊川ガイド @toyokawaguide の",
        "プロフィールのリンクから",
        "",
        "📣 「うちの物件もほめてほしい」という方は",
        "豊川ガイド @toyokawaguide のDMへ",
        "",
        hashtags(row) + (" #広告" if ad else "") + (" #豊川市賃貸" if in_toyokawa(row) else "") + " #地域メディア",
    ]
    return NL.join(lines)


def card_row(row: dict) -> dict:
    """画像を描く側（pr_eyecatch＝さくっとPRと同じ絵）に渡す入力"""
    return {
        "店名": _g(row, "物件名"),
        "ひとことキャッチ": _g(row, "ひとことキャッチ"),
        "エリア・住所": area(row),
        "ラベル": ("PR｜" if is_ad(row) else "") + "物件紹介｜良いことしか言いません",
        "色": "すみれ",
        "備考": _g(row, "備考"),
    }
