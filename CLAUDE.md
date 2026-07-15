# CLAUDE.md

このファイルは、このリポジトリで作業するAIエージェント(Claude Code)への指示です。

## プロジェクト概要

Shopify管理画面(複数ブランド: PHOTOPRI, e1, Qoo, artgraph)をSeleniumで自動操作し、
注文の検索・注文明細印刷を自動化するWindows向けツール。tkinter GUIから起動し、
最終的にPyInstallerでexe化して配布する(印刷担当スタッフが直接操作する)。

## 主要ファイル

- `指示書印刷_v8.0.py` - メインスクリプト(tkinter GUI + Selenium自動操作)
- `openChrome.bat` / `openChrome.sh` - Chrome起動用スクリプトの**テンプレート**。
  `launch_chrome()`関数はこれ自体を実行するのではなく、`DontTouch`フォルダの中に
  コピーされたものを実行する(下記「Chrome起動の仕組み」参照)。
- `ChromeCheck.bat` - 旧バージョンの名残。現在未使用。
- `requirements.txt` - Python依存パッケージ
- `bitmex.json` - **リポジトリには含まれない機密ファイル**(`.gitignore`で除外済み)。
  Googleスプレッドシート用のGoogleサービスアカウント秘密鍵。実行前にスクリプトと
  同じフォルダに配置すること(ユーザーから別途受け取る)。

## セットアップ

1. Python 3.11+ をインストール
2. `pip install -r requirements.txt`
3. `bitmex.json` をプロジェクトルートに配置(ユーザーから別途受領。なければ本人に確認する)
4. Google Chromeがインストールされていること
5. `DontTouch`フォルダをスクリプトと同じ階層に作成し(なければ手動で作成)、
   リポジトリ直下の`openChrome.bat`(Windows)または`openChrome.sh`(Mac)を
   その中にコピーする。Mac側は実行権限の付与が必要(`chmod +x DontTouch/openChrome.sh`)。
   `DontTouch`フォルダ自体はChromeのプロファイル(Cookie等)を保管する場所であり、
   `.gitignore`で除外されているため、PCごとに手動でこの配置作業が必要。

## 実行方法

`python 指示書印刷_v8.0.py` でtkinter GUIが起動する。「日時範囲で回収」または
「注文番号で回収」を選び、ブランドを選択して「実行」を押すと、Chromeがリモートデバッグ
モード(ポート9222)で自動起動し、Shopify管理画面を操作する。

## 重要な技術的注意点

### Shopify管理画面はShadow DOM/Web Componentsベースの新UI

Shopify管理画面は多くの要素が`<s-*>`カスタム要素のShadow DOM内にカプセル化されている
(1ページに1000個以上のshadow rootが存在する)。通常の
`driver.find_element(By.CSS_SELECTOR/XPATH, ...)`はShadow DOM内部には到達できないため、
スクリプト内の以下のヘルパー関数群でJavaScript経由のShadow DOM横断検索を行っている:

- `find_in_shadow_by_aria` / `find_in_shadow_by_role` / `find_all_in_shadow`
- `find_by_commandfor`(新しいHTML Invoker Commands API `commandfor`属性対応)
- `find_visible_by_text`(同一テキストの非表示複製要素を除外し、実際に表示されている
  ものだけを選ぶ)
- `resolve_clickable`(`display:contents`なカスタム要素から実際にクリック可能な
  子孫のbutton/aを解決)
- `click_element` / `click_element_simple`(通常click→ActionChains実マウス操作→
  JSクリックの順にフォールバック)

もしUIが変更されてセレクタが効かなくなった場合、まず「対象要素がShadow DOM内にないか」
「テキストが重複した非表示の複製要素を掴んでいないか(`getBoundingClientRect`が
`w=0,h=0`になっていないか)」を疑うこと。

### 印刷処理の正しい対象

印刷機能は独立したボタンではなく、注文詳細ページの「その他の操作」ドロップダウン
メニュー(id="order-details-more-actions-menu")内にある。メニュー内の「印刷」
セクションには2項目あるが:

- **「注文ページを印刷」← これが正しい**
- 「明細表を印刷」← これは別の帳票(packing slip PDF)を新規タブで開く別機能。
  誤ってこちらをクリックしないこと。

`click_print_button(driver)`関数がこの正しいフローを実装している。

### 「次へ」ボタン

旧UIの`id="nextURL"`は廃止され、`aria-label="Go to next page"`(英語ラベルのまま)
のボタンに変わっている。`click_next_order_button(driver)`関数を使うこと。

### Chrome起動の仕組み

`launch_chrome()`関数はChromeを直接起動するのではなく、OS判定(Windows/Mac)を行い、
`DontTouch`フォルダの中に**事前配置された**起動スクリプトを実行する:

- Windows: `<スクリプトと同じ場所>/DontTouch/openChrome.bat`
- Mac: `<スクリプトと同じ場所>/DontTouch/openChrome.sh`

これらのスクリプトはリポジトリ直下にテンプレートとして置かれている
(`openChrome.bat` / `openChrome.sh`)。中身は`%~dp0`(Windows)や
`$(dirname ...)`(Mac)でスクリプト自身の場所を動的に解決し、それを
`--user-data-dir`としてChromeを`--remote-debugging-port=9222 --kiosk-printing
--start-maximized`付きで起動する。PCごとに絶対パスを書き換える必要はない。

`DontTouch`フォルダにこの起動スクリプトが存在しない場合、`launch_chrome()`は
エラーメッセージを表示するだけで何もしない。**セットアップ手順の5番を必ず
実施すること。**

既に同じuser-data-dirでChromeが起動中の場合は新規プロセスは起動せず、既存
プロセスに新規ウィンドウ要求が転送されるだけなので、何度実行しても問題ない。
`--kiosk-printing`により印刷は確認ダイアログなしで直接実行される点に注意。

## テスト時の注意(重要)

このツールは実際のShopify本番ストアの実在の注文データに対して操作を行う。
特に印刷処理は実際にプリンター/PDF出力を伴うため、**むやみに自動で印刷ボタンまで
クリックするテストを繰り返さない**こと。動作確認する際の推奨手順:

1. tkinter GUIのボタン操作は自動化せず、関数を直接呼び出す形でテストする
   (画面のスクリーンショットを撮ると、ユーザーの他アプリの情報が写り込むリスクが
   あるため、`driver.save_screenshot()`でブラウザ内のみをキャプチャするか、
   `driver.execute_script(...)`でDOM状態を直接確認する方法を優先する)
2. 検索・詳細ページ遷移・情報取得など副作用のない処理から確認し、印刷ボタンなど
   実際に外部作用を及ぼす操作をクリックする前には、必ずユーザーに確認を取る
3. 複数のPython/Chromeプロセスが同時に同じ`DontTouch`プロファイルを使うと、
   ポート競合やSingletonLockの問題で不安定になる。テスト前に
   `ps aux | grep 指示書印刷` 等で既存プロセスの有無を確認し、不要なら整理してから
   1プロセスだけで実行する

## ビルド(EXE化)

```
pyinstaller "指示書印刷_v8.0.py" --add-data "bitmex.json;." --onefile --hidden-import=webdriver_manager --hidden-import=oauth2client --hidden-import=gspread --name "指示書印刷_v8.0"
```

`dist\指示書印刷_v8.0.exe` が生成される。`--add-data`の区切り文字はWindowsでは`;`。
