import pygame
import sys
import math
import random
import time

# --- Init ---
pygame.init()
pygame.mixer.init()

SCREEN_W, SCREEN_H = 1024, 768
screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
pygame.display.set_caption("Knight Fighter")
clock = pygame.time.Clock()
FPS = 60

# --- Asset paths ---
import os
BASE = os.path.dirname(os.path.abspath(__file__))

def asset(filename):
    exact = os.path.join(BASE, filename)
    if os.path.exists(exact):
        return exact
    def normalize(s):
        return s.lower().replace(" ", "").replace("_", "")
    target = normalize(filename)
    for f in os.listdir(BASE):
        if normalize(f) == target:
            return os.path.join(BASE, f)
    pngs = [f for f in os.listdir(BASE) if f.lower().endswith(('.png', '.jpg'))]
    raise FileNotFoundError(
        f"Asset '{filename}' not found in:\n  {BASE}\n"
        f"PNG files found: {pngs}"
    )

# ── Sprite-sheet helpers ──────────────────────────────────────────────────────
def load_spritesheet(path, frame_w, frame_h, scale=1.0):
    """Return dict of lists: row_index -> [Surface, ...]"""
    sheet = pygame.image.load(path).convert_alpha()
    sw, sh = sheet.get_size()
    cols = sw // frame_w
    rows = sh // frame_h
    frames = {}
    for r in range(rows):
        frames[r] = []
        for c in range(cols):
            surf = pygame.Surface((frame_w, frame_h), pygame.SRCCOLORKEY)
            surf.fill((0, 0, 0))
            surf.set_colorkey((0, 0, 0))
            surf.blit(sheet, (0, 0), (c * frame_w, r * frame_h, frame_w, frame_h))
            if scale != 1.0:
                nw, nh = int(frame_w * scale), int(frame_h * scale)
                surf = pygame.transform.scale(surf, (nw, nh))
            frames[r].append(surf)
    return frames, cols, rows

# ── Spritesheet row mapping (8-direction, common RPG layout) ──────────────────
# Typical LPC / RPG Maker layout rows:
#  0 = walk up     1 = walk left    2 = walk down    3 = walk right
#  4 = atk up      5 = atk left     6 = atk down     7 = atk right
# (death row varies; we'll use row 4+ as fallback)

SOLDIER_SCALE = 1.6
ORC_SCALE = 1.4
FRAME_W, FRAME_H = 100, 100

soldier_frames, sol_cols, sol_rows = load_spritesheet(
    asset("Soldier.png"), FRAME_W, FRAME_H, SOLDIER_SCALE)
orc_frames, orc_cols, orc_rows = load_spritesheet(
    asset("Orc.png"), FRAME_W, FRAME_H, ORC_SCALE)

# Arrow sprite
arrow_raw = pygame.image.load(asset("Arrow01(100x100).png")).convert_alpha()
arrow_raw.set_colorkey((0, 0, 0))
ARROW_SIZE = 32
arrow_base = pygame.transform.scale(arrow_raw, (ARROW_SIZE, ARROW_SIZE))

# Background map
bg_raw = pygame.image.load(asset("map.png")).convert()
bg = pygame.transform.scale(bg_raw, (SCREEN_W, SCREEN_H))

# ── Direction helpers ─────────────────────────────────────────────────────────
# We map: UP=0, LEFT=1, DOWN=2, RIGHT=3  (walk rows in spritesheet)
DIR_UP, DIR_LEFT, DIR_DOWN, DIR_RIGHT = 0, 1, 2, 3

def dir_from_vec(dx, dy):
    if abs(dx) >= abs(dy):
        return DIR_RIGHT if dx >= 0 else DIR_LEFT
    else:
        return DIR_DOWN if dy >= 0 else DIR_UP

# ── Arrow class ───────────────────────────────────────────────────────────────
class Arrow:
    SPEED = 12

    def __init__(self, x, y, direction):
        self.x = float(x)
        self.y = float(y)
        self.direction = direction
        # velocity
        self.vx, self.vy = 0.0, 0.0
        angle = 0  # degrees for rotation
        if direction == DIR_RIGHT:
            self.vx = self.SPEED; angle = 0
        elif direction == DIR_LEFT:
            self.vx = -self.SPEED; angle = 180
        elif direction == DIR_DOWN:
            self.vy = self.SPEED; angle = 270
        elif direction == DIR_UP:
            self.vy = -self.SPEED; angle = 90
        self.surf = pygame.transform.rotate(arrow_base, angle)
        self.alive = True

    def update(self):
        self.x += self.vx
        self.y += self.vy
        if self.x < -50 or self.x > SCREEN_W + 50 or self.y < -50 or self.y > SCREEN_H + 50:
            self.alive = False

    def get_rect(self):
        return pygame.Rect(self.x - 12, self.y - 12, 24, 24)

    def draw(self, surface):
        w, h = self.surf.get_size()
        surface.blit(self.surf, (int(self.x - w // 2), int(self.y - h // 2)))

# ── Player class ──────────────────────────────────────────────────────────────
class Player:
    SPEED = 3
    MAX_HP = 100
    SHOOT_COOLDOWN = 0.4   # seconds between arrows
    FRAME_RATE = 8         # animation fps
    ATK_ROWS = {DIR_UP: 4, DIR_LEFT: 5, DIR_DOWN: 6, DIR_RIGHT: 7}

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.hp = self.MAX_HP
        self.direction = DIR_DOWN
        self.frame_idx = 0
        self.frame_timer = 0.0
        self.shoot_timer = 0.0
        self.moving = False
        self.alive = True
        # Attack flash
        self.atk_anim = False
        self.atk_timer = 0.0
        self.atk_frame = 0
        # Hurt flash
        self.hurt_flash = 0.0
        fw = int(FRAME_W * SOLDIER_SCALE)
        self.w, self.h = fw, int(FRAME_H * SOLDIER_SCALE)

    def shoot(self, arrows):
        if self.shoot_timer <= 0:
            cx = self.x + self.w // 2
            cy = self.y + self.h // 2
            arrows.append(Arrow(cx, cy, self.direction))
            self.shoot_timer = self.SHOOT_COOLDOWN
            self.atk_anim = True
            self.atk_timer = 0.3
            self.atk_frame = 0

    def take_damage(self, amount):
        self.hp -= amount
        self.hurt_flash = 0.3
        if self.hp <= 0:
            self.hp = 0
            self.alive = False

    def update(self, dt, keys):
        # Movement
        dx, dy = 0, 0
        if keys[pygame.K_w] or keys[pygame.K_UP]:    dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:  dy += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:  dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]: dx += 1

        self.moving = (dx != 0 or dy != 0)
        if self.moving:
            length = math.sqrt(dx*dx + dy*dy)
            self.x += dx / length * self.SPEED
            self.y += dy / length * self.SPEED
            self.direction = dir_from_vec(dx, dy)

        # Clamp to screen
        self.x = max(0, min(SCREEN_W - self.w, self.x))
        self.y = max(0, min(SCREEN_H - self.h, self.y))

        # Animation
        self.frame_timer += dt
        frame_dur = 1.0 / self.FRAME_RATE
        if self.moving and self.frame_timer >= frame_dur:
            self.frame_timer = 0.0
            walk_frames = soldier_frames.get(self.direction, soldier_frames[0])
            self.frame_idx = (self.frame_idx + 1) % len(walk_frames)
        elif not self.moving:
            self.frame_idx = 0

        # Attack anim
        if self.atk_anim:
            self.atk_timer -= dt
            atk_row = self.ATK_ROWS.get(self.direction, 6)
            atk_frames = soldier_frames.get(atk_row, soldier_frames[0])
            self.atk_frame = min(int((1 - self.atk_timer / 0.3) * len(atk_frames)), len(atk_frames)-1)
            if self.atk_timer <= 0:
                self.atk_anim = False

        # Cooldowns
        self.shoot_timer = max(0.0, self.shoot_timer - dt)
        self.hurt_flash = max(0.0, self.hurt_flash - dt)

    def get_rect(self):
        return pygame.Rect(int(self.x) + 10, int(self.y) + 10, self.w - 20, self.h - 20)

    def draw(self, surface):
        if self.atk_anim:
            atk_row = self.ATK_ROWS.get(self.direction, 6)
            frames = soldier_frames.get(atk_row, soldier_frames.get(self.direction, soldier_frames[0]))
            idx = min(self.atk_frame, len(frames)-1)
            frame = frames[idx]
        else:
            row_frames = soldier_frames.get(self.direction, soldier_frames[0])
            frame = row_frames[self.frame_idx % len(row_frames)]

        if self.hurt_flash > 0:
            # Red tint
            tinted = frame.copy()
            tinted.fill((200, 0, 0, 100), special_flags=pygame.BLEND_RGBA_ADD)
            surface.blit(tinted, (int(self.x), int(self.y)))
        else:
            surface.blit(frame, (int(self.x), int(self.y)))

        # HP bar
        bar_w = self.w
        bar_h = 6
        bx, by = int(self.x), int(self.y) - 10
        pygame.draw.rect(surface, (60, 0, 0), (bx, by, bar_w, bar_h))
        pygame.draw.rect(surface, (0, 200, 50), (bx, by, int(bar_w * self.hp / self.MAX_HP), bar_h))

# ── Orc class ─────────────────────────────────────────────────────────────────
class Orc:
    SPEED = 1.2
    MAX_HP = 30
    DMG = 10
    ATK_COOLDOWN = 1.2
    FRAME_RATE = 6
    ATK_ROWS = {DIR_UP: 4, DIR_LEFT: 5, DIR_DOWN: 6, DIR_RIGHT: 7}

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.hp = self.MAX_HP
        self.direction = DIR_DOWN
        self.frame_idx = 0
        self.frame_timer = 0.0
        self.atk_timer = 0.0
        self.alive = True
        self.atk_anim = False
        self.atk_anim_timer = 0.0
        self.atk_anim_frame = 0
        fw = int(FRAME_W * ORC_SCALE)
        self.w, self.h = fw, int(FRAME_H * ORC_SCALE)

    def update(self, dt, player):
        if not self.alive:
            return

        px = player.x + player.w // 2
        py = player.y + player.h // 2
        cx = self.x + self.w // 2
        cy = self.y + self.h // 2

        dx = px - cx
        dy = py - cy
        dist = math.sqrt(dx*dx + dy*dy)

        attack_range = (player.w // 2 + self.w // 2) * 0.6

        if dist > attack_range:
            # Move toward player
            self.x += dx / dist * self.SPEED
            self.y += dy / dist * self.SPEED
            self.direction = dir_from_vec(dx, dy)

            # Walk animation
            self.frame_timer += dt
            if self.frame_timer >= 1.0 / self.FRAME_RATE:
                self.frame_timer = 0.0
                walk_frames = orc_frames.get(self.direction, orc_frames[0])
                self.frame_idx = (self.frame_idx + 1) % len(walk_frames)
        else:
            # Attack
            self.atk_timer -= dt
            if self.atk_timer <= 0:
                player.take_damage(self.DMG)
                self.atk_timer = self.ATK_COOLDOWN
                self.atk_anim = True
                self.atk_anim_timer = 0.4
                self.atk_anim_frame = 0

        if self.atk_anim:
            self.atk_anim_timer -= dt
            atk_row = self.ATK_ROWS.get(self.direction, 6)
            atk_frames = orc_frames.get(atk_row, orc_frames.get(self.direction, orc_frames[0]))
            self.atk_anim_frame = min(
                int((1 - self.atk_anim_timer / 0.4) * len(atk_frames)),
                len(atk_frames) - 1
            )
            if self.atk_anim_timer <= 0:
                self.atk_anim = False

    def get_rect(self):
        return pygame.Rect(int(self.x) + 8, int(self.y) + 8, self.w - 16, self.h - 16)

    def draw(self, surface):
        if self.atk_anim:
            atk_row = self.ATK_ROWS.get(self.direction, 6)
            frames = orc_frames.get(atk_row, orc_frames.get(self.direction, orc_frames[0]))
            idx = min(self.atk_anim_frame, len(frames)-1)
            frame = frames[idx]
        else:
            row_frames = orc_frames.get(self.direction, orc_frames[0])
            frame = row_frames[self.frame_idx % len(row_frames)]
        surface.blit(frame, (int(self.x), int(self.y)))

        # HP bar
        bar_w = self.w
        bar_h = 4
        bx, by = int(self.x), int(self.y) - 7
        pygame.draw.rect(surface, (80, 0, 0), (bx, by, bar_w, bar_h))
        pygame.draw.rect(surface, (200, 50, 0), (bx, by, int(bar_w * self.hp / self.MAX_HP), bar_h))

# ── Spawn helpers ─────────────────────────────────────────────────────────────
SPAWN_MARGIN = 60

def random_spawn_pos():
    side = random.randint(0, 3)
    if side == 0:   # top
        return random.randint(0, SCREEN_W), -SPAWN_MARGIN
    elif side == 1: # bottom
        return random.randint(0, SCREEN_W), SCREEN_H + SPAWN_MARGIN
    elif side == 2: # left
        return -SPAWN_MARGIN, random.randint(0, SCREEN_H)
    else:           # right
        return SCREEN_W + SPAWN_MARGIN, random.randint(0, SCREEN_H)

# ── HUD / fonts ───────────────────────────────────────────────────────────────
font_big   = pygame.font.SysFont("Arial", 48, bold=True)
font_med   = pygame.font.SysFont("Arial", 28, bold=True)
font_small = pygame.font.SysFont("Arial", 20)

def draw_text(surf, text, font, color, cx, cy, shadow=True):
    if shadow:
        s = font.render(text, True, (0, 0, 0))
        surf.blit(s, s.get_rect(center=(cx+2, cy+2)))
    t = font.render(text, True, color)
    surf.blit(t, t.get_rect(center=(cx, cy)))

# ── Game states ───────────────────────────────────────────────────────────────
STATE_MENU   = "menu"
STATE_PLAY   = "play"
STATE_DEAD   = "dead"

def run_game():
    state = STATE_MENU
    player = None
    orcs = []
    arrows = []
    score = 0
    start_time = 0.0
    elapsed = 0.0
    wave = 1
    spawn_timer = 0.0
    spawn_interval = 3.0  # seconds between spawns initially
    orc_kill_count = 0

    def reset():
        nonlocal player, orcs, arrows, score, start_time, elapsed, wave
        nonlocal spawn_timer, spawn_interval, orc_kill_count
        player = Player(SCREEN_W // 2 - 80, SCREEN_H // 2 - 80)
        orcs = []
        arrows = []
        score = 0
        start_time = time.time()
        elapsed = 0.0
        wave = 1
        spawn_timer = 0.0
        spawn_interval = 3.0
        orc_kill_count = 0

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        # ── Events ──
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if state == STATE_MENU:
                    if event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                        reset()
                        state = STATE_PLAY
                elif state == STATE_DEAD:
                    if event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                        state = STATE_MENU
                elif state == STATE_PLAY:
                    if event.key == pygame.K_SPACE:
                        player.shoot(arrows)
                    if event.key == pygame.K_ESCAPE:
                        state = STATE_MENU

        # ── Update ──
        if state == STATE_PLAY:
            keys = pygame.key.get_pressed()
            elapsed = time.time() - start_time

            # Wave escalation every 30 seconds
            new_wave = int(elapsed // 30) + 1
            if new_wave != wave:
                wave = new_wave
                spawn_interval = max(0.5, 3.0 - (wave - 1) * 0.4)

            # Spawn orcs
            spawn_timer -= dt
            if spawn_timer <= 0:
                sx, sy = random_spawn_pos()
                orcs.append(Orc(sx, sy))
                spawn_timer = spawn_interval * random.uniform(0.7, 1.3)

            player.update(dt, keys)

            for orc in orcs:
                orc.update(dt, player)

            # Arrows vs orcs
            for arrow in arrows:
                arrow.update()
                if not arrow.alive:
                    continue
                ar = arrow.get_rect()
                for orc in orcs:
                    if orc.alive and ar.colliderect(orc.get_rect()):
                        orc.alive = False
                        arrow.alive = False
                        orc_kill_count += 1
                        score += 10
                        break

            # Remove dead
            arrows = [a for a in arrows if a.alive]
            orcs   = [o for o in orcs   if o.alive]

            if not player.alive:
                state = STATE_DEAD

        # ── Draw ──
        screen.blit(bg, (0, 0))

        if state == STATE_MENU:
            # Semi-transparent overlay
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            screen.blit(overlay, (0, 0))
            draw_text(screen, "KNIGHT FIGHTER", font_big, (255, 215, 0), SCREEN_W//2, SCREEN_H//2 - 100)
            draw_text(screen, "Survive the orc onslaught!", font_med, (255, 255, 255), SCREEN_W//2, SCREEN_H//2 - 30)
            draw_text(screen, "WASD — move    SPACE — shoot arrow", font_small, (200, 200, 200), SCREEN_W//2, SCREEN_H//2 + 30)
            draw_text(screen, "Orcs get faster every 30 seconds", font_small, (200, 160, 100), SCREEN_W//2, SCREEN_H//2 + 65)
            draw_text(screen, "Press SPACE or ENTER to start", font_med, (100, 255, 100), SCREEN_W//2, SCREEN_H//2 + 130)

        elif state in (STATE_PLAY, STATE_DEAD):
            # Draw game objects
            for orc in orcs:
                orc.draw(screen)
            for arrow in arrows:
                arrow.draw(screen)
            if player:
                player.draw(screen)

            # HUD
            mins = int(elapsed) // 60
            secs = int(elapsed) % 60
            time_str = f"{mins:02d}:{secs:02d}"
            draw_text(screen, f"Time: {time_str}", font_med, (255, 255, 255), 120, 25)
            draw_text(screen, f"Score: {score}", font_med, (255, 215, 0), SCREEN_W//2, 25)
            draw_text(screen, f"Wave {wave}", font_med, (255, 100, 100), SCREEN_W - 100, 25)
            draw_text(screen, f"Kills: {orc_kill_count}", font_small, (200, 255, 200), SCREEN_W - 100, 55)

            # Player HP bar (large, bottom center)
            if player:
                hp_bar_w = 200
                hp_bar_h = 14
                hx = SCREEN_W // 2 - hp_bar_w // 2
                hy = SCREEN_H - 30
                pygame.draw.rect(screen, (80, 0, 0), (hx, hy, hp_bar_w, hp_bar_h), border_radius=4)
                fill_w = int(hp_bar_w * player.hp / player.MAX_HP)
                color = (0, 200, 50) if player.hp > 50 else (200, 200, 0) if player.hp > 25 else (220, 50, 0)
                if fill_w > 0:
                    pygame.draw.rect(screen, color, (hx, hy, fill_w, hp_bar_h), border_radius=4)
                pygame.draw.rect(screen, (200, 200, 200), (hx, hy, hp_bar_w, hp_bar_h), 1, border_radius=4)
                draw_text(screen, f"HP: {player.hp}", font_small, (255,255,255), SCREEN_W//2, hy - 12)

            if state == STATE_DEAD:
                overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 180))
                screen.blit(overlay, (0, 0))
                draw_text(screen, "YOU DIED", font_big, (220, 30, 30), SCREEN_W//2, SCREEN_H//2 - 90)
                draw_text(screen, f"Score: {score}   Kills: {orc_kill_count}   Time: {time_str}", font_med, (255, 215, 0), SCREEN_W//2, SCREEN_H//2 - 10)
                draw_text(screen, f"Survived to Wave {wave}", font_med, (255, 160, 60), SCREEN_W//2, SCREEN_H//2 + 45)
                draw_text(screen, "Press SPACE or ENTER to return to menu", font_med, (180, 255, 180), SCREEN_W//2, SCREEN_H//2 + 110)

        pygame.display.flip()

run_game()