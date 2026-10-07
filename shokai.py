# initial_login.py
import time
from playwright.sync_api import sync_playwright

USER_DATA_DIR = "./x_user_data"  # セッション保存用フォルダ

with sync_playwright() as p:
    # persistent context でブラウザを起動
    context = p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=False,  # 手動操作するため画面を表示
        args=["--disable-blink-features=AutomationControlled"] # bot検知回避の基本フラグ
    )
    page = context.new_page()
    page.goto("https://x.com/i/flow/login")
    
    print("ブラウザでXにログインしてください。完了したらEnterを押します...")
    input()
    
    context.close()
    print("ログイン情報を保存しました。")
