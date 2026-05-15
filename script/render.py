#!/usr/bin/env python3
"""Pillow renderer for Quizzy Springs Pop Culture Quiz video.
All animations (bubbles, glow, bounce, squash, confetti) baked per-frame.
Each segment encoded to silent mp4 immediately, frames deleted to save disk.
"""
from __future__ import annotations
import os, sys, json, math, random, shutil, subprocess, time, tempfile, textwrap
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths
paths.ensure_dirs()

ROOT = paths.ROOT
SEG_DIR = paths.SEG_DIR
AUDIO = paths.AUDIO_DIR
ASSETS = paths.ASSETS
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
DURS = json.loads(paths.DURATIONS_FILE.read_text())

# ---------- font cache ----------
_font_cache = {}
def F(size, weight="bold"):
    path = {"bold": FONT_BOLD, "xbold": FONT_XBOLD, "black": FONT_BLACK}[weight]
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]

# ---------- helpers ----------
def text_size(draw, txt, font):
    bbox = draw.textbbox((0, 0), txt, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

def draw_text_shadow(draw, xy, txt, font, fill, shadow=(0,0,0,180), offset=(3,3), anchor="lt"):
    draw.text((xy[0]+offset[0], xy[1]+offset[1]), txt, font=font, fill=shadow, anchor=anchor)
    draw.text(xy, txt, font=font, fill=fill, anchor=anchor)

def wrap_lines(draw, txt, font, max_w):
    words = txt.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if text_size(draw, test, font)[0] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

# ---------- background loading ----------
_bg_cache = {}
def load_bg(name):
    if name not in _bg_cache:
        per_ep = paths.EP_DIR / f"{name}.png"
        src = per_ep if per_ep.exists() else (VIS / f"{name}.png")
        _bg_cache[name] = Image.open(src).convert("RGB").resize((W,H))
    return _bg_cache[name].copy()

# ---------- bubbles ----------
def draw_bubbles(img, frame_num, count=40):
    draw = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(42)
    bases = [(rng.randint(0, W), rng.randint(0, H), rng.uniform(0.5,1.5),
              rng.randint(8,28), rng.uniform(5,20)) for _ in range(count)]
    colors = [(0,255,255),(255,100,200),(255,255,100),(150,255,100),(255,255,255)]
    for i,(bx,by,sp,sz,sw) in enumerate(bases):
        y = (H + by - frame_num*sp) % (H+200) - 100
        x = bx + math.sin(frame_num/30 + i)*sw
        alpha = int(50 + 35*math.sin(frame_num/20 + i))
        c = colors[i % 5]
        draw.ellipse([x-sz, y-sz, x+sz, y+sz], fill=(*c, max(0,min(255,alpha))))

# ---------- answer box ----------
BORDER_COLORS = [(180,80,255),(255,100,200),(80,220,255),(150,255,100)]

def draw_answer_box(img, frame_num, box_idx, pos, size, letter, text, state="normal", letter_scale=1.0):
    x, y = pos
    w, h = size
    phase = box_idx * 0.5
    pulse = 0.85 + 0.15*math.sin(frame_num/15 + phase)
    base = BORDER_COLORS[box_idx]
    if state == "correct":
        g = 0.7 + 0.3*math.sin(frame_num/8)
        border = (int(80*g), 255, int(80*g)); bw = 7
    elif state == "dimmed":
        border = tuple(int(c*0.3) for c in base); bw = 2
    else:
        border = tuple(int(c*pulse) for c in base); bw = 4

    # glow rings on overlay
    ov = Image.new("RGBA", img.size, (0,0,0,0))
    ovd = ImageDraw.Draw(ov)
    for ro in [12,8,4]:
        ga = int(70*pulse / (ro/4))
        ovd.rounded_rectangle([x-ro, y-ro, x+w+ro, y+h+ro], radius=24+ro,
                              outline=(*border, ga), width=2)
    img.alpha_composite(ov) if img.mode == "RGBA" else img.paste(ov, mask=ov)

    # main box
    bd = ImageDraw.Draw(img, "RGBA")
    fill_a = 220 if state != "dimmed" else 90
    bd.rounded_rectangle([x, y, x+w, y+h], radius=24,
                         fill=(20,25,50,fill_a), outline=border, width=bw)

    # letter
    lf = F(int(80*letter_scale), "black")
    lc = (255,235,80) if state != "dimmed" else (120,110,50)
    bd.text((x+40, y+h/2), f"{letter}:", font=lf, fill=lc, anchor="lm")

    # text wrapped
    tf = F(44, "bold")
    tc = (255,255,255) if state != "dimmed" else (140,140,140)
    lines = wrap_lines(bd, text, tf, w - 220)
    line_h = text_size(bd, "Hg", tf)[1] + 6
    total = line_h * len(lines)
    sy = y + h/2 - total/2
    for li, ln in enumerate(lines):
        bd.text((x+200, sy + li*line_h), ln, font=tf, fill=tc, anchor="lt")

# ---------- letter bounce ----------
def letter_scale(frame_num, bounce_start, duration=12):
    if frame_num < bounce_start: return 1.0
    p = (frame_num - bounce_start) / duration
    if p >= 1.0: return 1.0
    if p < 0.5: return 1.0 + 0.45 * (p*2)**2
    t = (p - 0.5)*2
    return 1.45 - 0.5*t + 0.05*math.sin(t*math.pi*2)

# ---------- drop with squash ----------
def card_transform(frame_num, drop_start=0, duration=18):
    if frame_num < drop_start: return -600, 1.0, 1.0
    f = frame_num - drop_start
    if f < 12:
        p = f/12
        return -600 + 600*(p*p), 1.0, 1.0
    elif f < 15: return 0, 1.10, 0.85
    elif f < 18: return 0, 0.97, 1.05
    else: return 0, 1.0, 1.0

# ---------- confetti ----------
def draw_confetti(img, frame_num, start, cx, cy):
    if frame_num < start: return
    age = frame_num - start
    if age > 60: return
    rng = random.Random(start)
    d = ImageDraw.Draw(img, "RGBA")
    cols = [(255,220,50),(255,80,180),(80,220,255),(150,255,100),(255,255,255)]
    for i in range(80):
        ang = rng.uniform(0, 2*math.pi); sp = rng.uniform(8, 25)
        vx = math.cos(ang)*sp; vy = math.sin(ang)*sp - 8
        gv = 0.5
        x = cx + vx*age
        y = cy + vy*age + 0.5*gv*age*age
        if age < 40: a = 255
        else: a = max(0, int(255*(60-age)/20))
        c = cols[i % 5]
        d.ellipse([x-7, y-3, x+7, y+3], fill=(*c, a))

# ---------- question card ----------
def render_question_card(bg, frame_num, q_data, phase, phase_frame,
                         letter_frames, letter_offsets, countdown_idx=None,
                         answer_state_frames=None, reveal_start=None,
                         confetti_start=None, banner_start=None,
                         fun_fact_start=None):
    """Render one frame of a question segment.
    phase: 'A' (intro), 'B' (countdown), 'C' (reveal)
    """
    img = bg.copy().convert("RGBA")
    draw_bubbles(img, frame_num)

    # Card drop animation only in phase A first 18 frames
    if phase == "A":
        dy, sx, sy_ = card_transform(phase_frame)
    else:
        dy, sx, sy_ = 0, 1.0, 1.0

    # Question text card (top center)
    q_text = q_data["question"]
    card_w, card_h = 1500, 200
    cx = W // 2
    cy = 140 + dy
    qd = ImageDraw.Draw(img, "RGBA")
    qd.rounded_rectangle([cx-card_w//2, cy, cx+card_w//2, cy+card_h], radius=28,
                         fill=(15,18,42,235), outline=(255,255,255,80), width=3)
    # Type-in effect for question text during frames 18-30 of phase A
    show_text = q_text
    if phase == "A":
        if phase_frame < 18:
            show_text = ""
        elif phase_frame < 30:
            visible = int(len(q_text) * (phase_frame - 18) / 12)
            show_text = q_text[:visible]
    qfont = F(50, "xbold")
    lines = wrap_lines(qd, show_text, qfont, card_w - 80)
    if lines:
        lh = text_size(qd, "Hg", qfont)[1] + 8
        total = lh * len(lines)
        sy_start = cy + card_h//2 - total//2
        for li, ln in enumerate(lines):
            draw_text_shadow(qd, (cx, sy_start + li*lh + lh//2), ln, qfont,
                             (255,255,255), anchor="mm", offset=(2,2))

    # Question number badge (top-left)
    n = q_data["n"]
    badge_x, badge_y = 80, 60
    qd.rounded_rectangle([badge_x, badge_y, badge_x+200, badge_y+100], radius=20,
                         fill=(255,210,60,240), outline=(255,255,255,200), width=3)
    bf = F(54, "black")
    qd.text((badge_x+100, badge_y+50), f"Q{n}", font=bf, fill=(30,20,80), anchor="mm")

    # Difficulty pill (top-right)
    diff = q_data["difficulty"].upper()
    diff_col = {"EASY": (80,220,120), "MEDIUM": (255,180,60), "HARD": (240,80,90)}[diff]
    pill_w = 260
    qd.rounded_rectangle([W-80-pill_w, 60, W-80, 160], radius=20,
                         fill=(*diff_col, 240), outline=(255,255,255,200), width=3)
    pf = F(40, "black")
    qd.text((W-80-pill_w//2, 110), diff, font=pf, fill=(20,20,40), anchor="mm")

    # Answer boxes
    bw, bh = 720, 130
    margin_x = 60
    box_y_start = 460
    gap_y = 30
    positions = [
        (margin_x, box_y_start),
        (W - margin_x - bw, box_y_start),
        (margin_x, box_y_start + bh + gap_y),
        (W - margin_x - bw, box_y_start + bh + gap_y),
    ]
    letters = ["A","B","C","D"]
    correct = q_data["answer"]
    opts = q_data["options"]

    # Slide-in animation for phase A — synced to the actual VO letter timestamps
    # so each answer box appears exactly when the narrator says its letter.
    visible = [True]*4
    slide_offsets = [0,0,0,0]
    if phase == "A":
        # letter_frames is a dict {"A": frame_within_vo_options, "B": ..., "C": ..., "D": ...}.
        # Absolute slide-in frame for each box = letter_offsets + letter_frames[L].
        # Fallback to progressive fixed offsets if letter_frames is malformed.
        if isinstance(letter_frames, dict) and all(L in letter_frames for L in "ABCD"):
            slide_starts = [letter_offsets + letter_frames[L] for L in "ABCD"]
        else:
            slide_starts = [30, 42, 54, 66]
        for i, ss in enumerate(slide_starts):
            if phase_frame < ss:
                visible[i] = False
            elif phase_frame < ss + 16:
                t = (phase_frame - ss) / 16
                ease = 1 - (1-t)**3
                if i % 2 == 0:  # from left
                    slide_offsets[i] = int(-1000 * (1-ease))
                else:
                    slide_offsets[i] = int(1000 * (1-ease))

    for i, (px, py) in enumerate(positions):
        if not visible[i]: continue
        ls = 1.0
        state = "normal"
        # Letter bounce timing
        if letter_frames and letters[i] in letter_frames:
            bounce_frame = letter_offsets + letter_frames[letters[i]]
            ls = letter_scale(frame_num, bounce_frame)
        if phase == "C" and answer_state_frames is not None:
            af = phase_frame
            if letters[i] == correct:
                if af >= answer_state_frames["correct_start"]:
                    state = "correct"
            else:
                if af >= answer_state_frames["dim_start"]:
                    state = "dimmed"
        draw_answer_box(img, frame_num, i, (px + slide_offsets[i], py),
                        (bw, bh), letters[i], opts[letters[i]], state, ls)

    # Phase B: countdown timer overlay
    if phase == "B" and countdown_idx is not None:
        cd_num = 6 - countdown_idx  # countdown_idx 0->6, 30->5, ... 150->1
        # Compute display number from phase_frame
        sec = phase_frame // 30
        display = max(1, 6 - sec)
        # within-second scale pop
        fws = phase_frame % 30
        scale_pop = 1.0
        if fws < 6:
            scale_pop = 1.0 + 0.15*math.sin(fws/6*math.pi)
        # ring color
        if display >= 5: ring = (80,220,120)
        elif display >= 3: ring = (255,200,60)
        else: ring = (240,80,90)
        ring_r = int(110 * scale_pop)
        timer_cx, timer_cy = W - 200, 270
        ovr = Image.new("RGBA", img.size, (0,0,0,0))
        od = ImageDraw.Draw(ovr)
        # glow
        for r in [ring_r+20, ring_r+12, ring_r+6]:
            od.ellipse([timer_cx-r, timer_cy-r, timer_cx+r, timer_cy+r],
                       outline=(*ring, 60), width=3)
        od.ellipse([timer_cx-ring_r, timer_cy-ring_r, timer_cx+ring_r, timer_cy+ring_r],
                   fill=(20,25,50,230), outline=ring, width=8)
        nf = F(int(120 * scale_pop), "black")
        od.text((timer_cx, timer_cy), str(display), font=nf, fill=ring, anchor="mm")
        img.alpha_composite(ovr)

    # Phase C: reveal animations
    if phase == "C":
        af = phase_frame
        # CORRECT banner sliding down
        if banner_start is not None and af >= banner_start:
            ba = af - banner_start
            if ba < 30:
                t = ba/30
                ease = 1 - (1-t)**3
                by = -150 + (80+150)*ease
            else:
                by = 80
            bx = W // 2
            bw_, bh_ = 700, 130
            bnr = ImageDraw.Draw(img, "RGBA")
            bnr.rounded_rectangle([bx-bw_//2, int(by), bx+bw_//2, int(by)+bh_], radius=30,
                                  fill=(80,220,120,245), outline=(255,255,255,255), width=5)
            cf = F(90, "black")
            draw_text_shadow(bnr, (bx, int(by)+bh_//2), "CORRECT!", cf,
                             (255,255,255), anchor="mm", offset=(3,3))

        # Confetti
        if confetti_start is not None:
            correct_idx = letters.index(correct)
            cx, cy = positions[correct_idx]
            draw_confetti(img, af, confetti_start, cx + bw//2, cy + bh//2)

        # Fun fact panel
        if fun_fact_start is not None and af >= fun_fact_start:
            ff_age = af - fun_fact_start
            if ff_age < 30:
                t = ff_age/30
                ease = 1 - (1-t)**3
                py = 1080 - (1080-820)*ease
            else:
                py = 820
            pw, ph = 1600, 200
            px = W//2 - pw//2
            ffd = ImageDraw.Draw(img, "RGBA")
            ffd.rounded_rectangle([px, int(py), px+pw, int(py)+ph], radius=24,
                                  fill=(255,210,60,245), outline=(255,255,255,220), width=4)
            lblf = F(36, "black")
            ffd.text((px+30, int(py)+30), "FUN FACT:", font=lblf, fill=(80,30,120))
            txtf = F(36, "bold")
            lines = wrap_lines(ffd, q_data["fun_fact"], txtf, pw-60)
            for li, ln in enumerate(lines):
                ffd.text((px+30, int(py)+80 + li*42), ln, font=txtf, fill=(30,20,60))

    # apply squash transform if in phase A early frames (whole-card not applied here for simplicity;
    # the drop is the dy on the question card itself which already gives the falling effect)

    return img.convert("RGB")

# ---------- segment renderers ----------
def render_intro_frame(frame_num):
    img = load_bg("bg_intro").convert("RGBA")
    draw_bubbles(img, frame_num)
    d = ImageDraw.Draw(img, "RGBA")
    # Logo fade-in & scale 0.5->1.0 over frames 0-30
    try:
        logo = Image.open(ASSETS / "logo.png").convert("RGBA")
        lf = frame_num
        if lf < 30:
            scale = 0.5 + 0.5 * (lf/30)
            alpha = int(255 * (lf/30))
        else:
            # gentle pulse
            scale = 1.0 + 0.03*math.sin(lf/30)
            alpha = 255
        lw, lh = logo.size
        target_h = 280
        ratio = target_h / lh
        new_w = int(lw * ratio * scale)
        new_h = int(target_h * scale)
        logo_r = logo.resize((new_w, new_h), Image.LANCZOS)
        # alpha
        a = logo_r.split()[3].point(lambda p: int(p * alpha / 255))
        logo_r.putalpha(a)
        img.alpha_composite(logo_r, (W//2 - new_w//2, 180 - new_h//2 + 100))
    except Exception:
        pass

    # Title "QUIZZY SPRINGS" slides up frames 30-90
    if frame_num >= 30:
        f = frame_num - 30
        if f < 60:
            t = f/60
            ease = 1 - (1-t)**3
            ty = 1200 - (1200-560)*ease
        else:
            ty = 560
        tf = F(180, "black")
        # gradient-fill via two layers
        draw_text_shadow(d, (W//2, int(ty)), "QUIZZY SPRINGS", tf,
                         (255,235,80), anchor="mm", offset=(5,5))

    # Subtitle fade-in frames 90-150 — autofit to safe width so long topics
    # like "VIRAL INTERNET TRENDS QUIZ" don't overflow the frame.
    if frame_num >= 90:
        f = frame_num - 90
        alpha = min(255, int(255 * f/60))
        subtitle_text = _QDATA.get("intro_subtitle", "QUIZ")
        safe_w = W - 240  # 120px margin on each side
        # Step font size down until it fits
        sub_size = 120
        while sub_size > 56:
            sf = F(sub_size, "xbold")
            bbox = d.textbbox((0, 0), subtitle_text, font=sf)
            if bbox[2] - bbox[0] <= safe_w:
                break
            sub_size -= 6
        ovr = Image.new("RGBA", img.size, (0,0,0,0))
        od = ImageDraw.Draw(ovr)
        draw_text_shadow(od, (W//2, 740), subtitle_text, sf,
                         (255,255,255,alpha), anchor="mm",
                         shadow=(0,0,0,min(180, alpha)), offset=(4,4))
        img.alpha_composite(ovr)

    # Tagline "20 QUESTIONS" floats up + fades in frames 150-180, then sits
    # at a fixed size. (Previous per-frame scale pulse caused jagged Ken-Burns
    # artifacts when integer pixel sizes shifted frame-to-frame.)
    if frame_num >= 150:
        f = frame_num - 150
        if f < 30:
            t = f / 30
            ease = 1 - (1-t)**3
            alpha = int(255 * ease)
            y_offset = int(40 * (1 - ease))  # floats up 40 px into position
        else:
            alpha = 255
            y_offset = 0
        ts = F(110, "black")  # CONSTANT size — no pulse
        ovr = Image.new("RGBA", img.size, (0,0,0,0))
        od = ImageDraw.Draw(ovr)
        draw_text_shadow(od, (W//2, 900 + y_offset), "20 QUESTIONS", ts,
                         (80,255,220,alpha), anchor="mm",
                         shadow=(0,0,0,min(150,alpha)), offset=(3,3))
        img.alpha_composite(ovr)

    return img.convert("RGB")


def render_bump_frame(frame_num, level):
    """level: 'easy' | 'medium' | 'hard'. Frames 0-90."""
    img = load_bg(f"bg_{level}").convert("RGBA")
    draw_bubbles(img, frame_num)
    d = ImageDraw.Draw(img, "RGBA")
    info = {"easy": ("EASY ROUND", "6 QUESTIONS", (140,255,160)),
            "medium": ("MEDIUM ROUND", "10 QUESTIONS", (255,220,80)),
            "hard": ("HARD ROUND", "4 QUESTIONS", (255,120,140))}
    big, sub, col = info[level]
    # Big title scales in frames 15-45
    if frame_num >= 15:
        f = frame_num - 15
        if f < 30:
            t = f/30
            ease = 1 - (1-t)**3 if t < 1 else 1
            scale = 0.3 + 0.7*ease
            alpha = int(255 * min(1, t*1.5))
        else:
            f2 = f - 30
            scale = 1.0 + 0.03*math.sin(f2/15)
            alpha = 255
        bf = F(int(200*scale), "black")
        ovr = Image.new("RGBA", img.size, (0,0,0,0))
        od = ImageDraw.Draw(ovr)
        draw_text_shadow(od, (W//2, 460), big, bf, (*col, alpha), anchor="mm",
                         shadow=(0,0,0, min(180, alpha)), offset=(5,5))
        img.alpha_composite(ovr)
    # Subtitle slides in frames 30-60
    if frame_num >= 30:
        f = frame_num - 30
        if f < 30:
            t = f/30
            ease = 1 - (1-t)**3
            sx_off = int(-800 * (1-ease))
            alpha = int(255 * min(1, t*1.5))
        else:
            sx_off = 0; alpha = 255
        sf = F(110, "xbold")
        ovr = Image.new("RGBA", img.size, (0,0,0,0))
        od = ImageDraw.Draw(ovr)
        draw_text_shadow(od, (W//2 + sx_off, 660), sub, sf,
                         (255,255,255,alpha), anchor="mm",
                         shadow=(0,0,0,min(180,alpha)), offset=(4,4))
        img.alpha_composite(ovr)
    return img.convert("RGB")


def render_outro_frame(frame_num, total_frames):
    img = load_bg("bg_outro").convert("RGBA")
    draw_bubbles(img, frame_num)

    # 1) Logo top-center, fades + slight pulse
    try:
        logo = Image.open(ASSETS/"logo.png").convert("RGBA")
        lw, lh = logo.size
        target_h = 180
        if frame_num < 20:
            tt = frame_num/20
            scale = 0.4 + 0.6*tt
            l_alpha = int(255*tt)
        else:
            scale = 1.0 + 0.025*math.sin(frame_num/30)
            l_alpha = 255
        nh = int(target_h*scale)
        nw = int(lw * nh / lh)
        logo_r = logo.resize((nw, nh), Image.LANCZOS)
        a = logo_r.split()[3].point(lambda p: int(p*l_alpha/255))
        logo_r.putalpha(a)
        img.alpha_composite(logo_r, (W//2 - nw//2, 50 + (target_h-nh)//2))
    except Exception:
        pass

    # 2) "THANKS FOR PLAYING!" centered, frames 15+ — sized to fit
    if frame_num >= 15:
        f = frame_num - 15
        if f < 22:
            t = f/22
            ease = 1 - (1-t)**3
            scale = 0.5 + 0.5*ease
            alpha = int(255 * min(1, t*1.3))
        else:
            scale = 1.0 + 0.025*math.sin(f/22)
            alpha = 255
        tf = F(int(120*scale), "black")
        ovr = Image.new("RGBA", img.size, (0,0,0,0))
        od = ImageDraw.Draw(ovr)
        draw_text_shadow(od, (W//2, 320), "THANKS FOR PLAYING!", tf,
                         (255,255,255,alpha), anchor="mm",
                         shadow=(0,0,0,min(180,alpha)), offset=(4,4))
        img.alpha_composite(ovr)

    # 3) Left column — WATCH THIS NEXT placeholder (16:9 box for drop-in)
    if frame_num >= 50:
        f = frame_num - 50
        if f < 25:
            t = f/25
            ease = 1 - (1-t)**3
            yoff = int(200*(1-ease))
            alpha = int(255*min(1, t*1.3))
        else:
            yoff = 0; alpha = 255
        wn_x, wn_y_base = 80, 470
        wn_w, wn_h = 800, 450  # 16:9 placeholder
        wn_y = wn_y_base + yoff
        ovr = Image.new("RGBA", img.size, (0,0,0,0))
        od = ImageDraw.Draw(ovr)
        # Label above the box
        lab_f = F(54, "black")
        draw_text_shadow(od, (wn_x + wn_w//2, wn_y - 30),
                         "WATCH THIS NEXT", lab_f,
                         (255,235,80,alpha), anchor="mm",
                         shadow=(0,0,0,min(180,alpha)), offset=(3,3))
        # Solid border box (semi-transparent dark fill)
        od.rounded_rectangle([wn_x, wn_y, wn_x+wn_w, wn_y+wn_h], radius=20,
                             fill=(15,15,40, min(170,alpha)),
                             outline=(255,255,255, min(255,alpha)), width=6)
        # Inner play icon
        cx, cy = wn_x + wn_w//2, wn_y + wn_h//2 - 20
        od.ellipse([cx-70, cy-70, cx+70, cy+70],
                   outline=(255,255,255,alpha), width=6)
        od.polygon([(cx-22, cy-32), (cx-22, cy+32), (cx+30, cy)],
                   fill=(255,255,255,alpha))
        # Placeholder label below icon
        pf_f = F(34, "bold")
        draw_text_shadow(od, (cx, wn_y+wn_h-60), "YOUR NEXT VIDEO HERE",
                         pf_f, (255,255,255,alpha), anchor="mm",
                         shadow=(0,0,0,min(180,alpha)), offset=(2,2))
        img.alpha_composite(ovr)

    # 4) Right column — Subscribe card + score prompt
    if frame_num >= 70:
        f = frame_num - 70
        if f < 25:
            t = f/25
            ease = 1 - (1-t)**3
            xoff = int(500*(1-ease))
            alpha = int(255*min(1, t*1.3))
        else:
            xoff = 0; alpha = 255
        pulse = 1.0 + 0.04*math.sin((frame_num-70)/15)
        rc_w, rc_h = 800, 450
        rc_x = 1040 + xoff
        rc_y = 470
        ovr = Image.new("RGBA", img.size, (0,0,0,0))
        od = ImageDraw.Draw(ovr)
        od.rounded_rectangle([rc_x, rc_y, rc_x+rc_w, rc_y+rc_h], radius=24,
                             fill=(15,15,40, min(210,alpha)),
                             outline=(255,255,255, min(200,alpha)), width=5)
        # Heading
        sf = F(54, "xbold")
        draw_text_shadow(od, (rc_x+rc_w//2, rc_y+55), "LIKED THIS QUIZ?",
                         sf, (255,255,255,alpha), anchor="mm",
                         shadow=(0,0,0, min(180,alpha)), offset=(3,3))
        # SUBSCRIBE button
        btn_w = int(560*pulse); btn_h = int(140*pulse)
        btn_x = rc_x + rc_w//2 - btn_w//2
        btn_y = rc_y + 130
        od.rounded_rectangle([btn_x, btn_y, btn_x+btn_w, btn_y+btn_h], radius=28,
                             fill=(220,30,60, min(245,alpha)),
                             outline=(255,255,255, min(255,alpha)), width=5)
        sub_f = F(int(72*pulse), "black")
        draw_text_shadow(od, (rc_x+rc_w//2, btn_y+btn_h//2), "SUBSCRIBE",
                         sub_f, (255,255,255,alpha), anchor="mm",
                         shadow=(0,0,0,min(180,alpha)), offset=(3,3))
        # Bell hint
        hf = F(32, "bold")
        draw_text_shadow(od, (rc_x+rc_w//2, btn_y+btn_h+50),
                         "and ring the bell", hf,
                         (255,255,255,alpha), anchor="mm",
                         shadow=(0,0,0,min(180,alpha)), offset=(2,2))
        # Score prompt at bottom
        score_f = F(38, "xbold")
        draw_text_shadow(od, (rc_x+rc_w//2, rc_y+rc_h-50),
                         "Drop your score below ↓", score_f,
                         (255,235,80,alpha), anchor="mm",
                         shadow=(0,0,0,min(180,alpha)), offset=(2,2))
        img.alpha_composite(ovr)

    return img.convert("RGB")


# ---------- question segment scheduling ----------
def question_timing(qnum):
    qd = DURS[f"vo_q{qnum:02d}_question"]
    od = DURS[f"vo_q{qnum:02d}_options"]
    ad = DURS[f"vo_q{qnum:02d}_answer"]
    fps = FPS
    # Phase A:
    # 0-30: drop+type, then question card visible
    # 30: vo_question starts
    # 30 + ceil(qd*fps): vo_question ends
    # +6 frames pad
    # then vo_options starts -> letter bounces relative to that
    # +9 frames pad after options end
    intro_anim = 30
    pad_q = 6
    options_start_frame = intro_anim + math.ceil(qd*fps) + pad_q
    pad_o = 9
    phase_a_frames = options_start_frame + math.ceil(od*fps) + pad_o
    phase_b_frames = 6 * fps  # exactly 180
    pad_pre_ans = 9
    pad_post_ans = 30
    phase_c_frames = pad_pre_ans + math.ceil(ad*fps) + pad_post_ans
    return {
        "phase_a": phase_a_frames,
        "phase_b": phase_b_frames,
        "phase_c": phase_c_frames,
        "total": phase_a_frames + phase_b_frames + phase_c_frames,
        "options_start_frame": options_start_frame,  # within phase A
        "question_vo_frame": intro_anim,
    }


def render_question_frame(args):
    """One frame in a question segment. Used by Pool.map."""
    qnum, abs_frame = args
    q = QUESTIONS[qnum-1]
    t = question_timing(qnum)
    letter_frames = json.loads((AUDIO / f"vo_q{qnum:02d}_letter_frames.json").read_text())

    if abs_frame < t["phase_a"]:
        phase = "A"; pf = abs_frame
        letter_offsets = t["options_start_frame"]
        return render_question_card(load_bg("bg_question"), abs_frame, q,
            phase, pf, letter_frames, letter_offsets)
    elif abs_frame < t["phase_a"] + t["phase_b"]:
        phase = "B"; pf = abs_frame - t["phase_a"]
        # in countdown: keep letter_offsets so latch any final bounce at start; not needed actually
        return render_question_card(load_bg("bg_question"), abs_frame, q,
            phase, pf, letter_frames, t["options_start_frame"])
    else:
        phase = "C"; pf = abs_frame - t["phase_a"] - t["phase_b"]
        # reveal timeline (within phase C)
        return render_question_card(load_bg("bg_reveal"), abs_frame, q,
            phase, pf, letter_frames, t["options_start_frame"],
            answer_state_frames={"correct_start": 5, "dim_start": 0},
            confetti_start=25,
            banner_start=15,
            fun_fact_start=30)


def render_intro_segment(out_mp4):
    total = math.ceil(DURS["vo_intro"] * FPS) + 18  # ~0.6s tail
    render_segment(out_mp4, total, "intro", lambda i: render_intro_frame(i))

def render_outro_segment(out_mp4):
    total = math.ceil(DURS["vo_outro"] * FPS) + 30
    render_segment(out_mp4, total, "outro", lambda i: render_outro_frame(i, total))

def render_bump_segment(out_mp4, level):
    total = 90
    render_segment(out_mp4, total, f"bump_{level}", lambda i: render_bump_frame(i, level))

def render_question_segment(out_mp4, qnum):
    t = question_timing(qnum)
    total = t["total"]
    render_segment(out_mp4, total, f"q{qnum:02d}",
                   lambda i: render_question_frame((qnum, i)))


# ---------- segment encode loop ----------
def _worker_init():
    # Reset bg cache per worker
    global _bg_cache, _font_cache
    _bg_cache = {}
    _font_cache = {}

# top-level worker callable
def _render_one(args):
    seg_type, idx, qnum = args
    if seg_type == "intro":
        img = render_intro_frame(idx)
    elif seg_type == "outro":
        # total computed elsewhere; we'll pass via globals? simpler: recompute
        total = math.ceil(DURS["vo_outro"] * FPS) + 30
        img = render_outro_frame(idx, total)
    elif seg_type.startswith("bump_"):
        img = render_bump_frame(idx, seg_type.split("_")[1])
    elif seg_type == "question":
        img = render_question_frame((qnum, idx))
    else:
        raise ValueError(seg_type)
    return idx, img

def render_segment_parallel(out_mp4, total_frames, seg_type, qnum=None):
    tmpdir = tempfile.mkdtemp(prefix=f"{seg_type}_", dir=str(SEG_DIR))
    t0 = time.time()
    args = [(seg_type, i, qnum) for i in range(total_frames)]
    workers = max(2, (os.cpu_count() or 4) - 1)
    progress = 0
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as pool:
        futs = {pool.submit(_render_one, a): a[1] for a in args}
        for fut in as_completed(futs):
            idx, img = fut.result()
            img.save(f"{tmpdir}/{idx:05d}.jpg", "JPEG", quality=92)
            progress += 1
            if progress % 300 == 0:
                print(f"  {seg_type}: {progress}/{total_frames} frames", flush=True)
    enc_t = time.time()
    subprocess.run(["ffmpeg","-y","-framerate", str(FPS),
        "-i", f"{tmpdir}/%05d.jpg",
        "-c:v","libx264","-preset","fast","-crf","18","-pix_fmt","yuv420p",
        "-r", str(FPS), str(out_mp4)], check=True, stderr=subprocess.DEVNULL)
    shutil.rmtree(tmpdir)
    print(f"  → {out_mp4.name} ({total_frames}f, render {enc_t-t0:.1f}s, encode {time.time()-enc_t:.1f}s)", flush=True)


def build_all():
    # 1) intro
    print("=== intro ===")
    intro_frames = math.ceil(DURS["vo_intro"] * FPS) + 18
    render_segment_parallel(SEG_DIR/"seg_intro.mp4", intro_frames, "intro")
    # 2) bump easy
    print("=== bump_easy ===")
    render_segment_parallel(SEG_DIR/"seg_bump_easy.mp4", 90, "bump_easy")
    # 3) Q1-6
    for n in range(1, 7):
        print(f"=== Q{n:02d} ===")
        t = question_timing(n)
        render_segment_parallel(SEG_DIR/f"seg_q{n:02d}.mp4", t["total"], "question", qnum=n)
    # 4) bump medium
    print("=== bump_medium ===")
    render_segment_parallel(SEG_DIR/"seg_bump_medium.mp4", 90, "bump_medium")
    # 5) Q7-16
    for n in range(7, 17):
        print(f"=== Q{n:02d} ===")
        t = question_timing(n)
        render_segment_parallel(SEG_DIR/f"seg_q{n:02d}.mp4", t["total"], "question", qnum=n)
    # 6) bump hard
    print("=== bump_hard ===")
    render_segment_parallel(SEG_DIR/"seg_bump_hard.mp4", 90, "bump_hard")
    # 7) Q17-20
    for n in range(17, 21):
        print(f"=== Q{n:02d} ===")
        t = question_timing(n)
        render_segment_parallel(SEG_DIR/f"seg_q{n:02d}.mp4", t["total"], "question", qnum=n)
    # 8) outro
    print("=== outro ===")
    outro_frames = math.ceil(DURS["vo_outro"] * FPS) + 30
    render_segment_parallel(SEG_DIR/"seg_outro.mp4", outro_frames, "outro")
    # Save timings json for later assembly
    timings = {}
    for n in range(1, 21):
        timings[f"q{n:02d}"] = question_timing(n)
    timings["intro_frames"] = intro_frames
    timings["outro_frames"] = outro_frames
    (SEG_DIR / "timings.json").write_text(json.dumps(timings, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # render single test frame
        img = render_intro_frame(120)
        img.save("/tmp/intro_test.jpg", "JPEG", quality=92)
        print("test intro frame → /tmp/intro_test.jpg")
        img2 = render_question_frame((1, 100))
        img2.save("/tmp/q01_test.jpg", "JPEG", quality=92)
        print("test q01 frame → /tmp/q01_test.jpg")
        img3 = render_question_frame((1, question_timing(1)["phase_a"] + question_timing(1)["phase_b"] + 40))
        img3.save("/tmp/q01_reveal_test.jpg", "JPEG", quality=92)
        print("test q01 reveal → /tmp/q01_reveal_test.jpg")
        img4 = render_bump_frame(50, "medium")
        img4.save("/tmp/bump_test.jpg", "JPEG", quality=92)
        print("test bump frame → /tmp/bump_test.jpg")
        img5 = render_outro_frame(200, 400)
        img5.save("/tmp/outro_test.jpg", "JPEG", quality=92)
    else:
        build_all()
