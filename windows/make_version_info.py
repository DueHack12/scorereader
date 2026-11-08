"""Write windows/version_info.txt for PyInstaller's --version-file: the details Windows shows under the .exe's
Properties > Details (product name, version, description). Real version details make the .exe look like the normal
app it is, which helps with antivirus false positives. The version comes from scorereader.py's __version__."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def version() -> str:
    with open(os.path.join(ROOT, "scorereader.py"), encoding="utf-8") as f:
        m = re.search(r'^__version__ = "([^"]+)"', f.read(), re.M)
    return m.group(1) if m else "0.0.0"


def version_info(v: str) -> str:
    nums = [int(x) for x in re.findall(r"\d+", v)[:4]]
    nums += [0] * (4 - len(nums))
    t = "(" + ", ".join(map(str, nums)) + ")"
    strings = {
        "CompanyName": "ScoreReader",
        "FileDescription": "ScoreReader - scoreboard data for vMix and OSE",
        "FileVersion": v,
        "InternalName": "ScoreReader",
        "LegalCopyright": "Copyright (c) 2026 Jack Singewald - MIT License",
        "OriginalFilename": "ScoreReader.exe",
        "ProductName": "ScoreReader",
        "ProductVersion": v,
    }
    table = ",\n          ".join(f"StringStruct({k!r}, {val!r})" for k, val in strings.items())
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
          {table}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "version_info.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(version_info(version()))
    print(f"Wrote {out} (ScoreReader {version()})")
