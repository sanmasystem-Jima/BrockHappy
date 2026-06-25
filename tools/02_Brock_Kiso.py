import json
import math
import os
import ezdxf
from ezdxf.enums import TextEntityAlignment

def load_project(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    a_cm = int(data.get("block_hikae", 0) * 100)
    b_cm = int(data.get("ura_con_thickness", 0) * 100)
    struct_type = data.get("structure_type", "road")

    # (控え長cm, 裏コン厚cm) → (H1, B1, H3, B2, H2_kiso, 型枠m2, コンクリートm3)
    table = {
        (30, 0):  (23, 39, 10, 10, 15, 3.3, 0.71),
        (35, 0):  (25, 43, 10, 10, 15, 3.5, 0.83),
        (35, 10): (30, 52, 10, 10, 15, 4.0, 1.14),
        (35, 15): (35, 55, 10, 10, 15, 4.5, 1.36),
    }

    dims = table.get((a_cm, b_cm), (30, 52, 10, 10, 15, 4.0, 1.14))

    # H2は構造種別で決定
    h2 = 100 if struct_type == "river" else 150

    return {
        "H1": dims[0] * 10,
        "B1": dims[1] * 10,
        "H3": dims[2] * 10,
        "B2": dims[3] * 10,
        "H2": h2,
        "type": struct_type,
        "kata_waku_m2": dims[5],   # 型枠 m²/10m（基礎コン）
        "concrete_m3":  dims[6],   # コンクリート m³/10m（基礎コン）
    }

def calc_quantities(d):
    """数量計算（10mあたり）"""
    offset_val = 100
    full_w_m   = (d["B1"] + 2 * offset_val) / 1000.0
    h2_m       = d["H2"] / 1000.0
    is_river   = (d["type"] == "river")

    q = {
        "note":          "10mあたり",
        "concrete_m3":   d["concrete_m3"],
        "kata_waku_m2":  d["kata_waku_m2"],
    }
    if is_river:
        q["narashi_m3"]      = round(full_w_m * h2_m * 10.0, 2)
        q["narashi_kata_m2"] = round(2 * h2_m * 10.0, 2)
    else:
        q["saiseki_m2"] = round(full_w_m * 10.0, 2)
    return q

def export_json(d, output_dir):
    offset_val      = 100
    foundation_type = "砕石基礎" if d["type"] == "road" else "均しコンクリート"

    data = {
        "metadata": {
            "origin": "Block front-bottom corner",
            "unit": "mm",
            "foundation_material": foundation_type
        },
        "points": {
            "base_top_front":              [100 - d["B2"], 0],
            "base_top_back":               [100, 0],
            "base_bottom_front":           [100 - d["B2"], -d["H1"]],
            "base_bottom_back":            [100 + (d["B1"] - d["B2"]), -d["H1"]],
            "base_toe_top":                [100 + (d["B1"] - d["B2"]), -d["H1"] + d["H3"]],
            "foundation_bottom_front_ext": [100 - d["B2"] - offset_val, -d["H1"] - d["H2"]],
            "foundation_bottom_back_ext":  [100 + (d["B1"] - d["B2"]) + offset_val, -d["H1"] - d["H2"]],
            "foundation_top_front_ext":    [100 - d["B2"] - offset_val, -d["H1"]],
            "foundation_top_back_ext":     [100 + (d["B1"] - d["B2"]) + offset_val, -d["H1"]],
        },
        "dimensions": d,
        "quantities":  calc_quantities(d),
    }

    out_path = os.path.join(output_dir, "kiso_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    return out_path

def export_dxf(d, scale_n, output_dir):
    doc = ezdxf.new("R2010", setup=True)
    doc.header['$INSUNITS'] = 4
    msp = doc.modelspace()
    s = 1.0 / scale_n

    # =========================================================
    # 断面形状
    # =========================================================
    conc_points = [
        (0, 0),
        (-d["B2"] * s, 0),
        (-d["B2"] * s, -d["H1"] * s),
        ((d["B1"] - d["B2"]) * s, -d["H1"] * s),
        ((d["B1"] - d["B2"]) * s, (-d["H1"] + d["H3"]) * s),
        (0, 0)
    ]
    msp.add_lwpolyline(conc_points, close=True)

    offset_val = 100
    base_points = [
        ((-d["B2"] - offset_val) * s,               -d["H1"] * s),
        ((d["B1"] - d["B2"] + offset_val) * s,       -d["H1"] * s),
        ((d["B1"] - d["B2"] + offset_val) * s,       (-d["H1"] - d["H2"]) * s),
        ((-d["B2"] - offset_val) * s,               (-d["H1"] - d["H2"]) * s),
    ]
    msp.add_lwpolyline(base_points, close=True)

    # =========================================================
    # 寸法線
    # =========================================================
    txt_h = 3.5
    asz   = 2.5
    dist  = 20.0

    attribs = {
        'dimtxt': txt_h,
        'dimasz': asz,
        'dimexo': 15.0,
        'dimexe': 3.0,
        'dimtix': 0,
        'dimblk': "OPEN",
        'dimlwd': 13,
        'dimlwe': 13,
        'dimclrd': 7,
        'dimclre': 7,
        'dimclrt': 7
    }

    # 左：H1
    dim_h1 = msp.add_linear_dim(
        base=(-d["B2"] * s - dist, 0),
        p1=(-d["B2"] * s, 0),
        p2=(-d["B2"] * s, -d["H1"] * s),
        angle=90, override=attribs
    )
    dim_h1.dimension.dxf.text = str(int(d["H1"]))
    dim_h1.render()

    # 上：B2（頂部の平らな部分の幅）
    dim_b2 = msp.add_linear_dim(
        base=(0, dist / 2),
        p1=(-d["B2"] * s, 0),
        p2=(0, 0),
        angle=0, override=attribs
    )
    dim_b2.dimension.dxf.text = str(int(d["B2"]))
    dim_b2.render()

    # 上：B1
    dim_b1 = msp.add_linear_dim(
        base=(0, dist),
        p1=(-d["B2"] * s, 0),
        p2=((d["B1"] - d["B2"]) * s, 0),
        angle=0, override=attribs
    )
    dim_b1.dimension.dxf.text = str(int(d["B1"]))
    dim_b1.render()

    right_x = (d["B1"] - d["B2"] + offset_val) * s

    # 右上：H3
    dim_h3 = msp.add_linear_dim(
        base=(right_x + dist, (-d["H1"] + d["H3"]) * s),
        p1=(right_x, (-d["H1"] + d["H3"]) * s),
        p2=(right_x, -d["H1"] * s),
        angle=90, override=attribs
    )
    dim_h3.dimension.dxf.text = str(int(d["H3"]))
    dim_h3.render()

    # 右下：H2
    dim_h2 = msp.add_linear_dim(
        base=(right_x + dist, -d["H1"] * s),
        p1=(right_x, -d["H1"] * s),
        p2=(right_x, (-d["H1"] - d["H2"]) * s),
        angle=90, override=attribs
    )
    dim_h2.dimension.dxf.text = str(int(d["H2"]))
    dim_h2.render()

    # 高さ寸法（H1・H3・H2）の矢印を外向きに統一
    _fix_arrows_outward(doc, [dim_h1, dim_h3, dim_h2], asz)

    # 下：全幅
    full_w = d["B1"] + 2 * offset_val
    dim_total = msp.add_linear_dim(
        base=(0, (-d["H1"] - d["H2"]) * s - dist),
        p1=((-d["B2"] - offset_val) * s, (-d["H1"] - d["H2"]) * s),
        p2=((d["B1"] - d["B2"] + offset_val) * s, (-d["H1"] - d["H2"]) * s),
        angle=0, override=attribs
    )
    dim_total.dimension.dxf.text = str(int(full_w))
    dim_total.render()

    # =========================================================
    # 表題（図の上・中央）
    # =========================================================
    center_x = ((d["B1"] - 2 * d["B2"]) / 2) * s
    y_scale  = dist + 8.0     # "S=1/**" (5mm)
    y_title  = y_scale + 10.0 # "基礎コンクリート" (7mm)

    t1 = msp.add_text("基礎コンクリート", dxfattribs={"height": 7.0})
    t1.dxf.insert      = (center_x, y_title)
    t1.dxf.halign      = 1
    t1.dxf.align_point = (center_x, y_title)

    t2 = msp.add_text(f"S=1/{int(scale_n)}", dxfattribs={"height": 5.0})
    t2.dxf.insert      = (center_x, y_scale)
    t2.dxf.halign      = 1
    t2.dxf.align_point = (center_x, y_scale)

    # ラベル
    label = "砕石基礎" if d["type"] == "road" else "均しコンクリート"
    cx = (base_points[0][0] + base_points[1][0]) / 2
    cy = (base_points[0][1] + base_points[2][1]) / 2
    text = msp.add_text(label, dxfattribs={"height": txt_h})
    text.dxf.insert = (cx, cy)
    text.dxf.halign = 1
    text.dxf.valign = 2
    text.dxf.align_point = (cx, cy)

    # =========================================================
    # 数量表（断面図の下に配置）
    # =========================================================
    is_river = (d["type"] == "river")

    q = calc_quantities(d)
    conc_m3         = q["concrete_m3"]
    kata_m2         = q["kata_waku_m2"]
    narashi_m3      = q.get("narashi_m3", 0.0)
    narashi_kata_m2 = q.get("narashi_kata_m2", 0.0)
    saiseki_m2      = q.get("saiseki_m2", 0.0)

    # 表の配置原点（断面図の下）
    table_origin_y = (-d["H1"] - d["H2"]) * s - dist - 15.0
    table_origin_x = (-d["B2"] - offset_val) * s
    cell_txt_h = txt_h * 0.9       # セル内文字の実高さ
    cell_h = cell_txt_h + 2 * 1.5  # 文字の上下1.5mmに罫線

    def draw_table(rows, title, ox, oy):
        """表を描画する"""
        headers = ["項目", "細目", "単位", "数量"]
        pad = 4.0  # 左右の余白
        col_w = []
        for col_idx, hdr in enumerate(headers):
            max_len = len(hdr)
            for row in rows:
                max_len = max(max_len, len(str(row[col_idx])))
            col_w.append(max_len * cell_txt_h + pad)
        total_w = sum(col_w)

        row_count = len(rows) + 1  # ヘッダー含む
        table_h   = cell_h * row_count

        # タイトル（表幅の中心に基準点）
        msp.add_text(title, dxfattribs={"height": txt_h}).set_placement(
            (ox + total_w / 2, oy + txt_h), align=TextEntityAlignment.BOTTOM_CENTER
        )

        # 右上に「10mあたり」（表幅からはみ出さないよう右端基準）
        msp.add_text("10mあたり", dxfattribs={"height": txt_h * 0.8}).set_placement(
            (ox + total_w, oy + txt_h), align=TextEntityAlignment.BOTTOM_RIGHT
        )

        # 外枠
        msp.add_lwpolyline([
            (ox, oy), (ox + total_w, oy),
            (ox + total_w, oy - table_h),
            (ox, oy - table_h), (ox, oy)
        ], close=True)

        # ヘッダー行（単位列だけセル中央揃え）
        unit_col = headers.index("単位")
        x = ox
        for col_idx, (hdr, cw) in enumerate(zip(headers, col_w)):
            msp.add_line((x, oy), (x, oy - table_h))
            if col_idx == unit_col:
                msp.add_text(hdr, dxfattribs={"height": txt_h * 0.9}).set_placement(
                    (x + cw / 2, oy - cell_h / 2), align=TextEntityAlignment.MIDDLE_CENTER
                )
            else:
                msp.add_text(hdr, dxfattribs={"height": txt_h * 0.9}).set_placement(
                    (x + 2, oy - cell_h / 2 - cell_txt_h / 2)
                )
            x += cw
        msp.add_line((ox, oy - cell_h), (ox + total_w, oy - cell_h))

        # データ行
        for r_idx, row in enumerate(rows):
            row_y = oy - cell_h * (r_idx + 1)
            msp.add_line((ox, row_y), (ox + total_w, row_y))
            x = ox
            for col_idx, (val, cw) in enumerate(zip(row, col_w)):
                txt = msp.add_text(str(val), dxfattribs={"height": txt_h * 0.9})
                if col_idx == unit_col:
                    txt.set_placement((x + cw / 2, row_y - cell_h / 2), align=TextEntityAlignment.MIDDLE_CENTER)
                else:
                    txt.set_placement((x + 2, row_y - cell_h / 2 - cell_txt_h / 2))
                x += cw

    if is_river:
        rows = [
            ["コンクリート",       "18kn/mm2",    "m3", f"{conc_m3:.2f}"],
            ["型枠",               "小型構造物",  "m2", f"{kata_m2:.2f}"],
            ["均しコンクリート",   "18kn/mm2",    "m3", f"{narashi_m3:.2f}"],
            ["均しコンクリート型枠","小型構造物", "m2", f"{narashi_kata_m2:.2f}"],
        ]
        draw_table(rows, "基礎工　数量表", table_origin_x, table_origin_y)
    else:
        rows = [
            ["コンクリート", "18kn/mm2",       "m3", f"{conc_m3:.2f}"],
            ["型枠",         "小型構造物",     "m2", f"{kata_m2:.2f}"],
            ["砕石基礎",     "RC-40　15cm厚",  "m2", f"{saiseki_m2:.2f}"],
        ]
        draw_table(rows, "基礎工　数量表", table_origin_x, table_origin_y)

    out_path = os.path.join(output_dir, "kiso_danmen.dxf")
    doc.saveas(out_path)
    return out_path

# =========================================================
# 岩着基礎
# =========================================================

def _draw_table(msp, title, subtitle, rows, col_w, t_h, c_h, ox, oy):
    tw = sum(col_w)
    n_rows = len(rows) + 1
    msp.add_text(title, dxfattribs={"height": t_h}).set_placement((ox, oy + t_h))
    if subtitle:
        msp.add_text(subtitle, dxfattribs={"height": t_h * 0.8}).set_placement(
            (ox + tw - 5, oy + t_h))
    msp.add_lwpolyline([
        (ox, oy), (ox+tw, oy), (ox+tw, oy-c_h*n_rows),
        (ox, oy-c_h*n_rows), (ox, oy)], close=True)
    hx = ox
    hdrs = ["測点", "Hp(m)", "面積(m²)"] if len(col_w) == 3 else ["項目", "細目", "単位", "数量"]
    for hdr, w in zip(hdrs, col_w):
        msp.add_line((hx, oy), (hx, oy - c_h * n_rows))
        msp.add_text(hdr, dxfattribs={"height": t_h * 0.9}).set_placement(
            (hx + w/2, oy - c_h/2 - t_h/2))
        hx += w
    msp.add_line((ox, oy - c_h), (ox + tw, oy - c_h))
    for ri, row in enumerate(rows):
        ry = oy - c_h * (ri + 1)
        msp.add_line((ox, ry), (ox + tw, ry))
        rx = ox
        for val, w in zip(row, col_w):
            msp.add_text(str(val), dxfattribs={"height": t_h * 0.9}).set_placement(
                (rx + 2, ry - c_h/2 - t_h/2))
            rx += w

def load_project_rock(path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    rock_type   = raw.get("rock_type", "nangan1")
    front_slope = float(raw.get("front_slope", 0.3))
    block_hikae = float(raw.get("block_hikae", 0.35))
    if rock_type == "nangan1":
        t_m, N, rock_label = 0.50, 0.2, "軟岩Ⅰ"
    else:
        t_m, N, rock_label = 0.30, 0.1, "軟岩Ⅱ以上"
    return {
        "rock_type":   rock_type,
        "rock_label":  rock_label,
        "t_m":         t_m,
        "N":           N,
        "A":           front_slope,
        "B":           0.10,
        "peline":      0.05,
        "block_hikae": block_hikae,
        "point_names": raw.get("point_names", []),
        "Hp_list":     raw.get("backfill_bottoms", []),
    }

def calc_quantities_rock(d):
    t = d["t_m"]; N = d["N"]; A = d["A"]; B = d["B"]
    hikae = d["block_hikae"]; pe = d["peline"]
    joge_top = (A + N) * t + B
    joge_bot = B
    umemodoshi_m3  = round((joge_top + joge_bot) / 2.0 * t * 10.0, 3)
    pe_bottom_m3   = round((hikae + pe) * pe * 10.0, 3)
    nobiri         = math.sqrt(A**2 + 1)
    pe_back_m3     = round(t * nobiri * pe * 10.0, 3)
    return {
        "note":             "10mあたり",
        "umemodoshi_m3":    umemodoshi_m3,
        "peline_bottom_m3": pe_bottom_m3,
        "peline_back_m3":   pe_back_m3,
        "joge_haba_top_m":  round(joge_top, 4),
        "joge_haba_bot_m":  round(joge_bot, 4),
        "neirimi_m":        t,
    }

def _fix_text_above_line(doc, dim_list):
    """render()済み寸法ブロックのテキストを寸法線の外側（上側）に強制移動。"""
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
        is_v = abs(ax1 - ax2) < 0.01  # 垂直寸法: 矢印が同じ x

        # 矢印位置 = 寸法線の座標
        dim_coord = ax1 if is_v else ay1

        # 垂直寸法の場合: 引き出し線の外端 x を取得して「外側」を判定
        ext_coord = None
        if is_v:
            for e in blk:
                if e.dxftype() != "LINE":
                    continue
                s, en = e.dxf.start, e.dxf.end
                if abs(s.y - en.y) < 0.01:  # 水平線 = 引き出し線
                    # 寸法線から遠い端が計測点側
                    ext_coord = s.x if abs(s.x - dim_coord) > abs(en.x - dim_coord) else en.x
                    break

        for e in blk:
            if e.dxftype() != "MTEXT":
                continue
            pos = e.dxf.insert
            if is_v:
                if ext_coord is None:
                    continue
                want_right = ext_coord < dim_coord   # 計測点が左 → テキストは右
                is_right   = pos.x > dim_coord
                if want_right != is_right:
                    e.dxf.insert = (2 * dim_coord - pos.x, pos.y, 0)
            else:
                # 水平寸法: 常に寸法線の上（y が大きい側）へ
                if pos.y < dim_coord:
                    e.dxf.insert = (pos.x, 2 * dim_coord - pos.y, 0)


def _fix_arrows_outward(doc, dim_list, asz):
    """render()済み寸法ブロックの矢印を強制的に外向きへ書き換える。"""
    for dim in dim_list:
        try:
            blk_name = dim.dimension.dxf.geometry
        except Exception:
            continue
        if blk_name not in doc.blocks:
            continue
        blk = doc.blocks[blk_name]

        # 矢印 INSERT を収集 → rotation を +180° 反転
        arrow_pos = []
        for e in blk:
            if e.dxftype() == "INSERT":
                arrow_pos.append((e.dxf.insert.x, e.dxf.insert.y))
                e.dxf.rotation = (e.dxf.rotation + 180.0) % 360.0

        if len(arrow_pos) < 2:
            continue

        # 矢印位置から寸法方向を判定
        (ax1, ay1), (ax2, ay2) = arrow_pos[0], arrow_pos[1]
        is_v = abs(ax1 - ax2) < 0.01   # 垂直寸法: 同じ x

        # 寸法線端点を矢印位置にスナップ（延長線はスキップ）
        for e in blk:
            if e.dxftype() != "LINE":
                continue
            s  = e.dxf.start
            en = e.dxf.end
            if is_v and abs(s.x - en.x) > 0.001:   # 水平線 = 延長線 → スキップ
                continue
            if not is_v and abs(s.y - en.y) > 0.001:  # 垂直線 = 延長線 → スキップ
                continue
            for arr_x, arr_y in arrow_pos:
                if ((s.x - arr_x)**2 + (s.y - arr_y)**2)**0.5 < asz * 2.5:
                    e.dxf.start = (arr_x, arr_y, 0)
                if ((en.x - arr_x)**2 + (en.y - arr_y)**2)**0.5 < asz * 2.5:
                    e.dxf.end   = (arr_x, arr_y, 0)


def export_json_rock(d, output_dir):
    q      = calc_quantities_rock(d)
    A      = d["A"]
    N      = d["N"]
    t      = d["t_m"] * 1000          # 根入れ深さ (mm)
    hikae  = d["block_hikae"] * 1000  # 控え長 (mm)
    B      = d["B"] * 1000            # 下端場 (mm)
    nobiri = math.sqrt(A**2 + 1)

    # ブロック主要点（kiso局所座標）
    # 原点 (0, 0) = 岩盤面×ブロック前面
    # danmen での合わせ方: base_top_back[0,0] → (current_front_btm_x, -H)
    F_bot_x = round(-A * t, 1)
    F_bot_y = round(-t,     1)
    B_bot_x = round(-A * t + hikae / nobiri, 1)
    B_bot_y = round(-t - hikae * A / nobiri, 1)

    out = {
        "metadata": {
            "origin":          "岩盤面×ブロック前面",
            "unit":            "mm",
            "foundation_type": "rock",
            "rock_label":      d["rock_label"],
            "alignment_note":  "base_top_back[0,0] を danmen の (current_front_btm_x, -H) に一致させる",
        },
        "dimensions": {
            "H1":        0,              # 04_互換（岩着は基礎コンなし）
            "H2":        0,              # 04_互換（岩着は砕石なし）
            "neirimi_mm": round(t, 1),
            "A":          A,
            "N":          N,
            "B_mm":       round(B, 1),
            "hikae_mm":   round(hikae, 1),
            "nobiri":     round(nobiri, 4),
        },
        "points": {
            # ── 合わせ点 ──────────────────────────────────────────────
            # danmen の (current_front_btm_x, -H) に一致させる基準点
            "base_top_back":               [0,       0      ],

            # ── ブロック根入れ点 ───────────────────────────────────────
            "base_top_front":              [F_bot_x, F_bot_y],  # F_bot: 前面根入れ深さ点
            "base_bottom_back":            [B_bot_x, B_bot_y],  # B_bot: 背面根入れ深さ点
            "base_bottom_front":           [round(-A * t - B, 1), F_bot_y],  # 埋戻し下端左端
            "base_toe_top":                [round(hikae * nobiri, 1), 0],    # 岩盤面×背面

            # ── 岩盤線・根入れ帯 外縁（100mm 余裕付き）────────────────
            "foundation_top_front_ext":    [round(-(A + N) * t - B - 100, 1), 0      ],
            "foundation_top_back_ext":     [round(hikae * nobiri + 100,    1), 0      ],
            "foundation_bottom_front_ext": [round(-(A + N) * t - B - 100, 1), F_bot_y],
            "foundation_bottom_back_ext":  [round(B_bot_x + 100,           1), B_bot_y],
        },
        "quantities": q,
    }
    out_path = os.path.join(output_dir, "kiso_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=4, ensure_ascii=False)
    return out_path

def export_dxf_rock(d, scale_n, output_dir):
    doc = ezdxf.new("R2010", setup=True)
    doc.header['$INSUNITS'] = 4
    msp = doc.modelspace()
    s = 1.0 / scale_n

    # パラメータ (mm)
    t      = d["t_m"]         * 1000
    N      = d["N"]
    A      = d["A"]
    B      = d["B"]           * 1000   # 100mm
    pe     = d["peline"]      * 1000   # 50mm
    hikae  = d["block_hikae"] * 1000
    nobiri = math.sqrt(A**2 + 1)

    pt_names = d.get("point_names", [])
    Hp_list  = [x for x in d.get("Hp_list", []) if x is not None]

    # ===== カスタム寸法スタイル（矢印外向き）=====
    txt_h   = 3.5
    asz     = 2.5
    dim_off = 15.0
    ds_name = "ROCK_DIM"
    if ds_name not in doc.dimstyles:
        ds = doc.dimstyles.new(ds_name)
        ds.dxf.dimtxt   = txt_h
        ds.dxf.dimasz   = asz
        ds.dxf.dimexo   = 1.0
        ds.dxf.dimexe   = 2.0
        ds.dxf.dimblk   = "OPEN"
        ds.dxf.dimlwd   = 13
        ds.dxf.dimlwe   = 13
        ds.dxf.dimclrd  = 7
        ds.dxf.dimclre  = 7
        ds.dxf.dimclrt  = 7
        ds.dxf.dimatfit = 0
        ds.dxf.dimtad   = 1    # テキストを寸法線の上に配置
        ds.dxf.dimgap   = 1.0  # 線とテキストの隙間 1mm（図上）

    # ===== ブロック主要点 =====
    F_bot = (-A*t,                -t                 )
    B_top = ( hikae/nobiri,       -hikae*A/nobiri     )
    B_bot = (-A*t + hikae/nobiri, -t - hikae*A/nobiri )

    # ===== 埋戻しコンクリート (台形) =====
    ume = [(0, 0), (-(A+N)*t-B, 0), (-A*t-B, -t), (-A*t, -t)]
    msp.add_lwpolyline([(x*s, y*s) for x,y in ume], close=True)

    # ===== ペーライン底面（前面直角方向、幅=控+5cm）=====
    pe_d = (-A/nobiri, -1/nobiri)
    ext  = hikae + pe
    pe_bot_far = (F_bot[0] + ext/nobiri, F_bot[1] - ext*A/nobiri)
    pe_bot_pts = [
        F_bot,
        pe_bot_far,
        (pe_bot_far[0] + pe*pe_d[0], pe_bot_far[1] + pe*pe_d[1]),
        (F_bot[0]      + pe*pe_d[0], F_bot[1]      + pe*pe_d[1]),
    ]
    msp.add_lwpolyline([(x*s, y*s) for x,y in pe_bot_pts], close=True)

    # ===== ペーライン背面（砕石下面まで延伸）=====
    bk_d = (1/nobiri, -A/nobiri)
    saiseki_mm = 200  # 砕石下面 offset (actual mm)
    # 背面ラインの砕石下面レベルでの交点
    B_saiseki = (hikae/nobiri + A*(saiseki_mm + hikae*A/nobiri), saiseki_mm)
    pe_bk_pts = [
        B_bot,
        B_saiseki,
        (B_saiseki[0] + pe*nobiri,   saiseki_mm),
        (B_bot[0]     + pe*bk_d[0], B_bot[1]     + pe*bk_d[1]),
    ]
    msp.add_lwpolyline([(x*s, y*s) for x,y in pe_bk_pts], close=True)

    # ===== ブロック輪郭（前面・背面を1m上まで延長、上面線なし）=====
    ext_up = 1000  # 1000mm = 1m 上に延長
    # 前面：F_bot から 1m上端まで
    msp.add_line((F_bot[0]*s, F_bot[1]*s), (A*ext_up*s, ext_up*s))
    # 底面
    msp.add_line((F_bot[0]*s, F_bot[1]*s), (B_bot[0]*s, B_bot[1]*s))
    # 背面：B_bot から 1m上端まで
    msp.add_line((B_bot[0]*s, B_bot[1]*s),
                 ((B_top[0] + A*ext_up)*s, (B_top[1] + ext_up)*s))

    # ===== 岩盤線（実線）=====
    margin   = 20
    iw_left  = (-(A+N)*t - B - margin) * s
    iw_right = (B_top[0] + pe*bk_d[0] + margin) * s
    msp.add_line((iw_left, 0), (0, 0))  # ブロック前面(x=0)で切って左側のみ

    # ===== 背面砕石下面（ブロック背面交差点を基点に右4cm）=====
    saiseki_y = 200 * s
    msp.add_line((B_saiseki[0]*s, saiseki_y), (B_saiseki[0]*s + 40, saiseki_y))
    msp.add_text("砕石下面", dxfattribs={"height": 3.0}).set_placement(
        (B_saiseki[0]*s + 42, saiseki_y))

    # ===== 寸法線 =====
    # 下端場 B
    b_base_y = F_bot[1]*s - dim_off
    d_b = msp.add_linear_dim(
        base=((-A*t - B/2)*s, b_base_y),
        p1=(F_bot[0]*s, F_bot[1]*s), p2=((-A*t-B)*s, F_bot[1]*s),
        angle=0, dimstyle=ds_name)
    d_b.dimension.dxf.text = str(int(B)); d_b.render()

    # 上端場
    joge_mm = (A+N)*t + B
    d_j = msp.add_linear_dim(
        base=((-joge_mm/2)*s, dim_off),
        p1=(0, 0), p2=(-joge_mm*s, 0),
        angle=0, dimstyle=ds_name)
    d_j.dimension.dxf.text = str(int(round(joge_mm))); d_j.render()

    # 根入れ深さ t → 左側（図上30mm = 3cm）
    lx = (-(A+N)*t - B - dim_off) * s - 30
    d_t = msp.add_linear_dim(
        base=(lx, -t/2*s),
        p1=((-(A+N)*t-B)*s, 0), p2=((-A*t-B)*s, -t*s),
        angle=90, dimstyle=ds_name)
    d_t.dimension.dxf.text = str(int(t)); d_t.render()

    # Hp 寸法線①（砕石下面 → ブロック前面底）
    hp_base_x = (B_top[0] + pe*bk_d[0] + dim_off) * s + 30
    hp_ext_x  = hp_base_x - 8  # 引き出し線をブロック右外側に短縮（図上8mm）
    d_hp1 = msp.add_linear_dim(
        base=(hp_base_x, (saiseki_y + F_bot[1]*s) / 2),
        p1=(hp_ext_x, saiseki_y), p2=(hp_ext_x, F_bot[1]*s),
        angle=90, dimstyle=ds_name)
    d_hp1.dimension.dxf.text = "Hp"; d_hp1.render()

    # Hp 寸法線②（ブロック前面底 → 背面最深部）= 控×勾配/伸び率
    d_hp2 = msp.add_linear_dim(
        base=(hp_base_x, (F_bot[1]*s + B_bot[1]*s) / 2),
        p1=(hp_ext_x, F_bot[1]*s), p2=(hp_ext_x, B_bot[1]*s),
        angle=90, dimstyle=ds_name)
    hp2_val = round(hikae * A / nobiri)
    d_hp2.dimension.dxf.text = f"{int(hikae)}×{A:g}/{nobiri:.3f}={int(hp2_val)}"
    d_hp2.render()

    # ブロック控え寸法（底面、F_bot→B_bot の斜め線そのものの長さ）
    d_hikae = msp.add_aligned_dim(
        p1=(F_bot[0]*s, F_bot[1]*s), p2=(B_bot[0]*s, B_bot[1]*s),
        distance=dim_off, dimstyle=ds_name)
    d_hikae.dimension.dxf.text = str(int(round(hikae)))
    d_hikae.render()

    # 背面ペーライン厚さ寸法（B_bot → B_bot+pe*bk_d、背面に直角な厚さ pe）
    pe_back_end = (B_bot[0] + pe*bk_d[0], B_bot[1] + pe*bk_d[1])
    d_pe_bk = msp.add_aligned_dim(
        p1=(B_bot[0]*s, B_bot[1]*s), p2=(pe_back_end[0]*s, pe_back_end[1]*s),
        distance=dim_off, dimstyle=ds_name)
    d_pe_bk.dimension.dxf.text = str(int(round(pe)))
    d_pe_bk.render()

    # 底面ペーライン厚さ寸法（F_bot → F_bot+pe*pe_d、ブロック底面と岩盤の間、右下に配置）
    pe_bot_end = (F_bot[0] + pe*pe_d[0], F_bot[1] + pe*pe_d[1])
    d_pe_bot = msp.add_aligned_dim(
        p1=(F_bot[0]*s, F_bot[1]*s), p2=(pe_bot_end[0]*s, pe_bot_end[1]*s),
        distance=dim_off, dimstyle=ds_name)
    d_pe_bot.dimension.dxf.text = str(int(round(pe)))
    d_pe_bot.render()

    # ===== 矢印外向き・テキスト外側補正（軸平行の寸法のみ）=====
    _fix_arrows_outward(doc, [d_b, d_j, d_t, d_hp1, d_hp2], asz)
    _fix_text_above_line(doc, [d_b, d_j, d_t, d_hp1, d_hp2])

    # Hp①（"Hp"ラベル）だけ寸法線の左側へ（_fix_text_above_line は右側に強制するため上書き）
    # Hp②（計算式）は右側のまま変更しない
    for dim in (d_hp1,):
        blk_name = dim.dimension.dxf.geometry
        blk = doc.blocks[blk_name]
        arrow_pos = [(e.dxf.insert.x, e.dxf.insert.y)
                     for e in blk if e.dxftype() == "INSERT"]
        dim_coord = arrow_pos[0][0]
        for e in blk:
            if e.dxftype() != "MTEXT":
                continue
            pos = e.dxf.insert
            if pos.x > dim_coord:
                e.dxf.insert = (2 * dim_coord - pos.x, pos.y, 0)

    # ===== 勾配ラベル =====
    # 左側（背面勾配 1:N）: 下→上の方向は (-N*t, t) → angle = atan2(t, -N*t)
    lmx  = ((-(A+N)*t - B + (-A*t - B)) / 2) * s
    ang_N = math.degrees(math.atan2(t, -N*t))
    tN = msp.add_text(f"1:{N:g}", dxfattribs={"height": txt_h})
    tN.dxf.rotation = ang_N
    tN.dxf.halign = 1
    tN.dxf.insert = tN.dxf.align_point = (lmx, -t/2*s)

    # 右側（前面勾配 1:A）: 下→上の方向は (A*t, t) → angle = atan2(t, A*t)
    rmx  = F_bot[0]*s / 2
    ang_A = math.degrees(math.atan2(t, A*t))
    tA = msp.add_text(f"1:{A:g}", dxfattribs={"height": txt_h})
    tA.dxf.rotation = ang_A
    tA.dxf.halign = 1
    tA.dxf.insert = tA.dxf.align_point = (rmx, -t/2*s)

    # ===== 埋戻しコン断面積（計算式テキスト）=====
    t_h2 = 3.0
    c_h2 = t_h2 * 3.0
    ox_t = iw_left
    oy_t = F_bot[1]*s - dim_off - 15.0

    t_m_val = t / 1000
    B_m_val = B / 1000
    top_m   = (A + N) * t_m_val + B_m_val
    bot_m   = B_m_val
    area_m2 = (top_m + bot_m) / 2 * t_m_val
    msp.add_text("埋戻しコンクリート断面積",
                 dxfattribs={"height": t_h2}).set_placement((ox_t, oy_t + t_h2 + 2 - 10.0))
    msp.add_text(f"({top_m:.2f}+{bot_m:.2f})/2×{t_m_val:.2f}={area_m2:.3f}m2",
                 dxfattribs={"height": t_h2}).set_placement((ox_t, oy_t - 10.0))

    # ===== 数量表 測点別（ペーラインコンクリート）=====
    if pt_names and Hp_list:
        cw2  = [35.0, 25.0, 40.0]
        oy2  = oy_t - t_h2 * 2 - 15.0
        rows2 = []
        for nm, hp in zip(pt_names, Hp_list):
            hp_m    = float(hp)
            hp_disp = round(hp_m + d["block_hikae"] * A / nobiri, 3)
            area    = round(hp_disp * nobiri * d["peline"], 4)
            rows2.append([str(nm), f"{hp_disp:.3f}", f"{area:.4f}"])
        _draw_table(msp, "ペーラインコンクリート", "",
                    rows2, cw2, t_h2, c_h2, ox_t, oy2)

    # ===== 表題 =====
    cx    = (-(A+N)*t / 2) * s
    y_scl = dim_off + 8.0 + 40.0
    y_ttl = y_scl + 10.0
    t1 = msp.add_text("岩着基礎", dxfattribs={"height": 7.0})
    t1.dxf.insert = t1.dxf.align_point = (cx, y_ttl); t1.dxf.halign = 1
    t2 = msp.add_text(f"S=1/{int(scale_n)}", dxfattribs={"height": 5.0})
    t2.dxf.insert = t2.dxf.align_point = (cx, y_scl); t2.dxf.halign = 1

    out_path = os.path.join(output_dir, "kiso_danmen.dxf")
    doc.saveas(out_path)
    return out_path

def main(output_dir, scale=10, **kwargs):
    print("--- 02_Brock_Kiso ---")
    scale_n    = float(scale)
    input_json = os.path.join(output_dir, "input.json")
    if not os.path.exists(input_json):
        print(f"\n[エラー] input.json が見つかりません: {input_json}")
        return

    try:
        with open(input_json, "r", encoding="utf-8") as _f:
            _raw = json.load(_f)
        foundation_type = _raw.get("foundation_type", "direct")

        if foundation_type == "rock":
            params    = load_project_rock(input_json)
            dxf_path  = export_dxf_rock(params, scale_n, output_dir)
            json_path = export_json_rock(params, output_dir)
        else:
            params    = load_project(input_json)
            dxf_path  = export_dxf(params, scale_n, output_dir)
            json_path = export_json(params, output_dir)

        print(f"    生成成功: kiso_danmen.dxf")
        print(f"    データ出力成功: kiso_data.json")
    except Exception as e:
        import traceback
        print(f"\n[エラー発生]: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main(".", scale=10)