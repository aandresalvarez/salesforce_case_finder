"""Detect WebView2 without importing the native UI or touching browser data."""
import os


def webview_available() -> bool:
    if os.name != "nt":
        return True
    import winreg

    suffix = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive, prefix in ((winreg.HKEY_CURRENT_USER, "SOFTWARE\\"),
                         (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\")):
        try:
            with winreg.OpenKey(hive, prefix + suffix) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
                if int(str(version).split(".")[0]) >= 86:
                    return True
        except (OSError, ValueError):
            continue
    return False
