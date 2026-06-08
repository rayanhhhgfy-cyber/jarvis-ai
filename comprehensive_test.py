import time
from backend.services.desktop_service import DesktopService

def run_comprehensive_test():
    desktop = DesktopService()

    print("=== Starting Comprehensive Desktop Control Test ===\n")

    # Test 1: Screen info
    print("1. Testing screen size detection...")
    screen_result = desktop.get_screen_size()
    print(f"   Screen size: {screen_result}")
    assert screen_result.get("success"), "Failed to get screen size"

    # Test 2: Mouse position and movement
    print("\n2. Testing mouse control...")
    pos_result = desktop.get_mouse_position()
    print(f"   Current position: {pos_result}")
    assert pos_result.get("success"), "Failed to get mouse position"

    original_x, original_y = pos_result["x"], pos_result["y"]

    # Move to corner and back
    desktop.move_mouse(100, 100, duration=0.3)
    time.sleep(0.5)
    pos_result = desktop.get_mouse_position()
    print(f"   Moved to: {pos_result}")

    desktop.move_mouse(original_x, original_y, duration=0.3)
    time.sleep(0.5)
    pos_result = desktop.get_mouse_position()
    print(f"   Returned to: {pos_result}")

    # Test 3: Mouse clicks
    print("\n3. Testing mouse clicks...")
    # Click at current position
    click_result = desktop.click()
    print(f"   Click result: {click_result}")
    assert click_result.get("success"), "Failed to perform click"

    # Right click
    right_click_result = desktop.right_click()
    print(f"   Right click result: {right_click_result}")
    assert right_click_result.get("success"), "Failed to perform right click"

    # Test 4: Keyboard control
    print("\n4. Testing keyboard control...")
    # Type a short message
    type_result = desktop.type_text("Jarvis control test ", interval=0.01)
    print(f"   Type result: {type_result}")
    assert type_result.get("success"), "Failed to type text"

    # Press Enter
    enter_result = desktop.press_key("enter")
    print(f"   Enter key result: {enter_result}")
    assert enter_result.get("success"), "Failed to press Enter key"

    # Test 5: Hotkey combinations
    print("\n5. Testing hotkey combinations...")
    # Copy (Ctrl+C) - should copy the typed text
    copy_result = desktop.hotkey("ctrl", "c")
    print(f"   Copy result: {copy_result}")
    assert copy_result.get("success"), "Failed to perform Ctrl+C"

    # Paste (Ctrl+V) in new location
    desktop.move_mouse(original_x + 50, original_y + 50, duration=0.3)
    time.sleep(0.3)
    paste_result = desktop.hotkey("ctrl", "v")
    print(f"   Paste result: {paste_result}")
    assert paste_result.get("success"), "Failed to perform Ctrl+V"

    # Test 6: Window management
    print("\n6. Testing window management...")
    # Launch calculator
    launch_result = desktop.launch_app("calculator")
    print(f"   Launch calculator: {launch_result}")
    assert launch_result.get("success"), "Failed to launch calculator"

    time.sleep(2)  # Wait for calculator to open

    # Get active window
    active_result = desktop.get_active_window()
    print(f"   Active window: {active_result}")
    assert active_result.get("success"), "Failed to get active window"

    # Minimize window
    minimize_result = desktop.minimize_window(active_result["title"])
    print(f"   Minimize window: {minimize_result}")
    assert minimize_result.get("success"), "Failed to minimize window"

    time.sleep(1)

    # Restore window
    restore_result = desktop.restore_window(active_result["title"])
    print(f"   Restore window: {restore_result}")
    assert restore_result.get("success"), "Failed to restore window"

    time.sleep(1)

    # Close calculator
    close_result = desktop.close_window(active_result["title"])
    print(f"   Close window: {close_result}")
    assert close_result.get("success"), "Failed to close window"

    # Test 7: Clipboard
    print("\n7. Testing clipboard...")
    clipboard_text = "Test clipboard content from Jarvis"
    write_result = desktop.write_clipboard(clipboard_text)
    print(f"   Write clipboard: {write_result}")
    assert write_result.get("success"), "Failed to write to clipboard"

    time.sleep(0.5)
    read_result = desktop.read_clipboard()
    print(f"   Read clipboard: {read_result}")
    assert read_result.get("success"), "Failed to read from clipboard"
    assert read_result.get("text") == clipboard_text, "Clipboard content mismatch"

    # Test 8: Screenshot
    print("\n8. Testing screenshot...")
    screenshot_result = desktop.screenshot()
    print(f"   Screenshot result: {screenshot_result}")
    assert screenshot_result.get("success"), "Failed to take screenshot"
    assert "screenshot_base64" in screenshot_result, "Screenshot missing base64 data"

    # Return mouse to original position
    desktop.move_mouse(original_x, original_y, duration=0.3)
    print(f"\n=== All tests passed! Mouse returned to ({original_x}, {original_y}) ===")
    return True

if __name__ == "__main__":
    try:
        run_comprehensive_test()
        print("\n🎉 COMPREHENSIVE TEST SUCCESSFUL - Jarvis has full desktop control!")
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise