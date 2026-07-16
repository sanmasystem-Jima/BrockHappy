# -*- coding: utf-8 -*-
# ブロック積 展開図

import json
import math
import os
import ezdxf
from ezdxf.enums import TextEntityAlignment


KOGUCHI_CUT = 300.0


def _fix_arrows_outward(doc, dim_list, asz):
    """render()済み寸法ブロックの矢印を外向きに統一する。
    測定距離が 2*asz+dimgap 未満（ezdxfが自動的に矢印を寸法線の外側に
    配置する「outside」レイアウト）の場合は、ezdxfのデフォルトが既に
    正しい外向き表示になっているため何もしない（無理に反転すると
    矢印同士が重なって壊れる）。それ以外は現在の向きを判定し、
    内向きの場合のみ反転し、寸法線を矢印先端に合わせて整える。
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

        is_v = abs(arrow_pos[0][0] - arrow_pos[1][0]) < 0.01
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
                if ((s.x - arr_x)**2 + (s.y - arr_y)**2)**0.5 < asz * 2.5:
                    e.dxf.start = (arr_x, arr_y, 0)
                if ((en.x - arr_x)**2 + (en.y - arr_y)**2)**0.5 < asz * 2.5:
                    e.dxf.end   = (arr_x, arr_y, 0)


def _get_dim_text_y(doc, dim):
    """render()済み寸法のMTEXT挿入点yを取得（取得不可ならNone）。"""
    try:
        blk_name = dim.dimension.dxf.geometry
    except Exception:
        return None
    if blk_name not in doc.blocks:
        return None
    for e in doc.blocks[blk_name]:
        if e.dxftype() == "MTEXT":
            return e.dxf.insert.y
    return None


def _draw_leader_label(msp, point_xy, text_str, sign, text_height, scale, layer):
    """斜め引出線＋アンダーライン付きラベルを描画（先端=引出線の先っちょに一致）。"""
    ldr_len = 15.0 * scale / math.sqrt(2)
    ldr_x   = point_xy[0] + sign * ldr_len
    ldr_y   = point_xy[1] + ldr_len
    msp.add_line(point_xy, (ldr_x, ldr_y), dxfattribs={"layer": layer, "lineweight": 13})

    gap   = 0.15 * text_height
    align = TextEntityAlignment.BOTTOM_LEFT if sign > 0 else TextEntityAlignment.BOTTOM_RIGHT
    t = msp.add_text(text_str, height=text_height, dxfattribs={"layer": layer, "style": "MS-GOTHIC"})
    t.set_placement((ldr_x, ldr_y + gap), align=align)

    # V-nas側は等幅フォントで半角/全角を問わず1文字=文字高さ幅で描画されるため、文字数×文字高さで実幅を計算
    ul_len = len(text_str) * text_height
    if sign > 0:
        x1, x2 = ldr_x, ldr_x + ul_len
    else:
        x1, x2 = ldr_x - ul_len, ldr_x
    msp.add_line((x1, ldr_y), (x2, ldr_y), dxfattribs={"layer": layer, "lineweight": 13})


def _fix_text_outside_dim(doc, dim_list):
    """垂直寸法のテキストを引き出し線の反対側（外側）へ強制移動。"""
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
        (ax1, ay1), (ax2, ay2) = arrow_pos[0], arrow_pos[1]
        is_v = abs(ax1 - ax2) < 0.01
        dim_coord = ax1 if is_v else ay1

        ext_coord = None
        if is_v:
            for e in blk:
                if e.dxftype() != "LINE":
                    continue
                s, en = e.dxf.start, e.dxf.end
                if abs(s.y - en.y) < 0.01:
                    ext_coord = s.x if abs(s.x - dim_coord) > abs(en.x - dim_coord) else en.x
                    break

        for e in blk:
            if e.dxftype() != "MTEXT":
                continue
            pos = e.dxf.insert
            if is_v:
                if ext_coord is None:
                    continue
                want_right = ext_coord < dim_coord
                is_right   = pos.x > dim_coord
                if want_right != is_right:
                    e.dxf.insert = (2 * dim_coord - pos.x, pos.y, 0)
            else:
                if pos.y < dim_coord:
                    e.dxf.insert = (pos.x, 2 * dim_coord - pos.y, 0)


def _foundation_kind_label(foundation_type, rock_type):
    if foundation_type == "rock":
        return {"nangan1": "岩着・軟岩Ⅰ", "nangan2": "岩着・軟岩Ⅱ以上"}.get(rock_type, f"岩着・{rock_type}")
    return "直接"


def _kiso_segments(foundation_types, rock_types, num_spans):
    """スパンごとの基礎形式・岩盤区分が同じ連続区間をまとめる。
    戻り値: [(開始スパン番号, 終了スパン番号(含む), (foundation_type, rock_type)), ...]"""
    kinds = []
    for i in range(num_spans):
        ft = foundation_types[i] if i < len(foundation_types) else None
        rt = rock_types[i] if (ft == "rock" and i < len(rock_types)) else None
        kinds.append((ft, rt))

    segments = []
    seg_start = 0
    for i in range(1, num_spans):
        if kinds[i] != kinds[seg_start]:
            segments.append((seg_start, i - 1, kinds[seg_start]))
            seg_start = i
    segments.append((seg_start, num_spans - 1, kinds[seg_start]))
    return segments


def _kind_key(foundation_type, rock_type):
    return (foundation_type, rock_type if foundation_type == "rock" else None)


def _kind_suffix(foundation_type, rock_type):
    """00_Brock_Tougou.py / 02_Brock_Kiso.py が生成する kiso_data_<suffix>.json のsuffixと一致させる"""
    if foundation_type == "rock":
        return {"nangan1": "岩着_軟岩1", "nangan2": "岩着_軟岩2"}.get(rock_type, f"岩着_{rock_type}")
    return "直接"


def _load_kiso_dims(output_dir, cache, foundation_type, rock_type, primary_key, default_h1, default_h2):
    """(foundation_type, rock_type) に対応する kiso_data.json の H1/H2（mm）を読み込む（キャッシュ付き）。
    先頭スパンの種類（primary_key）はサフィックスなしのファイルを使う。岩着はH1=H2=0（基礎コン・砕石なし）。"""
    key = _kind_key(foundation_type, rock_type)
    if key in cache:
        return cache[key]
    if key == primary_key:
        path = os.path.join(output_dir, "kiso_data.json")
    else:
        path = os.path.join(output_dir, f"kiso_data_{_kind_suffix(foundation_type, rock_type)}.json")
    h1, h2 = default_h1, default_h2
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            kd = json.load(f)
        dims = kd.get("dimensions", {})
        h1 = float(dims.get("H1", default_h1))
        h2 = float(dims.get("H2", default_h2))
    cache[key] = (h1, h2)
    return (h1, h2)


def main(output_dir, scale=50, **kwargs):

    scale = float(scale)
    MM    = 1000.0

    text_height = 3.5 * scale
    point_size  = text_height * 0.3
    dim_offset  = 25.0 * scale

    input_json = os.path.join(output_dir, "input.json")
    with open(input_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    point_names      = data["point_names"]
    elevations       = data["elevations"]
    embed_depths     = data["embed_depths"]
    block_heights    = data["block_heights"]
    upper_extension  = data["upper_extension"]
    lower_extension  = data["lower_extension"]
    water_level_els  = data.get("water_level_els")
    koguchi_type     = data.get("koguchi_type", "none")
    has_tenba_con    = data.get("has_tenba_con", "n")
    tenba_con_height = data.get("tenba_con_height", 0.0)
    is_gr_kiso       = data.get("has_gr_kiso") == "y"
    front_slope      = data.get("front_slope", 0.4)
    base_line_type   = data.get("base_line_type", "tenba_kado")

    # 基礎コン高さ・均しコン(砕石)高さ は kiso_data.json の H1/H2 を優先
    kiso_json_path = os.path.join(output_dir, "kiso_data.json")
    if os.path.exists(kiso_json_path):
        with open(kiso_json_path, "r", encoding="utf-8") as _f:
            _kd = json.load(_f)
        _dims = _kd.get("dimensions", {})
        base_concrete_h = float(_dims.get("H1", 300))   # mm
        crushed_stone_h = float(_dims.get("H2", 150))   # mm
    else:
        base_concrete_h = data.get("base_concrete_height", 0.30) * MM
        crushed_stone_h = data.get("crushed_stone_height", 0.15) * MM

    # 基礎コン高さ・砕石高さのスパンごとの解決（岩着区間は基礎コン・砕石ともに無し＝0）
    _num_spans_kiso   = len(upper_extension)
    _ft_primary       = data.get("foundation_type", "direct")
    _rt_primary       = data.get("rock_type")
    _kiso_primary_key = _kind_key(_ft_primary, _rt_primary)
    _foundation_types = data.get("foundation_types") or [_ft_primary] * _num_spans_kiso
    _rock_types       = data.get("rock_types") or [_rt_primary] * _num_spans_kiso
    _kiso_dims_cache  = {_kiso_primary_key: (base_concrete_h, crushed_stone_h)}

    def _span_kiso_h(span_idx):
        ft = _foundation_types[span_idx] if span_idx < len(_foundation_types) else _ft_primary
        rt = _rock_types[span_idx] if span_idx < len(_rock_types) else _rt_primary
        return _load_kiso_dims(output_dir, _kiso_dims_cache, ft, rt, _kiso_primary_key,
                                base_concrete_h, crushed_stone_h)

    def _point_kiso_h(point_idx):
        """測点の基礎コン高さ・砕石高さ（次スパン優先、最終測点は前スパン）"""
        if _num_spans_kiso <= 0:
            return (base_concrete_h, crushed_stone_h)
        return _span_kiso_h(min(point_idx, _num_spans_kiso - 1))

    slope_ratio = math.sqrt(1.0 + front_slope ** 2)

    # 各スパンの最大延長（上下の長い方）を累積してX座標を構築
    cum_x = [0.0]
    for _i in range(len(upper_extension)):
        cum_x.append(cum_x[-1] + max(upper_extension[_i], lower_extension[_i]) * MM)
    distances = cum_x

    top_els      = []
    bottom_els   = []
    umemodoshi_els = []  # ⑤ 埋戻し高さ

    if base_line_type == "tenba_kado":
        # 基準点EL = 天端コンクリート上面
        for el, embed, h in zip(elevations, embed_depths, block_heights):
            top_el  = el * MM                        # 天端コン上面 = 基準点EL
            bot_el  = top_el - h * MM                # ブロック底面
            top_els.append(top_el)
            bottom_els.append(bot_el)
            umemodoshi_els.append(bot_el + embed * MM)
    else:
        for el, embed, h in zip(elevations, embed_depths, block_heights):
            bottom = el - embed
            top    = bottom + h
            top_els.append(top * MM)
            bottom_els.append(bottom * MM)
            umemodoshi_els.append(el * MM)

    global_min_stone_y = min(
        bottom_els[_i] - _point_kiso_h(_i)[0] - _point_kiso_h(_i)[1] for _i in range(len(bottom_els))
    )
    global_dim_bot_y   = global_min_stone_y - dim_offset
    global_max_top_y   = max(top_els)
    global_dim_top_y   = global_max_top_y + dim_offset

    # GR基礎の場合、小口止幅(global_dim_top_y)の上にもう1段追加してから
    # 区間GR基礎長／全体GR基礎長／全長を積み上げる
    span_dim_y  = global_dim_top_y + (8.0 * scale if is_gr_kiso else 0.0)

    # =========================================================
    # DXF初期化
    # =========================================================
    doc = ezdxf.new("R2018")
    doc.header['$INSUNITS'] = 4 
    msp = doc.modelspace()

    doc.styles.add("MS-GOTHIC", font="msgothic.ttc")

    if 'DASHED' not in [lt.dxf.name for lt in doc.linetypes]:
        doc.linetypes.add('DASHED', pattern=[0.5, 0.25, -0.25])

    doc.layers.add(name="GUIDE",       color=8)
    doc.layers.add(name="POINT",       color=1)
    doc.layers.add(name="TOP",         color=1)
    doc.layers.add(name="BOTTOM",      color=5)
    doc.layers.add(name="SIDE",        color=3)
    doc.layers.add(name="BASE",        color=4)
    doc.layers.add(name="STONE",       color=9)
    doc.layers.add(name="KOGUCHI",     color=1)
    doc.layers.add(name="MEJI_LINE",   color=2, linetype="DASHED")
    doc.layers.add(name="UMEMODOSHI",  color=6)
    doc.layers.add(name="TEXT",        color=7)
    doc.layers.add(name="DIM",         color=2)
    doc.layers.add(name="REF_LINE",    color=6)
    doc.layers.add(name="WATER_LEVEL", color=5, linetype="DASHED")

    dimstyle = doc.dimstyles.get("Standard")
    dimstyle.dxf.dimtxt   = text_height
    dimstyle.dxf.dimasz   = 2.5 * scale
    dimstyle.dxf.dimexe   = 1.5 * scale
    dimstyle.dxf.dimexo   = 1.0 * scale
    dimstyle.dxf.dimgap   = 1.0 * scale
    dimstyle.dxf.dimtdec  = 2
    dimstyle.dxf.dimtxsty = "MS-GOTHIC"
    dimstyle.dxf.dimtad   = 1
    dimstyle.dxf.dimdec   = 2
    dimstyle.dxf.dimlfac  = 1.0 / MM  # mm→m変換
    dimstyle.dxf.dimzin = 0  # 末尾の0を表示
    dimstyle.dxf.dimblk  = "OPEN"  # 開矢印
    dimstyle.dxf.dimlwd  = 13      # 寸法線0.13mm
    dimstyle.dxf.dimlwe  = 13      # 延長線0.13mm
    dimstyle.dxf.dimclrd = 7
    dimstyle.dxf.dimclre = 7
    dimstyle.dxf.dimclrt = 7

    if "KISO_DIM_NOTEXT" not in doc.dimstyles:
        ks = doc.dimstyles.new("KISO_DIM_NOTEXT")
        ks.dxf.dimtxt  = 0.0
        ks.dxf.dimasz  = 2.5 * scale
        ks.dxf.dimexe  = 1.5 * scale
        ks.dxf.dimexo  = 1.0 * scale
        ks.dxf.dimgap  = 1.0 * scale
        ks.dxf.dimlfac = 1.0 / MM
        ks.dxf.dimblk  = "OPEN"
        ks.dxf.dimlwd  = 13
        ks.dxf.dimlwe  = 13
        ks.dxf.dimclrd = 7
        ks.dxf.dimclre = 7
        ks.dxf.dimclrt = 7

    if "VERT_DIM" not in doc.dimstyles:
        vd = doc.dimstyles.new("VERT_DIM")
        vd.dxf.dimtxt   = text_height
        vd.dxf.dimasz   = 2.5 * scale
        vd.dxf.dimexe   = 1.5 * scale
        vd.dxf.dimexo   = 1.0 * scale
        vd.dxf.dimgap   = 1.0 * scale
        vd.dxf.dimtxsty = "MS-GOTHIC"
        vd.dxf.dimtad   = 1
        vd.dxf.dimdec   = 2
        vd.dxf.dimlfac  = 1.0 / MM
        vd.dxf.dimzin   = 0
        vd.dxf.dimatfit = 0  # テキスト・矢印ともに外向き強制
        vd.dxf.dimblk   = "OPEN"
        vd.dxf.dimlwd   = 13
        vd.dxf.dimlwe   = 13
        vd.dxf.dimclrd  = 7
        vd.dxf.dimclre  = 7
        vd.dxf.dimclrt  = 7

    if "KOGUCHI_DIM" not in doc.dimstyles:
        kd = doc.dimstyles.new("KOGUCHI_DIM")
        kd.dxf.dimtxt   = text_height
        kd.dxf.dimasz   = 2.5 * scale
        kd.dxf.dimexe   = 1.5 * scale
        kd.dxf.dimexo   = 1.0 * scale
        kd.dxf.dimgap   = 1.0 * scale
        kd.dxf.dimtxsty = "MS-GOTHIC"
        kd.dxf.dimtad   = 1
        kd.dxf.dimdec   = 3
        kd.dxf.dimlfac  = 1.0 / MM
        kd.dxf.dimtix   = 0  # 矢印外向き
        kd.dxf.dimblk   = "OPEN"
        kd.dxf.dimlwd   = 13
        kd.dxf.dimlwe   = 13
        kd.dxf.dimclrd  = 7
        kd.dxf.dimclre  = 7
        kd.dxf.dimclrt  = 7

    GUIDE_OVERSHOOT = 10.0  # ブロック天端・基礎底からの突き出し量（mm）

    for _pi, (x, top_el, bottom_el) in enumerate(zip(distances, top_els, bottom_els)):
        _h1, _h2 = _point_kiso_h(_pi)
        guide_top = top_el + GUIDE_OVERSHOOT
        guide_bottom = bottom_el - _h1 - _h2 - GUIDE_OVERSHOOT
        msp.add_line((x, guide_bottom), (x, guide_top), dxfattribs={"layer": "GUIDE", "linetype": "DASHED"})

    for x, el in zip(distances, elevations):
        y = el * MM
        msp.add_point((x, y), dxfattribs={"layer": "POINT"})
        msp.add_line((x - point_size, y), (x + point_size, y), dxfattribs={"layer": "POINT"})
        msp.add_line((x, y - point_size), (x, y + point_size), dxfattribs={"layer": "POINT"})

    for i in range(len(distances) - 1):
        msp.add_line(
            (distances[i], elevations[i] * MM),
            (distances[i+1], elevations[i+1] * MM),
            dxfattribs={"layer": "REF_LINE"}
        )

    # 水面EL（河川のみ・測点ごと）
    if water_level_els:
        for x, wl in zip(distances, water_level_els):
            if wl is None:
                continue
            y = wl * MM
            msp.add_point((x, y), dxfattribs={"layer": "WATER_LEVEL"})
            msp.add_line((x - point_size, y), (x + point_size, y), dxfattribs={"layer": "WATER_LEVEL"})
            msp.add_line((x, y - point_size), (x, y + point_size), dxfattribs={"layer": "WATER_LEVEL"})

        for i in range(len(distances) - 1):
            if water_level_els[i] is None or water_level_els[i+1] is None:
                continue
            msp.add_line(
                (distances[i],   water_level_els[i]   * MM),
                (distances[i+1], water_level_els[i+1] * MM),
                dxfattribs={"layer": "WATER_LEVEL", "linetype": "DASHED"}
            )

        for x, wl in zip(distances, water_level_els):
            if wl is None:
                continue
            t_wl = msp.add_text(f"水面 EL={wl:.2f}", height=text_height,
                                 dxfattribs={"layer": "WATER_LEVEL", "style": "MS-GOTHIC", "color": 5})
            t_wl.set_placement((x + text_height * 0.5, wl * MM + text_height * 0.3))

    # =========================================================
    # 展開図 作図ループ
    # =========================================================
    num_spans  = len(upper_extension)
    tenba_t    = tenba_con_height * MM
    all_shapes = []
    left_end   = {}
    right_end  = {}

    for i in range(num_spans):
        x1, x2     = distances[i], distances[i + 1]
        top1, top2 = top_els[i],   top_els[i + 1]
        bot1, bot2 = bottom_els[i], bottom_els[i + 1]
        upper_len  = upper_extension[i] * MM
        lower_len  = lower_extension[i] * MM

        left_cut  = KOGUCHI_CUT if (i == 0           and koguchi_type in ["left",  "both"]) else 0.0
        right_cut = KOGUCHI_CUT if (i == num_spans-1 and koguchi_type in ["right", "both"]) else 0.0

        effective_upper = upper_len - left_cut - right_cut
        effective_lower = lower_len - left_cut - right_cut

        if effective_upper >= effective_lower:
            diff   = effective_upper - effective_lower
            offset = diff / 2.0
            tx1 = x1 + left_cut
            tx2 = x2 - right_cut
            bx1 = x1 + offset + left_cut
            bx2 = x2 - offset - right_cut
        else:
            diff   = effective_lower - effective_upper
            offset = diff / 2.0
            bx1 = x1 + left_cut
            bx2 = x2 - right_cut
            tx1 = x1 + offset + left_cut
            tx2 = x2 - offset - right_cut

        _span_base_h, _span_stone_h = _span_kiso_h(i)
        base_bot1  = bot1 - _span_base_h
        base_bot2  = bot2 - _span_base_h
        stone_bot1 = base_bot1 - _span_stone_h
        stone_bot2 = base_bot2 - _span_stone_h

        msp.add_line((tx1, top1), (tx2, top2), dxfattribs={"layer": "TOP"})

        if has_tenba_con == "y" and tenba_con_height > 0:
            msp.add_line((tx1, top1 - tenba_t), (tx2, top2 - tenba_t), dxfattribs={"layer": "TOP"})
            if is_gr_kiso or i != 0 or koguchi_type not in ["left", "both"]:
                msp.add_line((tx1, top1), (tx1, top1 - tenba_t), dxfattribs={"layer": "TOP"})
            if is_gr_kiso or i != num_spans - 1 or koguchi_type not in ["right", "both"]:
                msp.add_line((tx2, top2), (tx2, top2 - tenba_t), dxfattribs={"layer": "TOP"})

        msp.add_line((bx1, bot1),       (bx2, bot2),       dxfattribs={"layer": "BOTTOM"})
        # 岩着区間（基礎コン・砕石高さ=0）は基礎コン・砕石の絵を描かない（直接基礎区間のみ描画）
        if _span_base_h > 0:
            msp.add_line((bx1, base_bot1),  (bx2, base_bot2),  dxfattribs={"layer": "BASE"})
        if _span_stone_h > 0:
            msp.add_line((bx1, stone_bot1), (bx2, stone_bot2), dxfattribs={"layer": "STONE"})

        side_top1 = (top1 - tenba_t) if (has_tenba_con == "y" and tenba_t > 0) else top1
        side_top2 = (top2 - tenba_t) if (has_tenba_con == "y" and tenba_t > 0) else top2
        msp.add_line((tx1, side_top1), (bx1, bot1), dxfattribs={"layer": "SIDE"})
        msp.add_line((tx2, side_top2), (bx2, bot2), dxfattribs={"layer": "SIDE"})

        if _span_base_h > 0:
            msp.add_line((bx1, bot1),      (bx1, base_bot1),  dxfattribs={"layer": "BASE"})
            msp.add_line((bx2, bot2),      (bx2, base_bot2),  dxfattribs={"layer": "BASE"})
        if _span_stone_h > 0:
            msp.add_line((bx1, base_bot1), (bx1, stone_bot1), dxfattribs={"layer": "STONE"})
            msp.add_line((bx2, base_bot2), (bx2, stone_bot2), dxfattribs={"layer": "STONE"})

        if i == 0:
            left_end  = {"tx": tx1, "bx": bx1, "top": top1, "bot": bot1, "base_bot": base_bot1, "stone_bot": stone_bot1}
        if i == num_spans - 1:
            right_end = {"tx": tx2, "bx": bx2, "top": top2, "bot": bot2, "base_bot": base_bot2, "stone_bot": stone_bot2}

        # スパン延長寸法線（M単位）／GR基礎の場合は区間のGR基礎長
        # GR基礎ありの場合、両端は測点Xに引出し点を一致させ、30cm(小口止カット)を減算しない
        span_p1_x = x1 if (is_gr_kiso and i == 0)             else tx1
        span_p2_x = x2 if (is_gr_kiso and i == num_spans - 1) else tx2
        _dim = msp.add_linear_dim(
            base=(span_p1_x, span_dim_y),
            p1=(span_p1_x, top1), p2=(span_p2_x, top2),
            dimstyle="Standard", dxfattribs={"layer": "DIM"}
        )
        _dim.render()
        _fix_arrows_outward(doc, [_dim], 2.5 * scale)

        _dim = msp.add_linear_dim(
            base=(bx1, global_dim_bot_y),
            p1=(bx1, stone_bot1), p2=(bx2, stone_bot2),
            dimstyle="Standard", dxfattribs={"layer": "DIM"}
        )
        _dim.render()
        _fix_arrows_outward(doc, [_dim], 2.5 * scale)

        all_shapes.append({
            "span_no":     i + 1,
            "top_line":    [[tx1, top1], [tx2, top2]],
            "bottom_line": [[bx1, bot1], [bx2, bot2]]
        })

    # =========================================================
    # ⑤ 埋戻しライン（スパンごとの始点/終点の根入れを使う。
    #    測点配列（embed_depths）は隣接スパンの値を共有してしまうため、
    #    スパン自身の embed_depth_starts/ends を使ってスパン間の値が混ざらないようにする）
    # =========================================================
    _embed_starts = data.get("embed_depth_starts")
    _embed_ends   = data.get("embed_depth_ends")

    for i in range(len(distances) - 1):
        if base_line_type == "tenba_kado":
            if _embed_starts is not None and _embed_ends is not None and i < len(_embed_starts):
                e1, e2 = _embed_starts[i], _embed_ends[i]
            else:
                e1, e2 = embed_depths[i], embed_depths[i + 1]
            y1 = bottom_els[i]     + e1 * MM
            y2 = bottom_els[i + 1] + e2 * MM
        else:
            y1 = umemodoshi_els[i]
            y2 = umemodoshi_els[i + 1]
        msp.add_line(
            (distances[i], y1), (distances[i + 1], y2),
            dxfattribs={"layer": "UMEMODOSHI", "linetype": "DASHED"}
        )

    # =========================================================
    # ⑤ 裏砕石底面ライン（河川・岩着区間のみ。スパンごとの始点/終点を使い、
    #    スパンをまたいで値が混ざらないようにする）
    # =========================================================
    _is_river  = data.get("structure_type", "").startswith("river")
    _bf_starts = data.get("backfill_bottom_starts")
    _bf_ends   = data.get("backfill_bottom_ends")

    if _is_river and _bf_starts is not None and _bf_ends is not None:
        _bf_foundation_types = data.get("foundation_types") or [data.get("foundation_type")] * len(_bf_starts)
        for i in range(len(distances) - 1):
            ft = _bf_foundation_types[i] if i < len(_bf_foundation_types) else None
            if ft != "rock":
                continue
            sb1 = _bf_starts[i] if i < len(_bf_starts) else None
            sb2 = _bf_ends[i]   if i < len(_bf_ends)   else None
            if sb1 is None or sb2 is None:
                continue
            y1 = bottom_els[i]     + sb1 * MM
            y2 = bottom_els[i + 1] + sb2 * MM
            for x, y in ((distances[i], y1), (distances[i + 1], y2)):
                msp.add_line((x - point_size, y), (x + point_size, y), dxfattribs={"layer": "STONE"})
                msp.add_line((x, y - point_size), (x, y + point_size), dxfattribs={"layer": "STONE"})
            msp.add_line((distances[i], y1), (distances[i + 1], y2), dxfattribs={"layer": "STONE"})
    elif _is_river and data.get("foundation_type") == "rock":
        # 旧形式プロジェクト向けフォールバック（スパンごとのデータが無い場合）
        saiseki_bots = data.get("backfill_bottoms", [])
        if saiseki_bots and all(v is not None for v in saiseki_bots):
            saiseki_bot_els = [bot + sb * MM for bot, sb in zip(bottom_els, saiseki_bots)]
            for x, sb in zip(distances, saiseki_bot_els):
                msp.add_line((x - point_size, sb), (x + point_size, sb), dxfattribs={"layer": "STONE"})
                msp.add_line((x, sb - point_size), (x, sb + point_size), dxfattribs={"layer": "STONE"})
            for i in range(len(distances) - 1):
                msp.add_line(
                    (distances[i],   saiseki_bot_els[i]),
                    (distances[i+1], saiseki_bot_els[i+1]),
                    dxfattribs={"layer": "STONE"}
                )

    # =========================================================
    # 小口止コンクリート正面図
    # =========================================================
    def get_koguchi_top_y(end_data):
        if tenba_con_height == 0.0 or has_tenba_con == "n":
            return end_data["top"]
        elif tenba_con_height <= 0.15:
            return end_data["top"]
        else:
            return end_data["top"] - tenba_t

    if koguchi_type in ["left", "both"] and left_end:
        le      = left_end
        k_top_y = get_koguchi_top_y(le)
        x_in    = min(le["tx"], le["bx"])   # 上下辺のうち外側（左=小さい方）
        x_out   = x_in - KOGUCHI_CUT
        msp.add_line((x_in,  k_top_y),         (x_out, k_top_y),         dxfattribs={"layer": "KOGUCHI"})
        msp.add_line((x_out, k_top_y),         (x_out, le["stone_bot"]), dxfattribs={"layer": "KOGUCHI"})
        msp.add_line((x_out, le["stone_bot"]), (x_in,  le["stone_bot"]), dxfattribs={"layer": "KOGUCHI"})
        msp.add_line((x_in,  le["stone_bot"]), (x_in,  k_top_y),         dxfattribs={"layer": "KOGUCHI"})
        # GR基礎：GR天端の縦線(tx,top-tenba_t)と小口止天端(x_in)の間に隙間があれば繋ぐ
        if is_gr_kiso and abs(le["tx"] - x_in) > 1e-6:
            msp.add_line((le["tx"], k_top_y), (x_in, k_top_y), dxfattribs={"layer": "TOP"})
        # ③ 小口止延長寸法線
        _dim = msp.add_linear_dim(
            base=(x_out, global_dim_top_y),
            p1=(x_out, k_top_y), p2=(x_in, k_top_y),
            dimstyle="Standard", dxfattribs={"layer": "DIM"}
        )
        _dim.render()
        _fix_arrows_outward(doc, [_dim], 2.5 * scale)

    if koguchi_type in ["right", "both"] and right_end:
        re      = right_end
        k_top_y = get_koguchi_top_y(re)
        x_in    = max(re["tx"], re["bx"])   # 上下辺のうち外側（右=大きい方）
        x_out   = x_in + KOGUCHI_CUT
        msp.add_line((x_in,  k_top_y),         (x_out, k_top_y),         dxfattribs={"layer": "KOGUCHI"})
        msp.add_line((x_out, k_top_y),         (x_out, re["stone_bot"]), dxfattribs={"layer": "KOGUCHI"})
        msp.add_line((x_out, re["stone_bot"]), (x_in,  re["stone_bot"]), dxfattribs={"layer": "KOGUCHI"})
        msp.add_line((x_in,  re["stone_bot"]), (x_in,  k_top_y),         dxfattribs={"layer": "KOGUCHI"})
        # GR基礎：GR天端の縦線(tx,top-tenba_t)と小口止天端(x_in)の間に隙間があれば繋ぐ
        if is_gr_kiso and abs(re["tx"] - x_in) > 1e-6:
            msp.add_line((re["tx"], k_top_y), (x_in, k_top_y), dxfattribs={"layer": "TOP"})
        _dim = msp.add_linear_dim(
            base=(x_in, global_dim_top_y),
            p1=(x_in, k_top_y), p2=(x_out, k_top_y),
            dimstyle="Standard", dxfattribs={"layer": "DIM"}
        )
        _dim.render()
        _fix_arrows_outward(doc, [_dim], 2.5 * scale)

    # =========================================================
    # 延長計算
    # =========================================================
    koguchi_deduction_mm = 0.0
    if koguchi_type in ["left",  "both"]: koguchi_deduction_mm += KOGUCHI_CUT
    if koguchi_type in ["right", "both"]: koguchi_deduction_mm += KOGUCHI_CUT

    tenba_actual_mm = sum(upper_extension) * MM - koguchi_deduction_mm
    kiso_actual_mm  = sum(lower_extension) * MM - koguchi_deduction_mm
    koguchi_mm      = koguchi_deduction_mm

    # 小口止高さ（左右の平均）
    koguchi_h_mm = 0.0
    koguchi_h_count = 0
    if koguchi_type in ["left", "both"] and left_end:
        le = left_end
        k_top_y = get_koguchi_top_y(le)
        koguchi_h_mm += k_top_y - le["stone_bot"]
        koguchi_h_count += 1
    if koguchi_type in ["right", "both"] and right_end:
        re = right_end
        k_top_y = get_koguchi_top_y(re)
        koguchi_h_mm += k_top_y - re["stone_bot"]
        koguchi_h_count += 1
    if koguchi_h_count > 0:
        koguchi_h_mm /= koguchi_h_count

    # ⑦ 総延長（小口止含む長い方）
    total_upper_mm = sum(upper_extension) * MM
    total_lower_mm = sum(lower_extension) * MM
    total_mm = max(total_upper_mm, total_lower_mm) 
    # =========================================================
    # ② 天端コンクリート総延長寸法線（GR基礎は小口止部も含めた全体のGR基礎長）
    # =========================================================
    gr_len_mm = tenba_actual_mm + koguchi_deduction_mm if is_gr_kiso else tenba_actual_mm

    tenba_con_x1 = distances[0]
    if not is_gr_kiso and koguchi_type in ["left", "both"]:
        tenba_con_x1 += KOGUCHI_CUT
    tenba_con_x2 = tenba_con_x1 + gr_len_mm

    if is_gr_kiso:
        # 小口止を含む起終点＝測点そのものの位置
        tenba_p1_x, tenba_p1_y = distances[0],  top_els[0]
        tenba_p2_x, tenba_p2_y = distances[-1], top_els[-1]
    else:
        tenba_p1_x, tenba_p1_y = left_end["tx"],  left_end["top"]
        tenba_p2_x, tenba_p2_y = right_end["tx"], right_end["top"]

    tenba_dim_y = span_dim_y + (8.0 * scale)
    _dim = msp.add_linear_dim(
        base=(tenba_p1_x, tenba_dim_y),
        p1=(tenba_p1_x, tenba_p1_y),
        p2=(tenba_p2_x, tenba_p2_y),
        dimstyle="KISO_DIM_NOTEXT", dxfattribs={"layer": "DIM"}
    )
    _dim.render()
    _fix_arrows_outward(doc, [_dim], 2.5 * scale)
    tenba_label_x = (tenba_con_x1 + tenba_con_x2) / 2.0
    tenba_label_y = tenba_dim_y + text_height * 0.5
    tenba_label_text = f"GR基礎L={gr_len_mm/MM:.2f}m" if is_gr_kiso else f"天端コンクリートL={gr_len_mm/MM:.2f}m"
    t = msp.add_mtext(tenba_label_text, dxfattribs={"layer": "DIM", "char_height": text_height, "style": "MS-GOTHIC"})
    t.dxf.insert = (tenba_label_x, tenba_label_y)
    t.dxf.attachment_point = 5  # 中央

    # ② 基礎コンクリート総延長寸法線
    kiso_con_x1     = left_end["bx"]  if left_end  else distances[0]
    kiso_con_x2     = right_end["bx"] if right_end else distances[-1]
    _last_pt_idx    = len(bottom_els) - 1
    stone_bot_left  = left_end["stone_bot"]  if left_end  else (bottom_els[0]  - _point_kiso_h(0)[0]            - _point_kiso_h(0)[1])
    stone_bot_right = right_end["stone_bot"] if right_end else (bottom_els[-1] - _point_kiso_h(_last_pt_idx)[0] - _point_kiso_h(_last_pt_idx)[1])

    kiso_dim_y = global_dim_bot_y - (8.0 * scale)

    # 基礎形式・岩盤区分が区間で複数種類ある場合、区間ごとの対長を個別の段に追加する
    # （全体合計の対長線はこの外側＝さらに下へ押し出して残す）
    _kiso_foundation_types = data.get("foundation_types") or [data.get("foundation_type")] * num_spans
    _kiso_rock_types       = data.get("rock_types") or [data.get("rock_type")] * num_spans
    kiso_segments = _kiso_segments(_kiso_foundation_types, _kiso_rock_types, num_spans)

    # 区間ごとの基礎コンクリート延長（工種ごとの内訳）。09が工種ごとに計算・集計する際に使う。
    # 種類が1つだけの場合も含めて常に書き出す。
    kiso_by_kind = []
    for s0, s1, (seg_ft, seg_rt) in kiso_segments:
        seg_len_mm = sum(lower_extension[s0:s1 + 1]) * MM
        if s0 == 0             and koguchi_type in ["left",  "both"]: seg_len_mm -= KOGUCHI_CUT
        if s1 == num_spans - 1 and koguchi_type in ["right", "both"]: seg_len_mm -= KOGUCHI_CUT
        kiso_by_kind.append({
            "foundation_type": seg_ft,
            "rock_type":       seg_rt,
            "span_start":      s0,
            "span_end":        s1,
            "length_m":        round(seg_len_mm / MM, 3),
        })

    if len(kiso_segments) > 1:
        kiso_seg_dim_y = kiso_dim_y
        kiso_dim_y     = kiso_seg_dim_y - (8.0 * scale)

        for (s0, s1, (seg_ft, seg_rt)), kbk in zip(kiso_segments, kiso_by_kind):
            seg_x1 = left_end["bx"]  if s0 == 0             else all_shapes[s0]["bottom_line"][0][0]
            seg_x2 = right_end["bx"] if s1 == num_spans - 1 else all_shapes[s1]["bottom_line"][1][0]
            seg_y1 = stone_bot_left  if s0 == 0             else \
                (all_shapes[s0]["bottom_line"][0][1] - _span_kiso_h(s0)[0] - _span_kiso_h(s0)[1])
            seg_y2 = stone_bot_right if s1 == num_spans - 1 else \
                (all_shapes[s1]["bottom_line"][1][1] - _span_kiso_h(s1)[0] - _span_kiso_h(s1)[1])

            seg_len_mm = kbk["length_m"] * MM

            _dim = msp.add_linear_dim(
                base=(seg_x1, kiso_seg_dim_y),
                p1=(seg_x1, seg_y1), p2=(seg_x2, seg_y2),
                dimstyle="KISO_DIM_NOTEXT", dxfattribs={"layer": "DIM"}
            )
            _dim.render()
            _fix_arrows_outward(doc, [_dim], 2.5 * scale)
            seg_label_x = (seg_x1 + seg_x2) / 2.0
            seg_label_y = kiso_seg_dim_y - text_height * 0.5
            seg_label = (f"基礎コンクリートL({_foundation_kind_label(seg_ft, seg_rt)})"
                         f"={seg_len_mm / MM:.2f}m")
            t = msp.add_mtext(seg_label, dxfattribs={"layer": "DIM", "char_height": text_height, "style": "MS-GOTHIC"})
            t.dxf.insert = (seg_label_x, seg_label_y)
            t.dxf.attachment_point = 5

    _dim = msp.add_linear_dim(
        base=(kiso_con_x1, kiso_dim_y),
        p1=(kiso_con_x1, stone_bot_left),
        p2=(kiso_con_x2, stone_bot_right),
        dimstyle="KISO_DIM_NOTEXT", dxfattribs={"layer": "DIM"}
    )
    _dim.render()
    _fix_arrows_outward(doc, [_dim], 2.5 * scale)
    kiso_label_x = (kiso_con_x1 + kiso_con_x2) / 2.0
    kiso_label_y = kiso_dim_y - text_height * 0.5
    t = msp.add_mtext(f"基礎コンクリートL={kiso_actual_mm/MM:.2f}m", dxfattribs={"layer": "DIM", "char_height": text_height, "style": "MS-GOTHIC"})
    t.dxf.insert = (kiso_label_x, kiso_label_y)
    t.dxf.attachment_point = 5

    # ③ 小口止コンクリート高さ寸法線
    for i, (x, top, bot) in enumerate(zip(distances, top_els, bottom_els)):
        v_base_x = x - dim_offset if i == 0 else x + dim_offset

        if i == 0 and koguchi_type in ["left", "both"] and left_end:
            le = left_end
            k_top_y  = get_koguchi_top_y(le)
            kx_in    = min(le["tx"], le["bx"])
            koguchi_dim_x = v_base_x - (8.0 * scale)
            h_val_m  = (k_top_y - le["stone_bot"]) / MM
            dim = msp.add_linear_dim(
                base=(koguchi_dim_x, le["stone_bot"]),
                p1=(kx_in, k_top_y), p2=(kx_in, le["stone_bot"]),
                angle=90, dimstyle="KOGUCHI_DIM", dxfattribs={"layer": "DIM"}
            )
            dim.dimension.dxf.text = f"小口止コンクリート  H={h_val_m:.2f}m"
            dim.render()
            _fix_arrows_outward(doc, [dim], 2.5 * scale)
            _fix_text_outside_dim(doc, [dim])

        if i == len(distances) - 1 and koguchi_type in ["right", "both"] and right_end:
            re = right_end
            k_top_y  = get_koguchi_top_y(re)
            kx_in    = max(re["tx"], re["bx"])
            koguchi_dim_x = v_base_x + (8.0 * scale)
            h_val_m  = (k_top_y - re["stone_bot"]) / MM
            dim = msp.add_linear_dim(
                base=(koguchi_dim_x, re["stone_bot"]),
                p1=(kx_in, k_top_y), p2=(kx_in, re["stone_bot"]),
                angle=90, dimstyle="KOGUCHI_DIM", dxfattribs={"layer": "DIM"}
            )
            dim.dimension.dxf.text = f"小口止コンクリート  H={h_val_m:.2f}m"
            dim.render()
            _fix_arrows_outward(doc, [dim], 2.5 * scale)
            _fix_text_outside_dim(doc, [dim])

    # =========================================================
    # ⑦ 総延長寸法線（一番上）
    # =========================================================
    total_x1 = distances[0]
    total_x2 = total_x1 + total_mm

    total_dim_y = tenba_dim_y + (8.0 * scale)
    _dim = msp.add_linear_dim(
        base=(total_x1, total_dim_y),
        p1=(total_x1, top_els[0]),
        p2=(total_x2, top_els[-1]),
        dimstyle="KISO_DIM_NOTEXT", dxfattribs={"layer": "DIM"}
    )
    _dim.render()
    _fix_arrows_outward(doc, [_dim], 2.5 * scale)
    total_label_x = (total_x1 + total_x2) / 2.0
    total_label_y = total_dim_y + text_height * 0.5
    t = msp.add_mtext(f"総延長　L={total_mm/MM:.2f}m", dxfattribs={"layer": "DIM", "char_height": text_height, "style": "MS-GOTHIC"})
    t.dxf.insert = (total_label_x, total_label_y)
    t.dxf.attachment_point = 5

    # =========================================================
    # 表題（図の上・中央）
    # =========================================================
    cx       = total_label_x
    ty_scale = total_label_y + (6.0 + 30.0 - 15.0) * scale  # "S=1/**"  5mm (+3cm上移動、-1.5cm下移動)
    ty_tenkai= ty_scale      + 8.0 * scale          # "展開図"  7mm

    for txt, ty, th in [
        ("展開図",              ty_tenkai, 7.0 * scale),
        (f"S=1/{int(scale)}", ty_scale,  5.0 * scale),
    ]:
        t_obj = msp.add_text(txt, height=th, dxfattribs={"layer": "TEXT", "style": "MS-GOTHIC"})
        t_obj.dxf.halign      = 1
        t_obj.dxf.insert      = (cx, ty)
        t_obj.dxf.align_point = (cx, ty)

    # =========================================================
    # 測点名・EL表示
    # =========================================================
    for i, (x, top, bot, ume) in enumerate(zip(distances, top_els, bottom_els, umemodoshi_els)):
        el_x = x - dim_offset + text_height * 0.5 if i == 0 else x + text_height
        _sign = 1 if i == 0 else -1

        if is_gr_kiso:
            _draw_leader_label(msp, (x, top), f"EL={top/MM:.2f}", _sign, text_height, scale, "TEXT")
        else:
            msp.add_text(f"EL={top/MM:.2f}", height=text_height, dxfattribs={"layer": "TEXT", "style": "MS-GOTHIC"}).set_placement((el_x, top + text_height))

        msp.add_text(f"EL={bot/MM:.2f}", height=text_height, dxfattribs={"layer": "TEXT", "style": "MS-GOTHIC"}).set_placement((el_x, bot + text_height * 0.5))

        _draw_leader_label(msp, (x, ume), f"EL={ume/MM:.2f}", _sign, text_height, scale, "UMEMODOSHI")

    for x, top, name in zip(distances, top_els, point_names):
        t_obj = msp.add_text(name, height=text_height, dxfattribs={"layer": "TEXT", "style": "MS-GOTHIC"})
        t_obj.dxf.rotation = 90.0
        t_obj.set_placement((x - text_height * 0.5, top + text_height * 4))

    # =========================================================
    # 縦方向ブロック直高寸法線 & ④ 法長（HB）
    # =========================================================
    for i, (x, top, bot, h) in enumerate(zip(distances, top_els, bottom_els, block_heights)):
        v_base_x = x - dim_offset if i == 0 else x + dim_offset

        dim_top = (top - tenba_t) if is_gr_kiso else top

        dim_h1 = msp.add_linear_dim(
            base=(v_base_x, bot), p1=(x, bot), p2=(x, dim_top),
            angle=90, dimstyle="VERT_DIM", dxfattribs={"layer": "DIM"}
        )
        dim_h1.render()
        _fix_arrows_outward(doc, [dim_h1], 2.5 * scale)

        # ④ HBを直高寸法値のすぐ右隣に縦書き（直高数値と高さを揃える）
        hb_val   = (h - tenba_con_height) * slope_ratio
        tx       = v_base_x + text_height * 1.5 - 3.0 * scale
        dim_ty   = _get_dim_text_y(doc, dim_h1)
        ty       = dim_ty if dim_ty is not None else (dim_top + bot) / 2.0
        hb_txt  = msp.add_text(f"HB={hb_val:.2f}", height=text_height, dxfattribs={"layer": "TEXT", "style": "MS-GOTHIC"})
        hb_txt.dxf.rotation = 90.0
        hb_txt.set_placement((tx, ty), align=TextEntityAlignment.MIDDLE_CENTER)

    # =========================================================
    # ⑥ 目地（点線＋「目地材」テキスト）
    # =========================================================
    sum_upper       = sum(upper_extension)
    sum_lower       = sum(lower_extension)
    max_total_len_m = max(sum_upper, sum_lower)
    meji_count      = max(0, math.ceil(max_total_len_m / 10.0) - 1)

    meji_records = []

    if meji_count > 0:
        num_meji_segments = meji_count + 1
        total_extension_x = distances[-1] - distances[0]
        meji_interval_x   = total_extension_x / num_meji_segments

        for m_idx in range(1, num_meji_segments):
            meji_x = distances[0] + (meji_interval_x * m_idx)

            for s in range(len(distances) - 1):
                if distances[s] <= meji_x <= distances[s + 1]:
                    ratio            = (meji_x - distances[s]) / (distances[s + 1] - distances[s])
                    meji_top_y       = top_els[s]    + (top_els[s+1]    - top_els[s])    * ratio
                    meji_bot_y       = bottom_els[s] + (bottom_els[s+1] - bottom_els[s]) * ratio
                    _meji_h1, _meji_h2 = _span_kiso_h(s)
                    meji_stone_bot_y = meji_bot_y - _meji_h1 - _meji_h2

                    # ⑥ 点線
                    msp.add_line(
                        (meji_x, meji_top_y), (meji_x, meji_stone_bot_y),
                        dxfattribs={"layer": "MEJI_LINE", "linetype": "DASHED"}
                    )

                    # ⑥ 「目地材」テキスト（目地線の右に縦書き）
                    meji_text_x = meji_x + text_height * 0.8
                    meji_text_y = (meji_top_y + meji_bot_y) / 2.0
                    t_meji = msp.add_text("目地材", height=text_height, dxfattribs={"layer": "TEXT", "style": "MS-GOTHIC"})
                    t_meji.dxf.rotation = 90.0
                    t_meji.set_placement((meji_text_x, meji_text_y))

                    # H・HB テキスト（目地材の右隣）
                    meji_h_m  = (meji_top_y - meji_bot_y) / MM
                    meji_hb_m = (meji_h_m - tenba_con_height) * slope_ratio
                    meji_text_x_h  = meji_x + text_height * 2.2
                    meji_text_x_hb = meji_x + text_height * 3.6

                    t_h = msp.add_text(f"H ={meji_h_m:.2f}", height=text_height, dxfattribs={"layer": "TEXT", "style": "MS-GOTHIC"})
                    t_h.dxf.rotation = 90.0
                    t_h.set_placement((meji_text_x_h, meji_text_y))

                    t_hb = msp.add_text(f"HB={meji_hb_m:.2f}", height=text_height, dxfattribs={"layer": "TEXT", "style": "MS-GOTHIC"})
                    t_hb.dxf.rotation = 90.0
                    t_hb.set_placement((meji_text_x_hb, meji_text_y))

                    meji_records.append({
                        "x_mm":    meji_x,
                        "h_m":     meji_h_m,
                        "hocho_m": round(meji_hb_m, 3),
                    })
                    break

    # =========================================================
    # ファイル保存
    # =========================================================
    tenkai_json = os.path.join(output_dir, "tenkai_data.json")
    tenkai_data = {
        "spans":               all_shapes,
        "tenba_actual_m":      tenba_actual_mm / MM,
        "kiso_actual_m":       kiso_actual_mm / MM,
        "kiso_by_kind":        kiso_by_kind,
        "koguchi_deduction_m": koguchi_deduction_mm / MM,
        "meji":                meji_records,
    }
    with open(tenkai_json, "w", encoding="utf-8") as f:
        json.dump(tenkai_data, f, indent=2, ensure_ascii=False)

    output_dxf = os.path.join(output_dir, "tenkai.dxf")
    doc.saveas(output_dxf)
    print(f"    生成成功: tenkai.dxf")
    print(f"    データ出力成功: tenkai_data.json")

if __name__ == "__main__":
    main(".", scale=50)