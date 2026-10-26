"""
物件資料（CSV / Excel / PDF）から建物単位の情報を抜き出して 1 つの Excel にまとめる。

抜き出す項目: 物件名・所在地・築年・構造・階建て・管理会社・種別
（賃料・間取りなど部屋ごとの条件は対象外。空室数だけ数える）

使い方:
  python property_check/extract_properties.py --input 資料フォルダ --output 物件情報_抜き出し.xlsx

対応している資料（2026-10-26 時点で受け取った形式）:
  - CSV（Shift-JIS）  : 取引態様,種別,物件名/部屋番号,所在地,…,築年月 の形式
  - Excel             : 「空室一覧表」（1部屋2行、建物CD・構造・完成年月・住所）
  - PDF ミニミニ空室一覧 : 物件名/部屋番号/所在地/…/築年 の表
  - PDF 業者サイト一覧   : 物件名/部屋番号＋管理会社、所在地＋交通、階建て＋築年数 の表
  - PDF リアプロBB+     : 建物ごとのブロック（名前・管理会社・所在地・構造/階数/築年月）
  複数の資料をつなげた PDF でも、ページごとに形式を見分けて読む。

注意:
  - リアプロBB+ の一部（レオパレス物件）は元 PDF の時点で物件名が文字化けしている。
    Shift-JIS の残骸から、他資料の物件名＋同じ町・築年で読み替え、確からしさを記録する。
  - 資料そのもの・出力 Excel には鍵番号や連絡先が含まれるのでリポジトリに入れないこと。
"""
import argparse
import csv
import datetime
import io
import logging
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import openpyxl
import pdfplumber
from openpyxl.styles import Font, PatternFill

logging.disable(logging.WARNING)  # pdfplumber の FontBBox 警告を抑止

THIS_YEAR = datetime.date.today().year

# NFKC で直らない部首系の異体字（⻄・⻯など）と中黒の揺れをそろえる
RAD = str.maketrans({'⻄': '西', '⻯': '竜', '⻑': '長', '⻘': '青', '⻤': '鬼', '⻁': '虎', '⻩': '黄',
                     '⻝': '食', '⻫': '斉', '⻭': '歯', '⻲': '亀', '‧': '・', '･': '・'})


def nf(s):
    """全角半角・異体字をそろえる（改行は残す）"""
    return unicodedata.normalize('NFKC', str(s or '')).translate(RAD)


def N(s):
    return nf(s).replace('\n', '').strip()


def room(src, name, room_no, addr, built, struct='', floors='', kanri='', kind=''):
    return dict(src=src, name=name, room=room_no, addr=addr, built=built,
                struct=struct, floors=floors, kanri=kanri, kind=kind)


# ---------- 資料ごとの読み取り ----------

def read_csv(path):
    raw = path.read_bytes()
    for enc in ('utf-8-sig', 'cp932'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if '物件名/部屋番号' not in r or '所在地' not in r:
            print(f'  ! {path.name}: 未対応の CSV 形式のためスキップ')
            return []
        nm = N(r['物件名/部屋番号'])
        m = re.match(r'^(.*?)\s*([A-Z]?[-－]?\d{3,4}|[A-Z]-?\d|\d-O|[①②③④⑤]\d{3})$', nm)
        rows.append(room(f'{path.name}', m.group(1) if m else nm, m.group(2) if m else '',
                         N(r['所在地']), N(r.get('築年月')), kind=N(r.get('種別'))))
    return rows


def read_xlsx(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = []
    for ws in wb.worksheets:
        x = list(ws.iter_rows(values_only=True))
        # 見出し行（「建物CD」を含む行）を探す。次の行が2段目の見出し
        h = next((i for i, r in enumerate(x) if r and '建物CD' in [N(c) for c in r]), None)
        if h is None:
            print(f'  ! {path.name}/{ws.title}: 未対応の Excel 形式のためスキップ')
            continue
        head = [N(c).replace(' ', '') for c in x[h]]
        col = {k: head.index(k) for k in ('物件名', '部屋番号', '構造', '完成年月') if k in head}
        head2 = [N(c).replace(' ', '') for c in x[h + 1]]
        col2 = {k: head2.index(k) for k in ('住所', '種別') if k in head2}
        body = x[h + 2:]
        # 1部屋2行（1行目: 建物CD・物件名… / 2行目: 住所・種別…）
        start = next((i for i, r in enumerate(body) if r and r[col['物件名']]), 0)
        for a, b in zip(body[start::2], body[start + 1::2]):
            if not a[col['物件名']]:
                continue
            rows.append(room(path.name, N(a[col['物件名']]), N(a[col['部屋番号']]),
                             N(b[col2['住所']]), N(a[col['完成年月']]),
                             struct=N(a[col['構造']]), kind=N(b[col2['種別']])))
    return rows


def read_pdf(path):
    rows = []
    with pdfplumber.open(path) as p:
        first = p.pages[0].extract_text() or ''
        minimini = 'ミニミニ' in first and '空室一覧' in first
        rnp_pages = []
        for pg in p.pages:
            text = pg.extract_text() or ''
            if 'リアプロBB' in text:
                rnp_pages.append(pg)
            elif minimini:
                rows += _minimini_page(path, pg)
            else:
                rows += _portal_page(path, pg)
        rows += _rnp_pages(path, rnp_pages)
    return rows


def _minimini_page(path, pg):
    out = []
    for t in pg.extract_tables():
        for r in t:
            if not r or len(r) < 9 or not r[0] or N(r[0]) == '物件名':
                continue
            out.append(room(f'{path.name}(ミニミニ)', N(r[0]), N(r[1]), N(r[2]), N(r[8])))
    return out


def _portal_page(path, pg):
    """業者サイト一覧（物件名/部屋番号＋管理会社、所在地＋交通 … 階建て＋築年数）"""
    out = []
    for t in pg.extract_tables():
        for r in t:
            # 列ずれ対策: 「愛知県」で始まるセルを所在地列とし、その左を物件名列とする
            ai = next((k for k, c in enumerate(r) if c and nf(c).startswith('愛知県')), None)
            if ai is None or ai < 1 or not r[ai - 1] or len(r) <= ai + 6:
                continue
            name_cell, addr_cell, fb_cell = r[ai - 1], r[ai], r[ai + 6]
            lines = nf(name_cell).split('\n')
            nm, kanri = lines[0].strip(), ''.join(lines[1:]).strip()
            m = re.match(r'^(.*\S)\s+(\S+)$', nm)
            name, room_no = (m.group(1), m.group(2)) if m and re.search(r'\d', m.group(2)) else (nm, '')
            # 物件名が折り返されて部屋番号が2行目に回ったケース（例: 「ト 210株式会社…」）
            m2 = re.match(r'^(\S{0,6}?)\s*(\d{2,4}[A-Z]?)(\D.*)?$', kanri) if not room_no else None
            if m2:
                name, room_no, kanri = name + m2.group(1), m2.group(2), (m2.group(3) or '').strip()
            fb = nf(fb_cell).split('\n')
            out.append(room(f'{path.name}(業者サイト)', name, room_no, nf(addr_cell).split('\n')[0].strip(),
                            fb[1].strip() if len(fb) > 1 else '', floors=fb[0].strip(), kanri=kanri))
    return out


def _rnp_pages(path, pages):
    """リアプロBB+: 「構造地上N階 / YYYY年MM月築」の行を手がかりに、その3行上を物件名とする"""
    out, cur = [], None
    for pg in pages:
        L = [nf(l).strip() for l in (pg.extract_text() or '').split('\n')]
        for i, l in enumerate(L):
            m = re.match(r'^(\S*造)地上(\d+)階\s*/\s*(\d{4}年\d{2}月)築', l)
            if m and i >= 3:
                cur = room(f'{path.name}(リアプロBB+)', L[i - 3], '', L[i - 1].split('/')[0].strip(), m.group(3),
                           struct=m.group(1), floors=f'{m.group(2)}階建', kanri=L[i - 2])
                continue
            if cur and re.match(r'^(空室|退去予定|申込|居住中|募集停止)', l):
                out.append(dict(cur))
    return out


# ---------- 文字化けした物件名の読み替え ----------

K = '〇一二三四五六七八九'


def clean_addr(a):
    a = re.sub(r'\s+', '', a.replace('丁目丁目', '丁目').replace('ヶ', 'ケ'))
    return '愛知県' + a if a.startswith('豊川市') else a


def town(a):
    a = clean_addr(a).replace('愛知県', '')
    a = re.sub(r'[一二三四五六七八九]丁目', lambda m: str(K.index(m.group(0)[0])) + '丁目', a)
    m = re.match(r'(豊川市[^\d\-番]+?(\d丁目)?)', a)
    return m.group(1) if m else a


def year_of(built):
    """'2004年11月' → 2004、'築28年' → 今年-28（概算）"""
    m = re.search(r'(\d{4})年', built)
    if m:
        return int(m.group(1))
    m = re.search(r'築(\d+)年', built)
    return THIS_YEAR - int(m.group(1)) if m else None


def garble(s):
    """Shift-JIS の非 ASCII バイトが '?' に化けた状態を再現する"""
    try:
        b = s.encode('cp932')
    except UnicodeEncodeError:
        return None
    return ''.join(chr(c) if c < 0x80 else '?' for c in b)


def resolve_garbled(rows):
    fw = lambda s: ''.join(chr(ord(c) + 0xFEE0) if c.isascii() and c.isalnum() else c for c in s)
    collapse = lambda s: re.sub(r'\?+', '?', s or '')
    variants = lambda n: {n, fw(n)}
    is_garbled = lambda n: n.count('?') >= 3
    others = {}
    for x in rows:
        if not is_garbled(x['name']):
            others.setdefault(x['name'], set()).add((town(x['addr']), year_of(x['built'])))
    result = {}
    for x in rows:
        if not is_garbled(x['name']):
            continue
        k = (x['name'], x['addr'], x['built'])
        if k in result:
            continue
        y, t = year_of(x['built']), town(x['addr'])
        near = [n for n, v in others.items()
                if any(tt == t and (yy is None or y is None or abs(yy - y) <= 1) for tt, yy in v)]
        exact = [n for n in near if any(garble(v) == x['name'] for v in variants(n))]
        loose = [n for n in near if any(collapse(garble(v)) == collapse(x['name']) for v in variants(n))]
        # 先頭1文字（カナの2バイト目）が一致する候補
        head = [n for n in near if any((garble(v) or '')[:12] == x['name'][:12] for v in variants(n))]
        if len(exact) == 1:
            result[k] = (exact[0], '確実（文字コード一致＋同じ町・築年）')
        elif len(loose) == 1:
            result[k] = (loose[0], 'ほぼ確実（文字コードほぼ一致＋同じ町・築年）')
        elif len(head) == 1:
            result[k] = (head[0], 'ほぼ確実（名前の先頭が一致＋同じ町・築年）')
        elif len(near) == 1:
            result[k] = (near[0], '推定（同じ町・築年の物件が1つだけ）')
        else:
            result[k] = ('', '不明（候補: ' + ' / '.join(near) + '）' if near else '不明（他資料に候補なし）')
    return result


# ---------- 建物単位にまとめて Excel 出力 ----------

def build_workbook(rows, gmap, out_path):
    key = lambda n: re.sub(r'[\s・]', '', n).upper()
    B = {}
    for x in rows:
        name, note = x['name'], ''
        g = gmap.get((x['name'], x['addr'], x['built']))
        if g:
            if g[0]:
                name, note = g[0], '元資料で文字化け→' + g[1]
            else:
                name, note = '（文字化けで不明）' + clean_addr(x['addr']).replace('愛知県豊川市', ''), '元資料で文字化け→' + g[1]
        d = B.setdefault(key(name), dict(name=name, addr=Counter(), year=Counter(), struct=set(), floors=set(),
                                         kanri=set(), kind=set(), src=set(), rooms=0, note=set()))
        d['rooms'] += 1
        if x['addr']:
            d['addr'][clean_addr(x['addr'])] += 1
        y = year_of(x['built'])
        if y:
            d['year'][str(y) if re.search(r'\d{4}年', x['built']) else f'{y}頃'] += 1
        for f in ('struct', 'floors', 'kanri', 'kind'):
            if x[f] and x[f] != '入力なし':
                d[f].add(x[f])
        d['src'].add(x['src'])
        if note:
            d['note'].add(note)
        if '丁目丁目' in x['addr']:
            d['note'].add('元資料の住所が「丁目丁目」と重複表記')

    def flags(d):
        f = []
        if not d['addr']:
            f.append('所在地なし')
        else:
            towns = {re.sub(r'[\d\-番地号の]+.*$', '', a) for a in d['addr']}
            if len(towns) > 1:
                f.append('所在地が資料間で不一致')
            if not any(re.search(r'\d', re.sub(r'[\d一二三四五六七八九]+丁目', '', a)) for a in d['addr']):
                f.append('番地なし')
        ys = {int(y[:4]) for y in d['year']}
        if ys and max(ys) - min(ys) > 1:
            f.append('築年が資料間で不一致')
        if not d['year']:
            f.append('築年なし')
        if not d['struct']:
            f.append('構造なし')
        if not d['kanri']:
            f.append('管理会社なし')
        if any('不明' in n or '推定' in n for n in d['note']):
            f.append('物件名要確認')
        return f

    out = []
    for d in B.values():
        best = max(d['addr'], key=lambda a: (len(re.findall(r'\d', a)), d['addr'][a])) if d['addr'] else ''
        yrs = sorted(d['year'], key=lambda y: (y.endswith('頃'), y))
        j = lambda s: ' / '.join(sorted(s))
        out.append([d['name'], best, j(d['addr']), yrs[0] if yrs else '', j(d['struct']), j(d['floors']),
                    j(d['kanri']), j(d['kind']), d['rooms'], j(d['src']), '・'.join(flags(d)), ' '.join(sorted(d['note']))])
    out.sort(key=lambda r: (r[1].replace('愛知県豊川市', '')[:4], r[0]))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '建物一覧'
    ws.append(['物件名', '所在地（最も詳しいもの）', '所在地（資料ごとの表記）', '築年', '構造', '階建て',
               '管理会社', '種別', '空室数', '出典', '要確認', 'メモ'])
    for r in out:
        ws.append(r)
    hdr, warn = PatternFill('solid', fgColor='DDEBF7'), PatternFill('solid', fgColor='FFF2CC')
    for c in ws[1]:
        c.font, c.fill = Font(bold=True), hdr
    for row in ws.iter_rows(min_row=2):
        if row[10].value and ('不一致' in row[10].value or '要確認' in row[10].value):
            for c in row:
                c.fill = warn
    for col, w in zip('ABCDEFGHIJKL', [28, 34, 40, 9, 12, 9, 30, 10, 7, 30, 30, 40]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'B2'
    ws.auto_filter.ref = ws.dimensions

    ws2 = wb.create_sheet('資料別の件数')
    ws2.append(['資料', '部屋数', '建物数'])
    for s in sorted({x['src'] for x in rows}):
        xs = [x for x in rows if x['src'] == s]
        ws2.append([s, len(xs), len({x['name'] + x['addr'] for x in xs})])
    ws2.column_dimensions['A'].width = 40

    ws3 = wb.create_sheet('文字化けの読み替え')
    ws3.append(['所在地', '築年月', '元資料の表記', '読み替えた物件名', '確からしさ'])
    for (g, a, b), v in gmap.items():
        ws3.append([clean_addr(a), b, g, v[0], v[1]])
    for col, w in zip('ABCDE', [30, 10, 34, 28, 50]):
        ws3.column_dimensions[col].width = w
    wb.save(out_path)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', required=True, help='資料を入れたフォルダ（サブフォルダも読む）')
    ap.add_argument('--output', required=True, help='出力する Excel のパス')
    a = ap.parse_args()

    readers = {'.csv': read_csv, '.xlsx': read_xlsx, '.pdf': read_pdf}
    rows = []
    for path in sorted(Path(a.input).rglob('*')):
        fn = readers.get(path.suffix.lower())
        if not fn or path.name.startswith('~'):
            continue
        got = fn(path)
        print(f'  {path.name}: {len(got)} 部屋')
        rows += got
    if not rows:
        sys.exit('読み取れる資料がありませんでした')

    gmap = resolve_garbled(rows)
    out = build_workbook(rows, gmap, a.output)
    c = Counter(f for r in out for f in r[10].split('・') if f)
    print(f'部屋 {len(rows)} / 建物 {len(out)}')
    print('文字化け読み替え:', dict(Counter(v[1].split('（')[0] for v in gmap.values())))
    print('要確認:', dict(c))
    print(f'出力: {a.output}')


if __name__ == '__main__':
    main()
