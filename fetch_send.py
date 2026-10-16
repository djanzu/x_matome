# fetch_and_notify.py
import argparse
import os
import sys
from datetime import date, timedelta
from urllib.parse import quote
import requests
import yaml
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
# OpenAI 互換 API（vLLM など）を使用。接続先は llm_profiles.yaml で切り替える
from openai import OpenAI

# .env から設定を読み込む（既に環境変数が設定されている場合はそちらを優先）
load_dotenv()

# 設定項目
TARGET_USERNAME = os.environ.get("TARGET_USERNAME", "jack").lstrip("@")  # 取得対象のXユーザーID（@なし）
USER_DATA_DIR = "./x_user_data"
SEND_TO = os.environ.get("SEND_TO", "SLACK").strip().upper()  # 送信先（SLACK または DISCORD）
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
LLM_PROFILES_PATH = "llm_profiles.yaml"
DAYS = 7  # 今日を含めて何日分を取得するか

def get_recent_tweets(username, days=7, max_scrolls=50, max_idle_scrolls=3):
    """X の検索（from: / since: / until:）で、今日を含む直近 days 日分の投稿を取得する"""
    today = date.today()
    since = today - timedelta(days=days - 1)  # 今日を含めて days 日分
    until = today + timedelta(days=1)         # until は指定日を含まないため翌日を指定
    query = f"from:@{username} since:{since.isoformat()} until:{until.isoformat()}"
    # f=live で「最新」タブ（時系列順）を表示
    url = f"https://x.com/search?q={quote(query)}&src=typed_query&f=live"

    tweets = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.new_page()
        page.goto(url)

        # ツイート要素が表示されるまで待機（期間内に投稿がなければ空で返す）
        try:
            page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        except PlaywrightTimeoutError:
            context.close()
            return tweets

        # 新しいツイートが出てこなくなるまでスクロール
        collected = set()
        idle_scrolls = 0
        for _ in range(max_scrolls):
            new_count = 0
            for el in page.query_selector_all('article[data-testid="tweet"]'):
                text_el = el.query_selector('div[data-testid="tweetText"]')
                if not text_el:
                    continue
                text = text_el.inner_text().strip()
                time_el = el.query_selector("time")
                posted_at = time_el.get_attribute("datetime") if time_el else ""
                # 投稿日時＋本文で重複判定（同じ文面の別投稿を潰さないため）
                key = (posted_at, text)
                if text and key not in collected:
                    collected.add(key)
                    tweets.append({"posted_at": posted_at, "text": text})
                    new_count += 1

            idle_scrolls = idle_scrolls + 1 if new_count == 0 else 0
            if idle_scrolls >= max_idle_scrolls:
                break

            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(2000)

        context.close()

    # 古い順に並べる
    tweets.sort(key=lambda t: t["posted_at"])
    return tweets

def load_llm_profile(name=None):
    """llm_profiles.yaml からプロファイルを読み込む（name > 環境変数 LLM_PROFILE > default の順で選ぶ）"""
    with open(LLM_PROFILES_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    profiles = config.get("profiles", {})
    name = name or os.environ.get("LLM_PROFILE") or config.get("default")
    if name not in profiles:
        sys.exit(f"LLM プロファイル '{name}' が {LLM_PROFILES_PATH} にありません（候補: {', '.join(profiles)}）")

    profile = profiles[name]
    api_key_env = profile.get("api_key_env")
    return {
        "name": name,
        "base_url": profile["base_url"],
        "model": profile["model"],
        # api_key_env が未指定、または環境変数が未設定なら "EMPTY"（認証なしの vLLM 向け）
        "api_key": os.environ.get(api_key_env, "EMPTY") if api_key_env else "EMPTY",
        "temperature": profile.get("temperature", 0.5),
    }

def summarize_tweets(tweets, llm):
    client = OpenAI(base_url=llm["base_url"], api_key=llm["api_key"])
    formatted_tweets = "\n---\n".join(
        [f"{i+1}. [{t['posted_at']}] {t['text']}" for i, t in enumerate(tweets)]
    )

    prompt = f"""
以下のツイート（直近{DAYS}日間・{len(tweets)}件）を読み、主要な話題や投稿者の関心事・最新動向を簡潔に要約してください。

【ツイート一覧】
{formatted_tweets}
"""
    response = client.chat.completions.create(
        model=llm["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=llm["temperature"],
    )
    return response.choices[0].message.content

def send_to_slack(summary, username):
    payload = {
        "text": f"🤖 *@{username} の直近{DAYS}日間のツイート要約*\n\n{summary}"
    }
    requests.post(SLACK_WEBHOOK_URL, json=payload)

def send_to_discord(summary, username):
    payload = {
        "content": f"🤖 **@{username} の直近{DAYS}日間のツイート要約**\n\n{summary}"
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload)

def send_summary(summary, username):
    """SEND_TO で指定された送信先に要約を送る"""
    if SEND_TO == "SLACK":
        if not SLACK_WEBHOOK_URL:
            sys.exit("SLACK_WEBHOOK_URL が設定されていません（.env を確認してください）")
        print("3. Slackへ送信中...")
        send_to_slack(summary, username)
    elif SEND_TO == "DISCORD":
        if not DISCORD_WEBHOOK_URL:
            sys.exit("DISCORD_WEBHOOK_URL が設定されていません（.env を確認してください）")
        print("3. Discordへ送信中...")
        send_to_discord(summary, username)
    else:
        sys.exit(f"不明な SEND_TO '{SEND_TO}' です（候補: SLACK, DISCORD）")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="X の投稿を要約して Slack に送る")
    parser.add_argument("--llm", help=f"使う LLM プロファイル名（{LLM_PROFILES_PATH} の profiles のキー）")
    args = parser.parse_args()
    # ツイート取得の前に読み込み、プロファイル名の誤りをすぐ検出する
    llm = load_llm_profile(args.llm)
    print(f"LLM: {llm['name']}（{llm['model']}）")

    print("1. ツイート取得中...")
    tweets = get_recent_tweets(TARGET_USERNAME, days=DAYS)
    
    if not tweets:
        print("ツイートが取得できませんでした。")
        exit(1)
        
    print(f"2. {len(tweets)}件のツイートを要約中...")
    summary = summarize_tweets(tweets, llm)
    
    send_summary(summary, TARGET_USERNAME)
    print("完了しました。")

