import time
from backend.services.desktop_service import DesktopService

desktop = DesktopService()

def test_notepad():
    print("Launching Notepad...")
    result = desktop.launch_app("notepad")
    print(f"Launch result: {result}")
    if not result.get("success"):
        print("Failed to launch Notepad")
        return False

    # Wait for Notepad to open
    time.sleep(2)

    # Get active window to confirm
    active = desktop.get_active_window()
    print(f"Active window: {active}")

    # Type some text
    text = "Hello, Jarvis is controlling the PC!\nThis is a test of complex control."
    print(f"Typing: {text}")
    result = desktop.type_text(text, interval=0.01)
    print(f"Type result: {result}")

    # Wait a bit
    time.sleep(1)

    # Press Alt+F4 to close
    print("Closing Notepad with Alt+F4...")
    result = desktop.hotkey("alt", "f4")
    print(f"Hotkey result: {result}")

    # Wait for close dialog
    time.sleep(1)

    # Press Enter to don't save (if prompted)
    print("Pressing Enter to close without saving...")
    result = desktop.press_key("enter")
    print(f"Press result: {result}")

    print("Test completed.")
    return True

if __name__ == "__main__":
    test_notepad()