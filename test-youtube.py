#!/usr/bin/env python3
import yt_dlp
import sys

def test_youtube_access():
    """Test YouTube access from GitLab CI/CD"""
    test_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=jNQXAC9IVRw", 
        "https://www.youtube.com/watch?v=V8EO1-YAJ1k"
    ]
    
    for url in test_urls:
        print(f"\n🔍 Testing: {url}")
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                print(f"✅ SUCCESS: {info.get('title', 'Unknown')}")
                print(f"   Duration: {info.get('duration', 'Unknown')}s")
                print(f"   Channel: {info.get('uploader', 'Unknown')}")
                
        except Exception as e:
            print(f"❌ FAILED: {str(e)}")
    
    print(f"\n🌍 GitLab Runner IP and location info:")
    import requests
    try:
        ip_info = requests.get('https://ipapi.co/json/').json()
        print(f"   IP: {ip_info.get('ip', 'Unknown')}")
        print(f"   Location: {ip_info.get('city', 'Unknown')}, {ip_info.get('country_name', 'Unknown')}")
    except:
        print("   Could not fetch IP info")

if __name__ == "__main__":
    test_youtube_access()