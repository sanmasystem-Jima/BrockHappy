import json
import math
import os
import ezdxf

from ezdxf.math import Vec2
from ezdxf.enums import TextEntityAlignment

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
    """render()済み寸法ブロックの矢印を強制的に外向きへ書き換える。"""
    for dim in dim_list:
        try:
            blk_name = dim.dimension.dxf.geometry
        except Exception:
            continue
        if blk_name not in doc.blocks:
            continue
        blk = doc.blocks[blk_name]

        arrow_pos = []
        for e in blk:
            if e.dxftype() == "INSERT":
                arrow_pos.append((e.dxf.insert.x, e.dxf.insert.y))
                e.dxf.rotation = (e.dxf.rotation + 180.0) % 360.0

        if len(arrow_pos) < 2:
            continue

        (ax1, ay1), (ax2, ay2) = arrow_pos[0], arrow_pos[1]
        is_v = abs(ax1 - ax2) < 0.01

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

def load_json_files(output_dir):
    try:
        with open(os.path.join(output_dir, "input.json"), "r", encoding="utf-8") as f:
            raw_input = json.load(f)
        with open(os.path.join(output_dir, "tenba_data.json"), "r", encoding="utf-8") as f:
            output_shape = json.load(f)
        with open(os.path.join(output_dir, "kiso_data.json"), "r", encoding="utf-8") as f:
            foundation_data = json.load(f)
        with open(os.path.join(output_dir, "danmen_data.json"), "r", encoding="utf-8") as f:
            danmen_data = json.load(f)

        input_data = {}
        input_data["num_points"]        = raw_input["num_points"]
        input_data["point_names"]       = raw_input["point_names"]
        input_data["front_slope"]       = raw_input["front_slope"]
        input_data["backfill_slope"]    = raw_input.get("backfill_slope", 0.4)
        input_data["tenba_con_height"]  = raw_input["tenba_con_height"] * 1000.0
        input_data["block_hikae"]       = raw_input.get("block_hikae", 0.35) * 1000.0
        input_data["ura_con_thickness"] = raw_input.get("ura_con_thickness", 0.10) * 1000.0
        input_data["embed_depths"]      = [v * 1000.0 for v in raw_input["embed_depths"]]
        input_data["block_heights"]     = [v * 1000.0 for v in raw_input["block_heights"]]
        input_data["elevations"]        = raw_input["elevations"]
        input_data["base_line_type"]         = raw_input.get("base_line_type", "tenba_kado")
        input_data["back_excavation_slope"]  = raw_input.get("back_excavation_slope", 0.5)
        input_data["structure_type"]         = raw_input.get("structure_type", "river")
        input_data["backfill_top_offset"] = (raw_input.get("backfill_top_offset") or 0.0) * 1000.0
        input_data["has_gr_kiso"]         = raw_input.get("has_gr_kiso", "n")
        input_data["backfill_bottoms"]    = [
            v * 1000.0 if v is not None else None
            for v in (raw_input.get("backfill_bottoms") or [None] * raw_input["num_points"])
        ]
        input_data["water_level_els"]     = raw_input.get("water_level_els")
        input_data["foundation_type"]     = raw_input.get("foundation_type", "direct")

        return input_data, output_shape, foundation_data, danmen_data
    except Exception as e:
        print(f"    [エラー] JSON読み込み失敗: {e}")
        return None, None, None, None

def find_origins_from_basepoints(msp):
    pts = []
    for e in msp:
        if e.dxftype() == "LINE":
            layer_name = e.dxf.layer if e.has_dxf_attrib("layer") else ""
            if layer_name.upper() == "00_BASEPOINT":
                p1 = e.dxf.start
                p2 = e.dxf.end
                pts.append(((p1.x + p2.x) / 2.0, (p1.y + p2.y) / 2.0))

    if not pts:
        print("    ⚠ 00_BASEPOINT レイヤに基準点が見つかりません。")
        return []

    pts.sort(key=lambda p: p[0])
    unique_origins = []
    curr_xs = [pts[0][0]]
    curr_ys = [pts[0][1]]

    for p in pts[1:]:
        if p[0] - curr_xs[-1] > 1000.0:
            unique_origins.append(Vec2(sum(curr_xs)/len(curr_xs), sum(curr_ys)/len(curr_ys)))
            curr_xs = [p[0]]
            curr_ys = [p[1]]
        else:
            curr_xs.append(p[0])
            curr_ys.append(p[1])
    unique_origins.append(Vec2(sum(curr_xs)/len(curr_xs), sum(curr_ys)/len(curr_ys)))
    return unique_origins

def draw_table(msp, rows, title, ox, oy, txt_h):
    # 02/03と同じ規約（実寸mmなので比率 1.5/3.5・4.0/3.5 でpaper-mm相当に変換）
    headers = ["項目", "単位", "数量", "計算式"]
    cell_txt_h = txt_h * 0.9
    margin = txt_h * (1.5 / 3.5)
    pad    = txt_h * (4.0 / 3.5)
    cell_h = cell_txt_h + 2 * margin

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
                (x + pad / 2, oy - cell_h / 2 - cell_txt_h / 2)
            )
        x += cw
    msp.add_line((ox, oy - cell_h), (ox + total_w, oy - cell_h), dxfattribs={"layer": "TABLE"})

    for r_idx, row in enumerate(rows):
        row_y = oy - cell_h * (r_idx + 1)
        msp.add_line((ox, row_y), (ox + total_w, row_y), dxfattribs={"layer": "TABLE"})
        x = ox
        for col_idx, (val, cw) in enumerate(zip(row, col_w)):
            txt = msp.add_text(str(val), dxfattribs={"height": txt_h * 0.9, "layer": "TABLE"})
            if col_idx == unit_col:
                txt.set_placement((x + cw / 2, row_y - cell_h / 2), align=TextEntityAlignment.MIDDLE_CENTER)
            else:
                txt.set_placement((x + pad / 2, row_y - cell_h / 2 - cell_txt_h / 2))
            x += cw

def main(output_dir, scale=50, **kwargs):
    scale = float(scale)

    input_data, output_shape, foundation_data, danmen_data = load_json_files(output_dir)
    if not all([input_data, output_shape, foundation_data, danmen_data]):
        return

    foundation_type = foundation_data.get('metadata', {}).get('foundation_type', 'direct')

    dxf_in  = os.path.join(output_dir, "danmen.dxf")
    dxf_out = os.path.join(output_dir, "danmen_sunpou.dxf")

    if not os.path.exists(dxf_in):
        print(f"    [エラー] danmen.dxf が見つかりません。")
        return

    try:
        doc = ezdxf.readfile(dxf_in)
        doc.header['$INSUNITS'] = 4 
        msp = doc.modelspace()
    except Exception as e:
        print(f"    [エラー] DXFオープン失敗: {e}")
        return

    if "TABLE" not in [l.dxf.name for l in doc.layers]:
        doc.layers.new("TABLE", dxfattribs={"color": 7})
    if "TEXT" not in [l.dxf.name for l in doc.layers]:
        doc.layers.new("TEXT", dxfattribs={"color": 7})

    # 既存の寸法線・テキストをクリア
    for ent in list(msp.query("DIMENSION")):
        ent.destroy()
    for ent in list(msp.query("TEXT")):
        tc = ent.dxf.text.strip()
        if any(kw in tc for kw in input_data["point_names"] + ["EL=", "1 :"]):
            ent.destroy()
    # 05が描いた水面線・水面テキストは06側で高さ寸法とあわせて描き直すため一旦クリア
    for ent in list(msp.query("LINE TEXT")):
        if ent.dxf.layer == "09_WaterLevel":
            ent.destroy()

    origin_points  = find_origins_from_basepoints(msp)
    num_points     = min(input_data["num_points"], len(origin_points))
    base_line_type = input_data["base_line_type"]

    if num_points == 0:
        print("    [エラー] 基準点が見つかりません。05を先に実行してください。")
        return

    # 寸法スタイル設定
    dimstyle = doc.dimstyles.get("STANDARD")
    dimstyle.dxf.dimtxt = 175.0
    dimstyle.dxf.dimasz = 150.0
    dimstyle.dxf.dimgap = 50.0
    dimstyle.dxf.dimexo = 500.0
    dimstyle.dxf.dimexe = 100.0
    dimstyle.dxf.dimtad = 1
    dimstyle.dxf.dimzin = 0
    dimstyle.dxf.dimdec = 2
    dimstyle.dxf.dimtix = 0  # 矢印外向き
    dimstyle.dxf.dimlwd = 13
    dimstyle.dxf.dimlwe = 13
    dimstyle.dxf.dimblk = "OPEN"
    dimstyle.dxf.dimclrd = 7
    dimstyle.dxf.dimclre = 7
    dimstyle.dxf.dimclrt = 7

    front_slope     = input_data["front_slope"]
    n_bg            = input_data["backfill_slope"]
    n_exc           = input_data["back_excavation_slope"]
    structure_type  = input_data["structure_type"]
    slope_angle     = math.atan2(1.0, front_slope)
    perp_angle      = slope_angle + math.pi / 2
    v_slope         = Vec2(math.cos(slope_angle), math.sin(slope_angle))
    v_perp          = Vec2(math.cos(perp_angle),  math.sin(perp_angle))
    slope_factor    = math.sqrt(1.0 + front_slope**2)
    bg_slope_angle  = math.atan2(1.0, n_bg)
    bg_v_perp_out   = Vec2(math.cos(bg_slope_angle - math.pi/2), math.sin(bg_slope_angle - math.pi/2))
    exc_slope_angle = math.atan2(1.0, n_exc)
    exc_v_perp_out  = Vec2(math.cos(exc_slope_angle - math.pi/2), math.sin(exc_slope_angle - math.pi/2))
    text_size       = 175.0
    txt_h_table     = 175.0
    sanren_interval = 8.0 * scale

    kiso_bottom_offset = min(
        foundation_data['points']['foundation_bottom_front_ext'][1],
        foundation_data['points']['foundation_bottom_back_ext'][1]
    )

    suryo_sections = []

    for i in range(num_points):
        p_name    = input_data["point_names"][i]
        origin    = origin_points[i]
        embed_d   = input_data["embed_depths"][i]
        block_h   = input_data["block_heights"][i]
        tenba_h   = input_data["tenba_con_height"]
        hikae     = input_data["block_hikae"]
        uracon    = input_data["ura_con_thickness"]
        el_val    = input_data["elevations"][i]
        saiseki_w = 300.0

        # =========================================================
        # A) base_line_type に応じた座標計算
        # =========================================================
        if base_line_type == 'tenba_kado':
            # 基準点 = 天端コン上面前面
            real_top_y    = origin.y
            tenba_btm_y   = real_top_y - tenba_h
            real_bottom_y = real_top_y - block_h
            y_gl_line     = real_bottom_y + embed_d
        else:
            # 基準点 = 地盤線（埋戻し天）
            y_gl_line     = origin.y
            real_bottom_y = y_gl_line - embed_d
            real_top_y    = y_gl_line + (block_h - embed_d)
            tenba_btm_y   = real_top_y - tenba_h

        h_above_gl = block_h - embed_d
        h_down     = h_above_gl - tenba_h

        # 構造コーナー点をdanmen_dataから取得
        sec_pts       = danmen_data['sections'][i]['points']
        p_front_kiso  = Vec2(*sec_pts['block_btm_front'])
        p_front_tenba = Vec2(*sec_pts['tenba_btm_front'])
        p_tenba_top   = Vec2(*sec_pts['tenba_top_front'])
        p_gl_front    = Vec2(*sec_pts['gl_front'])

        # 背面構造座標（天端コン下面レベル）
        dx_hikae   = hikae     * slope_factor
        dx_uracon  = uracon    * slope_factor
        dx_saiseki = saiseki_w * slope_factor
        p_b0 = p_front_tenba
        p_b1 = Vec2(p_b0.x + dx_hikae,  p_b0.y)
        p_b2 = Vec2(*sec_pts['tenba_btm_back'])
        p_b3 = Vec2(*sec_pts['saiseki_top_back'])

        # 砕石最下端・砕石直高
        saiseki_bottom_y = real_bottom_y + kiso_bottom_offset

        # 裏砕石下幅（法線方向）
        p_saiseki_btm_left  = Vec2(*sec_pts['saiseki_btm_front'])
        p_saiseki_btm_right = Vec2(*sec_pts['saiseki_btm_back'])

        # 砕石・裏コンの正しい高さ算出（断面積・寸法線共用）
        _bk_top_ofs    = input_data["backfill_top_offset"]
        _bf_bot_raw    = (input_data["backfill_bottoms"][i]
                          if i < len(input_data["backfill_bottoms"]) else None)
        backfill_top_y    = tenba_btm_y - _bk_top_ofs
        # 砕石底の決定（基礎・構造種別により異なる）
        if foundation_type == 'rock':
            # 岩着：backfill_bottoms で直接入力（ブロック前面下端基準）
            backfill_bottom_y = real_bottom_y + (_bf_bot_raw if _bf_bot_raw is not None else 0.0)
        elif structure_type == 'road':
            # 道路直接基礎：砕石底 = GL面（埋め戻し深さ）
            backfill_bottom_y = y_gl_line
        else:
            # 河川直接基礎：砕石底 = 基礎底
            backfill_bottom_y = saiseki_bottom_y
        h_saiseki  = backfill_top_y - backfill_bottom_y        # 砕石直高
        h_uracon   = tenba_btm_y - backfill_bottom_y           # 裏コン高さ（tenba_btm → 砕石下面）

        # 裏砕石下幅（数量表の面積計算と同じ式に統一：砕石底=backfill_bottom_y基準）
        saiseki_bottom_w = saiseki_w + h_uracon * (front_slope - n_bg)

        # 砕石上端・下端、ブロック（法長範囲）上端・下端の絶対EL（水面より上の面積算出用）
        saiseki_top_el    = el_val + (backfill_top_y    - origin.y) / 1000.0
        saiseki_bottom_el = el_val + (backfill_bottom_y - origin.y) / 1000.0
        block_top_el      = el_val + (tenba_btm_y       - origin.y) / 1000.0
        block_bottom_el   = el_val + (real_bottom_y      - origin.y) / 1000.0

        # =========================================================
        # D) 断面図タイトル・縮尺
        # =========================================================
        title_x = origin.x
        title_y = real_top_y + 3500.0
        msp.add_text("断面図", dxfattribs={
            "insert": Vec2(title_x, title_y),
            "height": 7.0 * scale,
            "layer": "TEXT"
        })
        msp.add_text(f"S=1/{int(scale)}", dxfattribs={
            "insert": Vec2(title_x, title_y - 8.0 * scale),
            "height": 5.0 * scale,
            "layer": "TEXT"
        })

        # =========================================================
        # 測点名・ELテキスト
        # =========================================================
        msp.add_text(p_name, dxfattribs={
            "insert": Vec2(origin.x, real_top_y + 2000.0), "height": text_size * 1.3
        })

        x_el_right = p_front_kiso.x - 10.0 * scale
        for _el_text, _el_y in [
            (f"EL={el_val + h_above_gl/1000.0:.2f}", real_top_y    + 100.0),
            (f"EL={el_val:.2f}",                     y_gl_line     + 100.0),
            (f"EL={el_val - embed_d/1000.0:.2f}",    real_bottom_y + 100.0),
        ]:
            _t = msp.add_text(_el_text, dxfattribs={"height": text_size})
            _t.dxf.halign      = 2  # 右寄せ
            _t.dxf.insert      = (x_el_right, _el_y)
            _t.dxf.align_point = (x_el_right, _el_y)

        # =========================================================
        # 左側縦寸法（根入れ・全高）
        # =========================================================
        _x_embed_dim = p_front_kiso.x - 40.0 * scale
        _d_embed = msp.add_linear_dim(
            base=Vec2(_x_embed_dim, real_bottom_y),
            p1=Vec2(*sec_pts['gl_back']),
            p2=p_front_kiso,
            angle=90, text=f"{embed_d/1000:.2f}"
        )
        _d_embed.render()
        _fix_arrows_outward(doc, [_d_embed], dimstyle.dxf.dimasz)
        _fix_text_left(doc, [_d_embed])

        _x_block_dim = _x_embed_dim - 8.0 * scale
        if input_data.get('has_gr_kiso') == 'y':
            # GR基礎あり：ブロック・GR基礎の2段書き
            msp.add_linear_dim(
                base=Vec2(_x_block_dim, real_bottom_y),
                p1=p_front_kiso,
                p2=p_front_tenba,
                angle=90, text=f"{(block_h - tenba_h)/1000:.2f}"
            ).render()
            msp.add_linear_dim(
                base=Vec2(_x_block_dim, real_bottom_y),
                p1=p_front_tenba,
                p2=p_tenba_top,
                angle=90, text=f"{tenba_h/1000:.2f}"
            ).render()
        else:
            msp.add_linear_dim(
                base=Vec2(_x_block_dim, real_bottom_y),
                p1=p_front_kiso,
                p2=p_tenba_top,
                angle=90, text=f"{block_h/1000:.2f}"
            ).render()

        # =========================================================
        # 法長寸法（基礎天前面→天端コン下面前面）
        # =========================================================
        hocho_len   = p_front_kiso.distance(p_front_tenba)
        p_mid_slope = (p_front_kiso + p_front_tenba) / 2

        msp.add_linear_dim(
            base=p_mid_slope + v_perp * (15.0 * scale),
            p1=p_front_kiso,
            p2=p_front_tenba,
            angle=math.degrees(slope_angle),
            text=f"{hocho_len/1000:.2f}"
        ).render()

        # 前面勾配表示：文字列の下部中心をブロック前面の線の中心に一致させる
        slope_str   = f"1 : {front_slope:.2f}".rstrip('0').rstrip('.')
        p_slope_pos = (p_front_kiso + p_tenba_top) / 2
        t_slope = msp.add_text(slope_str, dxfattribs={
            "height": text_size, "rotation": math.degrees(slope_angle)
        })
        t_slope.dxf.halign      = 1  # CENTER
        t_slope.dxf.valign      = 1  # BOTTOM
        t_slope.dxf.insert      = p_slope_pos
        t_slope.dxf.align_point = p_slope_pos

        # 裏砕石背面の勾配表示：文字列の下部中心を裏砕石背面の線の中心に一致させる
        p_bg_btm = Vec2(*sec_pts['saiseki_btm_back'])
        p_bg_top = Vec2(*sec_pts['saiseki_top_back'])
        p_bg_mid = (p_bg_btm + p_bg_top) / 2
        bg_slope_str = f"1 : {n_bg:.2f}".rstrip('0').rstrip('.')
        t_bg = msp.add_text(bg_slope_str, dxfattribs={
            "height": text_size, "rotation": math.degrees(bg_slope_angle)
        })
        t_bg.dxf.halign      = 1  # CENTER
        t_bg.dxf.valign      = 1  # BOTTOM
        t_bg.dxf.insert      = p_bg_mid
        t_bg.dxf.align_point = p_bg_mid

        # 掘削面の勾配表示：文字列の上部中心を掘削ラインの中心に一致させる
        # （V-nasがvalign=TOPを認識しないため、BOTTOM基準で文字高さ分だけ上にずらして再現）
        p_exc_btm = Vec2(*sec_pts['exc_bottom'])
        p_exc_top = Vec2(*sec_pts['exc_top'])
        p_exc_mid = (p_exc_btm + p_exc_top) / 2
        exc_up    = Vec2(-math.sin(exc_slope_angle), math.cos(exc_slope_angle))
        p_exc_anchor = p_exc_mid - exc_up * text_size
        exc_slope_str = f"1 : {n_exc:.2f}".rstrip('0').rstrip('.')
        t_exc = msp.add_text(exc_slope_str, dxfattribs={
            "height": text_size, "rotation": math.degrees(exc_slope_angle)
        })
        t_exc.dxf.halign      = 1  # CENTER
        t_exc.dxf.valign      = 1  # BOTTOM
        t_exc.dxf.insert      = p_exc_anchor
        t_exc.dxf.align_point = p_exc_anchor

        # =========================================================
        # E) 右側縦寸法：天端コン厚 + 3段（砕石オフセット・砕石直高・砕石下から根入れ下）
        # =========================================================
        x_dim_right = sec_pts['exc_top'][0]
        dim_base_x  = x_dim_right + 20.0 * scale
        x_ref       = p_b1.x
        _right_dimexo = {"dimexo": dimstyle.dxf.dimexo + 3.0 * scale}

        # 天端コン厚（天コンあり のときのみ）
        if tenba_h > 0:
            msp.add_linear_dim(
                base=Vec2(dim_base_x, tenba_btm_y),
                p1=Vec2(x_ref, real_top_y),
                p2=Vec2(x_ref, tenba_btm_y),
                angle=90, text=f"{tenba_h/1000:.2f}",
                override=_right_dimexo
            ).render()

        if foundation_type == 'rock':
            # 岩着基礎：砕石オフセット・砕石直高・砕石下から根入れ下の3段
            foundation_btm_y  = real_bottom_y   # ブロック前面の下端

            h1 = _bk_top_ofs       # 砕石オフセット
            h2 = h_saiseki         # 砕石直高
            h3 = backfill_bottom_y - foundation_btm_y

            _rock_dims = []

            # 砕石オフセット（h1 > 0 のときのみ）
            if h1 > 1.0:
                _d = msp.add_linear_dim(
                    base=Vec2(dim_base_x, backfill_top_y),
                    p1=Vec2(x_ref, tenba_btm_y),
                    p2=Vec2(x_ref, backfill_top_y),
                    angle=90, text=f"{h1/1000:.2f}",
                    override=_right_dimexo
                )
                _d.render()
                _rock_dims.append(_d)

            # 砕石直高
            _d = msp.add_linear_dim(
                base=Vec2(dim_base_x, backfill_bottom_y),
                p1=Vec2(x_ref, backfill_top_y),
                p2=Vec2(x_ref, backfill_bottom_y),
                angle=90, text=f"{h2/1000:.2f}",
                override=_right_dimexo
            )
            _d.render()
            _rock_dims.append(_d)

            # 砕石下から根入れ下まで
            _d = msp.add_linear_dim(
                base=Vec2(dim_base_x, foundation_btm_y),
                p1=Vec2(x_ref, backfill_bottom_y),
                p2=Vec2(x_ref, foundation_btm_y),
                angle=90, text=f"{h3/1000:.2f}",
                override=_right_dimexo
            )
            _d.render()
            _rock_dims.append(_d)

            _fix_arrows_outward(doc, _rock_dims, dimstyle.dxf.dimasz)

        else:
            # 直接基礎：砕石オフセット・砕石直高の2段
            # 河川: backfill_bottom_y = saiseki_bottom_y（基礎底）
            # 道路: backfill_bottom_y = y_gl_line（GL面）
            h1 = _bk_top_ofs       # 砕石オフセット
            h2 = h_saiseki         # 砕石直高

            _direct_dims = []

            # 砕石オフセット（h1 > 0 のときのみ）
            if h1 > 1.0:
                _d = msp.add_linear_dim(
                    base=Vec2(dim_base_x, backfill_top_y),
                    p1=Vec2(x_ref, tenba_btm_y),
                    p2=Vec2(x_ref, backfill_top_y),
                    angle=90, text=f"{h1/1000:.2f}",
                    override=_right_dimexo
                )
                _d.render()
                _direct_dims.append(_d)

            # 砕石直高
            _d = msp.add_linear_dim(
                base=Vec2(dim_base_x, backfill_bottom_y),
                p1=Vec2(x_ref, backfill_top_y),
                p2=Vec2(x_ref, backfill_bottom_y),
                angle=90, text=f"{h2/1000:.2f}",
                override=_right_dimexo
            )
            _d.render()
            _direct_dims.append(_d)

            _fix_arrows_outward(doc, _direct_dims, dimstyle.dxf.dimasz)

        # =========================================================
        # 水面EL・水抜きパイプ対象高さ（河川のみ・測点ごと）
        # =========================================================
        water_els = input_data["water_level_els"]
        if structure_type in ('river', 'river_gohan') and water_els and i < len(water_els) and water_els[i] is not None:
            wl_el = water_els[i]
            wl_y  = origin.y + (wl_el - el_val) * 1000.0

            # 水面表示は左側のみ（寸法線群の左端 〜 構造物前面）
            wl_x_left  = _x_block_dim - 8.0 * scale
            wl_x_right = p_front_kiso.x
            wl_attr    = {'layer': '09_WaterLevel', 'color': 5, 'linetype': 'DASHED'}
            msp.add_line(Vec2(wl_x_left, wl_y), Vec2(wl_x_right, wl_y), dxfattribs=wl_attr)
            t_wl = msp.add_text(
                text=f"水面 EL={wl_el:.2f}",
                dxfattribs={'height': text_size, 'layer': '09_WaterLevel', 'color': 5}
            )
            t_wl.dxf.halign      = 2  # 右寄せ
            t_wl.dxf.insert      = Vec2(wl_x_left - 100.0, wl_y)
            t_wl.dxf.align_point = Vec2(wl_x_left - 100.0, wl_y)

            if foundation_type == 'rock':
                clip_top_y    = tenba_btm_y
                threshold_y   = max(backfill_bottom_y, wl_y)
                h_clip        = max(0.0, min(tenba_btm_y - real_bottom_y, tenba_btm_y - threshold_y))
            else:
                clip_top_y    = backfill_top_y
                threshold_y   = max(backfill_bottom_y, wl_y)
                h_clip        = max(0.0, min(h_saiseki, backfill_top_y - threshold_y))
            clip_bottom_y = clip_top_y - h_clip

            # 水抜きパイプ対象高さの根拠寸法（左側、直高の寸法線より16mm右寄りに設置）
            # 下端が水面・砕石下端のどちらでも（クリップの有無を問わず）描画する
            if h_clip > 1.0:
                _x_nuki_dim = _x_block_dim + 16.0 * scale
                _d_nuki = msp.add_linear_dim(
                    base=Vec2(_x_nuki_dim, clip_bottom_y),
                    p1=Vec2(p_front_kiso.x, clip_top_y),
                    p2=Vec2(p_front_kiso.x, clip_bottom_y),
                    angle=90, text=f"{h_clip/1000:.2f}"
                )
                _d_nuki.render()
                _fix_arrows_outward(doc, [_d_nuki], dimstyle.dxf.dimasz)
                _fix_text_left(doc, [_d_nuki])

        # =========================================================
        # 裏砕石下幅（法線方向斜め寸法）
        # =========================================================
        p_mid_btm = (p_saiseki_btm_left + p_saiseki_btm_right) / 2
        msp.add_linear_dim(
            base=p_mid_btm - v_perp * 1500.0 - v_slope * 1000.0,
            p1=p_saiseki_btm_left,
            p2=p_saiseki_btm_right,
            angle=math.degrees(perp_angle) + 180.0,
            text=f"{saiseki_bottom_w/1000:.2f}"
        ).render()

        # =========================================================
        # 天端3連寸法（段違い・文字方向修正）
        # =========================================================
        for idx, (pa, pb, val) in enumerate([
            (p_b0, p_b1, hikae),
            (p_b1, p_b2, uracon),
            (p_b2, p_b3, saiseki_w),
        ]):
            if val <= 0.0:
                continue
            base_pt = p_b0 + v_slope * (2000.0 + idx * sanren_interval) - v_slope * 750.0
            msp.add_linear_dim(
                base=base_pt,
                p1=pa, p2=pb,
                angle=math.degrees(perp_angle) + 180.0,
                text=f"{val/1000:.2f}"
            ).render()

        # =========================================================
        # C) 断面数量表（計算式付き）
        # =========================================================
        hocho_m      = hocho_len / 1000.0

        # 砕石：gravel 域（backfill_top_y → backfill_bottom_y）の台形面積
        _rate         = (front_slope - n_bg)                          # 単位深さあたりの幅増加 (mm/mm)
        saiseki_w_top = saiseki_w + _bk_top_ofs * _rate               # 砕石上端幅
        saiseki_w_bot = saiseki_w + h_uracon    * _rate               # 砕石下端幅（= backfill_bottom_y での幅）
        saiseki_area  = round((saiseki_w_top + saiseki_w_bot) / 2 * slope_factor * h_saiseki / (1000**2), 3)

        # 裏コン：tenba_btm → 砕石下面（backfill_bottom_y）
        uracon_area   = round(uracon * h_uracon * slope_factor / (1000**2), 3)

        uracon_shiki  = f"{uracon/1000:.3f}×{h_uracon/1000:.3f}×{slope_factor:.3f}"
        saiseki_shiki = f"({saiseki_w_top/1000:.3f}+{saiseki_w_bot/1000:.3f})/2×{slope_factor:.3f}×{h_saiseki/1000:.3f}"

        hocho_shiki = f"({block_h/1000:.2f}-{tenba_h/1000:.2f})×{slope_factor:.3f}"
        rows = [
            ["ブロック法長",  "m",  f"{hocho_m:.2f}",      hocho_shiki],
            ["砕石断面積",    "m²", f"{saiseki_area:.3f}", saiseki_shiki],
            ["裏コン断面積",  "m²", f"{uracon_area:.3f}",  uracon_shiki],
        ]

        table_x = origin.x - 5000.0
        table_y = real_bottom_y - 2000.0
        draw_table(msp, rows, f"断面数量　{p_name}", table_x, table_y, txt_h_table)

        suryo_sections.append({
            "point_name":      p_name,
            "hocho_m":         round(hocho_m, 3),
            "uracon_area_m2":  round(uracon_area, 4),
            "saiseki_area_m2": round(saiseki_area, 4),
            "saiseki_h_m":         round(h_saiseki / 1000.0, 3),
            "saiseki_top_el":      round(saiseki_top_el, 3),
            "saiseki_bottom_el":   round(saiseki_bottom_el, 3),
            "block_top_el":        round(block_top_el, 3),
            "block_bottom_el":     round(block_bottom_el, 3),
        })

    suryo_data = {
        "unit": {"length": "m", "area": "m2"},
        "sections": suryo_sections,
    }
    suryo_path = os.path.join(output_dir, "suryo_data.json")
    with open(suryo_path, "w", encoding="utf-8") as f:
        json.dump(suryo_data, f, indent=2, ensure_ascii=False)
    print(f"    データ出力成功: suryo_data.json")

    try:
        doc.saveas(dxf_out)
        print(f"    生成成功: danmen_sunpou.dxf")
    except PermissionError:
        print(f"    [エラー] ファイルが開いています。閉じて再実行してください。")

if __name__ == "__main__":
    main(".")