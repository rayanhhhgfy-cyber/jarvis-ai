import { execSync } from "child_process";
import { type ToolHandler } from "./types";
import path from "path";
import { existsSync, mkdirSync } from "fs";

function powershell(script: string): string {
  const encoded = Buffer.from(script, "utf16le").toString("base64");
  return execSync(`powershell.exe -NoProfile -EncodedCommand ${encoded}`, {
    timeout: 15000,
    windowsHide: true,
  }).toString();
}

export const desktopType: ToolHandler = async (args, _ctx) => {
  const text = args.text as string;
  if (!text) return { success: false, error: "text is required" };

  try {
    const escaped = text.replace(/'/g, "''");
    powershell(`
      Add-Type -AssemblyName System.Windows.Forms
      [System.Windows.Forms.SendKeys]::SendWait('${escaped}')
    `);
    return { success: true, data: { message: `Typed "${text}" into active window` } };
  } catch (err) {
    return { success: false, error: `Failed to type: ${(err as Error).message}` };
  }
};

export const desktopClick: ToolHandler = async (args, _ctx) => {
  const x = args.x as number;
  const y = args.y as number;
  if (x === undefined || y === undefined) return { success: false, error: "x and y coordinates required" };

  try {
    powershell(`
      Add-Type @"
        using System;
        using System.Runtime.InteropServices;
        public class Mouse {
          [DllImport("user32.dll")]
          public static extern bool SetCursorPos(int x, int y);
          [DllImport("user32.dll")]
          public static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, int dwExtraInfo);
        }
"@
      [Mouse]::SetCursorPos(${x}, ${y})
      Start-Sleep -Milliseconds 50
      [Mouse]::mouse_event(0x0002, 0, 0, 0, 0)
      Start-Sleep -Milliseconds 50
      [Mouse]::mouse_event(0x0004, 0, 0, 0, 0)
    `);
    return { success: true, data: { message: `Clicked at (${x}, ${y})` } };
  } catch (err) {
    return { success: false, error: `Failed to click: ${(err as Error).message}` };
  }
};

export const desktopScreenshot: ToolHandler = async (_args, _ctx) => {
  try {
    const screenshotsDir = path.join(process.cwd(), "data", "screenshots");
    if (!existsSync(screenshotsDir)) mkdirSync(screenshotsDir, { recursive: true });
    const filename = `screenshot_${Date.now()}.png`;
    const filepath = path.join(screenshotsDir, filename);

    powershell(`
      Add-Type -AssemblyName System.Windows.Forms,System.Drawing
      $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
      $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
      $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
      $graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bounds.Size)
      $bitmap.Save('${filepath.replace(/\\/g, "\\\\")}', [System.Drawing.Imaging.ImageFormat]::Png)
      $graphics.Dispose()
      $bitmap.Dispose()
    `);

    return { success: true, data: { message: "Desktop screenshot captured", path: filepath } };
  } catch (err) {
    return { success: false, error: `Failed to capture screenshot: ${(err as Error).message}` };
  }
};
