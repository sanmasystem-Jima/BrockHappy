# BrockHappy

BrockHappy は、構造物の図面・数量の生成を支援する Python ベースの処理群です。  
このリポジトリでは、公開用にコード本体と実行スクリプトのみを管理しています。

## 公開対象
- 00_Brock_Tougou.py
- tools/ 以下の Python スクリプト

## 含めないもの
- 生成物フォルダ
- DXF / JSON / 実行結果の出力ファイル
- ローカル実行時に作成される一時ファイル

## 主要構成
- 00_Brock_Tougou.py: 統合実行用の入口
- tools/01_Brock_Input.py: 入力処理
- tools/02_Brock_Kiso.py 〜 tools/11_Brock_Nouhin.py: 各工程の処理

## 実行方法
1. Python 環境を用意してください。
2. 00_Brock_Tougou.py を実行します。
3. 生成物はローカル環境で出力されます。

## 備考
- 生成物や出力結果は GitHub には含めていません。
- 依存ライブラリや実行環境は利用環境に応じてご用意ください。
