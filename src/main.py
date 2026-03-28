import pygame
import sys
import math
import random
import time
import os
import numpy as np
from PIL import Image as PILImage

pygame.init()
pygame.mixer.init()

SCREEN_W, SCREEN_H = 1024, 768
screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
pygame.display.set_caption("Knight Fighter")
clock = pygame.time.Clock()
FPS = 60

BASE = os.path.dirname(os.path.abspath(__file__))

def asset(filename):
    exact = os.path.join(BASE, filename)
    if os.path.exists(exact):
        return exact
    def n(s): return s.lower().replace(" ","").replace("_","")
    for f in os.listdir(BASE):
        if n(f) == n(filename):
            return os.path.join(BASE, f)
    pngs = [f for f in os.listdir(BASE) if f.lower().endswith(('.png','.jpg'))]
    raise FileNotFoundError(f"'{filename}' not found.\nFound: {pngs}")

# ── Spritesheet loader: pure-black bg → transparent ──────────────────────────
def load_spritesheet(path, frame_w, frame_h, scale, valid_per_row):
    """
    valid_per_row: dict {row_index: num_frames}
    Returns: dict {row_index: [pygame.Surface, ...]}
    """
    pil = PILImage.open(path).convert("RGB")
    arr = np.array(pil)
    sh, sw = arr.shape[:2]
    cols = sw // frame_w
    rows = sh // frame_h

    # Build RGBA once: pixels with ALL channels <= 3 become transparent
    rgba = np.zeros((sh, sw, 4), dtype=np.uint8)
    rgba[:, :, :3] = arr
    rgba[:, :, 3]  = np.where(np.all(arr <= 3, axis=2), 0, 255)

    nw = int(frame_w * scale)
    nh = int(frame_h * scale)

    frames = {}
    for r, n_frames in valid_per_row.items():
        if r >= rows:
            continue
        frames[r] = []
        for c in range(min(n_frames, cols)):
            cell = rgba[r*frame_h:(r+1)*frame_h, c*frame_w:(c+1)*frame_w]
            pil_cell = PILImage.fromarray(cell, "RGBA")
            if scale != 1.0:
                pil_cell = pil_cell.resize((nw, nh), PILImage.NEAREST)
            surf = pygame.image.fromstring(pil_cell.tobytes(), pil_cell.size, "RGBA").convert_alpha()
            frames[r].append(surf)
    return frames

# ── Row layout (confirmed by user) ───────────────────────────────────────────
# SOLDIER (900x700, 9 cols x 7 rows, 100x100 cells):
#   Row 0 = idle        (6 frames)
#   Row 1 = walk        (8 frames)
#   Row 2 = (unused - blank or extra)
#   Row 3 = sword attack(6 frames)
#   Row 4 = bow shot    (9 frames)
#   Row 5 = take damage (4 frames)
#   Row 6 = death       (4 frames)
#
# ORC (800x600, 8 cols x 6 rows, 100x100 cells):
#   Row 0 = idle        (6 frames)
#   Row 1 = walk        (8 frames)
#   Row 2 = attack      (6 frames)
#   Row 3 = attack2     (6 frames)  <- second attack row
#   Row 4 = take damage (4 frames)
#   Row 5 = death       (4 frames)

SOLDIER_VALID = {0:6, 1:8, 3:6, 4:9, 5:4, 6:4}
ORC_VALID     = {0:6, 1:8, 2:6, 3:6, 4:4, 5:4}

# Row constants — Soldier
S_IDLE   = 0
S_WALK   = 1
S_ATK    = 3   # sword
S_SHOOT  = 4   # bow
S_HURT   = 5
S_DEATH  = 6

# Row constants — Orc
O_IDLE   = 0
O_WALK   = 1
O_ATK    = 2
O_HURT   = 4
O_DEATH  = 5

SOLDIER_SCALE = 3.0
ORC_SCALE     = 2.6
FRAME_W = FRAME_H = 100

print("Loading assets...")
soldier_frames = load_spritesheet(asset("Soldier.png"), FRAME_W, FRAME_H, SOLDIER_SCALE, SOLDIER_VALID)
orc_frames     = load_spritesheet(asset("Orc.png"),     FRAME_W, FRAME_H, ORC_SCALE,     ORC_VALID)

# ── Arrow ─────────────────────────────────────────────────────────────────────
arrow_pil  = PILImage.open(asset("Arrow01(100x100).png")).convert("RGB")
arrow_arr  = np.array(arrow_pil)
arrow_rgba = np.zeros((*arrow_arr.shape[:2], 4), dtype=np.uint8)
arrow_rgba[:,:,:3] = arrow_arr
arrow_rgba[:,:,3]  = np.where(np.all(arrow_arr <= 10, axis=2), 0, 255)
arrow_pil_rgba = PILImage.fromarray(arrow_rgba, "RGBA").resize((64, 64), PILImage.NEAREST)
arrow_base = pygame.image.fromstring(arrow_pil_rgba.tobytes(), (64,64), "RGBA").convert_alpha()

def make_arrow(angle_deg):
    return pygame.transform.rotate(arrow_base, angle_deg)

# ── Background ────────────────────────────────────────────────────────────────
bg = pygame.transform.scale(pygame.image.load(asset("map.png")).convert(), (SCREEN_W, SCREEN_H))

# ── Direction constants ───────────────────────────────────────────────────────
DIR_UP, DIR_LEFT, DIR_DOWN, DIR_RIGHT = 0, 1, 2, 3

def dir_from_vec(dx, dy):
    if abs(dx) >= abs(dy):
        return DIR_RIGHT if dx >= 0 else DIR_LEFT
    return DIR_DOWN if dy >= 0 else DIR_UP

# ── Tight hitbox: sprite occupies ~32% of 100px cell, centered ───────────────
def make_hitbox(x, y, cw, ch):
    hw = int(cw * 0.33)
    hh = int(ch * 0.33)
    return pygame.Rect(
        x + cw // 2 - hw // 2,
        y + ch // 2 - hh // 2,
        hw, hh
    )

# ── Animation helper ──────────────────────────────────────────────────────────
def get_frame(frames_dict, row, idx):
    row_list = frames_dict.get(row)
    if not row_list:
        return None
    return row_list[idx % len(row_list)]

def row_len(frames_dict, row):
    return len(frames_dict.get(row, [1]))

# ── States ────────────────────────────────────────────────────────────────────
ANIM_IDLE  = "idle"
ANIM_WALK  = "walk"
ANIM_ATK   = "atk"
ANIM_SHOOT = "shoot"
ANIM_HURT  = "hurt"
ANIM_DEATH = "death"

# ── Arrow projectile ──────────────────────────────────────────────────────────
class Arrow:
    SPEED = 14

    def __init__(self, x, y, mx, my):
        self.x, self.y = float(x), float(y)
        dx, dy = mx - x, my - y
        d = math.hypot(dx, dy) or 1
        self.vx = dx / d * self.SPEED
        self.vy = dy / d * self.SPEED
        angle = -math.degrees(math.atan2(dy, dx))
        self.surf  = make_arrow(angle)
        self.alive = True

    def update(self):
        self.x += self.vx
        self.y += self.vy
        if not (-80 < self.x < SCREEN_W+80 and -80 < self.y < SCREEN_H+80):
            self.alive = False

    def get_rect(self):
        return pygame.Rect(self.x - 10, self.y - 10, 20, 20)

    def draw(self, surf):
        w, h = self.surf.get_size()
        surf.blit(self.surf, (int(self.x - w//2), int(self.y - h//2)))

# ── Player ────────────────────────────────────────────────────────────────────
class Player:
    SPEED    = 3.0
    MAX_HP   = 100
    SHOOT_CD = 0.4
    FPS_WALK = 8
    FPS_ATK  = 12
    FPS_HURT = 10
    FPS_DEATH= 8

    def __init__(self, x, y):
        self.x, self.y   = float(x), float(y)
        self.hp          = self.MAX_HP
        self.direction   = DIR_DOWN
        self.anim_state  = ANIM_IDLE
        self.frame_idx   = 0
        self.frame_timer = 0.0
        self.shoot_timer = 0.0
        self.alive       = True
        self.cw = int(FRAME_W * SOLDIER_SCALE)
        self.ch = int(FRAME_H * SOLDIER_SCALE)

    # ── row selection ──
    def _anim_row(self):
        if self.anim_state == ANIM_IDLE:  return S_IDLE
        if self.anim_state == ANIM_WALK:  return S_WALK
        if self.anim_state == ANIM_ATK:   return S_ATK
        if self.anim_state == ANIM_SHOOT: return S_SHOOT
        if self.anim_state == ANIM_HURT:  return S_HURT
        if self.anim_state == ANIM_DEATH: return S_DEATH
        return S_IDLE

    def _anim_fps(self):
        if self.anim_state == ANIM_WALK:  return self.FPS_WALK
        if self.anim_state in (ANIM_ATK, ANIM_SHOOT): return self.FPS_ATK
        if self.anim_state == ANIM_HURT:  return self.FPS_HURT
        if self.anim_state == ANIM_DEATH: return self.FPS_DEATH
        return 6  # idle

    def _set_anim(self, state):
        if self.anim_state == state:
            return
        # Priority: death > hurt > shoot/atk > walk > idle
        priority = {ANIM_DEATH:5, ANIM_HURT:4, ANIM_SHOOT:3, ANIM_ATK:3,
                    ANIM_WALK:2, ANIM_IDLE:1}
        if priority.get(state, 0) >= priority.get(self.anim_state, 0):
            self.anim_state  = state
            self.frame_idx   = 0
            self.frame_timer = 0.0

    def shoot(self, arrows, mx, my):
        if self.shoot_timer > 0 or not self.alive:
            return
        cx, cy = self.x + self.cw//2, self.y + self.ch//2
        arrows.append(Arrow(cx, cy, mx, my))
        self.shoot_timer = self.SHOOT_CD
        dx, dy = mx - cx, my - cy
        if abs(dx) > 4 or abs(dy) > 4:
            self.direction = dir_from_vec(dx, dy)
        self._set_anim(ANIM_SHOOT)

    def take_damage(self, amount):
        if not self.alive: return
        self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            self._set_anim(ANIM_DEATH)
            self.alive = False
        else:
            self._set_anim(ANIM_HURT)

    def update(self, dt, keys):
        # Movement (only when not in death/hurt anim)
        moving = False
        if self.alive and self.anim_state not in (ANIM_HURT, ANIM_DEATH):
            dx, dy = 0, 0
            if keys[pygame.K_w] or keys[pygame.K_UP]:    dy -= 1
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:  dy += 1
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:  dx -= 1
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]: dx += 1
            if dx or dy:
                moving = True
                length = math.hypot(dx, dy)
                self.x += dx / length * self.SPEED
                self.y += dy / length * self.SPEED
                self.direction = dir_from_vec(dx, dy)

        self.x = max(0, min(SCREEN_W - self.cw, self.x))
        self.y = max(0, min(SCREEN_H - self.ch, self.y))

        # Transition to walk/idle if no override anim is playing
        if self.anim_state not in (ANIM_DEATH, ANIM_HURT):
            if moving:
                self._set_anim(ANIM_WALK)
            elif self.anim_state == ANIM_WALK:
                self._set_anim(ANIM_IDLE)

        # Advance animation frame
        self.frame_timer += dt
        fps  = self._anim_fps()
        dur  = 1.0 / fps
        row  = self._anim_row()
        rlen = row_len(soldier_frames, row)

        if self.frame_timer >= dur:
            self.frame_timer = 0.0
            self.frame_idx += 1
            if self.frame_idx >= rlen:
                # One-shot animations → go back to idle/walk
                if self.anim_state in (ANIM_HURT, ANIM_SHOOT):
                    self.anim_state  = ANIM_IDLE
                    self.frame_idx   = 0
                elif self.anim_state == ANIM_DEATH:
                    self.frame_idx = rlen - 1  # freeze on last frame
                else:
                    self.frame_idx = 0  # loop idle/walk

        self.shoot_timer = max(0.0, self.shoot_timer - dt)

    def get_rect(self):
        return make_hitbox(self.x, self.y, self.cw, self.ch)

    def draw(self, surface):
        row   = self._anim_row()
        frame = get_frame(soldier_frames, row, self.frame_idx)
        if frame is None:
            return
        if self.direction == DIR_LEFT:
            frame = pygame.transform.flip(frame, True, False)
        surface.blit(frame, (int(self.x), int(self.y)))

        if self.alive:
            bx, by = int(self.x), int(self.y) - 8
            pygame.draw.rect(surface, (60, 0, 0),    (bx, by, self.cw, 5))
            fill = int(self.cw * self.hp / self.MAX_HP)
            pygame.draw.rect(surface, (0, 200, 60),  (bx, by, fill, 5))

# ── Orc ───────────────────────────────────────────────────────────────────────
class Orc:
    SPEED    = 1.3
    MAX_HP   = 30
    DMG      = 10
    ATK_CD   = 1.2
    FPS_WALK = 7
    FPS_ATK  = 10
    FPS_HURT = 10
    FPS_DEATH= 7

    def __init__(self, x, y):
        self.x, self.y   = float(x), float(y)
        self.hp          = self.MAX_HP
        self.direction   = DIR_DOWN
        self.anim_state  = ANIM_IDLE
        self.frame_idx   = 0
        self.frame_timer = 0.0
        self.atk_timer   = 0.0
        self.alive       = True
        self.dead_done   = False   # finished death anim → remove
        self.cw = int(FRAME_W * ORC_SCALE)
        self.ch = int(FRAME_H * ORC_SCALE)

    def _anim_row(self):
        if self.anim_state == ANIM_IDLE:  return O_IDLE
        if self.anim_state == ANIM_WALK:  return O_WALK
        if self.anim_state == ANIM_ATK:   return O_ATK
        if self.anim_state == ANIM_HURT:  return O_HURT
        if self.anim_state == ANIM_DEATH: return O_DEATH
        return O_IDLE

    def _anim_fps(self):
        if self.anim_state == ANIM_WALK:  return self.FPS_WALK
        if self.anim_state == ANIM_ATK:   return self.FPS_ATK
        if self.anim_state == ANIM_HURT:  return self.FPS_HURT
        if self.anim_state == ANIM_DEATH: return self.FPS_DEATH
        return 5

    def _set_anim(self, state):
        priority = {ANIM_DEATH:5, ANIM_HURT:4, ANIM_ATK:3, ANIM_WALK:2, ANIM_IDLE:1}
        if priority.get(state, 0) >= priority.get(self.anim_state, 0):
            self.anim_state  = state
            self.frame_idx   = 0
            self.frame_timer = 0.0

    def die(self):
        self.alive = False
        self._set_anim(ANIM_DEATH)

    def take_damage(self, amount):
        if not self.alive: return
        self.hp = max(0, self.hp - amount)
        if self.hp == 0:
            self.die()
        else:
            self._set_anim(ANIM_HURT)

    def update(self, dt, player):
        # Always advance animation even when dead (for death anim)
        self.frame_timer += dt
        fps  = self._anim_fps()
        row  = self._anim_row()
        rlen = row_len(orc_frames, row)

        if self.frame_timer >= 1.0 / fps:
            self.frame_timer = 0.0
            self.frame_idx  += 1
            if self.frame_idx >= rlen:
                if self.anim_state == ANIM_DEATH:
                    self.frame_idx = rlen - 1
                    self.dead_done = True
                elif self.anim_state == ANIM_HURT:
                    self.anim_state = ANIM_IDLE
                    self.frame_idx  = 0
                elif self.anim_state == ANIM_ATK:
                    self.anim_state = ANIM_IDLE
                    self.frame_idx  = 0
                else:
                    self.frame_idx = 0

        if not self.alive:
            return

        # Movement & attack logic using tight hitbox centers
        pr   = player.get_rect()
        my_r = self.get_rect()
        px, py = pr.centerx, pr.centery
        ox, oy = my_r.centerx, my_r.centery
        dx, dy = px - ox, py - oy
        dist   = math.hypot(dx, dy)

        # Attack when hitboxes nearly touch
        attack_range = (pr.width + my_r.width) * 0.55 + 2

        if self.anim_state not in (ANIM_HURT, ANIM_ATK):
            if dist > attack_range:
                # Walk toward player
                self.x += dx / dist * self.SPEED
                self.y += dy / dist * self.SPEED
                self.direction = dir_from_vec(dx, dy)
                self._set_anim(ANIM_WALK)
            else:
                # In range: try to attack
                self.atk_timer -= dt
                if self.atk_timer <= 0:
                    player.take_damage(self.DMG)
                    self.atk_timer = self.ATK_CD
                    self._set_anim(ANIM_ATK)
                elif self.anim_state == ANIM_WALK:
                    self._set_anim(ANIM_IDLE)

    def get_rect(self):
        return make_hitbox(self.x, self.y, self.cw, self.ch)

    def draw(self, surface):
        row   = self._anim_row()
        frame = get_frame(orc_frames, row, self.frame_idx)
        if frame is None:
            return
        if self.direction == DIR_LEFT:
            frame = pygame.transform.flip(frame, True, False)
        surface.blit(frame, (int(self.x), int(self.y)))

        if self.alive:
            bx, by = int(self.x), int(self.y) - 7
            pygame.draw.rect(surface, (80, 0, 0), (bx, by, self.cw, 4))
            fill = int(self.cw * self.hp / self.MAX_HP)
            pygame.draw.rect(surface, (200, 50, 0), (bx, by, fill, 4))

# ── Spawn ─────────────────────────────────────────────────────────────────────
def random_spawn():
    M = 80
    side = random.randint(0, 3)
    if side == 0: return random.randint(0, SCREEN_W), -M
    if side == 1: return random.randint(0, SCREEN_W), SCREEN_H + M
    if side == 2: return -M, random.randint(0, SCREEN_H)
    return SCREEN_W + M, random.randint(0, SCREEN_H)

# ── UI ────────────────────────────────────────────────────────────────────────
font_big   = pygame.font.SysFont("Arial", 52, bold=True)
font_med   = pygame.font.SysFont("Arial", 28, bold=True)
font_small = pygame.font.SysFont("Arial", 20)

def draw_text(surf, text, font, color, cx, cy):
    s = font.render(text, True, (0,0,0))
    surf.blit(s, s.get_rect(center=(cx+2, cy+2)))
    t = font.render(text, True, color)
    surf.blit(t, t.get_rect(center=(cx, cy)))

pygame.mouse.set_visible(False)

def draw_cursor(surface, mx, my):
    R, T = 13, 2
    pygame.draw.circle(surface, (255,70,70), (mx, my), R, T)
    pygame.draw.line(surface, (255,70,70), (mx-R-4, my), (mx+R+4, my), T)
    pygame.draw.line(surface, (255,70,70), (mx, my-R-4), (mx, my+R+4), T)

# ── Main loop ─────────────────────────────────────────────────────────────────
STATE_MENU, STATE_PLAY, STATE_DEAD = "menu", "play", "dead"

def run_game():
    state = STATE_MENU
    player = None
    orcs, arrows = [], []
    score = kills = 0
    start_time = elapsed = 0.0
    wave = 1
    spawn_timer = spawn_interval = 0.0
    # For death screen delay
    death_timer = 0.0

    def reset():
        nonlocal player, orcs, arrows, score, kills
        nonlocal start_time, elapsed, wave, spawn_timer, spawn_interval
        player = Player(SCREEN_W//2 - int(FRAME_W*SOLDIER_SCALE)//2,
                        SCREEN_H//2 - int(FRAME_H*SOLDIER_SCALE)//2)
        orcs, arrows = [], []
        score = kills = 0
        start_time = time.time()
        elapsed = 0.0
        wave = 1
        spawn_timer = 0.0
        spawn_interval = 3.0

    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        mx, my = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if state == STATE_MENU and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    reset(); state = STATE_PLAY
                elif state == STATE_DEAD and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    state = STATE_MENU
                elif state == STATE_PLAY and event.key == pygame.K_ESCAPE:
                    state = STATE_MENU
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and state == STATE_PLAY:
                player.shoot(arrows, mx, my)

        if state == STATE_PLAY:
            keys = pygame.key.get_pressed()
            if keys[pygame.K_SPACE]:
                player.shoot(arrows, mx, my)

            elapsed = time.time() - start_time

            new_wave = int(elapsed // 30) + 1
            if new_wave != wave:
                wave = new_wave
                spawn_interval = max(0.4, 3.0 - (wave-1)*0.4)

            spawn_timer -= dt
            if spawn_timer <= 0:
                sx, sy = random_spawn()
                orcs.append(Orc(sx, sy))
                spawn_timer = spawn_interval * random.uniform(0.7, 1.3)

            player.update(dt, keys)
            for orc in orcs:
                orc.update(dt, player)

            # Arrow ↔ orc collision
            for arrow in arrows:
                arrow.update()
                if not arrow.alive:
                    continue
                ar = arrow.get_rect()
                for orc in orcs:
                    if orc.alive and ar.colliderect(orc.get_rect()):
                        orc.die()
                        arrow.alive = False
                        kills += 1
                        score += 10
                        break

            arrows = [a for a in arrows if a.alive]
            # Keep orcs until death anim finishes
            orcs = [o for o in orcs if not (not o.alive and o.dead_done)]

            if not player.alive:
                state = STATE_DEAD
                death_timer = 0.0

        if state == STATE_DEAD:
            death_timer += dt
            # Let death anim finish before showing overlay
            player.update(dt, pygame.key.get_pressed())

        # ── Draw ──
        screen.blit(bg, (0, 0))

        if state == STATE_MENU:
            ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 150))
            screen.blit(ov, (0, 0))
            draw_text(screen, "KNIGHT FIGHTER",                   font_big,   (255,215,0),   SCREEN_W//2, SCREEN_H//2-110)
            draw_text(screen, "Survive the orc horde!",           font_med,   (255,255,255), SCREEN_W//2, SCREEN_H//2-45)
            draw_text(screen, "WASD — move",                      font_small, (200,200,200), SCREEN_W//2, SCREEN_H//2+10)
            draw_text(screen, "LMB / SPACE — shoot toward cursor",font_small, (200,200,200), SCREEN_W//2, SCREEN_H//2+40)
            draw_text(screen, "Waves escalate every 30 sec",      font_small, (200,160,100), SCREEN_W//2, SCREEN_H//2+75)
            draw_text(screen, "SPACE / ENTER to start",           font_med,   (100,255,100), SCREEN_W//2, SCREEN_H//2+130)

        elif state in (STATE_PLAY, STATE_DEAD):
            for orc in orcs:     orc.draw(screen)
            for arrow in arrows: arrow.draw(screen)
            if player:           player.draw(screen)

            mins, secs = int(elapsed)//60, int(elapsed)%60
            draw_text(screen, f"{mins:02d}:{secs:02d}", font_med,   (255,255,255), 70,          25)
            draw_text(screen, f"Score: {score}",        font_med,   (255,215,0),   SCREEN_W//2, 25)
            draw_text(screen, f"Wave {wave}",           font_med,   (255,100,100), SCREEN_W-90, 25)
            draw_text(screen, f"Kills: {kills}",        font_small, (180,255,180), SCREEN_W-90, 55)

            if player:
                hw, hh = 220, 14
                hx, hy = SCREEN_W//2 - hw//2, SCREEN_H - 30
                pygame.draw.rect(screen, (70,0,0), (hx,hy,hw,hh), border_radius=5)
                fill = int(hw * player.hp / player.MAX_HP)
                col = (0,210,60) if player.hp>50 else (220,200,0) if player.hp>25 else (230,40,0)
                if fill > 0:
                    pygame.draw.rect(screen, col, (hx,hy,fill,hh), border_radius=5)
                pygame.draw.rect(screen, (200,200,200), (hx,hy,hw,hh), 1, border_radius=5)
                draw_text(screen, f"HP  {player.hp}", font_small, (255,255,255), SCREEN_W//2, hy-13)

            if state == STATE_DEAD and death_timer > 1.0:
                ov = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
                alpha = min(int((death_timer - 1.0) * 200), 170)
                ov.fill((0, 0, 0, alpha))
                screen.blit(ov, (0, 0))
                if death_timer > 1.8:
                    draw_text(screen, "YOU DIED",                              font_big, (220,30,30),  SCREEN_W//2, SCREEN_H//2-100)
                    draw_text(screen, f"Score: {score}   Kills: {kills}",     font_med, (255,215,0),  SCREEN_W//2, SCREEN_H//2-20)
                    draw_text(screen, f"Time: {mins:02d}:{secs:02d}   Wave {wave}", font_med,(255,160,60),SCREEN_W//2, SCREEN_H//2+35)
                    draw_text(screen, "SPACE / ENTER — menu",                 font_med, (180,255,180),SCREEN_W//2, SCREEN_H//2+100)

        draw_cursor(screen, mx, my)
        pygame.display.flip()

run_game()