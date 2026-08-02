# -*- coding: utf-8 -*-
"""シリーズ名（「さくっとお知らせ」「さくっとPR」など）を1か所で持つ。

これまでは各所にベタ書きされていて、増やすたびに全部直す必要があった。
配信スクリプトの先頭で set_label() を呼ぶだけで、
記事タイトル／本文／SNSキャプション／アイキャッチ／リール／写真フレームの
すべてに反映される。

使い方:
    import series
    series.set_label("さくっとPR")     # 既定は「さくっとお知らせ」

⚠️ 参照側は `from series import LABEL` ではなく `import series` → `series.LABEL` と書くこと。
   前者だと import 時の値がコピーされ、あとから set_label() しても変わらない。
"""

DEFAULT_LABEL = "さくっとお知らせ"
LABEL = DEFAULT_LABEL

# ラベルごとのハッシュタグ。未登録のラベルは「#」＋ラベルを自動で使う
_TAG_OVERRIDE = {
    "さくっとお知らせ": "#さくっとお知らせ",
    "さくっとPR": "#さくっとPR",
}


def set_label(label: str | None) -> str:
    """シリーズ名を差し替える。空・None なら既定に戻す。"""
    global LABEL
    LABEL = (label or "").strip() or DEFAULT_LABEL
    return LABEL


# 帯の配色。広告シリーズは一目で見分けがつくようゴールド帯にする（社長決定 2026-08-02 A案）
# ステマ規制は「一般消費者が広告だと明瞭に認識できること」を求めるので、
# 文字（【PR】）だけでなく見た目でも区別がつくようにしておく。
_BAND_DEFAULT = ((252, 245, 230), (60, 50, 30))     # ベージュ帯 ＋ 濃茶文字
_BAND_AD = ((212, 160, 23), (26, 58, 138))          # ゴールド帯 ＋ 紺文字
_BAND_OVERRIDE = {
    "さくっとPR": _BAND_AD,
}


def band_colors():
    """(帯の背景色, 帯の上の文字色) を返す"""
    return _BAND_OVERRIDE.get(LABEL, _BAND_DEFAULT)


def is_ad() -> bool:
    """広告シリーズかどうか（開示表記の要否判定に使う）"""
    return LABEL in _BAND_OVERRIDE


def hashtag() -> str:
    """そのシリーズのハッシュタグ（空白を除いた `#ラベル`）"""
    if LABEL in _TAG_OVERRIDE:
        return _TAG_OVERRIDE[LABEL]
    return "#" + LABEL.replace(" ", "").replace("　", "")
