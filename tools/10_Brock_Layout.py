import glob
import json
import os
import ezdxf
from ezdxf import bbox
from ezdxf.math import BoundingBox
from ezdxf.addons.importer import Importer

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

SPACING_X = 20000.0   # 05_Brock_Danmen.py の測点間隔（mm）と一致させる

def _explode_dimensions_in_place(doc):
    """DIMENSIONエンティティをLINE/INSERT/TEXT等の実体に展開し、元のDIMENSIONを削除する。
    Importerは無名ブロック（DIMENSIONの見た目本体）をコピーしないため、そのままインポートすると
    統合先のスタイル設定でDIMENSIONが再生成され、矢印サイズ・向きが崩れてしまう。
    あらかじめ実体化しておくことで、見た目をそのままコピーできるようにする。"""
    msp = doc.modelspace()
    dims = [e for e in msp if e.dxftype() == 'DIMENSION']
    for dim in dims:
        for ve in dim.virtual_entities():
            msp.add_entity(ve)
        msp.delete_entity(dim)

def _section_entities(msp, offset_x, spacing=SPACING_X):
    """danmen.dxf の中から指定セクション（offset_x）に属するエンティティだけを抜き出す。"""
    x_lo = offset_x - spacing / 2
    x_hi = offset_x + spacing / 2
    found = []
    for e in msp:
        bb = bbox.extents([e], fast=True)
        if not bb.has_data:
            continue
        cx = (bb.extmin.x + bb.extmax.x) / 2
        if x_lo <= cx < x_hi:
            found.append(e)
    return found

def _flatten_section_offsets(danmen_data):
    """danmen_data['sections']を、通常/ダブル断面（工種が変わる測点）を区別しない
    offset_xのフラットなリストに変換する（05_Brock_Danmen.pyが描画した順・並びと一致する）。"""
    offsets = []
    for sec in danmen_data['sections']:
        if sec.get('is_dual'):
            offsets.append(sec['incoming']['offset_x'])
            offsets.append(sec['outgoing']['offset_x'])
        else:
            offsets.append(sec['offset_x'])
    return offsets

def _koguchi_cluster_extents(cluster):
    """ezdxf bbox.extents()はTEXTの幅をフォント形状(インク幅)から推定するため、
    V-nasの等幅フォントによる実際の描画幅(=文字数×文字高さ、08_Brock_Suryou.pyの
    write_koguchi_dxf_text参照)より狭く見積もり、KOGUCHI_SURYOUレイヤの数量計算テキストが
    仮想矩形からはみ出してしまう。このレイヤのTEXTだけ実描画幅で計算し直し、他は通常のbboxと合成する。"""
    others = [e for e in cluster if not (e.dxftype() == 'TEXT' and e.dxf.layer == 'KOGUCHI_SURYOU')]
    suryou_texts = [e for e in cluster if e.dxftype() == 'TEXT' and e.dxf.layer == 'KOGUCHI_SURYOU']

    bb = bbox.extents(others, fast=True) if others else bbox.extents(cluster, fast=True)
    xmin, ymin, xmax, ymax = bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y

    for e in suryou_texts:
        x0, y0 = e.dxf.insert.x, e.dxf.insert.y
        x1 = x0 + len(e.dxf.text) * e.dxf.height
        y1 = y0 + e.dxf.height
        xmin, ymin = min(xmin, x0), min(ymin, y0)
        xmax, ymax = max(xmax, x1), max(ymax, y1)

    return BoundingBox([(xmin, ymin, 0.0), (xmax, ymax, 0.0)])


def _cluster_entities_by_label(msp, label_prefix="測点"):
    """koguchi.dxf は測点ごとの図がX方向に並んでいるが、danmenのような等間隔配置ではないため、
    '測点 ' で始まるTEXTの個数を測点図の数とみなし、X方向の最大ギャップで分割してクラスタリングする。"""
    entities = [(bbox.extents([e], fast=True), e) for e in msp]
    entities = [((bb.extmin.x + bb.extmax.x) / 2, e) for bb, e in entities if bb.has_data]
    entities.sort(key=lambda t: t[0])

    num_labels = sum(
        1 for e in msp
        if e.dxftype() == 'TEXT' and e.dxf.text.startswith(label_prefix)
    )
    if num_labels <= 1 or not entities:
        return [[e for _, e in entities]]

    gaps = sorted(
        (entities[i + 1][0] - entities[i][0], i) for i in range(len(entities) - 1)
    )
    split_after = sorted(i for _, i in gaps[-(num_labels - 1):])

    clusters, start = [], 0
    for idx in split_after:
        clusters.append([e for _, e in entities[start:idx + 1]])
        start = idx + 1
    clusters.append([e for _, e in entities[start:]])
    return clusters

def _pack_shelf(items, start_x, start_y, right_x, gap):
    """items: [(key, w, h), ...] を左→右に詰め、right_xを超える前に次の行へ折り返す
    シェルフ（棚）パッキング。戻り値は [(key, x_left, y_top), ...] と配置後の最下端y。"""
    placements = []
    cur_x, cur_y, row_h = start_x, start_y, 0.0
    for key, w, h in items:
        if cur_x != start_x and cur_x + w > right_x:
            cur_y -= row_h + gap
            cur_x = start_x
            row_h = 0.0
        placements.append((key, cur_x, cur_y))
        cur_x += w + gap
        row_h = max(row_h, h)
    bottom_y = cur_y - row_h
    return placements, bottom_y

def main(output_dir, **kwargs):
    input_data = load_json(os.path.join(output_dir, 'input.json'))
    danmen_data = load_json(os.path.join(output_dir, 'danmen_data.json'))

    if not all([input_data, danmen_data]):
        print("    [エラー] 必要なJSONファイルが揃っていません。")
        return

    tenkai_path = os.path.join(output_dir, 'tenkai.dxf')
    # danmen_sunpou.dxf は danmen.dxf に寸法線・数量表を追記したもの（同じoffset_x配置）
    danmen_path = os.path.join(output_dir, 'danmen_sunpou.dxf')
    if not (os.path.exists(tenkai_path) and os.path.exists(danmen_path)):
        print("    [エラー] tenkai.dxf / danmen_sunpou.dxf が見つかりません。")
        return

    # 天端詳細図・基礎詳細図・小口止図（任意。無ければ展開図のみで続行）
    tenba_path = os.path.join(output_dir, 'tenba_danmen.dxf')
    koguchi_path = os.path.join(output_dir, 'koguchi.dxf')
    doc_tb = ezdxf.readfile(tenba_path) if os.path.exists(tenba_path) else None
    doc_kg = ezdxf.readfile(koguchi_path) if os.path.exists(koguchi_path) else None
    if doc_tb is None:
        print("    [警告] tenba_danmen.dxf が見つかりません（天端詳細図は省略）。")
    else:
        _explode_dimensions_in_place(doc_tb)
    if doc_kg is None:
        print("    [警告] koguchi.dxf が見つかりません（小口止図は省略）。")
    else:
        _explode_dimensions_in_place(doc_kg)

    # 基礎詳細図：基礎形式が区間で複数種類ある場合、kiso_danmen.dxf（先頭スパン）に加えて
    # kiso_danmen_<種別>.dxf も全部並べて表記する（02_Brock_Kiso.pyが種類の数だけ生成している）
    kiso_paths = [os.path.join(output_dir, 'kiso_danmen.dxf')]
    kiso_paths += sorted(glob.glob(os.path.join(output_dir, 'kiso_danmen_*.dxf')))
    kiso_docs = []
    for p in kiso_paths:
        if os.path.exists(p):
            d = ezdxf.readfile(p)
            _explode_dimensions_in_place(d)
            kiso_docs.append(d)
    if not kiso_docs:
        print("    [警告] kiso_danmen.dxf が見つかりません（基礎詳細図は省略）。")

    scale_tenkai = input_data.get('scale_tenkai', 50)
    scale_danmen = input_data.get('scale_danmen', 50)

    # シート全体の印刷スケール（V-nas側で最終的に1:sheet_scaleで印刷する想定）。
    # DXFは常に実寸(mm)のまま保持し、V-nasが「読み込み1/1＋全体縮尺1/sheet_scale」で
    # 表示・印刷することで正しいサイズになる（文字・寸法もこの前提で実寸化されている）。
    # 図面ごとのscaleがsheet_scaleと異なる場合だけ、その比率分だけ実寸を補正する
    # （例：シート1:50に対して1:200の図面を混在させるなら、実寸を50/200=0.25倍に縮小）。
    sheet_scale = kwargs.get('sheet_scale', scale_danmen)
    s_t = sheet_scale / scale_tenkai
    s_d = sheet_scale / scale_danmen

    doc_t = ezdxf.readfile(tenkai_path)
    doc_d = ezdxf.readfile(danmen_path)
    # DIMENSIONはImporterで無名ブロック（見た目本体）がコピーされず、統合先で再計算されて
    # 見た目が変わってしまう（サイズ・矢印など）。個別ファイルの見た目を一切変えないため、
    # 全ソースの寸法線を読み込み直後にLINE/INSERT/TEXT等へ実体化しておく。
    _explode_dimensions_in_place(doc_t)
    _explode_dimensions_in_place(doc_d)

    bbox_t = bbox.extents(doc_t.modelspace(), fast=True)

    # =========================================================
    # A1横使い シート（841×594mm。1:sheet_scaleで印刷する前提の実寸サイズに換算）
    # =========================================================
    SHEET_W, SHEET_H = 841.0 * sheet_scale, 594.0 * sheet_scale
    MARGIN = 20.0 * sheet_scale
    GAP    = 15.0 * sheet_scale   # 展開図と断面図の間隔

    combined = ezdxf.new('R2018')
    combined.header['$INSUNITS'] = 4
    combined.styles.add("MS-GOTHIC", font="msgothic.ttc")
    if 'DASHED' not in [lt.dxf.name for lt in combined.linetypes]:
        combined.linetypes.add('DASHED', pattern=[0.5, 0.25, -0.25])
    combined.layers.get('Defpoints').dxf.plot = 0   # 確認用の仮想矩形は印刷しない
    msp = combined.modelspace()

    # 用紙枠（目印）
    msp.add_lwpolyline(
        [(0, 0), (SHEET_W, 0), (SHEET_W, SHEET_H), (0, SHEET_H)],
        close=True, dxfattribs={'layer': 'SHEET_FRAME', 'color': 8}
    )

    # =========================================================
    # 表題（紙の中央上部、14mm文字＋アンダーライン）
    # =========================================================
    block_hikae_cm = int(round(input_data.get('block_hikae', 0.0) * 100))
    ura_con_cm     = int(round(input_data.get('ura_con_thickness', 0.0) * 100))
    front_slope    = input_data.get('front_slope', 0.4)
    title_text  = f"ブロック積工　控{block_hikae_cm}cm　裏コン{ura_con_cm}cm　勾配1：{front_slope:g}"
    title_h     = 14.0 * sheet_scale
    title_cx    = SHEET_W / 2.0
    title_y     = SHEET_H - MARGIN - title_h

    t_obj = msp.add_text(title_text, height=title_h, dxfattribs={'layer': 'TEXT', 'style': 'MS-GOTHIC'})
    t_obj.dxf.halign      = 1
    t_obj.dxf.insert      = (title_cx, title_y)
    t_obj.dxf.align_point = (title_cx, title_y)

    # V-nasは等幅フォントで描画されるため、実描画幅=文字数×文字高さで計算できる（[[brock-text-width-measurement]]）
    title_w = len(title_text) * title_h
    underline_y = title_y - 0.15 * title_h
    msp.add_line(
        (title_cx - title_w / 2.0, underline_y),
        (title_cx + title_w / 2.0, underline_y),
        dxfattribs={'layer': 'TEXT'}
    )

    # =========================================================
    # ブロック化（展開図1個＋断面図を測点ごとに分割）
    # =========================================================
    tenkai_blk = combined.blocks.new('TENKAI_BLK')
    importer_t = Importer(doc_t, combined)
    importer_t.import_entities(doc_t.modelspace(), target_layout=tenkai_blk)
    importer_t.finalize()

    # tenba_danmen.dxf / kiso_danmen.dxf は生成時点で座標が既に「用紙mm」(実寸mm/scale_kiso)
    # に変換済みのため、tenkai/danmenと違いさらに scale で割る必要はない。
    # 統合canvas換算は sheet_scale を直接掛けるだけでよい
    # （= 用紙mm × sheet_scale。最終的にV-nas側で1/sheet_scaleに縮小されるため、
    #   物理印刷サイズは用紙mmそのものに戻る＝元の1/scale_kiso表示が保たれる）。
    bbox_tb = None
    tb_w = tb_h = 0.0
    if doc_tb is not None:
        tenba_blk = combined.blocks.new('TENBA_BLK')
        importer_tb = Importer(doc_tb, combined)
        importer_tb.import_entities(doc_tb.modelspace(), target_layout=tenba_blk)
        importer_tb.finalize()
        bbox_tb = bbox.extents(doc_tb.modelspace(), fast=True)
        tb_w = sheet_scale * (bbox_tb.extmax.x - bbox_tb.extmin.x)
        tb_h = sheet_scale * (bbox_tb.extmax.y - bbox_tb.extmin.y)

    # 基礎詳細図：種類の数だけ個別ブロック化し、後段で他の要素と並べて配置する
    kiso_blocks = []  # (block_name, bbox_local)
    for i, d in enumerate(kiso_docs):
        importer_k = Importer(d, combined)
        block_name = f"KISO_BLK_{i}"
        blk = combined.blocks.new(block_name)
        importer_k.import_entities(d.modelspace(), target_layout=blk)
        importer_k.finalize()
        bbox_i = bbox.extents(d.modelspace(), fast=True)
        kiso_blocks.append((block_name, bbox_i))

    # koguchi.dxf は danmen_sunpou.dxf と同じ scale_danmen で生成されている（実寸mm保持・
    # 文字も実寸座標に組み込み済み）ため、danmenと同じ s_d 換算でそのまま統合できる。
    # ただし測点ごとの図がdanmenのような等間隔ではなくX方向に離れて配置されているため、
    # 丸ごと1ブロックにすると幅が巨大になる→測点単位でクラスタリングして個別ブロック化する。
    koguchi_blocks = []  # (block_name, bbox_local)
    if doc_kg is not None:
        importer_kg = Importer(doc_kg, combined)
        for i, cluster in enumerate(_cluster_entities_by_label(doc_kg.modelspace())):
            if not cluster:
                continue
            bbox_i = _koguchi_cluster_extents(cluster)
            block_name = f"KOGUCHI_{i}"
            blk = combined.blocks.new(block_name)
            importer_kg.import_entities(cluster, target_layout=blk)
            koguchi_blocks.append((block_name, bbox_i))
        importer_kg.finalize()

    importer_d = Importer(doc_d, combined)
    section_blocks = []  # (block_name, bbox_local, s_d)
    for i, offset_x in enumerate(_flatten_section_offsets(danmen_data)):
        entities_i = _section_entities(doc_d.modelspace(), offset_x)
        if not entities_i:
            continue
        bbox_i = bbox.extents(entities_i, fast=True)
        block_name = f"DANMEN_{i}"
        blk = combined.blocks.new(block_name)
        importer_d.import_entities(entities_i, target_layout=blk)
        section_blocks.append((block_name, bbox_i))
    importer_d.finalize()

    # =========================================================
    # 各要素の「ギリギリの大きさ（紙面換算）」を算出し、シェルフパッキングで自動配置
    # 展開図は単独で1行（最上段）、断面図3個はその下の行から詰めて配置する。
    # =========================================================
    right_x = SHEET_W - MARGIN

    tenkai_w = s_t * (bbox_t.extmax.x - bbox_t.extmin.x)
    tenkai_h = s_t * (bbox_t.extmax.y - bbox_t.extmin.y)

    # 上段：展開図の右側に天端詳細図→基礎詳細図（種類の数だけ）を横並び配置
    top_items = [('TENKAI_BLK', tenkai_w, tenkai_h)]
    if doc_tb is not None:
        top_items.append(('TENBA_BLK', tb_w, tb_h))
    top_items.extend(
        (block_name, sheet_scale * (bbox_i.extmax.x - bbox_i.extmin.x),
         sheet_scale * (bbox_i.extmax.y - bbox_i.extmin.y))
        for block_name, bbox_i in kiso_blocks
    )
    top_items.extend(
        (block_name, s_d * (bbox_i.extmax.x - bbox_i.extmin.x), s_d * (bbox_i.extmax.y - bbox_i.extmin.y))
        for block_name, bbox_i in koguchi_blocks
    )
    content_top_y = underline_y - GAP  # 表題＋アンダーラインの下に重ならないよう開始位置を下げる
    top_placements, top_bottom = _pack_shelf(
        top_items, MARGIN, content_top_y, right_x, GAP
    )

    danmen_items = [
        (block_name, s_d * (bbox_i.extmax.x - bbox_i.extmin.x), s_d * (bbox_i.extmax.y - bbox_i.extmin.y))
        for block_name, bbox_i in section_blocks
    ]
    # 今は折り返しなし、3個とも横並びで配置する（right_xを無限大にして折り返しを無効化）
    danmen_placements, bottom_y = _pack_shelf(
        danmen_items, MARGIN, top_bottom - GAP, float('inf'), GAP
    )
    placements = top_placements + danmen_placements

    if bottom_y < MARGIN:
        print(f"    [警告] レイアウトがシート下端を超えています（{MARGIN - bottom_y:.0f}mm超過）。")

    bbox_lookup = {'TENKAI_BLK': bbox_t}
    bbox_lookup.update({name: b for name, b in section_blocks})
    scale_lookup = {'TENKAI_BLK': s_t}
    scale_lookup.update({name: s_d for name, _ in section_blocks})
    layer_lookup = {'TENKAI_BLK': 'TENKAI'}
    layer_lookup.update({name: 'DANMEN' for name, _ in section_blocks})
    if doc_tb is not None:
        bbox_lookup['TENBA_BLK'] = bbox_tb
        scale_lookup['TENBA_BLK'] = sheet_scale
        layer_lookup['TENBA_BLK'] = 'TENBA'
    bbox_lookup.update({name: b for name, b in kiso_blocks})
    scale_lookup.update({name: sheet_scale for name, _ in kiso_blocks})
    layer_lookup.update({name: 'KISO' for name, _ in kiso_blocks})
    bbox_lookup.update({name: b for name, b in koguchi_blocks})
    scale_lookup.update({name: s_d for name, _ in koguchi_blocks})
    layer_lookup.update({name: 'KOGUCHI' for name, _ in koguchi_blocks})

    for block_name, x_left, y_top in placements:
        b = bbox_lookup[block_name]
        s = scale_lookup[block_name]
        w = s * (b.extmax.x - b.extmin.x)
        h = s * (b.extmax.y - b.extmin.y)
        insert_x = x_left - s * b.extmin.x
        insert_y = y_top - s * b.extmax.y
        msp.add_blockref(
            block_name, insert=(insert_x, insert_y),
            dxfattribs={'xscale': s, 'yscale': s, 'layer': layer_lookup[block_name]}
        )
        # 確認用の仮想矩形（ギリギリの大きさ）。Defpointsレイヤは印刷されない
        msp.add_lwpolyline(
            [(x_left, y_top), (x_left + w, y_top), (x_left + w, y_top - h), (x_left, y_top - h)],
            close=True, dxfattribs={'layer': 'Defpoints', 'color': 8}
        )

    out_path = os.path.join(output_dir, 'layout.dxf')
    combined.saveas(out_path)
    print(f"    生成成功: layout.dxf")

if __name__ == "__main__":
    main(".")
