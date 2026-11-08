from pathlib import Path
from copy import copy

from ursina import (
    Ursina, Entity, Sky, Text, application, camera, color,
    load_model, load_texture, mouse, window,
    Vec2, Vec3, raycast, destroy, invoke, time, held_keys, lerp,
)
from ursina.prefabs.first_person_controller import FirstPersonController as FPC
from time import monotonic
import math
import random
import os
import sys

LOOK_SENSITIVITY = 65  # 기본값 40보다 높게 설정
SLIDE_DURATION = 1.0
SLIDE_COOLDOWN = 0


class Player(FPC):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mouse_sensitivity = Vec2(LOOK_SENSITIVITY, LOOK_SENSITIVITY)
        self.slide_left = 0
        self.slide_cooldown = 0
        self.slide_direction = Vec3(0, 0, 1)
        self.air_speed = 0.0
        self.airborne_seen = False
        self.long_jump = False
        self.long_jump_airborne = False
        self.normal_jump_settings = (self.jump_height, self.jump_up_duration,
                                     self.fall_after, self.gravity)
        self.aiming = False

    def start_slide(self):
        direction = (self.forward * (held_keys['w'] - held_keys['s'])
                     + self.right * (held_keys['d'] - held_keys['a']))
        if (not mouse.locked or not self.enabled or not self.grounded
                or self.slide_left > 0 or self.slide_cooldown > 0
                or direction.length() == 0):
            return
        self.slide_direction = direction.normalized()
        self.slide_left = SLIDE_DURATION
        self.slide_cooldown = SLIDE_COOLDOWN

    def update(self):
        dt = min(time.dt, 0.05)
        self.slide_cooldown = max(0, self.slide_cooldown - dt)
        self.aiming = bool(held_keys['right mouse'] and mouse.locked)
        sensitivity = LOOK_SENSITIVITY * (0.55 if self.aiming else 1)
        self.mouse_sensitivity = Vec2(sensitivity, sensitivity)
        self.speed = 0 if self.slide_left > 0 or self.air_speed > 0 else (3 if self.aiming else 5)
        super().update()
        if self.long_jump:
            if not self.grounded:
                self.long_jump_airborne = True
            elif self.long_jump_airborne:
                self.long_jump = False
                (self.jump_height, self.jump_up_duration,
                 self.fall_after, self.gravity) = self.normal_jump_settings
        if self.air_speed > 0:
            if not self.grounded:
                self.airborne_seen = True
            elif self.airborne_seen:
                self.air_speed = 0
            if self.air_speed > 0 and self.move_with_collision(self.air_speed * dt):
                self.air_speed = 0
        if self.slide_left > 0:
            if not self.grounded:
                self.slide_left = 0
            else:
                step = (5 + 8 * self.slide_left / SLIDE_DURATION) * dt
                blocked = self.move_with_collision(step)
                self.slide_left = 0 if blocked else max(0, self.slide_left - dt)
        # 충돌 높이는 유지하고 카메라만 낮춰 좁은 천장에 끼지 않게 한다.
        self.camera_pivot.y = lerp(self.camera_pivot.y,
                                   1.05 if self.slide_left > 0 else self.height,
                                   min(1, dt * 14))

    def move_with_collision(self, step):
        # 슬라이드와 공중 가속에 동일한 몸통 폭/높이 충돌 검사를 적용한다.
        requested = step
        side = Vec3(self.slide_direction.z, 0, -self.slide_direction.x)
        for offset in (-0.3, 0, 0.3):
            for height in (0.25, 0.9, 1.8):
                hit = raycast(self.position + side * offset + Vec3(0, height, 0),
                              self.slide_direction, distance=step + 0.35,
                              ignore=self.ignore_list)
                if hit.hit:
                    step = min(step, max(0, hit.distance - 0.35))
        self.position += self.slide_direction * step
        return step < requested

    def jump(self):
        if not self.grounded or self.air_speed > 0:
            return
        if self.slide_left > 0:
            # 점프 순간의 방향과 속도를 보존한다. WASD를 놓아도 계속 전진한다.
            self.air_speed = 5 + 8 * self.slide_left / SLIDE_DURATION
            self.airborne_seen = False
            self.slide_left = 0
            # 상승 1.2초 + 하강 약 1.3초: 평지에서 약 2.5초 체공.
            self.long_jump = True
            self.long_jump_airborne = False
            self.jump_height = 3
            self.jump_up_duration = 1.2
            self.fall_after = 1.2
            self.gravity = 0.14
        super().jump()

    def start_fall(self):
        super().start_fall()
        if self.long_jump:
            self.air_time = 0


app = Ursina()
player = Player(position=(0, 0.1, -12))

ground = Entity(model='cube', scale=(100, 1, 100), y=-0.5,
                texture='white_cube', texture_scale=(100, 100), collider='box')
Sky()

asset_dir = Path(__file__).resolve().parent / 'assets' / 'blaster_kit'
palette = load_texture('colormap.png', folder=asset_dir / 'Textures')
weapons = {
    '1': dict(name='RIFLE', model='blaster-a', interval=0.10, damage=25,
              zoom=55, scale=0.65, hip=Vec3(.34, -.24, .85), aim=Vec3(0, -.23, .85)),
    '2': dict(name='SNIPER', model='blaster-e', interval=1.1, damage=120,
              zoom=22, scale=0.55, hip=Vec3(.34, -.24, 1.25), aim=Vec3(0, -.23, 1.05)),
    '3': dict(name='PISTOL', model='blaster-b', interval=0.28, damage=40,
              zoom=65, scale=0.8, hip=Vec3(.3, -.25, .7), aim=Vec3(0, -.2, .7)),
}
for weapon in weapons.values():
    weapon['mesh'] = load_model(weapon['model'] + '.obj', folder=asset_dir, use_deepcopy=True)
active_weapon = '1'
gun_model = weapons[active_weapon]['mesh']
target_model = load_model('target-large.obj', folder=asset_dir, use_deepcopy=True)
gun_position = weapons[active_weapon]['hip']
aim_position = weapons[active_weapon]['aim']
recoil = 0.0
gun = Entity(parent=camera, model=gun_model, texture=palette,
             position=gun_position, scale=weapons[active_weapon]['scale'], rotation_y=180)
flash = Entity(parent=camera, model='sphere', color=color.yellow,
               position=(0.34, -0.23, 1.35), scale=0.09, enabled=False)

score = 0
health = 100
kills = 0
game_over = False
next_shot = 0.0
score_text = Text('Hits: 0', position=(-0.86, 0.45), scale=1.3)
health_text = Text('HP: 100 | Kills: 0', position=(-0.86, 0.40), scale=1.2)
weapon_text = Text('1 RIFLE | 2 Sniper | 3 Pistol', position=(-0.86, 0.35), scale=1)
Text('Hold LMB: Fire | RMB: Aim | 1/2/3: Weapon\nWASD: Move | C: Slide | Space: Jump | Esc: Mouse',
     position=(-0.86, -0.40), scale=0.85)
death_text = Text('GAME OVER\nPress R to restart', origin=(0, 0), scale=2, enabled=False)
hit_marker = Text('X', origin=(0, 0), scale=1.5,
                  color=color.yellow, enabled=False)
targets = []
for x, z in ((-6, 10), (0, 16), (6, 22), (-10, 29), (10, 32)):
    Entity(model='cube', color=color.dark_gray,
           scale=(0.12, 1.6, 0.12), position=(x, 0.8, z), collider='box')
    targets.append(Entity(model=copy(target_model), texture=palette, scale=4,
                          position=(x, 2, z), rotation_y=90, collider='box'))

zombie_dir = asset_dir.parent / 'block_zombie'
zombie_model = load_model('zombie.obj', folder=zombie_dir, use_deepcopy=True)
zombie_texture = load_texture('palette.png', folder=zombie_dir)
zombie_texture.filtering = None
enemies = []


class Zombie(Entity):
    def __init__(self, position):
        super().__init__(name='zombie', model=copy(zombie_model), texture=zombie_texture,
                         position=position)
        self.health = 100
        self.attack_at = 0
        self.speed = random.uniform(1.4, 2.1)

    def update(self):
        if game_over or not mouse.locked or not player.enabled or self.health <= 0:
            return
        delta = player.position - self.position
        delta.y = 0
        distance = delta.length()
        if distance > 0.01:
            direction = delta.normalized()
            self.rotation_y = math.degrees(math.atan2(direction.x, direction.z))
        else:
            return
        if distance > 1.3:
            step = self.speed * min(time.dt, .05)
            # 다른 적이나 장애물 앞에서는 옆으로 돌아서 이동한다.
            for heading in (direction, Vec3(direction.z, 0, -direction.x),
                            Vec3(-direction.z, 0, direction.x)):
                blocked = raycast(self.position + Vec3(0, 1, 0), heading,
                                  distance=step + .65, ignore=(self,))
                if not blocked.hit:
                    self.position += heading * step
                    break
        elif abs(player.y - self.y) < 2.3 and monotonic() >= self.attack_at:
            eye = self.position + Vec3(0, 1.5, 0)
            to_player = player.position + Vec3(0, 1, 0) - eye
            if not raycast(eye, to_player.normalized(), distance=to_player.length(),
                           ignore=(self, player)).hit:
                self.attack_at = monotonic() + 1
                damage_player(10)

    def take_damage(self, amount):
        global kills
        if self.health <= 0:
            return
        self.health -= amount
        if self.health <= 0:
            self.collision = False
            self.enabled = False
            enemies.remove(self)
            destroy(self)
            kills += 1
            refresh_health()
            invoke(spawn_zombie, delay=3)
        else:
            self.blink(color.red, duration=.12)


def refresh_health():
    health_text.text = f'HP: {health} | Kills: {kills}'


def damage_player(amount):
    global health, game_over
    if game_over:
        return
    health = max(0, health - amount)
    refresh_health()
    if health == 0:
        game_over = True
        player.slide_left = player.air_speed = 0
        player.enabled = False
        mouse.locked = False
        gun.enabled = flash.enabled = hit_marker.enabled = False
        death_text.enabled = True


def spawn_zombie():
    if game_over:
        return
    angle = random.uniform(0, math.tau)
    radius = random.uniform(18, 26)
    x = max(-45, min(45, player.x + math.cos(angle) * radius))
    z = max(-45, min(45, player.z + math.sin(angle) * radius))
    enemies.append(Zombie((x, 0, z)))


for _ in range(6):
    spawn_zombie()


def select_weapon(key):
    global active_weapon, gun_position, aim_position, recoil, next_shot
    if game_over or not mouse.locked or key == active_weapon:
        return
    active_weapon = key
    weapon = weapons[key]
    gun.model = copy(weapon['mesh'])
    gun.texture = palette
    gun.scale = weapon['scale']
    gun_position, aim_position = weapon['hip'], weapon['aim']
    gun.position = gun_position
    recoil = 0
    flash.enabled = False
    # 교체로 기존 무기의 발사 대기 시간을 우회할 수 없다.
    next_shot = max(next_shot, monotonic() + .2)
    weapon_text.text = ' | '.join(f'{k} {v["name"] if k == key else v["name"].title()}'
                                  for k, v in weapons.items())


def reset_target(target):
    target.enabled = True


def shoot():
    global next_shot, score, recoil
    if game_over or not mouse.locked or not player.enabled:
        return
    now = monotonic()
    if now < next_shot:
        return
    weapon = weapons[active_weapon]
    next_shot = now + weapon['interval']
    recoil = 0.035 if player.aiming else 0.09
    flash.enabled = True
    invoke(setattr, flash, 'enabled', False, delay=0.05)

    # 화면 중앙에서 가장 가까운 충돌체만 맞힌다.
    hit = raycast(camera.world_position, camera.forward, distance=100,
                  ignore=(player, gun, flash))
    if not hit.hit:
        return
    impact = Entity(model='sphere', color=color.orange, scale=0.06,
                    position=hit.world_point + hit.world_normal * 0.015)
    destroy(impact, delay=0.2)
    if isinstance(hit.entity, Zombie):
        hit.entity.take_damage(weapon['damage'])
        hit_marker.enabled = True
        invoke(setattr, hit_marker, 'enabled', False, delay=.08)
    if hit.entity in targets:
        target = hit.entity
        target.enabled = False
        score += 1
        score_text.text = f'Hits: {score}'
        hit_marker.enabled = True
        invoke(setattr, hit_marker, 'enabled', False, delay=0.12)
        invoke(reset_target, target, delay=2)


def update():
    for zombie in enemies[:]:
        if abs(zombie.x) >= 100 or abs(zombie.z) >= 100:
            enemies.remove(zombie)
            destroy(zombie)
    if player.y < -10:
        player.position=(0, 0, 10)
    global recoil
    if game_over:
        return
    if held_keys['left mouse']:
        shoot()
    aiming = player.enabled and mouse.locked and bool(held_keys['right mouse'])
    blend = min(1, time.dt * 14)
    recoil = lerp(recoil, 0, min(1, time.dt * 18))
    pose = aim_position if aiming else gun_position
    gun.position = lerp(gun.position, pose - Vec3(0, 0, recoil), blend)
    flash.position = gun.position + Vec3(0, 0.01, 0.1)
    camera.fov = lerp(camera.fov, weapons[active_weapon]['zoom'] if aiming else 90, blend)
    player.cursor.scale = 0.004 if aiming else 0.008


def input(key):
    if game_over:
        if key == 'r':
            os.execl(sys.executable, sys.executable, str(Path(__file__).resolve()))
        return
    if key in weapons:
        select_weapon(key)
    elif key == 'left mouse down':
        shoot()
    elif key == 'c':
        player.start_slide()
    elif key == 'escape':
        player.slide_left = 0
        player.air_speed = 0
        player.aiming = False
        mouse.locked = not mouse.locked
        player.enabled = mouse.locked


#플레이어 리스폰


app.run()
