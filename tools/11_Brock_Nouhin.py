# 11_Brock_Nouhin.py
# 納品フォルダ作成（最終データのみをまとめてコピー）

import os
import re
import json
import shutil
import glob
import importlib.util

def _load_mod01():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "01_Brock_Input.py")
    spec = importlib.util.spec_from_file_location("mod01_for_nouhin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def _scale_str(scale):
    return f"{scale:g}"

# コピー対象（元ファイル名 → 縮尺キー）。縮尺キーがNoneのものはリネームせずそのままコピー。
_FILES = [
    ("danmen_sunpou.dxf", "scale_danmen"),
    ("kiso_danmen.dxf",   "scale_kiso"),
    ("koguchi.dxf",       "scale_danmen"),
    ("tenba_danmen.dxf",  "scale_tenba"),
    ("tenkai.dxf",        "scale_tenkai"),
    ("suryou_brock.txt",  None),
    ("input.json",        None),
]

def main(output_dir, **kwargs):
    input_json_path = os.path.join(output_dir, "input.json")
    if not os.path.isfile(input_json_path):
        print(f"[警告] input.jsonが見つかりません: {input_json_path}")
        return

    with open(input_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    mod01 = _load_mod01()
    base_name = mod01.make_output_folder_name(data)  # "output_..."

    # outputフォルダに手動で付けた番号プレフィックス（例: "01_"）を納品フォルダ名にも付ける
    m = re.match(r'^(\d+_)?output_', os.path.basename(output_dir))
    prefix = (m.group(1) or '') if m else ''

    nouhin_name = prefix + "納品_" + base_name[len("output_"):]

    # 古い納品フォルダが残っていれば作り直す（派生コピーのため削除して問題ない）
    for old in glob.glob(os.path.join(output_dir, "*納品_*")):
        if os.path.isdir(old):
            shutil.rmtree(old)

    nouhin_dir = os.path.join(output_dir, nouhin_name)
    os.makedirs(nouhin_dir, exist_ok=True)

    for filename, scale_key in _FILES:
        src = os.path.join(output_dir, filename)
        if not os.path.isfile(src):
            print(f"[警告] {filename} が見つからないため納品フォルダへのコピーをスキップします")
            continue

        if scale_key is None:
            dst_name = filename
        else:
            scale = kwargs.get(scale_key)
            stem, ext = os.path.splitext(filename)
            dst_name = f"{stem}_S1：{_scale_str(scale)}{ext}" if scale is not None else filename

        shutil.copy2(src, os.path.join(nouhin_dir, dst_name))

    print(f"    納品フォルダ → {nouhin_name}/")
