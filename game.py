import pygame
import time
import random
import math

try:
	import serial  # type: ignore
except Exception:  # pyserial may be missing; we'll run without it
	serial = None  # type: ignore


class Particle:
	def __init__(self, x: int, y: int, color: tuple[int, int, int]):
		self.x = float(x)
		self.y = float(y)
		self.vx = random.uniform(-2.5, 2.5)
		self.vy = random.uniform(-3.0, -0.5)
		self.life = 1.0
		self.color = color
		self.radius = random.randint(2, 4)

	def update(self, dt: float) -> None:
		self.x += self.vx * 60 * dt
		self.y += self.vy * 60 * dt
		self.vy += 0.06 * 60 * dt  # gravity
		self.life -= 0.02 * 60 * dt
		if self.life < 0:
			self.life = 0

	def draw(self, surface: pygame.Surface) -> None:
		alpha = max(0, min(255, int(255 * self.life)))
		s = pygame.Surface((self.radius * 2, self.radius * 2), pygame.SRCALPHA)
		pygame.draw.circle(s, (*self.color, alpha), (self.radius, self.radius), self.radius)
		surface.blit(s, (int(self.x - self.radius), int(self.y - self.radius)))


class Game:
	def __init__(self) -> None:
		pygame.init()
		try:
			pygame.mixer.init()
			self.snd_ok = True
		except Exception:
			self.snd_ok = False
		self.WIDTH, self.HEIGHT = 800, 600
		self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
		pygame.display.set_caption("GY-521 Coin Collector")
		self.clock = pygame.time.Clock()
		self.font = pygame.font.Font(None, 36)
		self.big_font = pygame.font.Font(None, 64)

		# Colors
		self.WHITE = (255, 255, 255)
		self.GREEN = (80, 230, 120)
		self.YELLOW = (255, 210, 60)
		self.BLUE_DARK = (20, 30, 60)
		self.BLUE_LIGHT = (40, 80, 160)

		# Serial
		self.ser = None
		self.serial_ok = False
		self._init_serial()

		# Game state
		self.state = "TITLE"  # TITLE -> PLAYING -> PAUSED or GAME_OVER

		# Particles
		self.particles: list[Particle] = []

		# Time limit
		self.round_time_sec = 60

		# Input smoothing
		self.smooth_ax = 0.0
		self.smooth_ay = 0.0
		self.smooth_alpha = 0.2

		self.reset()

		# High score
		self.high_score = self._load_high_score()

		# Sounds
		self.snd_pick = None
		self.snd_ui = None
		if self.snd_ok:
			try:
				# Very short synthesized beeps using pygame.sndarray would need numpy; instead load nothing-safe
				# Keep placeholders for future WAV files named coin.wav and ui.wav
				self.snd_pick = pygame.mixer.Sound(file=None)  # type: ignore[arg-type]
			except Exception:
				self.snd_pick = None
			try:
				self.snd_ui = pygame.mixer.Sound(file=None)  # type: ignore[arg-type]
			except Exception:
				self.snd_ui = None


	def _init_serial(self) -> None:
		if serial is None:
			self.serial_ok = False
			return
		try:
			self.ser = serial.Serial("COM3", 9600, timeout=0.01)  # type: ignore
			time.sleep(1.5)
			self.serial_ok = True
		except Exception:
			self.ser = None
			self.serial_ok = False

	def _load_high_score(self) -> int:
		try:
			with open("highscore.txt", "r", encoding="utf-8") as f:
				return int(f.read().strip() or 0)
		except Exception:
			return 0

	def _save_high_score(self) -> None:
		try:
			with open("highscore.txt", "w", encoding="utf-8") as f:
				f.write(str(self.high_score))
		except Exception:
			pass

	def reset(self) -> None:
		self.ball_radius = 25
		self.ball_x = self.WIDTH // 2
		self.ball_y = self.HEIGHT // 2
		self.coin_radius_base = 16
		self.coin_x = random.randint(self.coin_radius_base, self.WIDTH - self.coin_radius_base)
		self.coin_y = random.randint(self.coin_radius_base, self.HEIGHT - self.coin_radius_base)
		self.score = 0
		self.start_time_ms = pygame.time.get_ticks()
		self.remaining_ms = self.round_time_sec * 1000
		self.particles.clear()

	def gradient_background(self) -> None:
		for y in range(self.HEIGHT):
			blend = y / max(1, self.HEIGHT - 1)
			r = int(self.BLUE_DARK[0] * (1 - blend) + self.BLUE_LIGHT[0] * blend)
			g = int(self.BLUE_DARK[1] * (1 - blend) + self.BLUE_LIGHT[1] * blend)
			b = int(self.BLUE_DARK[2] * (1 - blend) + self.BLUE_LIGHT[2] * blend)
			pygame.draw.line(self.screen, (r, g, b), (0, y), (self.WIDTH, y))

	def read_inputs(self) -> tuple[float, float]:
		ax, ay = 0.0, 0.0
		if self.serial_ok and self.ser is not None and getattr(self.ser, "in_waiting", 0) > 0:
			try:
				line = self.ser.readline().decode(errors="ignore").strip()
				parts = line.split(",")
				if len(parts) == 3 and all(p.strip().lstrip("-").isdigit() for p in parts):
					ax_i, ay_i, _ = map(int, parts)
					ax = float(ax_i)
					ay = float(ay_i)
			except Exception:
				pass
		# Keyboard fallback and fine control
		keys = pygame.key.get_pressed()
		if keys[pygame.K_LEFT] or keys[pygame.K_a]:
			ax -= 3000
		if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
			ax += 3000
		if keys[pygame.K_UP] or keys[pygame.K_w]:
			ay += 3000  # forward tilt maps to negative screen Y later
		if keys[pygame.K_DOWN] or keys[pygame.K_s]:
			ay -= 3000
		return ax, ay

	def update_gameplay(self, dt: float) -> None:
		# Time
		elapsed = pygame.time.get_ticks() - self.start_time_ms
		self.remaining_ms = max(0, self.round_time_sec * 1000 - elapsed)
		if self.remaining_ms == 0:
			self.state = "GAME_OVER"
			self.high_score = max(self.high_score, self.score)
			self._save_high_score()
			return

		# Inputs and smoothing
		ax, ay = self.read_inputs()
		self.smooth_ax = self.smooth_alpha * ax + (1 - self.smooth_alpha) * self.smooth_ax
		self.smooth_ay = self.smooth_alpha * ay + (1 - self.smooth_alpha) * self.smooth_ay

		# Map accelerometer to movement
		sensitivity = 0.0009  # tune as needed
		vx = self.smooth_ax * sensitivity
		vy = -self.smooth_ay * sensitivity  # screen Y grows downwards
		self.ball_x += int(round(vx * 60 * dt))
		self.ball_y += int(round(vy * 60 * dt))

		# Keyboard small nudge for precision (Shift to slow)
		keys = pygame.key.get_pressed()
		modifier = 1
		if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
			modifier = 0.4
		if keys[pygame.K_j]:
			self.ball_x -= int(5 * modifier)
		if keys[pygame.K_l]:
			self.ball_x += int(5 * modifier)
		if keys[pygame.K_i]:
			self.ball_y -= int(5 * modifier)
		if keys[pygame.K_k]:
			self.ball_y += int(5 * modifier)

		# Clamp to window
		if self.ball_x - self.ball_radius < 0:
			self.ball_x = self.ball_radius
		elif self.ball_x + self.ball_radius > self.WIDTH:
			self.ball_x = self.WIDTH - self.ball_radius
		if self.ball_y - self.ball_radius < 0:
			self.ball_y = self.ball_radius
		elif self.ball_y + self.ball_radius > self.HEIGHT:
			self.ball_y = self.HEIGHT - self.ball_radius

		# Coin collision
		dx = self.ball_x - self.coin_x
		dy = self.ball_y - self.coin_y
		dist2 = dx * dx + dy * dy
		if dist2 < (self.ball_radius + self.coin_radius_base) ** 2:
			self.score += 1
			self.coin_x = random.randint(self.coin_radius_base, self.WIDTH - self.coin_radius_base)
			self.coin_y = random.randint(self.coin_radius_base, self.HEIGHT - self.coin_radius_base)
			# spawn particles
			for _ in range(24):
				self.particles.append(Particle(self.ball_x, self.ball_y, self.YELLOW))
			# sound
			try:
				if self.snd_pick is not None:
					self.snd_pick.play()
			except Exception:
				pass

		# Update particles
		for p in self.particles:
			p.update(dt)
		self.particles = [p for p in self.particles if p.life > 0]

	def draw_coin(self, t_ms: int) -> None:
		# Pulsing animated coin
		pulse = 1.0 + 0.15 * (1 + math.sin(t_ms * 0.007))
		radius = int(self.coin_radius_base * pulse)
		s = pygame.Surface((radius * 2 + 6, radius * 2 + 6), pygame.SRCALPHA)
		pygame.draw.circle(s, (255, 235, 120, 230), (radius + 3, radius + 3), radius)
		pygame.draw.circle(s, (255, 255, 255, 80), (radius + 3, radius + 3), int(radius * 0.5), width=3)
		self.screen.blit(s, (self.coin_x - radius - 3, self.coin_y - radius - 3))

	def draw_ball(self) -> None:
		# Soft edge ball
		s = pygame.Surface((self.ball_radius * 2 + 8, self.ball_radius * 2 + 8), pygame.SRCALPHA)
		pygame.draw.circle(s, (*self.GREEN, 255), (self.ball_radius + 4, self.ball_radius + 4), self.ball_radius)
		pygame.draw.circle(s, (255, 255, 255, 60), (self.ball_radius + 4, self.ball_radius + 4), int(self.ball_radius * 0.6))
		self.screen.blit(s, (self.ball_x - self.ball_radius - 4, self.ball_y - self.ball_radius - 4))

	def draw_ui(self) -> None:
		score_text = self.font.render(f"Score: {self.score}", True, self.WHITE)
		self.screen.blit(score_text, (20, 18))
		rem_s = max(0, int(self.remaining_ms / 1000))
		time_text = self.font.render(f"Time: {rem_s}s", True, self.WHITE)
		self.screen.blit(time_text, (self.WIDTH - 160, 18))
		hs_text = self.font.render(f"Best: {self.high_score}", True, self.WHITE)
		self.screen.blit(hs_text, (self.WIDTH // 2 - 60, 18))

	def run(self) -> None:
		running = True
		while running:
			dt = self.clock.tick(60) / 1000.0
			for event in pygame.event.get():
				if event.type == pygame.QUIT:
					running = False
				elif event.type == pygame.KEYDOWN:
					if self.state == "TITLE":
						if event.key in (pygame.K_RETURN, pygame.K_SPACE):
							self.reset()
							self.state = "PLAYING"
					elif self.state == "PLAYING":
						if event.key == pygame.K_ESCAPE:
							self.state = "PAUSED"
					elif self.state == "PAUSED":
						if event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
							self.state = "PLAYING"
					elif self.state == "GAME_OVER":
						if event.key in (pygame.K_RETURN, pygame.K_SPACE):
							self.reset()
							self.state = "PLAYING"

			# Draw
			self.gradient_background()
			now_ms = pygame.time.get_ticks()

			if self.state == "TITLE":
				title = self.big_font.render("GY-521 Coin Collector", True, self.WHITE)
				prompt = self.font.render("Press Enter/Space to start", True, self.WHITE)
				self.screen.blit(title, (self.WIDTH // 2 - title.get_width() // 2, self.HEIGHT // 3))
				self.screen.blit(prompt, (self.WIDTH // 2 - prompt.get_width() // 2, self.HEIGHT // 3 + 80))
				note = self.font.render("Use sensor tilt or arrows/WASD", True, self.WHITE)
				self.screen.blit(note, (self.WIDTH // 2 - note.get_width() // 2, self.HEIGHT // 3 + 130))
			elif self.state == "PLAYING":
				self.update_gameplay(dt)
				self.draw_coin(now_ms)
				self.draw_ball()
				for p in self.particles:
					p.draw(self.screen)
				self.draw_ui()
			elif self.state == "PAUSED":
				self.draw_coin(now_ms)
				self.draw_ball()
				for p in self.particles:
					p.draw(self.screen)
				self.draw_ui()
				paused = self.big_font.render("Paused", True, self.WHITE)
				resume = self.font.render("Press Esc/Enter to resume", True, self.WHITE)
				self.screen.blit(paused, (self.WIDTH // 2 - paused.get_width() // 2, self.HEIGHT // 2 - 20))
				self.screen.blit(resume, (self.WIDTH // 2 - resume.get_width() // 2, self.HEIGHT // 2 + 40))
			elif self.state == "GAME_OVER":
				self.draw_coin(now_ms)
				self.draw_ball()
				for p in self.particles:
					p.draw(self.screen)
				self.draw_ui()
				go = self.big_font.render("Time's Up!", True, self.WHITE)
				sum1 = self.font.render(f"Score: {self.score}", True, self.WHITE)
				sum2 = self.font.render(f"Best: {self.high_score}", True, self.WHITE)
				restart = self.font.render("Press Enter/Space to play again", True, self.WHITE)
				self.screen.blit(go, (self.WIDTH // 2 - go.get_width() // 2, self.HEIGHT // 2 - 60))
				self.screen.blit(sum1, (self.WIDTH // 2 - sum1.get_width() // 2, self.HEIGHT // 2))
				self.screen.blit(sum2, (self.WIDTH // 2 - sum2.get_width() // 2, self.HEIGHT // 2 + 34))
				self.screen.blit(restart, (self.WIDTH // 2 - restart.get_width() // 2, self.HEIGHT // 2 + 80))

			pygame.display.flip()

		pygame.quit()


if __name__ == "__main__":
	Game().run()