import os
import csv
import requests
from datetime import date

INSTAGRAM_ACCOUNT_ID = "17841467629335560"
FACEBOOK_PAGE_ID = "769724519560545"
ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"]
IMAGES_BASE_URL = "https://toyokawaguide.github.io/toyokawa-sns/images"

GRAPH_API = "https://graph.facebook.com/v18.0"


def post_feed(caption, image_filename):
    image_url = f"{IMAGES_BASE_URL}/{image_filename}"
    # Step1: メディアコンテナ作成
    res = requests.post(
        f"{GRAPH_API}/{INSTAGRAM_ACCOUNT_ID}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": ACCESS_TOKEN,
        },
    )
    res.raise_for_status()
    container_id = res.json()["id"]

    # Step2: 公開
    res = requests.post(
        f"{GRAPH_API}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
        data={"creation_id": container_id, "access_token": ACCESS_TOKEN},
    )
    res.raise_for_status()
    print(f"[feed] 投稿完了: {res.json()}")


def post_reel(caption, video_filename):
    video_url = f"{IMAGES_BASE_URL}/{video_filename}"
    # Step1: リールコンテナ作成
    res = requests.post(
        f"{GRAPH_API}/{INSTAGRAM_ACCOUNT_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": ACCESS_TOKEN,
        },
    )
    res.raise_for_status()
    container_id = res.json()["id"]

    # Step2: 公開
    res = requests.post(
        f"{GRAPH_API}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
        data={"creation_id": container_id, "access_token": ACCESS_TOKEN},
    )
    res.raise_for_status()
    print(f"[reel] 投稿完了: {res.json()}")


def post_story(image_filename):
    image_url = f"{IMAGES_BASE_URL}/{image_filename}"
    # Step1: ストーリーコンテナ作成
    res = requests.post(
        f"{GRAPH_API}/{INSTAGRAM_ACCOUNT_ID}/media",
        data={
            "media_type": "STORIES",
            "image_url": image_url,
            "access_token": ACCESS_TOKEN,
        },
    )
    res.raise_for_status()
    container_id = res.json()["id"]

    # Step2: 公開
    res = requests.post(
        f"{GRAPH_API}/{INSTAGRAM_ACCOUNT_ID}/media_publish",
        data={"creation_id": container_id, "access_token": ACCESS_TOKEN},
    )
    res.raise_for_status()
    print(f"[story] 投稿完了: {res.json()}")


def main():
    today = date.today().strftime("%Y-%m-%d")
    print(f"実行日: {today}")

    with open("schedule.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["date"] != today:
                continue

            print(f"本日の投稿: 問{row['question_no']} {row['place_name']}")
            post_feed(row["caption_instagram"], row["feed_image"])
            post_reel(row["caption_instagram"], row["reel_video"])
            post_story(row["story_image"])
            print("全フォーマット投稿完了")
            return

    print("本日の投稿はありません")


if __name__ == "__main__":
    main()
