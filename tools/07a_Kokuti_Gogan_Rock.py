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


def _x_at_y(p1, p2, y):
    x1, y1 = p1; x2, y2 = p2
    if abs(y2 - y1) < 1e-9:
        return x1
    return x1 + (y - y1) / (y2 - y1) * (x2 - x1)


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


def _fix_text_left(doc, dim_list):
    """render()済み垂直寸法のテキストを寸法線の左側へ強制移動。"""
    for dim in dim_list:
        try:
            blk_name = dim.dimension.dxf.geometry
        except Exception:
            continue
        if blk_name not in doc.blocks:
            continue
        blk = doc.blocks[blk_name]

        arrow_pos = [(e.dxf.insert.x, e.dxf.insert.y)
                     for e in blk if e.dxftype() == "INSERT"]
        if len(arrow_pos) < 2:
            continue
        dim_coord = arrow_pos[0][0]   # 垂直寸法: 矢印x = 寸法線x

        for e in blk:
            if e.dxftype() != "MTEXT":
                continue
            pos = e.dxf.insert
            if pos.x > dim_coord:     # テキストが右側にいたら左へ反転
                e.dxf.insert = (2 * dim_coord - pos.x, pos.y, 0)


def _fix_arrows_outward(doc, dim_list, asz):
    """render()済み寸法ブロックの矢印を外向きに統一する。
    render()は寸法線の長さに応じて矢印を内向き/外向きどちらにするか自動判定するため、
    無条件に180度反転すると「すでに外向き」のケースが内向きに戻ってしまう
    （直したつもりが別のケースを壊す）。矢印の現在の向き（テール方向）を実際に
    判定し、内向きの場合のみ反転する。
    """
    import math
    for dim in dim_list:
        try:
            blk_name = dim.dimension.dxf.geometry
        except Exception:
            continue
        if blk_name not in doc.blocks:
            continue
        blk = doc.blocks[blk_name]

        arrows = [e for e in blk if e.dxftype() == "INSERT"]
        if len(arrows) < 2:
            continue
        arrow_pos = [(e.dxf.insert.x, e.dxf.insert.y) for e in arrows]

        (ax1, ay1), (ax2, ay2) = arrow_pos[0], arrow_pos[1]
        is_v = abs(ax1 - ax2) < 0.01

        # 矢印ブロックはローカル座標で先端が原点(0,0)、根元(テール)が-X方向にある前提
        # （ezdxf標準矢印 "_CLOSEDFILLED" 等）。テールが相手の矢印側を向いていれば
        # 先端は外側を向いている＝既に外向き。逆ならテールが外を向いている＝内向き。
        for i, e in enumerate(arrows):
            ax, ay = arrow_pos[i]
            ox, oy = arrow_pos[1 - i]
            rot = math.radians(e.dxf.rotation)
            tail_dir = (-math.cos(rot), -math.sin(rot))
            to_other = (ox - ax, oy - ay)
            dot = tail_dir[0] * to_other[0] + tail_dir[1] * to_other[1]
            if dot < 0:
                e.dxf.rotation = (e.dxf.rotation + 180.0) % 360.0

        for e in blk:
            if e.dxftype() != "LINE":
                continue
            s  = e.dxf.start
            en = e.dxf.end
            if is_v and abs(s.x - en.x) > 0.001:
                continue
            if not is_v and abs(s.y - en.y) > 0.001:
                continue
            for arr_x, arr_y in arrow_pos:
                if ((s.x - arr_x) ** 2 + (s.y - arr_y) ** 2) ** 0.5 < asz * 2.5:
                    e.dxf.start = (arr_x, arr_y, 0)
                if ((en.x - arr_x) ** 2 + (en.y - arr_y) ** 2) ** 0.5 < asz * 2.5:
                    e.dxf.end   = (arr_x, arr_y, 0)


def _foundation_pe_bk_points(entities):
    """セクション内の05_Foundationレイヤの3本目のポリライン（ペーライン背面）の頂点を取得する。
    05_Brock_Danmen.py の描画順（ume, pe_bot, pe_bk）に依存。
    """
    polys = [e for e in entities if e.dxftype() == 'LWPOLYLINE' and e.dxf.layer == '05_Foundation']
    if len(polys) < 3:
        return None
    return [(p[0], p[1]) for p in polys[2].get_points('xy')]


def draw(output_dir, scale=50, **kwargs):
    input_data  = load_json(os.path.join(output_dir, 'input.json'))
    danmen_data = load_json(os.path.join(output_dir, 'danmen_data.json'))
    kiso_data   = load_json(os.path.join(output_dir, 'kiso_data.json'))
    if not all([input_data, danmen_data, kiso_data]):
        print("    [エラー] 必要なJSONファイルが揃っていません。")
        return

    danmen_msp = ezdxf.readfile(os.path.join(output_dir, 'danmen.dxf')).modelspace()

    sections     = danmen_data['sections']
    n            = len(sections)
    koguchi_type = input_data.get('koguchi_type', 'both')
    if koguchi_type == 'both':
        indices = [0, n - 1] if n > 1 else [0]
    elif koguchi_type == 'left':
        indices = [0]
    elif koguchi_type == 'right':
        indices = [n - 1]
    else:
        print("    [スキップ] 小口止コンクリートなし")
        return

    has_tc = input_data.get('has_tenba_con', 'n') == 'y'
    has_gr = input_data.get('has_gr_kiso') == 'y'

    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4
    msp = doc.modelspace()
    for lname, color in [('DANMEN_REF', 7), ('KOGUCHI_FRONT', 1)]:
        if lname not in {l.dxf.name for l in doc.layers}:
            doc.layers.new(lname, dxfattribs={'color': color})

    if 'DASHED' not in {lt.dxf.name for lt in doc.linetypes}:
        doc.linetypes.add('DASHED', pattern=[375, 250, -125])

    if 'KOGUCHI_DIM' not in {l.dxf.name for l in doc.layers}:
        doc.layers.new('KOGUCHI_DIM', dxfattribs={'color': 7})
    if 'KOGUCHI_DIM_STYLE' not in {ds.dxf.name for ds in doc.dimstyles}:
        doc.dimstyles.new('KOGUCHI_DIM_STYLE', dxfattribs={
            'dimasz': 2.5 * float(scale), 'dimtxt': 3.5 * float(scale), 'dimdec': 0,
            'dimexo': 1.0 * float(scale), 'dimexe': 1.5 * float(scale),
            'dimtad': 1,                 # 文字を寸法線の上に配置
            'dimgap': 1.0 * float(scale),  # 線から1mm（図上）離す
            'dimlwd': 13, 'dimlwe': 13,
            'dimblk': 'OPEN',
            'dimclrd': 7, 'dimclre': 7, 'dimclrt': 7,
        })

    la    = {'layer': 'DANMEN_REF',    'color': 7, 'lineweight': 35}
    la_jt = {'layer': 'KOGUCHI_FRONT', 'color': 1, 'linetype': 'DASHED', 'lineweight': 13}
    la_rb = {'layer': 'KOGUCHI_FRONT', 'color': 1, 'lineweight': 35}

    SEC_SPACING  = 20000.0
    DIM_OFFSET_H = 10.0 * float(scale)   # 水平寸法線：計測位置からの間隔（図上10mm）
    DIM_OFFSET_V = 15.0 * float(scale)   # 垂直寸法線：計測位置からの間隔（図上15mm）
    VIEW_GAP    = 30.0 * float(scale)   # 側面図と正面図の間隔（図上30mm）

    for draw_i, sec_i in enumerate(indices):
        sec = sections[sec_i]
        pts = sec['points']
        ox  = sec['offset_x']
        px  = draw_i * SEC_SPACING

        def lp(key):
            p = pts[key]
            return (p[0] - ox + px, p[1])

        # danmen.dxf からこの測点のエンティティを抽出（断面図コピー・ペーライン背面の抽出で共用）
        sec_entities = _section_entities(danmen_msp, sec['offset_x'])

        # 裏砕石下面 y（backfill_y）
        backfill_y = pts['saiseki_btm_front'][1]

        # ペーライン背面 2 点（danmen.dxf の 05_Foundation ポリラインから直接抽出）
        pe_bk_pts = _foundation_pe_bk_points(sec_entities)
        if pe_bk_pts is None:
            print("    [エラー] danmen.dxf からペーライン背面形状を抽出できません。")
            return
        pe_bk3 = (pe_bk_pts[3][0] - ox + px, pe_bk_pts[3][1])
        pe_bk2 = (pe_bk_pts[2][0] - ox + px, pe_bk_pts[2][1])

        # 共通頂点
        exc_btm = lp('exc_bottom')
        exc_top = lp('exc_top')
        c2 = lp('block_btm_front')
        c3 = pe_bk3
        c4 = pe_bk2
        c5 = lp('exc_bottom')

        if has_tc:
            tenba_top_y = pts['tenba_top_front'][1]
            y_blk_top   = pts['tenba_btm_front'][1]

            if has_gr:
                # ── GR基礎：小口止ポリゴン = ブロック本体のみ ──────
                c1  = lp('tenba_btm_front')
                c6  = (_x_at_y(exc_btm, exc_top, y_blk_top), y_blk_top)
                corners    = [c1, c2, c3, c4, c5, c6]
                y_top      = y_blk_top   # 打継目・重心計算の起点をブロック上面に
                y_rect_top = y_blk_top
                change_ys  = [backfill_y]

                # GR基礎・モルタル・基礎コンを小口止の上に描画
                n_slope  = input_data['front_slope']
                gr_h     = input_data['gr_height_m']     * 1000
                gr_bw    = input_data['gr_base_width_m'] * 1000
                mortar_h = input_data['gr_mortar_m']     * 1000
                kiso_h   = input_data['gr_kiso_con_m']   * 1000

                def sg(x, y):
                    return (x + px, y)

                gr_poly = [
                    sg(0,           0),
                    sg(400,         0),
                    sg(400,         -(gr_h - 100)),
                    sg(gr_bw - 100, -(gr_h - 100)),
                    sg(gr_bw - 100, -gr_h),
                    sg(-100,        -gr_h),
                    sg(-100,        -(gr_h - 100)),
                    sg(0,           -(gr_h - 100)),
                ]
                msp.add_lwpolyline(gr_poly, close=True,
                                   dxfattribs={'layer': 'DANMEN_REF', 'color': 3, 'lineweight': 35})

                x_face_gr = n_slope * (-gr_h)
                if x_face_gr < -100:
                    msp.add_line(sg(-100, -gr_h), sg(x_face_gr, -gr_h),
                                 dxfattribs={'layer': 'DANMEN_REF', 'color': 3, 'lineweight': 35})

                mt_y1, mt_y2 = -gr_h, -(gr_h + mortar_h)
                mt_poly = [sg(n_slope * mt_y1, mt_y1), sg(gr_bw, mt_y1),
                           sg(gr_bw, mt_y2),            sg(n_slope * mt_y2, mt_y2)]
                msp.add_lwpolyline(mt_poly, close=True,
                                   dxfattribs={'layer': 'DANMEN_REF', 'color': 4, 'lineweight': 35})

                kc_y1, kc_y2 = -(gr_h + mortar_h), -(gr_h + mortar_h + kiso_h)
                kc_poly = [sg(n_slope * kc_y1, kc_y1), sg(gr_bw, kc_y1),
                           sg(gr_bw, kc_y2),            sg(n_slope * kc_y2, kc_y2)]
                msp.add_lwpolyline(kc_poly, close=True,
                                   dxfattribs={'layer': 'DANMEN_REF', 'color': 5, 'lineweight': 35})

            else:
                # ── 普通天端コンあり：6頂点 ──────────────────────
                c1  = lp('tenba_top_front')
                c6  = (_x_at_y(exc_btm, exc_top, tenba_top_y), tenba_top_y)
                corners    = [c1, c2, c3, c4, c5, c6]
                y_top      = y_blk_top               # ブロック上面（打継目用）
                y_rect_top = tenba_top_y              # 正面図矩形上辺
                change_ys  = [backfill_y]

            def x_r(y):
                if y > backfill_y: return _x_at_y(exc_btm, exc_top, y)
                else:              return _x_at_y(c3, c4, y)

            def back_line(y):
                if y > backfill_y: return exc_btm, exc_top
                else:              return c3, c4

            def sec_bnd(y_a, y_b):
                v = []
                if y_b < backfill_y < y_a:
                    v += [(_x_at_y(exc_btm, exc_top, backfill_y), backfill_y),
                          (_x_at_y(c3, c4, backfill_y), backfill_y)]
                return v

        else:
            # ── 天端コンなし：8頂点 ──────────────────────
            saiseki_top_y = pts['saiseki_top_front'][1]
            ura_btm = lp('uracon_btm_back')
            ura_top = lp('tenba_btm_back')
            c1 = lp('tenba_btm_front')
            c6 = (_x_at_y(exc_btm, exc_top, saiseki_top_y), saiseki_top_y)
            c7 = (_x_at_y(ura_btm, ura_top, saiseki_top_y), saiseki_top_y)
            c8 = lp('tenba_btm_back')
            corners    = [c1, c2, c3, c4, c5, c6, c7, c8]
            y_top      = c1[1]
            y_rect_top = y_top
            change_ys  = [saiseki_top_y, backfill_y]

            def x_r(y):
                if y > saiseki_top_y:  return _x_at_y(ura_btm, ura_top, y)
                elif y > backfill_y:   return _x_at_y(exc_btm, exc_top, y)
                else:                  return _x_at_y(c3, c4, y)

            def back_line(y):
                if y > saiseki_top_y:  return ura_btm, ura_top
                elif y > backfill_y:   return exc_btm, exc_top
                else:                  return c3, c4

            def sec_bnd(y_a, y_b):
                v = []
                for y_c in sorted([saiseki_top_y, backfill_y], reverse=True):
                    if y_b < y_c < y_a:
                        if y_c == saiseki_top_y:
                            v += [(_x_at_y(ura_btm, ura_top, y_c), y_c),
                                  (_x_at_y(exc_btm, exc_top, y_c), y_c)]
                        else:
                            v += [(_x_at_y(exc_btm, exc_top, y_c), y_c),
                                  (_x_at_y(c3, c4, y_c), y_c)]
                return v

        y_bottom = c2[1]

        # 外周ポリゴンを描画
        msp.add_lwpolyline(corners, close=True, dxfattribs=la)

        # 打継目（側面図）
        joint_ys = []
        h_total  = y_top - y_bottom
        n_divs   = math.ceil(h_total / 1500)
        if n_divs > 1:
            h_each = h_total / n_divs
            for i in range(1, n_divs):
                yj  = y_top - h_each * i
                x_l = _x_at_y(c1, c2, yj)
                msp.add_line((x_l, yj), (x_r(yj), yj), dxfattribs=la_jt)
                joint_ys.append(yj)

        # 縦鉄筋（差筋：打継目ごとに前後壁面から125mm内側・壁面平行・600mm）
        dx_f = c1[0] - c2[0]; dy_f = c1[1] - c2[1]
        lf_  = math.sqrt(dx_f**2 + dy_f**2)
        fd   = (dx_f / lf_, dy_f / lf_)
        fn   = (dy_f / lf_, -dx_f / lf_)

        for yj in joint_ys:
            xw_f = _x_at_y(c1, c2, yj)
            cx_f = xw_f + 125 / fn[0]
            msp.add_line((cx_f - 300*fd[0], yj - 300*fd[1]),
                         (cx_f + 300*fd[0], yj + 300*fd[1]), dxfattribs=la_rb)
            p1b, p2b = back_line(yj)
            dx_e = p2b[0] - p1b[0]; dy_e = p2b[1] - p1b[1]
            le_  = math.sqrt(dx_e**2 + dy_e**2)
            ed   = (dx_e / le_, dy_e / le_)
            en   = (-dy_e / le_, dx_e / le_)
            xw_e = _x_at_y(p1b, p2b, yj)
            cx_e = xw_e + 125 / en[0]
            msp.add_line((cx_e - 300*ed[0], yj - 300*ed[1]),
                         (cx_e + 300*ed[0], yj + 300*ed[1]), dxfattribs=la_rb)

        # 正面図（側面図右端から 5000mm 右）
        right_x = max(p[0] for p in corners)
        fp  = right_x + VIEW_GAP
        kw  = 300.0

        msp.add_line((fp,      y_rect_top), (fp + kw, y_rect_top), dxfattribs=la)
        msp.add_line((fp,      y_bottom),   (fp + kw, y_bottom),   dxfattribs=la)
        msp.add_line((fp,      y_rect_top), (fp,      y_bottom),   dxfattribs=la)
        msp.add_line((fp + kw, y_rect_top), (fp + kw, y_bottom),   dxfattribs=la)

        if has_tc and not has_gr:
            # 天端コン下端（ブロック上面）境界線
            msp.add_line((fp, y_top), (fp + kw, y_top), dxfattribs=la)

        for yj in joint_ys:
            msp.add_line((fp, yj), (fp + kw, yj), dxfattribs=la_jt)

        # 背面の変化点
        for y_chg in change_ys:
            if y_bottom < y_chg < y_top:
                msp.add_line((fp, y_chg), (fp + kw, y_chg), dxfattribs=la)

        # ブロック下部突出の投影線（縦2本・横1本）
        y_proj = c3[1]
        msp.add_line((fp,      y_bottom), (fp,      y_proj), dxfattribs=la)
        msp.add_line((fp + kw, y_bottom), (fp + kw, y_proj), dxfattribs=la)
        msp.add_line((fp,      y_proj),   (fp + kw, y_proj), dxfattribs=la)

        # 重心算出（Shoelace公式）
        def poly_centroid(verts):
            nv = len(verts)
            Av = 0.0; cx_ = 0.0; cy_ = 0.0
            for i in range(nv):
                xi, yi = verts[i]; xj, yj = verts[(i + 1) % nv]
                c = xi * yj - xj * yi
                Av += c; cx_ += (xi + xj) * c; cy_ += (yi + yj) * c
            Av /= 2.0
            if abs(Av) < 1e-9:
                return sum(p[0] for p in verts) / nv, sum(p[1] for p in verts) / nv
            return cx_ / (6 * Av), cy_ / (6 * Av)

        def sec_pts(y_a, y_b):
            def xl(y): return _x_at_y(c1, c2, y)
            v = [(xl(y_a), y_a), (x_r(y_a), y_a)]
            v += sec_bnd(y_a, y_b)
            v += [(x_r(y_b), y_b), (xl(y_b), y_b)]
            return v

        # 鉄筋（側面図：重心に直径30mm円、立面図：重心yに300mm線）
        cx_front   = fp + kw if draw_i == 0 else fp
        boundaries = [y_top] + joint_ys + [y_bottom]
        for i in range(len(boundaries) - 1):
            y_a, y_b = boundaries[i], boundaries[i + 1]
            gcx, gcy = poly_centroid(sec_pts(y_a, y_b))
            msp.add_circle((gcx, gcy), 15, dxfattribs=la_rb)
            msp.add_line((cx_front - 150, gcy), (cx_front + 150, gcy), dxfattribs=la_rb)

        # ── 寸法線 ─────────────────────────────────────────────────
        la_dim     = {'layer': 'KOGUCHI_DIM'}
        left_x     = min(p[0] for p in corners)
        dim_objs   = []
        v_dim_objs = []

        # 縦寸法（側面図左側）：ぺーライン先端（c3、突出部0.149m分）まで延長
        v_bnds = [y_rect_top] + sorted(
            [y for y in change_ys if y_bottom < y < y_rect_top], reverse=True
        ) + [y_bottom, c3[1]]

        # GR基礎のときはGR形状に当たるため、右上へ図上1.5cm退避させる
        # （angle=90の縦寸法はbaseのx成分のみが表示位置に効くため、勾配比で薄めず
        #   x・yともにフルで15mm相当を加える）
        v_shift = (0.0, 0.0)
        if has_gr:
            v_shift = (15.0 * scale, 15.0 * scale)

        for _k in range(len(v_bnds) - 1):
            ya, yb = v_bnds[_k], v_bnds[_k + 1]
            d = msp.add_linear_dim(
                base=(left_x - DIM_OFFSET_V + v_shift[0], (ya + yb) / 2 + v_shift[1]),
                p1=(left_x, ya), p2=(left_x, yb),
                angle=90, dimstyle='KOGUCHI_DIM_STYLE',
                dxfattribs=la_dim
            )
            d.render()
            dim_objs.append(d)
            v_dim_objs.append(d)

        # 横寸法（正面図右側）
        h_items = [(y_rect_top, 1)]
        for y_chg in sorted(
            [y for y in change_ys if y_bottom < y < y_rect_top], reverse=True
        ):
            h_items.append((y_chg + 10, 1))
            h_items.append((y_chg - 10, -1))
        h_items.append((y_bottom, -1))

        for y_lv, sgn in h_items:
            x_left = _x_at_y(c1, c2, y_lv)
            x_back = x_r(y_lv)
            d = msp.add_linear_dim(
                base=((x_left + x_back) / 2, y_lv + sgn * DIM_OFFSET_H),
                p1=(x_left, y_lv), p2=(x_back, y_lv),
                angle=0, dimstyle='KOGUCHI_DIM_STYLE',
                dxfattribs=la_dim
            )
            d.render()
            dim_objs.append(d)

        # 正面図の高さ・幅 寸法線
        d = msp.add_linear_dim(
            base=(fp - DIM_OFFSET_V, (y_rect_top + y_bottom) / 2),
            p1=(fp, y_rect_top), p2=(fp, y_bottom),
            angle=90, dimstyle='KOGUCHI_DIM_STYLE',
            dxfattribs=la_dim
        )
        d.render()
        dim_objs.append(d)
        v_dim_objs.append(d)

        d = msp.add_linear_dim(
            base=((fp + fp + kw) / 2, y_rect_top + DIM_OFFSET_H),
            p1=(fp, y_rect_top), p2=(fp + kw, y_rect_top),
            angle=0, dimstyle='KOGUCHI_DIM_STYLE',
            dxfattribs=la_dim
        )
        d.render()
        dim_objs.append(d)

        # 矢印を外向きに統一・縦寸法の文字を左側に統一（render後でないと反映できない）
        _fix_arrows_outward(doc, dim_objs, doc.dimstyles.get('KOGUCHI_DIM_STYLE').dxf.dimasz)
        _fix_text_left(doc, v_dim_objs)

        # ── 表題（小口止コンクリート・縮尺・測点） ──────────────────
        this_bbs = []
        for e in msp:
            bb = bbox.extents([e], fast=True)
            if not bb.has_data:
                continue
            cx = (bb.extmin.x + bb.extmax.x) / 2
            if abs(cx - px) < SEC_SPACING / 2:
                this_bbs.append(bb)
        max_y    = max(b.extmax.y for b in this_bbs)
        min_x    = min(b.extmin.x for b in this_bbs)
        max_x    = max(b.extmax.x for b in this_bbs)
        center_x = (min_x + max_x) / 2

        title_h = 7.0 * scale
        sub_h   = 5.0 * scale
        gap     = 2.0 * scale
        line_gap = 1.5 * scale

        y_point_txt = max_y + gap
        y_scale_txt = y_point_txt + sub_h + line_gap
        y_title_txt = y_scale_txt + sub_h + line_gap

        for text, height, y_pos in [
            (f"測点 {sec['point_name']}", sub_h,   y_point_txt),
            (f"S=1/{int(scale)}",         sub_h,   y_scale_txt),
            ("小口止コンクリート",          title_h, y_title_txt),
        ]:
            t = msp.add_text(text, dxfattribs={'height': height, 'layer': '00_Text'})
            t.dxf.insert      = (center_x, y_pos)
            t.dxf.halign      = 1
            t.dxf.align_point = (center_x, y_pos)

    doc.saveas(os.path.join(output_dir, 'koguchi.dxf'))
    print("    生成成功: koguchi.dxf")


if __name__ == "__main__":
    draw(".")
