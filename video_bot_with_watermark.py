import os
import requests
import subprocess
import json
import asyncio
import time
from datetime import datetime, timedelta
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
os.environ["IMAGEMAGICK_BINARY"] = "/opt/homebrew/bin/magick"

from moviepy.editor import *
from moviepy.video.VideoClip import ColorClip
import edge_tts

load_dotenv()

# ============================
# CONFIGURATION
# ============================

# Use the token we know works (GraphQL)
BUFFER_API_KEY = os.getenv("BUFFER_API_KEY") or os.getenv("BUFFER_ACCESS_TOKEN") or "2ZUR6pZhjVC3CDsSGy3lQBBLn3LmZ61d7-e_KgqjSfM"
BUFFER_URL = "https://api.buffer.com"

# Load profile IDs
try:
    with open('profile_ids.json', 'r') as f:
        profiles = json.load(f)
    BUFFER_PROFILES = [p['id'] for p in profiles]
    print(f"📋 Found profiles: {BUFFER_PROFILES}")
except FileNotFoundError:
    print("⚠️ profile_ids.json not found")
    BUFFER_PROFILES = []

SPREADSHEET_ID = "1dLZKzpnVrJp8HVGo6x5FoJw3Sk5K0wPxX-aQ5F5PrBI"
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT", "service_account.json")

# Hashtags and Link
HASHTAGS = "#kenyantiktok🇰🇪 #creatorsearchinsights #smallbusiness #terekiosk #inventorymanagement #tere #fypppppppppppppppppppppppp #pos #trend"
PLAYSTORE_LINK = "https://play.google.com/store/apps/details?id=com.Tere"
LOGO_PATH = "logo.png"  # Ensure this file exists in the project root

# Cloudflare R2
R2_BUCKET = "my-video-assets"
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "https://pub-2c8f5c70aa494b5ebd42c9e0a87b930b.r2.dev")

# ============================
# READ FROM GOOGLE SHEETS
# ============================

def get_data_from_sheets():
    try:
        # Priority 1: GitHub Secret (Cloud)
        env_creds = os.getenv("GOOGLE_CREDS_JSON")
        if env_creds:
            print("🔐 Authenticating with Environment Credentials (Cloud)...")
            creds_dict = json.loads(env_creds)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
        
        # Priority 2: Service Account File (Local)
        elif os.path.exists(SERVICE_ACCOUNT_FILE):
            print(f"🔐 Authenticating with Service Account: {SERVICE_ACCOUNT_FILE}")
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
            client = gspread.authorize(creds)
        
        # Priority 3: OAuth Client ID (Local Browser)
        elif os.path.exists("client_secrets.json"):
            print("🔐 Authenticating with OAuth Client ID (Browser Login required)...")
            os.makedirs("temp", exist_ok=True)
            client = gspread.oauth(
                credentials_filename='client_secrets.json',
                authorized_user_filename='temp/authorized_user.json'
            )
        else:
            print("⚠️ No credentials found. Check .env or json files.")
            return None, []
        
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        return sheet, sheet.get_all_records()
    except Exception as e:
        print(f"❌ Error reading Google Sheets: {e}")
        return None, []

# ============================
# ASSET HELPERS
# ============================

def create_dummy_image(filename):
    print(f"🎨 Creating dummy image: {filename}")
    try:
        from PIL import Image, ImageDraw
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        img = Image.new('RGB', (1080, 1920), color='#1a1a2e')
        d = ImageDraw.Draw(img)
        d.text((540, 860), "Tere Kiosk", fill=(255, 255, 255), anchor="mm")
        img.save(filename)
        return filename
    except Exception as e:
        print(f"⚠️ Could not create dummy image: {e}")
        return None

def download_image_from_r2(filename):
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)
    local_path = f"{temp_dir}/{filename}"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    try:
        remote_path = f"r2:{R2_BUCKET}/{filename}"
        cmd = ["rclone", "copyto", remote_path, local_path]
        print(f"📥 Downloading {filename} from R2...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(local_path):
            print(f"✅ Downloaded: {local_path}")
            return local_path
    except:
        pass
    
    return create_dummy_image(local_path)

def upload_to_r2(local_path):
    filename = os.path.basename(local_path)
    print(f"📤 Uploading {filename} to R2...")
    try:
        cmd = ["rclone", "copy", local_path, f"r2:{R2_BUCKET}/"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            public_url = f"{R2_PUBLIC_BASE_URL}/{filename}"
            print(f"✅ Video available at: {public_url}")
            return public_url
    except Exception as e:
        print(f"❌ R2 Upload failed: {e}")
    return None

async def generate_audio_async(text, output_path, voice="en-US-JennyNeural"):
    if not voice:
        voice = "en-US-JennyNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

def generate_audio_async_wrapped(text, output_path, voice="en-US-JennyNeural"):
    voice = voice.split(' ')[0]
    print(f"🎤 Generating audio with voice: {voice}...")
    asyncio.run(generate_audio_async(text, output_path, voice))
    return output_path

# ============================
# CREATE VIDEO WITH WATERMARK & OUTRO
# ============================

def create_video_with_watermark(image_path, text, voice="en-US-JennyNeural", index=0):
    output_path = f"temp/final_video_{index}.mp4"
    print("🎬 Creating video with watermark and outro...")
    
    try:
        audio_path = f"temp/audio_{index}.mp3"
        generate_audio_async_wrapped(text, audio_path, voice)
        
        audio_clip = AudioFileClip(audio_path)
        audio_duration = audio_clip.duration
        
        if os.path.exists(image_path):
            image_clip = ImageClip(image_path).resize(height=720)
            image_clip = image_clip.set_duration(audio_duration)
            image_clip = image_clip.resize(lambda t: 1 + 0.05 * (t / audio_duration))
        else:
            image_clip = ColorClip(size=(1080, 1920), color=(50, 50, 80), duration=audio_duration)
        
        image_clip = image_clip.set_duration(audio_duration)
        
        # Find font path
        font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" # Linux fallback
        if not os.path.exists(font_path):
            font_path = "Arial"

        # 1. Watermark
        from PIL import Image, ImageDraw, ImageFont
        watermark_img = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_img)
        watermark_text = "#Free POS"
        
        try:
            font = ImageFont.truetype(font_path, 60)
        except:
            font = ImageFont.load_default()
        
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        text_img = Image.new('RGBA', (text_w + 40, text_h + 40), (0, 0, 0, 0))
        text_draw = ImageDraw.Draw(text_img)
        text_draw.text((13, 13), watermark_text, fill=(0, 0, 0, 180), font=font)
        text_draw.text((10, 10), watermark_text, fill=(0, 255, 0, 255), font=font)
        rotated_text = text_img.rotate(315, expand=True, resample=Image.BICUBIC)
        watermark_img.paste(rotated_text, (40, 40), rotated_text)
        
        watermark_clip = ImageClip(np.array(watermark_img), transparent=True).set_duration(audio_duration)
        watermark_clip = watermark_clip.set_position(("left", "top"))
        
        # 2. Subtitles
        chunks = []
        words = text.split()
        chunk = []
        for word in words:
            chunk.append(word)
            if len(' '.join(chunk)) > 25:
                chunks.append(' '.join(chunk))
                chunk = []
        if chunk: chunks.append(' '.join(chunk))
        subtitle_text = '\n'.join(chunks)
        
        text_clip = TextClip(
            subtitle_text,
            fontsize=42,
            color='white',
            font=font_path,
            method='caption',
            size=(image_clip.w * 0.9, None),
            align='center'
        ).set_position(('center', 0.75), relative=True).set_duration(audio_duration)
        
        main_video = CompositeVideoClip([image_clip, watermark_clip, text_clip]).set_audio(audio_clip)

        # 3. Outro
        outro_duration = 3
        # Ensure logo is available (download from R2 if needed)
        current_logo_path = LOGO_PATH
        if not os.path.exists(current_logo_path):
            print(f"📥 Logo not found locally. Downloading from R2...")
            downloaded_logo = download_image_from_r2(LOGO_PATH)
            if downloaded_logo:
                current_logo_path = downloaded_logo

        if os.path.exists(current_logo_path):
            logo_clip = ImageClip(current_logo_path).resize(width=image_clip.w * 0.6)
            logo_clip = logo_clip.set_duration(outro_duration).set_position('center')
            
            background = ColorClip(size=(main_video.w, main_video.h), color=(26, 26, 46)).set_duration(outro_duration)
            
            download_text = TextClip(
                "Download Now",
                fontsize=60,
                color='white',
                font=font_path,
                size=(image_clip.w * 0.8, None),
                align='center'
            ).set_duration(outro_duration).set_position(('center', 0.8), relative=True)
            
            outro = CompositeVideoClip([background, logo_clip, download_text])
        else:
            print(f"⚠️ {LOGO_PATH} not found. Using text-only outro.")
            background = ColorClip(size=(main_video.w, main_video.h), color=(26, 26, 46)).set_duration(outro_duration)
            download_text = TextClip(
                "TERE KIOSK\nDownload Now",
                fontsize=70,
                color='white',
                font=font_path,
                size=(image_clip.w * 0.8, None),
                align='center'
            ).set_duration(outro_duration).set_position('center')
            outro = CompositeVideoClip([background, download_text])

        # Concatenate main video and outro
        final_video = concatenate_videoclips([main_video, outro], method="compose")
        final_video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", logger=None, threads=4)
        return output_path
    except Exception as e:
        print(f"❌ Error creating video: {e}")
        return None

# ============================
# POST TO BUFFER (GraphQL)
# ============================

def post_to_buffer(video_url, text):
    if not BUFFER_PROFILES:
        print("❌ No Buffer profiles configured")
        return False
    
    print(f"📤 Posting to Buffer via GraphQL...")
    headers = {
        "Authorization": f"Bearer {BUFFER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    caption = f"{text}\n\n{HASHTAGS}\n\n📱 Download now: {PLAYSTORE_LINK}"
    mutation = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id } }
        ... on MutationError { message }
      }
    }
    """
    
    success = False
    for profile_id in BUFFER_PROFILES:
        variables = {
            "input": {
                "text": caption,
                "channelId": profile_id,
                "schedulingType": "automatic",
                "mode": "addToQueue",
                "assets": [{"video": {"url": video_url}}]
            }
        }
        try:
            response = requests.post(BUFFER_URL, json={'query': mutation, 'variables': variables}, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if "errors" in data:
                    print(f"❌ Error ({profile_id}): {data['errors'][0]['message']}")
                elif "message" in data.get('data', {}).get('createPost', {}):
                    print(f"❌ Error ({profile_id}): {data['data']['createPost']['message']}")
                else:
                    print(f"✅ Success: Posted to {profile_id}")
                    success = True
            else:
                print(f"❌ HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ Request failed: {e}")
    return success

# ============================
# MAIN CLOUD LOGIC
# ============================

def process_row(idx, row, sheet_instance):
    text = (row.get('Text') or row.get('text') or '').strip()
    img_name = (row.get('ImageFileName') or row.get('iImageFileName') or '').strip()
    voice = (row.get('Voice') or row.get('voice') or 'en-US-JennyNeural').strip()
    status = (row.get('Status') or row.get('status') or '').strip()

    if status.lower() == 'posted':
        return False

    if not text or not img_name:
        print(f"⏭️ Skipping row {idx}: Missing text or image.")
        return False
    
    print(f"\n🎬 Processing row {idx}: {text[:30]}...")
    image_path = download_image_from_r2(img_name)
    
    video_path = create_video_with_watermark(image_path, text, voice, idx)
    if not video_path:
        return False
        
    video_url = upload_to_r2(video_path)
    if video_url:
        if post_to_buffer(video_url, text):
            # Mark as posted
            try:
                # Find column index for "Status" or "status"
                headers = list(row.keys())
                status_col = -1
                for i, h in enumerate(headers, 1):
                    if h.lower() == 'status':
                        status_col = i
                        break
                
                if status_col != -1:
                    sheet_instance.update_cell(idx + 1, status_col, "Posted")
                    print(f"✅ Row {idx} marked as 'Posted' in Google Sheet.")
                else:
                    print("⚠️ 'Status' column not found in sheet. Could not mark as posted.")
            except Exception as e:
                print(f"⚠️ Could not update Sheet: {e}")
            return True
    return False

def main():
    print("🚀 Starting Video Bot (Cloud/Autonomous Version)")
    print("=" * 60)
    
    # Configure ImageMagick for Cloud (Ubuntu)
    if os.name != 'nt':
        if os.path.exists("/usr/bin/magick"):
            os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/magick"
        elif os.path.exists("/usr/bin/convert"):
            os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

    sheet_instance, records = get_data_from_sheets()
    if not records:
        return

    # Process exactly ONE unposted row
    for idx, row in enumerate(records, 1):
        status = (row.get('Status') or row.get('status') or '').strip()
        if status.lower() != 'posted':
            print(f"📍 Found next available row: {idx}")
            if process_row(idx, row, sheet_instance):
                print(f"✅ Successfully posted row {idx}. Task complete.")
                return 
            else:
                print(f"❌ Failed to process row {idx}. Stopping.")
                return
                
    print("🎉 All rows in the sheet have already been posted!")

if __name__ == "__main__":
    main()
