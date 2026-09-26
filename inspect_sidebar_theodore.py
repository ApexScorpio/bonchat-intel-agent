import sys
import os
import time
import ctypes
import win32gui
import win32ui
import win32con
from PIL import Image

sys.path.insert(0, r"S:\Users\lopes\Documents\Scrips\bonchat-intel-agent")
from src.desktop_isolation import set_thread_to_ghost_desktop, get_ghost_windows

user32 = ctypes.windll.user32

def capture_hwnd(hwnd):
    wr = win32gui.GetWindowRect(hwnd)
    w, h = wr[2] - wr[0], wr[3] - wr[1]
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    save_bit_map = win32ui.CreateBitmap()
    save_bit_map.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(save_bit_map)
    user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
    bmp_info = save_bit_map.GetInfo()
    bmp_str = save_bit_map.GetBitmapBits(True)
    img = Image.frombuffer('RGB', (bmp_info['bmWidth'], bmp_info['bmHeight']), bmp_str, 'raw', 'BGRX', 0, 1)
    win32gui.DeleteObject(save_bit_map.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return img

def click(hwnd, x, y):
    lp = (int(y) << 16) | (int(x) & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0201, 0x0001, lp)
    time.sleep(0.06)
    user32.PostMessageW(hwnd, 0x0202, 0, lp)
    time.sleep(0.2)

def main():
    set_thread_to_ghost_desktop()
    ghost_wins = get_ghost_windows()
    bonchat_hwnd = None
    for w in ghost_wins:
        t = w.get("title", "").lower()
        c = w.get("class", "").lower()
        if "bonchat" in t or "bonchat" in c or "ajuda" in t:
            bonchat_hwnd = w["hwnd"]
            break
            
    if not bonchat_hwnd:
        print("BonChat not found on TIMI_GHOST")
        return

    print(f"BonChat HWND: {bonchat_hwnd}")
    
    # 1. Reset search if open: click the (x) at (208, 95)
    click(bonchat_hwnd, 208, 95)
    time.sleep(0.5)
    
    # Capture window
    img = capture_hwnd(bonchat_hwnd)
    img.save(r"S:\Users\lopes\Documents\Scrips\bonchat-intel-agent\data\current_full_bonchat.png")
    
    # Crop sidebar (approx x: 50 to 250, y: 130 to 700)
    sidebar = img.crop((50, 130, 260, img.height))
    sidebar.save(r"S:\Users\lopes\Documents\Scrips\bonchat-intel-agent\data\sidebar_cropped.png")
    print("Saved current_full_bonchat.png and sidebar_cropped.png")

if __name__ == "__main__":
    main()
