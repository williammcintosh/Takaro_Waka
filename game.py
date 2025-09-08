import pygame, asyncio, math, random, time

W, H = 1200, 680
FPS = 60
FISH_LIFE = 3.0
TARGET = 7
ROT_SPEED = 3.0
THRUST = 0.12
FRICTION = 0.99
BRAKE = 0.95



class Waka:
    def __init__(self, x, y, fps=8, splash_snd=None):
        self.x, self.y = x, y
        self.ang = -90
        self.vx, self.vy = 0.0, 0.0
        self.net_flash_t = 0
        self.frames = [pygame.image.load(f"images/waka/waka__{i}.png").convert_alpha() for i in range(1, 8)]
        self.frame_idx = 0
        self.frame_ms = int(1000 / fps)
        self.last_frame_tick = pygame.time.get_ticks()
        self.rowing = False
        self.net_img = pygame.image.load("images/waka/wakanet__1.png").convert_alpha()
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
        self.splash_snd = splash_snd
        self.splash_cd = 180  # ms
        self.splash_snd = splash_snd
        self.splash_cd = 260  # ms between splashes
        self.last_splash = 0
        self.splash_ch = pygame.mixer.Channel(1)  # dedicated channel


    def net_active(self):
        return pygame.time.get_ticks() - self.net_flash_t < 120

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
        if keys[pygame.K_SPACE]:
            self.net_flash_t = pygame.time.get_ticks()

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
        # movement, Cant row if nets are up
        if self.stroking and not self.net_active() and now - self.stroke_start <= self.STROKE_MS:
            r = math.radians(self.ang)
            self.vx += math.cos(r) * self.STROKE_THRUST
            self.vy += math.sin(r) * self.STROKE_THRUST
            self.rowing = True
            # self._play_splash()
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
        if not self.splash_snd: return
        now = pygame.time.get_ticks()
        if now - self.last_splash < self.splash_cd:  # keep a small cooldown
            return
        self.last_splash = now

        ch = pygame.mixer.find_channel()  # pick a free one
        if not ch: return                  # all busy, skip this stroke

        vol = random.uniform(0.85, 1.0)
        l = random.uniform(0.9, 1.0); r = random.uniform(0.9, 1.0)
        ch.set_volume(vol*l, vol*r)
        ch.play(self.splash_snd)



    def draw(self, screen):
        img = self.frames[self.frame_idx]
        rotated = pygame.transform.rotate(img, -self.ang-90)
        rect = rotated.get_rect(center=(self.x, self.y))
        screen.blit(rotated, rect.topleft)

        if pygame.time.get_ticks() - self.net_flash_t < 120:
            net_rot = pygame.transform.rotate(self.net_img, -self.ang-90)
            net_rect = net_rot.get_rect(center=(self.x, self.y))
            screen.blit(net_rot, net_rect.topleft)

    def try_catch(self, fish):
        # only during cast window
        if not fish or pygame.time.get_ticks() - self.net_flash_t >= 120:
            return False

        # rotate net like in draw
        net_rot = pygame.transform.rotate(self.net_img, -self.ang-90)
        net_rect = net_rot.get_rect(center=(int(self.x), int(self.y)))

        # fish current frame and rect
        fish_img = fish.frames[fish.frame_idx]
        fish_rect = fish_img.get_rect(center=(int(fish.x), int(fish.y)))

        # pixel masks
        net_mask = pygame.mask.from_surface(net_rot)
        fish_mask = pygame.mask.from_surface(fish_img)

        # offset of fish relative to net
        offset = (fish_rect.left - net_rect.left, fish_rect.top - net_rect.top)

        return net_mask.overlap(fish_mask, offset) is not None
    


class Fish:

    def __init__(self, x, y, life=FISH_LIFE, fps=10, scale=1.0):
        self.x, self.y = float(x), float(y)
        self.expires_at = time.time() + life
        self.frames = [pygame.image.load(f"images/fishy/fish__{i}.png").convert_alpha() for i in range(1, 28)]
        if scale != 1.0:
            self.frames = [pygame.transform.smoothscale(f, (int(f.get_width()*scale), int(f.get_height()*scale))) for f in self.frames]
        self.frame_idx = 0
        self.frame_ms = int(1000 / fps)
        self.last_frame_tick = pygame.time.get_ticks()

    @property
    def alive(self):
        return time.time() < self.expires_at

    def update(self):
        now = pygame.time.get_ticks()
        if now - self.last_frame_tick >= self.frame_ms:
            self.frame_idx = (self.frame_idx + 1) % len(self.frames)
            self.last_frame_tick = now

    def draw(self, screen):
        img = self.frames[self.frame_idx]
        rect = img.get_rect(center=(int(self.x), int(self.y)))
        screen.blit(img, rect.topleft)


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
    pygame.init()
    pygame.mixer.init()
    pygame.mixer.set_num_channels(16)  # more heads to play on
    coin = pygame.mixer.Sound("sounds/get-coin.mp3")
    splash_snd = pygame.mixer.Sound("sounds/row_splash.mp3")
    count = {
        1: pygame.mixer.Sound("sounds/tahi_ika.mp3"),
        2: pygame.mixer.Sound("sounds/rua_ika.mp3"),
        3: pygame.mixer.Sound("sounds/toru_ika.mp3"),
        4: pygame.mixer.Sound("sounds/wha_ika.mp3"),
        5: pygame.mixer.Sound("sounds/rima_ika.mp3"),
        6: pygame.mixer.Sound("sounds/ono_ika.mp3"),
        7: pygame.mixer.Sound("sounds/whitu_ika.mp3"),
    }

    screen = pygame.display.set_mode((W, H))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 24)

    waka = Waka(W/2, H/2, splash_snd=splash_snd)
    fish = None
    score = 0
    start = time.time()
    time_limit = 60

    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT: running = False
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_UP:
                if not waka.stroking and not waka.net_active():
                    waka.stroking = True
                    waka._play_splash()
                    waka.stroke_start = pygame.time.get_ticks()
            elif e.type == pygame.KEYUP and e.key == pygame.K_UP:
                waka.stroking = False

        keys = pygame.key.get_pressed()
        waka.handle_input(keys)
        waka.update()

        now = time.time()
        if fish is None and random.random() < 0.02:
            fish = Fish(random.randint(40, W-40), random.randint(40, H-40), life=FISH_LIFE, fps=8, scale=0.9)
        elif fish and not fish.alive:
            fish = None

        if fish:
            fish.update()

        if fish and waka.try_catch(fish):
            score += 1
            coin.play()
            if score in count:
                count[score].play()
            fish = None

        bg = get_sky_color(start)
        screen.fill(bg)

        if fish:
            fish.draw(screen)
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
