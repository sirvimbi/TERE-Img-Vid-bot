import os
import requests
import subprocess
import json
import asyncio
import time
from datetime import datetime
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from moviepy.editor import *
import edge_tts
import numpy as np

# ============================
# FIX: Handle Pillow compatibility
# ============================
try:
    from PIL import Image, ImageDraw, ImageFont
    if not hasattr(Image, 'ANTIALIAS'):
        Image.ANTIALIAS = Image.LANCZOS
except:
    pass

load_dotenv()

# ============================
# CONFIGURATION
# ============================

BUFFER_API_KEY = os.getenv("BUFFER_API_KEY", "2ZUR6pZhjVC3CDsSGy3lQBBLn3LmZ61d7-e_KgqjSfM")

# Load profile IDs
BUFFER_PROFILES = []
try:
    with open('profile_ids.json', 'r') as f:
        profiles = json.load(f)
    for profile in profiles:
        service = profile.get('service', '').lower()
        if 'tiktok' in service:
            BUFFER_PROFILES.append(profile['id'])
        elif 'instagram' in service:
            BUFFER_PROFILES.append(profile['id'])
        elif 'facebook' in service:
            BUFFER_PROFILES.append(profile['id'])
    print(f"📋 Found profiles: {BUFFER_PROFILES}")
except FileNotFoundError:
    print("⚠️ profile_ids.json not found")
    BUFFER_PROFILES = []

SPREADSHEET_ID = "1dLZKzpnVrJp8HVGo6x5FoJw3Sk5K0wPxX-aQ5F5PrBI"
SERVICE_ACCOUNT_FILE = "service_account.json"

# ============================
# HASHTAGS AND LINK
# ============================

HASHTAGS = "#kenyantiktok🇰🇪 #creatorsearchinsights #smallbusiness #terekiosk #inventorymanagement #tere #fypppppppppppppppppppppppp #pos #trend"
PLAYSTORE_LINK = "https://play.google.com/store/apps/details?id=com.Tere"

# ============================
# READ FROM GOOGLE SHEETS
# ============================

def get_data_from_sheets():
    try:
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            print("⚠️ service_account.json not found. Using sample data.")
            return [
                {"Text": "Welcome to Tere Kiosk! Manage your inventory with ease.", 
                 "ImageFileName": "intro.jpg"}
            ]
        
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        records = sheet.get_all_records()
        print(f"📊 Read {len(records)} rows from Google Sheets")
        return records
    except Exception as e:
        print(f"❌ Error reading Google Sheets: {e}")
        return []

# ============================
# CREATE DUMMY IMAGE
# ============================

def create_dummy_image(filename):
    print(f"🎨 Creating dummy image: {filename}")
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (1080, 1920), color='#1a1a2e')
        d = ImageDraw.Draw(img)
        d.text((540, 860), "Tere Kiosk", fill=(255, 255, 255), anchor="mm")
        d.text((540, 960), "Inventory Management", fill=(100, 200, 255), anchor="mm")
        img.save(filename)
        return filename
    except Exception as e:
        print(f"⚠️ Could not create dummy image: {e}")
        return None

# ============================
# DOWNLOAD FROM R2
# ============================

def download_image_from_r2(filename):
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)
    local_path = f"{temp_dir}/{filename}"
    
    try:
        subprocess.run(["rclone", "--version"], capture_output=True, check=True)
        remote_path = f"r2:my-video-assets/{filename}"
        cmd = ["rclone", "copy", remote_path, temp_dir]
        print(f"📥 Downloading {filename} from R2...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(local_path):
            print(f"✅ Downloaded: {local_path}")
            return local_path
    except:
        pass
    
    return create_dummy_image(local_path)

# ============================
# GENERATE AUDIO
# ============================

async def generate_audio_async(text, output_path):
    voice = "en-US-JennyNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
    return output_path

def generate_audio(text, output_path="temp/audio.mp3"):
    os.makedirs("temp", exist_ok=True)
    print(f"🎤 Generating audio...")
    asyncio.run(generate_audio_async(text, output_path))
    return output_path

# ============================
# CREATE VIDEO WITH WATERMARK
# ============================

def create_video_with_watermark(image_path, text, output_path="temp/final_with_watermark.mp4"):
    os.makedirs("temp", exist_ok=True)
    
    print("🎬 Creating video with watermark...")
    
    try:
        # Generate audio
        audio_path = generate_audio(text)
        
        # Load audio
        audio_clip = AudioFileClip(audio_path)
        audio_duration = audio_clip.duration
        
        # Load image
        if os.path.exists(image_path):
            image_clip = ImageClip(image_path).resize(height=720)
        else:
            from moviepy.video.VideoClip import ColorClip
            image_clip = ColorClip(size=(1080, 1920), color=(50, 50, 80), duration=audio_duration)
        
        image_clip = image_clip.set_duration(audio_duration)
        
        # ============================
        # CREATE WATERMARK: "#Free POS" with Green Glow, Rotated 315° (-45°)
        # ============================
        
        from PIL import Image, ImageDraw, ImageFont
        
        # Create a transparent image for the watermark
        watermark_img = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark_img)
        
        watermark_text = "#Free POS"
        
        # Try to load a font, fallback to default
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 60)
        except:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 60)
            except:
                font = ImageFont.load_default()
        
        # Get text size
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Create a larger canvas for the text with shadow/glow
        padding = 30
        glow_size = 20  # Size of the glow effect
        text_img = Image.new('RGBA', (text_width + padding * 2 + glow_size * 2, text_height + padding * 2 + glow_size * 2), (0, 0, 0, 0))
        text_draw = ImageDraw.Draw(text_img)
        
        # Position the text in the center of the canvas
        x = padding + glow_size
        y = padding + glow_size
        
        # Draw multiple layers for glow effect (green)
        glow_colors = [
            (0, 255, 100, 30),   # Outer glow (very transparent)
            (0, 255, 100, 60),   # Mid glow
            (0, 255, 100, 120),  # Inner glow
            (0, 255, 100, 200),  # Core glow
        ]
        
        # Draw glow layers with offsets for shadow/glow effect
        offsets = [
            (-8, -8), (-6, -6), (-4, -4), (-2, -2),
            (0, 0),
            (2, 2), (4, 4), (6, 6), (8, 8)
        ]
        
        # Draw shadow/glow layers
        for offset_x, offset_y in offsets:
            # Outer glow (softer, more transparent)
            text_draw.text(
                (x + offset_x, y + offset_y), 
                watermark_text, 
                fill=(0, 255, 100, 40),  # Green with transparency
                font=font
            )
        
        # Draw the main text (bright green)
        text_draw.text(
            (x, y), 
            watermark_text, 
            fill=(0, 255, 100, 255),  # Bright green, fully opaque
            font=font
        )
        
        # Draw a second layer for extra brightness
        text_draw.text(
            (x, y), 
            watermark_text, 
            fill=(100, 255, 150, 180),  # Lighter green highlight
            font=font
        )
        
        # Rotate the text image by 315° (-45°)
        rotated_text = text_img.rotate(-45, expand=True, resample=Image.BICUBIC)
        
        # Position at top-left with padding
        x_pos = 20
        y_pos = 20
        
        # Paste onto the main image
        watermark_img.paste(rotated_text, (x_pos, y_pos), rotated_text)
        
        # Convert PIL image to numpy array for MoviePy
        watermark_array = np.array(watermark_img)
        
        # Create a MoviePy clip from the watermark
        watermark_clip = ImageClip(watermark_array, transparent=True).set_duration(audio_duration)
        watermark_clip = watermark_clip.set_position(("left", "top"))
        
        # ============================
        # CREATE SUBTITLES: Just White Text, No Shadow
        # ============================
        
        # Split text into chunks for subtitles
        words = text.split()
        chunks = []
        chunk = []
        for word in words:
            chunk.append(word)
            if len(' '.join(chunk)) > 25:
                chunks.append(' '.join(chunk))
                chunk = []
        if chunk:
            chunks.append(' '.join(chunk))
        subtitle_text = '\n'.join(chunks)
        
        # Create white subtitle (no shadow, no glow)
        subtitle_clip = TextClip(
            subtitle_text,
            fontsize=42,
            color='white',
            font='Arial',
            method='caption',
            size=(image_clip.w * 0.9, None),
            align='center'
        ).set_position(('center', 0.75), relative=True).set_duration(audio_duration)
        
        # ============================
        # COMBINE EVERYTHING
        # ============================
        
        final_clip = CompositeVideoClip([
            image_clip,
            watermark_clip,
            subtitle_clip
        ]).set_audio(audio_clip)
        
        # Write the video
        final_clip.write_videofile(
            output_path, 
            fps=24, 
            codec="libx264",
            audio_codec="aac",
            verbose=False,
            logger=None,
            threads=4
        )
        print(f"✅ Video with watermark saved: {output_path}")
        return output_path
        
    except Exception as e:
        print(f"❌ Error creating video with watermark: {e}")
        import traceback
        traceback.print_exc()
        return None

# ============================
# POST TO BUFFER
# ============================

def post_to_buffer(video_path, text):
    if not BUFFER_PROFILES:
        print("❌ No Buffer profiles configured")
        return None
    
    print(f"📤 Uploading to Buffer...")
    
    if not os.path.exists(video_path):
        print(f"❌ Video not found: {video_path}")
        return None
    
    # Upload video
    upload_url = "https://api.buffer.com/1/media/upload.json"
    with open(video_path, 'rb') as f:
        files = {'file': (os.path.basename(video_path), f, 'video/mp4')}
        params = {'access_token': BUFFER_API_KEY}
        
        try:
            upload_response = requests.post(upload_url, files=files, params=params, timeout=60)
            print(f"   Upload status: {upload_response.status_code}")
        except Exception as e:
            print(f"❌ Upload error: {e}")
            return None
    
    if upload_response.status_code != 200:
        print(f"❌ Upload failed: {upload_response.text}")
        return None
    
    media_id = upload_response.json().get('id')
    print(f"✅ Media uploaded, ID: {media_id}")
    
    # Create caption with hashtags and link
    caption = f"{text}\n\n{HASHTAGS}\n\n📱 Download now: {PLAYSTORE_LINK}"
    
    # Create post
    create_url = "https://api.buffer.com/1/updates/create.json"
    payload = {
        "text": caption[:280],  # Buffer character limit
        "media": [{"media_id": media_id}],
        "profile_ids": BUFFER_PROFILES
    }
    params = {'access_token': BUFFER_API_KEY}
    
    create_response = requests.post(create_url, json=payload, params=params, timeout=30)
    
    if create_response.status_code == 200:
        print("✅ Post created!")
        return create_response.json()
    else:
        print(f"❌ Post failed: {create_response.text}")
        return None

# ============================
# MAIN
# ============================

def main():
    print("🚀 Starting Video Bot with Watermark")
    print("=" * 60)
    
    if not BUFFER_PROFILES:
        print("❌ No Buffer profiles. Run: python get_profiles.py")
        return
    
    records = get_data_from_sheets()
    if not records:
        print("❌ No data in Google Sheets")
        return
    
    processed = 0
    for idx, row in enumerate(records, 1):
        text = row.get('Text', '').strip()
        image_filename = row.get('ImageFileName', '').strip()
        
        if not text or not image_filename:
            print(f"⏭️ Skipping row {idx}")
            continue
        
        print(f"\n🎬 Processing row {idx}: {text[:30]}...")
        
        image_path = download_image_from_r2(image_filename)
        if not image_path:
            print(f"❌ Could not get image")
            continue
        
        video_path = create_video_with_watermark(image_path, text)
        if not video_path or not os.path.exists(video_path):
            print("❌ Video creation failed")
            continue
        
        result = post_to_buffer(video_path, text)
        
        if result:
            processed += 1
            print(f"✅ Video {idx} posted!")
        else:
            print(f"❌ Failed to post video {idx}")
        
        if idx < len(records):
            print("⏳ Waiting 60 seconds...")
            time.sleep(60)
    
    print(f"\n🎉 Completed! Processed {processed} videos.")

if __name__ == "__main__":
    main()
