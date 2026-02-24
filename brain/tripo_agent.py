import requests
import json
import time
from config import TRIPO_API_KEY

BASE_URL = "https://api.tripo3d.ai/v2/openapi/task"

def create_task(prompt):
    """
    Initializes a text-to-3d task on Tripo AI.
    Returns: {"success": True, "task_id": "..."} or {"success": False, "error": "..."}
    """
    if not TRIPO_API_KEY or TRIPO_API_KEY == "your_key_here":
        return {"success": False, "error": "Tripo API Key not configured. Please add TRIPO_API_KEY to config.py"}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TRIPO_API_KEY}"
    }
    
    data = {
        "type": "text_to_model",
        "prompt": prompt
    }

    try:
        response = requests.post(BASE_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        res_data = response.json()
        
        if res_data.get("code") == 0:
            return {
                "success": True, 
                "task_id": res_data["data"]["task_id"]
            }
        else:
            return {
                "success": False, 
                "error": res_data.get("message", "Unknown Tripo API error")
            }
            
    except requests.exceptions.HTTPError as e:
        try:
            err_json = e.response.json()
            err_msg = err_json.get("message", str(e))
            return {"success": False, "error": f"Tripo API Error: {err_msg}"}
        except:
            return {"success": False, "error": f"HTTP Error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Connection Error: {str(e)}"}

def get_status(task_id):
    """
    Checks the status of a Tripo AI task.
    Returns: {"success": True, "status": "running|success|failed", "model_url": "...", "progress": n}
    """
    if not TRIPO_API_KEY:
        return {"success": False, "error": "No API Key"}

    headers = {
        "Authorization": f"Bearer {TRIPO_API_KEY}"
    }

    try:
        response = requests.get(f"{BASE_URL}/{task_id}", headers=headers, timeout=30)
        response.raise_for_status()
        res_data = response.json()
        
        if res_data.get("code") == 0:
            task_data = res_data["data"]
            status = task_data.get("status")
            progress = task_data.get("progress", 0)
            
            result = {
                "success": True,
                "status": status,
                "progress": progress
            }
            
            if status == "success":
                # Tripo returns a dictionary of output files, we want the GLB one
                output = task_data.get("output", {})
                model_url = output.get("model") # Usually the GLB
                result["model_url"] = model_url
                
            return result
        else:
            return {
                "success": False, 
                "error": res_data.get("message", "Unknown Tripo API status error")
            }
            
    except requests.exceptions.HTTPError as e:
        try:
            err_json = e.response.json()
            err_msg = err_json.get("message", str(e))
            return {"success": False, "error": f"Tripo Status Error: {err_msg}"}
        except:
            return {"success": False, "error": f"HTTP Error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Connection Error: {str(e)}"}
