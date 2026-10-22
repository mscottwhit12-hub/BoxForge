#!/usr/bin/env python3
"""Write assets/boxforge.ico and assets/boxforge.png from the app's own icon drawing.   python tools/make_icon.py
Needs Pillow. Run python build.py first so dieline_generator.py is current."""
import importlib.util, os, sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dg", os.path.join(ROOT, "dieline_generator.py"))
dg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dg)


def icon(n):
    im = Image.new("RGBA", (n, n))
    im.putdata([px for row in dg.icon_pixels(n) for px in row])
    return im


out = os.path.join(ROOT, "assets")
os.makedirs(out, exist_ok=True)
big = icon(256)
big.save(os.path.join(out, "boxforge.png"))
big.save(os.path.join(out, "boxforge.ico"), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
# macOS .icns: a small container of PNG pictures (type code + length + data), written here without any extra tool
import io, struct
chunks = []
for code, n in ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024)):
    buf = io.BytesIO()
    icon(n).save(buf, "PNG")
    chunks.append(code + struct.pack(">I", 8 + len(buf.getvalue())) + buf.getvalue())
body = b"".join(chunks)
with open(os.path.join(out, "boxforge.icns"), "wb") as fh:
    fh.write(b"icns" + struct.pack(">I", 8 + len(body)) + body)
print("wrote", os.path.join(out, "boxforge.ico"), ", boxforge.icns and boxforge.png")
