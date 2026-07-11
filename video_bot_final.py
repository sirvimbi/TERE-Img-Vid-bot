import os
import requests
import json
import asyncio
import time
from datetime import datetime
from moviepy.editor import *
import edge_tts

# ============================
# CONFIGURATION
# ============================

BUFFER_API_KEY = "cQJ4xuqenqOibNAcASCs0m8vgz-JNelFl3OvAf86i96"

# Try to load profile IDs
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
except:
    print("⚠️ Could not load profiles")

# ============================
# CREATE VIDEO (No subtitles)
# ============================

async def generate_audio(text):
    os.makedirs("temp", exist_ok=True)
    output_path = "temp/audio.mp3"
    voice = "en-US-JennyNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
    return output_path

def create_video(image_path, text):
    os.makedirs("temp", exist_ok=True)
    output_path = "temp/final.mp4"
    
    print("🎬 Creating video...")
    
    try:
        # Generate audio
        audio_path = asyncio.run(generate_audio(text))
        
        # Create video
        audio_clip = AudioFileClip(audio_path)
        audio_duration = audio_clip.duration
        
        if os.path.exists(image_path):
            image_clip = ImageClip(image_path).resize(height=720)
        else:
            from moviepy.video.VideoClip import ColorClip
            image_clip = ColorClip(size=(1080, 1920), color=(50, 50, 80), duration=audio_duration)
        
        image_clip = image_clip.set_duration(audio_duration)
        final_clip = image_clip.set_audio(audio_clip)
        
        final_clip.write_videofile(
            output_path, 
            fps=24, 
            codec="libx264",
            audio_codec="aac",
            verbose=False,
            logger=None,
            threads=4
        )
        print(f"✅ Video created: {output_path}")
        return output_path
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

# ============================
# POST TO BUFFER
# ============================

def post_to_buffer(video_path, caption):
    if not BUFFER_PROFILES:
        print("❌ No Buffer profiles configured")
        return None
    
    print(f"📤 Uploading to Buffer...")
    
    if not os.path.exists(video_path):
        print(f"❌ Video not found: {video_path}")
        return None
    
    # Try v1 API
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
    
    # Create post
    create_url = "https://api.buffer.com/1/updates/create.json"
    payload = {
        "text": caption[:280],
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
    print("🚀 Starting Video Bot")
    print("=" * 60)
    
    # Create a test image if needed
    if not os.path.exists("temp/intro.jpg"):
        os.makedirs("temp", exist_ok=True)
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (1080, 1920), color='#1a1a2e')
        d = ImageDraw.Draw(img)
        d.text((540, 860), "Test Video", fill=(255, 255, 255), anchor="mm")
        d.text((540, 960), "Made with Video Bot", fill=(100, 200, 255), anchor="mm")
        img.save("temp/intro.jpg")
    
    text = "Welcome to my automated video! This is a test post."
    
    # Create video
    video_path = create_video("temp/intro.jpg", text)
    if not video_path:
        print("❌ Video creation failed")
        return
    
    # Post to Buffer
    caption = f"{text} #VideoBot #Automation"
    result = post_to_buffer(video_path, caption)
    
    if result:
        print("✅ Success!")
    else:
        print("❌ Failed")

if __name__ == "__main__":
    main()
