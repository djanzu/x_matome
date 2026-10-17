# workdb.py
# SQLite による作業状態の保存・再開を担う小さなモジュール。
#
# fetch_send.py の処理途中でエラーが起きても、次回実行時に
# 前回の終了状態から再開できるよう、進行中の内容を SQLite に保存する。
# 工程が失敗なく完了するたび、消費済みのデータを逐次削除し、
# すべての工程が完了したら作業ファイル自体を削除する。
import os
import sqlite3

DB_PATH = os.environ.get("WORK_DB_PATH", "work.sqlite")


def connect(path=DB_PATH):
    """DB を開き、必要なテーブルを用意する。"""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tweets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posted_at TEXT NOT NULL,
            text TEXT NOT NULL,
            done_flg INTEGER NOT NULL DEFAULT 0   -- 0=false, 1=true
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS llm_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            response TEXT NOT NULL,
            sent_flg INTEGER NOT NULL DEFAULT 0   -- 0=false, 1=true
        )"""
    )
    conn.commit()
    return conn


def save_tweets(conn, tweets):
    """ツイートを tweets へ保存する（done_flg=false）。

    前回の残骸があれば入れ替える。
    """
    conn.execute("DELETE FROM tweets")
    conn.executemany(
        "INSERT INTO tweets (posted_at, text, done_flg) VALUES (?, ?, 0)",
        [(t["posted_at"], t["text"]) for t in tweets],
    )
    conn.commit()


def get_tweets(conn):
    """保存済みのツイートを古い順に返す（posted_at, text）。"""
    return conn.execute(
        "SELECT posted_at, text FROM tweets ORDER BY posted_at"
    ).fetchall()


def tweets_exist(conn):
    """tweets に 1 件でも保存されているか（＝ツイート取得済み）。"""
    return conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0] > 0


def get_unsent_response(conn):
    """まだ送信していない LLM の返答（sent_flg=false）を返す。なければ None。"""
    return conn.execute(
        "SELECT id, response FROM llm_responses WHERE sent_flg = 0 ORDER BY id LIMIT 1"
    ).fetchone()


def sent_response_exists(conn):
    """送信済みの返答（sent_flg=true）が残っているか。"""
    return conn.execute("SELECT COUNT(*) FROM llm_responses WHERE sent_flg = 1").fetchone()[0] > 0


def finalize_llm_step(conn, response):
    """LLM 工程の完了を一つのトランザクションで確定する。

    - LLM の返答を llm_responses へ保存（sent_flg=false）
    - tweets の done_flg を true にする
    - 消費済みのツイートを削除（逐次削除）

    途中で失敗した場合はロールバックされ、再開時に要約工程からやり直せる。
    """
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO llm_responses (response, sent_flg) VALUES (?, 0)",
        (response,),
    )
    cur.execute("UPDATE tweets SET done_flg = 1")
    cur.execute("DELETE FROM tweets")
    conn.commit()


def finalize_send(conn, rid):
    """送信工程の完了を一つのトランザクションで確定する。

    - 該当する llm_responses の sent_flg を true にする
    - 消費済みの返答を削除（逐次削除）
    """
    cur = conn.cursor()
    cur.execute("UPDATE llm_responses SET sent_flg = 1 WHERE id = ?", (rid,))
    cur.execute("DELETE FROM llm_responses WHERE id = ?", (rid,))
    conn.commit()


def remove_file(path=DB_PATH):
    """作業ファイルを削除する（全工程が完了したとき・不要になったとき）。"""
    if os.path.exists(path):
        os.remove(path)
