#!/bin/bash
# このファイルは DontTouch フォルダの中に配置して使用すること。
# SCRIPT_DIR はこのスクリプト自身が置かれているフォルダ(=DontTouch)を指すため、
# PCごとにパスを書き換える必要がない。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$SCRIPT_DIR" --kiosk-printing --start-maximized
