"""Create original local motion assets with Pillow and ffmpeg."""
import math
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageChops

out = Path(__file__).resolve().parents[1] / "public" / "media"
out.mkdir(parents=True, exist_ok=True)
w, h, fps, seconds = 960, 540, 24, 8
encoder = subprocess.Popen(["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", "-g", "12", "-movflags", "+faststart", str(out / "synora-flow.mp4")], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
for frame in range(fps * seconds):
    t = frame / (fps * seconds) * math.tau
    image = Image.new("RGB", (w, h), (8, 30, 23))
    glow = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(glow)
    cx, cy = 695 + 45 * math.sin(t), 265 + 30 * math.cos(t)
    for radius in range(330, 0, -8):
        power = (1-radius/340)**1.6
        draw.ellipse((cx-radius, cy-radius*.8, cx+radius, cy+radius*.8), fill=(int(10+power*34), int(30+power*59), int(23+power*27)))
    image = Image.blend(image, glow.filter(ImageFilter.GaussianBlur(35)), .85)
    lines = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(lines)
    for strand in range(85):
        points = []
        for step in range(220):
            a = step/219*math.tau
            twist = a+t+strand*.012
            radius = 125+strand*1.7+22*math.sin(a*3+t)
            points.append((cx+math.cos(a)*radius+38*math.sin(twist*2), cy+math.sin(a)*radius*.64+38*math.cos(twist)))
        light = (math.sin(strand*.13+t)+1)/2
        draw.line(points, fill=(int(35+light*54), int(80+light*83), int(49+light*47)))
    image = ImageChops.screen(image, lines)
    if frame == 0: image.save(out / "synora-flow.jpg", quality=90)
    encoder.stdin.write(image.tobytes())
encoder.stdin.close()
if encoder.wait(): raise RuntimeError("Video encoding failed")
print("Created local video and poster")
