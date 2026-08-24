import os
import io
from PIL import Image, ImageDraw, ImageFont

COLOR_HEX_MAP = {
    "brown": "#8B4513",
    "light_blue": "#38BDF8",
    "pink": "#F472B6",
    "orange": "#FB923C",
    "red": "#EF4444",
    "yellow": "#FACC15",
    "green": "#22C55E",
    "dark_blue": "#1D4ED8",
}

from stats_db import get_player_stats

PLAYER_NEON_SCHEMES = [
    {"rgb": (255, 0, 85),   "hex": "#FF0055", "label": "P1"},  # Neon Pink/Red
    {"rgb": (0, 240, 255),  "hex": "#00F0FF", "label": "P2"},  # Neon Cyan
    {"rgb": (57, 255, 20),  "hex": "#39FF14", "label": "P3"},  # Neon Green
    {"rgb": (255, 230, 0),  "hex": "#FFE600", "label": "P4"},  # Neon Gold
]

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "board_template.png")

def get_font(size=14, bold=False):
    font_candidates = [
        "arialbd.ttf" if bold else "arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for font_name in font_candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except IOError:
            continue
    return ImageFont.load_default()

def get_tile_bounds(pos: int, W: int, H: int) -> tuple[int, int, int, int]:
    # Exact board grid alignment for clean board_template.png
    margin_x_left = int(0.140 * W)
    margin_x_right = int(0.860 * W)
    margin_y_top = int(0.145 * H)
    margin_y_bottom = int(0.855 * H)

    tile_w = (margin_x_right - margin_x_left) / 9.0
    tile_h = (margin_y_bottom - margin_y_top) / 9.0

    if pos == 0:  # Top-Left START
        return (0, 0, margin_x_left, margin_y_top)
    elif pos == 10:  # Top-Right JAIL
        return (margin_x_right, 0, W, margin_y_top)
    elif pos == 20:  # Bottom-Right VACATION
        return (margin_x_right, margin_y_bottom, W, H)
    elif pos == 30:  # Bottom-Left GO TO JAIL
        return (0, margin_y_bottom, margin_x_left, H)
    elif 1 <= pos <= 9:  # Top Row (left to right, pos 1 next to START, pos 9 next to JAIL)
        step = pos - 1
        x1 = int(margin_x_left + step * tile_w)
        x2 = int(x1 + tile_w)
        return (x1, int(0.015 * H), x2, margin_y_top)
    elif 11 <= pos <= 19:  # Right Column (top to bottom, pos 11 below JAIL, pos 19 above VACATION)
        step = pos - 11
        y1 = int(margin_y_top + step * tile_h)
        y2 = int(y1 + tile_h)
        return (margin_x_right, y1, int(0.985 * W), y2)
    elif 21 <= pos <= 29:  # Bottom Row (right to left, pos 21 next to VACATION, pos 29 next to GO TO JAIL)
        step = pos - 21
        x2 = int(margin_x_right - step * tile_w)
        x1 = int(x2 - tile_w)
        return (x1, margin_y_bottom, x2, int(0.985 * H))
    elif 31 <= pos <= 39:  # Left Column (bottom to top, pos 31 above GO TO JAIL, pos 39 below START)
        step = pos - 31
        y2 = int(margin_y_bottom - step * tile_h)
        y1 = int(y2 - tile_h)
        return (int(0.015 * W), y1, margin_x_left, y2)
    raise ValueError(f"Invalid position {pos}")

def render_board_base(game) -> Image.Image:
    """Renders the static board template with owner colors, banners, prices, and properties."""
    if os.path.exists(TEMPLATE_PATH):
        base_img = Image.open(TEMPLATE_PATH).convert("RGBA")
    else:
        # High quality dark neon fallback canvas if template image missing
        base_img = Image.new("RGBA", (1200, 960), (10, 15, 29, 255))

    W, H = base_img.size

    # Create overlay layer for translucent glows, owner banners, and clean text
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_tiny = get_font(max(8, int(W * 0.009)), bold=False)

    # 1. Overlay Dynamic Property Text, Owner Badges, Recolor Banners & Mortgaged Status
    for pos in range(40):
        x1, y1, x2, y2 = get_tile_bounds(pos, W, H)
        tile = game.board[pos]
        tile_type = tile["type"]
        is_mortgaged = tile.get("is_mortgaged", False)
        tile_w = x2 - x1
        tile_h = y2 - y1

        # Determine inner text slot zone and banner rectangle for each tile side
        pad = 2
        banner_rect = None
        if 1 <= pos <= 9:
            # Top row: color bar at BOTTOM
            cx1 = x1 + pad
            cy1 = y1 + pad
            cx2 = x2 - pad
            cy2 = y2 - int(tile_h * 0.28)
            banner_rect = (x1 + 1, cy2, x2 - 1, y2 - 1)
        elif 11 <= pos <= 19:
            # Right column: color bar on LEFT
            cx1 = x1 + int(tile_w * 0.28)
            cy1 = y1 + pad
            cx2 = x2 - pad
            cy2 = y2 - pad
            banner_rect = (x1 + 1, y1 + 1, cx1, y2 - 1)
        elif 21 <= pos <= 29:
            # Bottom row: color bar at TOP (closest to center)
            cx1 = x1 + pad
            cy1 = y1 + int(tile_h * 0.28)
            cx2 = x2 - pad
            cy2 = y2 - pad
            banner_rect = (x1 + 1, y1 + 1, x2 - 1, cy1)
        elif 31 <= pos <= 39:
            # Left column: color bar on RIGHT
            cx1 = x1 + pad
            cy1 = y1 + pad
            cx2 = x2 - int(tile_w * 0.28)
            cy2 = y2 - pad
            banner_rect = (cx2, y1 + 1, x2 - 1, y2 - 1)
        else:
            cx1, cy1, cx2, cy2 = x1, y1, x2, y2

        # Color tiles by owner: recolor banner and background when owned
        if pos in game.properties_owned:
            owner_id = game.properties_owned[pos]
            owner_idx = next((i for i, p in enumerate(game.player_list) if p.id == owner_id), 0)
            scheme = PLAYER_NEON_SCHEMES[owner_idx % len(PLAYER_NEON_SCHEMES)]
            r, g, b = scheme["rgb"]

            # 1. Recolor banner / header with owner's neon color
            if banner_rect and tile_type == "property":
                bx1, by1, bx2, by2 = banner_rect
                draw.rectangle([bx1, by1, bx2, by2], fill=(r, g, b, 235))
                draw.rectangle([bx1, by1, bx2, by2], outline=(255, 255, 255, 180), width=1)

            # 2. Recolor inner tile card background with glowing owner tint
            draw.rectangle([cx1, cy1, cx2, cy2], fill=(r, g, b, 50))

            # 3. Glowing owner border outline around tile frame
            draw.rectangle([cx1 - 1, cy1 - 1, cx2 + 1, cy2 + 1], outline=(r, g, b, 120), width=3)
            draw.rectangle([cx1, cy1, cx2, cy2], outline=(r, g, b, 255), width=2)

            # 4. Owner Badge (P1, P2...) in top-left of text slot
            badge_font = get_font(max(8, int(min(tile_w, tile_h) * 0.14)), bold=True)
            draw.rectangle([cx1 + 2, cy1 + 2, cx1 + 18, cy1 + 12], fill=(r, g, b, 240))
            draw.text((cx1 + 10, cy1 + 7), scheme["label"], fill=(0, 0, 0, 255), font=badge_font, anchor="mm")

        # Overlay text & elements directly onto template (NO opaque box fill)
        if pos not in (0, 10, 20, 30):
            clean_label = ""
            clean_label2 = ""

            if tile_type == "property":
                city_name = tile.get("city", "")
                if not city_name:
                    raw_name = tile.get("name", "")
                    city_name = raw_name.split(",")[0].strip()
                # Clean non-ASCII / emoji characters
                city_name = "".join([c for c in city_name if ord(c) < 128 or ord(c) > 255]).strip()
                if not city_name:
                    city_name = tile.get("country", "CITY")

                words = city_name.upper().split()
                if len(words) == 1:
                    clean_label = words[0]
                    clean_label2 = ""
                elif len(words) == 2:
                    clean_label = words[0]
                    clean_label2 = words[1]
                else:
                    mid = len(words) // 2
                    clean_label = " ".join(words[:mid])
                    clean_label2 = " ".join(words[mid:])

            elif tile_type == "community_chest":
                clean_label = "WORLD"
                clean_label2 = "TREASURY"
            elif tile_type == "chance":
                clean_label = "GLOBAL"
                clean_label2 = "NEWS"
            elif tile_type == "tax":
                clean_label = "TAX"
                clean_label2 = ""
            elif tile_type == "railroad":
                raw_name = tile.get("name", "")
                airport_parts = [w for w in raw_name.replace("✈️", "").split() if w.lower() not in ("international", "airport")]
                clean_label = airport_parts[0].upper() if airport_parts else "JFK"
                clean_label2 = "AIRPORT"
            elif tile_type == "utility":
                raw_name = tile.get("name", "")
                utility_parts = [w for w in raw_name.replace("⚡", "").replace("📡", "").replace("☢️", "").replace("🛰️", "").split()]
                clean_label = utility_parts[0].upper() if utility_parts else "UTILITY"
                clean_label2 = utility_parts[1].upper() if len(utility_parts) > 1 else ""
            else:
                clean_label = tile_type.upper()

            # Dynamic Font Sizing to fit slot box
            box_w = cx2 - cx1
            box_h = cy2 - cy1
            narrow = min(box_w, box_h)

            base_size = max(8, min(12, int(narrow * 0.20)))
            tile_font = get_font(base_size, bold=True)
            price_font = get_font(max(7, base_size - 2), bold=True)

            text_x = (cx1 + cx2) // 2

            if tile_type == "property":
                line_gap = base_size + 2
                num_lines = 2 if clean_label2 else 1
                total_h = line_gap * num_lines
                center_y = (cy1 + cy2) // 2 - 4

                ty1 = center_y - total_h // 2 + line_gap // 2

                # Text with drop shadow for high contrast
                draw.text((text_x + 1, ty1 + 1), clean_label, fill=(0, 0, 0, 240), font=tile_font, anchor="mm")
                draw.text((text_x, ty1), clean_label, fill=(255, 255, 255, 255), font=tile_font, anchor="mm")

                if clean_label2:
                    draw.text((text_x + 1, ty1 + line_gap + 1), clean_label2, fill=(0, 0, 0, 240), font=tile_font, anchor="mm")
                    draw.text((text_x, ty1 + line_gap), clean_label2, fill=(255, 255, 255, 255), font=tile_font, anchor="mm")

                # Price at bottom of tile slot if unowned
                if pos not in game.properties_owned:
                    price = tile.get("price", 0)
                    draw.text((text_x + 1, cy2 - base_size // 2 - 1), f"${price}", fill=(0, 0, 0, 240), font=price_font, anchor="mm")
                    draw.text((text_x, cy2 - base_size // 2 - 2), f"${price}", fill=(0, 240, 255, 255), font=price_font, anchor="mm")

            else:
                line_gap = base_size + 2
                num_lines = 2 if clean_label2 else 1
                total_h = line_gap * num_lines
                center_y = (cy1 + cy2) // 2 - 4
                ty1 = center_y - total_h // 2 + line_gap // 2

                draw.text((text_x + 1, ty1 + 1), clean_label, fill=(0, 0, 0, 240), font=tile_font, anchor="mm")
                draw.text((text_x, ty1), clean_label, fill=(255, 235, 170, 255), font=tile_font, anchor="mm")

                if clean_label2:
                    draw.text((text_x + 1, ty1 + line_gap + 1), clean_label2, fill=(0, 0, 0, 240), font=tile_font, anchor="mm")
                    draw.text((text_x, ty1 + line_gap), clean_label2, fill=(255, 235, 170, 255), font=tile_font, anchor="mm")

                if tile_type in ("railroad", "utility") and pos not in game.properties_owned:
                    price = tile.get("price", 0)
                    draw.text((text_x, cy2 - base_size // 2 - 2), f"${price}", fill=(0, 240, 255, 255), font=price_font, anchor="mm")
                elif tile_type == "tax":
                    amount = tile.get("amount", 0)
                    draw.text((text_x, cy2 - base_size // 2 - 2), f"-${amount}", fill=(255, 80, 80, 255), font=price_font, anchor="mm")

            # Draw Mortgaged Status Overlay
            if is_mortgaged:
                draw.rectangle([cx1 + 2, (cy1 + cy2)//2 - 8, cx2 - 2, (cy1 + cy2)//2 + 8], fill=(220, 20, 40, 200))
                draw.text((text_x, (cy1 + cy2)//2), "MORTGAGED", fill=(255, 255, 255, 255), font=price_font, anchor="mm")

            # Draw Houses/Skyscraper Indicator on Corner
            houses = tile.get("houses", 0)
            if houses > 0:
                h_text = "SKY" if houses == 5 else f"{houses}H"
                hw = 24
                hh = 12
                draw.rectangle([cx2 - hw - 2, cy1 + 2, cx2 - 2, cy1 + hh + 2], fill=(0, 220, 130, 240))
                draw.text((cx2 - hw // 2 - 2, cy1 + hh // 2 + 2), h_text, fill=(0, 0, 0, 255), font=font_tiny, anchor="mm")

    return Image.alpha_composite(base_img, overlay)

def draw_player_tokens_on_image(base_img: Image.Image, game, positions_override: dict[int, int] | None = None) -> Image.Image:
    """Draws multi-layer glowing player tokens on the pre-rendered board image."""
    W, H = base_img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font_tiny = get_font(max(8, int(W * 0.009)), bold=False)

    pos_players: dict[int, list[int]] = {}
    for idx, player in enumerate(game.player_list):
        state = game.get_player_state(player.id)
        if not state.get("bankrupt", False):
            if positions_override and player.id in positions_override:
                p = positions_override[player.id]
            else:
                p = state["position"]
            pos_players.setdefault(p, []).append(idx)

    for pos, player_indices in pos_players.items():
        x1, y1, x2, y2 = get_tile_bounds(pos, W, H)
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        count = len(player_indices)

        for i, p_idx in enumerate(player_indices):
            offset_x = int((i - (count - 1) / 2) * (W * 0.022))
            tx = center_x + offset_x
            ty = center_y + int(H * 0.015) if pos not in (0, 10, 20, 30) else center_y

            scheme = PLAYER_NEON_SCHEMES[p_idx % len(PLAYER_NEON_SCHEMES)]
            r, g, b = scheme["rgb"]

            # Layer 1: Translucent Glowing Aura
            r_aura = int(W * 0.018)
            draw.ellipse([tx - r_aura, ty - r_aura, tx + r_aura, ty + r_aura], fill=(r, g, b, 70))

            # Layer 2: Secondary Bloom Ring
            r_bloom = int(W * 0.014)
            draw.ellipse([tx - r_bloom, ty - r_bloom, tx + r_bloom, ty + r_bloom], fill=(r, g, b, 140))

            # Layer 3: Crisp Outer White Ring
            r_ring = int(W * 0.011)
            draw.ellipse([tx - r_ring, ty - r_ring, tx + r_ring, ty + r_ring], outline=(255, 255, 255, 255), width=2)

            # Layer 4: Solid Neon Core
            r_core = int(W * 0.009)
            draw.ellipse([tx - r_core, ty - r_core, tx + r_core, ty + r_core], fill=(r, g, b, 240))

            # Layer 5: Centered Player Label
            draw.text((tx, ty), scheme["label"], fill=(255, 255, 255, 255), font=font_tiny, anchor="mm")

    return Image.alpha_composite(base_img, overlay).convert("RGB")

def render_board_image(game, positions_override: dict[int, int] | None = None) -> io.BytesIO:
    """Renders a static single PNG frame of the board."""
    base_img = render_board_base(game)
    final_img = draw_player_tokens_on_image(base_img, game, positions_override)

    buf = io.BytesIO()
    final_img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

def render_board_movement_animation(game, moving_player_id: int, start_pos: int, end_pos: int) -> io.BytesIO:
    """
    Renders an animated GIF showing the token sliding tile-by-tile from start_pos to end_pos.
    Intermediate frames have short durations and the final frame pauses.
    """
    # Calculate stepping path along the 40-tile perimeter track
    if start_pos == end_pos:
        path = [start_pos]
    elif end_pos > start_pos:
        path = list(range(start_pos, end_pos + 1))
    else:
        # Wrapped around GO
        path = list(range(start_pos, 40)) + list(range(0, end_pos + 1))

    if len(path) <= 1:
        return render_board_image(game)

    base_img = render_board_base(game)
    frames = []

    for step_pos in path:
        frame_img = draw_player_tokens_on_image(base_img, game, {moving_player_id: step_pos})
        # Resize slightly to keep animated GIF compact & super snappy in Discord chat
        frame_img = frame_img.resize((960, 768), Image.Resampling.BILINEAR)
        # Convert to P mode with adaptive palette for crisp GIF color compression
        frames.append(frame_img.convert("P", palette=Image.Palette.ADAPTIVE))

    # Intermediate steps ~190ms, resting frame ~1300ms
    durations = [190] * (len(frames) - 1) + [1300]

    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True
    )
    buf.seek(0)
    return buf
