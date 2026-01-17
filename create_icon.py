"""Script to generate the Writer Platform icon."""

from PIL import Image, ImageDraw
import os

def create_icon():
    """Create a professional writer's app icon."""
    # Create the largest size first, then resize for others
    size = 256

    # Create image with solid background (not transparent - better for system tray)
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Calculate proportions
    margin = size // 10

    # Background: rounded rectangle in deep blue/purple
    bg_color = (75, 85, 175)  # Professional deep blue-purple

    # Draw rounded rectangle background
    corner_radius = size // 5
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=corner_radius,
        fill=bg_color
    )

    # Draw a page/document in the center
    page_margin = size // 4
    page_color = (250, 250, 252)  # Almost white
    page_left = page_margin + 10
    page_top = page_margin
    page_right = size - page_margin - 10
    page_bottom = size - page_margin + 10

    # Page shadow
    shadow_offset = 4
    draw.rectangle(
        [page_left + shadow_offset, page_top + shadow_offset,
         page_right + shadow_offset, page_bottom + shadow_offset],
        fill=(50, 55, 120)
    )

    # Main page
    draw.rectangle(
        [page_left, page_top, page_right, page_bottom],
        fill=page_color,
        outline=(200, 200, 210),
        width=2
    )

    # Draw text lines on the page
    line_color = (120, 130, 180)
    line_y_start = page_top + 25
    line_spacing = 22
    for i in range(6):
        y = line_y_start + i * line_spacing
        if y < page_bottom - 20:
            x_start = page_left + 15
            x_end = page_right - 15
            # Vary line lengths
            if i == 5:
                x_end = x_start + (x_end - x_start) // 2
            elif i == 2:
                x_end = x_start + (x_end - x_start) * 3 // 4
            draw.line([(x_start, y), (x_end, y)], fill=line_color, width=3)

    # Draw a pen/pencil diagonally across
    pen_color = (255, 200, 50)  # Gold/yellow
    pen_dark = (200, 150, 30)  # Darker gold for detail

    # Pen body coordinates
    pen_x1, pen_y1 = size - margin - 30, margin + 50  # Top right
    pen_x2, pen_y2 = margin + 50, size - margin - 30  # Bottom left

    # Draw pen body (thicker line)
    pen_width = 18
    draw.line([(pen_x1, pen_y1), (pen_x2, pen_y2)], fill=pen_color, width=pen_width)

    # Pen tip (triangle at bottom-left end)
    tip_length = 25
    # Calculate direction
    import math
    angle = math.atan2(pen_y2 - pen_y1, pen_x2 - pen_x1)
    tip_x = pen_x2 + tip_length * math.cos(angle)
    tip_y = pen_y2 + tip_length * math.sin(angle)

    # Draw triangular tip
    perp_angle = angle + math.pi / 2
    half_width = pen_width // 2
    draw.polygon([
        (pen_x2 + half_width * math.cos(perp_angle), pen_y2 + half_width * math.sin(perp_angle)),
        (pen_x2 - half_width * math.cos(perp_angle), pen_y2 - half_width * math.sin(perp_angle)),
        (tip_x, tip_y)
    ], fill=(80, 80, 80))  # Dark gray tip

    # Eraser end (small rectangle at top-right end)
    eraser_color = (255, 150, 150)  # Pink
    eraser_length = 20
    ex1 = pen_x1 - eraser_length * math.cos(angle)
    ey1 = pen_y1 - eraser_length * math.sin(angle)
    draw.line([(pen_x1, pen_y1), (ex1, ey1)], fill=eraser_color, width=pen_width)

    # Save multiple sizes for ICO
    assets_dir = os.path.join(os.path.dirname(__file__), 'assets')
    os.makedirs(assets_dir, exist_ok=True)

    ico_path = os.path.join(assets_dir, 'icon.ico')
    png_path = os.path.join(assets_dir, 'icon.png')

    # Create images at different sizes
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for s in sizes:
        resized = img.resize((s, s), Image.Resampling.LANCZOS)
        images.append(resized)

    # Save ICO with multiple sizes
    # The first image is the default, append_images adds the rest
    images[-1].save(
        ico_path,
        format='ICO',
        append_images=images[:-1]
    )

    # Save high-res PNG
    img.save(png_path, format='PNG')

    print(f"Icon created: {ico_path}")
    print(f"Icon size: {os.path.getsize(ico_path)} bytes")
    print(f"PNG created: {png_path}")

    return ico_path

if __name__ == '__main__':
    create_icon()
