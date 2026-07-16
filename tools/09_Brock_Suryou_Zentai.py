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

def _kind_label(foundation_type, rock_type):
    if foundation_type == 'rock':
        return {'nangan1': '岩着・軟岩Ⅰ', 'nangan2': '岩着・軟岩Ⅱ以上'}.get(rock_type, f'岩着・{rock_type}')
    return '直接基礎'

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

    # ④基礎コンクリートは区間ごとの基礎形式で計算方法（ペーライン／延長）が変わるため、
    # スパン自身の基礎形式（区間対応）を使う（プロジェクト全体の代表値では決め打ちしない）
    span_foundation_types = input_data.get('foundation_types') or [foundation_type] * num_spans
    span_rock_types       = input_data.get('rock_types') or [input_data.get('rock_type')] * num_spans

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

        span_ft = span_foundation_types[i] if i < len(span_foundation_types) else foundation_type

        peline_avg = peline_vol = None
        if span_ft == 'rock':
            # ペーライン（基礎）は下端の延長(下延長)のみで決まるため、上下平均ではなく下延長を使う
            # （境界測点はもう一方の工種側の値になっている場合があるため、片側だけでもフォールバックする）
            pa = sec_a.get('peline_area_m2')
            pb = sec_b.get('peline_area_m2')
            if pa is None: pa = pb
            if pb is None: pb = pa
            if pa is not None and pb is not None:
                peline_avg = _r3((pa + pb) / 2.0)
                peline_vol = _r3(peline_avg * lower_extension[i])

        span_rows.append({
            'span_no':     i + 1,
            'foundation_type': span_ft,
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
            'peline_avg':  peline_avg,
            'peline_a':    sec_a.get('peline_area_m2'),
            'peline_b':    sec_b.get('peline_area_m2'),
            'peline_vol':  peline_vol,
        })

    block_area_m2  = _r3(block_area_m2)
    uracon_vol_m3  = _r3(uracon_vol_m3)
    saiseki_vol_m3 = _r3(saiseki_vol_m3)
    nukipipe_area  = _r3(nukipipe_area)

    # =========================================================
    # ④ 基礎コンクリート：区間の基礎形式ごとに計算（岩着=ペーライン立米／直接=延長）してから集計
    # =========================================================
    kiso_extension_m = _r3(tenkai_data['kiso_actual_m'])   # 後方互換用（全区間合計の延長、参考値）

    kiso_by_kind = tenkai_data.get('kiso_by_kind') or [{
        'foundation_type': foundation_type,
        'rock_type':       input_data.get('rock_type'),
        'span_start':      0,
        'span_end':        num_spans - 1,
        'length_m':        kiso_extension_m,
    }]

    kiso_kind_rows = []
    for kbk in kiso_by_kind:
        ft = kbk['foundation_type']
        rt = kbk.get('rock_type')
        s0 = kbk.get('span_start', 0)
        s1 = kbk.get('span_end', num_spans - 1)
        label = _kind_label(ft, rt)
        if ft == 'rock':
            spans_in_kind = [span_rows[s] for s in range(s0, s1 + 1) if s < len(span_rows)]
            vol = _r3(sum((r['peline_vol'] or 0.0) for r in spans_in_kind))
            kiso_kind_rows.append({
                'label': label, 'unit': 'm3', 'value': vol,
                'spans': spans_in_kind,
            })
        else:
            kiso_kind_rows.append({
                'label': label, 'unit': 'm', 'value': kbk['length_m'],
                'spans': [],
            })

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

    lines.append("【④基礎コンクリート（区間の基礎形式ごとに計算）】")
    for kr in kiso_kind_rows:
        lines.append(f"  [{kr['label']}]")
        if kr['unit'] == 'm3':
            for r in kr['spans']:
                if r['peline_vol'] is None:
                    continue
                lines.append(
                    f"    測点{r['p1']}〜{r['p2']}: "
                    f"({r['peline_a']:.4f}+{r['peline_b']:.4f})/2 × "
                    f"{r['lower']:.3f}(下延長) = {r['peline_vol']:.3f} m3"
                )
            lines.append(f"    ペーライン 合計 = {kr['value']:.3f} m3")
        else:
            lines.append(f"    延長 = {kr['value']:.3f} m")
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

    kiso_summary_lines = [
        f"    ④基礎コンクリート : {kr['label']} {kr['value']:.3f} {kr['unit']}"
        for kr in kiso_kind_rows
    ] if len(kiso_kind_rows) > 1 else [
        f"    ④基礎コンクリート : {kiso_kind_rows[0]['value']:.3f} {kiso_kind_rows[0]['unit']}"
        + ("（ペーライン）" if kiso_kind_rows[0]['unit'] == 'm3' else "")
    ]

    lines += [
        "",
        "  * 全体数量 まとめ",
        f"    ①ブロック         : {block_area_m2:.3f} m2",
        f"    ②裏コンクリート   : {uracon_vol_m3:.3f} m3",
        f"    ③裏砕石           : {saiseki_vol_m3:.3f} m3",
        *kiso_summary_lines,
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
