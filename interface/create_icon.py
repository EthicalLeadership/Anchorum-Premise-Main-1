#!/usr/bin/env python3
from PIL import Image, ImageDraw
import os

def create_anchorum_icon():
    size = 512
    img = Image.new('RGB', (size, size), color=(26, 54, 93))
    draw = ImageDraw.Draw(img)
    
    # Draw scale icon
    cx, cy = size // 2, size // 2
    
    # Scale base
    draw.rectangle([cx - 100, cy - 15, cx + 100, cy + 15], outline=(246, 173, 85), width=12)
    
    # Scale pans
    draw.line([cx - 90, cy - 15, cx - 50, cy - 80], fill=(246, 173, 85), width=12)
    draw.line([cx + 90, cy - 15, cx + 50, cy - 80], fill=(246, 173, 85), width=12)
    
    # Save icon
    icon_path = os.path.join(os.path.dirname(__file__), 'public', 'icon.png')
    os.makedirs(os.path.dirname(icon_path), exist_ok=True)
    img.save(icon_path, 'PNG')
    print(f"✅ Icon created: {icon_path}")

if __name__ == "__main__":
    create_anchorum_icon()
