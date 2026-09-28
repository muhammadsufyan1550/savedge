# Savedge

A public web application for bulk-downloading Instagram saved posts and reels directly from an official Meta data export ZIP.

No Instagram credentials, passwords, or cookies required.

---

## Features

- **100% Safe & Private**: No Instagram login required. Downloads run strictly off public CDN links contained in your personal data export.
- **Fast & Responsive**: Real-time download progress streamed via Server-Sent Events (SSE) with fallback polling.
- **High Quality**: Leverages `yt-dlp` and `ffmpeg` to retrieve the highest available resolution for photos, reels, and video carousels.
- **One-Click Packaging**: Automatically packages all media into a single `savedge_<id>.zip` archive.
- **Optimized for Render.com Free Tier**:
  - Ephemeral storage cleanup cleans raw files immediately after ZIP generation.
  - Background sweeper cleans sessions older than 30 minutes.
  - Stream-to-disk upload handler with a 500 MB limit.
- **Apple Dark Mode Aesthetic**: Clean, responsive UI with drag-and-drop, progress animation, and status feedback.
- **Monetization-Ready**: Built-in Google AdSense slots (728×90 leaderboard & 300×250 medium rectangle) and Buy Me a Coffee integration.

---

## How to Get Your Instagram Export

1. Open Instagram on your mobile device or web browser.
2. Go to **Settings &gt; Accounts Center &gt; Your information and permissions &gt; Download your information**.
3. Choose **Download or transfer information**.
4. Select your Instagram profile.
5. Select **Some of your information** and scroll down to check **Saved posts**.
6. Set the Format to **JSON** (do not select HTML) and choose your date range (e.g., "All time").
7. Click **Create files**. Meta will email you when the download is ready (usually 5–15 minutes).
8. Download the `.zip` export file from Instagram and upload it to Savedge!

---

## Project Structure

```
savedge/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI application & API endpoints
│   ├── session.py         # Thread-safe session & storage manager
│   ├── downloader.py      # Core parser & yt-dlp download pipeline
│   └── static/
│       └── index.html     # Single-page frontend application
├── ig_downloader.py       # Standalone CLI reference script
├── requirements.txt       # Production dependencies
├── Dockerfile             # Container definition with ffmpeg
├── render.yaml            # Render Blueprint deployment specification
└── README.md
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/` | Serves the single-page application |
| `GET`  | `/healthz` | Health check endpoint for container orchestrators |
| `POST` | `/upload` | Accepts export ZIP (up to 500 MB), initializes worker |
| `GET`  | `/progress/{session_id}` | Real-time SSE progress stream |
| `GET`  | `/status/{session_id}` | JSON state polling endpoint (fallback for SSE) |
| `GET`  | `/download/{session_id}` | Streams the completed `.zip` file |

---

## Local Development

### 1. Prerequisites
- Python 3.10+ (or [uv](https://github.com/astral-sh/uv))
- `ffmpeg` (optional, for merging video formats)

### 2. Setup
```bash
# Clone the repository
git clone https://github.com/muhammadsufyan1550/savedge.git
cd savedge

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the App
```bash
uvicorn app.main:app --reload --port 10000
```
Open your browser at `http://localhost:10000`.

---

## Running with Docker

```bash
docker build -t savedge .
docker run -p 10000:10000 savedge
```

---

## Deploying to Render.com

1. Push your repository to GitHub or GitLab.
2. Sign in to [Render.com](https://render.com).
3. Click **New +** &gt; **Blueprint** and connect your repository.
4. Render will detect `render.yaml` and configure the web service automatically on the Free tier.
5. Once deployed, your site will be live at `https://savedge.onrender.com` (or your chosen URL).

---
0

Replace `data-ad-client="ca-pub-XXXXXXXXXXXXXXXX"` and `data-ad-slot="XXXXXXXXXX"` with your verified AdSense publisher code once approved.

---

## License

MIT License. Not affiliated with Meta or Instagram.
