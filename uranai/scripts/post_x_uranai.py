"""
X（Twitter）への占い投稿
==========================

main.py から呼ばれる。tweepy で X に投稿。
.env から認証情報読込：X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET
"""
from __future__ import annotations
import os
from datetime import date

import tweepy

from caption import make_x_caption


def post_x_uranai(*, weekday_key: str, data: dict, spot, target_date: date,
                   post_url: str, dry: bool = False) -> dict:
    """X に投稿
    Returns: {"status": "ok"/"dry"/"error", "tweet_id": str|None, "url": str|None, "caption": str}
    """
    caption = make_x_caption(weekday_key, data, spot, target_date, post_url)

    if dry:
        return {"status": "dry", "tweet_id": None, "url": None, "caption": caption}

    try:
        client = tweepy.Client(
            consumer_key=os.getenv("X_API_KEY"),
            consumer_secret=os.getenv("X_API_SECRET"),
            access_token=os.getenv("X_ACCESS_TOKEN"),
            access_token_secret=os.getenv("X_ACCESS_SECRET"),
        )
        response = client.create_tweet(text=caption)
        tweet_id = str(response.data["id"])
        return {
            "status": "ok",
            "tweet_id": tweet_id,
            "url": f"https://x.com/toyokawaguide/status/{tweet_id}",
            "caption": caption,
        }
    except Exception as e:
        return {"status": "error", "tweet_id": None, "url": None, "caption": caption, "error": str(e)}
