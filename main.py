import pygame, asyncio, math, random, time, os, sys

W, H = 1200, 680
FPS = 60
TIME_LIMIT = 300
FISH_LIFE = 4.0
FISH_UPPERBOUND = 40   
FISH_LOWERBOUND = 160   # Lower bound of fish spawning loc
TARGET = 9
ROT_SPEED = 3.0
FRICTION = 0.99
BRAKE = 0.95
ROW_WAKE_DELAY_MS = 120
PRE_END_DELAY_MS = 600   # wait before showing end screen
END_DELAY_MS = 800       # wait on end screen before buttons
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
                 rowing_wake="waka/rowing_wake.png"):
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

    def scaled(self, surf, scale, scale_precision=3):
        k = (id(surf), round(scale,scale_precision))
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
        self.stroke_state = "ready"   # ready|charging|cooldown
        self.stroke_t0 = 0
        self.stroking = False
        self.stroke_start = 0
        self.stroke_ms = 300  # length of one stroke
        self.stroke_thrust = 0.336
        self.stroke_frame_ms = max(1, int(self.stroke_ms / len(self.frames)))
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
            self.rowing = False
        self.stroke_state = "cooldown"
        self.stroke_t0 = now

    def update(self):
        now = pygame.time.get_ticks()

        # nets animate first
        self._update_nets()

        # movement, cannot row if nets are out
        if self.stroking and not self.net_active() and now - self.stroke_start <= self.stroke_ms:
            r = math.radians(self.ang)
            self.vx += math.cos(r) * self.stroke_thrust
            self.vy += math.sin(r) * self.stroke_thrust
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
    def __init__(self, x, y, base_frames, splash_snds=None,
                 life=FISH_LIFE, scale=1.0):
        self.x, self.y = float(x), float(y)
        self.life = float(life)
        self.birth = time.time()
        self.expires_at = self.birth + self.life
        self.x, self.y = float(x), float(y)
        self.life = float(life)
        self.birth = time.time()
        self.expires_at = self.birth + self.life
        self.frames = base_frames if scale==1.0 else [
            pygame.transform.smoothscale(f, (int(f.get_width()*scale), int(f.get_height()*scale)))
            for f in base_frames
        ]
        self.n_frames = len(self.frames)
        self.frame_idx = 0
        self.splash_snds = splash_snds or []
        self.spawn_tick = pygame.time.get_ticks()
        self.splash_played = False
        self.splash_delay_ms = self.splash_delay_ms = int(500 * self.life + 500)

    @property
    def alive(self):
        return time.time() < self.expires_at

    def update(self):
        now_s = time.time()
        p = max(0.0, min(1.0, (now_s - self.birth) / self.life))
        self.frame_idx = min(int(p * self.n_frames), self.n_frames - 1)
        self._maybe_play_splash(pygame.time.get_ticks())

    def _maybe_play_splash(self, now_ms):
        if self.splash_played or not self.alive or not self.splash_snds:
            return
        if now_ms - self.spawn_tick >= self.splash_delay_ms:
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
            pygame.draw.rect(screen, BRT_WHITE, rect, width=3)
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
    def __init__(self, img, spawn_ms=60, life_ms=500, max_parts=80, back_offset=100,
                 start_scale=0.75, end_scale=1.15):
        self.img = img
        self.spawn_ms = spawn_ms
        self.life_ms = life_ms
        self.max_parts = max_parts
        self.back_offset = back_offset
        self.start_scale = start_scale
        self.end_scale = end_scale
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
            # wakes grow over time
            prog = max(0.0, min(1.0, p["t"] / self.life_ms))
            s = self.start_scale + (self.end_scale - self.start_scale) * prog
            alpha = int(160 * (1.0 - prog))
            # Fade out
            img = pygame.transform.rotozoom(self.img, -p["ang"]-90, s)
            img.set_alpha(alpha)
            screen.blit(img, img.get_rect(center=(p["x"], p["y"])))

class UiKit:
    def __init__(self, screen, border_surface,
                 button_fill=MAORI_RED, text_color=BRT_WHITE,
                 outline_idle=DARK_GRAY, corner_radius=14,
                 bg_color=OFF_WHITE, font_name="fonts/DejaVuSans.ttf", font_sizes=None,
                 ui_scale=0.70):
        self.screen = screen
        self.border_src = border_surface.convert_alpha()
        self.button_fill = button_fill
        self.text_color = text_color
        self.outline_idle = outline_idle
        self.radius = corner_radius
        self.bg_color = bg_color
        self.title = "Tākaro Waka"
        self.subtitle = "Nau mai ki Matariki! It's Matariki time!"
        self._border_cache = {}

        h = max(1, screen.get_height())
        auto = max(0.6, h / 680.0)
        scale = ui_scale if ui_scale is not None else auto

        base = {"title": 96, "subtitle": 56, "button": 48, "hud": 24}
        if font_sizes:
            base.update(font_sizes)

        def make(size):
            size = max(12, int(size * scale))
            return (pygame.font.Font(font_name, size)
                    if font_name else pygame.font.SysFont(None, size))

        self.fonts = {k: make(v) for k, v in base.items()}

    def font(self, key):
        return self.fonts[key]

    def render_center(self, key, text, color, center):
        surf = self.fonts[key].render(text, True, color)
        rect = surf.get_rect(center=center)
        self.screen.blit(surf, rect)
        return rect

    def _draw_border(self, scale=0.95):
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

    def sky_color(self, start_time, cycle_length=60, stops=None,
                  morning_clr=(135,206,250), daytime_clr=(0,191,255),
                  evening_clr=(255,204,153), nighttm_clr=(0,0,20)):
        if stops is None:
            stops = [
                (0.00, morning_clr),
                (0.25, daytime_clr),
                (0.50, evening_clr),
                (1.00, nighttm_clr),
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

    def _blit_matariki_stars(self, star_imgs, y, max_h=56, gap=12, alpha=220):
        scaled = []
        for im in star_imgs:
            h = im.get_height()
            s = max_h / float(h)
            out = pygame.transform.smoothscale(
                im, (int(im.get_width()*s), int(h*s))
            ).convert_alpha()
            out.set_alpha(alpha)
            scaled.append(out)
        total_w = sum(i.get_width() for i in scaled) + gap*(len(scaled)-1)
        x = (self.screen.get_width() - total_w)//2
        for im in scaled:
            self.screen.blit(im, (x, y - im.get_height()//2))
            x += im.get_width() + gap

    def draw_end(self, msg, stars=None, border_scale=0.99, overlay_alpha=140,
                 stars_h=56, stars_gap=12):
        self.screen.fill(self.bg_color)
        bimg, brect = self._draw_border(border_scale)
        self.screen.blit(bimg, brect)
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0,0,0,overlay_alpha))
        self.screen.blit(overlay, (0,0))
        cx, cy = self.screen.get_width()//2, self.screen.get_height()//2
        self.render_center("title", self.title, EGG_SHELL, (cx, cy-100))
        self.render_center("subtitle", msg, BRT_WHITE, (cx, cy-40))
        if stars:
            self._blit_matariki_stars(stars, y=cy+40, max_h=stars_h, gap=stars_gap)

    async def show_dialog(self, items, title=None, subtitle="", border_scale=0.99,
                          overlay_alpha=120, fps=60, stars=None, stars_h=100,
                          stars_gap=12, button_start_y=40, button_spacing=80,
                          first_button_offset=0, title_y=-200, subtitle_y=-160):
        clock = pygame.time.Clock()
        btns = [self._make_button(lbl) for (lbl, _) in items]

        while True:
            clock.tick(fps)
            mouse = pygame.mouse.get_pos()
            clicked = False
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    hard_quit()
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_RETURN:
                        return items[0][1]
                    if e.key == pygame.K_ESCAPE:
                        return items[-1][1]
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    clicked = True

            self.screen.fill(self.bg_color)
            bimg, brect = self._draw_border(border_scale)
            self.screen.blit(bimg, brect)
            overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            overlay.fill((0,0,0,overlay_alpha))
            self.screen.blit(overlay, (0,0))

            cx, cy = self.screen.get_width()//2, self.screen.get_height()//2
            self.render_center("title", title or self.title, EGG_SHELL, (cx, cy + title_y))
            self.render_center("subtitle", subtitle, BRT_WHITE, (cx, cy + subtitle_y))

            # auto tweak for the final end menu with all nine stars
            nine_stars = bool(stars) and len(stars) >= 9
            local_stars_h = max(stars_h, 84) if nine_stars else stars_h
            local_button_start_y = max(button_start_y, 120) if nine_stars else button_start_y

            if stars:
                self._blit_matariki_stars(stars, y=cy-20, max_h=local_stars_h, gap=stars_gap)

            base_y = cy + local_button_start_y + first_button_offset

            for i, ((surf, rect, box), (_, val)) in enumerate(zip(btns, items)):
                y = base_y + i * button_spacing
                ctr = (cx, y)
                hit = pygame.Rect(0,0, box.w, box.h); hit.center = ctr
                over = hit.collidepoint(mouse)
                self._draw_button(ctr, surf, rect, box, over)
                if over and clicked:
                    return val

            pygame.display.flip()
            await asyncio.sleep(0)

    async def show_menu(self):
        return await self.show_dialog(
            [("Play","play"), ("How to play","how"), ("Quit","quit")],
            title=self.title, subtitle=self.subtitle, title_y=-210, subtitle_y=-150
        )
    
    async def show_end_result(self, collected_stars, total=9,
                            subtitle_win="Ka pai e hoa, 9 whetū complete!",
                            subtitle_lose="Aroha mai. Try again!",
                            star_h = 140, btn_y = 140):
        n = len(collected_stars) if collected_stars else 0
        win = (n >= total)
        msg = subtitle_win if win else f"{subtitle_lose} {n}/9 whetū. You caught {n}/{total}."

        return await self.show_dialog(
            [("Replay","replay"), ("Quit","quit")],
            title=self.title,
            subtitle=msg,
            stars=collected_stars,   # only the ones they actually got
            stars_h=star_h,
            button_start_y=btn_y,
            button_spacing=90,
            title_y=-210, subtitle_y=-150
        )
    
    def _blit_lines_left(self, key, lines, x, y, color):
        f = self.fonts[key]; lh = f.get_height() + 8
        for ln in lines:
            self.screen.blit(f.render(ln, True, color), (x, y))
            y += lh

    async def show_info_slide(self, title, lines, img_path,
                            line_font_key="button",
                            border_scale=0.99, overlay_alpha=110, fps=60,
                            left_ratio=0.52, lines_y_offset=80,
                            button_label="next", button_bottom_margin=140):
        clock = pygame.time.Clock()
        img = pygame.image.load(img_path).convert_alpha()
        btn_surf, btn_rect, btn_box = self._make_button(button_label)

        while True:
            clock.tick(fps)
            mouse = pygame.mouse.get_pos(); clicked = False
            for e in pygame.event.get():
                if e.type == pygame.QUIT: hard_quit() 
                if e.type == pygame.KEYDOWN:
                    if e.key in (pygame.K_RETURN, pygame.K_SPACE): return "next"
                    if e.key == pygame.K_ESCAPE: return "back"
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    clicked = True

            self.screen.fill(self.bg_color)
            bimg, brect = self._draw_border(border_scale)
            self.screen.blit(bimg, brect)
            overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            overlay.fill((0,0,0,overlay_alpha)); self.screen.blit(overlay, (0,0))

            pad = 28
            content = brect.inflate(-pad*2, -pad*2)
            left_w = int(content.w * left_ratio)
            text_x = content.left + 8
            text_y = content.top + 8

            title_surf = self.fonts["subtitle"].render(title, True, EGG_SHELL)
            self.screen.blit(title_surf, (text_x, text_y))
            self._blit_lines_left(line_font_key, lines,
                                text_x, text_y + title_surf.get_height() + lines_y_offset, BRT_WHITE)

            img_area = pygame.Rect(content.left + left_w + 16, content.top,
                                content.w - left_w - 16, content.h - 80)
            scale = min(img_area.w / img.get_width(), img_area.h / img.get_height(), 1.0)
            pic = pygame.transform.smoothscale(img, (int(img.get_width()*scale), int(img.get_height()*scale)))
            self.screen.blit(pic, pic.get_rect(center=img_area.center))

            cx = self.screen.get_width() // 2
            by = brect.bottom - button_bottom_margin
            hit = pygame.Rect(0,0, btn_box.w, btn_box.h); hit.center = (cx, by)
            over = hit.collidepoint(mouse)
            self._draw_button((cx, by), btn_surf, btn_rect, btn_box, over)
            if over and clicked: return "next"

            pygame.display.flip()
            await asyncio.sleep(0)

    async def show_howto(self):
        # Slide 1 — Goal
        lines1 = [
            "• Catch 9 ika",
            "• Tāne tosses them ki te rangi",
            "• They become the Matariki whetū",
            "• Beat the sunset",
        ]
        res = await self.show_info_slide("Goal  Whāinga", lines1,
                                        "images/howto/scene_1.png",
                                        line_font_key="button",
                                        button_bottom_margin=140,
                                        lines_y_offset=80)
        if res in ("quit", "back"): return res

        # Slide 2 — Controls
        lines2 = [
            "• Row press ↑   Pēhi ↑ ki te hoe",
            "• Turn press ← →   Huri i te waka",
            "• Nets press Space to open the kupenga",
            "• You can't row while nets are out",
        ]
        return await self.show_info_slide("Controls  Ngā Mana Whakahaere", lines2,
                                        "images/howto/scene_2.png",
                                        line_font_key="button",
                                        button_bottom_margin=140,
                                        lines_y_offset=80)
    
    async def show_difficulty(self):
        return await self.show_dialog(
            [("Easy","easy"), ("Medium","medium"), ("Hard","hard"), ("Quit","quit")],
            title=self.title,
            subtitle="Select difficulty",
            button_start_y=-10,   # drop buttons a bit
            button_spacing=90,    # roomy stack
            subtitle_y=-100,
        )

class SoundKit:
    def __init__(self, base="sounds", volumes=None, num_channels=16):
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.set_num_channels(num_channels)
        self.type = "ogg"
        self.base = base
        self.coin = self._load("get-coin."+self.type)
        self.row_splashes = self._load_seq("row_splash__{}."+self.type, 1, 7)
        self.fish_splashes = self._load_seq("fish_splash__{}."+self.type, 1, 6)
        self.net_flips = self._load_seq("net_flip__{}."+self.type, 1, 4)
        self.count = {i:self._load(n) for i,n in enumerate(
            ["tahi_ika."+self.type,"rua_ika."+self.type,"toru_ika."+self.type,"wha_ika."+self.type,
             "rima_ika."+self.type,"ono_ika."+self.type,"whitu_ika."+self.type,"waru_ika."+self.type,
             "iwa_ika."+self.type], start=1)}

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



def set_params(diff):
    global TIME_LIMIT, FISH_LIFE
    if diff == "easy":
        TIME_LIMIT, FISH_LIFE = 120, 5.0
    elif diff == "medium":
        TIME_LIMIT, FISH_LIFE = 60, 4.0
    else:
        TIME_LIMIT, FISH_LIFE = 30, 3.0

def hard_quit():
    pygame.quit()
    if sys.platform != "emscripten":
        sys.exit(0)

async def main():
    pygame.mixer.init()
    screen = pygame.display.set_mode((W, H))
    snd = SoundKit()
    ik = ImagesKit()
    ui = UiKit(screen, ik.border)

    # main menu
    # main menu loop
    while True:
        choice = await ui.show_menu()

        if choice == "quit":
            hard_quit()

        if choice == "how":
            await ui.show_howto()
            continue  # back to menu

        if choice == "play":
            diff = await ui.show_difficulty()
            if diff in ("easy","medium","hard"):
                set_params(diff)
                break      # proceed to game state
            else:
                continue   # back to menu



    # game state
    END_DELAY_MS = 800
    state = "play"  # play | ending
    end_start_ms = None
    end_msg = ""

    clock = pygame.time.Clock()
    font = ui.fonts["hud"]

    waka = Waka(
        W/2, H/2,
        splash_snds=snd.row_splashes,
        frames=ik.waka_frames,
        net_frames=ik.net_frames
    )

    wake_small = WakeTrail(ik.wake_small, start_scale=0.7, end_scale=1.2)
    wake_big   = WakeTrail(ik.wake_big,   start_scale=0.8, end_scale=1.25)
    row_wake   = WakeTrail(ik.rowing_wake, start_scale=0.9, end_scale=1.3, back_offset=0, life_ms=1000)

    fish = None
    score = 0
    start = time.time()
    catch_effect = None
    row_wake_due = None
    cheat_center = False

    freeze_frame = None
    running = True
    while running:
        dt = clock.tick(FPS)

        # events
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                hard_quit()

            # cheat toggle always allowed
            elif e.type == pygame.KEYDOWN and e.key in (pygame.K_9, pygame.K_KP9):
                cheat_center = True
            elif e.type == pygame.KEYUP and e.key in (pygame.K_9, pygame.K_KP9):
                cheat_center = False

            if state != "play":
                continue  # inputs frozen when ending

            if e.type == pygame.KEYDOWN and e.key == pygame.K_UP:
                if not waka.stroking and not waka.net_active():
                    waka.stroking = True
                    waka._play_splash()
                    waka.stroke_start = pygame.time.get_ticks()
                    row_wake_due = pygame.time.get_ticks() + ROW_WAKE_DELAY_MS
            elif e.type == pygame.KEYUP and e.key == pygame.K_UP:
                waka.stroking = False

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

        # ending state: delay, then dialog
        if state == "ending":
            collected_stars = ik.stars[:score]
            choice = await ui.show_end_result(collected_stars, total=9)
            if choice == "replay":
                # reset
                score = 0; fish = None; catch_effect = None; row_wake_due = None
                start = time.time()
                waka = Waka(W/2, H/2, splash_snds=snd.row_splashes,
                            frames=ik.waka_frames, net_frames=ik.net_frames)
                wake_small = WakeTrail(ik.wake_small, start_scale=0.7, end_scale=1.2)
                wake_big   = WakeTrail(ik.wake_big,   start_scale=0.8, end_scale=1.25)
                row_wake   = WakeTrail(ik.rowing_wake, start_scale=0.9, end_scale=1.3, back_offset=0, life_ms=1000)
                state = "play"
                continue
            else:
                running = False
                continue

        # gameplay update
        keys = pygame.key.get_pressed()
        waka.handle_input(keys)
        waka.update()

        # schedule single rowing wake once per initial press
        if row_wake_due and pygame.time.get_ticks() >= row_wake_due:
            row_wake.spawn(waka.x, waka.y, waka.ang)
            row_wake_due = None

        # spawn wakes
        wake_small.spawn(waka.x, waka.y, waka.ang)
        if waka.rowing and not waka.net_active():
            wake_big.spawn(waka.x, waka.y, waka.ang)

        wake_small.update(dt)
        wake_big.update(dt)
        row_wake.update(dt)

        # fish spawn
        now = time.time()
        if fish is None and random.random() < 0.02:
            sx = W//2 if cheat_center else random.randint(FISH_UPPERBOUND, W - FISH_UPPERBOUND)
            sy = H//2 if cheat_center else random.randint(FISH_LOWERBOUND, H - FISH_UPPERBOUND)
            fish = Fish(sx, sy, base_frames=ik.fish_frames, splash_snds=snd.fish_splashes)
        elif fish and not fish.alive:
            fish = None

        if fish:
            if cheat_center:
                fish.x, fish.y = W//2, H//2
            fish.update()

        # catch check
        if fish and waka.try_catch(fish):
            score += 1
            snd.play_coin()
            snd.say_count(score)
            star_img = ik.star_for_score(score)
            catch_effect = CatchEffect(fish.x, fish.y, star_img)
            fish = None

        # draw
        ui.fill_sky(start, cycle_length=TIME_LIMIT)
        if catch_effect:
            catch_effect.update(dt)
            catch_effect.draw(screen)
            if catch_effect.done:
                catch_effect = None

        if fish:
            fish.draw(screen)

        row_wake.draw(screen)
        wake_small.draw(screen)
        wake_big.draw(screen)
        waka.draw(screen)

        remaining = max(0, int(TIME_LIMIT - (now - start)))
        hud = f"Fish {score}/{TARGET}   Time {remaining}s"
        screen.blit(font.render(hud, True, BRT_WHITE), (10, 10))

        # end trigger
        if score >= TARGET or remaining <= 0:
            waka.vx = waka.vy = 0.0
            waka.rowing = waka.stroking = False
            state = "ending"

        pygame.display.flip()
        await asyncio.sleep(0)

    hard_quit()


if __name__ == "__main__":
    asyncio.run(main())
