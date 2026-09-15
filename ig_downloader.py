#!/usr/bin/env python3
import json
import os
import sys
import zipfile
import subprocess
import argparse
from pathlib import Path


def find_saved_json(extract_dir: Path):
    candidates = [
        "your_instagram_activity/saved/saved_posts.json",
        "saved/saved_posts.json",
        "saved_posts.json",
        "your_instagram_activity/saved/saved_media.json",
        "saved/saved_media.json",
        "saved_media.json",
    ]
    for rel in candidates:
        p = extract_dir / rel
        if p.exists():
            return p
    for root, _, files in os.walk(extract_dir):
        for f in files:
            if f in ("saved_posts.json", "saved_media.json"):
                return Path(root) / f
    return None


def extract_urls(json_path: Path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []
    if isinstance(data, dict):
        items = data.get("saved_saved_media") or data.get("saved_media") or []
    elif isinstance(data, list):
        items = data

    urls = []
    for item in items:
        try:
            href = None
            if isinstance(item.get("label_values"), list):
                for lv in item["label_values"]:
                    if lv.get("label") == "URL" and lv.get("href"):
                        href = lv["href"]
                        break
            if not href and isinstance(item.get("string_map_data"), dict):
                smd = item["string_map_data"]
                href = (
                    smd.get("Saved on", {}).get("href") or
                    smd.get("Href", {}).get("value") or
                    smd.get("href", {}).get("value")
                )
            if href and href.startswith("http"):
                urls.append(href)
        except (KeyError, TypeError):
            pass
    return urls


def get_ytdlp_cmd():
    candidates = [
        ["yt-dlp"],
        [sys.executable, "-m", "yt_dlp"],
    ]
    for cmd in candidates:
        try:
            subprocess.run(cmd + ["--version"], capture_output=True, check=True)
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def download_url(url, output_dir, index, total, ytdlp_cmd):
    print(f"\n[{index}/{total}] Downloading: {url}")
    cmd = ytdlp_cmd + [
        "--output", str(output_dir / "%(upload_date)s_%(id)s.%(ext)s"),
        "--no-playlist",
        "--quiet",
        "--progress",
        url
    ]
    result = subprocess.run(cmd)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path")
    parser.add_argument("--output", "-o", default="ig_saved_downloads")
    args = parser.parse_args()

    zip_path = Path(args.zip_path)
    output_dir = Path(args.output)

    if not zip_path.exists():
        print(f"ERROR: ZIP file not found: {zip_path}")
        sys.exit(1)

    ytdlp_cmd = get_ytdlp_cmd()
    if not ytdlp_cmd:
        print("ERROR: yt-dlp is not installed. Run: pip install yt-dlp")
        sys.exit(1)

    extract_dir = Path("ig_export_extracted")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    json_path = find_saved_json(extract_dir)
    if not json_path:
        print("ERROR: Could not find saved_posts.json in the export.")
        sys.exit(1)

    urls = extract_urls(json_path)
    if not urls:
        print("No saved post URLs found.")
        sys.exit(0)

    print(f"Found {len(urls)} saved post(s).")
    output_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    failed = []
    for i, url in enumerate(urls, 1):
        ok = download_url(url, output_dir, i, len(urls), ytdlp_cmd)
        if ok:
            success += 1
        else:
            failed.append(url)

    print(f"\nDone! {success}/{len(urls)} downloaded.")
    if failed:
        failed_log = output_dir / "failed_urls.txt"
        with open(failed_log, "w") as f:
            f.write("\n".join(failed))


if __name__ == "__main__":
    main()
