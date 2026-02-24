"""
WizerBet Brand Asset Generator
Generates: logo, favicon, PWA icons, apple-touch-icon, OG image
"""

from PIL import Image, ImageDraw, ImageFont
import os
import struct
import io

# ── Brand Colors ──────────────────────────────────────────────
BRAND_BG = "#0f1117"       # Dark background
BRAND_ACCENT = "#1abc9c"   # Teal/emerald accent
BRAND_GOLD = "#f0b90b"     # Gold for "Bet" accent
BRAND_WHITE = "#ffffff"
BRAND_SURFACE = "#1a1d27"
BRAND_SUBTLE = "#8b95a5"

# ── Paths ─────────────────────────────────────────────────────
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "public")
os.makedirs(OUT_DIR, exist_ok=True)


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def hex_to_rgba(h, a=255):
    return hex_to_rgb(h) + (a,)


def get_font(size):
    """Try to load a good system font, fall back gracefully."""
    font_candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def get_bold_font(size):
    """Try to load a bold system font."""
    font_candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def draw_rounded_rect(draw, xy, radius, fill):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    # Four corners
    draw.ellipse([x0, y0, x0 + 2*radius, y0 + 2*radius], fill=fill)
    draw.ellipse([x1 - 2*radius, y0, x1, y0 + 2*radius], fill=fill)
    draw.ellipse([x0, y1 - 2*radius, x0 + 2*radius, y1], fill=fill)
    draw.ellipse([x1 - 2*radius, y1 - 2*radius, x1, y1], fill=fill)
    # Two rectangles to fill the body
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)


def create_icon(size, padding_ratio=0.12):
    """Create WizerBet icon at given size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    padding = int(size * padding_ratio)
    radius = int(size * 0.18)

    # Background rounded square
    draw_rounded_rect(draw, [padding, padding, size - padding, size - padding],
                      radius, hex_to_rgb(BRAND_BG))

    # Inner accent border (subtle glow)
    inner_pad = padding + int(size * 0.02)
    inner_radius = radius - int(size * 0.02)

    # Draw the "W" letter - clean and bold
    font_size = int(size * 0.48)
    font = get_bold_font(font_size)

    text = "W"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Center the W
    tx = (size - tw) // 2
    ty = (size - th) // 2 - int(size * 0.04)

    # Draw W in accent color
    draw.text((tx, ty), text, fill=hex_to_rgb(BRAND_ACCENT), font=font)

    # Small accent dot/bar under the W
    bar_w = int(size * 0.25)
    bar_h = max(int(size * 0.035), 2)
    bar_x = (size - bar_w) // 2
    bar_y = ty + th + int(size * 0.04)

    draw_rounded_rect(draw, [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                      bar_h // 2, hex_to_rgb(BRAND_GOLD))

    return img


def create_favicon_ico(sizes=[16, 32, 48]):
    """Create a multi-resolution .ico file."""
    images = []
    for s in sizes:
        icon = create_icon(s, padding_ratio=0.06)
        # Convert to RGBA
        images.append(icon)

    path = os.path.join(OUT_DIR, "favicon.ico")
    images[0].save(path, format="ICO", sizes=[(s, s) for s in sizes],
                   append_images=images[1:])
    print(f"  Created: favicon.ico ({', '.join(f'{s}x{s}' for s in sizes)})")


def create_og_image():
    """Create Open Graph image (1200x630)."""
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), hex_to_rgb(BRAND_BG))
    draw = ImageDraw.Draw(img)

    # Subtle gradient-like background pattern (horizontal stripes)
    for y in range(h):
        # Slight gradient from top-left to bottom-right
        r_base, g_base, b_base = hex_to_rgb(BRAND_BG)
        factor = y / h * 0.15
        r = min(255, int(r_base + factor * 30))
        g = min(255, int(g_base + factor * 35))
        b = min(255, int(b_base + factor * 45))
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Accent line at top
    draw.rectangle([0, 0, w, 4], fill=hex_to_rgb(BRAND_ACCENT))

    # Draw the icon (small)
    icon_size = 120
    icon = create_icon(icon_size, padding_ratio=0.0)
    icon_x = (w - icon_size) // 2
    icon_y = 100
    img.paste(icon, (icon_x, icon_y), icon)

    # Brand name "WizerBet"
    title_font = get_bold_font(72)
    title = "WizerBet"
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    tx = (w - tw) // 2
    ty = icon_y + icon_size + 40

    # Draw "Wizer" in white, "Bet" in accent
    wizer_font = get_bold_font(72)
    bet_font = get_bold_font(72)

    wizer = "Wizer"
    bet = "Bet"

    wizer_bbox = draw.textbbox((0, 0), wizer, font=wizer_font)
    bet_bbox = draw.textbbox((0, 0), bet, font=bet_font)

    total_w = (wizer_bbox[2] - wizer_bbox[0]) + (bet_bbox[2] - bet_bbox[0])
    start_x = (w - total_w) // 2

    draw.text((start_x, ty), wizer, fill=hex_to_rgb(BRAND_WHITE), font=wizer_font)
    draw.text((start_x + wizer_bbox[2] - wizer_bbox[0], ty), bet,
              fill=hex_to_rgb(BRAND_ACCENT), font=bet_font)

    # Tagline
    tagline_font = get_font(28)
    tagline = "AI-Powered Football Betting Intelligence"
    bbox = draw.textbbox((0, 0), tagline, font=tagline_font)
    tagline_w = bbox[2] - bbox[0]
    tagline_x = (w - tagline_w) // 2
    tagline_y = ty + 90
    draw.text((tagline_x, tagline_y), tagline, fill=hex_to_rgb(BRAND_SUBTLE), font=tagline_font)

    # Feature pills at the bottom
    pill_font = get_font(18)
    pills = ["15 Leagues", "AI Predictions", "Value Bets", "Live Odds"]
    pill_gap = 24
    pill_h = 36
    pill_padding_x = 20

    # Calculate total width
    pill_widths = []
    for pill_text in pills:
        bbox = draw.textbbox((0, 0), pill_text, font=pill_font)
        pill_widths.append(bbox[2] - bbox[0] + pill_padding_x * 2)

    total_pills_w = sum(pill_widths) + pill_gap * (len(pills) - 1)
    pill_start_x = (w - total_pills_w) // 2
    pill_y = tagline_y + 70

    cx = pill_start_x
    for i, (pill_text, pw) in enumerate(zip(pills, pill_widths)):
        # Pill background
        draw_rounded_rect(draw, [cx, pill_y, cx + pw, pill_y + pill_h],
                         pill_h // 2, hex_to_rgb(BRAND_SURFACE))
        # Pill text
        bbox = draw.textbbox((0, 0), pill_text, font=pill_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        text_x = cx + (pw - text_w) // 2
        text_y = pill_y + (pill_h - text_h) // 2 - 2
        draw.text((text_x, text_y), pill_text, fill=hex_to_rgb(BRAND_ACCENT), font=pill_font)
        cx += pw + pill_gap

    # Bottom accent line
    draw.rectangle([0, h - 4, w, h], fill=hex_to_rgb(BRAND_ACCENT))

    path = os.path.join(OUT_DIR, "og-image.png")
    img.save(path, "PNG", optimize=True)
    print(f"  Created: og-image.png (1200x630)")


def create_logo_svg():
    """Create the main SVG logo for the brand."""
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 48" fill="none">
  <rect x="2" y="2" width="44" height="44" rx="10" fill="#0f1117"/>
  <text x="24" y="30" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-weight="700" font-size="26" fill="#1abc9c">W</text>
  <rect x="14" y="36" width="20" height="3" rx="1.5" fill="#f0b90b"/>
  <text x="56" y="33" font-family="Segoe UI, Arial, sans-serif" font-weight="700" font-size="28" fill="#ffffff">Wizer</text>
  <text x="134" y="33" font-family="Segoe UI, Arial, sans-serif" font-weight="700" font-size="28" fill="#1abc9c">Bet</text>
</svg>'''

    path = os.path.join(OUT_DIR, "logo.svg")
    with open(path, "w") as f:
        f.write(svg)
    print(f"  Created: logo.svg")


def create_favicon_svg():
    """Create SVG favicon for modern browsers."""
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
  <rect width="48" height="48" rx="10" fill="#0f1117"/>
  <text x="24" y="30" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-weight="700" font-size="26" fill="#1abc9c">W</text>
  <rect x="14" y="36" width="20" height="3" rx="1.5" fill="#f0b90b"/>
</svg>'''

    path = os.path.join(OUT_DIR, "favicon.svg")
    with open(path, "w") as f:
        f.write(svg)
    print(f"  Created: favicon.svg")


def main():
    print("🎨 Generating WizerBet brand assets...\n")

    # 1. SVG assets
    print("SVG Assets:")
    create_logo_svg()
    create_favicon_svg()

    # 2. PNG icons at various sizes
    print("\nPNG Icons:")
    for size, name in [(16, "icon-16.png"), (32, "icon-32.png"),
                       (180, "apple-touch-icon.png"),
                       (192, "icon-192.png"), (512, "icon-512.png")]:
        pad = 0.06 if size <= 32 else 0.08 if size <= 180 else 0.12
        icon = create_icon(size, padding_ratio=pad)
        path = os.path.join(OUT_DIR, name)
        icon.save(path, "PNG", optimize=True)
        print(f"  Created: {name} ({size}x{size})")

    # 3. Favicon ICO
    print("\nFavicon:")
    create_favicon_ico([16, 32, 48])

    # 4. OG Image
    print("\nOG Image:")
    create_og_image()

    print("\n✅ All brand assets generated successfully!")
    print(f"   Output directory: {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    main()
