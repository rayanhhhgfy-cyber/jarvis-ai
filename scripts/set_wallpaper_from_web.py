import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.wallpaper import search_and_set_wallpaper_sync

if __name__ == '__main__':
    query = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else ''
    if not query:
        print("Usage: python scripts/set_wallpaper_from_web.py <search query>")
        sys.exit(1)
    try:
        result = search_and_set_wallpaper_sync(query)
        print(result)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
