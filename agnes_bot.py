import os
import requests
import json
import asyncio
import time
import sys
import re
import subprocess
from datetime import datetime
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import PIL.Image
import numpy as np

# ============================
# MOVIEPY & PILLOW COMPATIBILITY FIX
# ============================
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

# Configure MoviePy to use ImageMagick via environment variable
if os.name == 'nt':  # Windows
    os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
elif os.path.exists("/opt/homebrew/bin/magick"):  # macOS (Homebrew)
    os.environ["IMAGEMAGICK_BINARY"] = "/opt/homebrew/bin/magick"
else:  # Linux (GitHub Actions)
    os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

from moviepy.editor import *
from moviepy.video.VideoClip import ColorClip

load_dotenv()

# ============================
# CONFIGURATION
# ============================

# AGNES API
AGNES_API_KEY = "sk-195A0vuQ61x3pGK6bAjdaWzjrZc5hJHNUls2ANYIt6PypwPT"
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"

# BUFFER API
BUFFER_API_KEY = os.getenv("BUFFER_API_KEY") or os.getenv("BUFFER_ACCESS_TOKEN") or "2ZUR6pZhjVC3CDsSGy3lQBBLn3LmZ61d7-e_KgqjSfM"
BUFFER_URL = "https://api.buffer.com"

# Load profile IDs
BUFFER_PROFILES = []
env_profiles = os.getenv("BUFFER_PROFILE_IDS")
if env_profiles:
    BUFFER_PROFILES = [pid.strip() for pid in env_profiles.split(",") if pid.strip()]
    print(f"📋 Loaded profiles from Env: {BUFFER_PROFILES}")

if len(BUFFER_PROFILES) < 3:
    # Always include all three unless fully specified in environment
    BUFFER_PROFILES = [
        "6a53866180cc80cdcaa5f066", # Instagram
        "6a522ee0404834462894dfbf", # TikTok
        "6a5380ff80cc80cdcaa5d2bf"  # Facebook
    ]
    print(f"📋 Standardizing on all 3 profiles: {BUFFER_PROFILES}")

# GOOGLE SHEETS
SPREADSHEET_ID = "1dLZKzpnVrJp8HVGo6x5FoJw3Sk5K0wPxX-aQ5F5PrBI"
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT", "service_account.json")

# R2 (For hosting generated videos for Buffer)
R2_BUCKET = "my-video-assets"
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "https://pub-2c8f5c70aa494b5ebd42c9e0a87b930b.r2.dev")

# LOGO
LOGO_PATH = "logo.png"

HASHTAGS = "#kenyantiktok🇰🇪 #creatorsearchinsights #smallbusiness #terekiosk #inventorymanagement #tere #fypppppppppppppppppppppppp #pos #trend"
PLAYSTORE_LINK = "https://play.google.com/store/apps/details?id=com.Tere"

# ============================
# GOOGLE SHEETS LOGIC
# ============================

def get_data_from_sheet2():
    try:
        env_creds = os.getenv("GOOGLE_CREDS_JSON")
        if env_creds:
            creds_dict = json.loads(env_creds)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
        elif os.path.exists(SERVICE_ACCOUNT_FILE):
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
            client = gspread.authorize(creds)
        elif os.path.exists("client_secrets.json"):
            client = gspread.oauth(
                credentials_filename='client_secrets.json',
                authorized_user_filename='temp/authorized_user.json'
            )
        else:
            print("❌ No Google credentials found.")
            return None, []
        
        sheet = client.open_by_key(SPREADSHEET_ID).get_worksheet(1)
        return sheet, sheet.get_all_records()
    except Exception as e:
        print(f"❌ Error reading Sheet 2: {e}")
        return None, []

def update_row_status(sheet_instance, idx, row, status_text):
    """Mark a row with a specific status in the Google Sheet"""
    try:
        headers = [h.lower() for h in row.keys()]
        if 'status' in headers:
            status_col = headers.index('status') + 1
        else:
            status_col = len(headers) + 1
            if idx == 1:
                sheet_instance.update_cell(1, status_col, "Status")
        
        sheet_instance.update_cell(idx + 1, status_col, status_text)
        print(f"✅ Row {idx} marked as '{status_text}' in Sheet 2.")
    except Exception as e:
        print(f"⚠️ Failed to update sheet status: {e}")

# ============================
# AGNES AI LOGIC
# ============================

def find_video_url_recursive(data):
    """Deeply search for any .mp4 URL in the response data"""
    if isinstance(data, str) and (data.startswith("http") and ".mp4" in data):
        return data
    if isinstance(data, dict):
        # Specific check for known nested fields
        for key in ["video_url", "url", "output", "data"]:
            val = data.get(key)
            if val:
                found = find_video_url_recursive(val)
                if found: return found
        # Fallback loop
        for k, v in data.items():
            found = find_video_url_recursive(v)
            if found: return found
    if isinstance(data, list):
        for item in data:
            found = find_video_url_recursive(item)
            if found: return found
    return None

def generate_agnes_video(prompt):
    """Submit task to Agnes AI and poll for result"""
    print(f"🎨 Submitting video task to Agnes AI...")
    headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "agnes-video-v2.0",
        "prompt": prompt,
        "aspect_ratio": "9:16"
    }
    
    try:
        response = requests.post(f"{AGNES_BASE_URL}/videos", json=payload, headers=headers)
        if response.status_code != 200:
            resp_text = response.text
            print(f"❌ Agnes Task Submission Failed: {resp_text}")
            if "content_policy_violation" in resp_text:
                return "ERROR_POLICY"
            if "rate_limit_exceeded" in resp_text:
                return "ERROR_RATE_LIMIT"
            return "ERROR_SUBMISSION"
        
        video_id = response.json().get("video_id")
        print(f"⏳ Task submitted! Video ID: {video_id}. Polling for result...")
        
        # Polling loop (max 15 minutes)
        max_retries = 90 
        for i in range(max_retries):
            time.sleep(10)
            poll_url = f"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}"
            res = requests.get(poll_url, headers=headers)
            
            if res.status_code == 200:
                data = res.json()
                status = (data.get("status") or data.get("internal_status") or "").lower()
                
                if status == "completed" or data.get("progress") == 100:
                    video_url = find_video_url_recursive(data)
                    
                    if video_url:
                        print(f"✅ Video ready: {video_url}")
                        return video_url
                    else:
                        print(f"⚠️ Status completed but URL missing. Full response keys: {list(data.keys())}")
                        return None
                elif status == "failed":
                    print(f"❌ Agnes Generation Failed: {data.get('error') or data.get('message')}")
                    return None
                else:
                    if i % 3 == 0:
                        print(f"⏳ Status: {status} ({i*10}s elapsed)...")
            else:
                print(f"⚠️ Polling error {res.status_code}: {res.text}")
                
        print("❌ Polling timed out.")
        return None
    except Exception as e:
        print(f"❌ Agnes API Exception: {e}")
        return None

# ============================
# VIDEO PROCESSING
# ============================

def add_overlays_and_outro(input_video_path, caption_text, index):
    output_path = f"temp/agnes_final_{index}.mp4"
    print("🎬 Adding subtitles and outro to Agnes video...")
    
    try:
        video = VideoFileClip(input_video_path)
        
        # Subtitles
        chunks = []
        words = caption_text.split()
        chunk = []
        for word in words:
            chunk.append(word)
            if len(' '.join(chunk)) > 25:
                chunks.append(' '.join(chunk))
                chunk = []
        if chunk: chunks.append(' '.join(chunk))
        subtitle_text = '\n'.join(chunks)
        
        font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
        if not os.path.exists(font_path): font_path = "Arial"
            
        text_clip = TextClip(
            subtitle_text,
            fontsize=42,
            color='white',
            font=font_path,
            method='caption',
            size=(video.w * 0.9, None),
            align='center'
        ).set_position(('center', 0.70), relative=True).set_duration(video.duration)
        
        main_video = CompositeVideoClip([video, text_clip])

        # Outro
        outro_duration = 3
        background = ColorClip(size=(video.w, video.h), color=(26, 26, 46)).set_duration(outro_duration)
        
        # Ensure logo is available
        current_logo_path = LOGO_PATH
        if not os.path.exists(current_logo_path):
            print(f"📥 Logo not found locally. Using placeholder.")

        if os.path.exists(current_logo_path):
            logo_clip = ImageClip(current_logo_path).resize(width=video.w * 0.6).set_duration(outro_duration).set_position('center')
            download_text = TextClip("Download Now", fontsize=60, color='white', font=font_path).set_duration(outro_duration).set_position(('center', 0.8), relative=True)
            outro = CompositeVideoClip([background, logo_clip, download_text])
        else:
            download_text = TextClip("TERE KIOSK\nDownload Now", fontsize=70, color='white', font=font_path).set_duration(outro_duration).set_position('center')
            outro = CompositeVideoClip([background, download_text])

        final = concatenate_videoclips([main_video, outro], method="compose")
        final.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", logger=None)
        return output_path
    except Exception as e:
        print(f"❌ Video processing error: {e}")
        return None

# ============================
# BUFFER & R2
# ============================

def upload_to_r2(local_path):
    filename = os.path.basename(local_path)
    cmd = ["rclone", "copy", local_path, f"r2:{R2_BUCKET}/"]
    print(f"📤 Uploading {filename} to R2...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    return f"{R2_PUBLIC_BASE_URL}/{filename}" if result.returncode == 0 else None

def post_to_buffer(video_url, caption):
    headers = {"Authorization": f"Bearer {BUFFER_API_KEY}", "Content-Type": "application/json"}
    mutation = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id } }
        ... on MutationError { message }
      }
    }
    """
    
    success_count = 0
    for profile_id in BUFFER_PROFILES:
        metadata = {}
        if profile_id == "6a53866180cc80cdcaa5f066": # Instagram
            metadata = {"instagram": {"type": "reel", "shouldShareToFeed": True}}
        elif profile_id == "6a5380ff80cc80cdcaa5d2bf": # Facebook
            metadata = {"facebook": {"type": "post"}}

        variables = {
            "input": {
                "text": f"{caption}\n\n{HASHTAGS}\n\n📱 Download: {PLAYSTORE_LINK}",
                "channelId": profile_id,
                "schedulingType": "automatic",
                "mode": "addToQueue",
                "assets": [{"video": {"url": video_url}}],
                "metadata": metadata
            }
        }
        res = requests.post(BUFFER_URL, json={'query': mutation, 'variables': variables}, headers=headers)
        if res.status_code == 200 and "post" in res.json().get('data', {}).get('createPost', {}):
            print(f"✅ Posted to {profile_id}")
            success_count += 1
        else:
            print(f"❌ Failed to post to {profile_id}")
    return success_count > 0

# ============================
# MAIN
# ============================

def main():
    print("🚀 Agnes AI Video Bot Initialized")
    os.makedirs("temp", exist_ok=True)
    
    # Configure ImageMagick for Cloud
    if os.name != 'nt':
        if os.path.exists("/usr/bin/magick"):
            os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/magick"
        elif os.path.exists("/usr/bin/convert"):
            os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

    sheet_instance, records = get_data_from_sheet2()
    if not records: return

    policy_violation_count = 0
    max_policy_violations = 3

    for idx, row in enumerate(records, 1):
        status = (row.get('Status') or row.get('status') or '').strip().lower()
        if status in ['posted', 'failed: policy']: continue
        
        prompt = (row.get('Full AI Video Prompt (10 sec)') or row.get('VideoPrompt') or '').strip()
        if not prompt: continue
        
        print(f"\n🎬 Processing Row {idx} from Sheet 2...")
        
        # 1. Agnes Generation
        video_url = generate_agnes_video(prompt)
        
        if video_url == "ERROR_POLICY":
            update_row_status(sheet_instance, idx, row, "Failed: Policy")
            policy_violation_count += 1
            if policy_violation_count >= max_policy_violations:
                print(f"🛑 Reached limit of {max_policy_violations} policy violations. Stopping to prevent account flag.")
                return
            print("⚠️ Moving to next row due to policy violation.")
            continue # TRY NEXT ROW
        
        if video_url == "ERROR_RATE_LIMIT":
            print("⏳ Rate limit hit. Exiting to retry tomorrow.")
            return 
            
        if not video_url or video_url == "ERROR_SUBMISSION":
            print(f"❌ Submission failed for row {idx}. Trying next row...")
            continue # Try next row instead of exiting completely

        # 2. Download and Process
        temp_input = f"temp/agnes_raw_{idx}.mp4"
        try:
            r = requests.get(video_url, stream=True, timeout=60)
            with open(temp_input, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        except Exception as e:
            print(f"❌ Download failed for row {idx}: {e}. Trying next row...")
            continue

        caption_text = row.get('BenefitFocus', prompt[:100])
        processed_path = add_overlays_and_outro(temp_input, caption_text, idx)
        
        if not processed_path:
            print(f"❌ Video processing failed for row {idx}. Trying next row...")
            continue

        # 3. Host and Post
        public_url = upload_to_r2(processed_path)
        if public_url and post_to_buffer(public_url, caption_text):
            update_row_status(sheet_instance, idx, row, "Posted")
            print("🎉 Successfully posted. Task complete for today!")
            return

        print(f"❌ Final posting failed for row {idx}. Trying next row...")
        continue

    print("🎉 All rows in Sheet 2 are already processed or failed!")

if __name__ == "__main__":
    main()
