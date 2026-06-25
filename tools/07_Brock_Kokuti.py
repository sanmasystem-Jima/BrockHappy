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

def main(output_dir, **kwargs):
    path = os.path.join(output_dir, 'input.json')
    if not os.path.exists(path):
        print("    [エラー] input.json が見つかりません。")
        return

    with open(path, 'r', encoding='utf-8') as f:
        input_data = json.load(f)

    structure_name  = input_data.get('structure_name', '')
    foundation_type = input_data.get('foundation_type', '')

    # 古いinput.jsonにはstructure_nameがないため、structure_typeから導出
    if not structure_name:
        stype = input_data.get('structure_type', '')
        bline = input_data.get('base_line_type', '')
        if stype in ('river', 'river_gohan'):
            structure_name = '護岸'
        elif stype in ('road', 'road_dai'):
            structure_name = '法留' if bline == 'front_toe' else '道台'
        elif stype == 'road_tome':
            structure_name = '法留'

    child_name = _DISPATCH.get((structure_name, foundation_type))
    if child_name is None:
        print(f"    [エラー] 未対応の組み合わせ: {structure_name} / {foundation_type}")
        return

    tools_dir = os.path.dirname(os.path.abspath(__file__))
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)

    try:
        child_mod = importlib.import_module(child_name)
    except ImportError:
        print(f"    [未実装] {child_name}.py が見つかりません。")
        return

    child_mod.draw(output_dir, **kwargs)

if __name__ == "__main__":
    main(".")
