from pathlib import Path
import base64, zipfile, shutil

ROOT = Path(__file__).resolve().parent
parts = []
for i in range(1, 8):
    parts.append((ROOT / f"emtready-build/payload.b64.{i:03d}").read_text(encoding="utf-8").strip())

raw = base64.b64decode("".join(parts))
zip_path = ROOT / "emtready_source.zip"
zip_path.write_bytes(raw)
extract = ROOT / "emtready_source"
if extract.exists():
    shutil.rmtree(extract)
with zipfile.ZipFile(zip_path) as z:
    z.extractall(extract)

src = extract / "EMTReady_NREMT_Beta_Project"
if not src.exists():
    raise SystemExit("EMTReady project directory not found in payload")

for name in ["index.html", "main.js", "package.json", "README.txt"]:
    shutil.copy2(src / name, ROOT / name)
(ROOT / "build").mkdir(exist_ok=True)
shutil.copy2(src / "build" / "icon.png", ROOT / "build" / "icon.png")
print("Prepared EMTReady NREMT beta source")
