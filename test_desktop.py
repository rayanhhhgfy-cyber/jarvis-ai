import pyautogui
from backend.services.desktop_service import DesktopService

# Get original position
original_x, original_y = pyautogui.position()
print(f"Original position: ({original_x}, {original_y})")

# Create desktop service instance
desktop = DesktopService()

# Move to (100, 100)
result = desktop.move_mouse(100, 100, duration=0.5)
print(f"Move result: {result}")

# Move back to original
result = desktop.move_mouse(original_x, original_y, duration=0.5)
print(f"Move back result: {result}")

print("Test completed successfully.")