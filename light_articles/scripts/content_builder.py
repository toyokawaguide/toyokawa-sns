"""
content_builder.py — ライト記事の本文＆タイトルを生成

【モード】
- 続報モード（元記事タイトルあり）
- お知らせモード（元記事タイトルなし）
"""
from __future__ import annotations


def get_sub(row: dict) -> str:
    """その後（1段目）+ その後（2段目）を結合（後方互換：旧サブ列も対応）
    場所と完全一致する1段目は省略（LR002のような新店オープン記事対応）"""
    sub1 = row.get("その後（1段目）", "").strip()
    sub2 = row.get("その後（2段目）", "").strip()
    place = row.get("場所", "").strip()

    # 場所と同じ1段目は省略
    if sub1 and sub1 == place:
        sub1 = ""

    if sub1 and sub2:
        return f"{sub1}{sub2}"  # 改行なし結合（本文用）
    elif sub1:
        return sub1
    elif sub2:
        return sub2
    else:
        return row.get("サブ", "お知らせ").strip()  # 後方互換


def build_title(row: dict) -> str:
    """記事タイトル生成（タイトル上書き列が空でなければ優先）"""
    override = row.get("タイトル上書き", "").strip()
    if override:
        return override

    place = row.get("場所", "").strip()
    sub = get_sub(row)
    has_original = bool(row.get("元記事タイトル", "").strip())

    # 「その後」の冒頭が「場所」と一致する場合は省略（LR002のような新店オープン記事対応）
    sub_for_title = sub
    if place and sub_for_title.startswith(place):
        sub_for_title = sub_for_title[len(place):].lstrip("、,。 　")

    if has_original:
        # 続報モード
        return f"【さくっとお知らせ】{place} → {sub_for_title}"
    else:
        # お知らせモード
        return f"【さくっとお知らせ】{place}（{sub_for_title}）"


def build_content(row: dict, eyecatch_id: int = None,
                  photo_html: str = "") -> str:
    """本文 HTML を生成"""
    override = row.get("本文上書き", "").strip()
    if override:
        return override

    place = row.get("場所", "").strip()
    sub = get_sub(row)
    address = row.get("住所", "").strip()
    landmark = row.get("目印", "").strip()
    map_url = row.get("地図URL", "").strip()
    map_embed = row.get("地図埋込みコード", "").strip()
    original_url = row.get("元記事URL", "").strip()
    original_title = row.get("元記事タイトル", "").strip()
    has_original = bool(original_title)

    parts = []

    # === 冒頭・装飾ボックス（趣旨説明・全モード共通・絵文字なし） ===
    parts.append(f"<!-- wp:html -->")
    parts.append(
        '<div style="background:#fff8e7; border-left:5px solid #d4a017; '
        'padding:14px 18px; margin:1em 0; border-radius:6px; font-size:0.95em;">'
        '<p style="margin:0;"><strong>【さくっとお知らせ】</strong>は、'
        '以前ご紹介させて頂いた場所の続報や、'
        '豊川市内の&ldquo;ちょっとした街の変化&rdquo;を'
        'ゆるっとお届けする記事です。'
        '「そういえば…」のネタにでも使ってやってください。</p>'
        '</div>'
    )
    parts.append(f"<!-- /wp:html -->")
    parts.append("")

    # === リード文 ===
    if has_original:
        _, wp_predicate = _detect_zokuhou_lead(row)
        _wp_pre = row.get("リード接頭", "").strip() or "以前ご紹介した"
        parts.append(f"<!-- wp:paragraph -->")
        parts.append(f"<p>{_wp_pre}<strong>{place}</strong>の、{wp_predicate}</p>")
        parts.append(f"<!-- /wp:paragraph -->")
        parts.append("")

        if original_url:
            parts.append(f"<!-- wp:paragraph -->")
            parts.append(f"<p>▼ 過去記事はこちら<br>")
            parts.append(f'<a href="{original_url}" target="_blank" rel="noopener">{original_title}</a></p>')
            parts.append(f"<!-- /wp:paragraph -->")
            parts.append("")
    else:
        parts.append(f"<!-- wp:paragraph -->")
        parts.append(f"<p>管理人が街を歩いてて、ちょっと気になった<strong>{place}</strong>の話。<br>")
        parts.append(f"ゆるっとお知らせ程度に。</p>")
        parts.append(f"<!-- /wp:paragraph -->")
        parts.append("")

    # === 結末（アイキャッチと同じ形式で「{place} ▶ {sub}」表記） ===
    parts.append(f"<!-- wp:heading {{\"level\":3}} -->")
    parts.append(f"<h3>その後、どうなった？</h3>")
    parts.append(f"<!-- /wp:heading -->")
    parts.append("")
    parts.append(f"<!-- wp:paragraph -->")
    parts.append(f"<p><strong>{place}</strong> ▶ <strong>{sub}</strong></p>")
    parts.append(f"<!-- /wp:paragraph -->")
    parts.append("")

    # === 写真 ===
    if photo_html:
        parts.append(photo_html)
        parts.append("")

    # === 場所情報＋店舗SNSリンク ===
    shop_official = row.get("店舗公式サイトURL", "").strip()
    shop_instagram = row.get("店舗InstagramURL", "").strip()
    shop_x = row.get("店舗XURL", "").strip()
    if address or landmark or shop_official or shop_instagram or shop_x:
        parts.append(f"<!-- wp:heading {{\"level\":3}} -->")
        parts.append(f"<h3>場所</h3>")
        parts.append(f"<!-- /wp:heading -->")
        parts.append("")
        parts.append(f"<!-- wp:paragraph -->")
        loc_parts = []
        if address:
            loc_parts.append(f"住所：{address}")
        if landmark:
            loc_parts.append(f"目印：{landmark}")
        if map_url:
            loc_parts.append(f'<a href="{map_url}" target="_blank" rel="noopener">▶ Google Mapsで見る</a>')
        if shop_official:
            loc_parts.append(f'<a href="{shop_official}" target="_blank" rel="noopener">▶ 公式サイト</a>')
        if shop_instagram:
            loc_parts.append(f'<a href="{shop_instagram}" target="_blank" rel="noopener">▶ Instagram</a>')
        if shop_x:
            loc_parts.append(f'<a href="{shop_x}" target="_blank" rel="noopener">▶ X</a>')
        parts.append(f"<p>" + "<br>".join(loc_parts) + "</p>")
        parts.append(f"<!-- /wp:paragraph -->")
        parts.append("")

        # 地図埋込み（地図URLの下に表示）
        if map_embed:
            parts.append(f"<!-- wp:html -->")
            parts.append('<div style="margin:1em 0; max-width:100%; overflow:hidden;">')
            parts.append(map_embed)
            parts.append('</div>')
            parts.append(f"<!-- /wp:html -->")
            parts.append("")

    # === 管理人のつぶやき（N列に入力がある時のみ表示・絵文字なし） ===
    tsubuyaki = row.get("管理人のつぶやき", "").strip()
    if tsubuyaki:
        parts.append(f'<!-- wp:heading {{"level":3}} -->')
        parts.append(f"<h3>管理人のつぶやき</h3>")
        parts.append(f"<!-- /wp:heading -->")
        parts.append("")
        # 改行を <br> に変換
        tsubuyaki_html = tsubuyaki.replace("\n", "<br>")
        parts.append(f"<!-- wp:paragraph -->")
        parts.append(f"<p>{tsubuyaki_html}</p>")
        parts.append(f"<!-- /wp:paragraph -->")
        parts.append("")

    # === お礼セクションとの間に余白（つぶやきの有無に関わらず・お礼を独立感持たせる） ===
    parts.append(f'<!-- wp:spacer {{"height":"40px"}} -->')
    parts.append('<div style="height:40px" aria-hidden="true" class="wp-block-spacer"></div>')
    parts.append(f"<!-- /wp:spacer -->")
    parts.append("")

    # === 締め・お礼セクション（装飾なしシンプル版・スマホ対応） ===
    URL_CONTACT = "https://toyokawa-rentallife.com/inquiry/"
    URL_INSTAGRAM = "https://www.instagram.com/toyokawaguide/"
    URL_X = "https://x.com/toyokawaguide"
    URL_LINE = "https://line.me/ti/p/UhnW5Kpvyb"

    parts.append(f"<!-- wp:paragraph -->")
    parts.append(f"<p>豊川市民の皆様、いつも本当にありがとうございます！</p>")
    parts.append(f"<!-- /wp:paragraph -->")
    parts.append("")

    parts.append(f"<!-- wp:paragraph -->")
    parts.append(f"<p><strong>豊川ガイドは皆様からご提供頂く情報により成り立っております。マジで。</strong></p>")
    parts.append(f"<!-- /wp:paragraph -->")
    parts.append("")

    parts.append(f"<!-- wp:paragraph -->")
    parts.append(
        f"<p><strong>気まぐれ</strong>ではございますがお礼"
        f"（Amazonギフトカード）をさせて頂くこともございますので、"
        f"皆様の日常にある「ちょっと気になったこと」や「通りすがりの発見」など、"
        f"ジャンル問わず&ldquo;豊川市の小さな変化&rdquo;を教えて頂けますと幸いです。</p>"
    )
    parts.append(f"<!-- /wp:paragraph -->")
    parts.append("")

    parts.append(f"<!-- wp:list -->")
    parts.append(f"<ul>")
    parts.append(f'<li><a href="{URL_CONTACT}" target="_blank" rel="noopener">お問い合わせフォーム</a></li>')
    parts.append(f'<li><a href="{URL_INSTAGRAM}" target="_blank" rel="noopener">インスタグラム</a></li>')
    parts.append(f'<li><a href="{URL_X}" target="_blank" rel="noopener">Ｘ</a></li>')
    parts.append(f'<li><a href="{URL_LINE}" target="_blank" rel="noopener">ＬＩＮＥ（非公式）</a></li>')
    parts.append(f"</ul>")
    parts.append(f"<!-- /wp:list -->")

    return "\n".join(parts)


def build_photo_html(photo_urls: list[str]) -> str:
    """写真リストから WP本文用の HTML を生成"""
    if not photo_urls:
        return ""
    parts = []
    for url in photo_urls:
        parts.append(f'<!-- wp:image -->')
        parts.append(f'<figure class="wp-block-image"><img src="{url}" alt=""/></figure>')
        parts.append(f'<!-- /wp:image -->')
        parts.append("")
    return "\n".join(parts)


def _tsubuyaki_block(row: dict) -> list[str]:
    """管理人のつぶやきブロックを返す（あれば見出し＋本文の2要素／なければ空）"""
    tsubuyaki = row.get("管理人のつぶやき", "").strip()
    if not tsubuyaki:
        return []
    return ["▶ 管理人のつぶやき", tsubuyaki]


def _detect_zokuhou_lead(row: dict) -> tuple[str, str]:
    """続報モードのリード文をその後の内容から自動判定

    戻り値: (caption_lead, wp_predicate)
    - caption_lead: SNSキャプション用フル文（絵文字あり）
    - wp_predicate: WP本文用述語（場所名の後に続く・絵文字なし）
    """
    # リード接頭/接尾（V/W列・プルダウン）が指定されてれば最優先（自動判定より優先）
    _pre = row.get("リード接頭", "").strip()
    _suf = row.get("リード接尾", "").strip()
    if _pre or _suf:
        p = _pre or "以前ご紹介した"
        s = _suf or "の、その後が分かりました🤝"
        wp_pred = s.lstrip("の、 ").rstrip("🤝🎉😢👀… ").strip() or "その後が分かりました。"
        return (f"{p}あの場所{s}", wp_pred)

    sub1 = row.get("その後（1段目）", "").strip()
    sub2 = row.get("その後（2段目）", "").strip()
    combined = f"{sub1} {sub2}"

    if any(k in combined for k in ["オープン予定", "オープン日", "新規オープン",
                                     "開店", "新店", "オープンします"]):
        return ("以前ご紹介したあの場所のオープン日が分かりました🎉",
                "オープン日が分かりました。")
    if "閉店" in combined or "閉業" in combined:
        return ("以前ご紹介したあの場所、閉店情報が入りました…😢",
                "閉店情報が入りました。")
    if "リニューアル" in combined or "改装オープン" in combined:
        return ("以前ご紹介したあの場所のリニューアル情報をお届け🤝",
                "リニューアル情報が分かりました。")
    if "移転" in combined:
        return ("以前ご紹介したあの場所、移転先が分かりました🤝",
                "移転情報が分かりました。")
    # デフォルト
    return ("以前ご紹介したあの場所の、その後が分かりました🤝",
            "その後が分かりました。")


def _x_weight(text: str) -> int:
    """X の文字数カウント（CJK は 2 weight）。URL の自動短縮は概算 23 weight"""
    import re
    # URL を一律 23 weight に置換
    url_pattern = re.compile(r"https?://\S+")
    urls = url_pattern.findall(text)
    stripped = url_pattern.sub("", text)
    w = 23 * len(urls)
    for ch in stripped:
        # CJK 文字判定：ひらがな・カタカナ・漢字・全角記号
        if "　" <= ch <= "鿿" or "＀" <= ch <= "￯":
            w += 2
        else:
            w += 1
    return w


def build_x_caption(row: dict, wp_url: str) -> str:
    """X（Twitter）予約投稿用テキスト（手動コピペ用）

    280 weight を超える場合はつぶやきを省略してフォールバック。
    """
    place = row.get("場所", "").strip()
    sub = get_sub(row)
    has_original = bool(row.get("元記事タイトル", "").strip())

    if has_original:
        title = f"【さくっとお知らせ】{place} → {sub}"
        lead, _ = _detect_zokuhou_lead(row)
    else:
        title = f"【さくっとお知らせ】{place}"
        lead = f"街でちょっと気になった{place}の話、ゆるっとお届け。"

    closing = "豊川市のちょっとした変化、見つけたらDMで教えてね👀"
    hashtags = "#豊川市 #豊川ガイド #さくっとお知らせ"

    # まずはつぶやきあり版を試算
    ts = _tsubuyaki_block(row)
    if ts:
        full = (f"{title}\n\n{lead}\n\n{ts[0]}\n{ts[1]}"
                f"\n\n▼ 詳細\n{wp_url}\n\n{closing}\n\n{hashtags}")
        if _x_weight(full) <= 280:
            return full
        # オーバーする場合はつぶやき抜き
    return f"{title}\n\n{lead}\n\n▼ 詳細\n{wp_url}\n\n{closing}\n\n{hashtags}"


def build_threads_caption(row: dict, wp_url: str) -> str:
    """Threads 用キャプション（500字制限）

    Threads は文字数制限が緩いので管理人のつぶやきを常に含める。
    """
    place = row.get("場所", "").strip()
    sub = get_sub(row)
    has_original = bool(row.get("元記事タイトル", "").strip())

    if has_original:
        title = f"【さくっとお知らせ】{place} → {sub}"
        lead, _ = _detect_zokuhou_lead(row)
    else:
        title = f"【さくっとお知らせ】{place}"
        lead = f"街でちょっと気になった{place}の話、ゆるっとお届け。"

    closing = "豊川市のちょっとした変化、見つけたらDMで教えてね👀"
    hashtags = "#豊川市 #豊川ガイド #さくっとお知らせ"

    lines = [title, "", lead]
    ts = _tsubuyaki_block(row)
    if ts:
        lines += ["", ts[0], ts[1]]
    lines += ["", "▼ 詳細", wp_url, "", closing, "", hashtags]
    return "\n".join(lines)


def build_instagram_caption(row: dict, wp_url: str) -> str:
    """Instagram Feed 用キャプション（リンクは非クリッカブル）

    Instagram は 2200字制限なので管理人のつぶやきを常に含める。
    """
    place = row.get("場所", "").strip()
    sub = get_sub(row)
    address = row.get("住所", "").strip()
    has_original = bool(row.get("元記事タイトル", "").strip())

    if has_original:
        title = f"【さくっとお知らせ】{place} → {sub}"
        lead, _ = _detect_zokuhou_lead(row)
    else:
        title = f"【さくっとお知らせ】{place}（{sub}）"
        lead = f"街でちょっと気になった{place}の話、ゆるっとお届け。"

    lines = [title, "", lead]
    ts = _tsubuyaki_block(row)
    if ts:
        lines += ["", ts[0], ts[1]]
    if address:
        lines += ["", f"📍 {address}"]
    lines += [
        "",
        "▼ 詳細",
        "プロフィールのリンクから本文をどうぞ",
        "",
        "👀 豊川市のちょっとした変化、見つけたらDMで教えてね",
        "",
        "#豊川市 #豊川ガイド #さくっとお知らせ #地域メディア",
    ]
    return "\n".join(lines)
