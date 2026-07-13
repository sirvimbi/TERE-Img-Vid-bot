import os
import requests
import json
import asyncio
import time
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
BUFFER_PROFILE_IDS = [
    "6a53866180cc80cdcaa5f066", # Instagram
    "6a522ee0404834462894dfbf", # TikTok
    "6a5380ff80cc80cdcaa5d2bf"  # Facebook
]

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
        # Auth logic similar to video_bot.py
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
        
        # Open Sheet 2
        sheet = client.open_by_key(SPREADSHEET_ID).get_worksheet(1) # Index 1 is the second sheet
        return sheet, sheet.get_all_records()
    except Exception as e:
        print(f"❌ Error reading Sheet 2: {e}")
        return None, []

# ============================
# AGNES AI LOGIC
# ============================

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
            print(f"❌ Agnes Task Submission Failed: {response.text}")
            return None
        
        video_id = response.json().get("video_id")
        print(f"⏳ Task submitted! Video ID: {video_id}. Polling for result...")
        
        # Polling loop
        max_retries = 60 # 5 minutes max
        for i in range(max_retries):
            time.sleep(10) # Poll every 10 seconds
            poll_url = f"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}"
            res = requests.get(poll_url, headers=headers)
            
            if res.status_code == 200:
                data = res.json()
                status = data.get("status", "").lower()
                
                if status == "completed":
                    video_url = data.get("video_url")
                    print(f"✅ Video ready: {video_url}")
                    return video_url
                elif status == "failed":
                    print(f"❌ Agnes Generation Failed: {data.get('error')}")
                    return None
                else:
                    print(f"⏳ Status: {status} ({i*10}s elapsed)...")
            else:
                print(f"⚠️ Polling warning: {res.status_code}")
                
        print("❌ Polling timed out.")
        return None
    except Exception as e:
        print(f"❌ Agnes API Error: {e}")
        return None

# ============================
# VIDEO PROCESSING (Subtitles & Outro)
# ============================

def add_overlays_and_outro(input_video_path, caption_text, index):
    output_path = f"temp/agnes_final_{index}.mp4"
    print("🎬 Adding subtitles and outro to Agnes video...")
    
    try:
        video = VideoFileClip(input_video_path)
        
        # 1. Subtitles (Simple White)
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

        # 2. Outro
        outro_duration = 3
        background = ColorClip(size=(video.w, video.h), color=(26, 26, 46)).set_duration(outro_duration)
        
        if os.path.exists(LOGO_PATH):
            logo_clip = ImageClip(LOGO_PATH).resize(width=video.w * 0.6).set_duration(outro_duration).set_position('center')
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
# BUFFER & R2 LOGIC
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
    for profile_id in BUFFER_PROFILE_IDS:
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
            print(f"❌ Failed to post to {profile_id}: {res.text}")
    return success_count > 0

# ============================
# MAIN
# ============================

def main():
    print("🚀 Agnes AI Video Bot Initialized")
    os.makedirs("temp", exist_ok=True)
    
    sheet_instance, records = get_data_from_sheet2()
    if not records: return

    for idx, row in enumerate(records, 1):
        status = row.get('Status', '').strip().lower()
        if status == 'posted': continue
        
        prompt = row.get('VideoPrompt', '').strip()
        if not prompt: continue
        
        print(f"\n🎬 Processing Row {idx} from Sheet 2...")
        
        # 1. Agnes Generation
        video_url = generate_agnes_video(prompt)
        if not video_url: continue
        
        # 2. Download and Process
        temp_input = f"temp/agnes_raw_{idx}.mp4"
        with open(temp_input, 'wb') as f:
            f.write(requests.get(video_url).content)
        
        # Use the "BenefitFocus" or "VideoPrompt" snippet for captions
        caption_text = row.get('BenefitFocus', prompt[:100])
        processed_path = add_overlays_and_outro(temp_input, caption_text, idx)
        
        # 3. Host and Post
        public_url = upload_to_r2(processed_path)
        if public_url and post_to_buffer(public_url, caption_text):
            # 4. Mark Status
            try:
                # Find Status column
                headers = [h.lower() for h in row.keys()]
                status_col = headers.index('status') + 1
                sheet_instance.update_cell(idx + 1, status_col, "Posted")
                print(f"✅ Row {idx} marked as Posted in Sheet 2.")
            except:
                print("⚠️ Failed to update sheet status.")
            
            # Exit after one successful post per run
            return

    print("🎉 All rows in Sheet 2 are posted!")

if __name__ == "__main__":
    main()
