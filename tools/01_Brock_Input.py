# 01_Brock_Input.py
# 条件入力ツール

import glob
import json
import os
import re
import sys

# ==============================
# 共通入力関数
# ==============================

def _cur(val):
    """現在値をプロンプト末尾に付ける共通フォーマット"""
    return f" [{val}] → " if val is not None else "： "

class _UndoRequested(Exception):
    """数値入力で「M」と入力されたときに発生させる、1つ前の項目に戻るための信号"""
    pass

def _run_steps_with_undo(steps):
    """steps（引数なしcallableのリスト）を順に実行する。
    実行中に _UndoRequested が発生したら1つ前のstepからやり直す
    （先頭のstepで発生した場合はこれ以上戻れないことを表示する）。
    """
    i = 0
    while i < len(steps):
        try:
            steps[i]()
            i += 1
        except _UndoRequested:
            if i > 0:
                i -= 1
                print("  ※ 1つ前の項目に戻ります。")
            else:
                print("  ※ これより前には戻れません。完了後の確認画面をご利用ください。")

def input_str(prompt, current=None):
    s = input(f"{prompt}{_cur(current)}").strip()
    if s.lower() == "m":
        raise _UndoRequested()
    return current if s == "" else s

def input_float(prompt, current=None, min_val=None, max_val=None, exclusive_min=False):
    """min_val/max_val を指定すると範囲外の値で警告して再入力させる。
    exclusive_min=True の場合 min_val は「より大きい」（境界値そのものは不可）。
    「M」と入力すると _UndoRequested を発生させ、1つ前の項目に戻れるようにする。
    """
    s = input(f"{prompt}{_cur(current)}").strip()
    if s.lower() == "m":
        raise _UndoRequested()
    if s == "":
        return current
    try:
        val = float(s)
    except ValueError:
        print("※ 数値を入力してください")
        return input_float(prompt, current, min_val, max_val, exclusive_min)
    if min_val is not None:
        if exclusive_min and val <= min_val:
            print(f"※ {min_val:g}より大きい値を入力してください（入力値: {val:g}）")
            return input_float(prompt, current, min_val, max_val, exclusive_min)
        if not exclusive_min and val < min_val:
            print(f"※ {min_val:g}以上の値を入力してください（入力値: {val:g}）")
            return input_float(prompt, current, min_val, max_val, exclusive_min)
    if max_val is not None and val > max_val:
        print(f"※ {max_val:g}以下の値を入力してください（入力値: {val:g}）")
        return input_float(prompt, current, min_val, max_val, exclusive_min)
    return val

def input_int(prompt, current=None, min_val=None, max_val=None):
    s = input(f"{prompt}{_cur(current)}").strip()
    if s.lower() == "m":
        raise _UndoRequested()
    if s == "":
        return current
    try:
        val = int(s)
    except ValueError:
        print("※ 整数を入力してください")
        return input_int(prompt, current, min_val, max_val)
    if min_val is not None and val < min_val:
        print(f"※ {min_val}以上の値を入力してください（入力値: {val}）")
        return input_int(prompt, current, min_val, max_val)
    if max_val is not None and val > max_val:
        print(f"※ {max_val}以下の値を入力してください（入力値: {val}）")
        return input_int(prompt, current, min_val, max_val)
    return val

def input_choice(prompt, choices, current=None):
    print(prompt)
    for key, (code, label) in choices.items():
        print(f"  {key}: {label}")
    if current is not None:
        cur_label = next(
            (f"{k}:{lbl}" for k, (cd, lbl) in choices.items() if cd == current),
            current
        )
        s = input(f"番号{_cur(cur_label)}").strip()
    else:
        s = input("番号： ").strip()
    if s == "":
        return current
    if s in choices:
        return choices[s][0]
    print("※ 正しい番号を入力してください")
    return input_choice(prompt, choices, current)

def input_yesno(prompt, current=None, required=False):
    """1:はい / 2:いいえ  内部値は "y"/"n" のまま保持
    required=True の場合、Enterのみでの前回値保持を許さず、明示的に1か2を入力させる
    （影響の大きい質問で「うっかりEnter」を防ぐため）。
    """
    cur_disp = {"y": "1(はい)", "n": "2(いいえ)"}.get(current) if current else None
    print(prompt)
    print("  1: はい  2: いいえ")
    if required:
        s = input(f"(1/2){_cur(cur_disp)}　※必ず1か2を入力してください：").strip()
    else:
        s = input(f"(1/2){_cur(cur_disp)}").strip()
    if s == "":
        if required:
            print("※ この質問はEnterで前回値を引き継げません。1か2を入力してください。")
            return input_yesno(prompt, current, required)
        return current
    if s == "1":
        return "y"
    if s == "2":
        return "n"
    print("※ 1 または 2 を入力してください")
    return input_yesno(prompt, current, required)

# ==============================
# 構造物名・基礎名の導出
# ==============================

def derive_names(data):
    stype = data.get("structure_type", "")
    bline = data.get("base_line_type", "")
    if stype in ("river", "river_gohan"):
        structure_name = "護岸"
    elif stype in ("road", "road_dai"):
        structure_name = "法留" if bline == "front_toe" else "道台"
    elif stype == "road_tome":
        structure_name = "法留"
    else:
        structure_name = stype or "不明"
    foundation_name = {"direct": "直接", "rock": "岩着"}.get(data.get("foundation_type", ""), "")
    return structure_name, foundation_name

# ==============================
# JSON 読み書き
# ==============================

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==============================
# outputフォルダ名の自動生成
# ==============================

def make_output_folder_name(data):
    """
    input.jsonの内容からoutputフォルダ名を生成（連番は手動で付与する運用のため付けない）
    例: output_護岸_直接_1-0.4_BC10_L14.1m
    """
    stype_raw = data.get("structure_type", "")
    base_line = data.get("base_line_type", "")
    if data.get("structure_name"):
        stype = data["structure_name"]
    elif stype_raw in ("river", "river_gohan"):
        stype = "護岸"
    elif stype_raw in ("road", "road_dai"):
        stype = "法留" if base_line == "front_toe" else "道台"
    elif stype_raw == "road_tome":
        stype = "法留"
    else:
        stype = stype_raw or "不明"

    ftype = data.get("foundation_name") or \
            {"direct": "直接", "rock": "岩着"}.get(data.get("foundation_type", ""), "")

    tc_str    = "天端あり" if data.get("has_tenba_con") == "y" else "天端なし"
    slope_str = f"1-{data.get('front_slope', 0.0):g}"
    bc_cm     = int(round(data.get("ura_con_thickness", 0.0) * 100))
    bc_str    = f"BC{bc_cm}"

    upper   = data.get("upper_extension", [])
    lower   = data.get("lower_extension", [])
    total_l = max(sum(upper) if upper else 0.0,
                  sum(lower) if lower else 0.0)
    l_str = f"L{total_l:g}m"

    gr_str = "GR基礎" if data.get("has_gr_kiso") == "y" else ""
    parts = [p for p in [stype, ftype, tc_str, gr_str, slope_str, bc_str, l_str] if p]
    return "output_" + "_".join(parts)

# ==============================
# outputフォルダの確定・作成・input.json保存
# ==============================

def resolve_output_dir(data, prev_folder=None, base_dir=None):
    """
    data（入力結果）からoutputフォルダ名を確定し、必要ならリネーム・新規作成を行い、
    input.jsonをそのフォルダへ保存する。output_dirのパスを返す。
    """
    base_dir = base_dir or os.getcwd()
    folder_name = make_output_folder_name(data)

    if prev_folder:
        # 既存フォルダを編集した場合：番号プレフィックスは維持したまま実際にリネームする
        old_basename = os.path.basename(prev_folder)
        m = re.match(r'^(\d+_)?output_', old_basename)
        prefix = m.group(1) or '' if m else ''
        new_basename = prefix + folder_name
        new_path = os.path.join(base_dir, new_basename)
        if os.path.abspath(new_path) != os.path.abspath(prev_folder):
            if os.path.exists(new_path):
                print(f"※ 入力内容は変更されましたが、リネーム先 {new_basename} が既に存在するため、")
                print(f"   フォルダ名は変更せず {old_basename} のまま使用します。")
            else:
                print(f"※ 入力内容の変更によりフォルダ名を変更します。")
                print(f"   旧: {old_basename}")
                print(f"   新: {new_basename}")
                os.rename(prev_folder, new_path)
                prev_folder = new_path
        output_dir = prev_folder
    else:
        output_dir = os.path.join(base_dir, folder_name)

    print(f"\n出力フォルダ: {os.path.basename(output_dir)}")

    os.makedirs(output_dir, exist_ok=True)

    input_json_path = os.path.join(output_dir, "input.json")
    save_json(input_json_path, data)
    print(f"    input.json → {os.path.basename(output_dir)}/")

    return output_dir

# ==============================
# 各セクション（通常フロー・確認画面の修正の両方から呼ばれる）
# ==============================

def _ask_structure_type(data):
    data["structure_type"] = input_choice(
        "=== 構造物の種類 ===",
        {"1": ("river", "河川構造物"), "2": ("road", "道路構造物")},
        data.get("structure_type")
    )

def _ask_soil_type(data):
    data["soil_type"] = input_choice(
        "=== 地盤条件 ===",
        {"1": ("cut", "切土"), "2": ("fill", "盛土")},
        data.get("soil_type")
    )

def _ask_base_line_type(data):
    data["base_line_type"] = input_choice(
        "=== 基準線の種類 ===",
        {
            "1": ("tenba_kado", "天端角基準"),
            "2": ("front_toe",  "埋戻し天基準"),
        },
        data.get("base_line_type")
    )

def _ask_num_points(data):
    def _step():
        data["num_points"] = input_int("変化点数", data.get("num_points"), min_val=2, max_val=50)
    _run_steps_with_undo([_step])
    return data["num_points"]

def _ask_point_name_for_point(data, i):
    data["point_names"][i] = input_str(f"測点{i+1}", data["point_names"][i])

def _ask_point_names(data, n):
    if "point_names" not in data or len(data["point_names"]) != n:
        data["point_names"] = [None] * n
    print("\n=== 測点名 ===")
    _run_steps_with_undo([(lambda i=i: _ask_point_name_for_point(data, i)) for i in range(n)])

def _ask_elevation_for_point(data, i):
    data["elevations"][i] = input_float(f"測点{i+1} 標高", data["elevations"][i])

def _ask_elevations(data, n):
    if "elevations" not in data or len(data["elevations"]) != n:
        data["elevations"] = [None] * n
    print("\n=== 標高（m） ===")
    _run_steps_with_undo([(lambda i=i: _ask_elevation_for_point(data, i)) for i in range(n)])

def _ask_front_slope(data):
    data["front_slope"] = input_float("前面勾配（1:n の n 部分）", data.get("front_slope", 0.4),
                                        min_val=0, max_val=2.0, exclusive_min=True)

def _ask_block_hikae(data):
    data["block_hikae"] = input_float("ブロック控え a（m）", data.get("block_hikae", 0.35),
                                        min_val=0, max_val=5.0, exclusive_min=True)

def _ask_ura_con_thickness(data):
    data["ura_con_thickness"] = input_float("裏込コンクリート厚 b（m）", data.get("ura_con_thickness", 0.15),
                                              min_val=0, max_val=2.0)

def _ask_front_back_conditions(data):
    _run_steps_with_undo([
        lambda: _ask_front_slope(data),
        lambda: _ask_block_hikae(data),
        lambda: _ask_ura_con_thickness(data),
    ])

def _is_dotai(data):
    return data.get("structure_type") == "road" and data.get("base_line_type") == "tenba_kado"

def _is_gogan(data):
    return data.get("structure_type") in ("river", "river_gohan")

def _ask_gr_trio(data, tenba_h):
    while True:
        _run_steps_with_undo([
            lambda: data.update(gr_height_m=input_float(
                "GR基礎の高さ（m）", data.get("gr_height_m"), min_val=0, max_val=5.0, exclusive_min=True)),
            lambda: data.update(gr_mortar_m=input_float(
                "モルタルの厚さ（m）", data.get("gr_mortar_m"), min_val=0, max_val=5.0, exclusive_min=True)),
            lambda: data.update(gr_kiso_con_m=input_float(
                "基礎コンの厚さ（m）", data.get("gr_kiso_con_m"), min_val=0, max_val=5.0, exclusive_min=True)),
        ])
        total = (data["gr_height_m"] or 0) + (data["gr_mortar_m"] or 0) + (data["gr_kiso_con_m"] or 0)
        if abs(total - tenba_h) < 0.001:
            break
        print(f"  ※ GR基礎({data['gr_height_m']:g}) + モルタル({data['gr_mortar_m']:g})"
              f" + 基礎コン({data['gr_kiso_con_m']:g}) = {total:g}m"
              f" ≠ 天端コン厚({tenba_h:g}m)。再入力してください。")

def _ask_tenba_con_and_gr(data):
    # 天端コンクリート
    data["has_tenba_con"] = input_yesno("=== 天端コンクリートの有無 ===", data.get("has_tenba_con"))
    if data["has_tenba_con"] == "y":
        def _step():
            data["tenba_con_height"] = input_float("天端コンクリート厚（m）", data.get("tenba_con_height", 0.1),
                                                     min_val=0, max_val=2.0, exclusive_min=True)
        _run_steps_with_undo([_step])
    else:
        data["tenba_con_height"] = 0.0

    # GR基礎（道台または護岸かつ天端コン > 0.1m のとき）
    if (_is_dotai(data) or _is_gogan(data)) and data["has_tenba_con"] == "y" and (data.get("tenba_con_height") or 0) > 0.1:
        data["has_gr_kiso"] = input_yesno("=== ガードレール基礎の有無 ===", data.get("has_gr_kiso"), required=True)
        if data["has_gr_kiso"] == "y":
            def _step_width():
                data["gr_base_width_m"] = input_float("GR基礎の底版幅（m）", data.get("gr_base_width_m"),
                                                        min_val=0, max_val=5.0, exclusive_min=True)
            _run_steps_with_undo([_step_width])
            _ask_gr_trio(data, data["tenba_con_height"])
        else:
            data["gr_height_m"]     = None
            data["gr_base_width_m"] = None
            data["gr_mortar_m"]     = None
            data["gr_kiso_con_m"]   = None
    else:
        data["has_gr_kiso"]     = "n"
        data["gr_height_m"]     = None
        data["gr_base_width_m"] = None
        data["gr_mortar_m"]     = None
        data["gr_kiso_con_m"]   = None

def _ask_foundation_and_rock(data):
    data["foundation_type"] = input_choice(
        "=== 基礎形式 ===",
        {"1": ("rock", "岩着基礎"), "2": ("direct", "直接基礎")},
        data.get("foundation_type")
    )
    if data["foundation_type"] == "rock":
        data["rock_type"] = input_choice(
            "=== 岩盤区分 ===",
            {"1": ("nangan1", "軟岩Ⅰ"), "2": ("nangan2", "軟岩Ⅱ以上")},
            data.get("rock_type")
        )
    else:
        data["rock_type"] = None

def _is_hatome(data):
    return data.get("structure_type") == "road" and data.get("base_line_type") == "front_toe"

def _ask_canal_for_point(data, i):
    data["has_canal"][i] = input_yesno(f"測点{i+1} 水路の有無", data["has_canal"][i])
    if data["has_canal"][i] == "y":
        data["canal_depth"][i] = input_float(
            f"測点{i+1} 水路の深さ（道路天から水路底, m）", data["canal_depth"][i],
            min_val=0, max_val=2.0)
    else:
        data["canal_depth"][i] = 0.0
    data["embed_depths"][i] = round(data["canal_depth"][i] + 0.3, 3)

def _ask_embed_depth_for_point(data, i):
    data["embed_depths"][i] = input_float(f"測点{i+1} 根入れ", data["embed_depths"][i],
                                            min_val=0, max_val=2.3, exclusive_min=True)

def _ask_embed_depths(data, n):
    if _is_hatome(data):
        # 法留（岩着・直接共通）：根入れ＝水路の深さ＋30cm（水路なしは道路天から30cm）
        if "has_canal" not in data or len(data["has_canal"]) != n:
            data["has_canal"] = [None] * n
        if "canal_depth" not in data or len(data["canal_depth"]) != n:
            data["canal_depth"] = [None] * n
        if "embed_depths" not in data or len(data["embed_depths"]) != n:
            data["embed_depths"] = [None] * n
        print("\n=== 水路（測点ごと） ===")
        _run_steps_with_undo([(lambda i=i: _ask_canal_for_point(data, i)) for i in range(n)])
        print("  根入れ: 水路底（水路なしは道路天）から30cmで自動算出")
    elif data["foundation_type"] == "rock":
        # 岩着は岩盤区分より自動設定
        t_auto = 0.50 if data["rock_type"] == "nangan1" else 0.30
        data["embed_depths"] = [t_auto] * n
        print(f"\n  根入れ: {t_auto*100:.0f}cm（岩盤区分より自動）")
    else:
        if "embed_depths" not in data or len(data["embed_depths"]) != n:
            data["embed_depths"] = [None] * n
        print("\n=== 根入れ（m・測点ごと） ===")
        _run_steps_with_undo([(lambda i=i: _ask_embed_depth_for_point(data, i)) for i in range(n)])

def _ask_water_level_for_point(data, i):
    data["water_level_els"][i] = input_float(f"測点{i+1} 水面EL", data["water_level_els"][i])

def _ask_water_level(data, n):
    if data.get("structure_type") in ("river", "river_gohan"):
        if "water_level_els" not in data or len(data["water_level_els"]) != n:
            data["water_level_els"] = [None] * n
        print("\n=== 水面EL（m・測点ごと） ===")
        _run_steps_with_undo([(lambda i=i: _ask_water_level_for_point(data, i)) for i in range(n)])
    else:
        data["water_level_els"] = [None] * n

def _ask_block_height_for_point(data, i):
    data["block_heights"][i] = input_float(f"測点{i+1} ブロック直高（m）", data["block_heights"][i],
                                             min_val=0, max_val=5.0, exclusive_min=True)

def _ask_block_heights(data, n):
    if "block_heights" not in data or len(data["block_heights"]) != n:
        data["block_heights"] = [None] * n
    print("\n=== ブロック直高（m・天端コンクリート含む） ===")
    _run_steps_with_undo([(lambda i=i: _ask_block_height_for_point(data, i)) for i in range(n)])

def _edit_front_back_and_backfill_slope(data):
    """確認画面用：前面勾配はブロック前面・裏込め砕石背面で連動することが多いため、
    前面勾配側を直したら続けて裏込め背面勾配も聞き直す（新しい前面勾配からの提案値を出す）。"""
    _ask_front_back_conditions(data)
    data["backfill_slope"] = None
    _ask_backfill_slope(data)

def _ask_backfill_slope(data):
    is_tomeru = _is_hatome(data)
    front_slope_val = data.get("front_slope") or 0.0
    existing_bs = data.get("backfill_slope")
    if existing_bs is None and not is_tomeru:
        auto_bs = round(front_slope_val - 0.1, 4)
        print(f"  ※ 裏込め背面勾配 標準値: 1:{auto_bs:g}"
              f"（前面勾配 1:{front_slope_val:g} − 0.1）")
        current_bs = auto_bs
    else:
        current_bs = existing_bs
    while True:
        def _step():
            data["backfill_slope"] = input_float("裏込め背面勾配（1:n の n 部分）", current_bs,
                                                  min_val=0, exclusive_min=True)
        _run_steps_with_undo([_step])
        bs = data["backfill_slope"]
        if bs is not None and bs > front_slope_val:
            print(f"  ※ 裏込め背面勾配はブロック前面勾配（1:{front_slope_val:g}）と平行かそれ以下"
                  f"（急）にしてください（入力値: 1:{bs:g}）。再入力してください。")
            current_bs = bs
            continue
        break

def _ask_backfill_top_offset(data):
    if data["has_tenba_con"] == "n":
        def _step():
            data["backfill_top_offset"] = input_float(
                "裏込天端オフセット（m）", data.get("backfill_top_offset"),
                min_val=0, max_val=1.0
            )
        _run_steps_with_undo([_step])
    else:
        data["backfill_top_offset"] = None

def _ask_backfill_raw_for_point(data, i):
    mode = data["backfill_mode"]
    while True:
        val = input_float(f"測点{i+1}", data["backfill_raw"][i])
        if mode == "top_down":
            computed = data["block_heights"][i] - val if val is not None else None
        else:  # btm_up
            computed = val
        if computed is not None and computed > data["block_heights"][i]:
            print(f"  ※ 裏込め砕石底面（{computed:g}m）はブロック直高"
                  f"（{data['block_heights'][i]:g}m）以下にしてください。再入力してください。")
            continue
        data["backfill_raw"][i] = val
        data["backfill_bottoms"][i] = computed
        break

def _ask_backfill_bottoms(data, n):
    if data["foundation_type"] == "direct" and data["structure_type"] != "road":
        # 河川直接基礎: 均しコン下（計算段階で決定）
        print("\n  裏込砕石底面高さ: 均しコンクリート下（自動）")
        data["backfill_bottoms"] = [None] * n
        data["backfill_mode"]    = "auto"
    elif data["foundation_type"] == "direct" and data["structure_type"] == "road":
        # 道路構造物（道台・法留）の直接基礎: 埋戻し天と砕石下端は必ず一致するため質問不要
        print("\n  裏込め砕石底面高さ: 前面埋め戻しと同じ高さ（自動）")
        data["backfill_bottoms"] = list(data["embed_depths"])
        data["backfill_mode"]    = "embed_same"
    else:
        data["backfill_mode"] = input_choice(
            "=== 裏込め砕石底面の高さ ===",
            {
                "1": ("top_down",   "天端からの下がり"),
                "2": ("embed_same", "前面埋め戻しと同じ高さ"),
                "3": ("btm_up",     "ブロック前面下端からの上がり"),
            },
            data.get("backfill_mode")
        )
        mode = data["backfill_mode"]

        if mode == "embed_same":
            data["backfill_bottoms"] = list(data["embed_depths"])
            data["backfill_raw"]     = [None] * n
        else:
            if "backfill_raw" not in data or len(data["backfill_raw"]) != n:
                data["backfill_raw"] = [None] * n
            if "backfill_bottoms" not in data or len(data["backfill_bottoms"]) != n:
                data["backfill_bottoms"] = [None] * n
            label = "天端からの下がり（m）" if mode == "top_down" \
                    else "ブロック前面下端からの上がり（m）"
            print(f"\n=== 裏込め砕石底面  {label} ===")
            _run_steps_with_undo([(lambda i=i: _ask_backfill_raw_for_point(data, i)) for i in range(n)])

def _ask_koguchi_type(data):
    data["koguchi_type"] = input_choice(
        "=== 小口止コンクリート ===",
        {
            "1": ("both",  "両側あり"),
            "2": ("left",  "左のみ"),
            "3": ("right", "右のみ"),
            "4": ("none",  "両側なし"),
        },
        data.get("koguchi_type")
    )

def _ask_extension_upper(data, i):
    data["upper_extension"][i] = input_float("  上延長（m）", data["upper_extension"][i],
                                               min_val=0, max_val=20.0, exclusive_min=True)

def _ask_extension_lower(data, i):
    data["lower_extension"][i] = input_float("  下延長（m）", data["lower_extension"][i],
                                               min_val=0, max_val=20.0, exclusive_min=True)

def _ask_extension_for_span(data, i):
    print(f"\n第{i+1}スパンの延長（{data['point_names'][i]}～{data['point_names'][i+1]}）")
    _run_steps_with_undo([
        lambda: _ask_extension_upper(data, i),
        lambda: _ask_extension_lower(data, i),
    ])

def _ask_extensions(data, span):
    if "upper_extension" not in data or len(data["upper_extension"]) != span:
        data["upper_extension"] = [None] * span
    if "lower_extension" not in data or len(data["lower_extension"]) != span:
        data["lower_extension"] = [None] * span
    print("\n=== 上下延長（スパンごと） ===")
    for i in range(span):
        _ask_extension_for_span(data, i)

def _ask_back_excavation_slope(data):
    def _step():
        data["back_excavation_slope"] = input_float(
            "背面の掘削勾配（1:n の n 部分）", data.get("back_excavation_slope", 0.5),
            min_val=0, max_val=2.0, exclusive_min=True
        )
    _run_steps_with_undo([_step])

def _ask_scales(data):
    print("\n=== 図面縮尺（1/n の n） ===")
    _run_steps_with_undo([
        lambda: data.update(scale_kiso=input_float(
            "基礎断面の縮尺", data.get("scale_kiso", 10), min_val=1, max_val=1000)),
        lambda: data.update(scale_tenba=input_float(
            "天端断面の縮尺", data.get("scale_tenba", data.get("scale_kiso", 10)), min_val=1, max_val=1000)),
        lambda: data.update(scale_tenkai=input_float(
            "展開図の縮尺", data.get("scale_tenkai", 50), min_val=1, max_val=1000)),
        lambda: data.update(scale_danmen=input_float(
            "断面図の縮尺", data.get("scale_danmen", 50), min_val=1, max_val=1000)),
    ])

# ==============================
# 入力完了後の確認・修正画面
# ==============================

def _fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)

def _fmt_slope(v):
    return "-" if v is None else f"1:{v:g}"

def _fmt_list(lst):
    if not lst:
        return "-"
    return ", ".join(_fmt(v) for v in lst)

def _pick_index(label, count):
    while True:
        s = input(f"{label}番号(1-{count})を選択：").strip()
        try:
            idx = int(s)
            if 1 <= idx <= count:
                return idx - 1
        except ValueError:
            pass
        print("※ 正しい番号を入力してください")

_STRUCTURE_LABELS  = {"river": "河川構造物", "road": "道路構造物"}
_SOIL_LABELS       = {"cut": "切土", "fill": "盛土"}
_BASELINE_LABELS   = {"tenba_kado": "天端角基準", "front_toe": "埋戻し天基準"}
_FOUNDATION_LABELS = {"rock": "岩着基礎", "direct": "直接基礎"}
_ROCK_LABELS       = {"nangan1": "軟岩Ⅰ", "nangan2": "軟岩Ⅱ以上"}
_KOGUCHI_LABELS    = {"both": "両側あり", "left": "左のみ", "right": "右のみ", "none": "両側なし"}

def _review_and_edit(data, n, span):
    while True:
        is_hatome = _is_hatome(data)
        is_rock   = data.get("foundation_type") == "rock"
        mode      = data.get("backfill_mode")

        if is_hatome:
            embed_editor = (lambda: _ask_canal_for_point(data, _pick_index("測点", n)))
        elif is_rock:
            embed_editor = (lambda: print("  ※ 岩着基礎の根入れは岩盤区分から自動算出されます。"
                                           "「基礎形式・岩盤区分」の項目で変更してください。"))
        else:
            embed_editor = (lambda: _ask_embed_depth_for_point(data, _pick_index("測点", n)))

        if mode in ("top_down", "btm_up"):
            bottoms_editor = (lambda: _ask_backfill_raw_for_point(data, _pick_index("測点", n)))
        else:
            bottoms_editor = (lambda: print("  ※ この基礎形式・条件では裏込め砕石底面は自動算出されます。"))

        if span > 0:
            ext_editor = (lambda: _ask_extension_for_span(data, _pick_index("スパン", span)))
        else:
            ext_editor = (lambda: print("  ※ スパンがありません。"))

        tenba_str = f"あり({_fmt(data.get('tenba_con_height'))}m)" if data.get("has_tenba_con") == "y" else "なし"
        gr_str    = "あり" if data.get("has_gr_kiso") == "y" else "なし"

        items = [
            ("構造物の種類",          _STRUCTURE_LABELS.get(data.get("structure_type"), "-"),
             lambda: _ask_structure_type(data)),
            ("地盤条件",              _SOIL_LABELS.get(data.get("soil_type"), "-"),
             lambda: _ask_soil_type(data)),
            ("基準線の種類",          _BASELINE_LABELS.get(data.get("base_line_type"), "-"),
             lambda: _ask_base_line_type(data)),
            ("測点名",                _fmt_list(data.get("point_names")),
             lambda: _ask_point_name_for_point(data, _pick_index("測点", n))),
            ("標高",                  _fmt_list(data.get("elevations")),
             lambda: _ask_elevation_for_point(data, _pick_index("測点", n))),
            ("前面勾配/ブロック控え/裏込コン厚",
             f"{_fmt_slope(data.get('front_slope'))} / {_fmt(data.get('block_hikae'))} / {_fmt(data.get('ura_con_thickness'))}",
             lambda: _edit_front_back_and_backfill_slope(data)),
            ("天端コンクリート・GR基礎", f"{tenba_str} / GR{gr_str}",
             lambda: _ask_tenba_con_and_gr(data)),
            ("基礎形式・岩盤区分",
             f"{_FOUNDATION_LABELS.get(data.get('foundation_type'), '-')} / "
             f"{_ROCK_LABELS.get(data.get('rock_type'), '-')}",
             lambda: _ask_foundation_and_rock(data)),
            ("根入れ",                _fmt_list(data.get("embed_depths")), embed_editor),
            ("水面EL",                _fmt_list(data.get("water_level_els")),
             lambda: _ask_water_level_for_point(data, _pick_index("測点", n))),
            ("ブロック直高",          _fmt_list(data.get("block_heights")),
             lambda: _ask_block_height_for_point(data, _pick_index("測点", n))),
            ("裏込め背面勾配",        _fmt_slope(data.get("backfill_slope")),
             lambda: _ask_backfill_slope(data)),
            ("裏込天端オフセット",    _fmt(data.get("backfill_top_offset")),
             lambda: _ask_backfill_top_offset(data)),
            ("裏込め砕石底面",        _fmt_list(data.get("backfill_bottoms")), bottoms_editor),
            ("小口止コンクリート",    _KOGUCHI_LABELS.get(data.get("koguchi_type"), "-"),
             lambda: _ask_koguchi_type(data)),
            ("上下延長",
             " / ".join(f"第{i+1}({_fmt(u)}/{_fmt(l)})" for i, (u, l) in
                        enumerate(zip(data.get("upper_extension", []), data.get("lower_extension", [])))) or "-",
             ext_editor),
            ("背面の掘削勾配",        _fmt_slope(data.get("back_excavation_slope")),
             lambda: _ask_back_excavation_slope(data)),
            ("図面縮尺",
             f"基礎1/{_fmt(data.get('scale_kiso'))} 天端1/{_fmt(data.get('scale_tenba'))} "
             f"展開1/{_fmt(data.get('scale_tenkai'))} 断面1/{_fmt(data.get('scale_danmen'))}",
             lambda: _ask_scales(data)),
        ]

        print("\n==== 入力内容の確認 ====")
        for idx, (label, value, _editor) in enumerate(items, 1):
            print(f" {idx:2d}. {label}: {value}")

        print("\n1: このまま進む　2: 修正する")
        s = input("(1/2) [Enter=1] → ").strip()
        if s != "2":
            return data

        sel = input(f"修正する項目番号(1-{len(items)})を選択：").strip()
        try:
            sel_idx = int(sel)
            if 1 <= sel_idx <= len(items):
                items[sel_idx - 1][2]()
            else:
                print("※ 正しい番号を入力してください")
        except ValueError:
            print("※ 正しい番号を入力してください")

# ==============================
# メイン処理
# ==============================

def main(prev_data=None, prev_folder=None, base_dir=None):
    data = prev_data.copy() if prev_data else {}

    print("\n==============================")
    print("  ブロック積工 条件入力")
    print("==============================")
    print("  数値入力では M と入力すると1つ前の項目に戻れます\n")

    _ask_structure_type(data)
    _ask_soil_type(data)
    _ask_base_line_type(data)

    n    = _ask_num_points(data)
    span = max(n - 1, 0)

    _ask_point_names(data, n)
    _ask_elevations(data, n)
    _ask_front_back_conditions(data)
    _ask_tenba_con_and_gr(data)
    _ask_foundation_and_rock(data)
    _ask_embed_depths(data, n)
    _ask_water_level(data, n)
    _ask_block_heights(data, n)
    _ask_backfill_slope(data)
    _ask_backfill_top_offset(data)
    _ask_backfill_bottoms(data, n)
    _ask_koguchi_type(data)
    _ask_extensions(data, span)
    _ask_back_excavation_slope(data)
    _ask_scales(data)

    # 派生フィールド（後工程・フォルダ名参照用）
    structure_name, foundation_name = derive_names(data)
    data["structure_name"]  = structure_name   # "護岸" / "道台" / "法留"
    data["foundation_name"] = foundation_name  # "直接" / "岩着"

    print(f"\n  構造物種別: {structure_name}  基礎形式: {foundation_name}")
    print("\n入力完了\n")

    data = _review_and_edit(data, n, span)

    output_dir = resolve_output_dir(data, prev_folder=prev_folder, base_dir=base_dir)
    return data, output_dir

# ==============================
# 単体起動（BROCKinputtool.exe）用：既存フォルダ選択・修正
# ==============================

def _default_base_dir():
    """exe実行時はexeの場所、スクリプト実行時はtools/の一つ上（BrockHappy/）を返す"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def scan_output_folders(base_dir):
    pattern = os.path.join(base_dir, "*output_*")
    folders = [f for f in glob.glob(pattern)
               if re.match(r'^(\d+_)?output_', os.path.basename(f))]
    folders.sort()
    return [f for f in folders if os.path.isfile(os.path.join(f, "input.json"))]

def select_existing_or_new(base_dir):
    """既存フォルダ一覧を表示して選択させる。戻り値: (既存フォルダパス or None, input_dataのdict)"""
    folders = scan_output_folders(base_dir)

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

if __name__ == "__main__":
    base_dir = _default_base_dir()
    prev_folder, prev_data = select_existing_or_new(base_dir)

    if prev_folder and prev_data:
        print("\n入力内容を修正しますか？  1: はい  2: いいえ")
        s = input("(1/2) [Enter=2] → ").strip()
        if s == "1":
            main(prev_data, prev_folder=prev_folder, base_dir=base_dir)
        else:
            print("    入力内容をそのまま使用します（変更なし）。")
    else:
        main(prev_data, prev_folder=prev_folder, base_dir=base_dir)
