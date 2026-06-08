
import sys
import os
from pathlib import Path
import json

# Add current directory to path so we can import shared
sys.path.append(os.getcwd())

from shared.security import init_security, create_access_token, create_refresh_token
from backend.config import settings

def refresh():
    # Load settings from .env
    init_security(
        secret_key=settings.backend_secret_key,
        algorithm=settings.jwt_algorithm,
        access_expire_minutes=60, # 1 hour
    )
    
    config_path = Path("config/client_config.json")
    if not config_path.exists():
        print("Config file not found")
        return
        
    config = json.loads(config_path.read_text())
    
    device_id = config["device_id"]
    device_name = config["device_name"]
    
    print(f"Refreshing token for {device_name} ({device_id})...")
    
    new_access_token = create_access_token({"device_id": device_id, "device_name": device_name})
    new_refresh_token = create_refresh_token({"device_id": device_id})
    
    config["access_token"] = new_access_token
    config["refresh_token"] = new_refresh_token
    
    config_path.write_text(json.dumps(config, indent=2))
    print("Tokens refreshed successfully!")

if __name__ == "__main__":
    refresh()
