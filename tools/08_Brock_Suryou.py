import json
import math
import os
import ezdxf
from ezdxf import bbox

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

# D13 単位重量 (kg/m)
D13_KG_PER_M = 0.995

def _r3(x):
    """m単位の値を小数点以下3桁に四捨五入する。以降の計算はこの値を使う。"""
    return round(x, 3)

def _section_entities(danmen_msp, offset_x, spacing=15000.0):
    """danmen.dxf の中から指定セクション（offset_x）に属するエンティティだけを抜き出す。"""
    x_lo = offset_x - spacing / 2
    x_hi = offset_x + spacing / 2
    found = []
    for e in danmen_msp:
        bb = bbox.extents([e], fast=True)
        if not bb.has_data:
            continue
        cx = (bb.extmin.x + bb.extmax.x) / 2
        if x_lo <= cx < x_hi:
            found.append(e)
    return found

def _foundation_pe_bk_points(entities):
    """セクション内の05_Foundationレイヤの3本目のポリライン（ペーライン背面）の頂点を取得する。
    05_Brock_Danmen.py の描画順（ume, pe_bot, pe_bk）に依存。
    """
    polys = [e for e in entities if e.dxftype() == 'LWPOLYLINE' and e.dxf.layer == '05_Foundation']
    if len(polys) < 3:
        return None
    return [(p[0], p[1]) for p in polys[2].get_points('xy')]

def koguchi_quantities(pts, ox, foundation_type='direct', pe_bk_pts=None):
    """すべての数値をm単位で扱い、計算結果は都度小数点3桁に四捨五入してから
    次の計算へ使う（図面の寸法値に合わせるため）。
    """
    def m(mm):
        return mm / 1000.0

    bf_x1 = m(pts['block_btm_front'][0] - ox)
    bf_y1 = m(pts['block_btm_front'][1])
    bf_x2 = m(pts['tenba_btm_front'][0] - ox)
    bf_y2 = m(pts['tenba_btm_front'][1])
    bf_dx = bf_x2 - bf_x1
    bf_dy = bf_y2 - bf_y1

    def x_bf_at(y):
        return _r3(bf_x1 + (y - bf_y1) / bf_dy * bf_dx)

    y_top = m(pts['tenba_top_front'][1])
    # 岩着基礎：打継目・伸び率は07aと同じ「ブロック前面下端」までの高さを使う
    # （ぺーライン背面の突出部は別区間③として側面積にのみ加算する）
    y_bottom = bf_y1 if foundation_type == 'rock' else m(pts['kiso_btm_front'][1])
    takasa_m = _r3(y_top - y_bottom)

    x_bf_top    = x_bf_at(y_top)
    x_bf_bottom = x_bf_at(y_bottom)
    x_exc_top    = m(pts['exc_top'][0]    - ox)
    x_exc_bottom = m(pts['exc_bottom'][0] - ox)
    y_exc_top    = m(pts['exc_top'][1])
    y_exc_bottom = m(pts['exc_bottom'][1])

    def x_exc_at(y):
        return _r3(x_exc_bottom + (y - y_exc_bottom) / (y_exc_top - y_exc_bottom) * (x_exc_top - x_exc_bottom))

    # 裏砕石上端オフセット：天端〜裏砕石上端の間は背面が掘削面ではなく裏コン背面ライン（うら線）になる
    # （天端コンがある場合はオフセット自体が常に0なので、ここではブロック上面=tenba_btm_frontを基準に判定する）
    tenba_btm_y_m = m(pts['tenba_btm_front'][1])
    saiseki_top_y = m(pts['saiseki_top_front'][1])
    has_offset    = saiseki_top_y < tenba_btm_y_m - 0.0005

    if has_offset:
        ura_x1 = m(pts['uracon_btm_back'][0] - ox)
        ura_y1 = m(pts['uracon_btm_back'][1])
        ura_x2 = m(pts['tenba_btm_back'][0]  - ox)
        ura_y2 = m(pts['tenba_btm_back'][1])

        def x_ura_at(y):
            return _r3(ura_x1 + (y - ura_y1) / (ura_y2 - ura_y1) * (ura_x2 - ura_x1))

    has_mid = 'exc_mid_bottom' in pts

    # 岩着基礎：ぺーライン背面のせり出し部分を含む3区間（変化点で分割）
    if foundation_type == 'rock' and pe_bk_pts is not None:
        backfill_y = m(pts['saiseki_btm_front'][1])
        pe_bk3 = (m(pe_bk_pts[3][0] - ox), m(pe_bk_pts[3][1]))  # ブロック前面下端側の先端
        pe_bk2 = (m(pe_bk_pts[2][0] - ox), m(pe_bk_pts[2][1]))  # 裏砕石底面側

        def x_pe_at(y):
            x1, y1 = pe_bk3; x2, y2 = pe_bk2
            return _r3(x1 + (y - y1) / (y2 - y1) * (x2 - x1))

        x_bf_mid    = x_bf_at(bf_y1)        # = block_btm_front.x（c1-c2線の下端）
        x_bf_backfl = x_bf_at(backfill_y)   # c1-c2線を backfill_y まで延長した位置

        # ① 天端 ～ 裏砕石底面：前面=ブロック前面線、背面=掘削面
        # 裏砕石上端オフセットがある場合、天端〜裏砕石上端は背面がうら線（裏コン背面）になるため分割する
        # 背面側はexc_bottom（裏砕石底面と同じ高さ）をそのまま使う
        if has_offset:
            jou_0   = _r3(x_ura_at(y_top) - x_bf_top)
            shita_0 = _r3(x_ura_at(saiseki_top_y) - x_bf_at(saiseki_top_y))
            h_0     = _r3(y_top - saiseki_top_y)
            area_0  = _r3((jou_0 + shita_0) / 2 * h_0)

            jou_1   = _r3(x_exc_at(saiseki_top_y) - x_bf_at(saiseki_top_y))
            shita_1 = _r3(x_exc_bottom - x_bf_backfl)
            h_1     = _r3(saiseki_top_y - backfill_y)
            area_1  = _r3((jou_1 + shita_1) / 2 * h_1)
        else:
            jou_1   = _r3(x_exc_top - x_bf_top)
            shita_1 = _r3(x_exc_bottom - x_bf_backfl)
            h_1     = _r3(y_top - backfill_y)
            area_1  = _r3((jou_1 + shita_1) / 2 * h_1)

        # ② 裏砕石底面 ～ ブロック前面下端：前面=ブロック前面線、背面=ぺーライン背面
        # backfill_y の高さで「掘削面→ぺーライン背面」へ背面側が水平に段差移動するため
        # jou_2（pe_bk2基準）はshita_1（exc_bottom基準）とは別の値になる
        jou_2   = _r3(x_pe_at(backfill_y) - x_bf_backfl)
        shita_2 = _r3(x_pe_at(bf_y1) - x_bf_mid)
        h_2     = _r3(backfill_y - bf_y1)
        area_2  = _r3((jou_2 + shita_2) / 2 * h_2)

        # ③ ブロック前面下端 ～ ぺーライン先端：前面=ブロック底面線、背面=ぺーライン背面
        jou_3   = shita_2   # 区間②の下辺をそのまま引き継ぐ（四捨五入済みの値）
        shita_3 = 0.0       # 先端で前面・背面が一致（幅0）
        h_3     = _r3(bf_y1 - pe_bk3[1])
        area_3  = _r3((jou_3 + shita_3) / 2 * h_3)

        if has_offset:
            sokumen_m2 = _r3(area_0 + area_1 + area_2 + area_3)
            parts = [
                {'label': '①天端〜裏砕石上端',         'jou': jou_0, 'shita': shita_0, 'h': h_0, 'area': area_0},
                {'label': '②裏砕石上端〜底面',         'jou': jou_1, 'shita': shita_1, 'h': h_1, 'area': area_1},
                {'label': '③裏砕石底面〜前面下端',     'jou': jou_2, 'shita': shita_2, 'h': h_2, 'area': area_2},
                {'label': '④前面下端〜ぺーライン先端', 'jou': jou_3, 'shita': shita_3, 'h': h_3, 'area': area_3},
            ]
        else:
            sokumen_m2 = _r3(area_1 + area_2 + area_3)
            parts = [
                {'label': '①天端〜裏砕石底面',         'jou': jou_1, 'shita': shita_1, 'h': h_1, 'area': area_1},
                {'label': '②裏砕石底面〜前面下端',     'jou': jou_2, 'shita': shita_2, 'h': h_2, 'area': area_2},
                {'label': '③前面下端〜ぺーライン先端', 'jou': jou_3, 'shita': shita_3, 'h': h_3, 'area': area_3},
            ]
    # 段があるときは上下に分割して合算
    elif has_mid:
        y_mid       = m(pts['exc_mid_bottom'][1])
        x_exc_mid_b = m(pts['exc_mid_bottom'][0] - ox)   # 段の下コーナー（右境界・下部）
        x_exc_mid_t = m(pts['exc_mid_top'][0]    - ox)   # 段の上コーナー（右境界・上部）
        x_bf_mid    = x_bf_at(y_mid)

        # 上部台形: y_mid ～ y_top
        jou_u   = _r3(x_exc_top   - x_bf_top)   # 上端幅
        shita_u = _r3(x_exc_mid_t - x_bf_mid)   # 下端幅（段の上）
        h_u     = _r3(y_top - y_mid)
        area_u  = _r3((jou_u + shita_u) / 2 * h_u)

        # 下部台形: y_bottom ～ y_mid
        jou_l   = _r3(x_exc_mid_b - x_bf_mid)   # 上端幅（段の下）
        shita_l = _r3(x_exc_bottom - x_bf_bottom)
        h_l     = _r3(y_mid - y_bottom)
        area_l  = _r3((jou_l + shita_l) / 2 * h_l)

        sokumen_m2 = _r3(area_u + area_l)
        parts = [
            {'label': '上部', 'jou': jou_u,  'shita': shita_u, 'h': h_u,  'area': area_u},
            {'label': '下部', 'jou': jou_l,  'shita': shita_l, 'h': h_l,  'area': area_l},
        ]
    elif has_offset:
        # 裏砕石上端オフセットがある場合、天端〜裏砕石上端は背面がうら線（裏コン背面）になるため分割する
        jou_0   = _r3(x_ura_at(y_top) - x_bf_top)
        shita_0 = _r3(x_ura_at(saiseki_top_y) - x_bf_at(saiseki_top_y))
        h_0     = _r3(y_top - saiseki_top_y)
        area_0  = _r3((jou_0 + shita_0) / 2 * h_0)

        jou_1   = _r3(x_exc_at(saiseki_top_y) - x_bf_at(saiseki_top_y))
        shita_1 = _r3(x_exc_bottom - x_bf_bottom)
        h_1     = _r3(saiseki_top_y - y_bottom)
        area_1  = _r3((jou_1 + shita_1) / 2 * h_1)

        sokumen_m2 = _r3(area_0 + area_1)
        parts = [
            {'label': '①天端〜裏砕石上端', 'jou': jou_0, 'shita': shita_0, 'h': h_0, 'area': area_0},
            {'label': '②裏砕石上端〜下端', 'jou': jou_1, 'shita': shita_1, 'h': h_1, 'area': area_1},
        ]
    else:
        jou_haba   = _r3(x_exc_top    - x_bf_top)
        shita_haba = _r3(x_exc_bottom - x_bf_bottom)
        sokumen_m2 = _r3((jou_haba + shita_haba) / 2 * takasa_m)
        parts = [
            {'label': '',   'jou': jou_haba, 'shita': shita_haba, 'h': takasa_m, 'area': sokumen_m2},
        ]

    # コンクリート体積 (m^3) = 側面積 × 0.30
    concrete_m3 = _r3(sokumen_m2 * 0.30)

    # 型枠面積 (m^2) = 側面積×2 + 高さ×伸び率×0.30
    slope_len_m = _r3(math.sqrt((x_bf_top - x_bf_bottom) ** 2 + takasa_m ** 2))
    nobiri       = _r3(slope_len_m / takasa_m)
    kata_waku_m2 = _r3(sokumen_m2 * 2 + takasa_m * nobiri * 0.30)

    # 打継目（1500mm間隔の分割数は元のmm基準のルールをそのまま使う）
    n_divs   = math.ceil(takasa_m * 1000 / 1500)
    n_joints = n_divs - 1

    # 鉄筋 D13: 0.60×2×継ぎ目数 + 0.30×（継ぎ目数+1）
    d13_len_m = _r3(0.60 * 2 * n_joints + 0.30 * (n_joints + 1))
    d13_kg    = _r3(d13_len_m * D13_KG_PER_M)

    return {
        'has_mid':     has_mid,
        'parts':       parts,
        'takasa_m':    takasa_m,
        'sokumen_m2':  sokumen_m2,
        'nobiri':      nobiri,
        'n_divs':      n_divs,
        'n_joints':    n_joints,
        'concrete_m3': concrete_m3,
        'kata_waku_m2': kata_waku_m2,
        'd13_len_m':   d13_len_m,
        'd13_kg':      d13_kg,
    }

def _koguchi_term_str(p):
    """上辺=下辺のときは平均計算を省略して幅×高さのみ表示する。"""
    if abs(p['jou'] - p['shita']) < 0.0005:
        return f"{p['jou']:.3f} × {p['h']:.3f}"
    return f"({p['jou']:.3f}+{p['shita']:.3f})/2 × {p['h']:.3f}"

def compact_koguchi_lines(q):
    """koguchi.dxf に書き込むコンパクト版（測点見出し・高さ・打継目数・伸び率・小計を省略）。"""
    terms = [_koguchi_term_str(p) for p in q['parts']]
    if len(terms) >= 3:
        # 幅を抑えるため、3項目目以降は改行して"+"始まりの2行目に表示する
        area_lines = [
            f"    側面積{' + '.join(terms[:2])}",
            f"      + {' + '.join(terms[2:])} = {q['sokumen_m2']:.3f} m2",
        ]
    else:
        area_lines = [f"    側面積{' + '.join(terms)} = {q['sokumen_m2']:.3f} m2"]

    nj = q['n_joints']
    return [
        "  コンクリート",
        *area_lines,
        f"    {q['sokumen_m2']:.3f} × 0.30 = {q['concrete_m3']:.3f} m3",
        "",
        "  型枠",
        f"    {q['sokumen_m2']:.3f}×2 + {q['takasa_m']:.3f}×{q['nobiri']:.3f}×0.30 = {q['kata_waku_m2']:.3f} m^2",
        "",
        "  鉄筋（D13）",
        f"    0.60×2×{nj} + 0.30×{nj + 1} = {q['d13_len_m']:.3f} m",
        f"    {q['d13_len_m']:.3f} × {D13_KG_PER_M} = {q['d13_kg']:.3f} kg",
    ]

def write_koguchi_dxf_text(output_dir, rows, sec_spacing=20000.0):
    """各小口止インスタンスの図の下にコンパクトな数量計算を記入する。"""
    koguchi_path = os.path.join(output_dir, 'koguchi.dxf')
    if not os.path.exists(koguchi_path):
        print("    [エラー] koguchi.dxf が見つかりません（数量記入をスキップ）。")
        return

    doc = ezdxf.readfile(koguchi_path)
    msp = doc.modelspace()
    if 'KOGUCHI_SURYOU' not in {l.dxf.name for l in doc.layers}:
        doc.layers.new('KOGUCHI_SURYOU', dxfattribs={'color': 7})

    groups = {i: [] for i in range(len(rows))}
    for e in msp:
        bb = bbox.extents([e], fast=True)
        if not bb.has_data:
            continue
        cx = (bb.extmin.x + bb.extmax.x) / 2
        di = min(range(len(rows)), key=lambda i: abs(cx - i * sec_spacing))
        groups[di].append(bb)

    text_h     = 150.0
    line_h     = 220.0
    top_margin = 400.0

    for draw_i, (name, q) in enumerate(rows):
        bbs = groups[draw_i]
        if not bbs:
            continue
        x0 = min(b.extmin.x for b in bbs)
        y0 = min(b.extmin.y for b in bbs) - top_margin

        for i, line in enumerate(compact_koguchi_lines(q)):
            if not line:
                continue
            msp.add_text(line, dxfattribs={
                'insert': (x0, y0 - i * line_h),
                'height': text_h,
                'layer': 'KOGUCHI_SURYOU',
            })

    doc.saveas(koguchi_path)
    print("    記入成功: koguchi.dxf に数量計算を追記")

def fmt_koguchi_block(name, q):
    taka_m = q['takasa_m']
    soku   = q['sokumen_m2']
    nobiri = q['nobiri']
    nj     = q['n_joints']
    nd     = q['n_divs']

    lines = [f"【{name}】"]
    lines.append(f"  高さ     = {taka_m:.3f} m")
    lines.append(f"  打継目数 = {nj} 箇所（{nd} 打設）")
    lines.append(f"  伸び率   = {nobiri:.3f}")
    lines.append(f"")
    lines.append(f"  コンクリート")

    for p in q['parts']:
        lbl = f"  [{p['label']}]" if p['label'] else ""
        lines.append(
            f"    側面積{lbl} = {_koguchi_term_str(p)} = {p['area']:.3f} m^2"
        )
    if len(q['parts']) > 1:
        lines.append(f"    側面積 計 = {soku:.3f} m^2")
    lines.append(f"    体積   = {soku:.3f} × 0.30 = {q['concrete_m3']:.3f} m^3")
    lines.append(f"")
    lines.append(f"  型枠")
    lines.append(f"    = {soku:.3f}×2 + {taka_m:.3f}×{nobiri:.3f}×0.30")
    lines.append(f"    = {_r3(soku*2):.3f} + {_r3(taka_m*nobiri*0.30):.3f}")
    lines.append(f"    = {q['kata_waku_m2']:.3f} m^2")
    lines.append(f"")
    lines.append(f"  鉄筋（D13）")
    lines.append(f"    = 0.60×2×{nj} + 0.30×({nj}+1)")
    lines.append(f"    = {_r3(0.60*2*nj):.3f} + {_r3(0.30*(nj+1)):.3f} = {q['d13_len_m']:.3f} m")
    lines.append(f"    = {q['d13_len_m']:.3f} × {D13_KG_PER_M} = {q['d13_kg']:.3f} kg")

    return lines

def main(output_dir, **kwargs):
    danmen_data = load_json(os.path.join(output_dir, 'danmen_data.json'))
    input_data  = load_json(os.path.join(output_dir, 'input.json'))

    if not all([danmen_data, input_data]):
        print("    [エラー] 必要なJSONファイルが揃っていません。")
        return

    koguchi_type = input_data.get('koguchi_type', 'both')
    if koguchi_type == 'none':
        print("    小口止コンクリートなし → スキップ")
        return

    sections = danmen_data['sections']
    n_sec    = len(sections)
    if koguchi_type == 'left':
        end_indices = [0]
    elif koguchi_type == 'right':
        end_indices = [n_sec - 1]
    else:  # both
        end_indices = [0] if n_sec == 1 else [0, n_sec - 1]

    primary_ft = input_data.get('foundation_type', 'direct')

    # 小口止ごとに、その測点自身の基礎形式（区間対応済み）で計算方法を選ぶ
    # （左右で基礎形式が異なる場合、プロジェクト全体の代表値では決め打ちしない）
    danmen_msp = None
    danmen_load_failed = False
    def _get_danmen_msp():
        nonlocal danmen_msp, danmen_load_failed
        if danmen_msp is None and not danmen_load_failed:
            danmen_path = os.path.join(output_dir, 'danmen.dxf')
            if os.path.exists(danmen_path):
                danmen_msp = ezdxf.readfile(danmen_path).modelspace()
            else:
                danmen_load_failed = True
        return danmen_msp

    rows = []
    for sec_i in end_indices:
        sec = sections[sec_i]
        ft  = sec.get('foundation_type') or primary_ft
        pe_bk_pts = None
        if ft == 'rock':
            msp_ = _get_danmen_msp()
            if msp_ is None:
                print("    [エラー] danmen.dxf が見つかりません（岩着基礎のぺーライン背面抽出に必要）。")
                return
            sec_entities = _section_entities(msp_, sec['offset_x'])
            pe_bk_pts = _foundation_pe_bk_points(sec_entities)
        q = koguchi_quantities(sec['points'], sec['offset_x'], ft, pe_bk_pts)
        rows.append((sec['point_name'], q))

    total_concrete  = _r3(sum(q['concrete_m3']  for _, q in rows))
    total_kata_waku = _r3(sum(q['kata_waku_m2'] for _, q in rows))
    total_d13_kg    = _r3(sum(q['d13_kg']       for _, q in rows))

    SEP  = "=" * 56
    SEP2 = "-" * 56

    out_lines = [
        SEP,
        "    小口止コンクリート  数量計算書",
        SEP,
    ]

    for name, q in rows:
        out_lines.append("")
        out_lines.extend(fmt_koguchi_block(name, q))
        out_lines.append(SEP2)

    out_lines += [
        "",
        f"  * 合　計（小口止コンクリート × {len(rows)} 箇所）",
        f"    コンクリート : {total_concrete:.3f} m^3",
        f"    型枠         : {total_kata_waku:.3f} m^2",
        f"    D13鉄筋      : {total_d13_kg:.3f} kg",
        SEP,
    ]

    text = "\n".join(out_lines)
    print(text)

    out_path = os.path.join(output_dir, 'suryou_koguchi.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"\n    生成成功: suryou_koguchi.txt")

    write_koguchi_dxf_text(output_dir, rows)

if __name__ == "__main__":
    main(".")
