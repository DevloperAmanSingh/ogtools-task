#!/usr/bin/env python3

import subprocess
import sys
import os

def check_requirements():
    required_packages = {
        'streamlit': 'streamlit',
        'google-genai': 'google.genai',
        'requests': 'requests',
        'pandas': 'pandas'
    }
    
    missing = []
    for package_name, import_name in required_packages.items():
        try:
            __import__(import_name)
            print(f"✅ {package_name}")
        except ImportError:
            missing.append(package_name)
            print(f"❌ {package_name}")
    
    if missing:
        print(f"\n❌ Missing packages: {', '.join(missing)}")
        print("Install with: pip install " + " ".join(missing))
        return False
    
    print("✅ All packages available!")
    return True

def check_api_key():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("⚠️  API Key not found!")
        print("Set your API key: export GEMINI_API_KEY=your_api_key_here")
        print("Get a free key at: https://makersuite.google.com/app/apikey")
        return False
    
    print("✅ API Key configured")
    return True

def main():
    print("🚀 Blog Scraper - Starting UI...")
    print("=" * 50)
    
    if not check_requirements():
        return
    
    check_api_key()
    
    print("\n📱 Starting Streamlit app...")
    print("🌐 The app will open in your browser automatically")
    print("🔄 Use Ctrl+C to stop the server")
    print("=" * 50)
    
    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", 
            "src/ui/app.py",
            "--server.port", "8501",
            "--server.address", "localhost"
        ])
    except KeyboardInterrupt:
        print("\n👋 Stopping the server...")
    except Exception as e:
        print(f"❌ Error launching Streamlit: {e}")

if __name__ == "__main__":
    main() 