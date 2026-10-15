#!/usr/bin/env python3
"""
yt2ig — auto-posts your latest YouTube uploads to Instagram as Reels.

Designed to run on a schedule inside GitHub Actions (free, no server needed).
State (which videos have already been posted) is tracked in state.json,
which the workflow commits back to the repo after each run.

Required environment variables (set these as GitHub Actions secrets):
  YOUTUBE_API_KEY      - YouTube Data API v3 key
  YOUTUBE_CHANNEL_ID   - Your channel's ID (starts with "UC...")
  CLOUDINARY_CLOUD_NAME
  CLOUDINARY_API_KEY
  CLOUDINARY_API_SECRET
  IG_USER_ID           - Your Instagram Business account's numeric user id
  IG_ACCESS_TOKEN      - Long-lived Meta Graph API access token

Optional:
  MAX_VIDEOS_PER_RUN   - default 1 (safety limit so you don't flood IG)
  CAPTION_SUFFIX       - text appended to every caption (e.g. hashtags)
"""

import json
import os
import sys
import time
import pathlib
import requests
import yt_dlp
import cloudinary
import cloudinary.uploader

STATE_FILE = pathlib.Path(__file__).parent / "state.json"
GRAPH_API = "https://graph.facebook.com/v21.0"


def env(name, required=True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        print(f"ERROR: missing required environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return val


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"posted_video_ids": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_uploads_playlist_id(api_key, channel_id):
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "contentDetails", "id": channel_id, "key": api_key},
        timeout=30,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        raise RuntimeError("Channel not found — check YOUTUBE_CHANNEL_ID")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_latest_videos(api_key, playlist_id, max_results=10):
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/playlistItems",
        params={
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": max_results,
            "key": api_key,
        },
        timeout=30,
    )
    r.raise_for_status()
    videos = []
    for item in r.json().get("items", []):
        videos.append(
            {
                "video_id": item["contentDetails"]["videoId"],
                "title": item["snippet"]["title"],
                "description": item["snippet"].get("description", ""),
                "published_at": item["snippet"]["publishedAt"],
            }
        )
    # Oldest first, so if multiple are new we post in upload order
    videos.sort(key=lambda v: v["published_at"])
    return videos


def download_video(video_id, out_dir="downloads"):
    pathlib.Path(out_dir).mkdir(exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_path = str(pathlib.Path(out_dir) / f"{video_id}.mp4")
    ydl_opts = {
        "format": "mp4[height<=1080]/best[ext=mp4]/best",
        "outtmpl": out_path,
        "quiet": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return out_path


def upload_to_cloudinary(file_path, public_id):
    cloudinary.config(
        cloud_name=env("CLOUDINARY_CLOUD_NAME"),
        api_key=env("CLOUDINARY_API_KEY"),
        api_secret=env("CLOUDINARY_API_SECRET"),
    )
    result = cloudinary.uploader.upload_large(
        file_path,
        resource_type="video",
        public_id=public_id,
        folder="yt2ig",
    )
    return result["secure_url"], result["public_id"]


def delete_from_cloudinary(public_id):
    try:
        cloudinary.uploader.destroy(f"yt2ig/{public_id}", resource_type="video")
    except Exception as e:
        print(f"WARNING: could not delete Cloudinary asset {public_id}: {e}")


def build_caption(title, description, suffix):
    caption = title.strip()
    if description.strip():
        caption += "\n\n" + description.strip()[:1500]
    if suffix:
        caption += "\n\n" + suffix
    return caption[:2200]  # Instagram caption limit


def post_reel_to_instagram(ig_user_id, access_token, video_url, caption):
    # Step 1: create a media container
    r = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=60,
    )
    r.raise_for_status()
    creation_id = r.json()["id"]

    # Step 2: poll until the video is finished processing
    status = "IN_PROGRESS"
    attempts = 0
    while status in ("IN_PROGRESS", "PUBLISHED") and attempts < 30:
        time.sleep(10)
        r = requests.get(
            f"{GRAPH_API}/{creation_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        r.raise_for_status()
        status = r.json().get("status_code")
        if status == "FINISHED":
            break
        attempts += 1
    if status != "FINISHED":
        raise RuntimeError(f"Media container never finished processing (status={status})")

    # Step 3: publish
    r = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["id"]


def main():
    api_key = env("YOUTUBE_API_KEY")
    channel_id = env("YOUTUBE_CHANNEL_ID")
    ig_user_id = env("IG_USER_ID")
    ig_token = env("IG_ACCESS_TOKEN")
    max_per_run = int(env("MAX_VIDEOS_PER_RUN", required=False, default="1"))
    caption_suffix = env("CAPTION_SUFFIX", required=False, default="")

    state = load_state()
    posted_ids = set(state["posted_video_ids"])

    playlist_id = get_uploads_playlist_id(api_key, channel_id)
    videos = get_latest_videos(api_key, playlist_id)
    new_videos = [v for v in videos if v["video_id"] not in posted_ids][:max_per_run]

    if not new_videos:
        print("No new videos to post. Up to date.")
        return

    for video in new_videos:
        vid = video["video_id"]
        print(f"Processing {vid} — {video['title']}")
        try:
            local_path = download_video(vid)
            video_url, cloud_public_id = upload_to_cloudinary(local_path, vid)
            caption = build_caption(video["title"], video["description"], caption_suffix)
            media_id = post_reel_to_instagram(ig_user_id, ig_token, video_url, caption)
            print(f"Posted to Instagram as media id {media_id}")

            # Clean up
            delete_from_cloudinary(cloud_public_id)
            pathlib.Path(local_path).unlink(missing_ok=True)

            posted_ids.add(vid)
            state["posted_video_ids"] = list(posted_ids)
            save_state(state)  # save after each success, not just at the end
        except Exception as e:
            print(f"ERROR processing {vid}: {e}", file=sys.stderr)
            # Don't mark as posted — it'll retry next run
            continue


if __name__ == "__main__":
    main()
