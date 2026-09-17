"""
board_renderer.py - High-Fidelity 20-Tile Board Renderer for Territory Wars

Features:
- Clean 6x6 perimeter layout (20 tiles: 4 corners + 4 inner tiles per side)
- Modern dark matte aesthetic matching the provided reference image
- High-contrast card surfaces:
    * START corner (glowing cyan neon frame)
    * DEAD ZONE corners (hazard stripes + warning triangle)
    * NEUTRAL / DRAW cards (sleek slate deck cards)
    * PROPERTY cards (clean card surface, color banner, Climate/Terrain/Economy stats)
- Center Scorecard Panel displaying:
    * Player color badge
    * Player name & cash
    * Territory count (e.g. 3/14)
    * Real-time 3-circle strike indicators (unfilled vs filled red)
- Dynamic ownership highlights with owner badges (P1, P2, P3, P4)
- Multi-layer glowing player tokens with collision offsets
- Static layer caching (composite dynamic elements on top)
- Asynchronous non-blocking rendering via loop.run_in_executor
"""

import os
import io
import math
import asyncio
from PIL import Image, ImageDraw, ImageFont
from territories import BOARD_TILES, DEAD_ZONE_POSITIONS, NEUTRAL_POSITIONS, PROPERTY_POSITIONS

# Player neon color schemes
PLAYER_NEON_SCHEMES = [
    {"rgb": (0, 240, 255),   "hex": "#00F0FF", "label": "P1", "name": "Cyan"},    # P1 Neon Cyan
    {"rgb": (34, 197, 94),   "hex": "#22C55E", "label": "P2", "name": "Green"},   # P2 Emerald Green
    {"rgb": (249, 115, 22),  "hex": "#F97316", "label": "P3", "name": "Orange"},  # P3 Vibrant Orange
    {"rgb": (168, 85, 247),  "hex": "#A855F7", "label": "P4", "name": "Purple"},  # P4 Neon Purple
]

CANVAS_SIZE = 1200  # 1200 x 1200 high-res board

def get_font(size: int = 14, bold: bool = False):
    """Returns a TrueType font with fallbacks for Windows and Linux."""
    candidates = [
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
        "calibrib.ttf" if bold else "calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for font_name in candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()

def get_tile_rect(pos: int, W: int, H: int) -> tuple[int, int, int, int]:
    """
    Returns (x1, y1, x2, y2) bounds for a given tile position (0 to 19).
    Board has 6 tiles per side:
      Corner 0: (0, 0)
      Tiles 1-4: Top Row (step 1 to 4)
      Corner 5: (5, 0)
      Tiles 6-9: Right Column (step 1 to 4)
      Corner 10: (5, 5)
      Tiles 11-14: Bottom Row (step 1 to 4)
      Corner 15: (0, 5)
      Tiles 16-19: Left Column (step 1 to 4)
    """
    pad = int(W * 0.030)
    board_w = W - 2 * pad
    board_h = H - 2 * pad

    # Grid size: 6 cells
    corner_size = int(board_w * 0.170)
    inner_w = (board_w - 2 * corner_size) / 4.0
    inner_h = (board_h - 2 * corner_size) / 4.0

    # Margins
    left = pad
    right = pad + board_w
    top = pad
    bottom = pad + board_h

    if pos == 0:  # Top-Left START
        return (left, top, left + corner_size, top + corner_size)
    elif 1 <= pos <= 4:  # Top edge
        idx = pos - 1
        x1 = int(left + corner_size + idx * inner_w)
        x2 = int(x1 + inner_w)
        return (x1, top, x2, top + corner_size)
    elif pos == 5:  # Top-Right DEAD ZONE 1
        return (right - corner_size, top, right, top + corner_size)
    elif 6 <= pos <= 9:  # Right edge
        idx = pos - 6
        y1 = int(top + corner_size + idx * inner_h)
        y2 = int(y1 + inner_h)
        return (right - corner_size, y1, right, y2)
    elif pos == 10:  # Bottom-Right NEUTRAL 1
        return (right - corner_size, bottom - corner_size, right, bottom)
    elif 11 <= pos <= 14:  # Bottom edge (right to left)
        idx = pos - 11
        x2 = int(right - corner_size - idx * inner_w)
        x1 = int(x2 - inner_w)
        return (x1, bottom - corner_size, x2, bottom)
    elif pos == 15:  # Bottom-Left DEAD ZONE 2
        return (left, bottom - corner_size, left + corner_size, bottom)
    elif 16 <= pos <= 19:  # Left edge (bottom to top)
        idx = pos - 16
        y2 = int(bottom - corner_size - idx * inner_h)
        y1 = int(y2 - inner_h)
        return (left, y1, left + corner_size, y2)

    raise ValueError(f"Invalid position {pos}")


# ---------------------------------------------------------------------------
# Helper Drawing Functions
# ---------------------------------------------------------------------------
def draw_rounded_card(draw: ImageDraw.Draw, rect: tuple[int, int, int, int], radius: int, fill: tuple, outline: tuple = None, width: int = 1):
    """Draws a rounded rectangle card."""
    x1, y1, x2, y2 = rect
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill, outline=outline, width=width)

def draw_hazard_stripes(draw: ImageDraw.Draw, rect: tuple[int, int, int, int], radius: int):
    """Draws diagonal hazard warning stripes on the border of Dead Zones."""
    x1, y1, x2, y2 = rect
    # Base dark red fill
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=(40, 15, 20, 255), outline=(220, 38, 38, 255), width=3)

    # Hazard stripe lines along the border perimeter
    stripe_w = 6
    for offset in range(-50, (x2 - x1) + (y2 - y1) + 50, 16):
        # Draw clipped lines near border
        sx1 = x1 + offset
        sy1 = y1 + 3
        sx2 = sx1 - 18
        sy2 = y1 + 14
        if x1 <= sx1 <= x2:
            draw.line([(sx1, sy1), (sx2, sy2)], fill=(220, 38, 38, 200), width=stripe_w)
        # Bottom edge
        by1 = y2 - 14
        by2 = y2 - 3
        if x1 <= sx1 <= x2:
            draw.line([(sx1, by1), (sx2, by2)], fill=(220, 38, 38, 200), width=stripe_w)


# ---------------------------------------------------------------------------
# Static Board Layer (Cached)
# ---------------------------------------------------------------------------
def render_static_board(game) -> Image.Image:
    """
    Renders the static base board:
    - Charcoal board canvas with dark frame
    - All 20 base tile cards:
        * START corner (Tile 0)
        * DEAD ZONE corners (Tiles 5, 15)
        * NEUTRAL / DRAW cards (Tiles 7, 10, 12)
        * PROPERTY cards (14 properties with stats & prices)
    - Center Scorecard Panel container outline
    """
    if game._static_board_cache is not None:
        return game._static_board_cache.copy()

    W = CANVAS_SIZE
    H = CANVAS_SIZE
    img = Image.new("RGBA", (W, H), (22, 25, 33, 255))
    draw = ImageDraw.Draw(img)

    # Subtle background grid lines
    grid_color = (30, 35, 46, 255)
    for step in range(0, W, 40):
        draw.line([(step, 0), (step, H)], fill=grid_color, width=1)
        draw.line([(0, step), (W, step)], fill=grid_color, width=1)

    # Center area boundary shadow
    draw.rounded_rectangle([int(W * 0.02), int(H * 0.02), int(W * 0.98), int(H * 0.98)], radius=24, outline=(38, 44, 58, 255), width=2)

    # Fonts
    font_lg = get_font(26, bold=True)
    font_md = get_font(18, bold=True)
    font_sm = get_font(14, bold=True)
    font_xs = get_font(11, bold=True)
    font_stat = get_font(12, bold=True)

    # Draw all 20 tiles
    for pos in range(20):
        x1, y1, x2, y2 = get_tile_rect(pos, W, H)
        tile = BOARD_TILES[pos]
        tile_type = tile["type"]
        card_pad = 4
        cx1, cy1, cx2, cy2 = x1 + card_pad, y1 + card_pad, x2 - card_pad, y2 - card_pad
        card_w = cx2 - cx1
        card_h = cy2 - cy1

        if tile_type == "start":
            # --- START Tile ---
            draw_rounded_card(draw, (cx1, cy1, cx2, cy2), radius=16, fill=(18, 24, 34, 255), outline=(0, 229, 255, 255), width=3)
            # Power / Start icon
            mid_x = (cx1 + cx2) // 2
            mid_y = cy1 + int(card_h * 0.42)
            r_icon = 28
            draw.ellipse([mid_x - r_icon, mid_y - r_icon, mid_x + r_icon, mid_y + r_icon], outline=(0, 229, 255, 255), width=4)
            draw.line([(mid_x, mid_y - r_icon - 4), (mid_x, mid_y - 4)], fill=(0, 229, 255, 255), width=5)
            # START text
            draw.text((mid_x, cy2 - 32), "START", fill=(255, 255, 255, 255), font=font_lg, anchor="mm")
            draw.text((mid_x, cy2 - 14), "+$200 / +1 CARD", fill=(0, 229, 255, 255), font=font_xs, anchor="mm")

        elif tile_type == "dead_zone":
            # --- DEAD ZONE Tile ---
            draw_hazard_stripes(draw, (cx1, cy1, cx2, cy2), radius=16)
            mid_x = (cx1 + cx2) // 2
            mid_y = cy1 + int(card_h * 0.42)
            # Warning Triangle
            tri_h = 32
            draw.polygon([
                (mid_x, mid_y - tri_h),
                (mid_x - 30, mid_y + 14),
                (mid_x + 30, mid_y + 14)
            ], outline=(239, 68, 68, 255), fill=(70, 20, 25, 255))
            # Exclamation mark
            draw.text((mid_x, mid_y - 4), "!", fill=(255, 255, 255, 255), font=font_lg, anchor="mm")
            # Label
            draw.text((mid_x, cy2 - 32), "DEAD ZONE", fill=(239, 68, 68, 255), font=font_md, anchor="mm")
            draw.text((mid_x, cy2 - 14), "+1 STRIKE", fill=(255, 120, 120, 255), font=font_xs, anchor="mm")

        elif tile_type == "neutral":
            # --- NEUTRAL / DRAW Card ---
            draw_rounded_card(draw, (cx1, cy1, cx2, cy2), radius=14, fill=(45, 53, 67, 255), outline=(71, 85, 105, 255), width=2)
            mid_x = (cx1 + cx2) // 2
            mid_y = cy1 + int(card_h * 0.42)
            # Card deck icon (overlapping rounded boxes)
            cw, ch = 24, 34
            draw.rounded_rectangle([mid_x - cw - 4, mid_y - ch + 4, mid_x + cw - 12, mid_y + ch - 4], radius=4, outline=(148, 163, 184, 255), width=2)
            draw.rounded_rectangle([mid_x - cw + 4, mid_y - ch - 4, mid_x + cw - 4, mid_y + ch - 12], radius=4, fill=(58, 68, 86, 255), outline=(226, 232, 240, 255), width=2)
            # Label
            draw.text((mid_x, cy2 - 28), "DRAW", fill=(226, 232, 240, 255), font=font_md, anchor="mm")
            draw.text((mid_x, cy2 - 12), "1 TCG CARD", fill=(148, 163, 184, 255), font=font_xs, anchor="mm")

        else:
            # --- PROPERTY Card ---
            # Card body: clean light card surface
            draw_rounded_card(draw, (cx1, cy1, cx2, cy2), radius=12, fill=(244, 240, 232, 255), outline=(203, 213, 225, 255), width=1)

            # Orientation-specific layout
            is_top = (1 <= pos <= 4)
            is_bottom = (11 <= pos <= 14)
            is_left = (16 <= pos <= 19)
            is_right = (6 <= pos <= 9)

            color_hex = tile.get("color", "#00C4FF")
            # Parse color
            r = int(color_hex[1:3], 16)
            g = int(color_hex[3:5], 16)
            b = int(color_hex[5:7], 16)

            mid_x = (cx1 + cx2) // 2

            # Banner bar (at the inner side facing board center)
            bar_h = 10
            if is_top:
                draw.rectangle([cx1 + 1, cy2 - bar_h, cx2 - 1, cy2 - 1], fill=(r, g, b, 255))
            elif is_bottom:
                draw.rectangle([cx1 + 1, cy1 + 1, cx2 - 1, cy1 + bar_h], fill=(r, g, b, 255))
            elif is_left:
                draw.rectangle([cx2 - bar_h, cy1 + 1, cx2 - 1, cy2 - 1], fill=(r, g, b, 255))
            else:  # is_right
                draw.rectangle([cx1 + 1, cy1 + 1, cx1 + bar_h, cy2 - 1], fill=(r, g, b, 255))

            # Property text content
            flag = tile.get("flag", "")
            city = tile.get("name", "")
            country = tile.get("country", "")
            stats = tile.get("stats", {})
            price = tile.get("price", 250)

            # Draw City Name and Country
            title_y = cy1 + 22 if not is_bottom else cy1 + 28
            draw.text((mid_x, title_y), city.upper(), fill=(15, 23, 42, 255), font=font_sm, anchor="mm")
            draw.text((mid_x, title_y + 16), country.upper(), fill=(100, 116, 139, 255), font=font_xs, anchor="mm")

            # Draw 3 Stat indicators: Climate, Terrain, Economy
            stat_y = title_y + 36
            stats_text = f"C:{stats.get('climate', 5)}  T:{stats.get('terrain', 5)}  E:{stats.get('economy', 5)}"
            draw.text((mid_x, stat_y), stats_text, fill=(51, 65, 85, 255), font=font_stat, anchor="mm")

            # Price text
            price_y = cy2 - 20 if not is_top else cy2 - 24
            draw.text((mid_x, price_y), f"${price}", fill=(15, 23, 42, 255), font=font_md, anchor="mm")

    # Store in static cache
    game._static_board_cache = img.copy()
    return img


# ---------------------------------------------------------------------------
# Dynamic Board Overlay (Ownership, Tokens, Scorecard)
# ---------------------------------------------------------------------------
def render_dynamic_overlay(base_img: Image.Image, game) -> Image.Image:
    """
    Composites real-time dynamic elements:
    - Owned tile tints & badges in player colors
    - Center Scorecard panel (Player rows, cash, territories count, strike circles)
    """
    W, H = base_img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_md = get_font(18, bold=True)
    font_sm = get_font(14, bold=True)
    font_xs = get_font(12, bold=True)
    font_lg = get_font(22, bold=True)

    # 1. Tile Ownership Highlights
    for pos, owner_id in game.properties_owned.items():
        x1, y1, x2, y2 = get_tile_rect(pos, W, H)
        card_pad = 4
        cx1, cy1, cx2, cy2 = x1 + card_pad, y1 + card_pad, x2 - card_pad, y2 - card_pad

        # Find owner index
        owner_idx = next((i for i, p in enumerate(game.player_list) if p.id == owner_id), 0)
        scheme = PLAYER_NEON_SCHEMES[owner_idx % len(PLAYER_NEON_SCHEMES)]
        r, g, b = scheme["rgb"]

        # Neon glow border & overlay
        draw.rounded_rectangle([cx1, cy1, cx2, cy2], radius=12, fill=(r, g, b, 45), outline=(r, g, b, 255), width=3)

        # Owner badge
        draw.rounded_rectangle([cx1 + 4, cy1 + 4, cx1 + 32, cy1 + 22], radius=4, fill=(r, g, b, 240))
        draw.text((cx1 + 18, cy1 + 13), scheme["label"], fill=(0, 0, 0, 255), font=font_xs, anchor="mm")

    # 2. Center Scorecard Panel (matching reference mockup)
    sc_w = int(W * 0.46)
    sc_h = int(H * 0.38)
    sc_x1 = (W - sc_w) // 2
    sc_y1 = (H - sc_h) // 2
    sc_x2 = sc_x1 + sc_w
    sc_y2 = sc_y1 + sc_h

    # Container background with subtle border
    draw.rounded_rectangle([sc_x1, sc_y1, sc_x2, sc_y2], radius=18, fill=(30, 36, 48, 245), outline=(55, 65, 81, 255), width=2)

    # Panel header with title & window control dots
    draw.text((sc_x1 + 24, sc_y1 + 22), "TERRITORY WARS", fill=(148, 163, 184, 255), font=font_xs, anchor="lm")
    draw.ellipse([sc_x2 - 38, sc_y1 + 16, sc_x2 - 28, sc_y1 + 26], fill=(71, 85, 105, 255))
    draw.ellipse([sc_x2 - 24, sc_y1 + 16, sc_x2 - 14, sc_y1 + 26], fill=(71, 85, 105, 255))

    # Divider line
    draw.line([(sc_x1 + 16, sc_y1 + 38), (sc_x2 - 16, sc_y1 + 38)], fill=(45, 55, 72, 255), width=1)

    # Player Rows
    row_start_y = sc_y1 + 50
    row_h = (sc_h - 65) // max(len(game.player_list), 1)

    for i, p in enumerate(game.player_list):
        st = game.get_player_state(p.id)
        scheme = PLAYER_NEON_SCHEMES[i % len(PLAYER_NEON_SCHEMES)]
        r, g, b = scheme["rgb"]

        ry1 = row_start_y + i * row_h
        ry2 = ry1 + row_h - 8
        rx1 = sc_x1 + 16
        rx2 = sc_x2 - 16

        # Row box
        is_elim = st.get("is_eliminated", False)
        row_bg = (20, 24, 33, 200) if not is_elim else (28, 18, 22, 200)
        draw.rounded_rectangle([rx1, ry1, rx2, ry2], radius=8, fill=row_bg)

        mid_ry = (ry1 + ry2) // 2

        # Color chip badge
        chip_w = 26
        chip_h = 20
        chip_x = rx1 + 12
        draw.rounded_rectangle([chip_x, mid_ry - chip_h // 2, chip_x + chip_w, mid_ry + chip_h // 2], radius=4, fill=(r, g, b, 255))
        draw.text((chip_x + chip_w // 2, mid_ry), scheme["label"], fill=(0, 0, 0, 255), font=font_xs, anchor="mm")

        # Player Name
        name_x = chip_x + chip_w + 12
        name = p.display_name[:14]
        name_color = (255, 255, 255, 255) if not is_elim else (148, 163, 184, 255)
        draw.text((name_x, mid_ry), name, fill=name_color, font=font_sm, anchor="lm")

        # Cash & Properties
        num_props = len(st.get("properties", []))
        stats_str = f"${st['money']} | {num_props}/14" if not is_elim else "ELIMINATED"
        draw.text((rx2 - 110, mid_ry), stats_str, fill=(203, 213, 225, 255), font=font_xs, anchor="rm")

        # 3 Strike Indicators (Circles on right)
        strikes = st.get("strikes", 0)
        circle_start_x = rx2 - 75
        r_circ = 9
        for s_idx in range(3):
            cx = circle_start_x + s_idx * 22
            cy = mid_ry
            if s_idx < strikes:
                # Filled Red Strike Indicator
                draw.ellipse([cx - r_circ, cy - r_circ, cx + r_circ, cy + r_circ], fill=(239, 68, 68, 255), outline=(255, 255, 255, 255), width=1)
                draw.line([(cx - 4, cy - 4), (cx + 4, cy + 4)], fill=(255, 255, 255, 255), width=2)
                draw.line([(cx - 4, cy + 4), (cx + 4, cy - 4)], fill=(255, 255, 255, 255), width=2)
            else:
                # Unfilled Neutral Circle
                draw.ellipse([cx - r_circ, cy - r_circ, cx + r_circ, cy + r_circ], fill=(30, 36, 48, 255), outline=(100, 116, 139, 255), width=2)

    return Image.alpha_composite(base_img, overlay)


# ---------------------------------------------------------------------------
# Player Tokens Drawing
# ---------------------------------------------------------------------------
def draw_player_tokens(base_img: Image.Image, game, positions_override: dict[int, int] | None = None) -> Image.Image:
    """Draws multi-layer glowing neon player tokens on the board."""
    W, H = base_img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font_token = get_font(13, bold=True)

    pos_players: dict[int, list[int]] = {}
    for idx, player in enumerate(game.player_list):
        st = game.get_player_state(player.id)
        if not st.get("is_eliminated", False):
            p_pos = positions_override[player.id] if (positions_override and player.id in positions_override) else st["position"]
            pos_players.setdefault(p_pos, []).append(idx)

    for pos, player_indices in pos_players.items():
        x1, y1, x2, y2 = get_tile_rect(pos, W, H)
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        count = len(player_indices)

        for i, p_idx in enumerate(player_indices):
            offset_x = int((i - (count - 1) / 2) * (W * 0.026))
            tx = center_x + offset_x
            ty = center_y + (16 if pos not in (0, 5, 10, 15) else 0)

            scheme = PLAYER_NEON_SCHEMES[p_idx % len(PLAYER_NEON_SCHEMES)]
            r, g, b = scheme["rgb"]

            # Glowing Aura
            r_aura = int(W * 0.020)
            draw.ellipse([tx - r_aura, ty - r_aura, tx + r_aura, ty + r_aura], fill=(r, g, b, 75))

            # Outer white crisp ring
            r_ring = int(W * 0.014)
            draw.ellipse([tx - r_ring, ty - r_ring, tx + r_ring, ty + r_ring], outline=(255, 255, 255, 255), width=2)

            # Solid neon core
            r_core = int(W * 0.012)
            draw.ellipse([tx - r_core, ty - r_core, tx + r_core, ty + r_core], fill=(r, g, b, 240))

            # Label (P1, P2, etc.)
            draw.text((tx, ty), scheme["label"], fill=(0, 0, 0, 255), font=font_token, anchor="mm")

    return Image.alpha_composite(base_img, overlay).convert("RGB")


# ---------------------------------------------------------------------------
# Public Renderer API
# ---------------------------------------------------------------------------
def _render_board_image_sync(game, positions_override: dict[int, int] | None = None) -> io.BytesIO:
    """Synchronous board rendering implementation."""
    static_img = render_static_board(game)
    dynamic_img = render_dynamic_overlay(static_img, game)
    final_img = draw_player_tokens(dynamic_img, game, positions_override)

    buf = io.BytesIO()
    final_img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


async def render_board_image_async(game, positions_override: dict[int, int] | None = None) -> io.BytesIO:
    """Asynchronously renders the board using run_in_executor to avoid blocking."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _render_board_image_sync, game, positions_override)


def _render_board_animation_sync(game, moving_player_id: int, start_pos: int, end_pos: int) -> io.BytesIO:
    """Synchronous animation rendering."""
    if start_pos == end_pos:
        path = [start_pos]
    elif end_pos > start_pos:
        path = list(range(start_pos, end_pos + 1))
    else:
        path = list(range(start_pos, 20)) + list(range(0, end_pos + 1))

    if len(path) <= 1:
        return _render_board_image_sync(game)

    static_img = render_static_board(game)
    dynamic_base = render_dynamic_overlay(static_img, game)
    frames = []

    for step_pos in path:
        frame = draw_player_tokens(dynamic_base, game, {moving_player_id: step_pos})
        # Resize for smooth Discord rendering
        frame = frame.resize((960, 960), Image.Resampling.BILINEAR)
        frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE))

    durations = [220] * (len(frames) - 1) + [1400]
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


async def render_board_animation_async(game, moving_player_id: int, start_pos: int, end_pos: int) -> io.BytesIO:
    """Asynchronously renders movement animation using run_in_executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _render_board_animation_sync, game, moving_player_id, start_pos, end_pos)
