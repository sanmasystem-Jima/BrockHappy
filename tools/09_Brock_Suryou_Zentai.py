import json
import math
import os

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def _r3(x):
    """m単位の値を小数点以下3桁に四捨五入する。以降の計算はこの値を使う。"""
    return round(x, 3)

def main(output_dir, **kwargs):
    input_data  = load_json(os.path.join(output_dir, 'input.json'))
    suryo_data  = load_json(os.path.join(output_dir, 'suryo_data.json'))
    tenkai_data = load_json(os.path.join(output_dir, 'tenkai_data.json'))

    if not all([input_data, suryo_data, tenkai_data]):
        print("    [エラー] 必要なJSONファイルが揃っていません。")
        return

    upper_extension = input_data['upper_extension']
    lower_extension = input_data['lower_extension']
    koguchi_type    = input_data.get('koguchi_type', 'none')
    has_gr_kiso     = input_data.get('has_gr_kiso') == 'y'
    front_slope     = input_data['front_slope']
    hikae           = input_data['block_hikae']
    uracon_t        = input_data['ura_con_thickness']
    nobiri          = _r3(math.sqrt(1.0 + front_slope ** 2))

    structure_type   = input_data.get('structure_type', 'road')
    foundation_type  = input_data.get('foundation_type', 'direct')
    water_level_els  = input_data.get('water_level_els')
    is_river         = structure_type in ('river', 'river_gohan')
    use_water_clip_direct = is_river and foundation_type == 'direct'
    use_water_clip_rock   = is_river and foundation_type == 'rock'

    sections = suryo_data['sections']
    num_spans = len(upper_extension)

    # 水抜きパイプ対象高さ
    #   直接基礎（河川）：裏砕石高さのうち水面より上の部分
    #   岩着基礎（河川）：裏砕石底面と水面の高い方を基準に、その上のブロック高さ（法長範囲）
    #   それ以外：従来通り裏砕石高さをそのまま使用
    nuki_h_list = []
    for idx, sec in enumerate(sections):
        wl = water_level_els[idx] if (water_level_els and idx < len(water_level_els)) else None
        if use_water_clip_direct and wl is not None:
            h = max(0.0, min(sec['saiseki_h_m'], sec['saiseki_top_el'] - max(sec['saiseki_bottom_el'], wl)))
        elif use_water_clip_rock and wl is not None:
            threshold = max(sec['saiseki_bottom_el'], wl)
            h = max(0.0, min(sec['block_top_el'] - sec['block_bottom_el'], sec['block_top_el'] - threshold))
        else:
            h = sec['saiseki_h_m']
        nuki_h_list.append(_r3(h))

    # =========================================================
    # ① ブロック面積 / ② 裏コン体積 / ③ 裏砕石体積 / ⑦ 水抜き対象面積
    # =========================================================
    block_area_m2  = 0.0
    uracon_vol_m3  = 0.0
    saiseki_vol_m3 = 0.0
    nukipipe_area  = 0.0

    span_rows = []
    for i in range(num_spans):
        sec_a = sections[i]
        sec_b = sections[i + 1]
        ext_avg = _r3((upper_extension[i] + lower_extension[i]) / 2.0)

        hocho_avg   = _r3((sec_a['hocho_m']         + sec_b['hocho_m'])         / 2.0)
        uracon_avg  = _r3((sec_a['uracon_area_m2']  + sec_b['uracon_area_m2'])  / 2.0)
        saiseki_avg = _r3((sec_a['saiseki_area_m2'] + sec_b['saiseki_area_m2']) / 2.0)
        saiseki_h_avg = _r3((nuki_h_list[i] + nuki_h_list[i + 1]) / 2.0)

        block_area  = _r3(hocho_avg   * ext_avg)
        uracon_vol  = _r3(uracon_avg  * ext_avg)
        saiseki_vol = _r3(saiseki_avg * ext_avg)
        nuki_area   = _r3(saiseki_h_avg * nobiri * ext_avg)

        block_area_m2  += block_area
        uracon_vol_m3  += uracon_vol
        saiseki_vol_m3 += saiseki_vol
        nukipipe_area  += nuki_area

        span_rows.append({
            'span_no':     i + 1,
            'p1':          sec_a['point_name'],
            'p2':          sec_b['point_name'],
            'ext_avg':     ext_avg,
            'upper':       upper_extension[i],
            'lower':       lower_extension[i],
            'hocho_avg':   hocho_avg,
            'hocho_a':     sec_a['hocho_m'],
            'hocho_b':     sec_b['hocho_m'],
            'block_area':  block_area,
            'uracon_avg':  uracon_avg,
            'uracon_a':    sec_a['uracon_area_m2'],
            'uracon_b':    sec_b['uracon_area_m2'],
            'uracon_vol':  uracon_vol,
            'saiseki_avg': saiseki_avg,
            'saiseki_a':   sec_a['saiseki_area_m2'],
            'saiseki_b':   sec_b['saiseki_area_m2'],
            'saiseki_vol': saiseki_vol,
            'saiseki_h_avg': saiseki_h_avg,
            'saiseki_h_a': nuki_h_list[i],
            'saiseki_h_b': nuki_h_list[i + 1],
            'nuki_area':   nuki_area,
        })

    block_area_m2  = _r3(block_area_m2)
    uracon_vol_m3  = _r3(uracon_vol_m3)
    saiseki_vol_m3 = _r3(saiseki_vol_m3)
    nukipipe_area  = _r3(nukipipe_area)

    # =========================================================
    # ④ 基礎コンクリート延長 / ⑤ 天端コン延長
    # =========================================================
    kiso_extension_m = _r3(tenkai_data['kiso_actual_m'])
    if has_gr_kiso:
        tenba_extension_m = _r3(tenkai_data['tenba_actual_m'] + tenkai_data['koguchi_deduction_m'])
    else:
        tenba_extension_m = _r3(tenkai_data['tenba_actual_m'])

    # =========================================================
    # ⑥ 小口止コンクリート基数
    # =========================================================
    koguchi_kisuu = {'both': 2, 'left': 1, 'right': 1, 'none': 0}.get(koguchi_type, 0)

    # =========================================================
    # ⑦ 水抜きパイプ 本数・長さ
    # =========================================================
    nukipipe_honsuu = math.ceil(nukipipe_area / 3.0) if nukipipe_area > 0 else 0
    nukipipe_len_each = _r3((hikae + uracon_t) * nobiri)
    nukipipe_len_total = _r3(nukipipe_honsuu * nukipipe_len_each)

    # =========================================================
    # ⑧ 目地材
    # =========================================================
    meji_records = tenkai_data.get('meji', [])
    meji_unit_w = _r3(hikae + uracon_t)
    meji_rows = []
    meji_area_m2 = 0.0
    for idx, m in enumerate(meji_records):
        area = _r3(meji_unit_w * m['hocho_m'])
        meji_area_m2 += area
        meji_rows.append({'no': idx + 1, 'hocho_m': m['hocho_m'], 'area': area})
    meji_area_m2 = _r3(meji_area_m2)

    # =========================================================
    # テキスト出力
    # =========================================================
    SEP  = "=" * 56
    SEP2 = "-" * 56

    lines = [SEP, "    全体数量計算書", SEP, ""]

    lines.append("【①ブロック】")
    for r in span_rows:
        lines.append(
            f"  測点{r['p1']}〜{r['p2']}: "
            f"({r['hocho_a']:.3f}+{r['hocho_b']:.3f})/2 × "
            f"({r['upper']:.3f}+{r['lower']:.3f})/2 = {r['block_area']:.3f} m2"
        )
    lines.append(f"  合計 = {block_area_m2:.3f} m2")
    lines.append(SEP2)

    lines.append("【②裏コンクリート】")
    for r in span_rows:
        lines.append(
            f"  測点{r['p1']}〜{r['p2']}: "
            f"({r['uracon_a']:.3f}+{r['uracon_b']:.3f})/2 × "
            f"({r['upper']:.3f}+{r['lower']:.3f})/2 = {r['uracon_vol']:.3f} m3"
        )
    lines.append(f"  合計 = {uracon_vol_m3:.3f} m3")
    lines.append(SEP2)

    lines.append("【③裏砕石】")
    for r in span_rows:
        lines.append(
            f"  測点{r['p1']}〜{r['p2']}: "
            f"({r['saiseki_a']:.3f}+{r['saiseki_b']:.3f})/2 × "
            f"({r['upper']:.3f}+{r['lower']:.3f})/2 = {r['saiseki_vol']:.3f} m3"
        )
    lines.append(f"  合計 = {saiseki_vol_m3:.3f} m3")
    lines.append(SEP2)

    lines.append("【④基礎コンクリート】")
    lines.append(f"  延長 = {kiso_extension_m:.3f} m")
    lines.append(SEP2)

    lines.append("【⑤天端コン】")
    gr_note = "（GR基礎：小口止上の延長を含む）" if has_gr_kiso else "（ブロック上のみ）"
    lines.append(f"  延長 = {tenba_extension_m:.3f} m {gr_note}")
    lines.append(SEP2)

    lines.append("【⑥小口止コンクリート】")
    lines.append(f"  基数 = {koguchi_kisuu} 基（koguchi_type={koguchi_type}）")
    lines.append(SEP2)

    lines.append("【⑦水抜きパイプ】")
    if use_water_clip_direct:
        lines.append("  ※河川＋直接基礎のため、水面より上の砕石高さのみで算出")
    elif use_water_clip_rock:
        lines.append("  ※河川＋岩着基礎のため、裏砕石底面と水面の高い方より上のブロック高さで算出")
    for r in span_rows:
        lines.append(
            f"  測点{r['p1']}〜{r['p2']}: "
            f"({r['saiseki_h_a']:.3f}+{r['saiseki_h_b']:.3f})/2 × {nobiri:.3f} × "
            f"({r['upper']:.3f}+{r['lower']:.3f})/2 = {r['nuki_area']:.3f} m2"
        )
    lines.append(f"  対象面積 合計 = {nukipipe_area:.3f} m2")
    lines.append(f"  本数 = ceil({nukipipe_area:.3f} / 3.0) = {nukipipe_honsuu} 本")
    lines.append(f"  1本長さ = ({hikae:.3f}+{uracon_t:.3f}) × {nobiri:.3f} = {nukipipe_len_each:.3f} m")
    lines.append(f"  延長   = {nukipipe_honsuu} × {nukipipe_len_each:.3f} = {nukipipe_len_total:.3f} m")
    lines.append(SEP2)

    lines.append("【⑧目地材】")
    if meji_rows:
        for r in meji_rows:
            lines.append(
                f"  目地{r['no']}: ({hikae:.3f}+{uracon_t:.3f}) × {r['hocho_m']:.3f} = {r['area']:.3f} m2"
            )
    else:
        lines.append("  目地箇所なし")
    lines.append(f"  合計 = {meji_area_m2:.3f} m2")
    lines.append(SEP2)

    lines += [
        "",
        "  * 全体数量 まとめ",
        f"    ①ブロック         : {block_area_m2:.3f} m2",
        f"    ②裏コンクリート   : {uracon_vol_m3:.3f} m3",
        f"    ③裏砕石           : {saiseki_vol_m3:.3f} m3",
        f"    ④基礎コンクリート : {kiso_extension_m:.3f} m",
        f"    ⑤天端コン         : {tenba_extension_m:.3f} m",
        f"    ⑥小口止コンクリート: {koguchi_kisuu} 基",
        f"    ⑦水抜きパイプ     : {nukipipe_honsuu} 本 / {nukipipe_len_total:.3f} m",
        f"    ⑧目地材           : {meji_area_m2:.3f} m2",
        SEP,
    ]

    text = "\n".join(lines)
    print(text)

    out_path = os.path.join(output_dir, 'suryou_brock.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"\n    生成成功: suryou_brock.txt")

if __name__ == "__main__":
    main(".")
