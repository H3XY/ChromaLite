"""Writes the Windows version resource for the .exe (shown under Properties > Details),
taking the version from APP_VERSION in prismatic.pyw. Usage: make_version_info.py OUT_FILE"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def app_version():
    with open(os.path.join(ROOT, "prismatic.pyw"), encoding="utf-8") as f:
        return re.search(r'^APP_VERSION = "(\d+)\.(\d+)\.(\d+)"', f.read(), re.M).groups()


def main():
    major, minor, patch = app_version()
    v = f"{major}.{minor}.{patch}"
    nums = f"({major}, {minor}, {patch}, 0)"
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Prismatic project (H3XY)'),
      StringStruct('FileDescription', 'Prismatic - lighting app for keyboards, mice and mousepads'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'Prismatic'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 H3XY. MIT License.'),
      StringStruct('OriginalFilename', 'Prismatic.exe'),
      StringStruct('ProductName', 'Prismatic'),
      StringStruct('ProductVersion', '{v}'),
      StringStruct('Comments', 'Open source: https://github.com/H3XY/Prismatic')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write(text)
    print("version", v)


if __name__ == "__main__":
    main()
