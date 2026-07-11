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
import PIL.Image

# ============================
# MOVIEPY & PILLOW COMPATIBILITY FIX
# ============================
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

# Configure MoviePy to use ImageMagick via environment variable
os.environ["IMAGEMAGICK_BINARY"] = "/opt/homebrew/bin/magick"

from moviepy.editor import *
import edge_tts

# Load environment variables
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
    print("⚠️ profile_ids.json not found. Please run get_profiles.py first.")
    BUFFER_PROFILES = []

SPREADSHEET_ID = "1dLZKzpnVrJp8HVGo6x5FoJw3Sk5K0wPxX-aQ5F5PrBI"
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT", "service_account.json")

# Cloudflare R2 config
R2_BUCKET = "my-video-assets"
# IMPORTANT: Buffer GraphQL needs a PUBLIC URL to fetch your video.
# Replace this with your actual R2 public bucket URL (e.g., https://pub-xxx.r2.dev)
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "https://your-public-bucket.r2.dev")

# ============================
# STEP 1: Read from Google Sheets
# ============================

def get_data_from_sheets():
    """Read video data from Google Sheets or fallback for testing"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"⚠️ {SERVICE_ACCOUNT_FILE} not found. Using sample data for demonstration.")
        return [
            {"Text": "Welcome to my automated video! This is a test post.", 
             "ImageFileName": "intro.jpg", 
             "Voice": "en-US-JennyNeural"}
        ]
    
    try:
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
# STEP 2: Handle R2 (Download/Upload)
# ============================

def download_image_from_r2(filename):
    """Download an image from Cloudflare R2 or create dummy if fails"""
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)
    local_path = os.path.join(temp_dir, filename)
    
    remote_path = f"r2:{R2_BUCKET}/{filename}"
    print(f"📥 Downloading {filename} from R2...")
    
    try:
        cmd = ["rclone", "copy", remote_path, temp_dir]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(local_path):
            print(f"✅ Downloaded: {local_path}")
            return local_path
    except Exception as e:
        print(f"⚠️ rclone download failed: {e}")
    
    # Fallback: create a dummy image
    print("🎨 Creating dummy image for testing...")
    img = PIL.Image.new('RGB', (1080, 1920), color = (26, 26, 46))
    img.save(local_path)
    return local_path

def upload_to_r2(local_path):
    """Upload video to R2 so Buffer can access it via public URL"""
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

# ============================
# STEP 3: Audio Generation
# ============================

async def generate_audio_async(text, output_path):
    voice = "en-US-JennyNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

def generate_audio(text):
    os.makedirs("temp", exist_ok=True)
    audio_path = "temp/audio.mp3"
    print(f"🎤 Generating audio...")
    asyncio.run(generate_audio_async(text, audio_path))
    return audio_path

# ============================
# STEP 4: Video Creation
# ============================

def create_video(image_path, audio_path):
    output_path = "temp/video_raw.mp4"
    print("🎬 Creating video clip...")
    
    audio_clip = AudioFileClip(audio_path)
    image_clip = ImageClip(image_path).set_duration(audio_clip.duration)
    image_clip = image_clip.resize(height=720) # Normalize size
    
    # Simple zoom effect
    image_clip = image_clip.resize(lambda t: 1 + 0.05 * (t / audio_clip.duration))
    
    final_clip = image_clip.set_audio(audio_clip)
    final_clip.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", logger=None, threads=4)
    
    return output_path

# ============================
# STEP 5: Subtitles
# ============================

def add_subtitles(video_path, text):
    output_path = "temp/final_video.mp4"
    print("📝 Adding subtitles...")
    
    try:
        video = VideoFileClip(video_path)
        
        # Try to find a valid font on macOS
        font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
        if not os.path.exists(font_path):
            font_path = "Arial" # Fallback to system font name
            
        txt_clip = TextClip(
            text,
            fontsize=40,
            color='white',
            method='caption',
            size=(video.w * 0.8, None),
            font=font_path
        ).set_position(('center', 'bottom')).set_duration(video.duration).margin(bottom=50, opacity=0)

        final = CompositeVideoClip([video, txt_clip])
        final.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None, threads=4)
        return output_path
    except Exception as e:
        print(f"⚠️ Could not add subtitles: {e}")
        print("💡 Continuing without subtitles...")
        return video_path

# ============================
# STEP 6: Post to Buffer (GraphQL)
# ============================

def post_to_buffer(video_url, caption):
    """Post to Buffer using GraphQL mutation"""
    if not BUFFER_PROFILES:
        print("❌ No Buffer profiles to post to.")
        return False

    print(f"📤 Posting to Buffer via GraphQL...")
    headers = {
        "Authorization": f"Bearer {BUFFER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    mutation = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { 
          post { 
            id 
          } 
        }
        ... on MutationError { 
          message 
        }
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
                    print(f"❌ Buffer GraphQL Error ({profile_id}): {data['errors'][0]['message']}")
                elif "message" in data.get('data', {}).get('createPost', {}):
                    print(f"❌ Buffer Mutation Error ({profile_id}): {data['data']['createPost']['message']}")
                else:
                    print(f"✅ Success: Posted to {profile_id}")
                    success = True
            else:
                print(f"❌ Buffer HTTP Error: {response.status_code}")
                print(response.text)
        except Exception as e:
            print(f"❌ Request failed: {e}")
            
    return success

# ============================
# MAIN
# ============================

def main():
    print("🚀 Starting Video Bot (GraphQL Version)...")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    records = get_data_from_sheets()
    if not records:
        print("❌ No data found.")
        return

    processed = 0
    for idx, row in enumerate(records, 1):
        text = row.get('Text', '')
        image_name = row.get('ImageFileName', '')
        
        if not text or not image_name:
            continue
            
        print(f"\n🎬 Processing #{idx}: {text[:30]}...")
        
        # 1. Assets
        image_path = download_image_from_r2(image_name)
        audio_path = generate_audio(text)
        
        # 2. Video Edit
        video_raw = create_video(image_path, audio_path)
        final_video = add_subtitles(video_raw, text)
        
        # 3. Host and Post
        video_url = upload_to_r2(final_video)
        
        if video_url:
            if "your-public-bucket" in video_url:
                print("⚠️ Warning: R2_PUBLIC_BASE_URL is not configured in .env.")
                print(f"💡 Please set it so Buffer can fetch: {video_url}")
            
            caption = f"{text} #Automated #VideoBot"
            if post_to_buffer(video_url, caption):
                processed += 1
        else:
            print("❌ Skipping Buffer post: Failed to upload video to R2.")
            
        if idx < len(records):
            print("⏳ Waiting 30s...")
            time.sleep(30)

    print(f"\n🎉 Completed! Processed {processed} videos.")

if __name__ == "__main__":
    main()
