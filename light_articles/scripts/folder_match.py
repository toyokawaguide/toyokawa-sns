# -*- coding: utf-8 -*-
"""写真フォルダ名と記事内容の整合チェック（2026-08-01 社長指示）

背景: フォルダ名は「SNS053_2026.08.03【いよいよ本丸へ】豊川市役所の分庁舎…」のように
      ID の後ろに日付と記事タイトルが入っている。従来は ID の前方一致だけで写真を拾っていたため、
      フォルダを取り違えても気づけず「違う写真が反映される」事故が起きた。

判定: ① ID一致  ② 日付が両方にあれば突合  ③ 特徴語の一致（タイトル⇔フォルダ名の双方向）
      いずれかで不一致なら RuntimeError で止める（間違った写真で投稿するより中止が安全）。
"""
import re
import unicodedata

# 記事タイトルによく出るが識別に役立たない語
STOP = {
    "豊川", "豊川市", "豊川ガイド", "こと", "そう", "みたい", "って", "けど", "から", "ため",
    "ここ", "どこ", "これ", "それ", "あれ", "です", "ます", "した", "ある", "いる", "する",
    "さん", "様", "予定", "情報", "お知らせ", "本当", "今回", "現在", "場所", "跡地",
}

DATE_RE = re.compile(r"(20\d{2})[.\-/年]\s*(\d{1,2})[.\-/月]\s*(\d{1,2})")


def norm(s: str) -> str:
    """比較用に正規化（全半角統一・記号と空白を除去・小文字化）"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"[\s　]+", "", s)
    s = re.sub(r"[【】「」『』（）()\[\]〈〉《》・･、。，．,\.!！?？…‥\-—–ー~〜/／\\|｜:：;；＋+*＊&＆'\"”“’]", "", s)
    return s.lower()


def keywords(text: str, min_len: int = 2, top: int = 12) -> list:
    """識別に効く語を取り出す（カタカナ/漢字/英数のかたまり）"""
    t = unicodedata.normalize("NFKC", str(text or ""))
    toks = re.findall(r"[ァ-ヶー]{2,}|[一-龥]{2,}|[A-Za-z][A-Za-z0-9]{2,}|[0-9]{3,}", t)
    out = []
    for w in toks:
        if len(w) < min_len or w in STOP:
            continue
        if norm(w) in [norm(x) for x in out]:
            continue
        out.append(w)
    return out[:top]


def pick_date(s):
    """文字列から日付(年,月,日)を取り出す。無ければ None"""
    m = DATE_RE.search(unicodedata.normalize("NFKC", str(s or "")))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _rate(src: str, target: str):
    """src の特徴語が target にどれだけ含まれるか (率, 一致語, 使った語)"""
    tn = norm(target)
    kws = keywords(src)
    if not kws:
        return None, [], []
    hit = [w for w in kws if norm(w) and norm(w) in tn]
    return len(hit) / len(kws), hit, kws


def _bigrams(s: str) -> set:
    n = norm(s)
    return {n[i:i + 2] for i in range(len(n) - 1)}


def _ngram_rate(a: str, b: str):
    """短い方の2文字組が長い方にどれだけ含まれるか（「かき氷」のような
    漢字＋ひらがなの複合語を語分割できないケースの救済）"""
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return None
    small, large = (ba, bb) if len(ba) <= len(bb) else (bb, ba)
    if len(small) < 4:                        # 短すぎる文字列は偶然一致しやすいので使わない
        return None
    return len(small & large) / len(small)


def match_score(title: str, folder_tail: str) -> tuple:
    """(一致率0..1, 一致した語, 使った語)
    タイトル→フォルダ / フォルダ→タイトル の双方向＋文字N-gramで見て、最も高い値を採る。
    （フォルダ名は「マルイチ八幡店ローソン」のように短縮されることがあるため）"""
    tail = DATE_RE.sub("", folder_tail)
    fwd, fhit, fkws = _rate(title, tail)      # タイトルの語がフォルダ名にあるか
    rev, rhit, rkws = _rate(tail, title)      # フォルダ名の語がタイトルにあるか
    cands = []
    if fwd is not None:
        cands.append((fwd, fhit, fkws))
    if rev is not None and len(rkws) >= 2:    # 語1個だけの逆方向は信用しない
        cands.append((rev, rhit, rkws))
    ng = _ngram_rate(title, tail)
    if ng is not None and ng >= 0.55:         # 文字レベルでほぼ同じ内容 → 一致とみなす
        cands.append((ng, ["文字一致{:.0%}".format(ng)], ["文字列全体"]))
    if not cands:
        return 1.0, [], []                    # 判定材料なし → 通す
    return max(cands, key=lambda x: x[0])


def verify(ID: str, folder_name: str, title: str, pub_date=None,
           threshold: float = 0.34, raise_on_fail: bool = True):
    """フォルダ名が記事内容と合っているか検証。
    pub_date: キュー側の公開日（"2026.08.03" 等）。フォルダ名にも日付があれば突合する。"""
    base = folder_name.split("_", 1)
    fid = base[0].strip()
    tail = base[1] if len(base) > 1 else ""

    # ① ID そのものの一致
    if norm(fid) != norm(ID):
        msg = "写真フォルダのIDが違います: 要求={} / フォルダ={}（{}）".format(ID, fid, folder_name)
        if raise_on_fail:
            raise RuntimeError(msg)
        return False, msg

    if not tail.strip():
        return True, "{}: フォルダ名に記事名なし（ID一致のみで通過）".format(ID)

    # ② 日付が両方にあれば突合（最も確実な取り違え検知）
    fd, qd = pick_date(tail), pick_date(pub_date)
    if fd and qd and fd != qd:
        msg = ("写真フォルダの日付が記事とズレています（{}）\n"
               "    フォルダ: {}\n"
               "    キュー  : {}\n"
               "    → 別の日の写真フォルダを掴んでいる可能性。".format(ID, folder_name, pub_date))
        if raise_on_fail:
            raise RuntimeError(msg)
        return False, msg
    date_ok = bool(fd and qd and fd == qd)

    # ③ 特徴語の一致（双方向）
    rate, hit, kws = match_score(title, tail)
    if rate < threshold and not (date_ok and hit):
        msg = ("写真フォルダと記事内容が一致しません（{}）\n"
               "    フォルダ: {}\n"
               "    記事    : {}\n"
               "    一致率  : {:.0%}（{}/{}語）一致した語={}\n"
               "    → 違う写真が入っている可能性。フォルダ名かキューを直してください。"
               .format(ID, folder_name, title, rate, len(hit), len(kws), hit))
        if raise_on_fail:
            raise RuntimeError(msg)
        return False, msg

    d = "・日付一致" if date_ok else ""
    return True, "{}: フォルダ名と記事内容が一致（{:.0%}{}・{}）".format(ID, rate, d, hit)
