import json
import os
import sys
import importlib

_DISPATCH = {
    ('護岸', 'rock'):   '07a_Kokuti_Gogan_Rock',
    ('護岸', 'direct'): '07b_Kokuti_Gogan_Direct',
    ('法留', 'rock'):   '07c_Kokuti_Hato_Rock',
    ('法留', 'direct'): '07d_Kokuti_Hato_Direct',
    ('道台', 'rock'):   '07e_Kokuti_Dotai_Rock',
    ('道台', 'direct'): '07f_Kokuti_Dotai_Direct',
}


def _explode_dimensions_in_place(doc):
    """DIMENSIONエンティティをLINE/INSERT/TEXT等の実体に展開し、元のDIMENSIONを削除する。
    Importerは無名ブロック（DIMENSIONの見た目本体）をコピーしないため、そのままインポートすると
    統合先のスタイル設定でDIMENSIONが再生成され、矢印サイズ・向きが崩れてしまう
    （10_Brock_Layout.pyと同じ対策）。"""
    msp = doc.modelspace()
    dims = [e for e in msp if e.dxftype() == 'DIMENSION']
    for dim in dims:
        for ve in dim.virtual_entities():
            msp.add_entity(ve)
        msp.delete_entity(dim)


def _derive_structure_name(input_data):
    structure_name = input_data.get('structure_name', '')
    if not structure_name:
        stype = input_data.get('structure_type', '')
        bline = input_data.get('base_line_type', '')
        if stype in ('river', 'river_gohan'):
            structure_name = '護岸'
        elif stype in ('road', 'road_dai'):
            structure_name = '法留' if bline == 'front_toe' else '道台'
        elif stype == 'road_tome':
            structure_name = '法留'
    return structure_name


def main(output_dir, **kwargs):
    path = os.path.join(output_dir, 'input.json')
    if not os.path.exists(path):
        print("    [エラー] input.json が見つかりません。")
        return

    with open(path, 'r', encoding='utf-8') as f:
        input_data = json.load(f)

    structure_name = _derive_structure_name(input_data)

    koguchi_type = input_data.get('koguchi_type', 'none')
    if koguchi_type == 'none':
        print("    [スキップ] 小口止コンクリートなし")
        return

    danmen_path = os.path.join(output_dir, 'danmen_data.json')
    if not os.path.exists(danmen_path):
        print("    [エラー] danmen_data.json が見つかりません。05を先に実行してください。")
        return
    with open(danmen_path, 'r', encoding='utf-8') as f:
        danmen_data = json.load(f)

    sections = danmen_data.get('sections', [])
    n = len(sections)
    if n == 0:
        print("    [エラー] danmen_data.json に測点データがありません。")
        return

    side_indices = []
    if koguchi_type in ('both', 'left'):
        side_indices.append(0)
    if koguchi_type in ('both', 'right') and n > 1:
        side_indices.append(n - 1)
    if not side_indices:
        side_indices = [n - 1]  # 測点1つ・right指定など

    tools_dir = os.path.dirname(os.path.abspath(__file__))
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)

    # 小口止対象の各測点について、その測点自身の基礎形式（区間対応済み）で担当モジュールを決める
    # （左右で基礎形式が異なる場合、従来のようにプロジェクト全体で1つのモジュールに決め打ちしない）
    primary_ft = input_data.get('foundation_type', 'direct')
    groups = {}   # child_name -> [sec_i, ...]（登場順）
    for sec_i in side_indices:
        sec = sections[sec_i]
        ft = sec.get('foundation_type') or primary_ft
        child_name = _DISPATCH.get((structure_name, ft))
        if child_name is None:
            print(f"    [エラー] 未対応の組み合わせ: {structure_name} / {ft}")
            return
        groups.setdefault(child_name, []).append(sec_i)

    def _load_child(name):
        try:
            return importlib.import_module(name)
        except ImportError:
            print(f"    [未実装] {name}.py が見つかりません。")
            return None

    if len(groups) == 1:
        # 従来通り：左右とも同じ基礎形式 → 1つのモジュールでまとめて描画・保存
        child_name, idxs = next(iter(groups.items()))
        child_mod = _load_child(child_name)
        if child_mod is None:
            return
        child_mod.draw(output_dir, indices_override=idxs, **kwargs)
        return

    # 左右で基礎形式（担当モジュール）が異なる：それぞれ描画し、1つのkoguchi.dxfに統合する
    import ezdxf
    from ezdxf.addons.importer import Importer

    merged = ezdxf.new('R2010')
    merged.header['$INSUNITS'] = 4

    start_draw_i = 0
    for child_name, idxs in groups.items():
        child_mod = _load_child(child_name)
        if child_mod is None:
            return
        doc = child_mod.draw(output_dir, indices_override=idxs, start_draw_i=start_draw_i,
                              save=False, **kwargs)
        if doc is None:
            print(f"    [エラー] {child_name}.draw() が図面を返しませんでした。")
            return
        _explode_dimensions_in_place(doc)
        importer = Importer(doc, merged)
        importer.import_entities(doc.modelspace(), target_layout=merged.modelspace())
        importer.finalize()
        start_draw_i += len(idxs)

    merged.saveas(os.path.join(output_dir, 'koguchi.dxf'))
    print("    生成成功: koguchi.dxf（左右で基礎形式が異なるため"
          f"{len(groups)}つの子ファイルを統合）")


if __name__ == "__main__":
    main(".")
