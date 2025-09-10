import pygame, asyncio, math, random, time

W, H = 1200, 680
FPS = 60
FISH_LIFE = 3.0
TARGET = 9
ROT_SPEED = 3.0
THRUST = 0.12
FRICTION = 0.99
BRAKE = 0.95

pygame.init()
screen = pygame.display.set_mode((W, H))
fish_imgs = [pygame.image.load(f"images/fishy/fish__{i}.png").convert_alpha()
                for i in range(1, 28)]
star_imgs = [pygame.image.load(f"images/stars/matariki_star_{i}.png").convert_alpha()
                for i in range(1, 10)]
wake_img_big = pygame.image.load("images/waka/waka_wake_big.png").convert_alpha()
wake_img_small = pygame.image.load("images/waka/waka_wake_small.png").convert_alpha()

class Waka:
    def __init__(self, x, y, fps=8, splash_snds=None):
        self.x, self.y = x, y
        self.ang = -90
        self.vx, self.vy = 0.0, 0.0
        self.net_flash_t = 0
        self.frames = [pygame.image.load(f"images/waka/waka__{i}.png").convert_alpha() for i in range(1, 8)]
        self.frame_idx = 0
        self.frame_ms = int(1000 / fps)
        self.last_frame_tick = pygame.time.get_ticks()
        self.rowing = False
        self.net_frames = [
            pygame.image.load("images/waka/wakanet__1.png").convert_alpha(),
            pygame.image.load("images/waka/wakanet__2.png").convert_alpha(),
            pygame.image.load("images/waka/wakanet__3.png").convert_alpha(),
        ]
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
    def __init__(self, x, y, life=FISH_LIFE, fps=10, scale=1.0,
                 splash_snds=None, splash_delay_ms=None, splash_frame=12):
        self.x, self.y = float(x), float(y)
        self.expires_at = time.time() + life
        self.frames = fish_imgs
        if scale != 1.0:
            self.frames = [
                pygame.transform.smoothscale(
                    f, (int(f.get_width()*scale), int(f.get_height()*scale))
                ) for f in self.frames
            ]
        self.frame_idx = 0
        self.frame_ms = int(1000 / fps)
        self.last_frame_tick = pygame.time.get_ticks()

        # sounds
        self.splash_snds = splash_snds or []  # safe default
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
    def __init__(self, x, y, star, flash_ms=120, star_ms=600, steps=12):
        self.x, self.y = int(x), int(y)
        self.flash_ms, self.star_ms = flash_ms, star_ms
        self.t, self.done = 0, False

        # prebuild star frames once
        w, h = star.get_width(), star.get_height()
        self.star_frames = []
        for i in range(steps):
            p = (i+1)/steps
            s = 0.6 + 0.4*math.sin(p*math.pi)
            self.star_frames.append(
                pygame.transform.smoothscale(star, (int(w*s), int(h*s)))
            )

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
        else:
            p = min(1.0, (self.t - self.flash_ms)/self.star_ms)
            idx = min(int(p*(len(self.star_frames)-1)), len(self.star_frames)-1)
            img = self.star_frames[idx]
            screen.blit(img, img.get_rect(center=(self.x,self.y)))

class WakeTrail:
    def __init__(self, img, spawn_ms=60, life_ms=500, max_parts=80):
        self.img = img
        self.spawn_ms = spawn_ms
        self.life_ms = life_ms
        self.max_parts = max_parts
        self.parts, self.last_spawn = [], 0

    def spawn(self, x, y, ang):
        now = pygame.time.get_ticks()
        if now - self.last_spawn < self.spawn_ms: return
        self.last_spawn = now
        # drop a bit behind the waka nose
        r = math.radians(ang)
        px = x - math.cos(r)*24
        py = y - math.sin(r)*24
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



def get_sky_color(start_time, cycle_length=60):
    now = time.time()
    elapsed = now - start_time
    stops = [
        (0, (135,206,250)),
        (0.25, (0,191,255)),
        (0.5, (255,127,80)),
        (1.0, (0,0,20))
    ]
    t = min(elapsed / cycle_length, 1.0)
    for i in range(len(stops)-1):
        t0, c0 = stops[i]
        t1, c1 = stops[i+1]
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0)
            return (
                int(c0[0] + (c1[0]-c0[0])*f),
                int(c0[1] + (c1[1]-c0[1])*f),
                int(c0[2] + (c1[2]-c0[2])*f),
            )
    return stops[-1][1]


async def main():
    pygame.mixer.init()
    pygame.mixer.set_num_channels(16)  # more heads to play on
    coin = pygame.mixer.Sound("sounds/get-coin.mp3")
    # in main() when you load sounds
    row_spalshes = [
        pygame.mixer.Sound(f"sounds/row_splash__{i}.mp3") for i in range(1, 8)
    ]
    fish_splashes = [
        pygame.mixer.Sound(f"sounds/fish_splash__{i}.mp3")
        for i in range(1, 7)
    ]
    net_flips = [
        pygame.mixer.Sound(f"sounds/net_flip__{i}.mp3")
        for i in range(1, 5)
    ]
    count = {
        1: pygame.mixer.Sound("sounds/tahi_ika.mp3"),
        2: pygame.mixer.Sound("sounds/rua_ika.mp3"),
        3: pygame.mixer.Sound("sounds/toru_ika.mp3"),
        4: pygame.mixer.Sound("sounds/wha_ika.mp3"),
        5: pygame.mixer.Sound("sounds/rima_ika.mp3"),
        6: pygame.mixer.Sound("sounds/ono_ika.mp3"),
        7: pygame.mixer.Sound("sounds/whitu_ika.mp3"),
    }
    coin.set_volume(0.4)
    for n in net_flips: n.set_volume(0.8)
    for s in fish_splashes: s.set_volume(0.9)
    for r in row_spalshes: r.set_volume(0.3)
    # for c in count: c.set_volume(1.0)

    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 24)

    waka = Waka(W/2, H/2, splash_snds=row_spalshes) 
    wake_big   = WakeTrail(wake_img_big,   spawn_ms=60,  life_ms=500)
    wake_small = WakeTrail(wake_img_small, spawn_ms=140, life_ms=450)
    fish = None
    score = 0
    start = time.time()
    time_limit = 60
    catch_effect = None

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
            elif e.type == pygame.KEYUP and e.key == pygame.K_UP:
                waka.stroking = False

            # nets control
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_SPACE:
                random.choice(net_flips).play()
                if waka.net_state in ("idle", "retracting"):
                    waka.net_state = "extending"
            elif e.type == pygame.KEYUP and e.key == pygame.K_SPACE:
                random.choice(net_flips).play()
                if waka.net_state in ("extending", "held"):
                    waka.net_state = "retracting"

        keys = pygame.key.get_pressed()
        waka.handle_input(keys)
        waka.update()

        # spawn wake continuously while rowing
        wake_small.spawn(waka.x, waka.y, waka.ang) 
        if waka.rowing and not waka.net_active():
            wake_big.spawn(waka.x, waka.y, waka.ang)

        wake_small.update(dt)
        wake_big.update(dt)

        now = time.time()
        if fish is None and random.random() < 0.02:
            fish = Fish(
                random.randint(40, W-40),
                random.randint(40, H-40),
                life=FISH_LIFE,
                fps=8,
                scale=0.9,
                splash_snds=fish_splashes,
                splash_delay_ms=2000   # optional, only if you want a timed delay
            )
        elif fish and not fish.alive:
            fish = None

        if fish:
            fish.update()

        if fish and waka.try_catch(fish):
            score += 1
            coin.play()
            if score in count:
                count[score].play()
            idx = score - 1  # score 1 → index 0
            if idx < len(star_imgs):
                catch_effect = CatchEffect(fish.x, fish.y, star_imgs[idx])
            else:
                catch_effect = None  # or wrap/reuse last star
            fish = None
            

        bg = get_sky_color(start)
        screen.fill(bg)

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

        remaining = max(0, int(time_limit - (now-start)))
        txt = f"Fish {score}/{TARGET}   Time {remaining}s"
        screen.blit(font.render(txt, True, (255,255,255)), (10,10))

        if score >= TARGET or remaining <= 0:
            msg = "Ka pai! Feast ready." if score>=TARGET else "Kua pau te wā."
            screen.blit(font.render(msg, True, (255,255,255)), (W//2-100, H//2))
            pygame.display.flip()
            await asyncio.sleep(1.5)
            running = False

        pygame.display.flip()
        clock.tick(FPS)
        await asyncio.sleep(0)

    pygame.quit()

if __name__ == "__main__":
    asyncio.run(main())
