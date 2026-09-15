import json
from pathlib import Path
import pytest
from app.downloader import extract_urls, find_saved_json


def test_find_saved_json(tmp_path: Path):
    sub = tmp_path / "your_instagram_activity" / "saved"
    sub.mkdir(parents=True)
    target = sub / "saved_posts.json"
    target.write_text("{}", encoding="utf-8")

    found = find_saved_json(tmp_path)
    assert found == target


def test_find_saved_media_nested(tmp_path: Path):
    nested = tmp_path / "some_folder" / "deep"
    nested.mkdir(parents=True)
    target = nested / "saved_media.json"
    target.write_text("{}", encoding="utf-8")

    found = find_saved_json(tmp_path)
    assert found == target


def test_extract_urls_string_map_data(tmp_path: Path):
    data = {
        "saved_saved_media": [
            {
                "title": "Post 1",
                "string_map_data": {
                    "Saved on": {
                        "href": "https://www.instagram.com/p/ABC12345/",
                        "timestamp": 1600000000
                    }
                }
            },
            {
                "title": "Post 2",
                "string_map_data": {
                    "href": {
                        "value": "https://www.instagram.com/reel/XYZ7890/"
                    }
                }
            }
        ]
    }
    json_path = tmp_path / "saved_posts.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    urls = extract_urls(json_path)
    assert urls == [
        "https://www.instagram.com/p/ABC12345/",
        "https://www.instagram.com/reel/XYZ7890/",
    ]


def test_extract_urls_label_values(tmp_path: Path):
    data = [
        {
            "label_values": [
                {"label": "Account", "value": "testuser"},
                {"label": "URL", "href": "https://www.instagram.com/p/DEF456/"}
            ]
        }
    ]
    json_path = tmp_path / "saved_posts.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    urls = extract_urls(json_path)
    assert urls == ["https://www.instagram.com/p/DEF456/"]
