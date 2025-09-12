import pygame, asyncio, math, random, time, os

W, H = 1200, 680
FPS = 60
TIME_LIMIT = 60
FISH_LIFE = 3.0
FISH_UPPERBOUND = 40
FISH_LOWERBOUND = 80
TARGET = 9
ROT_SPEED = 3.0
THRUST = 0.12
FRICTION = 0.99
BRAKE = 0.75
ROW_WAKE_DELAY_MS = 120
BRT_WHITE = (255,255,255)
OFF_WHITE = (245,245,245)
MAORI_RED = (212,0,0)
DARK_GRAY = (30,30,30)
EGG_SHELL = (255,235,120)

pygame.init()



class ImagesKit:
    def __init__(self, base="images",
                 border_path="borders/maori_koru_border.png",
                 fish_frame_count=27, waka_frame_count=7, star_count=9, net_frame_count=3,
                 wake_big="waka/waka_wake_big.png",
                 wake_small="waka/waka_wake_small.png",
                 rowing_wake="waka/rowing_wake.png"
                 ):
        self.base = base
        self._scale_cache = {}  # (id(surface), round(scale,3)) -> scaled surface

        def _load(rel, alpha=True):
            surf = pygame.image.load(os.path.join(self.base, rel))
            return surf.convert_alpha() if alpha else surf.convert()

        # load once
        self.border       = _load(border_path, True)
        self.fish_frames  = [_load(f"fishy/fish__{i}.png", True) for i in range(1, fish_frame_count+1)]
        self.waka_frames  = [_load(f"waka/waka__{i}.png", True)  for i in range(1, waka_frame_count+1)]
        self.net_frames   = [_load(f"waka/wakanet__{i}.png", True) for i in range(1, net_frame_count+1)]
        self.stars        = [_load(f"stars/matariki_star_{i}.png", True) for i in range(1, star_count+1)]
        self.wake_big     = _load(wake_big, True)
        self.wake_small   = _load(wake_small, True)
        self.rowing_wake  = _load(rowing_wake, True)

    def star_for_score(self, score):
        idx = max(0, min(score-1, len(self.stars)-1))
        return self.stars[idx]

    def scaled(self, surf, scale):
        k = (id(surf), round(scale,3))
        if k in self._scale_cache:
            return self._scale_cache[k]
        w, h = surf.get_width(), surf.get_height()
        out = pygame.transform.smoothscale(surf, (int(w*scale), int(h*scale)))
        self._scale_cache[k] = out
        return out

    def scale_list(self, frames, scale):
        return [self.scaled(f, scale) for f in frames]


class Waka:
    def __init__(self, x, y, fps=8, splash_snds=None, frames=None, net_frames=None):
        assert frames and net_frames, "Pass frames from ImagesKit"
        self.x, self.y = x, y
        self.ang = -90
        self.vx, self.vy = 0.0, 0.0
        self.frames = frames
        self.net_frames = net_frames
        self.frame_idx = 0
        self.frame_ms = int(1000 / fps)
        self.last_frame_tick = pygame.time.get_ticks()
        self.rowing = False
        self.net_frames = net_frames
        self.last_boost_t = 0
        self.boost_ms = 140
        self.BOOST = THRUST * 10  # tweak to taste
        self.stroke_state = "ready"   # ready|charging|cooldown
        self.stroke_t0 = 0
        self.stroking = False
        self.stroke_start = 0
        self.STROKE_MS = 300  # length of one stroke
        self.STROKE_THRUST = THRUST * 2.8  # tweak
        self.stroke_frame_ms = max(1, int(self.STROKE_MS / len(self.frames)))
        self.splash_snds = splash_snds
        self.splash_cd = 260  # ms between splashes
        self.last_splash = 0
        self.splash_ch = pygame.mixer.Channel(1)  # dedicated channel
        self.net_idx = 0            # 0..2
        self.net_state = "idle"     # idle, extending, held, retracting
        self.last_net_tick = pygame.time.get_ticks()
        self.net_frame_ms = 90


    def net_active(self):
        return self.net_idx > 0 or self.net_state in ("extending", "held")

    def handle_input(self, keys):
        if keys[pygame.K_LEFT]:
            self.ang -= ROT_SPEED
        if keys[pygame.K_RIGHT]:
            self.ang += ROT_SPEED
        else:
            self.rowing = False
        if keys[pygame.K_DOWN]:
            self.vx *= BRAKE
            self.vy *= BRAKE

    def finish_stroke(self):
        now = pygame.time.get_ticks()
        dur = min(now - self.stroke_t0, self.max_charge)
        if dur >= self.min_charge:
            # scale 0..1 across [min,max]
            k = (dur - self.min_charge) / (self.max_charge - self.min_charge) if self.max_charge>self.min_charge else 1.0
            impulse = self.base_impulse + k * self.bonus_impulse
            rad = math.radians(self.ang)
            self.vx += math.cos(rad) * impulse
            self.vy += math.sin(rad) * impulse
            self.rowing = True
            self.last_frame_tick = now
        else:
            self.rowing = False  # too short, no boost
        self.stroke_state = "cooldown"
        self.stroke_t0 = now

    def update(self):
        now = pygame.time.get_ticks()

        # nets animate first
        self._update_nets()

        # movement, cannot row if nets are out
        if self.stroking and not self.net_active() and now - self.stroke_start <= self.STROKE_MS:
            r = math.radians(self.ang)
            self.vx += math.cos(r) * self.STROKE_THRUST
            self.vy += math.sin(r) * self.STROKE_THRUST
            self.rowing = True
            if now - self.last_frame_tick >= self.stroke_frame_ms:
                self.frame_idx = (self.frame_idx + 1) % len(self.frames)
                self.last_frame_tick = now
        else:
            self.rowing = False
            self.frame_idx = 0

        # physics + wrap
        self.x += self.vx; self.y += self.vy
        self.vx *= FRICTION; self.vy *= FRICTION
        if self.x < 0: self.x += W
        if self.x > W: self.x -= W
        if self.y < 0: self.y += H
        if self.y > H: self.y -= H


    def _play_splash(self):
        if not self.splash_snds:
            return
        now = pygame.time.get_ticks()
        if now - self.last_splash < self.splash_cd:
            return
        self.last_splash = now
        snd = random.choice(self.splash_snds)
        snd.play()


    # --- nets animation stepper, add inside Waka ---
    def _update_nets(self):
        now = pygame.time.get_ticks()
        if now - self.last_net_tick < self.net_frame_ms:
            return
        self.last_net_tick = now

        if self.net_state == "extending":
            if self.net_idx < 2:
                self.net_idx += 1
            else:
                self.net_state = "held"
        elif self.net_state == "retracting":
            if self.net_idx > 0:
                self.net_idx -= 1
            else:
                self.net_state = "idle"

    def draw(self, screen):
        img = self.frames[self.frame_idx]
        rotated = pygame.transform.rotate(img, -self.ang-90)
        rect = rotated.get_rect(center=(self.x, self.y))
        screen.blit(rotated, rect.topleft)

        if self.net_active():
            net_img = self.net_frames[self.net_idx]
            net_rot = pygame.transform.rotate(net_img, -self.ang-90)
            net_rect = net_rot.get_rect(center=(self.x, self.y))
            screen.blit(net_rot, net_rect.topleft)

    def try_catch(self, fish):
        if not fish or not self.net_active():
            return False

        net_img = self.net_frames[self.net_idx]
        net_rot = pygame.transform.rotate(net_img, -self.ang-90)
        net_rect = net_rot.get_rect(center=(int(self.x), int(self.y)))

        fish_img = fish.frames[fish.frame_idx]
        fish_rect = fish_img.get_rect(center=(int(fish.x), int(fish.y)))

        net_mask = pygame.mask.from_surface(net_rot)
        fish_mask = pygame.mask.from_surface(fish_img)
        offset = (fish_rect.left - net_rect.left, fish_rect.top - net_rect.top)
        return net_mask.overlap(fish_mask, offset) is not None
    


class Fish:
    def __init__(self, x, y,
                 base_frames,
                 splash_snds=None,
                 life=FISH_LIFE,
                 fps=10, scale=1.0,
                 splash_delay_ms=None, splash_frame=12):
        self.x, self.y = float(x), float(y)
        self.expires_at = time.time() + life
        self.frames = base_frames if scale==1.0 else [
            pygame.transform.smoothscale(f, (int(f.get_width()*scale), int(f.get_height()*scale)))
            for f in base_frames
        ]
        self.frame_idx = 0
        self.frame_ms = int(1000 / fps)
        self.last_frame_tick = pygame.time.get_ticks()
        self.splash_snds = splash_snds or []
        self.spawn_tick = pygame.time.get_ticks()
        self.splash_delay_ms = splash_delay_ms
        self.splash_frame = splash_frame
        self.splash_played = False

    @property
    def alive(self):
        return time.time() < self.expires_at

    def update(self):
        now = pygame.time.get_ticks()
        if now - self.last_frame_tick >= self.frame_ms:
            self.frame_idx = (self.frame_idx + 1) % len(self.frames)
            self.last_frame_tick = now
        self._maybe_play_splash(now)

    def _maybe_play_splash(self, now):
        if self.splash_played or not self.alive or not self.splash_snds:
            return
        if self.splash_delay_ms is not None:
            if now - self.spawn_tick >= self.splash_delay_ms:
                random.choice(self.splash_snds).play()
                self.splash_played = True
        else:
            if self.frame_idx >= self.splash_frame:
                random.choice(self.splash_snds).play()
                self.splash_played = True

    def draw(self, screen):
        img = self.frames[self.frame_idx]
        rect = img.get_rect(center=(int(self.x), int(self.y)))
        screen.blit(img, rect.topleft)


class CatchEffect:
    _cache = {}  # {(id(surface), steps, w,h): [scaled_surfaces...]}

    def __init__(self, x, y, star_img, flash_ms=120, star_ms=600, steps=12):
        self.x, self.y = int(x), int(y)
        self.flash_ms, self.star_ms = flash_ms, star_ms
        self.t, self.done = 0, False
        self.frames = self._get_frames(star_img, steps)

    @classmethod
    def _get_frames(cls, star, steps):
        w, h = star.get_width(), star.get_height()
        key = (id(star), steps, w, h)
        if key in cls._cache:
            return cls._cache[key]
        out = []
        for i in range(steps):
            p = (i+1)/steps
            s = 0.6 + 0.4*math.sin(p*math.pi)
            out.append(pygame.transform.smoothscale(star, (int(w*s), int(h*s))))
        cls._cache[key] = out
        return out

    def update(self, dt):
        self.t += dt
        if self.t > self.flash_ms + self.star_ms:
            self.done = True

    def draw(self, screen):
        if self.t <= self.flash_ms:
            p = self.t / self.flash_ms
            size = int(20 + 80*p)
            rect = pygame.Rect(0,0,size,size); rect.center = (self.x,self.y)
            pygame.draw.rect(screen, (255,255,255), rect, width=3)
            return

        p = min(1.0, (self.t - self.flash_ms)/self.star_ms)
        idx = min(int(p*(len(self.frames)-1)), len(self.frames)-1)
        img = self.frames[idx]

        # soft fade out
        alpha = int(255*(1.0 - p))
        prev_alpha = img.get_alpha()
        img.set_alpha(alpha)
        screen.blit(img, img.get_rect(center=(self.x,self.y)))
        img.set_alpha(prev_alpha)


class WakeTrail:
    def __init__(self, img, spawn_ms=60, life_ms=500, max_parts=80, back_offset=100):
        self.img = img
        self.spawn_ms = spawn_ms
        self.life_ms = life_ms
        self.max_parts = max_parts
        self.back_offset = back_offset
        self.parts, self.last_spawn = [], 0

    def spawn(self, x, y, ang):
        now = pygame.time.get_ticks()
        if now - self.last_spawn < self.spawn_ms: return
        self.last_spawn = now
        # drop a bit behind the waka nose
        r = math.radians(ang)
        px = x - math.cos(r)*self.back_offset
        py = y - math.sin(r)*self.back_offset
        self.parts.append({"x": px, "y": py, "ang": ang, "t": 0})
        if len(self.parts) > self.max_parts: self.parts.pop(0)

    def update(self, dt):
        for p in self.parts: p["t"] += dt
        self.parts = [p for p in self.parts if p["t"] < self.life_ms]

    def draw(self, screen):
        for p in self.parts:
            a = 1 - p["t"]/self.life_ms
            s = 0.7 + 0.2*a
            img = pygame.transform.rotozoom(self.img, -p["ang"]-90, s)
            img.set_alpha(int(160*a))
            screen.blit(img, img.get_rect(center=(p["x"], p["y"])))

class UiKit:
    def __init__(self, screen, border_surface,
                 button_fill=MAORI_RED, text_color=BRT_WHITE,
                 outline_idle=DARK_GRAY, corner_radius=14,
                 bg_color=OFF_WHITE, font_name=None, font_sizes=None):
        self.screen = screen
        self.border_src = border_surface.convert_alpha()
        self.button_fill = button_fill
        self.text_color = text_color
        self.outline_idle = outline_idle
        self.radius = corner_radius
        self.bg_color = bg_color
        self.title = "Tākaro Waka"
        self.subtitle = "it's matariki time!"
        self._border_cache = {}

        # fonts
        h = max(1, screen.get_height())
        scale = max(0.6, h / 680.0)
        base = {"title": 96, "subtitle": 56, "button": 48, "hud": 24}
        if font_sizes:
            base.update(font_sizes)
        self.fonts = {
            k: pygame.font.SysFont(font_name, max(12, int(v*scale)))
            for k, v in base.items()
        }

    def font(self, key): return self.fonts[key]

    def render_center(self, key, text, color, center):
        surf = self.fonts[key].render(text, True, color)
        rect = surf.get_rect(center=center)
        self.screen.blit(surf, rect)
        return rect

    def _draw_border(self, scale=0.8):
        if scale not in self._border_cache:
            bw, bh = self.border_src.get_size()
            surf = pygame.transform.smoothscale(
                self.border_src, (int(bw*scale), int(bh*scale))
            )
            self._border_cache[scale] = surf
        img = self._border_cache[scale]
        rect = img.get_rect(center=(self.screen.get_width()//2,
                                    self.screen.get_height()//2))
        return img, rect

    def _make_button(self, text, pad=18):
        surf = self.fonts["button"].render(text, True, self.text_color)
        rect = surf.get_rect()
        box = pygame.Rect(0, 0, rect.w + pad*2, rect.h + pad*2)
        return surf, rect, box

    def _draw_button(self, center, surf, rect, box, hovered):
        box.center = center
        rect.center = center
        pygame.draw.rect(self.screen, self.button_fill, box, border_radius=self.radius)
        pygame.draw.rect(self.screen, BRT_WHITE if hovered else self.outline_idle,
                         box, width=4, border_radius=self.radius)
        self.screen.blit(surf, rect.topleft)

    async def show_menu(self, border_scale=0.9, overlay_alpha=120, fps=60):
        clock = pygame.time.Clock()
        # build buttons
        items = [("Play","play"), ("How to play","how"), ("Quit","quit")]
        btns = [self._make_button(lbl) for (lbl, _) in items]

        while True:
            dt = clock.tick(fps)
            mouse = pygame.mouse.get_pos()
            clicked = False
            choice = None

            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return "quit"
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_RETURN:
                        return items[0][1]  # default to first item
                    if e.key == pygame.K_ESCAPE:
                        return "quit"
                    if e.key == pygame.K_h:
                        # optional hotkey for how to play if present
                        for lbl, val in items:
                            if lbl.lower().startswith("how"):
                                return val
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    clicked = True

            # background + border
            self.screen.fill(self.bg_color)
            bimg, brect = self._draw_border(border_scale)
            self.screen.blit(bimg, brect)

            # overlay
            overlay = pygame.Surface((self.screen.get_width(), self.screen.get_height()), pygame.SRCALPHA)
            overlay.fill((0,0,0,overlay_alpha))
            self.screen.blit(overlay, (0,0))

            # titles
            cx, cy = self.screen.get_width()//2, self.screen.get_height()//2
            self.render_center("title", self.title, EGG_SHELL, (cx, cy-160))
            self.render_center("subtitle", self.subtitle, BRT_WHITE, (cx, cy-100))

            # buttons
            spacing = 80
            start_y = cy + 10
            centers = [(cx, start_y + i*spacing) for i in range(len(btns))]
            for (surf, rect, box), (_, val), ctr in zip(btns, items, centers):
                hit = pygame.Rect(0,0, box.w, box.h); hit.center = ctr
                over = hit.collidepoint(mouse)
                self._draw_button(ctr, surf, rect, box, over)
                if over and clicked:
                    choice = val

            pygame.display.flip()
            await asyncio.sleep(0)

            if choice:
                return choice
    
    def sky_color(self, start_time, cycle_length=60, stops=None):
        """
        Returns an (r,g,b) based on elapsed time across color stops.
        """
        if stops is None:
            stops = [
                (0.00, (135,206,250)),  # morning
                (0.25, (0,191,255)),    # day
                (0.50, (255,204,153)),  # sunset
                (1.00, (0,0,20)),       # night
            ]
        elapsed = time.time() - start_time
        t = max(0.0, min(1.0, elapsed / float(cycle_length)))
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i+1]
            if t0 <= t <= t1:
                f = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
                return (
                    int(c0[0] + (c1[0]-c0[0]) * f),
                    int(c0[1] + (c1[1]-c0[1]) * f),
                    int(c0[2] + (c1[2]-c0[2]) * f),
                )
        return stops[-1][1]

    def fill_sky(self, start_time, cycle_length=60, stops=None):
        self.screen.fill(self.sky_color(start_time, cycle_length, stops))

class SoundKit:
    def __init__(self, base="sounds", volumes=None, num_channels=16):
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.set_num_channels(num_channels)

        self.base = base
        self.coin = self._load("get-coin.mp3")
        self.row_splashes = self._load_seq("row_splash__{}.mp3", 1, 7)
        self.fish_splashes = self._load_seq("fish_splash__{}.mp3", 1, 6)
        self.net_flips = self._load_seq("net_flip__{}.mp3", 1, 4)
        self.count = {i:self._load(n) for i,n in enumerate(
            ["tahi_ika.mp3","rua_ika.mp3","toru_ika.mp3","wha_ika.mp3",
             "rima_ika.mp3","ono_ika.mp3","whitu_ika.mp3","waru_ika.mp3",
             "iwa_ika.mp3"], start=1)}

        self.vols = {"coin":0.2,"row":0.1,"fish":0.5,"net":0.8,"count":0.9}
        if volumes: self.vols.update(volumes)

        if self.coin: self.coin.set_volume(self.vols["coin"])
        for s in self.row_splashes: s.set_volume(self.vols["row"])
        for s in self.fish_splashes: s.set_volume(self.vols["fish"])
        for s in self.net_flips: s.set_volume(self.vols["net"])
        for s in self.count.values():
            if s: s.set_volume(self.vols["count"])

    # set all count vols later
    def set_count_volume(self, vol):
        self.vols["count"] = vol
        for s in self.count.values():
            if s: s.set_volume(vol)

    # one-off play with custom vol (uses a channel)
    def say_count(self, n, vol=None):
        s = self.count.get(n)
        if not s: return
        if vol is None:
            s.play()
        else:
            ch = pygame.mixer.find_channel()
            if ch: ch.set_volume(vol); ch.play(s)
            else:  s.set_volume(vol); s.play()


    def _load(self, rel):
        try:
            return pygame.mixer.Sound(os.path.join(self.base, rel))
        except Exception as e:
            print("Failed to load sound:", rel, e)
            return None

    def _load_seq(self, pattern, start, end_inclusive):
        out = []
        for i in range(start, end_inclusive+1):
            s = self._load(pattern.format(i))
            if s: out.append(s)
        return out

    # helpers
    def play_coin(self):
        if self.coin: self.coin.play()

    def random_row(self):
        return random.choice(self.row_splashes) if self.row_splashes else None

    def random_fish(self):
        return random.choice(self.fish_splashes) if self.fish_splashes else None

    def random_net(self):
        return random.choice(self.net_flips) if self.net_flips else None

    def say_count(self, n):
        s = self.count.get(n)
        if s: s.play()




async def main():
    pygame.mixer.init()
    screen = pygame.display.set_mode((W, H))
    snd = SoundKit()
    ik = ImagesKit()
    ui = UiKit(screen, ik.border)

    # Main menu
    choice = await ui.show_menu()
    if choice == "quit":
        pygame.quit()
        return

    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 24)

    waka = Waka(
        W/2, H/2,
        splash_snds=snd.row_splashes,
        frames=ik.waka_frames,
        net_frames=ik.net_frames
    )
    # wake_big   = WakeTrail(ik.wake_big)
    # wake_small = WakeTrail(ik.wake_small)
    # row_wake   = WakeTrail(ik.rowing_wake)
    wake_big   = WakeTrail(ik.wake_big,   spawn_ms=60, life_ms=500, max_parts=80, back_offset=120)
    wake_small = WakeTrail(ik.wake_small, spawn_ms=60, life_ms=500, max_parts=80, back_offset=100)
    row_wake   = WakeTrail(ik.rowing_wake,spawn_ms=60,  life_ms=750, max_parts=30, back_offset=1) 
    fish = None
    score = 0
    start = time.time()
    catch_effect = None
    row_wake_due = None

    running = True
    while running:
        dt = clock.tick(FPS)
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_UP:
                if not waka.stroking and not waka.net_active():
                    waka.stroking = True
                    waka._play_splash()
                    waka.stroke_start = pygame.time.get_ticks()
                    row_wake_due = pygame.time.get_ticks() + ROW_WAKE_DELAY_MS
            elif e.type == pygame.KEYUP and e.key == pygame.K_UP:
                waka.stroking = False

            # nets control
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                s = snd.random_net()
                if s: s.play()
                if waka.net_state in ("idle", "retracting"):
                    waka.net_state = "extending"
            elif e.type == pygame.KEYUP and e.key == pygame.K_SPACE:
                s = snd.random_net()
                if s: s.play()
                if waka.net_state in ("extending", "held"):
                    waka.net_state = "retracting"

        keys = pygame.key.get_pressed()
        waka.handle_input(keys)
        waka.update()

        # schedule the single rowing wake once per initial press
        if row_wake_due and pygame.time.get_ticks() >= row_wake_due:  # NEW
            row_wake.spawn(waka.x, waka.y, waka.ang)
            row_wake_due = None

        # spawn wake continuously while rowing
        wake_small.spawn(waka.x, waka.y, waka.ang) 
        if waka.rowing and not waka.net_active():
            wake_big.spawn(waka.x, waka.y, waka.ang)

        wake_small.update(dt)
        wake_big.update(dt)
        row_wake.update(dt)

        now = time.time()
        if fish is None and random.random() < 0.02:
            fish = Fish(
                random.randint(FISH_UPPERBOUND,W-FISH_UPPERBOUND),
                random.randint(FISH_LOWERBOUND,H-FISH_UPPERBOUND),
                base_frames=ik.fish_frames,
                splash_snds=snd.fish_splashes,
            )
        elif fish and not fish.alive:
            fish = None

        if fish:
            fish.update()

        if fish and waka.try_catch(fish):
            score += 1
            snd.play_coin()
            snd.say_count(score)
            star_img = ik.star_for_score(score)
            catch_effect = CatchEffect(fish.x, fish.y, star_img)    
            fish = None
            
        ui.fill_sky(start)

        if catch_effect:
            catch_effect.update(dt)
            catch_effect.draw(screen)
            if catch_effect.done:
                catch_effect = None

        if fish:
            fish.draw(screen)

        wake_small.draw(screen)
        wake_big.draw(screen)
        waka.draw(screen)
        row_wake.draw(screen) 

        remaining = max(0, int(TIME_LIMIT - (now-start)))
        txt = f"Fish {score}/{TARGET}   Time {remaining}s"
        screen.blit(font.render(txt, True, BRT_WHITE), (10,10))

        if score >= TARGET or remaining <= 0:
            msg = "Ka pai! Feast ready." if score>=TARGET else "Kua pau te wā."
            screen.blit(font.render(msg, True, BRT_WHITE), (W//2-100, H//2))
            pygame.display.flip()
            await asyncio.sleep(1.5)
            running = False

        pygame.display.flip()
        clock.tick(FPS)
        await asyncio.sleep(0)

    pygame.quit()

if __name__ == "__main__":
    asyncio.run(main())
