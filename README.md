# yt2ig — auto-post your YouTube uploads to Instagram Reels

Runs entirely for free on GitHub Actions. No server, no laptop, no hosting bill.
Checks your channel hourly, and posts any new upload to Instagram as a Reel.

## How it works
1. GitHub Actions wakes up on a schedule (free, built into GitHub).
2. It checks your YouTube channel for uploads it hasn't posted yet (tracked in `state.json`).
3. Downloads the video, pushes it to Cloudinary (free tier) just long enough to get
   a public URL — Instagram's API requires a URL, not a direct file upload.
4. Posts it to Instagram as a Reel via the Graph API, then deletes the Cloudinary copy.

## One-time setup (about 20–30 minutes)

### 1. Create the GitHub repo
- Create a new **private** repo on GitHub.
- Upload all these files (`sync.py`, `requirements.txt`, `state.json`,
  `.github/workflows/sync.yml`, this README) to it.

### 2. Get a YouTube Data API key
- Go to [Google Cloud Console](https://console.cloud.google.com/).
- Create a project → enable **YouTube Data API v3** → create an API key.
- Find your channel ID: on your channel page → Settings → Advanced, or via
  https://www.youtube.com/account_advanced.

### 3. Create a free Cloudinary account
- Sign up at cloudinary.com (free tier is generous — way more than you'll need).
- From your dashboard, grab: Cloud name, API key, API secret.

### 4. Set up Instagram API access
Since your Instagram Business account is already linked to a Facebook Page, you need:
- A Meta Developer app: go to [developers.facebook.com](https://developers.facebook.com/) → My Apps → Create App → type "Business".
- Add the **Instagram Graph API** product to it.
- Under App Roles, add yourself as an **Admin/Tester** — this lets you use the API
  on your own account without needing Meta's public app review process.
- Use the Graph API Explorer (or OAuth flow) to generate a **long-lived User
  Access Token** with `instagram_basic`, `instagram_content_publish`, and
  `pages_show_list` permissions.
- Find your Instagram **user id** (the Business Account id, a numeric string) using
  the Graph API Explorer: `GET /me/accounts` → then `GET /{page-id}?fields=instagram_business_account`.
- Note: long-lived tokens expire after ~60 days. You'll need to refresh it
  periodically (there's a Graph API call for that — ask me later and I'll add
  an auto-refresh step).

### 5. Add your secrets to GitHub
In your repo: Settings → Secrets and variables → Actions → New repository secret.
Add each of these:
- `YOUTUBE_API_KEY`
- `YOUTUBE_CHANNEL_ID`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `IG_USER_ID`
- `IG_ACCESS_TOKEN`

### 6. Turn it on
- Go to the **Actions** tab of your repo → enable workflows if prompted.
- That's it — it'll run every hour automatically from now on.

## Using it from your phone
- Install the free **GitHub Mobile** app and sign in.
- Open your repo → Actions tab → you'll see every run, and can tap
  **"Run workflow"** to trigger a check manually any time.
- You'll also get a push notification if a run fails.

## Adjusting behavior
- Change how often it checks: edit the `cron` line in `.github/workflows/sync.yml`
  (currently every hour).
- Change how many videos post per run: edit `MAX_VIDEOS_PER_RUN` in the same file.
- Add standard hashtags to every post: set `CAPTION_SUFFIX` in the same file.

## Safety notes
- `MAX_VIDEOS_PER_RUN` defaults to 1 so a backlog of old videos won't flood
  your Instagram all at once the first time you run it.
- If you want to *backfill* nothing (only post videos uploaded from now on),
  run the script once manually first and let it mark your existing videos as
  "posted" without actually posting — ask me and I'll add a `--mark-only` flag.
