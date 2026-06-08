import asyncio
import httpx
import json
from pathlib import Path
from shared.models import DeviceType

async def pair_device():
    base_url = "http://localhost:8000"
    
    # 1. Initiate Pairing
    print("Initiating pairing...")
    async with httpx.AsyncClient() as client:
        req_data = {
            "device_name": "Sir's Workstation",
            "device_type": DeviceType.DESKTOP.value,
            "platform": "windows"
        }
        res = await client.post(f"{base_url}/api/devices/pair/initiate", json=req_data)
        if res.status_code != 200:
            print(f"Failed to initiate: {res.text}")
            return
        
        pairing_data = res.json()
        pairing_code = pairing_data.get("pairing_code")
        print(f"Got pairing code: {pairing_code}")
        
        # 2. Approve Pairing
        print("Approving pairing...")
        res = await client.post(f"{base_url}/api/devices/pair/approve?pairing_code={pairing_code}")
        if res.status_code != 200:
            print(f"Failed to approve: {res.text}")
            return
            
        auth_data = res.json()
        print("Successfully paired!")
        
        # 3. Update local_state_manager config
        config_path = Path("./config/client_config.json")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        config = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                
        config["device_id"] = auth_data["device_id"]
        config["device_secret"] = auth_data["device_secret"]
        config["access_token"] = auth_data["access_token"]
        config["refresh_token"] = auth_data["refresh_token"]
        config["paired"] = True
        
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            
        print("Updated client_config.json.")

if __name__ == "__main__":
    asyncio.run(pair_device())
