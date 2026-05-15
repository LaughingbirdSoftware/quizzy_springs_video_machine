#!/usr/bin/env python3
"""Pillow renderer for the Quizzy Springs MOVIES quiz format.

Produces segment mp4s compatible with assemble_movies.py:
    seg_intro.mp4
    seg_bump_{easy,medium,hard}.mp4 (only emitted if the corresponding bump is needed)
    seg_q{NN}.mp4  for every question in questions.json
    seg_outro.mp4  (built from bg_outro_movies.mp4 + held final frame)

Reads:
    questions.json           — episode content
    vo/durations.json        — VO clip lengths
    vo/vo_qNN_letter_frames.json — when A/B/C/D are spoken in vo_qNN_options.mp3

Renders the new left/right layout: image card on left, options stacked on right,
options fly in synced to VO letter timestamps, timer bar drains during think time,
reveal swaps the main image for the answer image.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths

paths.ensure_dirs()

ROOT = paths.ROOT
SEG_DIR = paths.SEG_DIR
AUDIO = paths.AUDIO_DIR
EP_DIR = paths.EP_DIR
VIS = paths.BG_DIR

W, H = 1920, 1080
FPS = 30
FONT_BOLD = str(paths.FONTS_DIR / "Montserrat-Bold.ttf")
FONT_XBOLD = str(paths.FONTS_DIR / "Montserrat-ExtraBold.ttf")
FONT_BLACK = str(paths.FONTS_DIR / "Montserrat-Black.ttf")

_QDATA = json.loads(paths.QUESTIONS_FILE.read_text())
QUESTIONS = _QDATA["questions"]
INTRO_TEXT = _QDATA["intro"]
OUTRO_TEXT = _QDATA["outro"]
EPISODE_TITLE = _QDATA.get("intro_subtitle", _QDATA.get("title", "MOVIES QUIZ")).upper()
DURS = json.loads(paths.DURATIONS_FILE.read_text())

YELLOW = (255, 214, 0)
WHITE = (255, 255, 255)
GREEN = (60, 220, 90)
GREEN_HIGHLIGHT = (60, 200, 90)
DARK = (12, 22, 50)
NEAR_BLACK = (16, 22, 36)
DIM = (60, 60, 80, 220)
DIM_TEXT = (200, 200, 220, 255)

# ---- font cache --------------------------------------------------------

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def F(size: int, weight: str = "black") -> ImageFont.FreeTypeFont:
    p = {"bold": FONT_BOLD, "xbold": FONT_XBOLD, "black": FONT_BLACK}[weight]
    key = (p, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(p, size)
    return _font_cache[key]


# ---- text helpers ------------------------------------------------------

def text_shadow(draw, xy, txt, font, fill, anchor="lt", shadow_offset=(3, 4),
                shadow=(0, 0, 0, 200)):
    draw.text((xy[0] + shadow_offset[0], xy[1] + shadow_offset[1]), txt,
              font=font, fill=shadow, anchor=anchor)
    draw.text(xy, txt, font=font, fill=fill, anchor=anchor)


def rounded(draw, box, radius, **kw):
    draw.rounded_rectangle(box, radius=radius, **kw)


def wrap_lines(draw, txt, font, max_w):
    words, lines, cur = txt.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ---- image fitting -----------------------------------------------------

def fit_contained(img: Image.Image, target_w: int, target_h: int,
                  bg: tuple[int, int, int] = NEAR_BLACK) -> Image.Image:
    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w, new_h = max(1, int(src_w * scale)), max(1, int(src_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), bg)
    canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    return canvas


# ---- background cache (per worker) -------------------------------------

_bg_cache: dict[str, Image.Image] = {}


def load_bg(name: str) -> Image.Image:
    """Resolve background by name. Falls back from per-episode → shared."""
    if name in _bg_cache:
        return _bg_cache[name].copy()
    per_ep = EP_DIR / f"{name}.png"
    src = per_ep if per_ep.exists() else (VIS / f"{name}.png")
    if not src.exists():
        # last-resort: blank navy
        bg = Image.new("RGBA", (W, H), (16, 22, 36, 255))
    else:
        bg = Image.open(src).convert("RGBA").resize((W, H))
    _bg_cache[name] = bg
    return bg.copy()


def load_question_image(rel_or_abs: str) -> Image.Image:
    """Resolve an image path relative to the episode dir or absolute."""
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = EP_DIR / rel_or_abs
    return Image.open(p).convert("RGB")


# ---- layout constants --------------------------------------------------

BADGE_CX, BADGE_CY = 159, 138
# Card + options are sized + centered together per question. Sizes below
# are ceilings; actual card_w comes from the image aspect ratio.
CARD_MAX_H = 640       # absolute height ceiling (leaves room for fun fact)
CARD_MAX_W = 940       # absolute width ceiling
CARD_PAD = 18          # inner padding around the image inside the yellow frame
CARD_CENTER_Y = 580    # vertical center of the card area
CARD_OPT_GAP = 80      # horizontal gap between card and options column
OPT_Y = 278                                         # top of options column (centers with image card)
OPT_W, OPT_H = 780, 130
OPT_GAP = 28
TIMER_Y = 1030
TIMER_W, TIMER_H = 1500, 36


# ---- per-question timing -----------------------------------------------

def question_timing(qnum: int) -> dict:
    qd = DURS[f"vo_q{qnum:02d}_question"]
    od = DURS[f"vo_q{qnum:02d}_options"]
    ad = DURS[f"vo_q{qnum:02d}_answer"]
    fps = FPS
    intro_anim = 30
    pad_q = 6
    options_start = intro_anim + math.ceil(qd * fps) + pad_q
    pad_o = 9
    phase_a = options_start + math.ceil(od * fps) + pad_o
    phase_b = 6 * fps  # 180
    pad_pre_ans = 9
    pad_post_ans = 30
    phase_c = pad_pre_ans + math.ceil(ad * fps) + pad_post_ans
    return {
        "phase_a": phase_a,
        "phase_b": phase_b,
        "phase_c": phase_c,
        "total": phase_a + phase_b + phase_c,
        "options_start_frame": options_start,
        "question_vo_frame": intro_anim,
        "reveal_swap_frame": pad_pre_ans,  # inside phase C
    }


# ---- per-option fly-in animation ---------------------------------------

REVEAL_DURATION = 12  # frames


def ease_out_quad(t: float) -> float:
    return 1.0 - (1.0 - t) * (1.0 - t)


def option_anim_state(letter: str, frame_in_phase_a: int,
                      options_start: int, letter_frames):
    """Return (visible: bool, x_offset_px: int, alpha: int) for an option.

    letter_frames may be a dict {'A': frame, ...} (real ElevenLabs format) or a
    list [fA, fB, fC, fD] (legacy/test). If the letter is absent, the option
    is treated as always-visible (defensive fallback).
    """
    if isinstance(letter_frames, dict):
        if letter not in letter_frames:
            return (True, 0, 255)
        reveal_at = options_start + letter_frames[letter]
    else:
        idx = "ABCD".index(letter)
        if idx >= len(letter_frames):
            return (False, 0, 0)
        reveal_at = options_start + letter_frames[idx]
    delta = frame_in_phase_a - reveal_at
    if delta < 0:
        return (False, 0, 0)
    if delta >= REVEAL_DURATION:
        return (True, 0, 255)
    t = delta / REVEAL_DURATION
    eased = ease_out_quad(t)
    x_off = int((1 - eased) * 90)
    alpha = int(eased * 255)
    return (True, x_off, alpha)


# ---- composition: header, image card, options, timer -------------------

def draw_header(canvas: Image.Image, num: int, total: int, question_text: str,
                question_alpha: int = 255):
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Question number inside the baked-in pink badge
    badge_font = F(92, "black")
    text_shadow(draw, (BADGE_CX, BADGE_CY), str(num), badge_font, WHITE,
                anchor="mm", shadow_offset=(0, 0))

    # Episode title (yellow) — fixed, comes from questions.json
    title_font = F(70, "black")
    text_shadow(draw, (W // 2, 30), EPISODE_TITLE, title_font, YELLOW, anchor="mt")

    # Question text — wrapped, max 2 lines, fades in during intro animation
    if question_alpha > 0:
        q_font = F(40, "xbold")
        lines = wrap_lines(draw, question_text, q_font, 1200)[:2]
        line_h = 50
        layer = Image.new("RGBA", (W, 130), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for i, ln in enumerate(lines):
            ld.text((layer.width // 2 + 2, 5 + i * line_h + 3), ln, font=q_font,
                    fill=(0, 0, 0, int(question_alpha * 0.78)), anchor="mt")
            ld.text((layer.width // 2, 5 + i * line_h), ln, font=q_font,
                    fill=(*WHITE, question_alpha), anchor="mt")
        canvas.alpha_composite(layer, (0, 115))

    # Counter top-right
    num_font = F(64, "black")
    of_font = F(44, "xbold")
    right_x = W - 80
    of_label = f"OF {total}"
    of_w = draw.textbbox((0, 0), of_label, font=of_font)[2]
    text_shadow(draw, (right_x, 100), of_label, of_font, WHITE, anchor="rt")
    text_shadow(draw, (right_x - of_w - 22, 88), str(num), num_font, YELLOW, anchor="rt")


def card_dims_for(image_path: Path) -> tuple[int, int, int, int]:
    """Return (card_x, card_y, card_w, card_h) sized to the image's aspect ratio.

    Card + options column are centered together horizontally on screen so the
    layout always feels balanced regardless of image aspect.
    """
    img = load_question_image(str(image_path))
    src_w, src_h = img.size
    aspect = src_w / src_h
    inner_h = CARD_MAX_H - 2 * CARD_PAD
    inner_w = int(inner_h * aspect)
    if inner_w > CARD_MAX_W - 2 * CARD_PAD:
        inner_w = CARD_MAX_W - 2 * CARD_PAD
        inner_h = int(inner_w / aspect)
    card_w = inner_w + 2 * CARD_PAD
    card_h = inner_h + 2 * CARD_PAD
    total_w = card_w + CARD_OPT_GAP + OPT_W
    card_x = (W - total_w) // 2
    card_y = CARD_CENTER_Y - card_h // 2
    return card_x, card_y, card_w, card_h


def opt_x_for(card_box: tuple[int, int, int, int]) -> int:
    card_x, _, card_w, _ = card_box
    return card_x + card_w + CARD_OPT_GAP


def draw_image_card(canvas: Image.Image, image_path: Path,
                    y_offset: int = 0, alpha: int = 255,
                    card_box: tuple[int, int, int, int] | None = None):
    """Draw the image card. y_offset shifts it down for intro animation.

    card_box: if provided, the (x, y, w, h) to use; otherwise computed from image.
    Passing card_box from the caller keeps the card stable during a main→reveal swap.
    """
    if alpha == 0:
        return
    if card_box is None:
        card_x, card_y, card_w, card_h = card_dims_for(image_path)
    else:
        card_x, card_y, card_w, card_h = card_box
    card_y += y_offset

    # shadow
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([card_x - 4, card_y - 4, card_x + card_w + 12, card_y + card_h + 16],
                         radius=26, fill=(0, 0, 0, int(150 * alpha / 255)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.alpha_composite(shadow)

    layer = Image.new("RGBA", (card_w + 24, card_h + 24), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    rounded(ld, [0, 0, card_w, card_h], radius=24,
            fill=(*NEAR_BLACK, alpha), outline=(*YELLOW, alpha), width=12)
    inner_w, inner_h = card_w - 2 * CARD_PAD, card_h - 2 * CARD_PAD
    img = load_question_image(str(image_path))
    inset = fit_contained(img, inner_w, inner_h, bg=NEAR_BLACK)
    if alpha < 255:
        inset_rgba = inset.convert("RGBA")
        alpha_mask = Image.new("L", inset_rgba.size, alpha)
        inset_rgba.putalpha(alpha_mask)
        layer.alpha_composite(inset_rgba, (CARD_PAD, CARD_PAD))
    else:
        layer.paste(inset, (CARD_PAD, CARD_PAD))
    canvas.alpha_composite(layer, (card_x, card_y))


def draw_option_row(canvas: Image.Image, row_idx: int, letter: str, text: str,
                    opt_x: int, state: str = "normal", x_offset: int = 0,
                    alpha: int = 255):
    """state: 'normal' | 'correct' | 'wrong' | 'hidden'."""
    if state == "hidden" or alpha == 0:
        return
    x = opt_x + x_offset
    y = OPT_Y + row_idx * (OPT_H + OPT_GAP)

    if state == "correct":
        bg_fill = (*GREEN_HIGHLIGHT, alpha)
        text_fill = (*WHITE, alpha)
        circle_fill = (*DARK, alpha)
        outline = (*YELLOW, alpha)
        outline_w = 6
    elif state == "wrong":
        bg_fill = (*DIM[:3], int(220 * alpha / 255))
        text_fill = (*DIM_TEXT[:3], alpha)
        circle_fill = (*NEAR_BLACK, alpha)
        outline = None
        outline_w = 0
    else:
        bg_fill = (*WHITE, alpha)
        text_fill = (*DARK, alpha)
        circle_fill = (*NEAR_BLACK, alpha)
        outline = None
        outline_w = 0

    layer = Image.new("RGBA", (OPT_W + 20, OPT_H + 20), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    rounded(ld, [0, 0, OPT_W, OPT_H], radius=24, fill=bg_fill,
            outline=outline, width=outline_w)

    circle_r = 56
    circle_cx, circle_cy = 28 + circle_r, OPT_H // 2
    ld.ellipse([circle_cx - circle_r, circle_cy - circle_r,
                circle_cx + circle_r, circle_cy + circle_r],
               fill=circle_fill, outline=(*YELLOW, alpha), width=6)
    letter_font = F(64, "black")
    ld.text((circle_cx, circle_cy + 4), letter, font=letter_font,
            fill=(*YELLOW, alpha), anchor="mm")

    opt_font = F(46, "black")
    ld.text((circle_cx + circle_r + 28, circle_cy + 4), text,
            font=opt_font, fill=text_fill, anchor="lm")

    canvas.alpha_composite(layer, (x, y))


def draw_timer_bar(canvas: Image.Image, progress: float):
    """progress 1.0 → 0.0 (drains)."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    x = (W - TIMER_W) // 2
    y = TIMER_Y
    rounded(draw, [x, y, x + TIMER_W, y + TIMER_H], radius=18,
            fill=(255, 255, 255, 70), outline=(255, 255, 255, 200), width=3)
    fill_w = int(TIMER_W * max(0.0, min(1.0, progress)))
    if fill_w > 10:
        rounded(draw, [x + 5, y + 5, x + fill_w - 5, y + TIMER_H - 5], radius=14,
                fill=GREEN)


def draw_fun_fact(canvas: Image.Image, text: str, alpha: int):
    if alpha <= 0 or not text:
        return
    draw_layer = Image.new("RGBA", (W, 100), (0, 0, 0, 0))
    ld = ImageDraw.Draw(draw_layer)
    font = F(34, "xbold")
    lines = wrap_lines(ld, text, font, 1400)[:2]
    line_h = 42
    for i, ln in enumerate(lines):
        ld.text((W // 2 + 2, 4 + i * line_h + 2), ln, font=font,
                fill=(0, 0, 0, int(alpha * 0.7)), anchor="mt")
        ld.text((W // 2, 4 + i * line_h), ln, font=font,
                fill=(*YELLOW, alpha), anchor="mt")
    canvas.alpha_composite(draw_layer, (0, 915))


# ---- frame renderers ---------------------------------------------------

def render_question_frame(qnum: int, abs_frame: int) -> Image.Image:
    q = QUESTIONS[qnum - 1]
    total_qs = len(QUESTIONS)
    t = question_timing(qnum)
    lf_path = AUDIO / f"vo_q{qnum:02d}_letter_frames.json"
    letter_frames = json.loads(lf_path.read_text()) if lf_path.exists() else {"A": 0, "B": 60, "C": 120, "D": 180}

    main_img = EP_DIR / q.get("main_image", "")
    reveal_img_path = q.get("reveal_image") or q.get("main_image")
    reveal_img = EP_DIR / reveal_img_path

    # Lock the card box to the main image's aspect; reveal letterboxes inside it.
    card_box = card_dims_for(main_img) if main_img.exists() else None
    opt_x = opt_x_for(card_box) if card_box else 1060

    bg = load_bg("bg_question_movies")

    if abs_frame < t["phase_a"]:
        # Phase A: intro fade-in, then sequential option reveal
        pf = abs_frame
        # intro animation (first 30 frames): question text + image card fade/slide in
        if pf < 30:
            ease = ease_out_quad(pf / 30)
            q_alpha = int(ease * 255)
            card_alpha = int(ease * 255)
            card_y_off = int((1 - ease) * 30)
        else:
            q_alpha, card_alpha, card_y_off = 255, 255, 0

        draw_header(bg, qnum, total_qs, q["question"], question_alpha=q_alpha)
        if main_img.exists():
            draw_image_card(bg, main_img, y_offset=card_y_off, alpha=card_alpha,
                            card_box=card_box)

        for i, L in enumerate(["A", "B", "C", "D"]):
            visible, xoff, alpha = option_anim_state(L, pf, t["options_start_frame"], letter_frames)
            if visible:
                draw_option_row(bg, i, L, q["options"][L], opt_x=opt_x,
                                state="normal", x_offset=xoff, alpha=alpha)
        # Timer hidden during phase A

    elif abs_frame < t["phase_a"] + t["phase_b"]:
        # Phase B: think time, timer drains
        pf = abs_frame - t["phase_a"]
        draw_header(bg, qnum, total_qs, q["question"], question_alpha=255)
        if main_img.exists():
            draw_image_card(bg, main_img, card_box=card_box)
        for i, L in enumerate(["A", "B", "C", "D"]):
            draw_option_row(bg, i, L, q["options"][L], opt_x=opt_x, state="normal")
        progress = 1.0 - (pf / t["phase_b"])
        draw_timer_bar(bg, progress)

    else:
        # Phase C: reveal
        pf = abs_frame - t["phase_a"] - t["phase_b"]
        answer = q["answer"]
        # image swap happens at reveal_swap_frame, with 8-frame crossfade
        swap_frame = t["reveal_swap_frame"]
        if pf < swap_frame:
            # still showing main
            shown_path = main_img
            reveal_alpha = 0
        elif pf < swap_frame + 8 and reveal_img.exists() and main_img.exists():
            # crossfade — composite reveal over main
            shown_path = main_img
            reveal_alpha = int(((pf - swap_frame) / 8) * 255)
        else:
            shown_path = reveal_img if reveal_img.exists() else main_img
            reveal_alpha = 255 if reveal_img.exists() else 0

        draw_header(bg, qnum, total_qs, q["question"], question_alpha=255)
        if shown_path.exists():
            draw_image_card(bg, shown_path, card_box=card_box)
        if reveal_alpha > 0 and reveal_img.exists() and shown_path != reveal_img:
            draw_image_card(bg, reveal_img, alpha=reveal_alpha, card_box=card_box)

        # option highlight: 8-frame transition starting at swap_frame
        hl_start = swap_frame
        if pf < hl_start:
            for i, L in enumerate(["A", "B", "C", "D"]):
                draw_option_row(bg, i, L, q["options"][L], opt_x=opt_x, state="normal")
        else:
            for i, L in enumerate(["A", "B", "C", "D"]):
                state = "correct" if L == answer else "wrong"
                draw_option_row(bg, i, L, q["options"][L], opt_x=opt_x, state=state)

        # Fun fact fade-in after a delay
        ff_start = swap_frame + 30
        if pf >= ff_start:
            fade = min(1.0, (pf - ff_start) / 12)
            draw_fun_fact(bg, q.get("fun_fact", ""), alpha=int(fade * 255))

    return bg.convert("RGB")


def render_intro_frame(frame_num: int, total_frames: int) -> Image.Image:
    bg = load_bg("bg_intro_movies")
    draw = ImageDraw.Draw(bg, "RGBA")

    # "QUIZZY SPRINGS" title big — fixed string, fits at 140
    title_font = F(140, "black")
    tag_font = F(48, "xbold")
    # Episode subtitle: autofit to safe width so long topics
    # ("PRE-MCU TRIVIA QUIZ", "CHRISTOPHER NOLAN FILMS") don't overflow.
    safe_w = W - 240
    sub_size = 80
    while sub_size > 44:
        sf_probe = F(sub_size, "black")
        bbox = draw.textbbox((0, 0), EPISODE_TITLE, font=sf_probe)
        if bbox[2] - bbox[0] <= safe_w:
            break
        sub_size -= 4
    sub_font = F(sub_size, "black")

    # Fade-in over first 24 frames
    fade_in = min(1.0, frame_num / 24)
    # Slight pulse during VO
    pulse = 1.0 + 0.02 * math.sin(frame_num / 12)
    cx, cy = W // 2, 380

    # Big "QUIZZY SPRINGS"
    title_alpha = int(fade_in * 255)
    title_layer = Image.new("RGBA", (W, 250), (0, 0, 0, 0))
    tl = ImageDraw.Draw(title_layer)
    tl.text((W // 2 + 4, 8), "QUIZZY SPRINGS", font=title_font,
            fill=(0, 0, 0, int(title_alpha * 0.8)), anchor="mt")
    tl.text((W // 2, 4), "QUIZZY SPRINGS", font=title_font,
            fill=(*WHITE, title_alpha), anchor="mt")
    bg.alpha_composite(title_layer, (0, cy - 100))

    # Episode subtitle (yellow, big)
    sub_alpha = int(min(1.0, max(0.0, (frame_num - 18) / 24)) * 255)
    if sub_alpha > 0:
        sub_layer = Image.new("RGBA", (W, 150), (0, 0, 0, 0))
        sl = ImageDraw.Draw(sub_layer)
        sl.text((W // 2 + 4, 8), EPISODE_TITLE, font=sub_font,
                fill=(0, 0, 0, int(sub_alpha * 0.8)), anchor="mt")
        sl.text((W // 2, 4), EPISODE_TITLE, font=sub_font,
                fill=(*YELLOW, sub_alpha), anchor="mt")
        bg.alpha_composite(sub_layer, (0, cy + 130))

    # Tagline
    if frame_num > 60:
        tag_alpha = int(min(1.0, (frame_num - 60) / 18) * 255)
        tag_layer = Image.new("RGBA", (W, 80), (0, 0, 0, 0))
        td = ImageDraw.Draw(tag_layer)
        td.text((W // 2 + 3, 6), "25 QUESTIONS · CAN YOU GET THEM ALL?", font=tag_font,
                fill=(0, 0, 0, int(tag_alpha * 0.8)), anchor="mt")
        td.text((W // 2, 4), "25 QUESTIONS · CAN YOU GET THEM ALL?", font=tag_font,
                fill=(*WHITE, tag_alpha), anchor="mt")
        bg.alpha_composite(tag_layer, (0, cy + 280))

    # Logo bottom
    logo = paths.LOGO_PATH
    if logo.exists():
        l = Image.open(logo).convert("RGBA")
        target_h = 180
        scale = target_h / l.height
        l = l.resize((int(l.width * scale), target_h), Image.LANCZOS)
        bg.alpha_composite(l, ((W - l.width) // 2, H - l.height - 60))

    return bg.convert("RGB")


def render_bump_frame(frame_num: int, level: str) -> Image.Image:
    bg = load_bg("bg_intro_movies")
    draw = ImageDraw.Draw(bg, "RGBA")
    fade = min(1.0, frame_num / 18)
    color = {"easy": GREEN, "medium": (255, 180, 60), "hard": (255, 80, 80)}[level]
    label = {"easy": "EASY ROUND", "medium": "MEDIUM ROUND", "hard": "HARD ROUND"}[level]
    fnt = F(140, "black")
    alpha = int(fade * 255)
    layer = Image.new("RGBA", (W, 220), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((W // 2 + 5, 10), label, font=fnt,
            fill=(0, 0, 0, int(alpha * 0.8)), anchor="mt")
    ld.text((W // 2, 4), label, font=fnt, fill=(*color, alpha), anchor="mt")
    bg.alpha_composite(layer, (0, H // 2 - 100))
    return bg.convert("RGB")


# ---- segment encoding --------------------------------------------------

def _worker_init():
    global _bg_cache, _font_cache
    _bg_cache = {}
    _font_cache = {}


def _render_one(args):
    seg_type, idx, qnum, total_frames = args
    if seg_type == "intro":
        img = render_intro_frame(idx, total_frames)
    elif seg_type.startswith("bump_"):
        img = render_bump_frame(idx, seg_type.split("_")[1])
    elif seg_type == "question":
        img = render_question_frame(qnum, idx)
    else:
        raise ValueError(seg_type)
    return idx, img


def render_segment_parallel(out_mp4: Path, total_frames: int, seg_type: str,
                            qnum: int | None = None):
    tmpdir = tempfile.mkdtemp(prefix=f"{seg_type}_", dir=str(SEG_DIR))
    t0 = time.time()
    args_list = [(seg_type, i, qnum, total_frames) for i in range(total_frames)]
    workers = max(2, (os.cpu_count() or 4) - 1)
    progress = 0
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as pool:
        futs = {pool.submit(_render_one, a): a[1] for a in args_list}
        for fut in as_completed(futs):
            idx, img = fut.result()
            img.save(f"{tmpdir}/{idx:05d}.jpg", "JPEG", quality=92)
            progress += 1
            if progress % 300 == 0:
                print(f"  {seg_type}: {progress}/{total_frames} frames", flush=True)
    enc_t = time.time()
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS),
                    "-i", f"{tmpdir}/%05d.jpg",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-r", str(FPS), str(out_mp4)],
                   check=True, stderr=subprocess.DEVNULL)
    shutil.rmtree(tmpdir)
    print(f"  → {out_mp4.name} ({total_frames}f, render {enc_t - t0:.1f}s, "
          f"encode {time.time() - enc_t:.1f}s)", flush=True)


def render_outro_from_mp4(out_mp4: Path):
    """Use bg_outro_movies.mp4 + held final frame to match outro VO + tail pad."""
    src = VIS / "bg_outro_movies.mp4"
    if not src.exists():
        raise RuntimeError(f"Missing {src}")
    vo_dur = DURS["vo_outro"]
    src_dur = 5.0  # this mp4 is 5s by spec; ffprobe could verify but we trust it
    tail_pad = 1.0
    target_total = max(src_dur, vo_dur + tail_pad)
    pad_seconds = max(0.0, target_total - src_dur)
    # Use tpad to hold the last frame for pad_seconds; strip audio (assemble adds its own).
    cmd = ["ffmpeg", "-y", "-i", str(src),
           "-an",
           "-vf", f"tpad=stop_mode=clone:stop_duration={pad_seconds:.3f}",
           "-c:v", "libx264", "-preset", "fast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-r", str(FPS), str(out_mp4)]
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
    print(f"  → {out_mp4.name} (outro: {src_dur}s + {pad_seconds:.2f}s held tail)")


# ---- difficulty split helper -------------------------------------------

def difficulty_groups() -> dict[str, list[int]]:
    """Return {'easy': [...], 'medium': [...], 'hard': [...]} of question numbers."""
    groups = {"easy": [], "medium": [], "hard": []}
    for q in QUESTIONS:
        d = q.get("difficulty", "medium").lower()
        if d not in groups:
            d = "medium"
        groups[d].append(q["n"])
    return groups


# ---- orchestrate -------------------------------------------------------

def build_all():
    groups = difficulty_groups()

    # 1) Intro
    print("=== intro ===")
    intro_frames = math.ceil(DURS["vo_intro"] * FPS) + 18
    render_segment_parallel(SEG_DIR / "seg_intro.mp4", intro_frames, "intro")

    bump_emitted: dict[str, bool] = {}
    timings = {"intro_frames": intro_frames}

    def maybe_bump(level: str):
        if not groups[level]:
            return
        print(f"=== bump_{level} ===")
        render_segment_parallel(SEG_DIR / f"seg_bump_{level}.mp4", 90, f"bump_{level}")
        bump_emitted[level] = True

    # 2/3/4) bump_easy + easy questions
    maybe_bump("easy")
    for n in groups["easy"]:
        print(f"=== Q{n:02d} (easy) ===")
        t = question_timing(n)
        timings[f"q{n:02d}"] = t
        render_segment_parallel(SEG_DIR / f"seg_q{n:02d}.mp4", t["total"], "question", qnum=n)

    maybe_bump("medium")
    for n in groups["medium"]:
        print(f"=== Q{n:02d} (medium) ===")
        t = question_timing(n)
        timings[f"q{n:02d}"] = t
        render_segment_parallel(SEG_DIR / f"seg_q{n:02d}.mp4", t["total"], "question", qnum=n)

    maybe_bump("hard")
    for n in groups["hard"]:
        print(f"=== Q{n:02d} (hard) ===")
        t = question_timing(n)
        timings[f"q{n:02d}"] = t
        render_segment_parallel(SEG_DIR / f"seg_q{n:02d}.mp4", t["total"], "question", qnum=n)

    # 5) Outro (from mp4)
    print("=== outro ===")
    render_outro_from_mp4(SEG_DIR / "seg_outro.mp4")
    # outro_frames recorded for assemble_movies.py
    vo_dur = DURS["vo_outro"]
    target_total = max(5.0, vo_dur + 1.0)
    timings["outro_frames"] = math.ceil(target_total * FPS)
    timings["bumps"] = sorted(bump_emitted.keys())
    timings["question_order"] = (groups["easy"] + groups["medium"] + groups["hard"])

    (SEG_DIR / "timings.json").write_text(json.dumps(timings, indent=2))
    print(f"\nWrote {SEG_DIR / 'timings.json'}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # render single test frames for visual inspection
        out = paths.EP_DIR / "_render_test"
        out.mkdir(exist_ok=True)
        img = render_intro_frame(80, 200)
        img.save(out / "intro_80.jpg", "JPEG", quality=92)
        for qn in [1, 2, 3]:
            t = question_timing(qn)
            samples = {
                "phase_a_mid": t["phase_a"] // 2,
                "phase_b_mid": t["phase_a"] + t["phase_b"] // 2,
                "phase_c_mid": t["phase_a"] + t["phase_b"] + t["phase_c"] // 2,
            }
            for tag, f_idx in samples.items():
                img = render_question_frame(qn, f_idx)
                img.save(out / f"q{qn:02d}_{tag}.jpg", "JPEG", quality=92)
        print(f"Test frames → {out}")
    else:
        build_all()
