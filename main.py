import os
import subprocess
import feedparser
import requests

RSS_URL = "https://subsplease.org/rss/?r=1080"
VK_ACCESS_TOKEN = os.getenv("VK_ACCESS_TOKEN")
VK_GROUP_ID = os.getenv("VK_GROUP_ID")

def check_rss():
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        return None
    latest = feed.entries[0]
    return {"title": latest.title, "link": latest.link}

def fetch_kitsu_poster(anime_title, slug):
    search_url = f"https://kitsu.io/api/edge/anime?filter[text]={anime_title}"
    headers = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
    res = requests.get(search_url, headers=headers)
    if res.status_code == 200 and res.json()["data"]:
        poster_url = res.json()["data"][0]["attributes"]["posterImage"]["original"]
        img_res = requests.get(poster_url)
        if img_res.status_code == 200:
            os.makedirs("posters", exist_ok=True)
            poster_path = f"posters/{slug}.jpg"
            with open(poster_path, "wb") as f:
                f.write(img_res.content)
            return poster_path
    return None

def upload_video_to_vk(video_path, title):
    url = "https://api.vk.com/method/video.save"
    params = {
        'access_token': VK_ACCESS_TOKEN,
        'v': '5.131',
        'group_id': VK_GROUP_ID,
        'name': title,
        'description': 'Uploaded via automated pipeline',
        'wallpost': 0
