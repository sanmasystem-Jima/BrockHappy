import json
import math
import os
import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.render import arrows as ezdxf_arrows
from ezdxf.enums import TextEntityAlignment


def _exo_to(measure_coord, edge, gap=3.0, outward=1):
    """構造物のバウンディングボックス端(edge)から gap(mm) 離れた位置から
    引出線が始まるよう、必要なdimexo（測定点からのオフセット量）を返す。
    outward=+1: edgeはbboxの最大値側（測定点より大きい方向に伸びる）
    outward=-1: edgeはbboxの最小値側（測定点より小さい方向に伸びる）
    """
    if outward > 0:
        return (edge + gap) - measure_coord
    return measure_coord - (edge - gap)


def _fix_arrows_outward(doc, dim_list, asz):
    """render()済み寸法ブロックの矢印を外向きに統一する。
    測定距離が 2*asz+dimgap 未満（ezdxfが自動的に矢印を寸法線の外側に
    配置する「outside」レイアウト）の場合は、ezdxfのデフォルトが既に
    正しい外向き表示になっているため何もしない（無理に反転すると
    矢印同士が重なって壊れる）。それ以外は現在の向きを判定し、
    内向きの場合のみ反転する。
    """
    for dim in dim_list:
        try:
            blk_name = dim.dimension.dxf.geometry
            dimgap = doc.dimstyles.get(dim.dimension.dxf.dimstyle).dxf.dimgap
        except Exception:
            continue
        if blk_name not in doc.blocks:
            continue
        blk = doc.blocks[blk_name]

        arrows = [e for e in blk if e.dxftype() == "INSERT"]
        if len(arrows) < 2:
            continue
        arrow_pos = [(e.dxf.insert.x, e.dxf.insert.y) for e in arrows]

        raw_measurement = math.hypot(
            arrow_pos[1][0] - arrow_pos[0][0], arrow_pos[1][1] - arrow_pos[0][1]
        )
        if (2 * asz + dimgap) > raw_measurement:
            continue  # ezdxfが外側配置を選択済み（既に正しい）

        for i, e in enumerate(arrows):
            ax, ay = arrow_pos[i]
            ox, oy = arrow_pos[1 - i]
            rot = math.radians(e.dxf.rotation)
            tail_dir = (-math.cos(rot), -math.sin(rot))
            to_other = (ox - ax, oy - ay)
            dot = tail_dir[0] * to_other[0] + tail_dir[1] * to_other[1]
            if dot < 0:
                e.dxf.rotation = (e.dxf.rotation + 180.0) % 360.0


def generate_tenba_dxf(json_filepath, dxf_filename, output_json, scale_input=10.0):
    try:
        with open(json_filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"【エラー】: {json_filepath} が見つかりません。")
        return

    if data.get("has_tenba_con") != "y":
        print("    天端コンクリートなし → スキップ")
        with open(output_json, 'w', encoding='utf-8') as jf:
            json.dump({
                "points": [
                    {"name": "front_top",    "x": 0.0, "y": 0.0},
                    {"name": "back_top",     "x": 0.0, "y": 0.0},
                    {"name": "back_bottom",  "x": 0.0, "y": 0.0},
                    {"name": "front_bottom", "x": 0.0, "y": 0.0}
                ]
            }, jf, indent=2, ensure_ascii=False)
        return

    scale = 1.0 / scale_input

    to_mm         = 1000.0
    h             = data["tenba_con_height"] * to_mm
    slope         = data["front_slope"]
    block_hikae   = data["block_hikae"]   * to_mm
    ura_con       = data["ura_con_thickness"] * to_mm
    struct_type   = data.get("structure_type", "road")

    # ① 天端幅計算：（控え厚＋裏コン厚＋300mm）×勾配伸び率
    k_front = math.sqrt(1 + slope**2)
    w_top   = (block_hikae + ura_con + 300.0) * k_front

    # ガードレール基礎判定
    is_guardrail = data.get("has_gr_kiso") == "y"
    if is_guardrail:
        gr_h     = data["gr_height_m"]     * to_mm
        gr_bw    = data["gr_base_width_m"] * to_mm
        mortar_h = data["gr_mortar_m"]     * to_mm
        kiso_h   = data["gr_kiso_con_m"]   * to_mm

    # 断面座標（実寸mm）
    # 基準点：前面上側 (0,0)
    p1_real = (0.0,   0.0)
    p2_real = (w_top, 0.0)
    p3_real = (w_top, -h)
    p4_real = (-h * slope, -h)
    real_coords = [p1_real, p2_real, p3_real, p4_real]

    # 数量計算
    # 断面積（台形）
    w_bottom = w_top + h * slope   # 下面幅
    area_m2  = (w_top + w_bottom) / 2 * h / (to_mm**2)  # m²

    conc_m3      = round(area_m2 * 10.0, 2)   # m³/10m
    # 型枠：前面（斜め）+ 背面（垂直）+ 両端なし → 前面法長 + 背面高さ
    front_len_m  = math.sqrt((h * slope)**2 + h**2) / to_mm
    back_len_m   = h / to_mm
    kata_m2_val  = round((front_len_m + back_len_m) * 10.0, 2)  # m²/10m

    # ガードレール基礎数量（モルタル・基礎コンは台形断面の平均幅で計算）
    if is_guardrail:
        gr_m         = round(10.0, 2)
        mortar_avg_w = gr_bw + slope * (gr_h + mortar_h / 2)
        kiso_avg_w   = gr_bw + slope * (gr_h + mortar_h + kiso_h / 2)
        mortar_m3    = round(mortar_avg_w / to_mm * mortar_h / to_mm * 10.0, 2)
        kiso_m3      = round(kiso_avg_w   / to_mm * kiso_h   / to_mm * 10.0, 2)
        kiso_kata_m2 = round(2 * kiso_h / to_mm * 10.0, 2)

    # JSON出力
    output_data = {
        "description": "天端コンクリート断面形状座標(mm)",
        "unit": "mm",
        "origin": "front_top_corner",
        "points": [
            {"name": "front_top",    "x": p1_real[0], "y": p1_real[1]},
            {"name": "back_top",     "x": p2_real[0], "y": p2_real[1]},
            {"name": "back_bottom",  "x": p3_real[0], "y": p3_real[1]},
            {"name": "front_bottom", "x": p4_real[0], "y": p4_real[1]}
        ],
        "quantities": {
            "concrete_m3":  conc_m3,
            "kata_waku_m2": kata_m2_val,
        }
    }
    if is_guardrail:
        output_data["quantities"]["guardrail"] = {
            "gr_m":          gr_m,
            "mortar_m3":     mortar_m3,
            "kiso_m3":       kiso_m3,
            "kiso_kata_m2":  kiso_kata_m2,
        }
    with open(output_json, 'w', encoding='utf-8') as jf:
        json.dump(output_data, jf, indent=2, ensure_ascii=False)

    # DXF作成
    doc = ezdxf.new('R2010', setup=True)
    doc.header['$INSUNITS'] = 4 
    msp = doc.modelspace()

    doc.layers.add(name="TENBA_CONC", color=7)
    doc.layers.add(name="DIMENSION",  color=1)
    doc.layers.add(name="GR_BASE",    color=3)
    doc.layers.add(name="GR_KISO",    color=4)
    doc.layers.add(name="TABLE",      color=7)

    # 断面形状（GR基礎あり の場合は台形不要）
    dxf_coords = [(p[0] * scale, p[1] * scale) for p in real_coords]
    dxf_coords.append(dxf_coords[0])
    if not is_guardrail:
        msp.add_lwpolyline(dxf_coords, dxfattribs={'layer': 'TENBA_CONC'})

    # ガードレール基礎描画（基点=(0,0)=天端コン前面上端=GR左上角）
    if is_guardrail:
        s = scale

        # GR既製品外形 8頂点ポリゴン（実寸mm→DXF座標）
        gr_poly = [
            (     0 * s,          0 * s),   # P1 基準点
            (   400 * s,          0 * s),   # P2 ③天端右端
            (   400 * s, -(gr_h-100) * s),  # P3 ④右側下端
            ((gr_bw-100)*s, -(gr_h-100)*s), # P4 ⑩背面水平
            ((gr_bw-100)*s, -gr_h * s),     # P5 ⑨底
            (  -100 * s, -gr_h * s),        # P6 ⑧底
            (  -100 * s, -(gr_h-100)*s),    # P7 ⑧上端
            (     0 * s, -(gr_h-100)*s),    # P8 ⑩前面水平
        ]
        msp.add_lwpolyline(gr_poly, close=True, dxfattribs={"layer": "GR_BASE"})

        # GR基礎の上部の矩形（P1-P2-P3-P8, x:0~400, y:0~-(gr_h-100)）の中心に表記
        gr_label_x = 200 * s
        gr_label_y = -(gr_h - 100) / 2 * s
        t_gr = msp.add_text("ガードレール基礎", dxfattribs={"height": 3.5, "layer": "GR_BASE"})
        t_gr.dxf.halign = 1
        t_gr.dxf.valign = 2
        t_gr.dxf.insert = t_gr.dxf.align_point = (gr_label_x, gr_label_y)

        # ⑤ 延長線：GR前端(-100mm) → ブロック前面
        x_face_gr = slope * (-gr_h)   # ブロック前面のx（実寸mm、負値）
        if x_face_gr < -100:
            msp.add_line(
                (-100 * s,   -gr_h * s),
                (x_face_gr * s, -gr_h * s),
                dxfattribs={"layer": "GR_BASE"}
            )

        # モルタル層（台形：前端=ブロック前面、後端=⑪）
        xf_mt_top = slope * (-gr_h)
        xf_mt_bot = slope * (-gr_h - mortar_h)
        msp.add_lwpolyline([
            (xf_mt_top * s, -gr_h * s),
            (gr_bw * s,     -gr_h * s),
            (gr_bw * s,     -(gr_h + mortar_h) * s),
            (xf_mt_bot * s, -(gr_h + mortar_h) * s),
        ], close=True, dxfattribs={"layer": "GR_KISO"})

        # 敷モルタル 引出線（線種・矢印は寸法線に準ずる：開矢印・layer DIMENSION）
        mt_cx = (xf_mt_top + xf_mt_bot + 2 * gr_bw) / 4 * s
        mt_cy = -(gr_h + mortar_h / 2) * s
        mt_text = "敷モルタル"
        mt_text_h = 3.5
        ldr_len = gr_label_y - mt_cy   # 右斜め45度、「ガードレール基礎」と同じ高さまで伸ばす
        lx = mt_cx + ldr_len
        ly = mt_cy + ldr_len
        msp.add_line((mt_cx, mt_cy), (lx, ly), dxfattribs={'layer': 'DIMENSION', 'lineweight': 13})
        ezdxf_arrows.ARROWS.render_arrow(
            msp, ezdxf_arrows.ARROWS.open, insert=(mt_cx, mt_cy), size=5.0,
            rotation=225.0,
            dxfattribs={'layer': 'DIMENSION', 'lineweight': 13}
        )
        t_mt = msp.add_text(mt_text, dxfattribs={"height": mt_text_h, "layer": "DIMENSION"})
        t_mt.dxf.halign = 0
        t_mt.dxf.valign = 0
        gap = 0.15 * mt_text_h
        t_mt.dxf.insert = (lx, ly + gap)

        # アンダーライン（先端=引出線の先端に一致、長さ=文字数×文字高さ=V-nas実描画幅）
        ul_len = len(mt_text) * mt_text_h
        msp.add_line((lx, ly), (lx + ul_len, ly), dxfattribs={'layer': 'DIMENSION', 'lineweight': 13})

        # GR基礎左上の角 → モルタル左上の角（破線）
        if 'DASHED' not in doc.linetypes:
            doc.linetypes.add('DASHED', pattern=[375, 250, -125])
        msp.add_line(
            (0, 0), (xf_mt_top * s, -gr_h * s),
            dxfattribs={"layer": "GR_KISO", "linetype": "DASHED", "lineweight": 13}
        )

        # 基礎コン層（台形：前端=ブロック前面、後端=⑪）
        xf_kc_top = slope * (-gr_h - mortar_h)
        xf_kc_bot = slope * (-gr_h - mortar_h - kiso_h)
        msp.add_lwpolyline([
            (xf_kc_top * s, -(gr_h + mortar_h) * s),
            (gr_bw * s,     -(gr_h + mortar_h) * s),
            (gr_bw * s,     -(gr_h + mortar_h + kiso_h) * s),
            (xf_kc_bot * s, -(gr_h + mortar_h + kiso_h) * s),
        ], close=True, dxfattribs={"layer": "GR_KISO"})

        # 基礎コン中央に「基礎コンクリート」と表記
        kc_label_x = (xf_kc_top + xf_kc_bot + 2 * gr_bw) / 4 * s
        kc_label_y = -(gr_h + mortar_h + kiso_h / 2) * s
        t_kc = msp.add_text("基礎コンクリート", dxfattribs={"height": 3.5, "layer": "GR_KISO"})
        t_kc.dxf.halign = 1
        t_kc.dxf.valign = 2
        t_kc.dxf.insert = t_kc.dxf.align_point = (kc_label_x, kc_label_y)

        # ⑪ 垂直線（モルタル+基礎コン 後端）
        msp.add_line(
            (gr_bw * s, -gr_h * s),
            (gr_bw * s, -(gr_h + mortar_h + kiso_h) * s),
            dxfattribs={"layer": "GR_KISO"}
        )

    # 構造物のバウンディングボックス（引出線の起点を構造物から3mm離すために使用）
    struct_layers = {"GR_BASE", "GR_KISO"} if is_guardrail else {"TENBA_CONC"}
    struct_entities = [e for e in msp if e.dxf.layer in struct_layers]
    struct_bb = ezdxf_bbox.extents(struct_entities, fast=True)

    # 寸法スタイル
    if 'JIMASTYLE' not in doc.dimstyles:
        dimstyle = doc.dimstyles.new('JIMASTYLE')
        dimstyle.dxf.dimtxt  = 3.5
        dimstyle.dxf.dimasz  = 5.0
        dimstyle.dxf.dimlfac = scale_input
        dimstyle.dxf.dimdec  = 0
        dimstyle.dxf.dimgap  = 1.5
        dimstyle.dxf.dimtad  = 1   # 寸法値を寸法線の上に
        dimstyle.dxf.dimblk  = "OPEN"   # 開矢印
        dimstyle.dxf.dimlwd  = 13
        dimstyle.dxf.dimlwe  = 13
        dimstyle.dxf.dimclrd = 7
        dimstyle.dxf.dimclre = 7
        dimstyle.dxf.dimclrt = 7

    offset_dist = 15.0
    if is_guardrail:
        s = scale
        dim_x = gr_bw * s + offset_dist  # 縦寸法線のX位置

        # 縦3段（右側）: GR高さ・モルタル・基礎コン（引出線は構造物のbboxから3mm離す）
        exo_right = _exo_to(gr_bw * s, struct_bb.extmax.x, outward=1)
        msp.add_linear_dim(
            base=(dim_x, 0),
            p1=(gr_bw * s,  0),
            p2=(gr_bw * s, -gr_h * s),
            angle=-90,
            dimstyle='JIMASTYLE', dxfattribs={'layer': 'DIMENSION'},
            override={'dimexo': exo_right}
        ).render()
        msp.add_linear_dim(
            base=(dim_x, 0),
            p1=(gr_bw * s, -gr_h * s),
            p2=(gr_bw * s, -(gr_h + mortar_h) * s),
            angle=-90,
            dimstyle='JIMASTYLE', dxfattribs={'layer': 'DIMENSION'},
            override={'dimexo': exo_right}
        ).render()
        d_kiso_h = msp.add_linear_dim(
            base=(dim_x, 0),
            p1=(gr_bw * s, -(gr_h + mortar_h) * s),
            p2=(gr_bw * s, -(gr_h + mortar_h + kiso_h) * s),
            angle=-90,
            dimstyle='JIMASTYLE', dxfattribs={'layer': 'DIMENSION'},
            override={'dimexo': exo_right}
        )
        d_kiso_h.render()
        _fix_arrows_outward(doc, [d_kiso_h], dimstyle.dxf.dimasz)

        # 横3本: モルタル上幅・基礎コン上面幅・GR基礎の幅（底面幅）
        y_mt   = -gr_h * s
        x_mt_l = slope * (-gr_h) * s
        msp.add_linear_dim(
            base=(0, 30.0),
            p1=(x_mt_l,    y_mt),
            p2=(gr_bw * s, y_mt),
            dimstyle='JIMASTYLE', dxfattribs={'layer': 'DIMENSION'},
            override={'dimexo': _exo_to(y_mt, struct_bb.extmax.y, outward=1)}
        ).render()

        # GR基礎購入品の幅（底辺 P6-P5、モルタル上幅寸法線の8mm下）
        msp.add_linear_dim(
            base=(0, 30.0 - 8.0),
            p1=(-100 * s,         -gr_h * s),
            p2=((gr_bw - 100) * s, -gr_h * s),
            dimstyle='JIMASTYLE', dxfattribs={'layer': 'DIMENSION'},
            override={'dimexo': _exo_to(-gr_h * s, struct_bb.extmax.y, outward=1)}
        ).render()

        y_kb   = -(gr_h + mortar_h + kiso_h) * s
        x_kb_l = slope * (-(gr_h + mortar_h + kiso_h)) * s
        kb_base_y = y_kb - 30.0
        msp.add_linear_dim(
            base=(0, kb_base_y),
            p1=(x_kb_l,    y_kb),
            p2=(gr_bw * s, y_kb),
            dimstyle='JIMASTYLE', dxfattribs={'layer': 'DIMENSION'},
            override={'dimexo': _exo_to(y_kb, struct_bb.extmin.y, outward=-1)}
        ).render()

        # 基礎コン上面幅（モルタル下面と同じ線）。底面幅の寸法線の8mm上に描く
        y_kc_top = -(gr_h + mortar_h) * s
        x_kc_top_l = slope * (-(gr_h + mortar_h)) * s
        msp.add_linear_dim(
            base=(0, kb_base_y + 8.0),
            p1=(x_kc_top_l, y_kc_top),
            p2=(gr_bw * s,  y_kc_top),
            dimstyle='JIMASTYLE', dxfattribs={'layer': 'DIMENSION'},
            override={'dimexo': _exo_to(y_kc_top, struct_bb.extmin.y, outward=-1)}
        ).render()
    else:
        # 上面幅寸法（引出線は構造物のbboxから3mm離す）
        msp.add_linear_dim(
            base=(0, offset_dist),
            p1=dxf_coords[0], p2=dxf_coords[1],
            dimstyle='JIMASTYLE', dxfattribs={'layer': 'DIMENSION'},
            override={'dimexo': _exo_to(dxf_coords[0][1], struct_bb.extmax.y, outward=1)}
        ).render()
        # 厚み寸法（矢印は外向き、引出線は構造物のbboxから3mm離す）
        d_thick = msp.add_linear_dim(
            base=((w_top * scale) + offset_dist, 0),
            p1=dxf_coords[1], p2=dxf_coords[2],
            angle=-90,
            override={'dimexo': _exo_to(dxf_coords[1][0], struct_bb.extmax.x, outward=1)},
            dimstyle='JIMASTYLE', dxfattribs={'layer': 'DIMENSION'}
        )
        d_thick.render()
        _fix_arrows_outward(doc, [d_thick], dimstyle.dxf.dimasz)

    # =========================================================
    # 表題（図の上・中央）
    # =========================================================
    txt_h    = 3.5
    center_x = (w_top / 2) * scale
    # GR基礎の場合はモルタル上幅寸法線(y=30)より上にずらして重なりを避ける
    y_scale  = (30.0 + 15.0) if is_guardrail else (offset_dist + 8.0)
    y_title  = y_scale + 10.0

    title_text = "ガードレール基礎" if is_guardrail else "天端コンクリート"
    t1 = msp.add_text(title_text, dxfattribs={"height": 7.0})
    t1.dxf.insert      = (center_x, y_title)
    t1.dxf.halign      = 1
    t1.dxf.align_point = (center_x, y_title)

    t2 = msp.add_text(f"S=1/{int(scale_input)}", dxfattribs={"height": 5.0})
    t2.dxf.insert      = (center_x, y_scale)
    t2.dxf.halign      = 1
    t2.dxf.align_point = (center_x, y_scale)

    # 前面勾配ラベル（前面中央、法線方向に少しオフセット）
    face_mid_x = (dxf_coords[0][0] + dxf_coords[3][0]) / 2
    face_mid_y = (dxf_coords[0][1] + dxf_coords[3][1]) / 2
    face_angle = math.degrees(math.atan2(1.0, slope))
    off_x = -6.0 / k_front
    off_y =  6.0 * slope / k_front
    t_sl = msp.add_text(f"1:{slope:g}", dxfattribs={"height": txt_h, "rotation": face_angle})
    t_sl.dxf.insert      = (face_mid_x + off_x, face_mid_y + off_y)
    t_sl.dxf.halign      = 1
    t_sl.dxf.valign      = 2
    t_sl.dxf.align_point = (face_mid_x + off_x, face_mid_y + off_y)

    # =========================================================
    # 数量表（断面図の下に配置）
    # =========================================================
    txt_h  = 3.5
    cell_txt_h = txt_h * 0.9       # セル内文字の実高さ
    cell_h = cell_txt_h + 2 * 1.5  # 文字の上下1.5mmに罫線

    table_x = dxf_coords[3][0] - 10.0
    if is_guardrail:
        table_y = y_kb - offset_dist - 15.0 - 20.0  # 最下段の寸法線から15mm、さらに20mm下
    else:
        table_y = dxf_coords[3][1] - 15.0    # 断面図の下端から15mm

    def draw_table(rows, title, ox, oy):
        headers = ["項目", "細目", "単位", "数量"]
        pad = 4.0  # 左右の余白
        col_w = []
        for col_idx, hdr in enumerate(headers):
            max_len = len(hdr)
            for row in rows:
                max_len = max(max_len, len(str(row[col_idx])))
            col_w.append(max_len * cell_txt_h + pad)
        total_w = sum(col_w)

        row_count = len(rows) + 1
        table_h   = cell_h * row_count

        msp.add_text(title, dxfattribs={"height": txt_h, "layer": "TABLE"}).set_placement(
            (ox + total_w / 2, oy + txt_h), align=TextEntityAlignment.BOTTOM_CENTER
        )
        msp.add_text("10mあたり", dxfattribs={"height": txt_h * 0.8, "layer": "TABLE"}).set_placement(
            (ox + total_w, oy + txt_h), align=TextEntityAlignment.BOTTOM_RIGHT
        )
        msp.add_lwpolyline([
            (ox, oy), (ox + total_w, oy),
            (ox + total_w, oy - table_h),
            (ox, oy - table_h), (ox, oy)
        ], close=True, dxfattribs={"layer": "TABLE"})

        unit_col = headers.index("単位")
        x = ox
        for col_idx, (hdr, cw) in enumerate(zip(headers, col_w)):
            msp.add_line((x, oy), (x, oy - table_h), dxfattribs={"layer": "TABLE"})
            if col_idx == unit_col:
                msp.add_text(hdr, dxfattribs={"height": txt_h * 0.9, "layer": "TABLE"}).set_placement(
                    (x + cw / 2, oy - cell_h / 2), align=TextEntityAlignment.MIDDLE_CENTER
                )
            else:
                msp.add_text(hdr, dxfattribs={"height": txt_h * 0.9, "layer": "TABLE"}).set_placement(
                    (x + 2, oy - cell_h / 2 - cell_txt_h / 2)
                )
            x += cw
        msp.add_line((ox, oy - cell_h), (ox + total_w, oy - cell_h), dxfattribs={"layer": "TABLE"})

        for r_idx, row in enumerate(rows):
            row_y = oy - cell_h * (r_idx + 1)
            msp.add_line((ox, row_y), (ox + total_w, row_y), dxfattribs={"layer": "TABLE"})
            x = ox
            for col_idx, (val, cw) in enumerate(zip(row, col_w)):
                if col_idx == unit_col:
                    msp.add_text(str(val), dxfattribs={"height": txt_h * 0.9, "layer": "TABLE"}).set_placement(
                        (x + cw / 2, row_y - cell_h / 2), align=TextEntityAlignment.MIDDLE_CENTER
                    )
                else:
                    msp.add_text(str(val), dxfattribs={"height": txt_h * 0.9, "layer": "TABLE"}).set_placement(
                        (x + 2, row_y - cell_h / 2 - cell_txt_h / 2)
                    )
                x += cw

    if is_guardrail:
        rows = [
            ["ガードレール基礎", "既製品",      "m",  f"{gr_m:.2f}"],
            ["モルタル",         f"1:3モルタル　{int(mortar_h)}mm厚", "m3", f"{mortar_m3:.2f}"],
            ["コンクリート",     "18kn/mm2",    "m3", f"{kiso_m3:.2f}"],
            ["型枠",             "小型構造物",  "m2", f"{kiso_kata_m2:.2f}"],
        ]
        draw_table(rows, "天端工（ガードレール基礎）数量表", table_x, table_y)
    else:
        rows = [
            ["コンクリート", "18kn/mm2",    "m3", f"{conc_m3:.2f}"],
            ["型枠",         "小型構造物",  "m2", f"{kata_m2_val:.2f}"],
        ]
        draw_table(rows, "天端コンクリート工　数量表", table_x, table_y)

    doc.saveas(dxf_filename)
    print(f"    DXF出力: tenba_danmen.dxf (1/{int(scale_input)})")
    print(f"    JSON出力: tenba_data.json")


def main(output_dir, scale=10, **kwargs):
    generate_tenba_dxf(
        os.path.join(output_dir, "input.json"),
        os.path.join(output_dir, "tenba_danmen.dxf"),
        os.path.join(output_dir, "tenba_data.json"),
        float(scale)
    )

if __name__ == "__main__":
    main(".")
