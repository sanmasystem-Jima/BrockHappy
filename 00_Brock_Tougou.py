# 00_Brock_Tougou.py
# ブロック積工 統合実行ツール
# フォルダ構成:
#   BrockHappy/
#   ├── 00_Brock_Tougou.py  ← このファイル
#   ├── tools/              ← 子ツール群
#   └── output_*/           ← 生成物（案件ごと）

import os
import sys
import json
import glob
import re
import shutil
import importlib.util

# =========================================================
# パス設定
# =========================================================
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR  = os.path.join(BASE_DIR, "tools")

# =========================================================
# ユーティリティ
# =========================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_tool(name):
    """tools/フォルダから子ツールをモジュールとして読み込む"""
    path = os.path.join(TOOLS_DIR, name)
    if not os.path.exists(path):
        print(f"[エラー] ツールが見つかりません: {path}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# =========================================================
# 既存outputフォルダのスキャンと選択
# =========================================================

def scan_output_folders():
    # 連番なし（output_...）・連番あり（手動でつけたNN_output_...）の両方を対象にする
    pattern = os.path.join(BASE_DIR, "*output_*")
    folders = [f for f in glob.glob(pattern)
               if re.match(r'^(\d+_)?output_', os.path.basename(f))]
    folders.sort()
    # input.jsonが存在するフォルダのみ有効
    return [f for f in folders if os.path.isfile(os.path.join(f, "input.json"))]

def select_existing_or_new():
    """
    既存フォルダ一覧を表示して選択させる。
    戻り値: (既存フォルダパス or None, 読み込んだinput_dataのdict or {})
    """
    folders = scan_output_folders()

    if not folders:
        print("既存のoutputフォルダが見つかりません。新規作成します。\n")
        return None, {}

    print("\n=== 既存の案件フォルダ ===")
    for idx, f in enumerate(folders, 1):
        print(f"  {idx}: {os.path.basename(f)}")
    print(f"  0: 新規作成")

    while True:
        s = input("\n番号を選択してください：").strip()
        if s == "0":
            return None, {}
        try:
            n = int(s)
            if 1 <= n <= len(folders):
                chosen = folders[n - 1]
                data = load_json(os.path.join(chosen, "input.json"))
                print(f"\n✔ 読み込み: {os.path.basename(chosen)}\n")
                return chosen, data
        except ValueError:
            pass
        print("※ 正しい番号を入力してください")

# =========================================================
# 縮尺入力
# =========================================================

# =========================================================
# 子ツール実行ラッパー
# =========================================================

def run_tool(tool_filename, output_dir, **kwargs):
    """
    tools/フォルダの子ツールを読み込み、main(output_dir, **kwargs) を呼ぶ
    """
    print(f"\n--- {tool_filename} 実行中 ---")
    try:
        mod = load_tool(tool_filename)
        mod.main(output_dir, **kwargs)
        print(f"    完了")
    except Exception as e:
        import traceback
        print(f"\n[エラー] {tool_filename}: {e}")
        traceback.print_exc()
        print("\n続行しますか？  1: はい  2: いいえ")
        if input("(1/2) → ").strip() != "1":
            sys.exit(1)

# =========================================================
# 基礎形式の種類（区間ごとに異なる場合、02を種類の数だけ実行する）
# =========================================================

_KISO_KIND_LABELS = {"nangan1": "岩着_軟岩1", "nangan2": "岩着_軟岩2"}

def _kiso_kind_label(foundation_type, rock_type):
    if foundation_type == "rock":
        return _KISO_KIND_LABELS.get(rock_type, f"岩着_{rock_type}")
    return "直接"

def _distinct_kiso_kinds(input_data):
    """(foundation_type, rock_type) の組をスパン順に列挙し重複を除いたリストを返す。
    先頭は必ず先頭スパン（従来のレガシー scalar と一致）。"""
    fts = input_data.get("foundation_types") or [input_data.get("foundation_type")]
    rts = input_data.get("rock_types") or [input_data.get("rock_type")]
    kinds = []
    seen = set()
    for i, ft in enumerate(fts):
        rt = rts[i] if i < len(rts) else None
        key = (ft, rt if ft == "rock" else None)
        if key not in seen:
            seen.add(key)
            kinds.append(key)
    return kinds

# =========================================================
# メイン処理
# =========================================================

def run_pipeline(output_dir, input_data):
    """
    02〜11を順次実行する（縮尺はinput_dataから取得）。
    00単体実行・99バッチ再描画の両方から共通で呼ばれる。
    """
    scale_kiso   = input_data.get("scale_kiso", 10)
    scale_tenba  = input_data.get("scale_tenba", scale_kiso)
    scale_tenkai = input_data.get("scale_tenkai", 50)
    scale_danmen = input_data.get("scale_danmen", 50)

    # 基礎形式・岩盤区分が区間で複数種類ある場合、02を種類の数だけ実行する。
    # 先頭スパン分は従来通り kiso_data.json / kiso_danmen.dxf（03〜11はこれを読む）。
    # 2種類目以降は kiso_data_<種別>.json / kiso_danmen_<種別>.dxf として追加生成するのみ
    # （03〜11側の区間対応は別作業）。
    kiso_kinds = _distinct_kiso_kinds(input_data)
    run_tool("02_Brock_Kiso.py", output_dir, scale=scale_kiso)
    if len(kiso_kinds) > 1:
        for ft, rt in kiso_kinds[1:]:
            run_tool("02_Brock_Kiso.py", output_dir, scale=scale_kiso,
                      foundation_type=ft, rock_type=rt,
                      suffix=_kiso_kind_label(ft, rt))
        print(f"    ※ 基礎形式・岩盤区分が{len(kiso_kinds)}種類あるため、"
              f"02_Brock_Kiso.pyを{len(kiso_kinds)}回実行しました。")

    run_tool("03_Brock_Tenba.py",   output_dir, scale=scale_tenba)
    run_tool("04_Brock_Tenkai.py",  output_dir, scale=scale_tenkai)
    run_tool("05_Brock_Danmen.py",  output_dir)
    run_tool("06_Brock_Sunpou.py",  output_dir, scale=scale_danmen)
    run_tool("07_Brock_Kokuti.py",  output_dir, scale=scale_danmen)
    run_tool("08_Brock_Suryou.py",  output_dir)
    run_tool("09_Brock_Suryou_Zentai.py", output_dir)
    run_tool("10_Brock_Layout.py", output_dir)
    run_tool("11_Brock_Nouhin.py", output_dir,
             scale_kiso=scale_kiso, scale_tenba=scale_tenba,
             scale_tenkai=scale_tenkai, scale_danmen=scale_danmen)


def main():
    print("\n" + "=" * 50)
    print("  ブロック積工 統合ツール  00_Brock_Tougou")
    print("=" * 50)

    # ① 既存フォルダ選択 or 新規
    prev_folder, prev_data = select_existing_or_new()

    # ② 01_Input実行（既存の場合は修正確認）
    # outputフォルダの確定・作成・リネーム・input.json保存は01側が担当する
    if prev_folder and prev_data:
        print("\n入力内容を修正しますか？  1: はい  2: いいえ")
        s = input("(1/2) [Enter=2] → ").strip()
        if s == "1":
            print("\n--- 01_Brock_Input 実行中 ---")
            try:
                mod01 = load_tool("01_Brock_Input.py")
                input_data, output_dir = mod01.main(prev_data, prev_folder=prev_folder, base_dir=BASE_DIR)
            except Exception as e:
                import traceback
                print(f"\n[エラー] 01_Brock_Input: {e}")
                traceback.print_exc()
                sys.exit(1)
        else:
            input_data = prev_data
            output_dir = prev_folder
            print("    入力内容をそのまま使用します。")
    else:
        print("\n--- 01_Brock_Input 実行中 ---")
        try:
            mod01 = load_tool("01_Brock_Input.py")
            input_data, output_dir = mod01.main(prev_data, prev_folder=prev_folder, base_dir=BASE_DIR)
        except Exception as e:
            import traceback
            print(f"\n[エラー] 01_Brock_Input: {e}")
            traceback.print_exc()
            sys.exit(1)

    # ③④ 縮尺取得＋02〜11を順次実行
    run_pipeline(output_dir, input_data)

    # ⑤ 完了
    print("\n" + "=" * 50)
    print(f"  全工程完了！")
    print(f"  出力先: {output_dir}")
    print("=" * 50)
    input("\nEnterキーで終了...")

if __name__ == "__main__":
    main()
