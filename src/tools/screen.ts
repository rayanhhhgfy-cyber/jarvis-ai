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

export const captureScreen: ToolHandler = async (_args, _ctx) => {
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

    return { success: true, data: { message: "Screen capture saved", path: filepath, width: 1920, height: 1080 } };
  } catch (err) {
    return { success: false, error: `Failed to capture screen: ${(err as Error).message}` };
  }
};
