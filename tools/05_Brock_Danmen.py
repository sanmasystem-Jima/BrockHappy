import json
import math
import os
import ezdxf

def load_json(path):
    if not os.path.exists(path): return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def extend_to_foundation(line_x_at_y0, n, pA, pB):
    xA, yA = pA
    xB, yB = pB
    if xB - xA == 0:
        xp = xA
        yp = (xp - line_x_at_y0) / n
        return (xp, yp)
    m = (yB - yA) / (xB - xA)
    denom = 1.0 - m * n
    if abs(denom) < 1e-9:
        return (line_x_at_y0 + n * yA, yA)
    yp = (m * line_x_at_y0 + yA - m * xA) / denom
    xp = n * yp + line_x_at_y0
    return (xp, yp)

def rock_foundation_shapes(foundation_data, input_data):
    """岩着基礎の3形状をkiso局所座標で返す。
    変換: kiso(lx,ly) → danmen(f_btm_x + lx, f_orig_y + ly)
    """
    q      = foundation_data.get('quantities', {})
    t_mm   = q.get('neirimi_m',      0.5) * 1000
    B_mm   = q.get('joge_haba_bot_m',0.1) * 1000
    top_m  = q.get('joge_haba_top_m',0.4)
    pe_m3  = q.get('peline_bottom_m3',0.2)
    A      = float(input_data['front_slope'])
    hk_mm  = float(input_data['block_hikae']) * 1000

    N      = (top_m - B_mm/1000) / (t_mm/1000) - A
    disc   = (hk_mm/1000)**2 + 4*pe_m3/10
    pe_mm  = ((-hk_mm/1000) + math.sqrt(disc)) / 2 * 1000

    nobiri = math.sqrt(A**2 + 1)

    # ブロック下端点（kiso局所座標）
    F_bot = (-A*t_mm,                          -t_mm                         )  # 前面底
    B_top = ( hk_mm/nobiri,                    -hk_mm*A/nobiri               )  # 背面→前面ベクトル
    B_bot = ( F_bot[0]+B_top[0],               F_bot[1]+B_top[1]             )  # 背面底

    # 埋戻しコンクリート（台形）
    ume = [(0,0), (-(A+N)*t_mm - B_mm, 0), (-A*t_mm - B_mm, -t_mm), (-A*t_mm, -t_mm)]

    # ペーライン底面
    pe_d   = (-A/nobiri, -1/nobiri)
    ext    = hk_mm + pe_mm
    pe_far = (F_bot[0] + ext/nobiri, F_bot[1] - ext*A/nobiri)
    pe_bot = [F_bot, pe_far,
              (pe_far[0]+pe_mm*pe_d[0], pe_far[1]+pe_mm*pe_d[1]),
              (F_bot[0] +pe_mm*pe_d[0], F_bot[1] +pe_mm*pe_d[1])]

    # ペーライン背面（岩盤面 kiso y=0 で止める = 裏コン領域と重ならない）
    bk_d = (1/nobiri, -A/nobiri)
    B_s  = (hk_mm*nobiri, 0)   # 背面が岩盤面(y=0)を通る点 = hk_mm*(1+A²)/nobiri = hk_mm*nobiri
    pe_bk = [B_bot, B_s,
              (B_s[0]  +pe_mm*nobiri,  0),
              (B_bot[0]+pe_mm*bk_d[0], B_bot[1]+pe_mm*bk_d[1])]

    left_x = -(A+N)*t_mm - B_mm   # 岩盤線左端kiso x
    return ume, pe_bot, pe_bk, left_x, F_bot, B_bot


def main(output_dir, **kwargs):
    input_data      = load_json(os.path.join(output_dir, 'input.json'))
    foundation_data = load_json(os.path.join(output_dir, 'kiso_data.json'))
    tenba_data      = load_json(os.path.join(output_dir, 'tenba_data.json'))

    if not all([input_data, foundation_data, tenba_data]):
        print("    [エラー] 必要なJSONファイルが揃っていません。")
        return

    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4
    msp = doc.modelspace()

    if 'DASHED' not in [lt.dxf.name for lt in doc.linetypes]:
        doc.linetypes.add('DASHED', pattern=[0.5, 0.25, -0.25])

    doc.layers.add(name='00_Text',      color=7)
    doc.layers.add(name='00_BasePoint', color=6)
    doc.layers.add(name='01_Tenba',     color=1)
    doc.layers.add(name='02_Block',     color=2)
    doc.layers.add(name='03_Uracon',    color=3)
    doc.layers.add(name='04_Backfill',  color=4)
    doc.layers.add(name='05_Foundation',color=5)
    doc.layers.add(name='06_Ground',    color=8)
    doc.layers.add(name='07_BaseRock',  color=9)
    doc.layers.add(name='08_Excavation',color=6, linetype='DASHED')
    doc.layers.add(name='09_WaterLevel',color=5, linetype='DASHED')

    n               = input_data['front_slope']
    n_bg            = input_data['backfill_slope']
    n_exc           = input_data.get('back_excavation_slope', 0.5)
    tenba_btm_y     = tenba_data['points'][3]['y']
    tenba_front_x   = tenba_data['points'][3]['x']
    tenba_top_x     = next(p['x'] for p in tenba_data['points'] if p['name'] == 'front_top')
    hikae           = input_data['block_hikae'] * 1000
    uracon          = input_data['ura_con_thickness'] * 1000
    base_line_type  = input_data.get('base_line_type', 'tenba_kado')
    struct_type     = input_data.get('structure_type', 'road')
    tenba_h         = input_data.get('tenba_con_height', 0.0) * 1000
    foundation_type = input_data.get('foundation_type', 'direct')

    # 裏砕石上端オフセット：天端下端から下方にずれる量 (mm)
    bto_val                = input_data.get('backfill_top_offset', None)
    backfill_top_offset_mm = (bto_val or 0.0) * 1000

    norm      = math.sqrt(1 + n**2)
    dx_hikae  = hikae  * norm
    dx_uracon = uracon * norm
    dx_filter = 300    * norm

    kiso_bottom_offset = min(
        foundation_data['points']['foundation_bottom_front_ext'][1],
        foundation_data['points']['foundation_bottom_back_ext'][1]
    )
    kiso_back_offset_x = foundation_data['points']['foundation_bottom_back_ext'][0]
    kiso_back_offset_y = foundation_data['points']['foundation_bottom_back_ext'][1]
    kiso_top_front_x   = foundation_data['points']['foundation_top_front_ext'][0]
    kiso_top_back_x    = foundation_data['points']['foundation_top_back_ext'][0]

    num_points = input_data['num_points']
    spacing_x  = 15000.0

    all_sections = []

    for i in range(num_points):
        offset_x = i * spacing_x
        pt_name  = input_data['point_names'][i]
        H        = input_data['block_heights'][i] * 1000
        embed    = input_data['embed_depths'][i]  * 1000

        def sc(x, y):
            return (x + offset_x, y)

        msp.add_text(
            text=pt_name,
            dxfattribs={'insert': sc(0, 500), 'height': 250, 'layer': '00_Text', 'color': 7}
        )

        current_front_btm_x = tenba_front_x - (H + tenba_btm_y) * n

        if foundation_type == 'rock':
            # base_top_front (F_bot) を danmen の (current_front_btm_x, -H) に一致させる
            _btf     = foundation_data['points']['base_top_front']
            f_orig_x = current_front_btm_x - _btf[0]   # = current_front_btm_x + A*t
            f_orig_y = -H - _btf[1]                      # = -H + t（岩盤面レベル）
        else:
            f_orig_x = current_front_btm_x - 100
            f_orig_y = -H

        p_base_back = (f_orig_x + foundation_data['points']['base_top_back'][0],
                       f_orig_y + foundation_data['points']['base_top_back'][1])
        p_base_toe  = (f_orig_x + foundation_data['points']['base_toe_top'][0],
                       f_orig_y + foundation_data['points']['base_toe_top'][1])

        f_top = (tenba_front_x, tenba_btm_y)
        # 岩着は F_bot が (current_front_btm_x, -H) に固定されるため直接セット
        if foundation_type == 'rock':
            f_btm = (current_front_btm_x, -H)
        else:
            f_btm = extend_to_foundation(0, n, p_base_back, p_base_toe)

        b_top = (f_top[0] + dx_hikae, tenba_btm_y)
        b_btm = extend_to_foundation(dx_hikae, n, p_base_back, p_base_toe)

        u_top = (b_top[0] + dx_uracon, tenba_btm_y)
        u_btm = extend_to_foundation(dx_hikae + dx_uracon, n, p_base_back, p_base_toe)

        bf_bottom_val = input_data['backfill_bottoms'][i]
        if bf_bottom_val is not None:
            backfill_y = -H + (bf_bottom_val * 1000)
        else:
            backfill_y = f_orig_y + kiso_bottom_offset

        # 岩着：裏コンは裏砕石下面止まり（岩盤面まで下ろさない）
        if foundation_type == 'rock':
            _drop = tenba_btm_y - backfill_y
            b_btm = (b_top[0] - _drop * n, backfill_y)
            u_btm = (u_top[0] - _drop * n, backfill_y)

        # 裏砅石上端Y（オフセット考慮）
        backfill_top_y = tenba_btm_y - backfill_top_offset_mm

        # 裏砕石前面のx：ブロック背面(裏コン後面)が各高さを通る位置
        #   上端: y = backfill_top_y
        #   下端: y = backfill_y
        top_drop = tenba_btm_y - backfill_top_y   # 天端下端から裏砕石上端までの落差
        btm_drop = tenba_btm_y - backfill_y        # 天端下端から裏砕石下端までの落差
        u_at_saiseki_top = (u_top[0] - top_drop * n, backfill_top_y)
        u_at_saiseki_btm = (u_top[0] - btm_drop * n, backfill_y)

        # 裏砕石後面
        fi_top = (u_top[0] + dx_filter, backfill_top_y)
        fi_drop = backfill_top_y - backfill_y          # 裏砕石の高さ方向落差
        fi_btm = (fi_top[0] - fi_drop * n_bg, backfill_y)

        # 基礎各点
        kiso_top_front  = (f_orig_x + kiso_top_front_x,  f_orig_y)
        kiso_top_back   = (f_orig_x + kiso_top_back_x,   f_orig_y)
        kiso_btm_front  = (f_orig_x + foundation_data['points']['foundation_bottom_front_ext'][0],
                           f_orig_y + kiso_bottom_offset)
        kiso_btm_back   = (f_orig_x + kiso_back_offset_x, f_orig_y + kiso_back_offset_y)

        # 地盤線（embed は常にブロック前面底 y=-H からの高さ）
        gl_y    = -H + embed
        gx      = f_btm[0] + embed * n
        gl_back = gx - embed * 2

        # 掘削上端Y
        exc_top_y = tenba_btm_y + tenba_h

        # 掘削線座標
        fi_btm_x, fi_btm_y = fi_btm
        exc_top_x = fi_btm_x + (exc_top_y - fi_btm_y) * n_exc

        if struct_type == 'road' and foundation_type == 'direct':
            kiso_back_x = f_orig_x + kiso_back_offset_x
            kiso_back_y = f_orig_y + kiso_back_offset_y
            exc_mid_x   = kiso_back_x + (backfill_y - kiso_back_y) * n_exc

        # =========================================================
        # 描画
        # =========================================================

        # 岩着：ブロック輪郭・根入れ形状・pe_bk を確定
        if foundation_type == 'rock':
            ume, pe_bot, pe_bk, *_ = rock_foundation_shapes(foundation_data, input_data)
            # f_btm_draw = base_top_front の合わせ点 = (current_front_btm_x, -H)
            f_btm_draw = f_btm
            # b_btm_draw = base_bottom_back (B_bot) を f_orig 変換で取得
            _bbb       = foundation_data['points']['base_bottom_back']
            b_btm_draw = (f_orig_x + _bbb[0], f_orig_y + _bbb[1])
            # pe_bk 上端を裏砕石下面（backfill_y）まで延伸
            # kiso y=0 が岩盤面 → backfill_y_kiso = backfill_y - f_orig_y
            _bfy_kiso = backfill_y - f_orig_y
            pe_bk = [pe_bk[0],
                     (pe_bk[1][0] + n * _bfy_kiso, _bfy_kiso),
                     (pe_bk[2][0] + n * _bfy_kiso, _bfy_kiso),
                     pe_bk[3]]
        else:
            f_btm_draw = f_btm
            b_btm_draw = b_btm

        # ブロック面（岩着は根入れ底まで）
        msp.add_lwpolyline([sc(*f_btm_draw), sc(*f_top), sc(*b_top), sc(*b_btm_draw)],
                           close=True, dxfattribs={'layer': '02_Block', 'color': 2})

        # 裏コンクリート（岩着は裏砕石下面止まり、直接は従来通り）
        msp.add_lwpolyline([sc(*b_btm), sc(*b_top), sc(*u_top), sc(*u_btm)], close=True,
                           dxfattribs={'layer': '03_Uracon', 'color': 3})

        # 裏砕石（オフセット適用後の4頂点）
        msp.add_lwpolyline([
            sc(*u_at_saiseki_top),
            sc(*u_at_saiseki_btm),
            sc(*fi_btm),
            sc(*fi_top),
        ], close=True, dxfattribs={'layer': '04_Backfill', 'color': 4})

        # 天端コンクリート（高さがある場合のみ描画）
        if tenba_h > 0:
            if input_data.get('has_gr_kiso') == 'y':
                gr_h     = input_data['gr_height_m']     * 1000
                gr_bw    = input_data['gr_base_width_m'] * 1000
                mortar_h = input_data['gr_mortar_m']     * 1000
                kiso_h   = input_data['gr_kiso_con_m']   * 1000

                # GR既製品 8頂点外形
                gr_poly = [
                    (0,           0),
                    (400,         0),
                    (400,         -(gr_h - 100)),
                    (gr_bw - 100, -(gr_h - 100)),
                    (gr_bw - 100, -gr_h),
                    (-100,        -gr_h),
                    (-100,        -(gr_h - 100)),
                    (0,           -(gr_h - 100)),
                ]
                msp.add_lwpolyline([sc(*p) for p in gr_poly], close=True,
                                   dxfattribs={'layer': '01_Tenba', 'color': 3})

                # 既製品下端からブロック前面への延長線
                x_face_gr = n * (-gr_h)
                if x_face_gr < -100:
                    msp.add_line(sc(-100, -gr_h), sc(x_face_gr, -gr_h),
                                 dxfattribs={'layer': '01_Tenba', 'color': 3})

                # モルタル層（台形）
                mt_y_top = -gr_h
                mt_y_btm = -(gr_h + mortar_h)
                mt_poly = [
                    (n * mt_y_top, mt_y_top),
                    (gr_bw,        mt_y_top),
                    (gr_bw,        mt_y_btm),
                    (n * mt_y_btm, mt_y_btm),
                ]
                msp.add_lwpolyline([sc(*p) for p in mt_poly], close=True,
                                   dxfattribs={'layer': '01_Tenba', 'color': 4})

                # 基礎コン層（台形）
                kc_y_top = -(gr_h + mortar_h)
                kc_y_btm = -(gr_h + mortar_h + kiso_h)
                kc_poly = [
                    (n * kc_y_top, kc_y_top),
                    (gr_bw,        kc_y_top),
                    (gr_bw,        kc_y_btm),
                    (n * kc_y_btm, kc_y_btm),
                ]
                msp.add_lwpolyline([sc(*p) for p in kc_poly], close=True,
                                   dxfattribs={'layer': '01_Tenba', 'color': 5})
            else:
                t_pts = [sc(p['x'], p['y']) for p in tenba_data['points']]
                msp.add_lwpolyline(t_pts, close=True,
                                   dxfattribs={'layer': '01_Tenba', 'color': 1})

        # 基礎：直接基礎は基礎コン+砕石層を描画、岩着は岩盤線のみ
        if foundation_type != 'rock':
            f_keys = ["base_top_front", "base_bottom_front", "base_bottom_back",
                      "base_toe_top", "base_top_back"]
            f_pts = [sc(f_orig_x + foundation_data['points'][k][0],
                        f_orig_y + foundation_data['points'][k][1]) for k in f_keys]
            msp.add_lwpolyline(f_pts, close=True,
                               dxfattribs={'layer': '05_Foundation', 'color': 5})

            r_keys = ["foundation_top_front_ext", "foundation_top_back_ext",
                      "foundation_bottom_back_ext", "foundation_bottom_front_ext"]
            r_pts = [sc(f_orig_x + foundation_data['points'][k][0],
                        f_orig_y + foundation_data['points'][k][1]) for k in r_keys]
            msp.add_lwpolyline(r_pts, close=True,
                               dxfattribs={'layer': '07_BaseRock', 'color': 9})
        else:
            # 岩着：kiso局所座標 → danmen変換で基礎形状を描画
            # f_orig = base_top_front 合わせ点の逆算 → kiso(0,0) = 岩盤面×前面

            def kr(lx, ly):
                return sc(f_orig_x + lx, f_orig_y + ly)

            msp.add_lwpolyline([kr(x, y) for x, y in ume], close=True,
                               dxfattribs={'layer': '05_Foundation', 'color': 5})
            msp.add_lwpolyline([kr(x, y) for x, y in pe_bot], close=True,
                               dxfattribs={'layer': '05_Foundation', 'color': 5})
            msp.add_lwpolyline([kr(x, y) for x, y in pe_bk], close=True,
                               dxfattribs={'layer': '05_Foundation', 'color': 5})

            # 岩盤線：JSON の foundation_top_*_ext（y=0 = 岩盤面 → f_orig_y）
            _fpts = foundation_data['points']
            msp.add_line(sc(f_orig_x + _fpts['foundation_top_front_ext'][0], f_orig_y),
                         sc(f_orig_x + _fpts['foundation_top_back_ext'][0],  f_orig_y),
                         dxfattribs={'layer': '07_BaseRock', 'color': 9})

        # 地盤線
        msp.add_line(sc(gx, gl_y), sc(gl_back, gl_y),
                     dxfattribs={'layer': '06_Ground', 'color': 8})

        # 掘削背面線
        exc_dxf = {'layer': '08_Excavation', 'color': 6, 'linetype': 'DASHED'}
        if struct_type == 'road' and foundation_type == 'direct':
            msp.add_lwpolyline([
                sc(kiso_back_x, kiso_back_y),
                sc(exc_mid_x,   backfill_y),
                sc(fi_btm_x,    fi_btm_y),
                sc(exc_top_x,   exc_top_y),
            ], dxfattribs=exc_dxf)
        else:
            msp.add_line(sc(fi_btm_x, fi_btm_y), sc(exc_top_x, exc_top_y),
                         dxfattribs=exc_dxf)

        # 基準点
        if base_line_type == 'front_toe':
            target_x = gx
            target_y = gl_y
        else:  # tenba_kado（天端の角 = 天端コン上面前面）
            target_x = tenba_top_x
            target_y = tenba_btm_y + tenba_h
        dxf_attr = {'layer': '00_BasePoint', 'color': 6}
        msp.add_line(sc(target_x - 50, target_y), sc(target_x + 50, target_y), dxfattribs=dxf_attr)
        msp.add_line(sc(target_x, target_y - 50), sc(target_x, target_y + 50), dxfattribs=dxf_attr)

        # 水面EL（河川のみ・測点ごと）
        water_els = input_data.get('water_level_els')
        if water_els and i < len(water_els) and water_els[i] is not None:
            el_val    = input_data['elevations'][i]
            wl_y      = target_y + (water_els[i] - el_val) * 1000
            wl_x_left  = min(f_top[0], gl_back) - 1000
            wl_x_right = exc_top_x + 500
            wl_attr   = {'layer': '09_WaterLevel', 'color': 5, 'linetype': 'DASHED'}
            msp.add_line(sc(wl_x_left, wl_y), sc(wl_x_right, wl_y), dxfattribs=wl_attr)
            msp.add_text(
                text=f"水面 EL={water_els[i]:.2f}",
                dxfattribs={'insert': sc(wl_x_right + 100, wl_y), 'height': 250,
                            'layer': '09_WaterLevel', 'color': 5}
            )

        # =========================================================
        # danmen_data.json 用データ収集
        # =========================================================
        def pt(x, y): return [round(x + offset_x, 3), round(y, 3)]

        section = {
            "point_name": pt_name,
            "offset_x":   offset_x,
            "points": {
                "tenba_top_front":    pt(tenba_top_x,                    tenba_btm_y + tenba_h),
                "tenba_top_back":     pt(tenba_data['points'][1]['x'],   tenba_btm_y + tenba_h),
                "tenba_btm_front":    pt(f_top[0],                       tenba_btm_y),
                "tenba_btm_back":     pt(u_top[0],                       tenba_btm_y),
                "block_btm_front":    pt(f_btm[0],                       f_btm[1]),
                "block_btm_back":     pt(b_btm[0],                       b_btm[1]),
                "uracon_btm_back":    pt(u_btm[0],                       u_btm[1]),
                "saiseki_top_front":  pt(u_at_saiseki_top[0],            backfill_top_y),
                "saiseki_top_back":   pt(fi_top[0],                      fi_top[1]),
                "saiseki_btm_front":  pt(u_at_saiseki_btm[0],            backfill_y),
                "saiseki_btm_back":   pt(fi_btm[0],                      fi_btm[1]),
                "kiso_top_front":     pt(kiso_top_front[0],              kiso_top_front[1]),
                "kiso_top_back":      pt(kiso_top_back[0],               kiso_top_back[1]),
                "kiso_btm_front":     pt(kiso_btm_front[0],              kiso_btm_front[1]),
                "kiso_btm_back":      pt(kiso_btm_back[0],               kiso_btm_back[1]),
                "gl_front":           pt(gx,                             gl_y),
                "gl_back":            pt(gl_back,                        gl_y),
                "exc_bottom":         pt(fi_btm[0],                      fi_btm[1]),
                "exc_top":            pt(exc_top_x,                      exc_top_y),
            }
        }

        # 道路直接基礎の場合は掘削中間点を追加
        if struct_type == 'road' and foundation_type == 'direct':
            section["points"]["exc_bottom"]     = pt(kiso_back_x, kiso_back_y)
            section["points"]["exc_mid_bottom"] = pt(exc_mid_x,   backfill_y)
            section["points"]["exc_mid_top"]    = pt(fi_btm[0],   fi_btm[1])
            section["points"]["exc_top"]        = pt(exc_top_x,   exc_top_y)

        all_sections.append(section)

    # JSON出力
    danmen_json = {
        "unit": "mm",
        "num_points": num_points,
        "sections": all_sections
    }
    json_path = os.path.join(output_dir, "danmen_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(danmen_json, f, indent=2, ensure_ascii=False)
    print(f"    データ出力成功: danmen_data.json")

    output_filename = os.path.join(output_dir, "danmen.dxf")
    doc.saveas(output_filename)
    print(f"    生成成功: danmen.dxf")

if __name__ == "__main__":
    main(".")
