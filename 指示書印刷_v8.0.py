from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import time
from datetime import datetime, timedelta
import os
import sys
import subprocess

# selenium 4
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

import requests

from collections import defaultdict
import re

# 必要な例外をインポート
from selenium.common.exceptions import ElementClickInterceptedException, NoSuchElementException
import platform

def launch_chrome():
    # Chromeをリモートデバッグモードで起動。
    # 専用のChromeプロファイル(Cookie等)をDontTouchフォルダに保管して安定動作させる
    # ため、DontTouchフォルダ内に事前配置した起動用スクリプト経由で起動する。
    # (DontTouchはユーザーが事前に用意するフォルダで、gitリポジトリには含まれない。
    #  リポジトリ直下の openChrome.bat / openChrome.sh をコピーして配置すること)
    current_os = platform.system()

    try:
        base_dir = os.path.dirname(sys.argv[0])
    except Exception:
        base_dir = os.path.dirname(__file__)

    if current_os == 'Windows':
        bat_file = os.path.join(base_dir, 'DontTouch', 'openChrome.bat')
        if os.path.exists(bat_file):
            subprocess.Popen([bat_file], shell=True)
        else:
            print(f"起動用batファイルが見つかりません: {bat_file}\n"
                  f"リポジトリ直下の openChrome.bat を DontTouch フォルダにコピーしてください。")
    elif current_os == 'Darwin':
        sh_file = os.path.join(base_dir, 'DontTouch', 'openChrome.sh')
        if os.path.exists(sh_file):
            subprocess.Popen(['bash', sh_file])
        else:
            print(f"起動用シェルスクリプトが見つかりません: {sh_file}\n"
                  f"リポジトリ直下の openChrome.sh を DontTouch フォルダにコピーしてください。")
    else:
        print(f"未対応のOSです: {current_os}")


def get_page_title(driver):
    # 現行UIではページタイトル(h1)もShadow DOM内にあるため横断検索が必要
    try:
        for element in driver.execute_script(_FIND_ALL_BY_SELECTOR_JS, "h1"):
            if element.text:
                return element
    except Exception:
        pass

    selectors = [
        (By.CSS_SELECTOR, "h1"),
        (By.ID, "page-title"),
        (By.CLASS_NAME, "Polaris-Header-Title"),
        (By.CSS_SELECTOR, ".Polaris-Header-Title__Title h1")
    ]
    for by, value in selectors:
        try:
            element = driver.find_element(by, value)
            if element.text:
                return element
        except Exception:
            continue
    raise NoSuchElementException("詳細ページのタイトル要素が見つかりませんでした")

def find_detail_link(driver):
    selectors = [
        'tbody tr a[href*="/orders/"]',
        'tr a[href*="/orders/"]',
        'a[href*="/orders/"]:not([href$="/orders"])'
    ]
    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                href = el.get_attribute('href')
                if el.is_displayed() and href and "/orders/" in href:
                    return el
        except Exception:
            continue
    raise NoSuchElementException("注文詳細へのリンクが見つかりませんでした")

def find_search_input(driver):
    selectors = [
        'input[placeholder="すべての注文を検索"]',
        'input[placeholder*="注文を検索"]',
        'input[placeholder*="Search"]',
        'input[type="search"]',
        'input[aria-label="検索"]',
        'input[aria-label="Search"]'
    ]
    for selector in selectors:
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
            if element.is_displayed():
                return element
        except NoSuchElementException:
            continue
    raise NoSuchElementException("検索入力フィールドが見つかりませんでした")


# 現行のShopify管理画面はUIの大部分がShadow DOM(Web Components)にカプセル化されており、
# 通常のfind_element(By.CSS_SELECTOR/XPATH)ではその内部の要素に到達できない。
# そのため、JavaScript側でShadow DOMを再帰的に辿って要素を探す。
_FIND_BY_ARIA_JS = '''
function find(root, label, exact) {
    const all = root.querySelectorAll("*");
    for (const el of all) {
        const aria = el.getAttribute && el.getAttribute("aria-label");
        if (aria && (exact ? aria === label : aria.includes(label))) {
            return el;
        }
        if (el.shadowRoot) {
            const found = find(el.shadowRoot, label, exact);
            if (found) return found;
        }
    }
    return null;
}
return find(document, arguments[0], arguments[1]);
'''

_FIND_BY_ROLE_JS = '''
function find(root, role) {
    const all = root.querySelectorAll("*");
    for (const el of all) {
        if (el.getAttribute && el.getAttribute("role") === role) {
            return el;
        }
        if (el.shadowRoot) {
            const found = find(el.shadowRoot, role);
            if (found) return found;
        }
    }
    return null;
}
return find(document, arguments[0]);
'''

_FIND_ALL_BY_SELECTOR_JS = '''
function find(root, selector, results) {
    root.querySelectorAll(selector).forEach(el => results.push(el));
    root.querySelectorAll("*").forEach(el => { if (el.shadowRoot) find(el.shadowRoot, selector, results); });
}
const results = [];
find(document, arguments[0], results);
return results;
'''

# s-internal-button等のカスタム要素は display:contents でサイズを持たないため、
# 実際にクリック可能な(サイズを持つ)子孫のbutton/a要素までShadow DOMを辿って解決する
_RESOLVE_CLICKABLE_JS = '''
function resolve(el) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return el;
    if (el.shadowRoot) {
        const inner = el.shadowRoot.querySelector("button, a, [role=button]");
        if (inner) return resolve(inner);
    }
    return el;
}
return resolve(arguments[0]);
'''

# commandfor/aria-controls等でポップオーバー・メニューに関連付けられたトリガー要素を探す
_FIND_BY_COMMANDFOR_JS = '''
function find(root, target) {
    const all = root.querySelectorAll("*");
    for (const el of all) {
        for (const attr of ["commandfor", "aria-controls", "popovertarget"]) {
            const v = el.getAttribute && el.getAttribute(attr);
            if (v && v.includes(target)) return el;
        }
        if (el.shadowRoot) {
            const found = find(el.shadowRoot, target);
            if (found) return found;
        }
    }
    return null;
}
return find(document, arguments[0]);
'''

# メニュー項目などはテキストが重複して複数存在することがあるため(レスポンシブ用の
# 別レイアウトなど)、実際に表示されている(サイズを持つ)ものだけに絞って探す
_FIND_VISIBLE_BY_TEXT_JS = '''
function find(root, text, results) {
    root.querySelectorAll("li, button, a, [role=menuitem]").forEach(el => {
        const t = el.textContent && el.textContent.trim();
        if (t === text) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) results.push(el);
        }
    });
    root.querySelectorAll("*").forEach(el => { if (el.shadowRoot) find(el.shadowRoot, text, results); });
}
const results = [];
find(document, arguments[0], results);
return results;
'''


def find_in_shadow_by_aria(driver, aria_label, exact=True):
    return driver.execute_script(_FIND_BY_ARIA_JS, aria_label, exact)


def find_in_shadow_by_role(driver, role):
    return driver.execute_script(_FIND_BY_ROLE_JS, role)


def find_all_in_shadow(driver, css_selector):
    return driver.execute_script(_FIND_ALL_BY_SELECTOR_JS, css_selector)


def find_by_commandfor(driver, target_id):
    return driver.execute_script(_FIND_BY_COMMANDFOR_JS, target_id)


def find_visible_by_text(driver, text):
    elements = driver.execute_script(_FIND_VISIBLE_BY_TEXT_JS, text)
    return elements[0] if elements else None


def resolve_clickable(driver, element):
    if element is None:
        return None
    return driver.execute_script(_RESOLVE_CLICKABLE_JS, element)


def click_element_simple(driver, element):
    # 通常クリック→scrollIntoView後クリック→JSクリックの順にフォールバックする
    try:
        element.click()
        return
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)
        return
    except Exception:
        pass
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.5)
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)


def click_element(driver, element):
    # Web Components(Invoker Commands API)を使うボタンはプログラム的な.click()では
    # 反応しないことがあるため、実際のマウス操作(ActionChains)を優先する
    try:
        ActionChains(driver).move_to_element(element).pause(0.2).click().perform()
        return
    except Exception:
        pass
    click_element_simple(driver, element)


def open_order_search(driver):
    # 「検索と絞り込み」はShadow DOM内のdiv(button相当)のため、通常のセレクタでは見つからない
    search_btn = find_in_shadow_by_aria(driver, '検索と絞り込み', exact=True)
    if search_btn is None:
        search_btn = find_in_shadow_by_aria(driver, '検索', exact=False)
    if search_btn is None:
        raise NoSuchElementException("「検索と絞り込み」ボタンが見つかりませんでした")
    # このボタンは通常クリックで確実に動作する(ActionChainsだと後続の検索欄取得が不安定になる)
    click_element_simple(driver, resolve_clickable(driver, search_btn))
    time.sleep(1)

    # 検索入力欄も通常のinputではなく、Shadow DOM内のcontenteditable divとして実装されている
    search_box = find_in_shadow_by_role(driver, 'textbox')
    if search_box is None:
        raise NoSuchElementException("検索入力フィールドが見つかりませんでした")
    return search_box


def click_print_button(driver):
    # 「注文ページを印刷」は独立したボタンではなく、「その他の操作」ドロップダウンメニュー
    # (id="order-details-more-actions-menu")内の項目として実装されている。
    # そのため先にメニューを開いてから項目をクリックする必要がある。
    main_handle = driver.current_window_handle

    trigger = find_by_commandfor(driver, 'order-details-more-actions-menu')
    if trigger is None:
        raise NoSuchElementException("「その他の操作」ボタンが見つかりませんでした")
    click_element(driver, resolve_clickable(driver, trigger))
    time.sleep(1)

    # メニュー項目のaria-label/accessibilitylabelを持つ要素自体はサイズ0の
    # カスタム要素のことが多いため、実際に表示されているli/button要素をテキストで探す
    menu_item = find_visible_by_text(driver, '注文ページを印刷')
    if menu_item is None:
        raise NoSuchElementException("「注文ページを印刷」メニュー項目が見つかりませんでした")
    click_element(driver, menu_item)
    time.sleep(1.5)

    # 印刷が新しいタブ/ウィンドウを開くことがあるため、後続処理のために必ず
    # 元のタブへ戻る(そうしないと以降の要素検索が別タブに対して行われてしまう)
    if driver.current_window_handle != main_handle:
        driver.switch_to.window(main_handle)


_NEXT_PAGE_LABELS = ['次のページへ移動', 'Go to next page']


def click_next_order_button(driver, retries=3, wait_between=1.5):
    # 旧UIの id="nextURL" ボタンは廃止され、aria-label="次のページへ移動"
    # (表示言語設定によっては英語の"Go to next page")のボタン(Shadow DOM内)に
    # 変わっている。印刷処理の直後はDOMやフォーカスが一時的に不安定なことが
    # あるため、複数回リトライする。
    last_error = NoSuchElementException("「次へ」ボタンが見つかりませんでした")
    for attempt in range(retries):
        for label in _NEXT_PAGE_LABELS:
            btn = find_in_shadow_by_aria(driver, label, exact=True)
            if btn is not None:
                click_element(driver, btn)
                return
        time.sleep(wait_between)
    raise last_error


_DATE_TEXT_PATTERN = re.compile(r'\d{4}年\d{1,2}月\d{1,2}日')


def get_page_date_text(driver):
    # ページヘッダー直下の日付表記(例: "2026年7月9日 12:06 下書き注文から")もShadow DOM内にある
    try:
        for element in find_all_in_shadow(driver, 'p.subheading'):
            if element.text and _DATE_TEXT_PATTERN.search(element.text):
                return element.text
    except Exception:
        pass

    # フォールバック: 旧UIのクラス名
    try:
        element = driver.find_element(By.CLASS_NAME, 'Polaris-Page-Header__AdditionalMetaData')
        return element.text
    except Exception:
        pass
    raise NoSuchElementException("日付情報の要素が見つかりませんでした")


def get_customer_section(driver, timeout=10):
    # aria-label="お客様"のセクションもShadow DOM内にある
    end_time = time.time() + timeout
    while time.time() < end_time:
        element = find_in_shadow_by_aria(driver, 'お客様')
        if element is not None:
            return element
        time.sleep(0.5)
    raise NoSuchElementException("お客様情報の要素が見つかりませんでした")


def Collect(next_url, driver, brand, dl_url,numText,customer_name, customer_info,date_string,payFlag,status_tags):

    try:
        # 必要情報の回収
        # "合計"というテキストを含むspan要素を見つける
        total_element = driver.find_element(By.XPATH, "//span[text()='合計']")

        # 親のdiv要素を取得
        parent_div = total_element.find_element(By.XPATH, "./ancestor::div[1]")

        # 兄弟のdiv要素を取得
        sibling_div = parent_div.find_element(By.XPATH, "following-sibling::div")

        # テキストを抽出
        total_price = sibling_div.text.replace("￥","").replace(",","")

        # 合計点数を抽出
        # "小計"というテキストを含むspan要素を見つける
        subtotal_element = driver.find_element(By.XPATH, "//span[text()='小計']")

        # 親のdiv要素を取得
        parent_div = subtotal_element.find_element(By.XPATH, "./ancestor::div[1]")

        # 兄弟のdiv要素を取得
        sibling_div = parent_div.find_element(By.XPATH, "following-sibling::div")

        # 「8個のアイテム」というテキストを抽出
        items_num = sibling_div.find_element(By.XPATH, ".//span[contains(text(), '個のアイテム')]").text.replace('個のアイテム','')


        # 「タグ」というテキストを持つh2要素を基に要素を指定
        tag_header_element =  driver.find_element(By.XPATH, "//h2[text()='タグ']")

        # 「タグ」の後に続く全てのタグ要素を取得
        tag_elements = tag_header_element.find_elements(By.XPATH, "./following-sibling::div//span[@class='Polaris-Tag__Text']")

        # タグをリストにして抽出
        put_tags = ', '.join([tag.text for tag in tag_elements]) 

        # 「配達方法」というテキストを持つspan要素を基に要素を指定
        try:
            delivery_method_label = driver.find_element(By.XPATH, "//span[text()='配達方法']")

            # 配達方法のテキスト要素を取得
            delivery_method_element = delivery_method_label.find_element(By.XPATH, "../following-sibling::dd//p")

            # 配達方法を抽出
            delivery_method = delivery_method_element.text
        
        except Exception:
            # 配達方法を抽出
            delivery_method =''

        # メモの要素を追加する
        memo_element = driver.find_element(By.XPATH, "//h2[text()='メモ']/ancestor::div/following-sibling::div//div")
        memo_text = memo_element.text
        if memo_text=='お客様からのメモはありません':
            memo_text=''

        # 親要素をXPathで見つける
        # CSSクラスが「_CustomStyledList_1lmi8_1」のulタグを親要素として取得
        parent_elements = driver.find_elements(By.XPATH, '//ul[@class="_CustomStyledList_1lmi8_1"]')

        for index, parent_element in enumerate(parent_elements):

            try:
                # 親要素の親要素のさらに1個上の兄弟要素を取得
                sibling_element = parent_element.find_element(By.XPATH, './../../preceding-sibling::div[1]')

                # その兄弟要素の子要素の子要素内のspanタグで「未回収」を含む要素を探す
                uncollected_element = sibling_element.find_element(By.XPATH, './/span')

                item_status=uncollected_element.text.replace('注意\n','')

                # 未回収の要素を取得して処理
                print(f"回収した未回収要素: {item_status}")

            except Exception as e:
                # 親要素の親要素のさらに1個上の兄弟要素を取得
                sibling_element = parent_element.find_element(By.XPATH, './../preceding-sibling::div[1]')

                # その兄弟要素の子要素の子要素内のspanタグで「未回収」を含む要素を探す
                uncollected_element = sibling_element.find_element(By.XPATH, './/span')

                item_status=uncollected_element.text.replace('注意\n','')

                # 未回収の要素を取得して処理
                print(f"回収した未回収要素: {item_status}")

            # 親要素直下のすべてのliタグを抽出
            list_items = parent_element.find_elements(By.XPATH, './li')

            # list_items内のitem_titleの出現回数を記録する辞書を作成
            title_counter = defaultdict(int)

            for index, item in enumerate(list_items):

                all_text=item.text

                # 「備考:」を含む要素を特定
                try:    
                    remark_tit = item.find_element(By.XPATH, ".//span[contains(text(), '備考欄:')]")

                    # その一つ下の兄弟要素の<div>を特定
                    remark_div = remark_tit.find_element(By.XPATH, "./following-sibling::div")

                    remark=remark_div.text
                except:
                    remark=''

                # 「データに関する備考:」を含む要素を特定
                try:
                    data_note_tit = item.find_element(By.XPATH, ".//span[contains(text(), 'データに関する備考:')]")

                    # その一つ下の兄弟要素の<div>を特定
                    data_note_div = data_note_tit.find_element(By.XPATH, "./following-sibling::div")

                    data_remark=data_note_div.text
                except:
                    data_remark=''

                # 「テストプリント配送先:」を含む要素を特定
                try:
                    test_address_tit = item.find_element(By.XPATH, ".//span[contains(text(), 'テストプリント配送先:')]")

                # その一つ下の兄弟要素の<div>を特定
                    test_address_div = test_address_tit.find_element(By.XPATH, "./following-sibling::div")

                    test_address=test_address_div.text
                except:
                    test_address=''

                # 初期化
                img_src = ''  # img_src を初期化

                try:
                    # h3タグを検索し、テキストを取得
                    item_title = item.find_element(By.TAG_NAME, 'h3').text
                    if item_title == '代金引換手数料':
                        continue

                    variant_title_element = item.find_element(By.CLASS_NAME, 'Polaris-Tag__Text')
                    variant_title = variant_title_element.text.replace("/", "-")
                    try:
                        # liタグ内のimgタグのsrcを回収
                        img_element = item.find_element(By.XPATH, './/img')
                        img_src = img_element.get_attribute('src')
                        print(img_src)
                    except Exception as e:
                        # imgが見つからない場合は空のまま
                        pass
                except Exception as e:
                    variant_title =''

                info=[]
                
                info.append(brand)
                info.append(numText)
                info.append(date_string)
                info.append(customer_name)
                info.append(customer_info)
                info.append(memo_text)
                info.append(status_tags)
                info.append(delivery_method)
                info.append(items_num)
                info.append(total_price)
                info.append(put_tags)
                info.append(payFlag)

                info.append(item_status)
                info.append(variant_title)
                info.append(img_src)
                info.append(all_text)
                info.append(remark)
                info.append(data_remark)
                info.append(test_address)

                print(info)
                wsh.append_row(info)

    except Exception as e:
        print(f"エラーが発生しました: {e}")

    time.sleep(1)


# ダウンロードディレクトリの設定
# download_dir = os.path.join(os.path.dirname(__file__), 'downloads')
# download_dir = r'\\Printpc-ishi\e\photopri_01'
def DownLoad(next_url, driver, dl_url,numText,customer_name):
    # フォルダ作成
    folder_name = numText+"_"+customer_name
    
    order_path=os.path.join(dl_url,folder_name)
    
    # フォルダが存在するかチェッ
    if not os.path.exists(order_path):
        # フォルダを作成
        os.makedirs(order_path)

    try:
        # 親要素をXPathで見つける
        # CSSクラスが「_CustomStyledList_1lmi8_1」のulタグを親要素として取得
        parent_elements = driver.find_elements(By.XPATH, '//ul[@class="_CustomStyledList_1lmi8_1"]')
        no_link_found = True  # リンクが見つからなかった場合のフラグ

        for index, parent_element in enumerate(parent_elements):
            # 親要素直下のすべてのliタグを抽出
            list_items = parent_element.find_elements(By.XPATH, './li')

            # list_items内のitem_titleの出現回数を記録する辞書を作成
            title_counter = defaultdict(int)

            for index, item in enumerate(list_items):
                try:
                    # h3タグを検索し、テキストを取得
                    item_title = item.find_element(By.TAG_NAME, 'h3').text
                    try:
                        variant_title_element = item.find_element(By.CLASS_NAME, 'Polaris-Tag__Text')
                        variant_title = variant_title_element.text.replace("/", "-")
                        set_title=item_title + "_" + variant_title
                    except:
                        print("バリアントなし")
                        variant_title=""
                        set_title=item_title

                    # item_titleの出現回数をカウント
                    title_counter[set_title] += 1

                    # 連番付きのフォルダ名を作成
                    if title_counter[set_title] > 1:
                        item_title_with_count = f"{set_title}#{title_counter[set_title]}"
                    else:
                        item_title_with_count = set_title

                    # フォルダ名を安全な文字列に変換
                    item_title_with_count = re.sub(r'[<>:"/\\|?*]', '_', item_title_with_count)

                    # フォルダ作成
                    item_path = os.path.join(order_path, item_title_with_count)


                except Exception as e:
                    # h3タグが見つからない場合
                    print(f"エラー内容：{e}。ファイルを含むボックスではなかったので飛ばします。")


                try:
                    # 親要素の子要素の中で、クラスがPolaris-Linkでテキストが「リンク」の要素を見つける
                    link_elements = item.find_elements(By.XPATH, ".//a[contains(@class, 'Polaris-Link') and contains(text(), 'リンク')]")
                    if len(link_elements) > 0:
                        no_link_found = False  # リンクが見つかった場合はフラグを更新
                        # フォルダが存在するかチェック
                        if not os.path.exists(item_path):
                            # フォルダを作成
                            os.makedirs(item_path)

                        for link_element in link_elements:
                            # そのaタグの親要素（divタグ）を取得
                            parent_div = link_element.find_element(By.XPATH, "./..")
                            grandparent_div = parent_div.find_element(By.XPATH, "./..")
                            greatparent_div = grandparent_div.find_element(By.XPATH, "./..")

                            # 親要素の最初の子要素（divタグ）を特定し、その中のテキストを抽出
                            property_name = greatparent_div.find_element(By.XPATH, "./div[1]").text
                            property_rename = property_name.replace("\n", "").replace("リンク", "").replace(":", "").replace("/", "-")
                            file_url = link_element.get_attribute('href')
                            # ファイル名をURLの最後の"/"より後の文字列に設定し、拡張子を抽出
                            basefilename = os.path.basename(file_url)
                            filename_without_ext, extension = os.path.splitext(basefilename)
                            
                            filename = numText + "_" + variant_title + "_" + property_rename + extension
                            # ファイル名から無効な文字を置換
                            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

                            print(f"ファイル名：{filename}")

                            # ファイルをダウンロード
                            response = requests.get(file_url)
                            filename_path = os.path.join(item_path, filename)  # 適切なファイル名を設定してください
                            with open(filename_path, 'wb') as file:
                                file.write(response.content)
                            time.sleep(2)
                except Exception as e:
                    # h3タグが見つからない場合
                    print(f"エラー内容：{e}　リンクが見つかりません")
        # リンクが見つからなかった場合、order_pathを削除（特定のURL以外の場合）
        if no_link_found and next_url != 'https://admin.shopify.com/store/aad872-2/orders?inContextTimeframe=today':
            if os.path.exists(order_path):
                os.rmdir(order_path)
                print(f"{order_path} を削除しました。")
    except Exception as e:
        print(f"エラーが発生しました: {e}")

    time.sleep(1)
    
def autoPrintNumber(next_url, order_number_list, dl_url, brand):

    # Chromeを起動
    launch_chrome()

    # Seleniumの処理を待機
    time.sleep(3)

    # 起動時にオプションをつける。（ポート指定により、起動済みのブラウザのドライバーを取得）
    options = webdriver.ChromeOptions()

    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    driver = webdriver.Chrome(options=options)

    driver.get(next_url)
 
    time.sleep(5)


    # # テストスキップ用
    # for t in range(4):
    #     detail_element=driver.find_element(By.XPATH,'//*[@id="nextURL"]')
    #     detail_element.click()
    #     time.sleep(2)

    # 詳細情報に飛ぶ
    try: 
        detail_element=driver.find_element(By.XPATH,'/html/body/div/div[1]/div/div[3]/main/div/div/div/div/div[2]/div/div[1]/div/div/div[1]/div/div[2]/div[1]/div/div/div[2]/span[1]/div/button')
        # detail_element.click()
    except Exception:
        # 詳細情報に飛ぶ(ログイン有)
        # ログイン処理
        try:
            send_element=driver.find_element(By.XPATH,'//*[@id="account_lookup"]/div[5]/button')
            
            time.sleep(2)
            send_element.click()
            time.sleep(3)

            # ログイン情報
            passsend_element=driver.find_element(By.XPATH,'//*[@id="login_form"]/div[2]/div[4]/button')
            time.sleep(2)
            passsend_element.click()
            time.sleep(3)

        except Exception:
            # 複数アカウントから選択
            # 'user-card__name'クラスを持つすべての要素を取得
            user_card_names = driver.find_elements(By.CLASS_NAME, 'user-card__name')

            # 各要素に対して
            for user_card_name in user_card_names:
                # テキストが'PRINTSTAFF'であるかチェック
                if user_card_name.text == 'PRINTSTAFF':
                    # 'PRINTSTAFF'を含む要素の親要素を取得
                    parent_a = user_card_name.find_element(By.XPATH, './ancestor::a')
                    # href属性を出力
                    parent_a.click()
                    time.sleep(3)

    time.sleep(1)

    # リスト内のデータを一個一個表示
    for order_number in order_number_list:
        print(f"注文番号: {order_number}")
        # フィルターをかける(検索ボタン・入力欄ともShadow DOM内のため専用関数を使用)
        try:
            search_input = open_order_search(driver)
        except Exception as e:
            print(f"検索と絞り込みを開けませんでした: {e}")
            continue

        time.sleep(1)
        search_input.send_keys(order_number)
        time.sleep(2)

        # 注文詳細リンクを見つけてクリックする
        try:
            detail_element = find_detail_link(driver)
            detail_element.click()
        except Exception as e:
            print(f"詳細画面への遷移リンクのクリックに失敗しました: {e}")
            # 最終的なフォールバック
            try:
                detail_elements = driver.find_elements(By.XPATH, "//a[contains(@href, '/orders/')]")
                detail_element = detail_elements[1]
                detail_element.click()
            except Exception as e2:
                print(f"最終フォールバックも失敗しました: {e2}")
                continue
        time.sleep(3)

        MAX_ATTEMPTS = 10  # 最大試行回数
        attempt = 0

        while attempt < MAX_ATTEMPTS:
            try:
                numElement = WebDriverWait(driver, 15).until(
                    lambda d: get_page_title(d)
                )
                numText = numElement.text
            except Exception as e:
                print(f"注文番号（タイトル）のロードタイムアウト: {e}")
                time.sleep(2)
                attempt += 1
                continue


            print(f"試行回数: {attempt + 1}, 現在の注文番号: {numText}")

            # 条件を確認
            if order_number in numText:
                print(f"条件を満たしました: {order_number} が {numText} に含まれています")

                # 日付データを回収(Shadow DOM対応)
                try:
                    original_text = get_page_date_text(driver)
                except Exception as e:
                    print(f"日付情報の取得に失敗しました: {e}")
                    continue

                # 文字列をスペースで分割し、前半部分を取得
                parts = original_text.split()
                if len(parts) >= 2:
                    date_string = parts[0] + parts[1]
                else:
                    print(f"日付文字列の形式が不正です: {original_text}")
                    continue

                # 文字列から日付と時刻を抽出
                date_format = "%Y年%m月%d日%H:%M"
                date = datetime.strptime(date_string, date_format)

                # aria-label="お客様"を持つセクションを取得(Shadow DOM対応)
                parent_element = get_customer_section(driver)
                customer_info = parent_element.text

                # 顧客名を取得（s-internal-linkカスタム要素から取得）
                try:
                    customer_name_element = parent_element.find_element(By.CSS_SELECTOR, "s-internal-link[href*='/customers/']")
                    customer_name = customer_name_element.text
                except:
                    try:
                        customer_name_element = parent_element.find_element(By.XPATH, ".//p")
                        customer_name = customer_name_element.text
                    except:
                        customer_name = "顧客名不明"

                if customer_name == "":
                    time.sleep(5)
                    try:
                        customer_name_element = parent_element.find_element(By.CSS_SELECTOR, "s-internal-link[href*='/customers/']")
                        customer_name = customer_name_element.text
                    except:
                        customer_name = "顧客名不明"

                print("")
                print("注文番号：" + numText)
                print("注文日時：" + date_string)
                print("顧客氏名：" + customer_name)

                # # --指示書情報回収--
                # Collect(next_url, driver, brand, dl_url,numText,customer_name, customer_info,date_string,payFlag,status_tags)
                # # --指示書情報回収--
                
                # # --ダウンロード処理を実行--
                # DownLoad(next_url, driver, dl_url,numText,customer_name)
                # # --ダウンロード処理を実行--
                
                # --印刷処理--
                # 現行UIでは「明細表を印刷」という単一ボタン(Shadow DOM内)をクリックするだけでよい
                try:
                    click_print_button(driver)
                    time.sleep(2)
                except Exception as e:
                    print(f"エラー：{e}。通常の印刷処理ができなかったため、デフォルト機能で印刷します")
                    driver.execute_script('window.print()')
                # --印刷処理--

                time.sleep(1)
                break  # ループを抜ける
            else:
                # 次のボタンを押す
                try:
                    click_next_order_button(driver)
                except Exception as e:
                    print(f"「次へ」ボタンのクリックに失敗しました: {e}")


                time.sleep(3)

            attempt += 1  # 試行回数を増加

        if attempt == MAX_ATTEMPTS:
            print("条件を満たせずに最大試行回数に達しました。")


        # 注文詳細に戻る
        detail_element=driver.find_element(By.CSS_SELECTOR, 'a[aria-label="注文"]')
        time.sleep(1)
        detail_element.click()
        time.sleep(1)

        # 探索をキャンセルする
        delete_element = driver.find_element(By.XPATH, "//button[contains(., 'キャンセル')]")
        delete_element.click()
        time.sleep(2)

    print("処理を終了しました")

    driver.close()

def autoPrint(next_url, start, end, dl_url, brand):

    # Chromeを起動
    launch_chrome()

    # Seleniumの処理を待機
    time.sleep(3)


    # 起動時にオプションをつける。（ポート指定により、起動済みのブラウザのドライバーを取得）
    options = webdriver.ChromeOptions()

    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    driver = webdriver.Chrome(options=options)

    driver.get(next_url)
 
    time.sleep(3)


    # 詳細情報に飛ぶ
    try:
        send_element=driver.find_element(By.XPATH,'//*[@id="account_lookup"]/div[5]/button')
        
        time.sleep(2)
        send_element.click()
        time.sleep(3)

        # ログイン情報
        passsend_element=driver.find_element(By.XPATH,'//*[@id="login_form"]/div[2]/div[4]/button')
        time.sleep(2)
        passsend_element.click()
        time.sleep(3)

    except Exception:
        try: 
            # 複数アカウントから選択
            # 'user-card__name'クラスを持つすべての要素を取得
            user_card_names = driver.find_elements(By.CLASS_NAME, 'user-card__name')

            # 各要素に対して
            for user_card_name in user_card_names:
                # テキストが'PRINTSTAFF'であるかチェック
                if user_card_name.text == 'PRINTSTAFF':
                    # 'PRINTSTAFF'を含む要素の親要素を取得
                    parent_a = user_card_name.find_element(By.XPATH, './ancestor::a')
                    # href属性を出力
                    parent_a.click()
                    time.sleep(3)
        except Exception:
            print("ログイン済みです")

    # 注文一覧のテーブル行が表示されるまで待機（ログイン完了待ちも兼ねる）
    print("注文一覧画面のロードを待機しています（必要に応じてログインを完了させてください）...")
    try:
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr, .Polaris-IndexTable__Row, a[href*='/orders/']"))
        )
        print("注文一覧画面のロードが完了しました。")
    except Exception as e:
        print(f"注文一覧画面のロードタイムアウト: {e}")

    MAX_RETRIES = 3  # 最大試行回数
    attempt = 0

    while attempt < MAX_RETRIES:
        try:
            # 注文詳細リンクを見つけてクリックする
            try:
                detail_element = find_detail_link(driver)
                detail_element.click()
                print("詳細に遷移しました")
            except Exception as e:
                print(f"詳細に遷移できませんでした: {e}")
                # 最終フォールバック
                try:
                    detail_elements = driver.find_elements(By.XPATH, "//a[contains(@href, '/orders/')]")
                    detail_element = detail_elements[0]
                    detail_element.click()
                except Exception as e2:
                    print(f"最終フォールバックも失敗しました: {e2}")
                    raise e2
            time.sleep(3)

            # クリック成功後、テキストを取得(Shadow DOM対応)
            # aria-label="お客様"を持つセクションを取得
            parent_element = get_customer_section(driver)

            # 顧客名を取得（s-internal-linkカスタム要素から取得）
            try:
                customer_name_element = parent_element.find_element(By.CSS_SELECTOR, "s-internal-link[href*='/customers/']")
                customer_name = customer_name_element.text
            except:
                try:
                    customer_name_element = parent_element.find_element(By.XPATH, ".//p")
                    customer_name = customer_name_element.text
                except:
                    customer_name = "顧客名不明"

            if customer_name == "":
                time.sleep(5)
                try:
                    customer_name_element = parent_element.find_element(By.CSS_SELECTOR, "s-internal-link[href*='/customers/']")
                    customer_name = customer_name_element.text
                except:
                    customer_name = "顧客名不明"

            print(f"取得したテキスト: {customer_name}")
            # numElement = driver.find_element(By.CLASS_NAME, 'Polaris-Header-Title')
            # numText = numElement.text
            # print(f"取得したテキスト: {numText}")

            # ✅ テキストが取得できたらループを抜ける
            break

        except Exception as e:
            print(f"エラー発生（試行回数: {attempt + 1}）: {e}")
            print("ページをリロードして再試行します...")
            driver.get(next_url)  # ページをリロード
            time.sleep(5)  # リロード後に少し待機

        attempt += 1  # 試行回数を増加

    # ✅ 3回試行しても要素を取得できなかった場合の処理
    if attempt == MAX_RETRIES:
        print("3回試行しても要素を取得できませんでした。")

    # --以下、ダウンロード処理を行う--
    judge=True

    while judge:
        # 注文番号を取得（ロードされるまで待機）
        try:
            numElement = WebDriverWait(driver, 15).until(
                lambda d: get_page_title(d)
            )
            numText = numElement.text
        except Exception as e:
            print(f"注文番号（タイトル）のロードタイムアウト: {e}")
            time.sleep(3)
            continue

        # 日付情報を取得(Shadow DOM対応)
        try:
            original_text = get_page_date_text(driver)
        except Exception as e:
            print(f"日付情報の取得に失敗しました: {e}")
            time.sleep(3)
            continue

        # 文字列をスペースで分割し、前半部分を取得
        parts = original_text.split()
        if len(parts) >= 2:
            date_string = parts[0] + parts[1]
        else:
            print(f"日付文字列の形式が不正です: {original_text}")
            continue

        # 文字列から日付と時刻を抽出
        date_format = "%Y年%m月%d日%H:%M"
        date = datetime.strptime(date_string, date_format)

        # aria-label="お客様"を持つセクションを取得(Shadow DOM対応)
        parent_element = get_customer_section(driver)
        customer_info = parent_element.text

        # 支払いフラグとステータスタグを初期化
        payFlag = ""
        status_tags = ""

        # 顧客名を取得（s-internal-linkカスタム要素から取得）
        try:
            customer_name_element = parent_element.find_element(By.CSS_SELECTOR, "s-internal-link[href*='/customers/']")
            customer_name = customer_name_element.text
        except:
            try:
                customer_name_element = parent_element.find_element(By.XPATH, ".//p")
                customer_name = customer_name_element.text
            except:
                customer_name = "顧客名不明"

        if customer_name == "":
            time.sleep(5)
            try:
                customer_name_element = parent_element.find_element(By.CSS_SELECTOR, "s-internal-link[href*='/customers/']")
                customer_name = customer_name_element.text
            except:
                customer_name = "顧客名不明"

        print("")
        print("注文番号：" + numText)
        print("注文日時：" + date_string)
        print("顧客氏名：" + customer_name)

        # 時間の条件を満たすかどうかを判定
        if end <= date:
            print("条件を満たしていません。ダウンロードせず、処理を続けます")
            time.sleep(1)

        elif start <= date < end:

            flag=True
            skip=False 

            # タグの要素を取得
            # numElementの兄弟要素のdivを取得
            tags = driver.find_element(By.CLASS_NAME, 'Polaris-InlineStack')
            order_tags = tags.find_elements(By.XPATH, ".//div")
            # 各要素に対して
            
            for order_tag in order_tags:
                # print(order_tag.text)
                if order_tag.text == 'キャンセル済み' or order_tag.text == '発送済み':
                    flag=False
                elif order_tag.text == '一部発送済み':
                    skip=True     

            if flag:           
                print("条件を満たしています。ダウンロードします")

                # # --指示書情報回収--
                # Collect(next_url, driver, brand, dl_url,numText,customer_name, customer_info,date_string,payFlag,status_tags)
                # # --指示書情報回収--

                # # --ダウンロード処理--
                # DownLoad(next_url, driver, dl_url,numText,customer_name)
                # # --ダウンロード処理--
                
                # --印刷処理--
                # 現行UIでは「明細表を印刷」という単一ボタン(Shadow DOM内)をクリックするだけでよい
                try:
                    click_print_button(driver)
                    time.sleep(2)
                except Exception as e:
                    print(f"エラー：{e}。通常の印刷処理ができなかったため、デフォルト機能で印刷します")
                    driver.execute_script('window.print()')
                # --印刷処理--
            else:
                print("キャンセルまたは、発送済みのため、ダウンロードせず処理を続けます")
                time.sleep(1)       

        else:
            print("条件を満たしていません。処理を終了します。")
            judge=False

        # 次のボタンを押す
        try:
            click_next_order_button(driver)
        except Exception as e:
            print(f"「次へ」ボタンのクリックに失敗しました: {e}")

        time.sleep(3)

    print("処理を終了しました")

    driver.close()

# # OSテスト環境用
# dl_path_photopri=r"C:\Users\torat\Downloads\一時ファイル"
# dl_path_e1=r"C:\Users\torat\Downloads\一時ファイル"
# dl_path_qoo=r"C:\Users\torat\Downloads\一時ファイル"

# 本番環境用
dl_path_photopri=r"\\192.168.3.16\ds923\photopri_01\注文ファイル"
dl_path_e1=r"\\192.168.3.16\ds923\e1_01\注文ファイル"
dl_path_qoo=r"\\192.168.3.16\外部共有フォルダ\Qoo_01\0_Qoo_order\注文ファイル"
dl_path_artgraph=r"\\192.168.3.16\外部共有フォルダ\artgraph_01\注文ファイル"

# # テスト環境用（Mac）
# dl_path_photopri=r"/Users/kurokawamutsuo/Downloads/test回収"
# dl_path_e1=r"/Users/kurokawamutsuo/Downloads/test回収"
# dl_path_qoo=r"/Users/kurokawamutsuo/Downloads/test回収"

url_qoo='https://admin.shopify.com/store/aad872-2/orders?inContextTimeframe=today'
url_e1='https://admin.shopify.com/store/e1print/orders?inContextTimeframe=today'
url_photopri='https://admin.shopify.com/store/photopri/orders?inContextTimeframe=today'
url_artgraph='https://admin.shopify.com/store/artgraph-shop/orders?inContextTimeframe=today'

brand_e1="e1"
brand_photopri="PHOTOPRI"
brand_artgraph="artgraph"
brand_qoo="qoo"

# EXE化に対応した相対パスの取得
try:        
    directory = os.path.dirname(sys.argv[0])
except Exception:
    directory = os.path.dirname(__file__)

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

# 設定
# EXE化に対応した相対パスの取得
try:        
    json_file = os.path.join(os.path.dirname(sys.argv[0]), 'bitmex.json')
except Exception:
    json_file = os.path.join(os.path.dirname(__file__), 'bitmex.json')

#2つのAPIを記述しないとリフレッシュトークンを3600秒毎に発行し続けなければならない
scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']

#認証情報設定
#ダウンロードしたjsonファイル名をクレデンシャル変数に設定（秘密鍵、Pythonファイルから読み込みしやすい位置に置く）         
credentials = ServiceAccountCredentials.from_json_keyfile_name(json_file, scope)

#OAuth2の資格情報を使用してGoogle APIにログインします。
gc = gspread.authorize(credentials)

#共有設定したスプレッドシートキーを変数[SPREADSHEET_KEY]に格納する。
SPREADSHEET_KEY = '1JUpzG-9BggkmSwXS83u4789CNxr05mJVjZ5XEPcJ7Nc'

ss = gc.open_by_key(SPREADSHEET_KEY)

# dlsh = ss.worksheet("回収スケジュール")
# wsh = ss.worksheet("日別回収")

# --スプレッドシートから処理--

# # シートの再計算を実行
# dlsh.update_cell(1, 1, dlsh.cell(1, 1).value)


# # シートのA〜K列のすべての値を取得
# values = dlsh.get_all_values()

# row_index = int(dlsh.acell('G1').value)  # G1セルの値をintで取得（行番号）
# target_row = values[row_index - 1]       # valuesは0始まりなので-1する
# do_time = target_row[1]  # D列（0-indexedで3）
# result = target_row[2]  # D列（0-indexedで3）
# start_str = target_row[3]  # D列（0-indexedで3）
# end_str = target_row[4]    # E列（0-indexedで4）


# # 文字列からdatetimeオブジェクトに変換（フォーマットに注意）
# start = datetime.strptime(start_str, '%Y/%m/%d %H:%M')
# end = datetime.strptime(end_str, '%Y/%m/%d %H:%M')

# print(f"Qoo開始: {start}, 終了: {end}{dl_path_qoo}")
# autoPrint(url_qoo, start, end, dl_path_qoo)

# print(f"e1開始: {start}, 終了: {end}{dl_path_e1}")
# autoPrint(url_e1, start, end, dl_path_e1)

# print(f"PHOTOPRI開始: {start}, 終了: {end}{dl_path_photopri}")
# autoPrint(url_photopri, start, end, dl_path_photopri, brand_photopri)



# # ✅ 最後に「済」をC列に記入
# if row_index is not None:
#     # 4列目と5列目のセルの値をコピー
#     start_cell_value = dlsh.cell(row_index, 4).value  # 4列目
#     end_cell_value = dlsh.cell(row_index, 5).value    # 5列目

#     # 同じセルに値のみ貼り付け
#     dlsh.update_cell(row_index, 4, start_cell_value)  # 4列目に貼り付け
#     dlsh.update_cell(row_index, 5, end_cell_value)    # 5列目に貼り付け
    
#     dlsh.update_cell(row_index, 3, "済")  # C列はインデックス3

# # --スプレッドシートから処理--


# --tkinterから処理--
import tkinter
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
# 現在の日付と時刻を取得
now = datetime.now()
# 昨日の日付を計算（時刻は12:00）
yesterday = now - timedelta(days=1)
yesterday_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
yesterday_time = yesterday.replace(year=1900, month=1, day=1, hour=12, minute=0)
# 今日の日付（時刻は12:00）
today_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
today_time = now.replace(year=1900, month=1, day=1, hour=12, minute=0)

# Tkクラス作成
root = tkinter.Tk()
# 画面サイズ
root.geometry('400x400')
# 画面タイトル
root.title('入力ボックス')

# 説明書
lbl = tkinter.Label(text='日時範囲、または注文番号を指定してください(入力形式注意！！)')
lbl.place(x=30, y=20)

# 説明書
lbl_num = tkinter.Label(text='ブランドと注文番号は一致させてください(全ブランド不可！)')
lbl_num.place(x=30, y=20)

# ブランドを選択する
lbl_mode_brand = tkinter.Label(text='ブランド')
lbl_mode_brand.place(x=30, y=50)

mode_brand = tkinter.StringVar(value='全ブランド')
mode_brand_dropdown = ttk.Combobox(root, textvariable=mode_brand, values=['全ブランド','PHOTOPRI', 'e1', 'Qoo', 'artgraph'])
mode_brand_dropdown.place(x=140, y=50)

# モード選択のラベルとドロップダウンリスト
lbl_mode = tkinter.Label(text='回収方法')
lbl_mode.place(x=30, y=80)
mode_var = tkinter.StringVar(value='日時範囲で回収')
mode_dropdown = ttk.Combobox(root, textvariable=mode_var, values=['日時範囲で回収', '注文番号で回収'])
mode_dropdown.place(x=140, y=80)

# 開始日のラベルとテキストボックス
lbl_start_date = tkinter.Label(text='開始日(古い日付)')
lbl_start_date.place(x=30, y=120)
txt_start_date = tkinter.Entry(width=20)
txt_start_date.place(x=140, y=120)
txt_start_date.insert(tkinter.END, yesterday_date.strftime('%Y/%m/%d'))

# 開始時刻のラベルとテキストボックス
lbl_start_time = tkinter.Label(text='開始時刻')
lbl_start_time.place(x=30, y=150)
txt_start_time = tkinter.Entry(width=20)
txt_start_time.place(x=140, y=150)
txt_start_time.insert(tkinter.END, yesterday_time.strftime('%H:%M'))

# 終了日のラベルとテキストボックス
lbl_end_date = tkinter.Label(text='終了日(新しい日付)')
lbl_end_date.place(x=30, y=180)
txt_end_date = tkinter.Entry(width=20)
txt_end_date.place(x=140, y=180)
txt_end_date.insert(tkinter.END, today_date.strftime('%Y/%m/%d'))

# 終了時刻のラベルとテキストボックス
lbl_end_time = tkinter.Label(text='終了時刻')
lbl_end_time.place(x=30, y=210)
txt_end_time = tkinter.Entry(width=20)
txt_end_time.place(x=140, y=210)
txt_end_time.insert(tkinter.END, today_time.strftime('%H:%M'))

lbl_dl_url = tkinter.Label(text='DLパス')
lbl_dl_url.place(x=30, y=240)

txt_dl_url_photopri = tkinter.Entry(width=20)
txt_dl_url_photopri.place(x=140, y=240)
txt_dl_url_photopri.insert(tkinter.END, dl_path_photopri)

txt_dl_url_e1 = tkinter.Entry(width=20)
txt_dl_url_e1.place(x=140, y=240)
txt_dl_url_e1.insert(tkinter.END, dl_path_e1)

txt_dl_url_qoo = tkinter.Entry(width=20)
txt_dl_url_qoo.place(x=140, y=240)
txt_dl_url_qoo.insert(tkinter.END, dl_path_qoo)

# 注文番号のラベルとテキストボックス
lbl_order_number = tkinter.Label(text='注文番号')
lbl_order_number.place(x=30, y=120)

# 注文番号の入力フィールドを含むフレームとスクロールバーを追加（修正箇所）
frame_order_number = tkinter.Frame(root)
frame_order_number.place(x=140, y=120, width=200, height=160)

scrollbar_order_number = tkinter.Scrollbar(frame_order_number)
scrollbar_order_number.pack(side=tkinter.RIGHT, fill=tkinter.Y)

# 注文番号の入力フィールドをTextウィジェットに変更（修正箇所）
txt_order_number = tkinter.Text(frame_order_number, width=30, height=8, yscrollcommand=scrollbar_order_number.set)
txt_order_number.pack(side=tkinter.LEFT, fill=tkinter.BOTH)
scrollbar_order_number.config(command=txt_order_number.yview)

# デフォルトの注文番号を挿入
txt_order_number.insert(tkinter.END, "#1111\n#1112\n")

# ボタンクリックイベント
def btn_click():
    if mode_var.get() == '日時範囲で回収':
        start_date_str = txt_start_date.get()
        start_time_str = txt_start_time.get()
        end_date_str = txt_end_date.get()
        end_time_str = txt_end_time.get()

        # 日付と時刻の文字列を結合し、datetimeオブジェクトに変換
        start_str = start_date_str + " " + start_time_str
        end_str = end_date_str + " " + end_time_str

        # 文字列からdatetimeオブジェクトに変換（フォーマットに注意）
        start = datetime.strptime(start_str, '%Y/%m/%d %H:%M')
        end = datetime.strptime(end_str, '%Y/%m/%d %H:%M')

        # 各テキストボックスから値を取得
        if mode_brand.get() == 'PHOTOPRI':
            dl_url = txt_dl_url_photopri.get() 
            # 結果を出力
            print(f"開始: {start}, 終了: {end}{dl_url}")
            autoPrint(url_photopri, start, end, dl_url, brand_photopri)
            
        elif mode_brand.get() == 'e1':
            dl_url = txt_dl_url_e1.get()
            # 結果を出力
            print(f"開始: {start}, 終了: {end}{dl_url}")
            autoPrint(url_e1, start, end, dl_url, brand_e1)

        elif mode_brand.get() == 'Qoo':
            dl_url = txt_dl_url_qoo.get()
            # 結果を出力
            print(f"開始: {start}, 終了: {end}{dl_url}")
            autoPrint(url_qoo, start, end, dl_url, brand_qoo)
        elif mode_brand.get() == 'artgraph':
            dl_url = txt_dl_url_qoo.get()
            # 結果を出力
            print(f"開始: {start}, 終了: {end}{dl_url}")
            autoPrint(url_artgraph, start, end, dl_url, brand_artgraph)
        else:
            print(f"Qoo開始: {start}, 終了: {end}{dl_path_qoo}")
            autoPrint(url_qoo, start, end, dl_path_qoo, brand_qoo)

            print(f"e1開始: {start}, 終了: {end}{dl_path_e1}")
            autoPrint(url_e1, start, end, dl_path_e1, brand_e1)

            print(f"PHOTOPRI開始: {start}, 終了: {end}{dl_path_photopri}")
            autoPrint(url_photopri, start, end, dl_path_photopri, brand_photopri)


    else:
        # 注文番号の取得方法を変更（リストに変換）
        order_number_text = txt_order_number.get("1.0", "end-1c")
        order_number_list = order_number_text.split('\n')
        order_number_list = [num for num in order_number_list if num.strip()]  # 空行を除去

        # 各テキストボックスから値を取得
        if mode_brand.get() == 'PHOTOPRI':
            dl_url = txt_dl_url_photopri.get() 
            # 結果を出力
            print(f"PHOTOPRI注文番号リスト: {order_number_list}, DLパス: {dl_url}")
            # autoPrint関数を変更する必要があります
            autoPrintNumber(url_photopri,order_number_list, dl_url, brand_photopri)
            
        elif mode_brand.get() == 'e1':
            dl_url = txt_dl_url_e1.get()
            # 結果を出力
            print(f"e1注文番号リスト: {order_number_list}, DLパス: {dl_url}")
            # autoPrint関数を変更する必要があります
            autoPrintNumber(url_e1,order_number_list, dl_url, brand_e1)

        elif mode_brand.get() == 'Qoo':
            dl_url = txt_dl_url_qoo.get()
            # 結果を出力
            print(f"Qoo注文番号リスト: {order_number_list}, DLパス: {dl_url}")
            # autoPrint関数を変更する必要があります
            autoPrintNumber(url_qoo,order_number_list, dl_url, brand_qoo)

        elif mode_brand.get() == 'artgraph':
            dl_url = txt_dl_url_qoo.get()
            # 結果を出力
            print(f"artgraph注文番号リスト: {order_number_list}, DLパス: {dl_url}")
            # autoPrint関数を変更する必要があります
            autoPrintNumber(url_artgraph,order_number_list, dl_url, brand_artgraph)


    root.destroy()

# 選択に応じた表示の切り替え
def update_brand_ui(*args):
    if mode_brand.get() == '全ブランド':
        lbl_dl_url.place_forget()
        txt_dl_url_photopri.place_forget()
        txt_dl_url_e1.place_forget()
        txt_dl_url_qoo.place_forget()

    elif mode_brand.get() == 'PHOTOPRI':
        lbl_dl_url.place(x=30, y=240)

        txt_dl_url_photopri.place(x=140, y=240)
        txt_dl_url_e1.place_forget()
        txt_dl_url_qoo.place_forget()
        

    elif mode_brand.get() == 'e1':
        lbl_dl_url.place(x=30, y=240)

        txt_dl_url_photopri.place_forget()
        txt_dl_url_e1.place(x=140, y=240)
        txt_dl_url_qoo.place_forget()
        
    
    elif mode_brand.get() == 'Qoo':
        lbl_dl_url.place(x=30, y=240)

        txt_dl_url_photopri.place_forget()
        txt_dl_url_e1.place_forget()
        txt_dl_url_qoo.place(x=140, y=240)

# モード変更時にUIを更新
mode_brand.trace_add('write', update_brand_ui)

# 選択に応じた表示の切り替え
def update_ui(*args):
    if mode_var.get() == '日時範囲で回収':
        lbl.place(x=30, y=20)
        lbl_num.place_forget()
        lbl_order_number.place_forget()
        frame_order_number.place_forget()
    else:
        lbl.place_forget()
        lbl_num.place(x=30, y=20)
        lbl_start_date.place_forget()
        lbl_start_date.place_forget()
        txt_start_date.place_forget()
        lbl_start_time.place_forget()
        txt_start_time.place_forget()
        lbl_end_date.place_forget()
        txt_end_date.place_forget()
        lbl_end_time.place_forget()
        txt_end_time.place_forget()
        lbl_order_number.place(x=30, y=120)
        frame_order_number.place(x=140, y=120)

# モード変更時にUIを更新
mode_var.trace_add('write', update_ui)

# ボタンを設置
btn = tkinter.Button(root, text='実行', command=btn_click)
btn.place(x=160, y=300)

def init_brand_ui():
    current_mode = mode_brand.get()
    # update_brand_uiと同じ処理

# 初期表示を更新
init_brand_ui()

update_ui()

# 表示
root.mainloop()

# 成功表示
messagebox.showinfo('成功', '完了しました')

sys.exit()

# --tkinterから処理--