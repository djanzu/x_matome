# x_matome

指定した X（旧 Twitter）ユーザーの直近 7 日間の投稿を取得し、LLM で要約して Slack または Discord に送るスクリプトです。

1. Playwright でブラウザを操作し、X の検索（`from:` / `since:` / `until:`）から投稿を集める
2. vLLM などの OpenAI 互換 API で投稿を要約する
3. 要約を Slack / Discord の Incoming Webhook に送る（送信先は `SEND_TO` で指定）

## 必要なもの

- Python 3
- X のアカウント（検索結果を見るためにログインが必要）
- OpenAI 互換 API のエンドポイント（vLLM など）
- Slack の Incoming Webhook URL

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```


### 設定ファイル

`.env.example` をコピーして `.env` を作り、値を書き換えます。

```bash
cp .env.example .env
```

| 変数名 | 内容 | 既定値 |
| --- | --- | --- |
| `TARGET_USERNAME` | 取得対象の X ユーザー ID（`@` なし） | `jack` |
| `SEND_TO` | 要約の送信先（`SLACK` または `DISCORD`） | `SLACK` |
| `SLACK_WEBHOOK_URL` | Slack の Incoming Webhook URL（`SEND_TO=SLACK` のとき必須） | なし |
| `DISCORD_WEBHOOK_URL` | Discord の Webhook URL（`SEND_TO=DISCORD` のとき必須） | なし |
| `LLM_PROFILE` | 使う LLM プロファイル名（下記参照） | `llm_profiles.yaml` の `default` |
| `VLLM_API_KEY` など | LLM の API キー。変数名は `llm_profiles.yaml` の `api_key_env` で指定する | `EMPTY` |

すでに環境変数が設定されている場合は、`.env` よりそちらが優先されます。

### LLM の切り替え

要約に使う LLM（OpenAI 互換 API）の接続先は [llm_profiles.yaml](llm_profiles.yaml) に名前付きで登録します。API キーはこのファイルに書かず、`.env` に置いた変数の名前を `api_key_env` で指定します。

```yaml
default: suisei2

profiles:
  suisei2:
    base_url: http://192.168.2.131:8888/v1
    model: qwen3.8-flash-next
    api_key_env: VLLM_API_KEY
    temperature: 0.5   # 省略時は 0.5
```

使うプロファイルは次の優先順で決まります。

1. 実行時の `--llm` オプション
2. 環境変数 `LLM_PROFILE`（`.env` に書いてもよい）
3. `llm_profiles.yaml` の `default`

`api_key_env` を省略した場合や、指定した環境変数が設定されていない場合は、API キーとして `EMPTY` を使います。

### X へのログイン（初回のみ）

**venvを有効化するのを忘れないでください。**


```bash
python shokai.py
```

ブラウザが起動するので、X にログインしてください。ログインが終わったらターミナルで Enter を押します。ログイン情報は `x_user_data/` に保存され、以降の実行で使われます。

## 使い方

```bash
python fetch_send.py

# その回だけ別の LLM を使う
python fetch_send.py --llm openai
```

実行すると、次の順に処理が進みます。

1. 対象ユーザーの直近 7 日分（今日を含む）の投稿を取得する
2. 取得した投稿を LLM で要約する
3. 要約を `SEND_TO` で指定した送信先（Slack / Discord）に送る

期間内に投稿がない場合や取得に失敗した場合は、「ツイートが取得できませんでした。」と表示して終了します（終了コード 1）。

取得する日数は [fetch_send.py](fetch_send.py) の `DAYS` で変えられます。

### 途中でエラーが起きたとき（再開）

処理の途中でエラーが発生しても、作業状態を SQLite（`work.sqlite`）に保存しているため、次に `fetch_send.py` を実行すると**前回異常終了した直前の工程から再開**します。実行時の進行は次のようになります。

```
ツイートを取得
  ↓
ツイートを table tweets へ保存（done_flg=false）
  ↓
LLM に送信
  ↓
LLM の返答を table llm_responses へ保存（sent_flg=false）、table tweets の done_flg=true
  ↓
Slack / Discord に送信
  ↓
table llm_responses の該当データの sent_flg=true
```

各工程が**失敗なく完了するたびに、消費済みのデータを逐次削除**し、全工程が完了したら作業ファイル自体を削除します。保存される内容は次のとおりです。

| 保存内容 | フラグ | 削除タイミング |
| --- | --- | --- |
| `tweets` テーブル（取得した投稿） | `done_flg` | LLM 要約が完了したら削除 |
| `llm_responses` テーブル（要約結果） | `sent_flg` | 送信が完了したら削除 |
| `work.sqlite`（作業ファイル） | - | 全工程が完了したら削除 |

再開の例：

- 取得後にエラー → 次回は「ツイート取得済み・未要約」の状態から、**要約工程から再開**（取得はやり直さない）
- 要約後にエラー → 次回は「要約済み・未送信」の状態から、**送信工程から再開**（取得・要約はやり直さない）
- 送信失敗 → `sent_flg` は false のまま残るので、次回に**再送**される

作業ファイルの保存先は環境変数 `WORK_DB_PATH` で変更できます（省略時は `work.sqlite`）。

## ファイル構成

| ファイル | 役割 |
| --- | --- |
| `shokai.py` | 初回ログイン用。ブラウザを開いてログイン情報を保存する |
| `fetch_send.py` | 投稿の取得・要約・送信先への送信を行う |
| `workdb.py` | 作業状態を SQLite に保存・再開する（`tweets` / `llm_responses` テーブル） |
| `llm_profiles.yaml` | 要約に使う LLM の接続先一覧 |
| `.env.example` | 設定ファイルのひな形 |
| `requirements.txt` | 依存パッケージ |

## 注意

- `x_user_data/` と `.env` にはログイン情報や Webhook URL が含まれます。`.gitignore` で除外していますが、共有しないよう注意してください。
- `work.sqlite` には取得したツイートや要約文が含まれます。`.gitignore` で除外していますが、共有しないよう注意してください。
- X の画面構成が変わると、投稿を取得できなくなることがあります。
- ログインの有効期限が切れたら、もう一度 `shokai.py` を実行してください。
