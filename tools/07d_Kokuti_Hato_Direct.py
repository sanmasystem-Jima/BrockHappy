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


def draw(output_dir, scale=50, indices_override=None, start_draw_i=0, save=True, **kwargs):
    input_data  = load_json(os.path.join(output_dir, 'input.json'))
    danmen_data = load_json(os.path.join(output_dir, 'danmen_data.json'))
    if not all([input_data, danmen_data]):
        print("    [エラー] 必要なJSONファイルが揃っていません。")
        return

    sections = danmen_data['sections']
    n_sec    = len(sections)
    if indices_override is not None:
        indices = indices_override
    else:
        koguchi_type = input_data.get('koguchi_type', 'both')
        if koguchi_type == 'both':
            indices = [0, n_sec - 1] if n_sec > 1 else [0]
        elif koguchi_type == 'left':
            indices = [0]
        elif koguchi_type == 'right':
            indices = [n_sec - 1]
        else:
            print("    [スキップ] 小口止コンクリートなし")
            return

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
            'dimtad': 1,                   # 文字を寸法線の上に配置
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
        px  = (start_draw_i + draw_i) * SEC_SPACING

        def lp(key):
            p = pts[key]
            return (p[0] - ox + px, p[1])

        # 前面参照線（-ox のみ、後で +px を加算）
        blk_btm_local = (pts['block_btm_front'][0] - ox, pts['block_btm_front'][1])
        tbtm_local    = (pts['tenba_btm_front'][0]  - ox, pts['tenba_btm_front'][1])

        # 背面折れ線（exc_top[1] == tenba_top_front[1] = y_top）
        exc_btm        = lp('exc_bottom')
        exc_mid_btm    = lp('exc_mid_bottom')
        exc_mid_top_pt = lp('exc_mid_top')
        exc_top_pt     = lp('exc_top')

        backfill_y = exc_mid_btm[1]

        y_top     = pts['tenba_top_front'][1]
        y_blk_top = pts['tenba_btm_front'][1]
        y_bottom  = pts['kiso_btm_front'][1]

        # 6頂点
        c1 = (_x_at_y(blk_btm_local, tbtm_local, y_top)    + px, y_top)
        c2 = (_x_at_y(blk_btm_local, tbtm_local, y_bottom) + px, y_bottom)
        c3 = exc_btm
        c4 = exc_mid_btm
        c5 = exc_mid_top_pt
        c6 = exc_top_pt

        corners    = [c1, c2, c3, c4, c5, c6]
        y_rect_top = y_top
        change_ys  = [y_blk_top]

        # 寸法線（縦・横）に使う変化点：08の数量計算は backfill_y（背面の段差）で分割している
        # （y_blk_top は前面のみの目印で幅は変化しないため寸法線には使わない）
        dim_change_ys = [backfill_y]

        def x_r(y):
            if y <= backfill_y:
                return _x_at_y(exc_btm, exc_mid_btm, y)
            else:
                return _x_at_y(exc_mid_top_pt, exc_top_pt, y)

        def back_line(y):
            if y <= backfill_y:
                return exc_btm, exc_mid_btm
            else:
                return exc_mid_top_pt, exc_top_pt

        def sec_bnd(y_a, y_b):
            v = []
            if y_b < backfill_y < y_a:
                v += [(exc_mid_top_pt[0], backfill_y),
                      (exc_mid_btm[0],    backfill_y)]
            return v

        # 外周ポリゴン
        msp.add_lwpolyline(corners, close=True, dxfattribs=la)

        # 打継目（側面図）
        joint_ys = []
        h_total  = y_top - y_bottom
        n_divs   = math.ceil(h_total / 1500)
        if n_divs > 1:
            h_each = h_total / n_divs
            for k in range(1, n_divs):
                yj  = y_top - h_each * k
                x_l = _x_at_y(c1, c2, yj)
                msp.add_line((x_l, yj), (x_r(yj), yj), dxfattribs=la_jt)
                joint_ys.append(yj)

        # 差筋
        dx_f = c1[0] - c2[0]; dy_f = c1[1] - c2[1]
        lf_  = math.sqrt(dx_f**2 + dy_f**2)
        fd   = (dx_f / lf_, dy_f / lf_)
        fn   = (dy_f / lf_, -dx_f / lf_)

        for yj in joint_ys:
            xw_f = _x_at_y(c1, c2, yj)
            cx_f = xw_f + 200 / fn[0]
            msp.add_line((cx_f - 300*fd[0], yj - 300*fd[1]),
                         (cx_f + 300*fd[0], yj + 300*fd[1]), dxfattribs=la_rb)

            p1b, p2b = back_line(yj)
            dx_e = p2b[0] - p1b[0]; dy_e = p2b[1] - p1b[1]
            le_  = math.sqrt(dx_e**2 + dy_e**2)
            ed   = (dx_e / le_, dy_e / le_)
            en   = (-dy_e / le_, dx_e / le_)
            xw_e = _x_at_y(p1b, p2b, yj)
            cx_e = xw_e + 200 / en[0]
            msp.add_line((cx_e - 300*ed[0], yj - 300*ed[1]),
                         (cx_e + 300*ed[0], yj + 300*ed[1]), dxfattribs=la_rb)

        # 正面図
        right_x = max(p[0] for p in corners)
        fp  = right_x + VIEW_GAP
        kw  = 300.0

        msp.add_line((fp,      y_rect_top), (fp + kw, y_rect_top), dxfattribs=la)
        msp.add_line((fp,      y_bottom),   (fp + kw, y_bottom),   dxfattribs=la)
        msp.add_line((fp,      y_rect_top), (fp,      y_bottom),   dxfattribs=la)
        msp.add_line((fp + kw, y_rect_top), (fp + kw, y_bottom),   dxfattribs=la)

        for yj in joint_ys:
            msp.add_line((fp, yj), (fp + kw, yj), dxfattribs=la_jt)

        for y_chg in change_ys:
            if y_bottom < y_chg < y_rect_top:
                msp.add_line((fp, y_chg), (fp + kw, y_chg), dxfattribs=la)

        # 水平鉄筋（Shoelace重心）
        def poly_centroid(verts):
            nv = len(verts)
            Av = 0.0; cx_ = 0.0; cy_ = 0.0
            for j in range(nv):
                xi, yi = verts[j]; xj, yj_c = verts[(j + 1) % nv]
                c = xi * yj_c - xj * yi
                Av += c; cx_ += (xi + xj) * c; cy_ += (yi + yj_c) * c
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

        cx_front   = fp + kw if draw_i == 0 else fp
        boundaries = [y_top] + joint_ys + [y_bottom]
        for k in range(len(boundaries) - 1):
            y_a, y_b = boundaries[k], boundaries[k + 1]
            gcx, gcy = poly_centroid(sec_pts(y_a, y_b))
            msp.add_circle((gcx, gcy), 15, dxfattribs=la_rb)
            msp.add_line((cx_front - 150, gcy), (cx_front + 150, gcy), dxfattribs=la_rb)

        # ── 寸法線 ─────────────────────────────────────────────────
        la_dim     = {'layer': 'KOGUCHI_DIM'}
        left_x     = min(p[0] for p in corners)
        dim_objs   = []
        v_dim_objs = []

        # 縦寸法（側面図左側）
        v_bnds = [y_rect_top] + sorted(
            [y for y in dim_change_ys if y_bottom < y < y_rect_top], reverse=True
        ) + [y_bottom]
        for _k in range(len(v_bnds) - 1):
            ya, yb = v_bnds[_k], v_bnds[_k + 1]
            d = msp.add_linear_dim(
                base=(left_x - DIM_OFFSET_V, (ya + yb) / 2),
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
            [y for y in dim_change_ys if y_bottom < y < y_rect_top], reverse=True
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

        title_h  = 7.0 * scale
        sub_h    = 5.0 * scale
        gap      = 2.0 * scale
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

    if save:
        doc.saveas(os.path.join(output_dir, 'koguchi.dxf'))
        print("    生成成功: koguchi.dxf")
    return doc


if __name__ == "__main__":
    draw(".")
