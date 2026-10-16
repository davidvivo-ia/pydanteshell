#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pygame-ce>=2.5", "numpy>=2.0"]
# ///
"""Dante's Hell — DISCIPLINATI. *Palle, palle, palle!* Una commedia per lemming.

Cien almas blancas con una cruz roja al pecho cruzan el Inferno, suben el
Purgatorio y ascienden al Paradiso. Tú no las mueves: les asignas oficios.

Un único fichero. Sin recursos externos: el pixel art, la luz (tenebrismo
dinámico, bloom, niebla, polvo en suspensión), la música y los 101 niveles
se generan por código, y cada nivel lleva una solución de referencia que el
selftest comprueba.

    uv run pydanteshell.py              # jugar
    python pydanteshell.py --selftest   # física, niveles y determinismo
    python pydanteshell.py --demo 4     # ver la solución del nivel 4
    python pydanteshell.py --level 33   # ir directo al Cocito
    python pydanteshell.py --all        # desbloquear la Commedia entera
    python pydanteshell.py --export-levels niveles/   # los 101 niveles en JSON
    python pydanteshell.py --custom mi_nivel.json     # jugar un nivel propio
    python pydanteshell.py --daily      # el Giudizio del giorno
    python pydanteshell.py --endless    # modo Infinito

Ratón y teclado: 1–9 oficio · clic asignar · Retroceso rebobinar · «.» un paso · F5 reiniciar ·
H ocultar HUD · F12 foto · QWERTYUI palle · clic derecho naranja ·
D Privilegio di Dioneo · C segundo intento (Purgatorio) · Tab artista del Mecenate ·
F avance · Espacio pausa · Supr 2 s Dies Irae.
Mando (SDL GameController): stick izq. cursor · A asignar · LB/RB oficio · X naranja ·
cruceta + Y palle · LT/RT cadenza · Start pausa · Select Dioneo · Select+Start 2 s Dies Irae.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import math
import os
import random
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import numpy as np

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
# 1. CONSTANTES
# ═══════════════════════════════════════════════════════════════════════════

TITLE = "Dante's Hell — Disciplinati"
TPS = 20  # ticks de lógica por segundo (simulación determinista a paso fijo)
TICK_MS = 1000 / TPS
LW, LH = 640, 360  # resolución lógica
VIEW_W, VIEW_H = 640, 296  # ventana al mundo
PANEL_H = LH - VIEW_H
CELL = 8  # un carácter del mapa = 8×8 píxeles
ROWS = VIEW_H // CELL  # 37

STEP_UP = 6
STEP_DOWN = 3
FALL_SPEED = 3
LETHAL_FALL = 60  # 8 bloques de 8 px ≈ los «8 bloques» del diseño
FLOAT_DELAY = 10
CLIMB_HEAD = 10
HOIST_TICKS = 5
BRICKS = 12
BRICK_TICKS = 16
SHRUG_TICKS = 10
BASH_CYCLE = 16
BASH_MOVES = frozenset({2, 3, 4, 5, 10, 11, 12, 13})
BASH_LOOKAHEAD = 8
MINE_TICKS = 12
DIG_TICKS = 8
BOMB_TICKS = 5 * TPS
OHNO_TICKS = 16
BOMB_RADIUS = 16
BLOCK_RANGE = 6
GUARD_RANGE = 9
HATCH_TICKS = 30
TRAP_COOLDOWN = 3 * TPS
EXIT_TICKS = 10
SPLAT_TICKS = 16
DROWN_TICKS = 20
BURN_TICKS = 14
PLAGUE_TICKS = 30
RR_MAX = 99

# Moria
FEBBRE_TICKS = 60 * TPS  # fiebre → bubón
BUBBONE_TICKS = 40 * TPS  # bubón → muerte
FOCO_TICKS = 6 * TPS  # cadáver sin enterrar → foco
IMMUNE_TICKS = 15 * TPS
MEDICO_RANGE = 22  # radio en el que el Medico cura
# Disciplina
FERVOR_SLOW = 30 * TPS
# Palle
PESO = {"cambio": 2, "medicinale": 1, "arancia": 1, "mecenate": 3, "congiura": 4, "giglio": 0}
LURE_TICKS = 10 * TPS
LUME_TICKS = 20 * TPS
COMBO_WINDOW = 10 * TPS
COMBO_TICKS = 6 * TPS
PANIC_TICKS = 5 * TPS
DIONEO_TICKS = 15 * TPS
NIGHT_CYCLE = 52 * TPS
NIGHT_LEN = 11 * TPS
DAYS = 33.5
CARRY_TICKS = 30  # Anteo baja a un alma al fondo del pozo
STARE_TICKS = 3 * TPS  # los golosos se quedan mirando la fruta
BLINK_ON, BLINK_OFF = 4 * TPS, 3 * TPS  # las promesas de la Luna


def release_interval(rr: int) -> int:
    """Ticks entre disciplinati para una cadenza 1–99."""
    return max(5, round((53 - rr // 2) * TPS / 17))


# Terreno (un byte por píxel)
AIR, DIRT, STEEL, OW_L, OW_R = range(5)
# Peligros (mapa aparte, no sólidos)
HZ_NONE, HZ_LIQUID, HZ_FIRE, HZ_PURGE, HZ_FLIP = range(5)


class Skill(StrEnum):
    PELLEGRINO = "pellegrino"
    GERIONE = "gerione"
    BUBBONE = "bubbone"
    FLAGELLANTE = "flagellante"
    CAPOMASTRO = "capomastro"
    PIAGNONE = "piagnone"
    MINATORE = "minatore"
    BECCHINO = "becchino"
    MEDICO = "medico"


SKILLS: list[Skill] = list(Skill)
SKILL_NAMES = {
    Skill.PELLEGRINO: "Pellegrino",
    Skill.GERIONE: "Gerione",
    Skill.BUBBONE: "Bubbone",
    Skill.FLAGELLANTE: "Flagellante",
    Skill.CAPOMASTRO: "Capomastro",
    Skill.PIAGNONE: "Piagnone",
    Skill.MINATORE: "Minatore",
    Skill.BECCHINO: "Becchino",
    Skill.MEDICO: "Medico",
}
# Lo que hace cada oficio, dicho como en Lemmings: el verbo en el botón.
SKILL_ACTION = {
    Skill.PELLEGRINO: "ESCALAR",
    Skill.GERIONE: "PLANEAR",
    Skill.BUBBONE: "EXPLOTAR",
    Skill.FLAGELLANTE: "BLOQUEAR",
    Skill.CAPOMASTRO: "ESCALERA",
    Skill.PIAGNONE: "EXCAVAR",
    Skill.MINATORE: "PICAR",
    Skill.BECCHINO: "CAVAR",
    Skill.MEDICO: "CURAR",
}
SKILL_HELP = {
    Skill.PELLEGRINO: "trepa paredes verticales con el bordón (para siempre)",
    Skill.GERIONE: "abre las alas y baja planeando desde cualquier altura (para siempre)",
    Skill.BUBBONE: "cuenta cinco segundos y revienta: abre un agujero en la roca",
    Skill.FLAGELLANTE: "se planta y no deja pasar: los demás se dan la vuelta",
    Skill.CAPOMASTRO: "construye una escalera de doce peldaños hacia delante y arriba",
    Skill.PIAGNONE: "excava un túnel horizontal a puñetazos",
    Skill.MINATORE: "pica en diagonal hacia abajo",
    Skill.BECCHINO: "cava un pozo vertical hacia abajo",
    Skill.MEDICO: "cura la peste a quien pasa a su lado, apaga los focos y es inmune (para siempre)",
}


class St(StrEnum):
    WALK = "walk"
    FALL = "fall"
    FLOAT = "float"
    CLIMB = "climb"
    HOIST = "hoist"
    BLOCK = "block"
    BUILD = "build"
    SHRUG = "shrug"
    BASH = "bash"
    MINE = "mine"
    DIG = "dig"
    OHNO = "ohno"
    SPLAT = "splat"
    DROWN = "drown"
    BURN = "burn"
    PLAGUE = "plague"
    FROZEN = "frozen"
    EXIT = "exit"


STATE_NAMES = {
    St.WALK: "Caminando",
    St.FALL: "Cayendo",
    St.FLOAT: "Planeando",
    St.CLIMB: "Escalando",
    St.HOIST: "Escalando",
    St.BLOCK: "Bloqueando",
    St.BUILD: "Construyendo escalera",
    St.SHRUG: "Escalera terminada",
    St.BASH: "Excavando",
    St.MINE: "Picando",
    St.DIG: "Cavando",
    St.OHNO: "¡Va a explotar!",
    St.SPLAT: "Caído",
    St.DROWN: "Ahogado",
    St.BURN: "Ardiendo",
    St.PLAGUE: "La Moria",
    St.FROZEN: "Hielo del Cocito",
    St.EXIT: "Salvado",
}

DOOMED = frozenset({St.OHNO, St.SPLAT, St.DROWN, St.BURN, St.PLAGUE, St.FROZEN, St.EXIT})
GROUND_WORK = frozenset({St.WALK, St.SHRUG, St.BUILD, St.BASH, St.MINE, St.DIG})
NEEDS_FLOOR = frozenset({St.WALK, St.SHRUG, St.BLOCK, St.BUILD, St.BASH})
EXITABLE = frozenset({St.WALK, St.FALL, St.FLOAT, St.SHRUG, St.BUILD, St.BASH, St.MINE, St.DIG})
AIRBORNE = frozenset({St.FALL, St.FLOAT, St.CLIMB, St.HOIST})
DYING = {St.SPLAT: SPLAT_TICKS, St.DROWN: DROWN_TICKS, St.BURN: BURN_TICKS, St.PLAGUE: PLAGUE_TICKS}


def _circle(r: int) -> np.ndarray:
    yy, xx = np.ogrid[-r : r + 1, -r : r + 1]
    return xx * xx + yy * yy <= r * r


BOMB_MASK = _circle(BOMB_RADIUS)
BASH_MASK = np.ones((9, 5), dtype=bool)
BASH_MASK[0, 3:] = False
BASH_MASK[-1, 4] = False
MINE_MASK = np.ones((10, 6), dtype=bool)
MINE_MASK[0, 3:] = False
MINE_MASK[1, 5] = False
DIG_MASK = np.ones((1, 9), dtype=bool)


# ═══════════════════════════════════════════════════════════════════════════
# 2. SPRITES — pixel art como texto (todo mira a la derecha)
# ═══════════════════════════════════════════════════════════════════════════
# W hábito  w sombra del hábito  R cruz roja  S piel  K látigo  k cuero
# B hábito del Maestro  G oro  F llama  c niño (Caravaggio)  H pelo

PALETTE = {
    "W": (236, 230, 214),
    "w": (168, 160, 150),
    "R": (205, 28, 30),
    "S": (226, 176, 134),
    "K": (120, 74, 40),
    "k": (80, 50, 30),
    "B": (42, 28, 38),
    "b": (74, 54, 66),
    "G": (240, 196, 70),
    "F": (255, 150, 40),
    "c": (124, 82, 52),
    "H": (40, 26, 18),
    "Y": (255, 236, 150),
    "I": (170, 220, 255),
}

_HOOD = ["...W....", "..WWW...", "..WWWW..", "..WSSW..", "..WWWW.."]
_BODY = ["..WRWw..", ".WRRRWK.", "..WRWw.K", "..WWWw..", "..WWWw.."]
_LEGS = [
    ["..WWWW..", "..S..S.."],
    ["..WWWW..", ".S...S.."],
    ["..WWWW..", "..S.S..."],
    ["..WWWW..", "...SS..."],
]
_WHIP = [
    ["..WRWwKK", ".WRRRW..", "..WRWw..", "..WWWw..", "..WWWw.."],
    ["..WRWw..", ".WRRRWKK", "..WRWw.K", "..WWWw..", "..WWWw.."],
]


def _walk_frames() -> list[list[str]]:
    return [_HOOD + _BODY + legs for legs in _LEGS]


SPRITE_SRC: dict[str, list[list[str]]] = {
    "walk": _walk_frames(),
    "whip": [_HOOD + b + _LEGS[0] for b in _WHIP],
    "fall": [
        ["S......S", ".S.W..S.", "..WWW...", "..WWWW..", "..WSSW..", "..WWWW..", "..WRWw..",
         ".WRRRW..", "..WRWw..", "..WWWw..", "..WWWW..", "..S..S.."],
        [".S....S.", "..SW.S..", "..WWW...", "..WWWW..", "..WSSW..", "..WWWW..", "..WRWw..",
         ".WRRRW..", "..WRWw..", "..WWWw..", ".WWWWW..", ".S...S.."],
    ],
    "float": [
        ["ww.....ww", "wWw...wWw", ".wWw.wWw.", "..wW.Ww..", "....W....", "...WWW...", "...WSSW..",
         "...WWWW..", "...WRWw..", "..WRRRW..", "...WRWw..", "...WWWw..", "...WWWW..", "...S..S.."],
        [".........", "ww.....ww", "wWww.wwWw", "..wWWWw..", "....W....", "...WWW...", "...WSSW..",
         "...WWWW..", "...WRWw..", "..WRRRW..", "...WRWw..", "...WWWw..", "...WWWW..", "...S..S.."],
    ],
    "climb": [
        ["......K.", "...W..K.", "..WWW.K.", "..WWWSK.", "..WWSSK.", "..WRWW..", "..RRRW..",
         "..WRWw..", "..WWWw..", "..WWWw..", "...WWW..", "...SS..."],
        ["......K.", "...W..K.", "..WWW.KS", "..WWWWK.", "..WWSS..", "..WRWWS.", "..RRRW..",
         "..WRWw..", "..WWWw..", "..WWWw..", "...WWW..", "....SS.."],
    ],
    "block": [
        ["...W....", "..WWW...", "..WWWW..", "..WSSW..", "K.WWWW.K", "KWWRWwWK", ".WRRRWW.",
         "..WRWw..", "..WWWw..", "..WWWw..", "..WWWW..", ".S....S."],
        ["...W....", "..WWW...", "..WWWW..", "..WSSW..", "..WWWW..", "KWWRWwWK", "KWRRRWWK",
         "..WRWw..", "..WWWw..", "..WWWw..", "..WWWW..", ".S....S."],
    ],
    "build": [
        ["...W....", "..WWW...", "..WWWW..", "..WSSW..", "..WWWW..", "..WRWw..", ".WRRRSGG",
         "..WRWw..", "..WWWw..", "..WWWw..", "..WWWW..", "..S..S.."],
        ["...W....", "..WWW...", "..WWWW..", "..WSSW..", "..WWWWGG", "..WRWS..", ".WRRRW..",
         "..WRWw..", "..WWWw..", "..WWWw..", "..WWWW..", "..S..S.."],
    ],
    "shrug": [
        ["...W....", "..WWW...", "S.WWWW.S", "S.WSSW.S", ".SWWWWS.", "..WRWw..", ".WRRRW..",
         "..WRWw..", "..WWWw..", "..WWWw..", "..WWWW..", "..S..S.."],
    ],
    "bash": [
        ["...W....", "..WWW...", "..WWWW..", "..WSSW..", "..WWWW..", "..WRWSSS", ".WRRRW..",
         "..WRWw..", "..WWWw..", "..WWWw..", "..WWWW..", ".S...S.."],
        ["...W..S.", "..WWW.S.", "..WWWWS.", "..WSSWS.", "..WWWW..", "..WRWw..", ".WRRRW..",
         "..WRWw..", "..WWWw..", "..WWWw..", "..WWWW..", ".S...S.."],
    ],
    "mine": [
        [".....kkk", "...W.K.k", "..WWWK..", "..WWWWS.", "..WSSWS.", "..WWWW..", "..WRWw..",
         ".WRRRW..", "..WRWw..", "..WWWw..", "..WWWW..", ".S...S.."],
        ["...W....", "..WWW...", "..WWWW..", "..WSSW..", "..WWWW..", "..WRWSS.", ".WRRRWSK",
         "..WRWw.K", "..WWWwkk", "..WWWw.k", "..WWWW..", ".S...S.."],
    ],
    "dig": [
        ["...W....", "..WWW...", "..WWWW..", "..WSSW..", ".SWWWWS.", ".KWRWwK.", ".KRRRWK.",
         ".KWRWwK.", ".kkkkkk.", "..WWWw..", "..WWWW..", "..S..S.."],
        ["........", "...W....", "..WWW...", "..WWWW..", "..WSSW..", "SWWWWWWS", "K.WRWw.K",
         "KWRRRW.K", "kkkkkkkk", "..WWWw..", "..WWWW..", "..S..S.."],
    ],
    "ohno": [
        ["..SW.S..", "..SWWS..", "..WWWW..", "..WSSW..", "..WWWW..", "..WRWw..", ".WRRRW..",
         "..WRWw..", "..WWWw..", "..WWWw..", "..WWWW..", "..S..S.."],
        ["........", "..SW.S..", "..SWWS..", "..WWWW..", "..WSSW..", "..WWWW..", "..WRWw..",
         ".WRRRW..", "..WRWw..", "..WWWw..", "..WWWW..", ".S....S."],
    ],
    "splat": [
        ["........"] * 9 + ["...WW...", "..WRRW..", ".WWWWWW."],
        ["........"] * 10 + [".S.RR.S.", "WWWRRWWW"],
        ["........"] * 11 + ["WRWWWRWW"],
    ],
    "frozen": [
        ["IIIIIIII", "IIIWIIII", "IIWWWIII", "IIWWWWII", "IIWSSWII", "IIWWWWII", "IIWRWwII",
         "IWRRRWII", "IIWRWwII", "IIWWWwII", "IIWWWWII", "IISIISII"],
    ],
}


def _recolor(frames: dict[str, list[list[str]]], mapping: dict[str, str]) -> dict[str, list[list[str]]]:
    table = str.maketrans(mapping)
    return {k: [[row.translate(table) for row in f] for f in v] for k, v in frames.items()}


# El Maestro Lapo: hábito negro, cruz de oro. El niño: ropa parda, sin capucha.
MAESTRO_SRC = _recolor(SPRITE_SRC, {"W": "B", "w": "b", "R": "G"})
CHILD_SRC = _recolor(SPRITE_SRC, {"W": "c", "w": "k", "R": "c"})

DIGITS = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "011", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
}


# ═══════════════════════════════════════════════════════════════════════════
# 3. TERRENO
# ═══════════════════════════════════════════════════════════════════════════


class Terrain:
    """Mapa de bytes [y, x] con el tipo de cada píxel, su color y su brillo propio."""

    def __init__(self, kinds: np.ndarray, colors: np.ndarray, emis: np.ndarray, brick: tuple[int, int, int]):
        self.k = kinds
        self.c = colors
        self.e = emis  # vetas incandescentes (bool)
        self.brick = np.array(brick, dtype=np.uint8)
        self.h, self.w = kinds.shape
        self.dirty: tuple[int, int, int, int] | None = (0, 0, self.w, self.h)

    def solid(self, x: int, y: int) -> bool:
        if x < 0 or x >= self.w:
            return True
        if y < 0 or y >= self.h:
            return False
        return self.k[y, x] != AIR

    def _clip(self, x0: int, y0: int, mask: np.ndarray):
        h, w = mask.shape
        ax0, ay0 = max(x0, 0), max(y0, 0)
        ax1, ay1 = min(x0 + w, self.w), min(y0 + h, self.h)
        if ax0 >= ax1 or ay0 >= ay1:
            return None
        return ax0, ay0, ax1, ay1, mask[ay0 - y0 : ay1 - y0, ax0 - x0 : ax1 - x0]

    @staticmethod
    def _forbidden(region: np.ndarray, d: int) -> np.ndarray:
        bad = region == STEEL
        if d > 0:
            bad |= region == OW_L
        elif d < 0:
            bad |= region == OW_R
        return bad

    def blocked(self, x0: int, y0: int, mask: np.ndarray, d: int) -> bool:
        r = self._clip(x0, y0, mask)
        if r is None:
            return False
        ax0, ay0, ax1, ay1, m = r
        return bool((m & self._forbidden(self.k[ay0:ay1, ax0:ax1], d)).any())

    def any_solid(self, x0: int, y0: int, mask: np.ndarray) -> bool:
        r = self._clip(x0, y0, mask)
        if r is None:
            return False
        ax0, ay0, ax1, ay1, m = r
        return bool((m & (self.k[ay0:ay1, ax0:ax1] != AIR)).any())

    def erase(self, x0: int, y0: int, mask: np.ndarray, d: int = 0) -> int:
        r = self._clip(x0, y0, mask)
        if r is None:
            return 0
        ax0, ay0, ax1, ay1, m = r
        region = self.k[ay0:ay1, ax0:ax1]
        hit = m & (region != AIR) & ~self._forbidden(region, d)
        n = int(hit.sum())
        if n:
            region[hit] = AIR
            self.e[ay0:ay1, ax0:ax1][hit] = False
            self._mark(ax0, ay0, ax1, ay1)
        return n

    def add_row(self, xa: int, xb: int, y: int, color: np.ndarray | None = None) -> None:
        if y < 0 or y >= self.h:
            return
        a, b = max(min(xa, xb), 0), min(max(xa, xb) + 1, self.w)
        if a >= b:
            return
        seg = self.k[y, a:b]
        air = seg == AIR
        seg[air] = DIRT
        col = self.brick if color is None else color
        shade = np.where((np.arange(a, b) % 6) == 0, 0.8, 1.0)[:, None]
        self.c[y, a:b][air] = (col[None, :] * shade[air]).astype(np.uint8)
        self._mark(a, y, b, y + 1)

    def _mark(self, x0: int, y0: int, x1: int, y1: int) -> None:
        if self.dirty is None:
            self.dirty = (x0, y0, x1, y1)
        else:
            a, b, c, d = self.dirty
            self.dirty = (min(a, x0), min(b, y0), max(c, x1), max(d, y1))


class FlipTerrain(Terrain):
    """La misma roca vista del revés, para quien cae hacia la luz.

    Comparte memoria con el terreno original (vistas de numpy con paso negativo):
    lo que se excava o se construye en un marco aparece en el otro.
    """

    def __init__(self, parent: Terrain):  # noqa: D107 — no llama a super a propósito
        self.parent = parent
        self.k = parent.k[::-1]
        self.c = parent.c[::-1]
        self.e = parent.e[::-1]
        self.brick = parent.brick
        self.h, self.w = parent.h, parent.w

    @property
    def dirty(self):
        return self.parent.dirty

    @dirty.setter
    def dirty(self, v) -> None:
        self.parent.dirty = v

    def _mark(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.parent._mark(x0, self.h - y1, x1, self.h - y0)


@dataclass(frozen=True)
class Theme:
    key: str
    dirt: tuple[tuple[int, int, int], ...]
    rim: tuple[int, int, int]
    brick: tuple[int, int, int]
    sky_top: tuple[int, int, int]
    sky_bot: tuple[int, int, int]
    ambient: tuple[int, int, int]  # luz ambiente (multiplica la escena)
    liquid: tuple[int, int, int]
    liquid_glow: bool
    veins: tuple[int, int, int] | None
    bg: str  # estilo de fondo
    motes: str  # partículas atmosféricas
    music: str
    candles: bool = True  # cada disciplinato lleva su vela


def _T(key, dirt, rim, brick, top, bot, amb, liq, glow, veins, bg, motes, music, candles=True) -> Theme:
    return Theme(key, dirt, rim, brick, top, bot, amb, liq, glow, veins, bg, motes, music, candles)


THEMES: dict[str, Theme] = {
    "firenze": _T("firenze", ((150, 112, 80), (128, 92, 66), (170, 132, 96)), (196, 168, 120), (226, 186, 128),
                  (24, 18, 30), (96, 58, 54), (120, 100, 110), (70, 88, 50), False, None, "firenze", "ash", "firenze"),
    "selva": _T("selva", ((52, 46, 40), (40, 36, 34), (66, 58, 48)), (70, 98, 54), (186, 150, 100),
                (4, 8, 16), (26, 34, 48), (86, 96, 122), (30, 40, 60), False, None, "selva", "fireflies", "inferno"),
    "inferno": _T("inferno", ((112, 58, 44), (86, 44, 36), (134, 72, 50)), (230, 120, 60), (226, 176, 112),
                  (16, 2, 4), (96, 22, 12), (128, 88, 84), (200, 70, 20), True, (255, 120, 30), "inferno", "embers", "inferno"),
    "acheronte": _T("acheronte", ((62, 58, 66), (48, 44, 54), (78, 72, 84)), (150, 140, 160), (210, 190, 150),
                    (6, 6, 14), (40, 34, 58), (92, 88, 116), (40, 60, 90), False, None, "inferno", "ash", "inferno"),
    "limbo": _T("limbo", ((120, 116, 104), (100, 96, 88), (140, 134, 120)), (200, 196, 170), (230, 210, 170),
                (30, 30, 40), (90, 90, 104), (150, 150, 160), (60, 70, 90), False, None, "limbo", "dust", "limbo", False),
    "tempesta": _T("tempesta", ((90, 60, 80), (70, 46, 66), (110, 74, 96)), (210, 120, 160), (226, 186, 150),
                   (14, 4, 20), (76, 26, 64), (118, 86, 118), (130, 40, 80), False, None, "tempesta", "wind", "inferno"),
    "fango": _T("fango", ((70, 60, 36), (56, 48, 28), (86, 74, 44)), (110, 110, 50), (200, 170, 110),
                (8, 10, 6), (44, 46, 24), (100, 100, 74), (64, 80, 30), False, None, "inferno", "rain", "inferno"),
    "dite": _T("dite", ((130, 48, 38), (104, 36, 30), (152, 62, 44)), (240, 120, 60), (230, 180, 120),
               (20, 2, 2), (120, 24, 8), (110, 60, 54), (220, 80, 20), True, (255, 90, 20), "dite", "embers", "inferno"),
    "sangue": _T("sangue", ((104, 50, 40), (84, 38, 32), (124, 62, 46)), (210, 90, 60), (220, 170, 120),
                 (16, 0, 0), (96, 10, 8), (104, 60, 58), (170, 16, 16), True, (220, 40, 30), "inferno", "embers", "inferno"),
    "malebolge": _T("malebolge", ((96, 82, 72), (76, 64, 58), (116, 100, 86)), (190, 150, 110), (220, 180, 130),
                    (10, 6, 6), (70, 40, 28), (100, 82, 80), (40, 30, 20), True, (255, 140, 40), "malebolge", "embers", "inferno"),
    "cocito": _T("cocito", ((150, 196, 226), (112, 162, 206), (186, 222, 244)), (240, 250, 255), (250, 236, 200),
                 (0, 6, 24), (16, 42, 80), (110, 140, 190), (120, 180, 230), False, None, "cocito", "snow", "cocito", False),
    "spiaggia": _T("spiaggia", ((206, 176, 132), (184, 150, 110), (224, 196, 150)), (160, 190, 120), (240, 210, 160),
                   (70, 120, 180), (230, 190, 170), (255, 245, 235), (60, 120, 190), False, None, "purgatorio", "dust", "purgatorio", False),
    "monte": _T("monte", ((196, 160, 140), (170, 136, 120), (214, 182, 160)), (150, 170, 110), (240, 210, 170),
                (90, 130, 200), (240, 200, 180), (255, 244, 236), (60, 110, 180), False, None, "purgatorio", "dust", "purgatorio", False),
    "rogo": _T("rogo", ((150, 110, 90), (124, 88, 72), (170, 130, 104)), (220, 150, 90), (240, 200, 150),
               (40, 16, 20), (190, 90, 50), (190, 150, 140), (240, 110, 30), True, (255, 150, 60), "purgatorio", "embers", "purgatorio"),
    "eden": _T("eden", ((120, 150, 80), (100, 130, 66), (140, 170, 96)), (170, 220, 110), (240, 220, 170),
               (110, 170, 220), (240, 230, 190), (255, 255, 245), (80, 160, 220), False, None, "eden", "petals", "purgatorio", False),
    "paradiso": _T("paradiso", ((222, 190, 110), (200, 166, 90), (240, 210, 140)), (255, 250, 220), (255, 240, 200),
                   (250, 240, 214), (255, 252, 240), (255, 255, 255), (255, 250, 220), True, (255, 240, 170), "paradiso", "gold", "paradiso", False),
}


def fbm(h: int, w: int, rng: np.random.Generator, base: int = 24, octaves: int = 4) -> np.ndarray:
    """Ruido de valor fractal en [0, 1], suave y barato."""
    out = np.zeros((h, w))
    amp, tot, cell = 1.0, 0.0, base
    for _ in range(octaves):
        gh, gw = h // cell + 3, w // cell + 3
        g = rng.random((gh, gw))
        yy = np.arange(h) / cell
        xx = np.arange(w) / cell
        y0, x0 = yy.astype(int), xx.astype(int)
        fy, fx = yy - y0, xx - x0
        fy = fy * fy * (3 - 2 * fy)
        fx = fx * fx * (3 - 2 * fx)
        a = g[y0][:, x0]
        b = g[y0][:, x0 + 1]
        c = g[y0 + 1][:, x0]
        d = g[y0 + 1][:, x0 + 1]
        top = a + (b - a) * fx[None, :]
        bot = c + (d - c) * fx[None, :]
        out += amp * (top + (bot - top) * fy[:, None])
        tot += amp
        amp *= 0.5
        cell = max(2, cell // 2)
    return out / tot


def colorize(kinds: np.ndarray, theme: Theme, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Textura base del terreno: estratos, grano y vetas. El sombreado va aparte."""
    h, w = kinds.shape
    pal = np.array(theme.dirt, dtype=float)
    n1 = fbm(h, w, rng, 32, 4)
    n2 = fbm(h, w, rng, 6, 2)
    yy, xx = np.mgrid[0:h, 0:w]
    strata = np.sin(yy * 0.32 + n1 * 9.0) * 0.5 + 0.5
    idx = np.minimum((strata * 0.6 + n2 * 0.4) * len(pal), len(pal) - 1).astype(int)
    col = pal[idx]
    grain = 0.86 + 0.28 * rng.random((h, w))
    col *= grain[..., None] * (0.9 + 0.2 * n2[..., None])
    emis = np.zeros((h, w), dtype=bool)
    if theme.veins is not None:
        ridge = np.abs(fbm(h, w, rng, 28, 3) - 0.5)
        zone = fbm(h, w, rng, 64, 2)
        emis = (ridge < 0.009) & (kinds == DIRT) & (zone > 0.6)
        col[emis] = np.array(theme.veins, dtype=float) * (0.55 + 0.25 * grain[emis])[:, None]
    # pietra serena: sillares florentinos
    bx, by = xx % 16, yy % 8
    off = (yy // 8) % 2 * 8
    bx = (xx + off) % 16
    sc = np.full((h, w), 128.0) + n2 * 30
    sc[(bx == 15) | (by == 7)] = 70
    sc[(bx == 0) | (by == 0)] = 172
    steel = kinds == STEEL
    stone = np.stack([sc * 0.92, sc * 0.98, sc * 1.06], axis=-1)
    col[steel] = stone[steel]
    col[(kinds == OW_R) & (((xx - np.abs(by - 4)) % 8) < 2)] *= 1.6
    col[(kinds == OW_L) & (((xx + np.abs(by - 4)) % 8) < 2)] *= 1.6
    return col.clip(0, 255).astype(np.uint8), emis


def _box(a: np.ndarray, r: int) -> np.ndarray:
    """Desenfoque de caja (media en una ventana de lado 2r+1) con sumas acumuladas."""
    p = np.pad(a, r + 1, mode="edge").astype(np.float32)
    c = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s[: a.shape[0], : a.shape[1]] / (k * k)


def shade_region(kinds: np.ndarray, base: np.ndarray, rim: tuple[int, int, int], floor: float = 0.42) -> tuple[np.ndarray, np.ndarray]:
    """Claroscuro del terreno: borde iluminado, interior hundido en sombra.

    Devuelve (rgb, alfa). Es la luz de Caravaggio aplicada a la roca: lo que
    toca el aire brilla; lo profundo se apaga.
    """
    solid = kinds != AIR
    air = (~solid).astype(np.float32)
    near = _box(air, 3)  # 0 en el corazón de la roca, ~0.5 en el borde
    depth = np.clip(near * 2.6, 0, 1)
    light = floor + (1 - floor) * depth
    col = base.astype(np.float32) * light[..., None]
    top = solid.copy()
    top[1:] &= ~solid[:-1]
    top2 = np.zeros_like(top)
    top2[1:] = top[:-1] & solid[1:]
    bottom = solid.copy()
    bottom[:-1] &= ~solid[1:]
    rimc = np.array(rim, dtype=np.float32)
    col[top] = col[top] * 0.25 + rimc * 0.85
    col[top2] = col[top2] * 0.55 + rimc * 0.4
    col[bottom] *= 0.55
    alpha = np.where(solid, 255, 0).astype(np.uint8)
    return col.clip(0, 255).astype(np.uint8), alpha


# ═══════════════════════════════════════════════════════════════════════════
# 4. LA COMMEDIA: 101 NIVELES (0 = Proemio, 1–34 Inferno, 35–67 Purgatorio,
#    68–100 Paradiso). Cada uno se genera por segmentos con solución conocida.
# ═══════════════════════════════════════════════════════════════════════════
# Leyenda del mapa (cada carácter = 8×8 px):
#   .  aire    #  roca    S  pietra serena (indestructible)    < >  sentido único
#   ~  líquido letal (Aqueronte, Estigia, Flegetonte, pez, agua del Cocito)
#   ^  fuego   %  fuego que purifica (Purgatorio VII)   |  centro de la Tierra (la gravedad se invierte)
#   E  pila bautismal (entrada)    X  salida
#   U  entrada y  x  salida «del revés»: para quien cae hacia la luz


@dataclass(frozen=True, slots=True)
class Rule:
    """Paso de una solución de referencia (demo, validador y calibración)."""

    skill: Skill | None
    x: int | None = None
    win: int = 1
    dir: int = 0
    state: St | None = None
    y: tuple[int, int] = (-999, 9999)
    n: int = 1
    delay: int = 0
    par: bool = False
    track: int = 0
    rr: int | None = None
    palla: str | None = None
    guard: int = -1


@dataclass(frozen=True, slots=True)
class GuardSpec:
    kind: str
    x: int
    y: int
    inv: bool = False


@dataclass(frozen=True, slots=True)
class PickSpec:
    kind: str  # palla roja, «giglio», «pagina» o «giunco»
    x: int
    y: int
    artist: str = ""
    need: bool = False  # la exige un guardián de este nivel
    inv: bool = False  # en coordenadas del revés


@dataclass
class Level:
    id: int
    name: str
    place: str
    canto: str
    cantica: str
    giornata: int
    difficulty: str
    total: int
    to_save: int
    rr: int
    minutes: int
    skills: dict[Skill, int]
    theme: str
    map: tuple[str, ...]
    solution: tuple[Rule, ...]
    pickups: tuple[PickSpec, ...] = ()
    guards: tuple[GuardSpec, ...] = ()
    vents: tuple[tuple[int, int, int], ...] = ()  # (x0, x1, y)
    boulders: tuple[tuple[int, int, int], ...] = ()  # (xa, xb, y)
    mods: frozenset[str] = frozenset()
    moria: tuple[int, bool] = (0, False)
    fire: tuple[int, float] | None = None
    sermon: str = ""
    hint: str = ""
    sky: str = ""
    special: str = ""
    guide: str = "Virgilio"
    target_pct: int = 50
    base: int = -1  # nivel de la Commedia del que deriva (desafíos, infinito)
    phantoms: tuple[tuple[int, int, int, int, str, bool], ...] = ()  # (x0, y0, x1, y1, tipo, del revés)
    boats: tuple[tuple[int, int, int], ...] = ()  # (x0, x1, y) del tramo de fango
    liquid: tuple[int, int, int] | None = None
    trees: tuple[tuple[int, int], ...] = ()
    sabios: tuple[tuple[int, int, str, str], ...] = ()


CANTICHE = {"proemio": "Proemio", "inferno": "Inferno", "purgatorio": "Purgatorio", "paradiso": "Paradiso"}
SLOTS = {"proemio": 8, "inferno": 8, "purgatorio": 7, "paradiso": 6}
SHIELD_OWNER = {"proemio": "Cosimo il Vecchio", "inferno": "Cosimo il Vecchio", "purgatorio": "Piero il Gottoso",
                "paradiso": "Lorenzo il Magnifico"}
DIFFICULTIES = ["Penitente", "Pellegrino", "Disciplinato", "Dannato"]

GUARDS = {
    # tipo: (nombre, qué palla lo aplaca, abre solo tras N s [0 = nunca], frase)
    "lupa": ("La lupa", "arancia", 0, "«...una lupa, che di tutte brame / sembiava carca». Distráela."),
    "lonza": ("La lonza", None, 0, "«…una lonza leggera e presta molto». Por aquí no se pasa."),
    "leone": ("Il leone", None, 0, "«…con la test'alta e con rabbiosa fame». Tampoco por aquí: «a te convien tenere altro viaggio»."),
    "caronte": ("Caronte", "cambio", 0, "«Caron dimonio, con occhi di bragia». Paga el óbolo."),
    "minosse": ("Minosse", "cambio", 0, "Minos juzga y ciñe la cola. Se deja convencer."),
    "cerbero": ("Cerbero", "arancia", 0, "Tres bocas. Virgilio le echó tierra; tú, una naranja."),
    "pluto": ("Pluto", "cambio", 0, "«Pape Satàn, pape Satàn aleppe!» Habla en monedas."),
    "flegias": ("Flegias", "cambio", 0, "El barquero de la Estigia cobra el pasaje."),
    "furie": ("Le Furie", None, 40, "Las Furias cierran Dite. Solo un mensajero del cielo abre."),
    "centauri": ("I Centauri", "arancia", 0, "Quirón y sus arqueros. Un señuelo los aparta."),
    "arpie": ("Le Arpie", "arancia", 0, "Las harpías anidan en el bosque de los suicidas."),
    "catone": ("Catone", "giunco", 0, "Catón exige el junco: humildad antes de subir."),
    "attesa": ("Gli Scomunicati", None, 30, "Los excomulgados esperan. Esperar también es trabajo."),
    "angelo": ("L'Angelo portiere", None, 15, "El ángel abre a quien espera. La gracia no se compra."),
    "pietro": ("San Pietro", None, 20, "Examen de fe. Espera la pregunta."),
    "anteo": ("Anteo", None, 0, "Anteo, sin cadenas: «mettine giù». Llega a su mano y te baja al fondo."),
    "giacomo": ("San Giacomo", None, 20, "Examen de esperanza."),
    "giovanni": ("San Giovanni", None, 20, "Examen de caridad."),
}

PALLE_INFO = {
    "cambio": ("Palla del Cambio", "Bezante del Arte del Cambio. Paga el peaje de un guardián.", (200, 34, 30)),
    "medicinale": ("Palla Medicinale", "Médici, médicos: cura la Moria en un radio y da inmunidad.", (214, 60, 50)),
    "arancia": ("Palla d'Arancia", "Naranja amarga: señuelo y correa. Se lanza con un clic.", (236, 120, 30)),
    "mecenate": ("Palla del Mecenate", "Invoca a un artista: Brunelleschi, Botticelli o Caravaggio.", (190, 30, 70)),
    "congiura": ("Palla della Congiura", "26 de abril de 1478. Aplaca a cualquier guardián o intercambia dos almas.", (120, 10, 14)),
    "giglio": ("Palla del Giglio", "Luis XI, 1465. Gracia prestada: amortigua una caída mortal por alma.", (40, 70, 200)),
}
RED_PALLE = ("cambio", "medicinale", "arancia", "mecenate", "congiura")
ARTISTS = ("brunelleschi", "botticelli", "caravaggio")


def place_info(i: int) -> dict:
    """Topografía de la Commedia: lugar, canto, tema, guardianes, reglas."""
    P = dict(mods=set(), guards=[], extra=[], palette=None, moria=(0, False), special="", sky="", guide="Virgilio")
    if i == 0:
        P.update(place="Florencia, 1348", canto="Proemio", theme="firenze", name="La città dolente",
                 palette=["wall", "dig"], moria=(2, True), special="child")
    elif i == 1:
        P.update(place="Selva oscura", canto="Inf. I", theme="selva", name="Nel mezzo del cammin", special="selva",
                 palette=["wall"])
    elif i <= 3:
        P.update(place="Antinferno", canto="Inf. III", theme="acheronte", name="Gli ignavi", palette=["wall", "dig", "drop_mine"],
                 mods={"banner"})
    elif i == 4:
        P.update(place="Acheronte", canto="Inf. III", theme="acheronte", name="Caron dimonio", guards=["caronte"],
                 palette=["pit", "wall"])
    elif i == 5:
        P.update(place="I · Limbo", canto="Inf. IV", theme="limbo", name="Il nobile castello", palette=["wall", "dig"],
                 mods={"nodeath"}, special="limbo")
    elif i == 6:
        P.update(place="II · Lussuriosi", canto="Inf. V", theme="tempesta", name="La bufera infernal", guards=["minosse"],
                 palette=["drop_float", "wall"], mods={"wind"})
    elif i <= 8:
        P.update(place="III · Golosi", canto="Inf. VI", theme="fango", name="Cerbero, fiera crudele",
                 guards=["cerbero"] if i == 7 else [], palette=["wall", "dig", "pit"])
    elif i <= 10:
        P.update(place="IV · Avari e prodighi", canto="Inf. VII", theme="malebolge", name="Pape Satàn",
                 guards=["pluto"] if i == 9 else [], palette=["wall", "drop_mine", "dig"], extra=["boulders"])
    elif i <= 12:
        P.update(place="V · Iracondi", canto="Inf. VII–VIII", theme="fango", name="La palude Stigia",
                 guards=["flegias"] if i == 11 else [], palette=["boat", "wall", "drop_float"])
    elif i <= 14:
        P.update(place="Città di Dite", canto="Inf. VIII–IX", theme="dite", name="Le mura di Dite",
                 guards=["furie"] if i == 13 else [], palette=["wall", "dig", "drop_mine"])
    elif i <= 16:
        P.update(place="VI · Eretici", canto="Inf. IX–XI", theme="dite", name="Gli avelli infuocati",
                 palette=["wall", "drop_float", "dig"], extra=["vents"], special="bulla" if i == 16 else "")
    elif i <= 18:
        P.update(place="VII · Flegetonte", canto="Inf. XII", theme="sangue", name="Il fiume di sangue",
                 guards=["centauri"] if i == 17 else [], palette=["pit", "wall", "drop_mine"])
    elif i <= 20:
        P.update(place="VII · Selva dei suicidi", canto="Inf. XIII", theme="selva", name="Pier della Vigna",
                 guards=["arpie"] if i == 19 else [], palette=["wall", "dig", "drop_float"], mods={"suicidi"})
    elif i == 21:
        P.update(place="VII · Sabbione ardente", canto="Inf. XIV–XVI", theme="inferno", name="La pioggia di fuoco",
                 palette=["wall", "pit", "drop_mine"], extra=["mecenate"], mods={"firerain"})
    elif i == 22:
        P.update(place="Discesa di Gerione", canto="Inf. XVII", theme="inferno", name="Gerione",
                 palette=["drop_float", "drop_float"])
    elif i <= 31:
        bolge = [
            ("Adulatori", "Inf. XVIII", {"sterco"}), ("Simoniaci", "Inf. XIX", {"vents"}), ("Indovini", "Inf. XX", {"backwards"}),
            ("Barattieri", "Inf. XXI–XXII", {"pece"}), ("Ipocriti", "Inf. XXIII", {"slowskills", "piombo"}),
            ("Ladri", "Inf. XXIV–XXV", {"snakes"}), ("Consiglieri fraudolenti", "Inf. XXVI–XXVII", {"flames"}),
            ("Seminatori di discordia", "Inf. XXVIII", set()), ("Falsari", "Inf. XXIX–XXX", {"moria2"}),
        ]
        nm, canto, m = bolge[i - 23]
        P.update(place=f"VIII · Malebolge — {nm}", canto=canto, theme="malebolge", name=nm,
                 palette=["wall", "pit", "drop_mine", "dig", "drop_float"], mods={x for x in m if x != "vents"},
                 extra=["vents"] if "vents" in m else [], moria=(3, False) if "moria2" in m else (0, False),
                 special="flame" if nm == "Consiglieri fraudolenti" else "")
    elif i == 32:
        P.update(place="Pozzo dei Giganti", canto="Inf. XXXI", theme="malebolge", name="Anteo",
                 palette=["drop_mine", "drop_anteo"])
    elif i == 33:
        P.update(place="IX · Cocito — Antenora", canto="Inf. XXXII–XXXIII", theme="cocito", name="La ghiaccia",
                 palette=["pit", "wall", "dig"], special="toll", mods={"ice"})
    elif i == 34:
        P.update(place="Lucifero", canto="Inf. XXXIV", theme="cocito", name="Lo 'mperador del doloroso regno",
                 palette=["wall"], special="lucifero", mods={"ice"})
    elif i <= 36:
        P.update(place="Spiaggia di Catone", canto="Purg. I–II", theme="spiaggia", name="Libertà va cercando",
                 guards=["catone"] if i == 35 else [], palette=["ascend", "wall"])
    elif i <= 40:
        names = {37: ("Scomunicati", ["attesa"]), 38: ("Negligenti", []), 39: ("Morti violenti", []),
                 40: ("Valletta dei principi", [])}
        nm, g = names[i]
        P.update(place=f"Antepurgatorio — {nm}", canto="Purg. III–VIII", theme="monte", name=nm, guards=g,
                 palette=["ascend", "wall", "climb_up"], mods={"night"},
                 special="caravaggio" if i == 39 else "", extra=["mecenate"] if i == 39 else [])
    elif i == 41:
        P.update(place="Porta di San Pietro", canto="Purg. IX", theme="monte", name="Le sette P",
                 guards=["angelo"], palette=["ascend", "wall"], extra=["cambio"])
    elif i <= 45:
        P.update(place="I · Superbi", canto="Purg. X–XII", theme="monte", name="Sotto il peso", palette=["ascend", "climb_up", "wall"],
                 mods={"night", "stones"}, sky="superbi")
    elif i <= 48:
        P.update(place="II · Invidiosi", canto="Purg. XIII–XV", theme="monte", name="Gli occhi cuciti",
                 palette=["ascend", "wall", "climb_up"], mods={"night", "dark", "ghost"})
    elif i <= 51:
        P.update(place="III · Iracondi", canto="Purg. XV–XVII", theme="monte", name="Il fumo", palette=["ascend", "wall", "climb_up"],
                 mods={"smoke", "ghost"})
    elif i <= 54:
        P.update(place="IV · Accidiosi", canto="Purg. XVII–XVIII", theme="monte", name="Correre senza posa",
                 palette=["ascend", "climb_up", "wall"], mods={"fast"})
    elif i <= 57:
        P.update(place="V · Avari", canto="Purg. XIX–XXI", theme="monte", name="Adhaesit pavimento",
                 palette=["ascend", "wall", "climb_up"], mods={"night", "return"}, moria=(1, True))
    elif i <= 60:
        P.update(place="VI · Golosi", canto="Purg. XXII–XXIV", theme="monte", name="L'albero dei frutti",
                 palette=["ascend", "climb_up", "wall"], mods={"night", "trees"})
    elif i <= 63:
        P.update(place="VII · Lussuriosi", canto="Purg. XXV–XXVII", theme="rogo", name="Il muro di fuoco",
                 palette=["ascend", "wall"], extra=["purge"], moria=(2, False))
    elif i <= 65:
        P.update(place="Rogo delle Vanità", canto="Firenze, 7 feb. 1497", theme="rogo", name="Il falò",
                 palette=["ascend", "climb_up", "ascend"], special="rogo")
    elif i <= 67:
        P.update(place="Paradiso terrestre", canto="Purg. XXVIII–XXXIII", theme="eden", name="Letè ed Eunoè",
                 palette=["ascend", "wall"], special="leteo", guide="Matelda" if i == 66 else "Beatrice")
    else:
        heavens = [
            (70, "Luna", "Par. II–V", "luna", "Voti mancati"), (73, "Mercurio", "Par. V–VII", "mercurio", "La gloria"),
            (76, "Venere", "Par. VIII–IX", "venere", "Amanti"), (79, "Sole", "Par. X–XIV", "sole", "Le due corone"),
            (82, "Marte", "Par. XIV–XVIII", "marte", "La croce"), (85, "Giove", "Par. XVIII–XX", "giove", "L'aquila"),
            (88, "Saturno", "Par. XXI–XXII", "saturno", "La scala d'oro"),
            (91, "Stelle fisse", "Par. XXIII–XXVII", "stelle", "L'esame"),
            (94, "Primum Mobile", "Par. XXVII–XXIX", "primum", "I cori angelici"),
            (99, "Empireo", "Par. XXX–XXXII", "empireo", "La candida rosa"),
            (100, "La visione", "Par. XXXIII", "visione", "L'amor che move il sole"),
        ]
        for hi, nm, canto, sky, title in heavens:
            if i <= hi:
                break
        guide = "San Bernardo" if i >= 97 else "Beatrice"
        g = []
        if sky == "stelle":
            g = [{89: "pietro", 90: "giacomo", 91: "giovanni"}[i]]
        P.update(place=f"Cielo di {nm}" if sky not in ("empireo", "visione", "primum") else nm, canto=canto, theme="paradiso",
                 name=title, palette=["drop_float", "wall", "drop_mine"], sky=sky, guide=guide, guards=g, mods={"lux"})
        if sky == "luna":
            P["mods"] = {"lux", "blink"}
            P["palette"] = ["drop_float", "wall"]
        if sky == "venere":
            P["mods"] = {"lux", "venus"}
        if sky == "marte":
            P["extra"] = ["croce"]
        if sky == "giove":
            P["extra"] = ["lettere"]
        if sky == "saturno":
            P["mods"] = {"lux", "silence"}
            P["palette"] = ["wall", "climb"]
        if sky == "mercurio":
            P["extra"] = ["temptation"]
        if sky == "primum":
            P["special"] = "primum"
        if sky == "visione":
            P["special"] = "final"
            P["mods"] = set()
    return P


def cantica_of(i: int) -> str:
    return "proemio" if i == 0 else "inferno" if i <= 34 else "purgatorio" if i <= 67 else "paradiso"


def giornata_of(i: int) -> int:
    """Giornata del Decamerón (0 = I … 9 = X). Diez niveles por jornada."""
    return 0 if i == 0 else min(9, (i - 1) // 10)


class MapBuilder:
    """Construye el mapa columna a columna y acumula la solución."""

    def __init__(self, fy: int, mods: set[str]):
        self.cols: list[list[str]] = []
        self.fy = fy
        self.mods = mods
        self.rules: list[Rule] = []
        self.need: dict[Skill, int] = {}
        self.pickups: list[PickSpec] = []
        self.guards: list[GuardSpec] = []
        self.vents: list[tuple[int, int, int]] = []
        self.boulders: list[tuple[int, int, int]] = []
        self.boats: list[tuple[int, int, int]] = []
        self.floaters = self.climbers = False
        self.flats: list[tuple[int, int]] = []  # (x, y) de suelo libre para coleccionables
        self.entrance: tuple[int, int] | None = None
        self.exit: tuple[int, int] | None = None
        self.descent = 0
        self.win = 1 if "fast" in mods else 0
        self.brick_ticks = BRICK_TICKS * (2 if "slowskills" in mods else 1)

    @property
    def c(self) -> int:
        return len(self.cols)

    def _col(self, floor: int | None = None) -> list[str]:
        col = ["."] * ROWS
        f = self.fy if floor is None else floor
        for r in range(f, ROWS):
            col[r] = "#"
        self.cols.append(col)
        return col

    def _need(self, s: Skill, n: int = 1) -> None:
        self.need[s] = self.need.get(s, 0) + n

    def flat(self, n: int, spot: bool = True) -> None:
        for k in range(n):
            self._col()
            if spot and 1 <= k < n - 1:
                self.flats.append(((self.c - 1) * CELL + 4, self.fy * CELL))

    # ── segmentos ────────────────────────────────────────────────────────
    def start(self) -> None:
        self.flat(3, spot=False)
        col = self._col()
        col[self.fy - 6] = "E"
        self.flat(6)

    def finish(self) -> None:
        self.flat(3, spot=False)
        col = self._col()
        col[self.fy - 1] = "X"
        self.flat(5, spot=False)

    def wall(self, h: int, w: int) -> None:
        self.flat(6)
        x = self.c * CELL
        for _ in range(w):
            col = self._col()
            for r in range(self.fy - h, self.fy):
                col[r] = "#"
        self.rules.append(Rule(Skill.PIAGNONE, x=x - 4, dir=1))
        self._need(Skill.PIAGNONE)
        self.flat(3)

    def pit(self) -> None:
        self.flat(6)
        g = self.c * CELL
        for _ in range(3):
            col = self._col(self.fy + 3)
            col[self.fy + 1] = col[self.fy + 2] = "~"
        bt = self.brick_ticks
        self.rules += [
            Rule(Skill.CAPOMASTRO, x=g - 1, win=self.win, dir=1),
            Rule(Skill.FLAGELLANTE, x=g - 26, win=4, dir=1, state=St.WALK),
            Rule(Skill.BUBBONE, state=St.BLOCK, x=g - 26, win=8, delay=BRICKS * bt + 12),
        ]
        for s in (Skill.CAPOMASTRO, Skill.FLAGELLANTE, Skill.BUBBONE):
            self._need(s)
        self.flat(5)

    def drop_float(self, d: int) -> None:
        self.flat(4)
        self.fy += d
        self.descent += d
        self.floaters = True
        self.flat(6)

    def drop_mine(self, d: int) -> None:
        lead = (2 * (d * CELL - 48)) // CELL + 3
        start = self.c
        for k in range(lead):
            col = self._col()
            if k >= lead - 3:
                for r in range(self.fy - 3, self.fy):
                    col[r] = "#"
        xc = (start + lead) * CELL
        self.rules.append(Rule(Skill.MINATORE, x=xc - 2 * (d * CELL - 48), dir=1, win=self.win))
        self._need(Skill.MINATORE)
        self.fy += d
        self.descent += d
        self.flat(6)

    def boat(self) -> None:
        """La palude Stigia: ocho bloques de fango y la barca de Flegias."""
        self.flat(6)
        g = self.c * CELL
        for _ in range(8):
            col = self._col(self.fy + 3)
            col[self.fy + 1] = col[self.fy + 2] = "~"
        self.boats.append((g, g + 8 * CELL, self.fy * CELL))
        self.flat(5)

    def selva(self) -> None:
        """Inf. I: tres caminos. Arriba esperan la lonza y el león; abajo, la loba."""
        self.flat(4)
        s = self.c
        fy = self.fy
        for _ in range(11):
            col = self._col(fy + 6)
            for r in range(fy, fy + 3):
                col[r] = "#"
        self.guards.append(GuardSpec("lonza", (s + 6) * CELL + 4, fy * CELL))
        self.guards.append(GuardSpec("leone", (s + 9) * CELL + 4, fy * CELL))
        self.rules.append(Rule(Skill.BECCHINO, x=(s + 2) * CELL + 4, win=self.win))
        self._need(Skill.BECCHINO)
        self.fy += 6
        self.descent += 6
        self.flat(3)

    def drop_anteo(self, d: int) -> None:
        """El pozo de los gigantes: Anteo recoge a quien llega al borde y lo deja abajo."""
        self.flat(4)
        self.guards.append(GuardSpec("anteo", self.c * CELL - 2, self.fy * CELL))
        self.fy += d
        self.descent += d
        self.flat(7)

    def dig(self) -> None:
        self.flat(4)
        s = self.c
        fy = self.fy
        for k in range(8):
            col = self._col(fy + 6)
            for r in range(fy, fy + 3):
                col[r] = "#"
            if k >= 6:
                for r in range(fy - 5, fy + 3):
                    col[r] = "S"
        self.rules.append(Rule(Skill.BECCHINO, x=(s + 3) * CELL + 4, win=self.win))
        self._need(Skill.BECCHINO)
        self.fy += 6
        self.descent += 6
        self.flat(6)

    def climb(self, h: int) -> None:
        self.flat(6)
        for _ in range(3):
            col = self._col()
            for r in range(self.fy - h, self.fy):
                col[r] = "#"
        self.climbers = True
        self.flat(6)

    def climb_up(self, h: int) -> None:
        self.flat(6)
        self.fy -= h
        self.climbers = True
        self.flat(6)

    def ascend(self) -> None:
        self.flat(5)
        face = self.c * CELL
        self.rules.append(Rule(Skill.CAPOMASTRO, x=face - 28, win=self.win, dir=1))
        self._need(Skill.CAPOMASTRO)
        self.fy -= 2
        self.flat(5)

    def guardian(self, kind: str) -> None:
        name, needs, auto, _ = GUARDS[kind]
        self.flat(2, spot=False)
        if needs:
            self.pickups.append(PickSpec(needs, self.c * CELL + 4, self.fy * CELL, need=True))
        self.flat(9, spot=False)
        gi = len(self.guards)
        gcol = self.c
        self.guards.append(GuardSpec(kind, self.c * CELL + 4, self.fy * CELL))
        self.flat(6 if kind == "caronte" else 5, spot=False)
        if kind == "caronte":
            # el rodeo durísimo: una pasarela sobre Caronte; solo se llega con escalera
            for k in range(gcol - 4, gcol + 6):
                self.cols[k][self.fy - 2] = "_"
        if needs and needs != "giunco":
            self.rules.append(Rule(None, palla=needs, guard=gi))

    def vent_row(self, n: int) -> None:
        self.flat(3)
        for _ in range(n):
            x0 = self.c * CELL
            self.flat(2, spot=False)
            self.vents.append((x0 + 2, x0 + 14, self.fy * CELL))
            self.flat(3, spot=False)

    def boulder_run(self) -> None:
        self.flat(2)
        xa = self.c * CELL
        self.flat(9, spot=False)
        self.boulders.append((xa + 8, self.c * CELL - 8, self.fy * CELL))
        self.flat(2)

    def purge(self) -> None:
        self.flat(4)
        for _ in range(4):
            col = self._col()
            for r in range(self.fy - 5, self.fy):
                col[r] = "%"
        self.flat(4)

    def rows(self, stalactites: random.Random | None = None) -> tuple[str, ...]:
        while self.c < VIEW_W // CELL:
            self._col()
        if stalactites is not None:
            # bóveda del embudo: estalactitas que nunca bajan hasta el camino
            top = min(next((r for r in range(ROWS) if col[r] != "."), ROWS) for col in self.cols)
            room = max(0, top - 6)
            depth = 0
            for col in self.cols:
                depth = max(0, min(room, depth + stalactites.choice((-1, 0, 0, 1))))
                if depth and stalactites.random() < 0.9:
                    for r in range(depth):
                        if col[r] == ".":
                            col[r] = "#"
        return tuple("".join(col[r] for col in self.cols) for r in range(ROWS))


SERMONS = [
    "Treinta y tres días y medio, hermanos. Ni uno más. Al cumplirse, todos salvos.",
    "El látigo limpia lo que el agua no alcanza. Caminad y azotaos.",
    "No miréis abajo. Quien mira abajo duda, y quien duda cae.",
    "La peste es castigo; la procesión, remedio. Seguid al de delante.",
    "Obedeced al Maestro como el Maestro obedece al Cielo.",
    "Si uno cae, no os detengáis: la fila no espera a nadie.",
    "Los médicos venden píldoras; nosotros, la gracia. Y gratis, casi.",
    "Dicen que el Papa nos condena. El Papa está lejos. El látigo, aquí.",
    "Contad los días, no los muertos.",
    "Quien deja de azotarse, deja de salvarse.",
    "La montaña es alta, pero el látigo empuja.",
    "Más luz, decís. La luz ciega. Bajad la cabeza.",
]

HINTS = {
    "wall": "Un muro de roca blanda: un Piagnone abre paso a golpes.",
    "pit": "Un foso letal: un Capomastro tiende el puente, un Flagellante frena a los demás… y luego, el Bubbone.",
    "drop_float": "Una caída de más de ocho bloques: sin Gerione, nadie la sobrevive.",
    "drop_mine": "Un acantilado: el Minatore baja en diagonal y deja la caída en algo soportable.",
    "dig": "Una losa sobre una cripta: el Becchino cava hacia abajo. La pietra serena no se rompe.",
    "climb": "Un muro alto sin otra salida: Pellegrini, todos.",
    "climb_up": "Una cornisa vertical: solo el bordón del Pellegrino sube por ella.",
    "ascend": "Una cornisa a dos bloques: doce ladrillos de Capomastro, empezando a tiempo.",
    "boat": "La palude Stigia: la barca de Flegias lleva a unos pocos cada vez. Sin óbolo no zarpa.",
    "selva": "Tres caminos: la lonza y el león cierran el de arriba. Virgilio: «a te convien tenere altro viaggio».",
    "drop_anteo": "El pozo de los gigantes: Anteo baja a quien llega al borde. No hace falta oficio, solo paciencia.",
}

GUIDE_LINES = {
    "Virgilio": [
        "«Or va, ch'un sol volere è d'ambedue.» Yo te guío; tú decides.",
        "No mires sus cruces: mira el terreno. El Infierno se aprende como un oficio.",
        "Cada castigo es la forma de su pecado. Aprende la forma y sabrás el camino.",
        "Ellos caminan porque camina el de delante. Tú no tienes esa excusa.",
        "Lo que gastes aquí lo pagarás arriba. El Infierno no cobra: anota.",
    ],
    "Matelda": ["El Leteo borra la memoria del pecado. Si el Peso es poco, el río se lo lleva."],
    "Beatrice": [
        "¿Por qué miras tus pies, si la luz está arriba?",
        "¿Qué pesa más: lo que llevas o lo que temes soltar?",
        "¿Quién te dijo que el látigo era el camino?",
        "¿Ves cómo la luz elige? ¿Y si te eligiera a ti?",
    ],
    "San Bernardo": ["Mira la rosa. Lo que queda por hacer es soltar."],
}


def build_level(i: int, seed: int | None = None) -> Level:
    P = place_info(i)
    rng = random.Random(1348 * 31 + i * 977 if seed is None else seed)
    cantica = cantica_of(i)
    mods = set(P["mods"])
    if cantica == "paradiso" and P["special"] != "final":
        mods.add("paradiso")
    span = {"proemio": (0, 1), "inferno": (1, 34), "purgatorio": (35, 67), "paradiso": (68, 100)}[cantica]
    prog = (i - span[0]) / max(1, span[1] - span[0])
    tier = min(3, int(prog * 4))
    descending = cantica in ("proemio", "inferno", "paradiso")
    total = 100  # cien almas blancas con una cruz roja al pecho, en cada nivel
    if P["special"] == "final":
        mb = MapBuilder(30, mods)
        mb.start()
        mb.flat(40)
        mb.finish()
        return _assemble(i, P, mb, mods, total, cantica, tier, rr=60)

    n_obst = 2 + min(4, round(prog * 4 + rng.random() * 0.9)) if i else 3
    palette = list(P["palette"])
    seq: list[str] = []
    if i == 0:
        seq = ["wall", "dig", "wall"]
    else:
        pits = 0
        for k in range(n_obst):
            choice = palette[k] if k < len(palette) and k < 2 else rng.choice(palette)
            if choice in ("pit", "boat"):
                if pits or "fast" in mods:
                    choice = "wall"
                pits += 1 if choice in ("pit", "boat") else 0
            seq.append(choice)
    if P["special"] == "lucifero":
        return _lucifero(i, P, mods, total, tier, rng)
    # presupuesto vertical
    drops = {"drop_float": 10, "drop_mine": 9, "dig": 6, "drop_anteo": 10}
    rises = {"ascend": 2, "climb_up": 5}
    if descending:
        budget = 24
        kept = []
        for s in seq:
            dv = drops.get(s, 0)
            if dv and budget - dv < 0:
                s = "wall"
                dv = 0
            budget -= dv
            kept.append(s)
        seq = kept
        fy = max(8, 33 - (24 - budget))
    else:
        budget = 23
        kept = []
        for s in seq:
            dv = rises.get(s, 0)
            if dv and budget - dv < 0:
                s = "wall"
                dv = 0
            budget -= dv
            kept.append(s)
        seq = kept
        fy = 33
    if P["special"] == "selva":
        seq = ["selva"]
        fy = 16
    mb = MapBuilder(fy, mods)
    mb.start()
    guards = list(P["guards"])
    if P["special"] == "selva":
        mb.selva()
        mb.guardian("lupa")
        seq = []
    if P["special"] == "rogo":
        mb.flat(4)
    if cantica == "purgatorio" and "catone" in guards:
        mb.pickups.append(PickSpec("giunco", mb.c * CELL + 12, mb.fy * CELL))
    gpos = rng.randrange(0, len(seq)) if seq else 0
    for k, s in enumerate(seq):
        if guards and k == gpos:
            mb.guardian(guards.pop())
        if k:
            mb.flat(rng.randint(1, 5))
        match s:
            case "wall":
                mb.wall(rng.randint(3, 5), rng.randint(2, 4))
            case "pit":
                mb.pit()
            case "drop_float":
                mb.drop_float(rng.randint(9, 11))
            case "drop_mine":
                mb.drop_mine(rng.randint(8, 10))
            case "dig":
                mb.dig()
            case "climb":
                mb.climb(rng.randint(5, 7))
            case "climb_up":
                mb.climb_up(rng.choice((5, 5, 6)))
            case "ascend":
                mb.ascend()
            case "drop_anteo":
                mb.drop_anteo(rng.randint(9, 11))
            case "boat":
                mb.boat()
        if "vents" in P["extra"] and k == 0:
            mb.vent_row(2 + tier // 2)
        if "boulders" in P["extra"] and k == 0:
            mb.boulder_run()
        if "purge" in P["extra"] and k == len(seq) // 2:
            mb.purge()
    for g in guards:
        mb.guardian(g)
    if "climb" in P["extra"]:
        mb.climb(6)
    mb.flat(4)
    mb.finish()
    return _assemble(i, P, mb, mods, total, cantica, tier, seq=seq, rng=rng, flip="lux" in mods)


def _flip_cols(cols: list[list[str]]) -> list[list[str]]:
    """Da la vuelta a unas columnas construidas en el marco de quien cae hacia arriba."""
    table = {"E": "U", "e": "u", "X": "x"}
    return [[table.get(ch, ch) for ch in reversed(col)] for col in cols]


def _lucifero(i, P, mods, total, tier, rng) -> Level:
    """Inf. XXXIV: se baja por el pelo de Lucifer, en el centro de la Tierra la gravedad
    se invierte y se sale, cabeza abajo, por la natural burella."""
    from dataclasses import replace as _rp
    mb = MapBuilder(14, mods)
    mb.start()
    mb.wall(4, 3)
    mb.flat(3)
    mb.drop_float(10)
    fyl = mb.fy
    mb.flat(4)
    ceil_row = fyl - 7  # techo de roca a 56 px del suelo
    # el techo se adelanta sobre la izquierda y acaba en un colmillo que frena a los del revés
    for k, col in enumerate(mb.cols[-8:]):
        for r in range(0, ceil_row + 1):
            col[r] = "#"
        if k == 0:
            for r in range(ceil_row + 1, ceil_row + 5):
                col[r] = "#"
        if k == 1:  # visera: el Pellegrino del revés no puede coronar el colmillo
            col[ceil_row + 4] = "#"
    off = mb.c
    mb2 = MapBuilder(ROWS - 1 - ceil_row, mods)
    mb2.flat(10)
    mb2.climb(6)
    mb2.flat(6)
    mb2.climb(5)
    mb2.flat(4)
    mb2.finish()
    right = _flip_cols(mb2.cols)
    for k in range(2):
        for r in range(fyl - 6, min(ROWS, fyl + 3)):
            if right[k][r] == ".":
                right[k][r] = "|"
    mb.cols += right
    mb.rules += [_rp(r, x=r.x + off * CELL) if r.x is not None else r for r in mb2.rules]
    for s, n in mb2.need.items():
        mb.need[s] = mb.need.get(s, 0) + n
    mb.climbers = True
    mb.pickups += [_rp(p, x=p.x + off * CELL, inv=True) for p in mb2.pickups]
    return _assemble(i, P, mb, mods, total, "inferno", tier, seq=["wall", "drop_float", "climb"], rng=rng)



def _assemble(i, P, mb: MapBuilder, mods, total, cantica, tier, rr=50, seq=(), rng=None, flip=False) -> Level:
    rng = rng or random.Random(i)
    rules = list(mb.rules)
    need = dict(mb.need)
    if mb.floaters:
        rules.insert(0, Rule(Skill.GERIONE, n=total + 2, par=True, track=1))
        need[Skill.GERIONE] = total + 2
    if mb.climbers:
        rules.insert(0, Rule(Skill.PELLEGRINO, n=total + 2, par=True, track=2))
        need[Skill.PELLEGRINO] = total + 2
    slack = [2, 1, 1, 0][tier]
    skills = {s: need.get(s, 0) + (slack if need.get(s, 0) and s not in (Skill.GERIONE, Skill.PELLEGRINO) else 0)
              for s in SKILLS}
    # Unos pocos oficios de sobra para la improvisación del jugador.
    spare = [Skill.CAPOMASTRO, Skill.PIAGNONE, Skill.BUBBONE, Skill.FLAGELLANTE]
    if cantica == "paradiso":
        spare = [Skill.CAPOMASTRO, Skill.PIAGNONE, Skill.PELLEGRINO]
        skills[Skill.BUBBONE] = skills[Skill.BECCHINO] = 0
        if i >= 99:
            skills[Skill.FLAGELLANTE] = 0
    for s in spare[: 2 - tier // 2]:
        skills[s] += 1
    plague = P["moria"][0] or P["moria"][1] or "moria2" in mods
    skills[Skill.MEDICO] = 4 if plague else 2
    if "fast" in mods:
        skills[Skill.FLAGELLANTE] = 0
    if "ingegno" == GIORNATE_MODS[giornata_of(i)]:
        # Neifile: la mitad de los oficios extra están escondidos en el nivel
        hidden = [s for s in SKILLS if skills[s] and s not in (Skill.GERIONE, Skill.PELLEGRINO)][1::2]
    else:
        hidden = []
    # Coleccionables: palle y la pagina del nivel
    pickups = list(mb.pickups)
    rule_x = [r.x for r in rules if r.x is not None]
    flats = [f for f in mb.flats if all(abs(f[0] - p.x) > 24 for p in pickups)]
    rng.shuffle(flats)
    for s in hidden:
        if flats:
            x, y = flats.pop()
            pickups.append(PickSpec("oficio", x, y, s.value))
    phantoms: list[tuple[int, int, int, int, str, bool]] = []
    shelf_kind = "blink" if "blink" in mods else "ghost" if "ghost" in mods else None
    if shelf_kind:
        # una cornisa que aparece y desaparece: la pagina está encima
        for k, (x, y) in enumerate(flats):
            if y > 0 and all(abs(x - rx) > 70 for rx in rule_x) and 40 < x < len(mb.cols) * CELL - 60:
                flats.pop(k)
                phantoms.append((x - 18, y - 16, x + 18, y - 13, shelf_kind, False))
                pickups.append(PickSpec("pagina", x, y - 16))
                break
    trees: list[tuple[int, int]] = []
    if "trees" in mods:
        for x, y in flats[:2]:
            if y > 0:
                trees.append((x, y))
        flats = flats[2:]
    sabios: list[tuple[int, int, str, str]] = []
    if P["special"] == "limbo":
        for (x, y), (nm, line) in zip(flats[:3], SABIOS):
            sabios.append((x, y, nm, line))
        flats = flats[3:]
    reds = {"proemio": ["medicinale"], "inferno": ["cambio", "arancia", "medicinale", "congiura", "mecenate"],
            "purgatorio": ["medicinale", "mecenate", "arancia", "cambio"], "paradiso": ["mecenate", "medicinale"]}[cantica]
    n_palle = 1 + (i % 3 == 0) if cantica != "paradiso" else (i % 2)
    if P["special"] in ("primum", "final"):
        n_palle = 0
    for k in range(n_palle):
        if flats:
            x, y = flats.pop()
            kind = reds[(i + k) % len(reds)]
            pickups.append(PickSpec(kind, x, y, ARTISTS[(i + k) % 3] if kind == "mecenate" else ""))
    if "mecenate" in P["extra"] and flats:
        x, y = flats.pop()
        pickups.append(PickSpec("mecenate", x, y, "caravaggio" if P["special"] == "caravaggio" else "brunelleschi"))
    if "cambio" in P["extra"] and flats:
        x, y = flats.pop()
        pickups.append(PickSpec("cambio", x, y))
    if i in (12, 47, 80) and flats:  # una Palla del Giglio por cantica
        x, y = flats.pop()
        pickups.append(PickSpec("giglio", x, y))
    if "temptation" in P["extra"]:
        for x, y in flats[:5]:
            pickups.append(PickSpec(reds[len(pickups) % len(reds)], x, y - 26))
        flats = flats[5:]
    if flats and P["special"] != "final" and not any(p.kind == "pagina" for p in pickups):
        x, y = flats.pop()
        pickups.append(PickSpec("pagina", x, abs(y), inv=y < 0))
    elif P["special"] == "final":
        pickups.append(PickSpec("pagina", 360, 30 * CELL))
    if P["special"] == "rogo":  # más pagine que salvar de la hoguera
        for x, y in flats[:2]:
            pickups.append(PickSpec("pagina", x, y))
    for kind in ("lettere", "croce"):
        if kind in P["extra"]:
            while len(mb.cols) < VIEW_W // CELL:
                mb._col()
            _sky_glyphs(mb, kind)
    vault = cantica == "inferno" and not mb.climbers and P["theme"] not in ("limbo",)
    rows = mb.rows(random.Random(i * 13 + 1) if vault else None)
    guards = tuple(mb.guards)
    if flip:
        rows = tuple("".join(r) for r in zip(*_flip_cols([list(c) for c in zip(*rows)])))
        guards = tuple(GuardSpec(g.kind, g.x, g.y, True) for g in guards)
        pickups = [PickSpec(p.kind, p.x, p.y, p.artist, p.need, True) for p in pickups]
        phantoms = [(a, b, c, d, k, True) for a, b, c, d, k, _ in phantoms]
    width = len(rows[0]) * CELL
    walk_s = width / TPS
    minutes = math.ceil((walk_s * 1.6 + total * release_interval(rr) / TPS + 50 + 25 * len(mb.guards) + 120 * len(mb.boats)
                         + (40 if "night" in mods else 0)) / 60) + (2 if "slowskills" in mods else 1)
    target = [50, 60, 70, 80][tier] if i else 40
    if P["special"] == "final":
        target = 1
    cal = CALIBRATION.get(i)
    need_n = math.ceil(total * target / 100)
    to_save = min(need_n, cal) if cal is not None else max(1, math.ceil(total * 0.4))
    fire = None
    if P["special"] == "rogo":
        fire = (total * release_interval(rr) + 30 * TPS, 0.10)  # sube cuando ya ha salido la procesión
    hint_bits = [HINTS[s] for s in dict.fromkeys(seq) if s in HINTS][:2]
    if P["special"] == "selva":
        hint_bits = [HINTS["selva"], HINTS["dig"]]
    if any(g.kind == "caronte" for g in mb.guards):
        hint_bits.append("O el rodeo durísimo: una escalera de Capomastro hasta la pasarela que pasa sobre Caronte.")
    if mb.guards:
        hint_bits.append(GUARDS[mb.guards[0].kind][3])
    if flip:
        hint_bits.insert(0, "Aquí no se cae hacia abajo: se cae hacia la luz.")
    if P["special"] == "lucifero":
        hint_bits = ["Bajad por el pelo del Emperador. En el centro de la Tierra todo se da la vuelta: lo que era techo será suelo.",
                     "Al otro lado, Pellegrini para todos."]
    guide = P["guide"]
    lines = GUIDE_LINES[guide]
    hint = " ".join(hint_bits) or lines[i % len(lines)]
    return Level(
        id=i, name=P["name"], place=P["place"], canto=P["canto"], cantica=cantica, giornata=giornata_of(i),
        difficulty=DIFFICULTIES[tier], total=total, to_save=to_save, rr=rr, minutes=minutes, skills=skills,
        theme=P["theme"], map=rows, solution=tuple(rules), pickups=tuple(pickups), guards=guards,
        vents=tuple(mb.vents), boulders=tuple(mb.boulders), mods=frozenset(mods), moria=P["moria"], fire=fire,
        boats=tuple(mb.boats), liquid=LIQUIDS.get(next((m for m in mods if m in LIQUIDS), ""), None),
        sermon=SERMONS[i % len(SERMONS)], hint=hint, sky=P["sky"], special=P["special"], guide=guide,
        target_pct=target, phantoms=tuple(phantoms), trees=tuple(trees), sabios=tuple(sabios),
    )


LIQUIDS = {"sterco": (96, 70, 30), "pece": (22, 16, 24)}

# Letras de luz del cielo de Júpiter (Par. XVIII), 3×5 bloques
GLYPHS = {
    "D": ["##.", "#.#", "#.#", "#.#", "##."], "I": ["###", ".#.", ".#.", ".#.", "###"],
    "L": ["#..", "#..", "#..", "#..", "###"], "G": [".##", "#..", "#.#", "#.#", ".##"],
    "T": ["###", ".#.", ".#.", ".#.", ".#."], "E": ["###", "#..", "##.", "#..", "###"],
    "U": ["#.#", "#.#", "#.#", "#.#", "###"], "S": [".##", "#..", ".#.", "..#", "##."],
    "A": [".#.", "#.#", "###", "#.#", "#.#"], "M": ["#.#", "###", "###", "#.#", "#.#"],
}


def _sky_glyphs(mb: MapBuilder, kind: str) -> None:
    """Escribe en lo alto del marco (abajo en el Paraíso) las letras o la cruz de luz."""
    if kind == "lettere":
        text, c0 = "DILIGITE IUSTITIAM", 6
        for ch in text:
            if ch != " " and c0 + 3 < len(mb.cols):
                for r, row in enumerate(reversed(GLYPHS[ch])):  # el marco se dará la vuelta
                    for k, v in enumerate(row):
                        if v == "#" and mb.cols[c0 + k][1 + r] == ".":
                            mb.cols[c0 + k][1 + r] = "#"
            c0 += 4
    elif kind == "croce":
        mid = len(mb.cols) // 2
        for r in range(0, 6):
            if mb.cols[mid][r] == ".":
                mb.cols[mid][r] = "#"
        for k in range(mid - 4, mid + 5):
            if 0 <= k < len(mb.cols) and mb.cols[k][3] == ".":
                mb.cols[k][3] = "#"


SABIOS = [
    ("Omero", "«Quelli è Omero poeta sovrano» (Inf. IV, 88)."),
    ("Aristotele", "«…il maestro di color che sanno» (Inf. IV, 131)."),
    ("Averroè", "«Averoìs, che 'l gran comento feo» (Inf. IV, 144)."),
]
GIORNATE_MODS = ["", "resurrect", "ingegno", "pairs", "pairs_safe", "lure_bounce", "lure_long", "fake", "", "magnanimo"]


@dataclass(slots=True)
class Entrance:
    x: int
    y: int
    dir: int
    inv: bool = False


@dataclass(slots=True)
class Exit:
    x: int
    y: int
    inv: bool = False


def parse_map(rows: tuple[str, ...]):
    width = max(len(r) for r in rows)
    pad = max(0, ROWS - len(rows))
    h, w = VIEW_H, width * CELL
    kinds = np.zeros((h, w), dtype=np.uint8)
    hazard = np.zeros((h, w), dtype=np.uint8)
    entrances: list[Entrance] = []
    exits: list[Exit] = []
    tri = np.tri(CELL, dtype=bool)
    for r, line in enumerate(rows):
        y0 = (r + pad) * CELL
        for c, ch in enumerate(line.ljust(width, ".")):
            x0 = c * CELL
            cell = kinds[y0 : y0 + CELL, x0 : x0 + CELL]
            match ch:
                case "#":
                    cell[:] = DIRT
                case "S":
                    cell[:] = STEEL
                case "<":
                    cell[:] = OW_L
                case ">":
                    cell[:] = OW_R
                case "/":
                    cell[tri[:, ::-1]] = DIRT
                case "\\":
                    cell[tri] = DIRT
                case "_":
                    cell[CELL // 2 :] = DIRT
                case "~":
                    hazard[y0 : y0 + CELL, x0 : x0 + CELL] = HZ_LIQUID
                case "^":
                    hazard[y0 : y0 + CELL, x0 : x0 + CELL] = HZ_FIRE
                case "%":
                    hazard[y0 : y0 + CELL, x0 : x0 + CELL] = HZ_PURGE
                case "|":
                    hazard[y0 : y0 + CELL, x0 : x0 + CELL] = HZ_FLIP
                case "U" | "u":
                    # en el marco del revés: fila r real ↔ fila ROWS-1-r
                    entrances.append(Entrance(x0 + CELL // 2, (ROWS - r - pad) * CELL, 1 if ch == "U" else -1, True))
                case "x":
                    exits.append(Exit(x0 + CELL // 2, (ROWS - r - pad) * CELL, True))
                case "E" | "e":
                    entrances.append(Entrance(x0 + CELL // 2, y0 + CELL, 1 if ch == "E" else -1))
                case "X":
                    exits.append(Exit(x0 + CELL // 2, y0 + CELL))
    entrances.sort(key=lambda e: e.x)
    return kinds, hazard, entrances, exits


# Calibración: almas que salva la solución de referencia en cada nivel, en el peor
# caso entre una Compagnia ligera y otra cargada (python pydanteshell.py --calibrate).
# El mínimo exigido nunca la supera.
CALIBRATION: dict[int, int] = {0: 101, 1: 100, 2: 100, 3: 100, 4: 99, 5: 100, 6: 100, 7: 97, 8: 100, 9: 69, 10: 73, 11: 100, 12: 100, 13: 100, 14: 100, 15: 80, 16: 82, 17: 99, 18: 99, 19: 100, 20: 100, 21: 82, 22: 100, 23: 98, 24: 73, 25: 97, 26: 98, 27: 90, 28: 80, 29: 93, 30: 97, 31: 98, 32: 100, 33: 99, 34: 100, 35: 100, 36: 100, 37: 100, 38: 100, 39: 100, 40: 100, 41: 100, 42: 100, 43: 100, 44: 100, 45: 100, 46: 100, 47: 100, 48: 100, 49: 100, 50: 100, 51: 100, 52: 100, 53: 100, 54: 100, 55: 78, 56: 68, 57: 90, 58: 100, 59: 100, 60: 100, 61: 84, 62: 96, 63: 87, 64: 100, 65: 100, 66: 100, 67: 100, 68: 100, 69: 100, 70: 100, 71: 100, 72: 100, 73: 100, 74: 100, 75: 100, 76: 100, 77: 100, 78: 100, 79: 100, 80: 100, 81: 100, 82: 100, 83: 100, 84: 100, 85: 100, 86: 100, 87: 100, 88: 100, 89: 100, 90: 100, 91: 100, 92: 100, 93: 100, 94: 100, 95: 100, 96: 100, 97: 100, 98: 100, 99: 100, 100: 100}


CUSTOM: dict[int, Level] = {}  # niveles cargados desde JSON (id ≥ 1000)


@lru_cache(maxsize=None)
def _built(i: int) -> Level:
    return build_level(i)


def get_level(i: int) -> Level:
    return CUSTOM[i] if i in CUSTOM else _built(i)


DAILY_ID, ENDLESS_ID = 2000, 3000
VARIANT_BASES = [i for i in range(2, 100) if place_info(i)["special"] not in ("selva", "lucifero", "final", "child")]


def make_variant(lid: int, seed: int, title: str) -> Level:
    """Un nivel nuevo generado con otra semilla sobre un lugar de la Commedia. Su mínimo se
    calibra al vuelo con la solución de referencia, así que siempre es resoluble."""
    from dataclasses import replace as _rp

    base = random.Random(seed).choice(VARIANT_BASES)
    lv = _rp(build_level(base, seed=seed), id=lid, base=base, name=title)
    CUSTOM[lid] = lv
    w, _ = simulate(lid, Autopilot(lv.solution))
    need = max(1, min(math.ceil(lv.total * lv.target_pct / 100), w.saved))
    lv = _rp(lv, to_save=need)
    CUSTOM[lid] = lv
    return lv


N_LEVELS = 101


# ═══════════════════════════════════════════════════════════════════════════
# 5. LA COMPAGNIA
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(slots=True, eq=False)
class Lemming:
    id: int
    x: int  # píxel de los PIES: está de pie si terrain.solid(x, y)
    y: int
    dir: int = 1
    state: St = St.FALL
    frame: int = 0
    fall: int = 0
    climber: bool = False
    floater: bool = False
    medico: bool = False
    bomb: int | None = None
    bricks: int = 0
    removed: bool = False
    maestro: bool = False
    child: bool = False
    moria: int = 0  # 0 sano · 1 febbre · 2 bubbone
    moria_t: int = 0
    immune: int = 0
    fervor: int = 0
    grace: bool = False
    purified: bool = False
    inv: bool = False  # cae hacia arriba (Lucifer, Paraíso)
    carry: list | None = None  # en la mano de Anteo
    stare: int = 0
    stared: bool = False


@dataclass(slots=True)
class Guardian:
    kind: str
    x: int
    y: int
    pacified: bool = False
    touched: bool = False
    timer: int = 0
    anim: int = 0
    inv: bool = False

    @property
    def name(self) -> str:
        return GUARDS[self.kind][0]

    @property
    def needs(self) -> str | None:
        return GUARDS[self.kind][1]


@dataclass(slots=True)
class Pickup:
    kind: str
    x: int
    y: int
    artist: str = ""
    need: bool = False
    inv: bool = False
    taken: bool = False
    fake: bool = False


@dataclass(slots=True)
class Campaign:
    """Lo que la Compagnia arrastra de un nivel al siguiente."""

    peso: int = 0
    shield: list[str] = field(default_factory=list)
    maestro: bool = True
    congiura: int = 0
    dioneo: bool = True

    def to_json(self) -> dict:
        return {"peso": self.peso, "shield": list(self.shield), "maestro": self.maestro, "congiura": self.congiura,
                "dioneo": self.dioneo}

    @staticmethod
    def from_json(d: dict | None) -> Campaign:
        d = d or {}
        return Campaign(int(d.get("peso", 0)), list(d.get("shield", [])), bool(d.get("maestro", True)),
                        int(d.get("congiura", 0)), bool(d.get("dioneo", True)))


GIORNATE = [
    # (rey/reina, tema, modificador, descripción)
    ("Pampinea", "Tema libre", "", "Ninguno. Se aprende."),
    ("Filomena", "Infortunios con final feliz", "resurrect",
     "Un alma caída por nivel resucita si otra llega a su cuerpo a tiempo."),
    ("Neifile", "Lo que se consigue con ingenio", "ingegno", "Un oficio más de cada clase disponible."),
    ("Filostrato", "Amores con final desdichado", "pairs", "Las parejas no se separan: si cae una, cae la otra."),
    ("Fiammetta", "Amores felices tras desgracias", "pairs_safe", "Las parejas no se contagian entre sí."),
    ("Elissa", "Réplicas ingeniosas", "lure_bounce", "La Palla d'Arancia rebota: su señuelo llega más lejos."),
    ("Dioneo", "Burlas de esposas a maridos", "lure_long", "Los señuelos duran el doble."),
    ("Lauretta", "Burlas en general", "fake", "Una palla de cada nivel es falsa: pesa y no sirve."),
    ("Emilia", "Tema libre", "", "Ninguno. Respiro antes del final."),
    ("Panfilo", "Magnanimidad", "magnanimo", "Cada alma salvada por encima del mínimo resta 1 de Peso."),
]

Command = tuple


class World:
    """Simulación determinista. No sabe que pygame existe."""

    def __init__(self, level: Level, camp: Campaign | None = None, seed: int = 1348, infinite: bool = False):
        self.level = level
        self.infinite = infinite  # oficios sin límite (opción del jugador)
        camp = camp or Campaign()
        self.camp_in = camp
        kinds, hazard, self.entrances, self.exits = parse_map(level.map)
        rng = np.random.default_rng(seed + level.id)
        theme = THEMES[level.theme]
        self.theme = theme
        colors, emis = colorize(kinds, theme, rng)
        self.terrain = self.tn = Terrain(kinds, colors, emis, theme.brick)
        self.ti = FlipTerrain(self.tn)
        self.hazard = self.hn = hazard
        self.hi = hazard[::-1]
        self._inv = False
        self.msg_serial = 0
        self.rng = rng
        self.mods = set(level.mods)
        g = GIORNATE[level.giornata][2]
        if g:
            self.mods.add(g)
        self.cantica = level.cantica
        self.slots = SLOTS[self.cantica]
        self.total = level.total
        self.skills: dict[Skill, int] = {s: level.skills.get(s, 0) for s in SKILLS}
        if "ingegno" in self.mods:
            hidden = {p.artist for p in level.pickups if p.kind == "oficio"}
            for s in SKILLS:
                if self.skills[s] and s.value not in hidden:
                    self.skills[s] += 1
        self.rr_min = self.rr = level.rr
        self.tick_count = 0
        self.time_total = self.time_left = level.minutes * 60 * TPS
        self.hatch = 0
        self.release_timer = 0
        self.released = 0
        self.saved = 0
        self.dead = 0
        self.nuking = False
        self.lemmings: list[Lemming] = []
        self.by_id: dict[int, Lemming] = {}
        self.blockers: list[tuple[int, int, int]] = []
        self.events: list[str] = []
        self.fx: list[tuple] = []
        self.messages: list[list] = []
        # escudo y Peso
        self.shield: list[str] = [p for p in camp.shield][: self.slots]
        if level.special == "primum" and any(p in RED_PALLE for p in self.shield):
            self.shield = [p for p in self.shield if p not in RED_PALLE]
            self.say("Primum Mobile: las palle rojas se disuelven en la luz. Solo queda el lirio.", "Beatrice")
        self.peso = camp.peso
        self.congiura = camp.congiura
        self.used: dict[str, int] = {}
        self.dioneo_avail = camp.dioneo
        self.dioneo_used = False
        # entidades
        self.guards = [Guardian(g.kind, g.x, g.y, inv=g.inv) for g in level.guards if g.kind != "anteo"]
        self.anteo = [(g.x, g.y) for g in level.guards if g.kind == "anteo"]
        self.pickups = [Pickup(p.kind, p.x, p.y, p.artist, p.need, p.inv) for p in level.pickups]
        # cornisas que van y vienen (Luna) u ocultas hasta que llega la luz (Lume, Botticelli)
        self.phantoms: list[dict] = []
        for x0, y0, x1, y1, kind, inv in level.phantoms:
            if inv:
                y0, y1 = VIEW_H - y1, VIEW_H - y0
            self.phantoms.append({"r": (x0, y0, x1, y1), "kind": kind, "on": False, "mask": None})
        self.drops: list[list[int]] = []  # lluvia de fuego del sabbione
        self.canopies = 0
        self.banner: list | None = None
        if "banner" in self.mods and self.entrances:
            self.banner = [float(self.entrances[0].x + 60), 1, 45 * TPS]
        self.trees = list(level.trees)
        self.sabios = [list(s) + [False] for s in level.sabios]
        self.lonely: set[int] = set()
        self.boats = [{"xa": x0, "xb": x1 - 24, "y": y, "x": x0, "dir": 1, "wait": 70} for x0, x1, y in level.boats]
        for b in self.boats:
            self._boat_paint(b["x"], b["x"] + 24, b["y"], True)
        self.snakes: list[list[int]] = []
        if "snakes" in self.mods:
            for k in range(2):
                x = int(self.tn.w * (0.4 + 0.25 * k))
                y = self._floor_at(x)
                if y is not None:
                    self.snakes.append([x, y, 1 if k % 2 else -1])
        self.snake_said = False
        self.primum_said = False
        self.tempo_used = False
        if "fake" in self.mods:
            reds = [p for p in self.pickups if p.kind in RED_PALLE and not p.need]
            if len(reds) > 1:
                reds[-1].fake = True
        self.vents = [list(v) for v in level.vents]
        self.boulders = [[xa, xb, y, xa, 1] for xa, xb, y in level.boulders]
        self.rats: list[list[int]] = []
        self.corpses: list[list[int]] = []  # [x, y, edad]
        self.focos: list[tuple[int, int]] = []
        n_inf, rats = level.moria
        self.infect_ids = {k * max(1, self.total // (n_inf + 1)) + 2 for k in range(n_inf)}
        if rats:
            for k in range(3):
                x = int(self.terrain.w * (0.3 + 0.2 * k))
                y = self._floor_at(x)
                if y is not None:
                    self.rats.append([x, y, -1 if k % 2 else 1])
        self.maestro_due = camp.maestro
        self.maestro: Lemming | None = None
        self.maestro_saved = False
        self.maestro_wait = 0
        self.child: tuple[int, int] | None = None
        if level.special == "child":
            x = int(self.terrain.w * 0.36)
            y = self._floor_at(x)
            if y is not None:
                self.child = (x, y)
        self.child_saved = False
        self.toll = camp.congiura if level.special == "toll" else 0
        self.statues: list[tuple[int, int]] = []
        self.fire_y = float(VIEW_H + 6)
        self.lure: list | None = None
        self.lume: list | None = None
        self.reveal = False
        self.combo = 0
        self.panic = 0
        self.dioneo = 0
        self.pick_times: deque[int] = deque()
        self.soul: list | None = None
        self.resurrected = False
        self.pagina = False
        self.giunco = False
        self.purge_paid = False
        self.flame_said = False
        self.notes: list[str] = []
        self.art_queue: list[str] = []
        self.cured = 0
        self.combo_hit = False
        if self.toll:
            self.say("El Cocito cobra la traición: {n} alma(s) quedan presas en el hielo de la Antenora.", "Virgilio", n=self.toll)
        if level.special == "bulla":
            self.say("Aviñón, 20 de octubre de 1349: la bula de Clemente VI condena a los flagelantes.", "Virgilio")
        if level.special == "lucifero":
            self.say("Trepa por su pelo. Al otro lado del centro de la Tierra están las estrellas.", "Virgilio")
        if "lux" in self.mods and level.id == 68:
            self.say("Aquí no se cae hacia abajo: se cae hacia la luz. Mira arriba.", "Beatrice")
        if level.id == 41:
            self.say("El Ángel graba siete P en cada frente. Cada cornisa borrará una.", "Virgilio")
        if level.id == 66:
            self.say("«Libero, dritto e sano è tuo arbitrio… per ch'io te sovra te corono e mitrio.» (Purg. XXVII)", "Virgilio")
        if level.id == 67:
            self.say("Virgilio se ha ido. Llega Beatrice, velada, entre flores.", "")
        if "suicidi" in self.mods:
            self.say("Cada rama que se rompe aquí sangra. Excavar cuesta Peso.", "Virgilio")

    # ── viaje en el tiempo ───────────────────────────────────────────────
    def snapshot(self) -> World:
        """Copia congelada del mundo (para rebobinar). Las vistas del revés se rehacen al volver."""
        keep = (self.ti, self.hi, self.events, self.fx)
        self.ti = self.hi = None
        self.events, self.fx = [], []
        try:
            return copy.deepcopy(self)
        finally:
            self.ti, self.hi, self.events, self.fx = keep

    @staticmethod
    def thaw(snap: World) -> World:
        w = copy.deepcopy(snap)
        w.ti = FlipTerrain(w.tn)
        w.hi = w.hn[::-1]
        w._frame(False)
        w.tn.dirty = (0, 0, w.tn.w, w.tn.h)
        return w

    # ── utilidades ───────────────────────────────────────────────────────
    def _floor_at(self, x: int) -> int | None:
        col = self.terrain.k[:, x]
        for y in range(8, self.terrain.h):
            if col[y] != AIR:
                return y
        return None

    def say(self, text: str, who: str = "", **kw) -> None:
        """Una voz en la escena. El texto es una plantilla: la interfaz la traduce."""
        self.messages.append([text, 6 * TPS + len(text) * 2, who, kw])
        self.msg_serial += 1

    def emit(self, ev: tuple) -> None:
        if self._inv:
            ev = (ev[0], ev[1], VIEW_H - 1 - ev[2], *ev[3:])
        self.fx.append(ev)

    def _frame(self, inv: bool) -> None:
        """Elige el marco de referencia: el del mundo o el de quien cae hacia la luz."""
        self._inv = inv
        if inv:
            self.terrain, self.hazard = self.ti, self.hi
        else:
            self.terrain, self.hazard = self.tn, self.hn

    @staticmethod
    def ry(L) -> int:
        """Altura real de los pies."""
        return VIEW_H - 1 - L.y if L.inv else L.y

    @staticmethod
    def rmid(L) -> int:
        """Altura real del centro del cuerpo."""
        return VIEW_H + 5 - L.y if L.inv else L.y - 6

    @property
    def has_inv(self) -> bool:
        return any(e.inv for e in self.entrances) or "lux" in self.mods or self.level.special == "lucifero"

    def rule_off(self, m: str) -> bool:
        return m in self.mods and self.dioneo == 0

    @property
    def night(self) -> bool:
        if not self.rule_off("night"):
            return False
        return self.tick_count % NIGHT_CYCLE >= NIGHT_CYCLE - NIGHT_LEN

    @property
    def alive(self) -> int:
        return sum(1 for L in self.lemmings if not L.removed and not L.maestro)

    @property
    def compagnia_done(self) -> bool:
        released_all = self.released >= self.total
        return (released_all or self.nuking) and self.alive == 0 and self.hatch >= HATCH_TICKS

    @property
    def maestro_out(self) -> bool:
        return self.maestro is not None and not self.maestro.removed

    @property
    def done(self) -> bool:
        if self.time_left <= 0:
            return True
        if not self.compagnia_done:
            return False
        if self.maestro_due and self.maestro is None and not self.nuking:
            return False
        return not self.maestro_out or self.maestro_wait > 25 * TPS

    @property
    def success(self) -> bool:
        return self.saved >= self.level.to_save

    def allowed(self, skill: Skill) -> bool:
        """Oficios que existen aquí: en el Paraíso no hay Bubbone ni Becchino, y en el último cielo
        ni Flagellante; la acedia no deja pararse."""
        if self.cantica == "paradiso" and skill in (Skill.BUBBONE, Skill.BECCHINO):
            return False
        lid = self.level.base if self.level.base >= 0 else self.level.id
        if skill == Skill.FLAGELLANTE and (lid >= 99 and self.cantica == "paradiso" or "fast" in self.mods):
            return False
        return True

    def has_skill(self, skill: Skill) -> bool:
        if self.infinite:
            return self.allowed(skill)
        return self.skills[skill] > 0

    def can_assign(self, L: Lemming, skill: Skill) -> bool:
        if L.removed or L.state in DOOMED or L.maestro:
            return False
        if L.moria == 2 and skill not in (Skill.BUBBONE, Skill.MEDICO):
            return False
        match skill:
            case Skill.PELLEGRINO:
                return not L.climber
            case Skill.GERIONE:
                return not L.floater
            case Skill.BUBBONE:
                return L.bomb is None
            case Skill.FLAGELLANTE:
                return L.state in GROUND_WORK and not self.rule_off("fast")
            case Skill.CAPOMASTRO:
                return L.state in GROUND_WORK and L.state != St.BUILD
            case Skill.PIAGNONE:
                return L.state in GROUND_WORK and L.state != St.BASH
            case Skill.MINATORE:
                return L.state in GROUND_WORK and L.state != St.MINE
            case Skill.BECCHINO:
                return L.state in GROUND_WORK and L.state != St.DIG
            case Skill.MEDICO:
                return not L.medico
        return False

    def lemmings_at(self, cx: int, cy: int) -> list[Lemming]:
        return [L for L in self.lemmings if not L.removed and abs(L.x - cx) <= 5 and abs(self.rmid(L) - cy) <= 8]

    def pick(self, cx: int, cy: int, skill: Skill | None) -> tuple[Lemming | None, int]:
        cands = self.lemmings_at(cx, cy)
        if not cands:
            return None, 0
        able = [L for L in cands if skill and self.can_assign(L, skill)]
        pool = able or cands
        best = min(pool, key=lambda L: (abs(L.x - cx) + abs(self.rmid(L) - cy), L.id))
        return best, len(cands)

    def guard_near(self, x: int, y: int, r: int = 28) -> Guardian | None:
        best = None
        for g in self.guards:
            gy = VIEW_H + 9 - g.y if g.inv else g.y - 10
            if not g.pacified and abs(g.x - x) <= r and abs(gy - y) <= r + 6:
                best = g
        return best

    # ── órdenes ──────────────────────────────────────────────────────────
    def do(self, cmd: Command) -> bool:
        match cmd:
            case ("assign", lid, skill):
                return self.assign(int(lid), Skill(skill))
            case ("rr", value):
                v = max(self.rr_min, min(RR_MAX, int(value)))
                changed = v != self.rr
                self.rr = v
                return changed
            case ("nuke",):
                if self.nuking:
                    return False
                self.nuking = True
                self.peso += 5
                self.notes.append("Dies Irae: +5 de Peso")
                self.events.append("ohno")
                self.say("Dies irae, dies illa…", "")
                return True
            case ("palla", slot, x, y):
                return self.use_palla(int(slot), int(x), int(y))
            case ("mecenate", slot, x, y, artist):
                return self.use_palla(int(slot), int(x), int(y), str(artist))
            case ("tempo", slot):
                return self.buy_time(int(slot))
            case ("swap", slot, a, b):
                return self.swap(int(slot), int(a), int(b))
            case ("return", slot):
                return self.return_palla(int(slot))
            case ("dioneo",):
                if not self.dioneo_avail or self.dioneo_used:
                    return False
                self.dioneo_used = True
                self.dioneo = DIONEO_TICKS
                self.events.append("lume")
                self.say("Privilegio di Dioneo: quince segundos sin la regla de este lugar.", "Dioneo")
                return True
        return False

    def assign(self, lid: int, skill: Skill) -> bool:
        L = self.by_id.get(lid)
        if L is not None and L.state == St.BLOCK and "paradiso" in self.mods and not L.removed:
            # en el Paraíso el Flagellante solo necesita que alguien le convenza de seguir
            self._set(L, St.WALK)
            L.fervor = 0
            self.emit(("grace", L.x, L.y - 8))
            self.say("El Flagellante deja el látigo y sigue a los demás.", "Beatrice")
            self.events.append("cure")
            return True
        if L is None or not self.has_skill(skill) or not self.can_assign(L, skill):
            return False
        if not self.infinite:
            self.skills[skill] -= 1
        L.fervor = 0
        L.stare = 0
        if "suicidi" in self.mods and skill in (Skill.PIAGNONE, Skill.MINATORE, Skill.BECCHINO, Skill.BUBBONE):
            self.peso += 1
            self.notes.append("«Perché mi schiante?»: +1 de Peso")
            self.say("«Perché mi schiante?» (Inf. XIII). El bosque sangra: +1 de Peso.", "Pier della Vigna")
        match skill:
            case Skill.PELLEGRINO:
                L.climber = True
            case Skill.GERIONE:
                L.floater = True
            case Skill.BUBBONE:
                L.bomb = BOMB_TICKS
            case Skill.FLAGELLANTE:
                self._set(L, St.BLOCK)
            case Skill.CAPOMASTRO:
                self._set(L, St.BUILD)
                L.bricks = BRICKS
            case Skill.PIAGNONE:
                self._set(L, St.BASH)
            case Skill.MINATORE:
                self._set(L, St.MINE)
            case Skill.BECCHINO:
                self._set(L, St.DIG)
            case Skill.MEDICO:
                L.medico = True
                L.moria = L.moria_t = 0
                L.immune = 10**9
                self.emit(("cure", L.x, L.y - 8))
                self.events.append("cure")
        self.events.append("assign")
        return True

    # ── palle ────────────────────────────────────────────────────────────
    def _spend(self, slot: int) -> str:
        kind = self.shield.pop(slot)
        cost = PESO[kind]
        self.peso += cost
        self.used[kind] = self.used.get(kind, 0) + 1
        if kind == "congiura":
            self.congiura += 1
        if "giglio" in self.shield:
            self.peso = min(self.peso, 30)
        self.events.append("palla")
        return kind

    def buy_time(self, slot: int) -> bool:
        """Purgatorio: un bezante compra un segundo intento de la cornisa."""
        if self.cantica != "purgatorio" or self.tempo_used or not 0 <= slot < len(self.shield) or self.shield[slot] != "cambio":
            return False
        self._spend(slot)
        self.tempo_used = True
        self.time_left += int(self.time_total * 0.4)
        self.notes.append("Segundo intento comprado: +2 de Peso")
        self.say("Un bezante compra un segundo intento de la cornisa: más días, +2 de Peso.", "")
        return True

    def use_palla(self, slot: int, x: int, y: int, artist: str | None = None) -> bool:
        if not 0 <= slot < len(self.shield):
            return False
        kind = self.shield[slot]
        g = self.guard_near(x, y)
        match kind:
            case "cambio":
                if g is None:
                    return False
                if g.kind == "angelo":
                    self._spend(slot)
                    self.peso += 5
                    self.notes.append("Intento de soborno al Ángel: +5 de Peso")
                    self.say("La gracia no se compra. El Ángel no se mueve; tu Peso, sí.", "L'Angelo")
                    self.events.append("ting")
                    return True
                if g.needs != "cambio":
                    return False
                self._spend(slot)
                self._pacify(g, "El óbolo cae en la mano del guardián. Pasad.")
                return True
            case "arancia":
                self._spend(slot)
                self.emit(("orange", x, y))
                if g is not None and g.needs == "arancia":
                    self._pacify(g, "{name} se arroja sobre la naranja. El paso queda libre.")
                    return True
                t = LURE_TICKS * (2 if "lure_long" in self.mods else 1)
                self.lure = [x, y, t]
                self.say("La naranja amarga rueda. Las almas la siguen.", "")
                return True
            case "medicinale":
                self._spend(slot)
                n = 0
                for L in self.lemmings:
                    if not L.removed and (L.x - x) ** 2 + (self.rmid(L) - y) ** 2 <= 48 * 48:
                        n += L.moria > 0
                        L.moria = L.moria_t = 0
                        L.immune = IMMUNE_TICKS
                self.focos = [f for f in self.focos if (f[0] - x) ** 2 + (f[1] - y) ** 2 > 48 * 48]
                self.corpses = [c for c in self.corpses if (c[0] - x) ** 2 + (c[1] - y) ** 2 > 48 * 48]
                self.emit(("cure", x, y))
                self.events.append("cure")
                self.say("Cosme y Damián: {n} curados. Quince segundos de inmunidad.", "", n=n)
                return True
            case "mecenate":
                if artist in ARTISTS:
                    if self.art_queue:
                        self.art_queue.pop(0)
                else:
                    artist = self.pick_artist(slot)
                self._spend(slot)
                if artist == "brunelleschi":
                    col = np.array((236, 204, 150), dtype=np.uint8)
                    if "firerain" in self.mods:
                        # una cúpula colgada en el aire: la lluvia de fuego choca con ella
                        ground = self._floor_at(min(max(x, 0), self.tn.w - 1)) or y
                        for dx in range(-30, 31):
                            yy = ground - 30 + int(12 * (dx / 30) ** 2)
                            self.tn.add_row(x + dx, x + dx, yy, col)
                            self.tn.add_row(x + dx, x + dx, yy + 1, col)
                        self.canopies += 1
                        self.say("Brunelleschi: doble casco, sin cimbra. Bajo la cúpula no llueve fuego.", "Brunelleschi")
                    else:
                        for dy in range(3):
                            self.tn.add_row(x - 30, x + 30, y + dy, col)
                        self.say("Brunelleschi: doble casco, sin cimbra. Un puente donde no lo había.", "Brunelleschi")
                    self.emit(("dome", x, y))
                elif artist == "botticelli":
                    self.reveal = True
                    self.say("Botticelli dibuja la Mappa dell'Inferno: todo queda a la vista.", "Botticelli")
                else:
                    self.lume = [x, y, LUME_TICKS]
                    self.say("Caravaggio pinta: un haz oblicuo elige a quien toca. Dejan de azotarse.", "Caravaggio")
                self.events.append("lume")
                return True
            case "congiura":
                if g is None:
                    return False
                self._spend(slot)
                self._pacify(g, "26 de abril de 1478. {name} se vuelve contra los suyos. Dante lo anota.")
                return True
            case "giglio":
                if self.level.special == "final":
                    self.shield.pop(slot)
                    self.used["giglio"] = 1
                    self.emit(("release", x, y))
                    self.events.append("lume")
                    self.say("El escudo de Lorenzo cae girando hasta perderse. Ya no hay nada que llevar.", "San Bernardo")
                    return True
                return False
        return False

    def next_artist(self) -> str:
        return self.art_queue[0] if self.art_queue else ARTISTS[(self.level.id + sum(self.used.values())) % 3]

    def pick_artist(self, slot: int) -> str:
        """El artista de cada Palla del Mecenate se decide al recogerla."""
        if self.art_queue:
            return self.art_queue.pop(0)
        return ARTISTS[(self.level.id + sum(self.used.values())) % 3]

    def swap(self, slot: int, a: int, b: int) -> bool:
        if not 0 <= slot < len(self.shield) or self.shield[slot] != "congiura":
            return False
        A, B = self.by_id.get(a), self.by_id.get(b)
        if A is None or B is None or A is B or A.removed or B.removed or A.state in DOOMED or B.state in DOOMED:
            return False
        self._spend(slot)
        A.x, B.x = B.x, A.x
        A.y, B.y = B.y, A.y
        A.dir, B.dir = B.dir, A.dir
        self.emit(("swap", A.x, A.y))
        self.emit(("swap", B.x, B.y))
        self.say("Dos almas cambian de lugar. Alguien, en algún sitio, lo cobrará.", "")
        return True

    def return_palla(self, slot: int) -> bool:
        if "return" not in self.mods or not 0 <= slot < len(self.shield):
            return False
        kind = self.shield.pop(slot)
        self.peso = max(0, self.peso - 3)
        self.notes.append(f"Devuelta {PALLE_INFO[kind][0]}: −3 de Peso")
        self.say("Adhaesit pavimento anima mea. Una palla menos, tres de Peso menos.", "")
        self.events.append("cure")
        return True

    def _pacify(self, g: Guardian, msg: str) -> None:
        g.pacified = True
        self.fx.append(("pacify", g.x, VIEW_H + 11 - g.y if g.inv else g.y - 12))
        self.events.append("bribe")
        self.say(msg, g.name, name=g.name)

    # ── tick ─────────────────────────────────────────────────────────────
    def tick(self) -> None:
        if len(self.events) > 256:
            del self.events[:-64]
        if len(self.fx) > 512:
            del self.fx[:-128]
        self._release()
        if self.nuking:
            for L in self.lemmings:
                if not L.removed and L.bomb is None and L.state not in DOOMED:
                    L.bomb = BOMB_TICKS
                    break
        for name in ("combo", "panic", "dioneo"):
            v = getattr(self, name)
            if v > 0:
                setattr(self, name, v - 1)
        if self.lure:
            self.lure[2] -= 1
            if self.lure[2] <= 0:
                self.lure = None
        if self.lume:
            self.lume[2] -= 1
            if self.lume[2] <= 0:
                self.lume = None
        if self.level.fire and self.tick_count > self.level.fire[0]:
            self.fire_y -= self.level.fire[1]
        self.blockers = [(L.x, L.y, BLOCK_RANGE, L.inv) for L in self.lemmings
                         if L.state == St.BLOCK and not L.removed and "paradiso" not in self.mods]
        self.blockers += [(g.x, g.y, GUARD_RANGE, g.inv) for g in self.guards if not g.pacified]
        self._boats()
        night = self.night
        self._phantoms()
        self._banner()
        if "venus" in self.mods and self.tick_count % 8 == 0:
            self._venus()
        if self.level.special == "rogo" and self.tick_count % (18 * TPS) == 9 * TPS:
            self.say(SAVONAROLA[(self.tick_count // (18 * TPS)) % len(SAVONAROLA)], "Savonarola")
        for L in self.lemmings:
            if L.removed:
                continue
            self._frame(L.inv)
            if L.bomb is not None and L.state not in DOOMED:
                L.bomb -= 1
                if L.bomb <= 0:
                    L.bomb = None
                    if L.state in AIRBORNE:
                        self._explode(L)
                        continue
                    self._set(L, St.OHNO)
                    self.events.append("ohno")
            self._moria(L)
            self._step(L, night)
            if not L.removed:
                self._hazards(L)
                if not L.removed and L.state not in DOOMED:
                    self._frame(L.inv)
                    self._pickups(L)
        self._frame(False)
        self._firerain()
        if self.tick_count % 2 == 0:
            self._medici()
        if self.tick_count % 4 == 0:
            self._contagion()
        self._rats()
        self._snakes()
        self._vents_boulders()
        self._guards()
        self._corpses()
        self._souls()
        if self.compagnia_done and self.maestro_out:
            self.maestro_wait += 1
        self.lemmings = [L for L in self.lemmings if not L.removed]
        for m in self.messages:
            m[1] -= 1
        self.messages = [m for m in self.messages if m[1] > 0][-4:]
        self.time_left -= 1
        self.tick_count += 1

    def _release(self) -> None:
        if not self.entrances:
            return
        if self.hatch < HATCH_TICKS:
            self.hatch += 1
            if self.hatch == HATCH_TICKS:
                self.events.append("letsgo")
            return
        if self.nuking:
            return
        if self.release_timer > 0:
            self.release_timer -= 1
            return
        e = self.entrances[self.released % len(self.entrances)]
        if self.released < self.total:
            if self.toll > 0:
                self.toll -= 1
                self.released += 1
                self.dead += 1
                x = e.x + 40 + 14 * len(self.statues)
                y = self._floor_at(min(x, self.terrain.w - 1)) or e.y
                self.statues.append((x, y))
                self.release_timer = release_interval(self.rr) // 2
                return
            L = Lemming(self.released, e.x, e.y, e.dir, inv=e.inv)
            if L.id in self.infect_ids:
                L.moria = 1
            self._add(L)
            self.released += 1
            self.release_timer = release_interval(self.rr)
        elif self.maestro_due and self.maestro is None:
            L = Lemming(10_000, e.x, e.y, e.dir, maestro=True, inv=e.inv)
            self.maestro = L
            self._add(L)
            self.say("Il Maestro Lapo cierra la procesión, látigo en mano.", "")

    def _add(self, L: Lemming) -> None:
        self.lemmings.append(L)
        self.by_id[L.id] = L

    # ── máquina de estados ───────────────────────────────────────────────
    def _set(self, L: Lemming, st: St) -> None:
        L.state = st
        L.frame = 0
        if st == St.FALL:
            L.fall = 0

    def _walk_moves(self, L: Lemming, night: bool) -> int:
        if night:
            return 0
        if L.stare > 0:  # se queda mirando la fruta
            L.stare -= 1
            return 0
        t = self.tick_count + L.id
        if "paradiso" in self.mods and L.fervor > FERVOR_SLOW and t % 80 < 24 and not self.dioneo:
            return 0  # deslumbrado: quien se azota no puede mirar la luz
        n = 2 if (self.rule_off("fast") or self.combo) else 1
        if self.rule_off("ice") and t % 3 == 0:
            n += 1  # el hielo del Cocito no deja pararse
        if L.id in self.lonely and t % 2 == 0:
            n -= 1  # Venus: sola, el alma no tiene prisa
        if self.panic and not self.combo and t % 2 == 0:
            n += 1
        if L.moria == 1 and t % 7 == 0:
            n -= 1
        elif L.moria == 2 and t % 3 == 0:
            n -= 1
        elif L.fervor > FERVOR_SLOW and t % 5 == 0:
            n -= 1
        if self.cantica == "purgatorio" and self.peso >= 10 and t % max(3, 13 - self.peso // 10) == 0:
            n -= 1
        return max(0, n)

    def _step(self, L: Lemming, night: bool) -> None:
        if L.carry is not None:
            c = L.carry
            c[0] += 1
            f = min(1.0, c[0] / CARRY_TICKS)
            L.x = round(c[1] + (c[3] - c[1]) * f)
            L.y = round(c[2] + (c[4] - c[2]) * f - 18 * math.sin(f * math.pi))
            if f >= 1:
                L.carry = None
                L.x, L.y = c[3], c[4]
                self._set(L, St.WALK)
            return
        if L.state in NEEDS_FLOOR and not self.terrain.solid(L.x, L.y):
            self._set(L, St.FALL)
        match L.state:
            case St.WALK:
                L.fervor += 1
                if self.lure and abs(L.x - self.lure[0]) < (120 if "lure_bounce" in self.mods else 80) and abs(self.ry(L) - self.lure[1]) < 64:
                    if abs(L.x - self.lure[0]) > 3:
                        L.dir = 1 if self.lure[0] > L.x else -1
                if self.banner and not L.inv and abs(L.x - self.banner[0]) < 56 and abs(L.x - self.banner[0]) > 4:
                    L.dir = 1 if self.banner[0] > L.x else -1
                if self.panic and not self.combo and self.rng.random() < 0.015:
                    L.dir = -L.dir
                for _ in range(self._walk_moves(L, night)):
                    if L.state != St.WALK:
                        break
                    self._walk(L)
            case St.FALL:
                self._fall(L)
            case St.FLOAT:
                self._float(L)
            case St.CLIMB:
                if not night:
                    self._climb(L)
            case St.HOIST:
                L.frame += 1
                if L.frame >= HOIST_TICKS:
                    L.x += L.dir
                    self._set(L, St.WALK)
            case St.BLOCK:
                L.frame += 1
                L.fervor += 2
            case St.BUILD:
                if not night:
                    self._build(L)
            case St.SHRUG:
                L.frame += 1
                if L.frame >= SHRUG_TICKS:
                    self._set(L, St.WALK)
            case St.BASH:
                if "slowskills" not in self.mods or self.tick_count % 2 or self.dioneo:
                    self._bash(L)
            case St.MINE:
                self._mine(L)
            case St.DIG:
                self._dig(L)
            case St.OHNO:
                L.frame += 1
                if not self.terrain.solid(L.x, L.y):
                    L.y += 1
                if L.frame >= OHNO_TICKS:
                    self._explode(L)
            case St.SPLAT | St.DROWN | St.BURN | St.PLAGUE:
                L.frame += 1
                if L.frame >= DYING[L.state]:
                    self._kill(L, L.state)
            case St.EXIT:
                L.frame += 1
                if L.frame >= EXIT_TICKS:
                    L.removed = True
                    if L.maestro:
                        self.maestro_saved = True
                        self.say("El Maestro cruza la puerta. «Ya os lo dije: el látigo salva.»", "Il Maestro")
                        if self.alive:
                            self.combo = max(self.combo, COMBO_TICKS)  # el resto lo sigue con más ritmo
                            self.say("El Maestro ha llegado: el resto lo sigue con más ritmo.", "")
                    else:
                        self.saved += 1
                        if L.child:
                            self.child_saved = True
                    self.events.append("yippee")
                    self.emit(("saved", L.x, L.y - 6))

    def _in_block_field(self, L: Lemming) -> bool:
        for bx, by, rng_, binv in self.blockers:
            if binv == L.inv and (bx, by) != (L.x, L.y) and abs(by - L.y) <= 8 and 0 < (bx - L.x) * L.dir <= rng_:
                return True
        return False

    def _walk(self, L: Lemming) -> None:
        t = self.terrain
        if self._in_block_field(L):
            L.dir = -L.dir
        L.frame += 1
        nx = L.x + L.dir
        if t.solid(nx, L.y - 1):
            h = 0
            while h <= STEP_UP and t.solid(nx, L.y - 1 - h):
                h += 1
            if h > STEP_UP:
                if L.climber and 0 <= nx < t.w:
                    self._set(L, St.CLIMB)
                else:
                    L.dir = -L.dir
                return
            L.x, L.y = nx, L.y - h
        elif t.solid(nx, L.y):
            L.x = nx
        else:
            L.x = nx
            for d in range(1, STEP_DOWN + 1):
                if t.solid(nx, L.y + d):
                    L.y += d
                    return
            self._set(L, St.FALL)

    def _land(self, L: Lemming, lethal: bool) -> None:
        if lethal and L.fall > LETHAL_FALL and "nodeath" not in self.mods:
            if "giglio" in self.shield and not L.grace:
                L.grace = True
                self.emit(("grace", L.x, L.y - 6))
                self.events.append("cure")
                self._set(L, St.WALK)
                return
            self._set(L, St.SPLAT)
            self.events.append("splat")
            self.emit(("blood", L.x, L.y))
        else:
            self._set(L, St.WALK)

    def _wind(self, L: Lemming) -> None:
        if self.rule_off("wind") and self.tick_count % 2 == 0:
            d = 1 if (self.tick_count // (9 * TPS)) % 2 == 0 else -1
            nx = L.x + d
            if not self.terrain.solid(nx, L.y - 1) and not self.terrain.solid(nx, L.y - 8):
                L.x = nx

    def _fall(self, L: Lemming) -> None:
        t = self.terrain
        L.frame += 1
        if L.floater and L.frame > FLOAT_DELAY:
            L.state = St.FLOAT
            L.frame = 0
            return
        self._wind(L)
        for _ in range(FALL_SPEED):
            if t.solid(L.x, L.y):
                break
            L.y += 1
            L.fall += 1
        if t.solid(L.x, L.y):
            self._land(L, True)

    def _float(self, L: Lemming) -> None:
        t = self.terrain
        L.frame += 1
        self._wind(L)
        for _ in range(1 + (L.frame % 2)):
            if t.solid(L.x, L.y):
                break
            L.y += 1
        if t.solid(L.x, L.y):
            self._land(L, False)

    def _climb_period(self) -> int:
        if self.cantica == "purgatorio":
            return 2 + self.peso // 15
        return 2

    def _climb(self, L: Lemming) -> None:
        t = self.terrain
        L.frame += 1
        if L.frame % self._climb_period():
            return
        if t.solid(L.x, L.y - CLIMB_HEAD) or L.y < CLIMB_HEAD + 2:
            L.dir = -L.dir
            L.x += L.dir
            self._set(L, St.FALL)
            return
        L.y -= 1
        if not t.solid(L.x + L.dir, L.y - 1):
            self._set(L, St.HOIST)

    def _brick_ticks(self) -> int:
        bt = BRICK_TICKS * (2 if self.rule_off("slowskills") else 1)
        if self.cantica == "purgatorio":
            bt += self.peso // 10
        return bt

    def _build(self, L: Lemming) -> None:
        t = self.terrain
        if self._in_block_field(L):
            L.dir = -L.dir
            self._set(L, St.WALK)
            return
        L.frame += 1
        if L.frame < self._brick_ticks():
            return
        L.frame = 0
        t.add_row(L.x, L.x + 5 * L.dir, L.y - 1)
        L.bricks -= 1
        self.events.append("brick" if L.bricks >= 3 else "warn")
        if t.solid(L.x + L.dir, L.y - 2) or t.solid(L.x + 2 * L.dir, L.y - 2) or t.solid(L.x, L.y - CLIMB_HEAD):
            L.dir = -L.dir
            self._set(L, St.WALK)
            return
        L.x += 2 * L.dir
        L.y -= 1
        if L.bricks <= 0:
            self._set(L, St.SHRUG)

    def _bash(self, L: Lemming) -> None:
        t = self.terrain
        if self._in_block_field(L):
            L.dir = -L.dir
            self._set(L, St.WALK)
            return
        L.frame = (L.frame + 1) % BASH_CYCLE
        if L.frame not in BASH_MOVES:
            return
        mask = BASH_MASK if L.dir > 0 else BASH_MASK[:, ::-1]
        x0 = L.x + 1 if L.dir > 0 else L.x - 5
        ahead = np.ones((9, BASH_LOOKAHEAD), dtype=bool)
        if not t.any_solid(L.x + 1 if L.dir > 0 else L.x - BASH_LOOKAHEAD, L.y - 9, ahead):
            self._set(L, St.WALK)
            return
        if t.blocked(x0, L.y - 9, mask, L.dir):
            self.events.append("ting")
            L.dir = -L.dir
            self._set(L, St.WALK)
            return
        if t.erase(x0, L.y - 9, mask, L.dir) and L.frame in (3, 11):
            self.emit(("dust", L.x + 4 * L.dir, L.y - 5))
        L.x += L.dir
        if not t.solid(L.x, L.y):
            for d in range(1, STEP_DOWN + 1):
                if t.solid(L.x, L.y + d):
                    L.y += d
                    return
            self._set(L, St.FALL)

    def _mine(self, L: Lemming) -> None:
        t = self.terrain
        if self._in_block_field(L):
            L.dir = -L.dir
            self._set(L, St.WALK)
            return
        L.frame += 1
        if L.frame < MINE_TICKS * (2 if self.rule_off("slowskills") else 1):
            return
        L.frame = 0
        mask = MINE_MASK if L.dir > 0 else MINE_MASK[:, ::-1]
        x0 = L.x if L.dir > 0 else L.x - 5
        if t.blocked(x0, L.y - 9, mask, L.dir):
            self.events.append("ting")
            L.dir = -L.dir
            self._set(L, St.WALK)
            return
        t.erase(x0, L.y - 9, mask, L.dir)
        self.emit(("dust", L.x + 3 * L.dir, L.y - 2))
        L.x += 2 * L.dir
        L.y += 1
        if not t.solid(L.x, L.y):
            self._set(L, St.FALL)

    def _dig(self, L: Lemming) -> None:
        t = self.terrain
        L.frame += 1
        if L.frame < DIG_TICKS * (2 if self.rule_off("slowskills") else 1):
            return
        L.frame = 0
        if t.blocked(L.x - 4, L.y, DIG_MASK, 0):
            self.events.append("ting")
            self._set(L, St.WALK)
            return
        t.erase(L.x - 4, L.y, DIG_MASK, 0)
        if L.y % 3 == 0:
            self.emit(("dust", L.x, L.y))
        # el sepulturero entierra los focos que encuentra
        self.focos = [f for f in self.focos if (f[0] - L.x) ** 2 + (f[1] - L.y) ** 2 > 18 * 18]
        self.corpses = [c for c in self.corpses if (c[0] - L.x) ** 2 + (c[1] - L.y) ** 2 > 18 * 18]
        L.y += 1
        if not t.solid(L.x, L.y):
            self._set(L, St.FALL)

    # ── muertes, salidas, explosiones ────────────────────────────────────
    def _kill(self, L: Lemming, cause: St | None = None) -> None:
        if L.removed:
            return
        L.removed = True
        if L.maestro:
            self.say("Ha caído el Maestro. La Compagnia, sin pastor, corre en pánico.", "")
            self.peso += 1
            self.notes.append("El Maestro murió por negligencia: +1 de Peso")
            if not self.combo:
                self.panic = PANIC_TICKS
            self.events.append("panic")
            return
        self.dead += 1
        if cause == St.PLAGUE:
            self.corpses.append([L.x, self.ry(L), 0])
        if "resurrect" in self.mods and not self.resurrected and self.soul is None and cause in (St.SPLAT, St.DROWN, St.BURN):
            y = L.y if cause != St.DROWN else L.y - 8
            self.soul = [L.x, y, 12 * TPS, L.id, L.inv]
        if "pairs" in self.mods and not L.child and cause != St.OHNO:
            mate = self.by_id.get(L.id ^ 1)
            # el oficio salva: un disciplinato ocupado no muere de pena
            if mate is not None and not mate.removed and mate.state in (St.WALK, St.FALL, St.FLOAT):
                self._set(mate, St.PLAGUE)
                self.say("Filostrato suspira: los amantes no se separan.", "Filostrato")

    def _explode(self, L: Lemming) -> None:
        r = BOMB_RADIUS
        self.terrain.erase(L.x - r, L.y - 6 - r, BOMB_MASK, 0)
        self.events.append("boom")
        self.emit(("boom", L.x, L.y - 6))
        # el bubón esparce la peste
        for o in self.lemmings:
            if o is not L and not o.removed and not o.immune and not o.child and o.moria == 0:
                if (o.x - L.x) ** 2 + (self.ry(o) - self.ry(L)) ** 2 < 20 * 20 and self.rng.random() < 0.25:
                    o.moria = 1
        self._kill(L, St.OHNO)

    def _moria(self, L: Lemming) -> None:
        if L.immune > 0:
            L.immune -= 1
        if not L.moria or L.state in DOOMED:
            return
        L.moria_t += 2 if L.fervor > FERVOR_SLOW else 1
        if L.moria == 1 and L.moria_t > FEBBRE_TICKS:
            L.moria, L.moria_t = 2, 0
            self.emit(("bubo", L.x, L.y - 6))
        elif L.moria == 2 and L.moria_t > BUBBONE_TICKS:
            L.bomb = None
            self._set(L, St.PLAGUE)
            self.events.append("drown")

    def _contagion(self) -> None:
        sick = [L for L in self.lemmings if L.moria and not L.removed and L.state not in DOOMED]
        sources: list[tuple[int, int, int, float, int]] = []
        k = 2.0 if "moria2" in self.mods else 1.0
        for L in sick:
            r = 5 if L.moria == 1 else 12
            if L.state == St.BLOCK:
                r *= 2
            sources.append((L.x, self.ry(L), r, (0.015 if L.moria == 1 else 0.03) * k, L.id))
        for fx, fy in self.focos:
            sources.append((fx, fy, 12, 0.05 * k, -1))
        for rx, ry, _ in self.rats:
            sources.append((rx, ry, 6, 0.12 * k, -1))
        if not sources:
            return
        for L in self.lemmings:
            if L.removed or L.moria or L.immune or L.child or L.state in DOOMED:
                continue
            for sx, sy, r, p, sid in sources:
                if "pairs_safe" in self.mods and sid >= 0 and sid ^ 1 == L.id:
                    continue
                if (L.x - sx) ** 2 + (self.ry(L) - sy) ** 2 <= r * r:
                    q = p * (1 + 0.5 * min(2.0, L.fervor / FERVOR_SLOW))
                    if self.rng.random() < q:
                        L.moria, L.moria_t = 1, 0
                        self.fx.append(("infect", L.x, self.rmid(L) - 2))
                        break

    def _medici(self) -> None:
        """Los médicos de la peste curan a quien pasa a su lado y apagan los focos."""
        docs = [L for L in self.lemmings if L.medico and not L.removed and L.state not in DOOMED]
        if not docs:
            return
        r2 = MEDICO_RANGE * MEDICO_RANGE
        for D in docs:
            dx, dy = D.x, self.ry(D)
            for L in self.lemmings:
                if L.moria and not L.removed and L.state not in DOOMED and (L.x - dx) ** 2 + (self.ry(L) - dy) ** 2 <= r2:
                    L.moria = L.moria_t = 0
                    L.immune = max(L.immune, IMMUNE_TICKS)
                    self.cured += 1
                    self.fx.append(("cure", L.x, self.rmid(L)))
                    self.events.append("cure")
            n = len(self.focos) + len(self.corpses)
            self.focos = [f for f in self.focos if (f[0] - dx) ** 2 + (f[1] - dy) ** 2 > r2]
            self.corpses = [c for c in self.corpses if (c[0] - dx) ** 2 + (c[1] - dy) ** 2 > r2]
            if len(self.focos) + len(self.corpses) < n:
                self.fx.append(("cure", dx, dy - 4))

    def _rats(self) -> None:
        if not self.rats or self.tick_count % 2:
            return
        t = self.terrain
        for r in self.rats:
            nx = r[0] + r[2]
            if not (0 < nx < t.w - 1) or t.solid(nx, r[1] - 2) or not t.solid(nx, r[1]) and not t.solid(nx, r[1] + 1):
                r[2] = -r[2]
                continue
            r[0] = nx
            if not t.solid(nx, r[1]):
                r[1] += 1
            elif t.solid(nx, r[1] - 1):
                r[1] -= 1

    def vent_on(self, v: list) -> bool:
        return (self.tick_count + v[0] * 3) % 170 < 22

    def boulder_moving(self, b: list) -> bool:
        span = (b[1] - b[0]) // 2 + 1
        return (self.tick_count + b[0]) % (span + 9 * TPS) < span

    def _vents_boulders(self) -> None:
        for b in self.boulders:
            if self.boulder_moving(b):
                b[3] += 2 * b[4]
                if b[3] >= b[1] or b[3] <= b[0]:
                    b[3] = max(b[0], min(b[1], b[3]))
                    b[4] = -b[4]
        if not self.vents and not self.boulders:
            return
        for L in self.lemmings:
            if L.removed or L.state in DOOMED or L.inv:
                continue
            for v in self.vents:
                if self.vent_on(v) and v[0] <= L.x <= v[1] and abs(L.y - v[2]) <= 2:
                    self._set(L, St.BURN)
                    self.events.append("burn")
                    self.emit(("fire", L.x, L.y - 4))
                    break
            else:
                for b in self.boulders:
                    if self.boulder_moving(b) and abs(L.x - b[3]) < 7 and b[2] - 16 <= L.y <= b[2] + 1:
                        self._set(L, St.SPLAT)
                        self.events.append("trap")
                        self.emit(("blood", L.x, L.y))
                        break

    def _guards(self) -> None:
        for g in self.guards:
            g.anim += 1
            if g.pacified:
                continue
            auto = GUARDS[g.kind][2]
            if not g.touched:
                for L in self.lemmings:
                    if not L.removed and L.inv == g.inv and abs(L.x - g.x) < 30 and abs(L.y - g.y) < 10:
                        g.touched = True
                        self.say(GUARDS[g.kind][3], g.name)
                        break
            if g.kind == "catone" and self.giunco:
                self._pacify(g, "Catón ve el junco ceñido: «Va dunque, e fa che tu costui ricinghe / d'un giunco schietto» (Purg. I).")
            elif auto and g.touched:
                g.timer += 1
                if g.timer >= auto * TPS:
                    if g.kind == "furie":
                        self._pacify(g, "Llega el messo del cielo: la puerta de Dite se abre con una varita.")
                    else:
                        self._pacify(g, "{name}: «Pasad». La espera era la prueba.")

    def _corpses(self) -> None:
        for c in self.corpses:
            c[2] += 1
            if c[2] == FOCO_TICKS:
                self.focos.append((c[0], c[1]))
                self.emit(("foco", c[0], c[1]))
        self.corpses = [c for c in self.corpses if c[2] < FOCO_TICKS]

    def _souls(self) -> None:
        if self.soul is None:
            return
        self.soul[2] -= 1
        if self.soul[2] <= 0:
            self.soul = None
            return
        sx, sy = self.soul[0], self.soul[1]
        for L in self.lemmings:
            if not L.removed and L.state == St.WALK and L.inv == self.soul[4] and abs(L.x - sx) < 8 and abs(L.y - sy) < 10:
                nid = 20_000 + self.soul[3]
                R = Lemming(nid, L.x, L.y, -L.dir, St.WALK, inv=L.inv)
                self._add(R)
                self.dead -= 1
                self.resurrected = True
                self.soul = None
                self.fx.append(("grace", L.x, self.rmid(L)))
                self.say("Filomena: «infortunio con final feliz». Un alma vuelve a la fila.", "Filomena")
                break

    def _hazards(self, L: Lemming) -> None:
        if L.state in DOOMED:
            return
        t = self.terrain
        if L.y >= t.h + 8:
            self._kill(L, St.SPLAT)
            return
        if L.carry is not None:
            return
        if self.ry(L) > self.fire_y:
            self._set(L, St.BURN)
            self.events.append("burn")
            self.emit(("fire", L.x, L.y - 4))
            return
        hy = L.y - 1
        if 0 <= L.x < t.w and 0 <= hy < t.h and "nodeath" not in self.mods:
            hz = self.hazard[hy, L.x]
            if hz == HZ_LIQUID:
                L.bomb = None
                self._set(L, St.DROWN)
                self.events.append("drown")
                self.emit(("splash", L.x, L.y))
                return
            if hz == HZ_FIRE or (hz == HZ_PURGE and L.state != St.WALK):
                L.bomb = None
                self._set(L, St.BURN)
                self.events.append("burn")
                self.emit(("fire", L.x, L.y - 4))
                return
            if hz == HZ_FLIP and not L.inv:
                # el centro de la Tierra: «io levai li occhi e credetti veder Lucifero com'io l'avea lasciato»
                L.inv = True
                L.y = VIEW_H - 1 - (L.y - 6)
                self._set(L, St.FALL)
                self.fx.append(("grace", L.x, VIEW_H - 1 - L.y))
                if not self.flame_said:
                    self.flame_said = True
                    self.say("«Attienti ben, ché per cotali scale… conviensi dipartir da tanto male.» Ahora el suelo es el techo.", "Virgilio")
                return
            if hz == HZ_PURGE:
                if L.moria:
                    self.emit(("cure", L.x, L.y - 6))
                L.moria = L.moria_t = 0
                L.fervor = 0
                if not L.purified:
                    L.purified = True
                    if not self.purge_paid:
                        self.purge_paid = True
                        self.peso = max(0, self.peso - 10)
                        self.notes.append("Atravesó el muro de fuego: −10 de Peso")
                        self.say("Quien cruza el fuego entero sale limpio. Quien se para, arde.", "Virgilio")
        if L.state == St.WALK and not L.inv:
            for ax, ay in self.anteo:
                if abs(L.x - ax) <= 2 and abs(L.y - ay) <= 2:
                    dx = ax + 18 * L.dir
                    dy = self._floor_at(min(max(dx, 0), self.tn.w - 1)) or L.y
                    L.carry = [0, L.x, L.y, dx, dy]
                    self.events.append("door")
                    return
            if self.trees and not L.stared:
                for tx, _ in self.trees:
                    if abs(L.x - tx) <= 1:
                        L.stared = True
                        L.stare = STARE_TICKS
            for s in self.sabios:
                if not s[4] and abs(L.x - s[0]) < 6:
                    s[4] = True
                    self.say(s[3], s[2])
        if L.state in EXITABLE:
            for e in self.exits:
                if e.inv == L.inv and abs(L.x - e.x) <= 3 and e.y - 8 <= L.y <= e.y + 1:
                    if self.level.special == "primum" and self.peso > 0 and not L.maestro:
                        # con Peso no se asciende: cada alma que llega quema un punto y vuelve
                        self.peso -= 1
                        L.dir = -L.dir
                        L.x += 4 * L.dir
                        self.emit(("cure", L.x, L.y - 8))
                        if not self.primum_said:
                            self.primum_said = True
                            self.say("Con Peso no se asciende: cada alma que llega quema un punto ({n} restantes).", "Beatrice",
                                     n=self.peso)
                        return
                    L.bomb = None
                    self._set(L, St.EXIT)
                    return
        if self.child is not None and not L.maestro and not L.inv and abs(L.x - self.child[0]) < 6 and abs(L.y - self.child[1]) < 8:
            cx, cy = self.child
            self.child = None
            C = Lemming(30_000, cx, cy, L.dir, St.WALK, child=True, immune=10**9)
            self._add(C)
            self.total += 1
            self.released += 1
            self.say("Un niño huérfano de la peste se une a la fila. Se llama Michelangelo. (Licencia: Milán, 1577.)", "")
            self.events.append("pagina")
        if self.level.special == "flame" and not self.flame_said and L.maestro and L.x > self.terrain.w // 2:
            self.flame_said = True
            self.say("Una de las llamas habla con la voz del Maestro. Dice que él solo dio consejo.", "")
        if self.lume:
            lx, ly, _ = self.lume
            # haz diagonal de arriba-derecha a abajo-izquierda que pasa por (lx, ly)
            d = abs((L.x - lx) + (self.ry(L) - ly)) / 1.4142
            if d < 22:
                L.fervor = 0

    def _boat_paint(self, x0: int, x1: int, y: int, on: bool) -> None:
        t = self.tn
        x0, x1 = max(0, x0), min(t.w, x1)
        if x0 >= x1:
            return
        reg = t.k[y : y + 4, x0:x1]
        if on:
            m = reg == AIR
            reg[m] = DIRT
            shade = np.array([(120, 84, 50), (100, 70, 42), (86, 60, 36), (60, 42, 28)], dtype=np.uint8)
            for k in range(4):
                row = t.c[y + k, x0:x1]
                row[m[k]] = shade[k]
        else:
            reg[reg == DIRT] = AIR
        t._mark(x0, y, x1, y + 4)

    def _boats(self) -> None:
        """Inf. VIII: la barca de Flegias va y viene por la Estigia; quien está encima viaja."""
        if not self.boats:
            return
        for b in self.boats:
            x, y = b["x"], b["y"]
            # Flegias, en la orilla de salida, no zarpa sin el óbolo
            held = any(g.kind == "flegias" and not g.pacified and g.x < b["xa"] for g in self.guards)
            if b["wait"] > 0:
                b["wait"] -= 1
            elif not held:
                d = b["dir"]
                for L in self.lemmings:
                    if not L.removed and not L.inv and L.y == y and x <= L.x < x + 24 and L.state not in AIRBORNE:
                        L.x += d
                if d > 0:
                    self._boat_paint(x, x + 1, y, False)
                    self._boat_paint(x + 24, x + 25, y, True)
                else:
                    self._boat_paint(x + 23, x + 24, y, False)
                    self._boat_paint(x - 1, x, y, True)
                b["x"] = x = x + d
                if x in (b["xa"], b["xb"]):
                    b["dir"] = -d
                    b["wait"] = 45
            at_left, at_right = x == b["xa"], x == b["xb"]
            if not at_left:
                self.blockers.append((b["xa"], y, BLOCK_RANGE, False))  # muelle izquierdo
                self.blockers.append((x - 1, y, BLOCK_RANGE, False))  # proa
            if not at_right:
                self.blockers.append((b["xb"] + 23, y, BLOCK_RANGE, False))  # muelle derecho
                self.blockers.append((x + 24, y, BLOCK_RANGE, False))  # popa

    def _snakes(self) -> None:
        """Inf. XXIV–XXV: entre los ladrones, quien toca una serpiente se vuelve serpiente."""
        if not self.snakes:
            return
        t = self.tn
        if self.tick_count % 3 == 0:
            for r in self.snakes:
                nx = r[0] + r[2]
                if not (0 < nx < t.w - 1) or t.solid(nx, r[1] - 2) or not t.solid(nx, r[1]) and not t.solid(nx, r[1] + 1):
                    r[2] = -r[2]
                    continue
                r[0] = nx
                if not t.solid(nx, r[1]):
                    r[1] += 1
                elif t.solid(nx, r[1] - 1):
                    r[1] -= 1
        for L in self.lemmings:
            if L.removed or L.inv or L.state != St.WALK or L.maestro or L.child:
                continue
            for r in self.snakes:
                if abs(L.x - r[0]) <= 3 and abs(L.y - r[1]) <= 3 and self.rng.random() < 0.004:
                    self.fx.append(("infect", L.x, L.y - 6))
                    self._kill(L, St.SPLAT)
                    if len(self.snakes) < 5:
                        self.snakes.append([L.x, L.y, -L.dir])
                    if not self.snake_said:
                        self.snake_said = True
                        self.say("Un ladrón se vuelve serpiente (Inf. XXV).", "Virgilio")
                    break

    def _phantoms(self) -> None:
        if not self.phantoms:
            return
        t = self.tn
        for ph in self.phantoms:
            x0, y0, x1, y1 = ph["r"]
            if ph["kind"] == "blink":
                want = (self.tick_count % (BLINK_ON + BLINK_OFF)) < BLINK_ON
            else:
                lit = False
                if self.lume:
                    lx, ly, _ = self.lume
                    lit = abs(((x0 + x1) / 2 - lx) + ((y0 + y1) / 2 - ly)) / 1.4142 < 40
                want = lit or self.reveal or self.dioneo > 0
            if want == ph["on"]:
                continue
            ph["on"] = want
            reg = t.k[y0:y1, x0:x1]
            if want:
                m = reg == AIR
                reg[m] = DIRT
                col = (200, 214, 240) if ph["kind"] == "blink" else (240, 220, 170)
                t.c[y0:y1, x0:x1][m] = col
                ph["mask"] = m
            elif ph["mask"] is not None:
                reg[ph["mask"] & (reg == DIRT)] = AIR
            t._mark(x0, y0, x1, y1)

    def _banner(self) -> None:
        """Antinferno: los ignavos corren tras un estandarte que no va a ninguna parte."""
        b = self.banner
        if b is None:
            return
        b[2] -= 1
        if b[2] <= 0:
            self.banner = None
            self.say("El estandarte se pierde en la niebla. Los ignavos se quedan sin nadie a quien seguir.", "Virgilio")
            return
        b[0] += 0.6 * b[1]
        lo, hi = self.entrances[0].x + 40, self.tn.w * 0.55
        if b[0] > hi or b[0] < lo:
            b[1] = -b[1]

    def _venus(self) -> None:
        walkers = [L for L in self.lemmings if not L.removed and L.state == St.WALK]
        buckets: dict[tuple[int, int], int] = {}
        for L in walkers:
            k = (L.x // 24, self.ry(L) // 24)
            buckets[k] = buckets.get(k, 0) + 1
        self.lonely = set()
        for L in walkers:
            bx, by = L.x // 24, self.ry(L) // 24
            n = sum(buckets.get((bx + dx, by + dy), 0) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            if n <= 1:
                self.lonely.add(L.id)

    def _firerain(self) -> None:
        """Inf. XIV: «piovean di foco dilatate falde». Lo que es sólido las apaga."""
        if "firerain" not in self.mods:
            return
        t = self.tn
        if self.rng.random() < 0.06 * t.w / VIEW_W:
            self.drops.append([int(self.rng.integers(0, t.w)), 0])
        alive = []
        for d in self.drops:
            hit = False
            for _ in range(4):
                d[1] += 1
                if t.solid(d[0], d[1]):
                    hit = True
                    break
            if hit:
                if d[1] > 2:
                    self.fx.append(("fire", d[0], d[1] - 2))
                continue
            for L in self.lemmings:
                if (not L.removed and not L.inv and L.state not in DOOMED and abs(L.x - d[0]) <= 2
                        and L.y - 12 <= d[1] <= L.y):
                    L.bomb = None
                    self._set(L, St.BURN)
                    self.events.append("burn")
                    self.fx.append(("fire", L.x, L.y - 4))
                    hit = True
                    break
            if not hit and d[1] < t.h:
                alive.append(d)
        self.drops = alive

    def _pickups(self, L: Lemming) -> None:
        for p in self.pickups:
            if p.taken or p.inv != L.inv or abs(L.x - p.x) > 5 or not (L.y - 14 <= p.y <= L.y + 2):
                continue
            if p.kind == "oficio":
                p.taken = True
                s = Skill(p.artist)
                self.skills[s] += 1
                self.emit(("pickup", p.x, p.y - 6, (190, 230, 190)))
                self.events.append("pagina")
                self.say("Neifile: «con ingenio». Un {skill} más escondido en el camino.", "Neifile", skill=SKILL_NAMES[s])
                continue
            if p.kind == "pagina":
                p.taken = True
                self.pagina = True
                self.events.append("pagina")
                self.emit(("pickup", p.x, p.y - 6, (250, 240, 200)))
                self.say("Una pagina salvada de las llamas.", "")
                continue
            if p.kind == "giunco":
                p.taken = True
                self.giunco = True
                self.events.append("pagina")
                continue
            if p.fake:
                p.taken = True
                self.peso += 1
                self.notes.append("Palla falsa: +1 de Peso")
                self.say("Era falsa. Lauretta se ríe: «burla en general».", "Lauretta")
                self.events.append("ting")
                continue
            if p.kind == "giglio" and "giglio" in self.shield:
                continue
            if len(self.shield) >= self.slots:
                if not p.need:
                    continue
                # la que exige el guardián entra siempre: otra cede su hueco
                out = next((k for k, q in enumerate(self.shield) if q != "giglio"), 0)
                gone = self.shield.pop(out)
                self.say("El escudo está lleno: la {palla} cede su hueco.", "", palla=PALLE_INFO[gone][0])
            p.taken = True
            self.shield.append(p.kind)
            if p.kind == "mecenate":
                self.art_queue.append(p.artist or "caravaggio")
            self.emit(("pickup", p.x, p.y - 6, PALLE_INFO[p.kind][2]))
            self.events.append("coin")
            if self.level.sky == "mercurio":
                self.peso += 1
                self.notes.append("Mercurio: la gloria pesa (+1)")
            self.pick_times.append(self.tick_count)
            while self.pick_times and self.pick_times[0] < self.tick_count - COMBO_WINDOW:
                self.pick_times.popleft()
            if len(self.pick_times) >= 3:
                self.pick_times.clear()
                self.combo = COMBO_TICKS
                self.combo_hit = True
                self.panic = 0
                self.events.append("combo")
                self.say("«Palle, palle, palle!» La Compagnia corre al doble.", "")


# ═══════════════════════════════════════════════════════════════════════════
# Autopiloto (soluciones de referencia) y repeticiones
# ═══════════════════════════════════════════════════════════════════════════


class Autopilot:
    def __init__(self, rules: tuple[Rule, ...]):
        self.rules = rules
        self.left = [r.n for r in rules]
        self.done_at: dict[int, int] = {}

    def step(self, world: World, apply) -> None:
        for tr in sorted({r.track for r in self.rules}):
            prev = 0
            for i, r in enumerate(self.rules):
                if r.track != tr:
                    continue
                if self.left[i] <= 0:
                    prev = self.done_at[i]
                    continue
                if world.tick_count >= prev + r.delay:
                    self._try(i, r, world, apply)
                    if self.left[i] <= 0:
                        prev = self.done_at[i]
                        continue
                if self.left[i] > 0 and not r.par:
                    break

    def _done(self, i: int, world: World) -> None:
        self.left[i] = 0
        self.done_at[i] = world.tick_count

    def _try(self, i: int, r: Rule, world: World, apply) -> None:
        if r.rr is not None:
            apply(("rr", r.rr))
            self._done(i, world)
            return
        if r.palla is not None:
            g = world.guards[r.guard]
            if g.pacified:
                self._done(i, world)
                return
            if r.palla in world.shield and apply(("palla", world.shield.index(r.palla), g.x, g.y - 10)):
                self._done(i, world)
            return
        if r.skill is None or not world.has_skill(r.skill):
            return
        for L in world.lemmings:
            if self.left[i] <= 0:
                break
            if L.removed or (r.state and L.state != r.state):
                continue
            if r.x is not None and abs(L.x - r.x) > r.win:
                continue
            if r.dir and L.dir != r.dir:
                continue
            if not r.y[0] <= L.y <= r.y[1]:
                continue
            if world.can_assign(L, r.skill) and apply(("assign", L.id, str(r.skill))):
                self.left[i] -= 1
                if self.left[i] <= 0:
                    self.done_at[i] = world.tick_count


class Replay:
    def __init__(self, commands: list[list]):
        self.cmds = sorted(commands, key=lambda c: c[0])
        self.pos = 0

    def step(self, world: World, apply) -> None:
        while self.pos < len(self.cmds) and self.cmds[self.pos][0] <= world.tick_count:
            apply(tuple(self.cmds[self.pos][1:]))
            self.pos += 1


def simulate(idx: int, pilot=None, camp: Campaign | None = None) -> tuple[World, list[list]]:
    """Juega un nivel sin ventana. Devuelve el mundo final y las órdenes grabadas."""
    world = World(get_level(idx), camp)
    log: list[list] = []

    def apply(cmd: Command) -> bool:
        ok = world.do(cmd)
        if ok:
            log.append([world.tick_count, *cmd])
        return ok

    while not world.done and not (world.compagnia_done and world.maestro_out):
        if pilot:
            pilot.step(world, apply)
        world.tick()
    return world, log


# ═══════════════════════════════════════════════════════════════════════════
# 6. RENDER — tenebrismo dinámico, bloom, parallax, atmósfera
# ═══════════════════════════════════════════════════════════════════════════


def _surface_from_rows(rows: list[str]) -> pygame.Surface:
    w = max(len(r) for r in rows)
    surf = pygame.Surface((w, len(rows)), pygame.SRCALPHA)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                surf.set_at((x, y), PALETTE[ch])
    return surf


def _outlined(img: pygame.Surface, color=(12, 6, 8, 150)) -> pygame.Surface:
    """Contorno de 1 px: legibles sobre la roca del Infierno y sobre el oro del Paraíso."""
    w, h = img.get_size()
    out = pygame.Surface((w + 2, h + 2), pygame.SRCALPHA)
    sil = pygame.mask.from_surface(img).to_surface(setcolor=color, unsetcolor=(0, 0, 0, 0))
    for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2)):
        out.blit(sil, (dx, dy))
    out.blit(img, (1, 1))
    return out


class Sprites:
    def __init__(self) -> None:
        self.sets = {}
        for key, src in (("w", SPRITE_SRC), ("m", MAESTRO_SRC), ("c", CHILD_SRC)):
            right = {k: [_outlined(_surface_from_rows(f)) for f in v] for k, v in src.items()}
            left = {k: [pygame.transform.flip(s, True, False) for s in v] for k, v in right.items()}
            self.sets[key] = (right, left)
        self.digits = {d: _surface_from_rows([r.replace("1", "Y").replace("0", ".") for r in rows]) for d, rows in DIGITS.items()}
        self.tint_cache: dict[tuple, pygame.Surface] = {}

    def get(self, name: str, i: int, d: int, who: str = "w") -> pygame.Surface:
        right, left = self.sets[who]
        frames = (right if d > 0 else left)[name]
        return frames[i % len(frames)]

    def tinted(self, img: pygame.Surface, color: tuple[int, int, int]) -> pygame.Surface:
        key = (id(img), color)
        s = self.tint_cache.get(key)
        if s is None:
            s = img.copy()
            s.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
            self.tint_cache[key] = s
        return s


def sprite_of(L: Lemming, tick: int) -> tuple[str, int, int]:
    f = L.frame
    match L.state:
        case St.WALK:
            if L.fervor > FERVOR_SLOW // 2 and (tick + L.id * 7) % 40 < 10:
                return "whip", (tick // 3) % 2, 0
            return "walk", (tick + L.id) // 2, 0
        case St.FALL:
            return "fall", tick // 2, 0
        case St.FLOAT:
            return "float", tick // 4, 0
        case St.CLIMB:
            return "climb", L.y // 2, 0
        case St.HOIST:
            return "climb", 1, 0
        case St.BLOCK:
            return "block", tick // 5, 0
        case St.BUILD:
            return "build", 0 if f < BRICK_TICKS // 2 else 1, 0
        case St.SHRUG:
            return "shrug", 0, 0
        case St.BASH:
            return "bash", f // 4, 0
        case St.MINE:
            return "mine", 0 if f < MINE_TICKS // 2 else 1, 0
        case St.DIG:
            return "dig", tick // 2, 0
        case St.OHNO:
            return "ohno", tick // 2, 0
        case St.SPLAT:
            return "splat", min(2, f * 3 // SPLAT_TICKS), 0
        case St.DROWN:
            return "fall", tick // 2, f // 2
        case St.BURN | St.PLAGUE:
            return "ohno", tick, f // 4 if L.state == St.PLAGUE else 0
        case St.FROZEN:
            return "frozen", 0, 0
        case St.EXIT:
            return "walk", tick // 2, 0
    return "walk", 0, 0


@lru_cache(maxsize=256)
def light_sprite(r: int, color: tuple[int, int, int], soft: float = 2.0) -> pygame.Surface:
    """Disco de luz con caída suave (aditivo, sobre negro)."""
    r = max(2, r)
    yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
    d = np.sqrt(xx * xx + yy * yy) / r
    f = np.clip(1 - d, 0, 1) ** soft
    rgb = (np.array(color, dtype=float)[None, None, :] * f[..., None]).clip(0, 255).astype(np.uint8)
    surf = pygame.Surface((2 * r + 1, 2 * r + 1))
    pygame.surfarray.blit_array(surf, rgb.transpose(1, 0, 2))
    return surf


def vertical_gradient(w: int, h: int, top, bot, mid=None) -> pygame.Surface:
    t = np.linspace(0, 1, h)[:, None]
    a, b = np.array(top, float), np.array(bot, float)
    if mid is not None:
        m = np.array(mid, float)
        col = np.where(t < 0.5, a + (m - a) * (t / 0.5), m + (b - m) * ((t - 0.5) / 0.5))
    else:
        col = a + (b - a) * t
    arr = np.broadcast_to(col[:, None, :], (h, w, 3)).clip(0, 255).astype(np.uint8)
    surf = pygame.Surface((w, h))
    pygame.surfarray.blit_array(surf, arr.transpose(1, 0, 2))
    return surf


@lru_cache(maxsize=32)
def cached_gradient(w: int, h: int, top, bot) -> pygame.Surface:
    """Degradado inmutable para la interfaz (no pintar encima)."""
    return vertical_gradient(w, h, top, bot)


def ridge(rng: random.Random, w: int, base: float, amp: float, rough: float = 0.5) -> list[float]:
    """Perfil 1D por desplazamiento de punto medio (montañas, bóvedas)."""
    n = 1
    while n < w:
        n *= 2
    pts = [base] * (n + 1)
    pts[0], pts[n] = base + rng.uniform(-amp, amp), base + rng.uniform(-amp, amp)
    step, a = n, amp
    while step > 1:
        half = step // 2
        for i in range(half, n, step):
            pts[i] = (pts[i - half] + pts[i + half]) / 2 + rng.uniform(-a, a)
        step = half
        a *= rough
    return pts[:w]


def _hatch(surf: pygame.Surface, color, spacing: int = 3, alpha: int = 40) -> None:
    """Rayado diagonal de grabado (Doré) sobre lo que ya hay pintado."""
    w, h = surf.get_size()
    hat = pygame.Surface((w, h), pygame.SRCALPHA)
    for x in range(-h, w, spacing):
        pygame.draw.line(hat, (*color, alpha), (x, h), (x + h, 0))
    mask = pygame.mask.from_surface(surf, 8)
    ms = mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
    hat.blit(ms, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(hat, (0, 0))


SKIES = {
    "luna": ((200, 214, 236), (240, 244, 252), (150, 170, 210)),
    "mercurio": ((220, 210, 190), (252, 246, 228), (190, 170, 140)),
    "venere": ((246, 200, 210), (255, 236, 240), (220, 140, 170)),
    "sole": ((255, 226, 140), (255, 250, 220), (250, 190, 70)),
    "marte": ((236, 150, 120), (255, 222, 200), (210, 80, 60)),
    "giove": ((220, 230, 246), (252, 252, 255), (170, 190, 230)),
    "saturno": ((190, 210, 220), (236, 244, 248), (130, 160, 180)),
    "stelle": ((20, 24, 60), (90, 90, 150), (240, 230, 180)),
    "primum": ((255, 255, 250), (255, 255, 255), (250, 240, 200)),
    "empireo": ((255, 246, 220), (255, 255, 248), (255, 220, 160)),
    "visione": ((255, 250, 236), (255, 255, 255), (255, 230, 170)),
}


class Backdrop:
    """Fondos pintados por capas (lejos/medio) que se desplazan en parallax."""

    def __init__(self, world_w: int, theme: Theme, sky: str, seed: int):
        self.theme = theme
        self.sky = sky
        rng = random.Random(seed)
        self.far_w = int(VIEW_W + (world_w - VIEW_W) * 0.25) + 2
        self.mid_w = int(VIEW_W + (world_w - VIEW_W) * 0.55) + 2
        style = theme.bg
        top, bot = theme.sky_top, theme.sky_bot
        mid = None
        if style == "paradiso" and sky in SKIES:
            top, bot, _ = SKIES[sky]
        self.sky_s = vertical_gradient(VIEW_W, VIEW_H, top, bot, mid)
        self.night_s = vertical_gradient(VIEW_W, VIEW_H, (4, 6, 22), (30, 30, 60)) if style == "purgatorio" else None
        self.far = pygame.Surface((self.far_w, VIEW_H), pygame.SRCALPHA)
        self.mid = pygame.Surface((self.mid_w, VIEW_H), pygame.SRCALPHA)
        self.glows: list[tuple[int, int, int, tuple[int, int, int]]] = []  # luces del fondo (capa lejana)
        getattr(self, f"_paint_{style}", self._paint_inferno)(rng)

    # ── estilos ─────────────────────────────────────────────────────────
    def _stars(self, rng, n, surf=None, color=(220, 220, 255)):
        surf = surf or self.sky_s
        for _ in range(n):
            x, y = rng.randrange(VIEW_W), rng.randrange(int(VIEW_H * 0.7))
            c = rng.randint(120, 255)
            surf.set_at((x, y), (min(255, c * color[0] // 255), min(255, c * color[1] // 255), min(255, c * color[2] // 255)))

    def _mountains(self, surf, rng, base, amp, color, rough=0.55, top=False):
        w = surf.get_width()
        prof = ridge(rng, w, base, amp, rough)
        pts = [(x, int(prof[x])) for x in range(w)]
        if top:
            poly = [(0, 0)] + pts + [(w - 1, 0)]
        else:
            poly = [(0, VIEW_H)] + pts + [(w - 1, VIEW_H)]
        pygame.draw.polygon(surf, color, poly)
        return prof

    def _paint_inferno(self, rng):
        t = self.theme
        dark = tuple(max(0, c // 3) for c in t.sky_bot)
        self._mountains(self.far, rng, VIEW_H * 0.55, 70, (*dark, 255), 0.6)
        self._mountains(self.far, rng, VIEW_H * 0.18, 40, (*tuple(c // 4 for c in t.sky_top), 255), 0.6, top=True)
        # hogueras lejanas del embudo
        for _ in range(self.far_w // 70):
            x = rng.randrange(self.far_w)
            y = rng.randint(int(VIEW_H * 0.5), VIEW_H - 20)
            self.glows.append((x, y, rng.randint(26, 60), (255, 90, 30) if t.key != "cocito" else (90, 150, 255)))
        mid_col = tuple(max(0, c // 6) for c in t.dirt[0])
        self._mountains(self.mid, rng, VIEW_H * 0.72, 50, (*mid_col, 255), 0.5)
        self._mountains(self.mid, rng, VIEW_H * 0.1, 26, (*mid_col, 255), 0.65, top=True)
        # estalactitas en la capa media
        for _ in range(self.mid_w // 24):
            x = rng.randrange(self.mid_w)
            h = rng.randint(10, 60)
            pygame.draw.polygon(self.mid, (*mid_col, 255), [(x - 5, 0), (x + 5, 0), (x + rng.randint(-2, 2), h)])
        # condenados en la cresta, a lo Doré
        for _ in range(self.mid_w // 18):
            x = rng.randrange(self.mid_w)
            y = int(VIEW_H * 0.72) + rng.randint(-26, 16)
            pygame.draw.rect(self.mid, (*mid_col, 255), (x, y - 6, 2, 6))
            pygame.draw.circle(self.mid, (*mid_col, 255), (x + 1, y - 7), 1)
        _hatch(self.far, (0, 0, 0), 3, 60)
        _hatch(self.mid, (255, 120, 60) if t.veins else (200, 200, 230), 4, 18)

    _paint_malebolge = _paint_inferno
    _paint_tempesta = _paint_inferno

    def _paint_dite(self, rng):
        self._paint_inferno(rng)
        # murallas de Dite con torres incandescentes
        col = (40, 8, 6, 255)
        y0 = int(VIEW_H * 0.48)
        pygame.draw.rect(self.far, col, (0, y0, self.far_w, VIEW_H - y0))
        x = 0
        while x < self.far_w:
            w = rng.randint(14, 26)
            h = rng.randint(20, 60)
            pygame.draw.rect(self.far, col, (x, y0 - h, w, h))
            for k in range(0, w - 3, 5):
                pygame.draw.rect(self.far, col, (x + k, y0 - h - 4, 3, 4))
            if rng.random() < 0.6:
                self.glows.append((x + w // 2, y0 - h + 10, 18, (255, 70, 20)))
                pygame.draw.rect(self.far, (255, 120, 40, 255), (x + w // 2 - 1, y0 - h + 8, 2, 4))
            x += w + rng.randint(10, 40)

    def _paint_selva(self, rng):
        self._stars(rng, 140)
        pygame.draw.circle(self.sky_s, (220, 226, 240), (VIEW_W * 3 // 4, 50), 14)
        self.glows.append((VIEW_W * 3 // 4, 50, 70, (90, 110, 160)))
        for layer, col, n, hmin in ((self.far, (14, 20, 26, 255), 60, 120), (self.mid, (6, 10, 12, 255), 40, 160)):
            w = layer.get_width()
            self._mountains(layer, rng, VIEW_H * 0.85, 12, col, 0.5)
            for _ in range(w // 10):
                x = rng.randrange(w)
                h = rng.randint(hmin // 2, hmin)
                pygame.draw.line(layer, col, (x, VIEW_H), (x + rng.randint(-6, 6), VIEW_H - h), rng.randint(2, 5))
                for _b in range(5):
                    by = VIEW_H - rng.randint(h // 3, h)
                    pygame.draw.line(layer, col, (x, by), (x + rng.randint(-20, 20), by - rng.randint(4, 20)), 2)
        _hatch(self.far, (0, 0, 0), 3, 50)

    def _paint_limbo(self, rng):
        self._stars(rng, 60)
        self._mountains(self.far, rng, VIEW_H * 0.7, 24, (60, 60, 74, 255))
        # il nobile castello: siete muros, siete puertas
        cx, base = self.far_w // 2, int(VIEW_H * 0.68)
        for k in range(7):
            w = 160 - k * 18
            h = 18 + k * 9
            pygame.draw.rect(self.far, (90 + k * 8, 90 + k * 8, 104 + k * 8, 255), (cx - w // 2, base - h, w, h))
            for t in range(-w // 2, w // 2, 8):
                pygame.draw.rect(self.far, (90 + k * 8, 90 + k * 8, 104 + k * 8, 255), (cx + t, base - h - 3, 4, 3))
        self.glows.append((cx, base - 40, 90, (120, 120, 90)))
        self._mountains(self.mid, rng, VIEW_H * 0.86, 10, (46, 50, 46, 255))

    def _paint_firenze(self, rng):
        self._stars(rng, 50)
        base = int(VIEW_H * 0.7)
        col = (34, 22, 30, 255)
        x = 0
        while x < self.far_w:
            w, h = rng.randint(14, 34), rng.randint(16, 50)
            pygame.draw.rect(self.far, col, (x, base - h, w, VIEW_H))
            pygame.draw.polygon(self.far, col, [(x - 2, base - h), (x + w // 2, base - h - 8), (x + w + 2, base - h)])
            for wy in range(base - h + 6, base, 9):
                if rng.random() < 0.25:
                    pygame.draw.rect(self.far, (220, 140, 60, 255), (x + rng.randint(2, max(3, w - 4)), wy, 2, 3))
            x += w + rng.randint(0, 6)
        # Santa Maria del Fiore: la cúpula de Brunelleschi, el campanile y la torre de Arnolfo
        dx = self.far_w // 2
        pygame.draw.rect(self.far, col, (dx - 46, base - 46, 92, 46))
        pygame.draw.rect(self.far, col, (dx - 20, base - 66, 40, 22))
        pygame.draw.ellipse(self.far, col, (dx - 30, base - 116, 60, 104))
        pygame.draw.rect(self.far, col, (dx - 4, base - 128, 8, 14))
        pygame.draw.rect(self.far, col, (dx + 60, base - 120, 16, 120))
        pygame.draw.rect(self.far, col, (dx - 150, base - 138, 14, 138))
        pygame.draw.rect(self.far, col, (dx - 156, base - 150, 26, 14))
        for k in range(5):  # humo de las hogueras de la peste
            self.glows.append((rng.randrange(self.far_w), base + rng.randint(-10, 20), rng.randint(30, 70), (200, 80, 30)))
        self._mountains(self.mid, rng, VIEW_H * 0.92, 6, (16, 10, 14, 255))

    def _paint_cocito(self, rng):
        self._stars(rng, 90, color=(180, 220, 255))
        self._mountains(self.far, rng, VIEW_H * 0.45, 80, (20, 40, 80, 255), 0.6)
        self._mountains(self.far, rng, VIEW_H * 0.1, 30, (10, 20, 50, 255), 0.6, top=True)
        for _ in range(self.mid_w // 20):  # cristales de hielo
            x = rng.randrange(self.mid_w)
            h = rng.randint(20, 90)
            c = (40 + rng.randint(0, 40), 80 + rng.randint(0, 40), 140 + rng.randint(0, 60), 255)
            pygame.draw.polygon(self.mid, c, [(x - 6, VIEW_H), (x, VIEW_H - h), (x + 6, VIEW_H)])
            pygame.draw.line(self.mid, (200, 230, 255, 255), (x, VIEW_H - h), (x + 3, VIEW_H - h // 2))
        # Lucifero, inmenso, al fondo del pozo
        cx = self.far_w // 2
        pygame.draw.polygon(self.far, (8, 10, 24, 255), [(cx - 120, VIEW_H), (cx - 60, 60), (cx, 40), (cx + 60, 60), (cx + 120, VIEW_H)])
        for s in (-1, 1):
            pygame.draw.polygon(self.far, (12, 14, 30, 255),
                                [(cx + s * 40, 90), (cx + s * 200, 20), (cx + s * 170, 120), (cx + s * 220, 140), (cx + s * 60, 150)])
        for k, c in ((-24, (255, 40, 40)), (0, (40, 40, 40)), (24, (230, 220, 90))):
            self.glows.append((cx + k, 70, 14, c))

    def _paint_purgatorio(self, rng):
        self._stars(rng, 0)
        if self.night_s is not None:
            self._stars(rng, 220, self.night_s)
        # la montaña en terrazas, con el mar de Catón al pie
        cx = self.far_w // 2
        base_y, peak_y = VIEW_H - 18, 40
        prof = ridge(rng, self.far_w, 0, 6, 0.6)
        for k in range(9):  # siete cornisas, el Antepurgatorio y el jardín
            y0 = base_y - (base_y - peak_y) * k / 9
            y1 = base_y - (base_y - peak_y) * (k + 1) / 9
            w0 = 330 * (1 - k / 9.6)
            w1 = 330 * (1 - (k + 1) / 9.6)
            shade = 150 + k * 9
            col = (shade, int(shade * 0.82), int(shade * 0.86), 255)
            pts = [(cx - w0 + prof[int(cx - w0) % self.far_w], y0), (cx - w1, y1 + 4), (cx + w1, y1 + 4), (cx + w0, y0)]
            pygame.draw.polygon(self.far, col, pts)
            pygame.draw.line(self.far, (min(255, shade + 50), shade, shade - 10, 255), (cx - w1, y1 + 4), (cx + w1, y1 + 4), 2)
        for k in range(14):  # el bosque del Edén en la cima
            x = cx + rng.randint(-34, 34)
            pygame.draw.circle(self.far, (110, 160, 90, 255), (x, peak_y + 2 + rng.randint(-3, 3)), rng.randint(3, 6))
        pygame.draw.rect(self.far, (60, 110, 170, 255), (0, VIEW_H - 22, self.far_w, 22))
        for x in range(0, self.far_w, 7):
            pygame.draw.line(self.far, (170, 210, 240, 255), (x, VIEW_H - 21 + (x // 7) % 3), (x + 3, VIEW_H - 21 + (x // 7) % 3))
        haze = pygame.Surface((self.far_w, VIEW_H), pygame.SRCALPHA)
        haze.fill((255, 230, 220, 70))
        self.far.blit(haze, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self._mountains(self.mid, rng, VIEW_H * 0.82, 26, (150, 120, 120, 170), 0.5)
        if self.sky == "superbi":  # Purg. X: los relieves de humildad tallados en la pared
            for k in range(self.mid_w // 160):
                x = 40 + k * 160
                pygame.draw.rect(self.mid, (225, 215, 205, 220), (x, 70, 90, 56))
                pygame.draw.rect(self.mid, (180, 170, 160, 220), (x, 70, 90, 56), 2)
                for f in range(4):
                    fx_ = x + 14 + f * 20
                    pygame.draw.circle(self.mid, (170, 160, 150, 230), (fx_, 88), 4)
                    pygame.draw.polygon(self.mid, (170, 160, 150, 230), [(fx_ - 5, 120), (fx_ + 5, 120), (fx_ + 2, 93), (fx_ - 2, 93)])

    def _paint_eden(self, rng):
        self._paint_purgatorio(rng)
        for _ in range(self.mid_w // 16):  # el bosque divino
            x = rng.randrange(self.mid_w)
            y = VIEW_H - rng.randint(10, 60)
            pygame.draw.line(self.mid, (70, 60, 40, 255), (x, VIEW_H), (x, y), 2)
            pygame.draw.circle(self.mid, (90 + rng.randint(0, 60), 150 + rng.randint(0, 60), 80, 230), (x, y), rng.randint(8, 16))

    def _paint_paradiso(self, rng):
        _, _, accent = SKIES.get(self.sky, SKIES["empireo"])
        cx, cy = self.far_w // 2, VIEW_H // 2 + 40
        if self.sky == "stelle":
            self._stars(rng, 500, color=(255, 240, 200))
        for k in range(10):  # las esferas concéntricas (Giovanni di Paolo)
            r = 60 + k * 34
            a = 60 + k * 10
            pygame.draw.circle(self.far, (*accent, max(20, 140 - k * 12)), (cx, cy), r, 2)
            for t in range(0, 360, 15):
                ang = math.radians(t + k * 7)
                px, py = cx + r * math.cos(ang), cy + r * math.sin(ang)
                pygame.draw.circle(self.far, (255, 255, 255, min(255, a + 60)), (int(px), int(py)), 1 + (k % 2))
        for t in range(0, 360, 12):  # rayos
            ang = math.radians(t)
            pygame.draw.line(self.far, (*accent, 40), (cx, cy), (cx + 700 * math.cos(ang), cy + 700 * math.sin(ang)), 3)
        self.glows.append((cx, cy, 90, tuple(c // 2 for c in accent)))
        if self.sky in ("empireo", "visione"):
            for ring in range(6):  # la rosa cándida
                for p in range(18 + ring * 4):
                    ang = p / (18 + ring * 4) * math.tau + ring * 0.3
                    r = 30 + ring * 26
                    pygame.draw.ellipse(self.mid, (255, 255, 255, 120 - ring * 12),
                                        (cx + r * math.cos(ang) - 9, cy + r * math.sin(ang) * 0.55 - 5, 18, 10))
        else:
            for _ in range(self.mid_w // 40):  # nubes de luz
                x, y = rng.randrange(self.mid_w), rng.randint(20, VIEW_H - 40)
                for k in range(5):
                    pygame.draw.circle(self.mid, (255, 255, 255, 50), (x + k * 9, y + rng.randint(-4, 4)), rng.randint(8, 14))

    def overlay(self, view: pygame.Surface, cam: int, frame: int) -> None:
        """Lo que se mueve en el fondo: coronas, cruz, águila, escala, luna."""
        sky = self.sky
        if not sky:
            return
        cx = VIEW_W // 2 - int(cam * 0.1)
        if sky == "sole":  # dos coronas de doce espíritus que giran en sentidos opuestos
            for ring, (r, sp) in enumerate(((70, 0.006), (100, -0.004))):
                for k in range(12):
                    a = k / 12 * math.tau + frame * sp
                    x, y = cx + r * math.cos(a), 120 + r * 0.45 * math.sin(a)
                    pygame.draw.circle(view, (255, 250, 200), (int(x), int(y)), 3 - ring)
        elif sky == "marte":  # la cruz de luz
            g = 180 + int(40 * math.sin(frame * 0.03))
            pygame.draw.rect(view, (255, g, g - 60), (cx - 4, 20, 8, 200))
            pygame.draw.rect(view, (255, g, g - 60), (cx - 70, 80, 140, 8))
        elif sky == "giove":  # DILIGITE IUSTITIAM… y el águila de luces
            if not hasattr(self, "_font"):
                self._font = pygame.font.Font(None, 22)
                self._words = self._font.render("DILIGITE IUSTITIAM QUI IUDICATIS TERRAM", True, (255, 250, 230))
            ww = self._words.get_width()
            view.blit(self._words, (cx - ww // 2, 24))
            for k in range(40):
                t = k / 40
                wing = math.sin(t * math.pi) * (40 + 10 * math.sin(frame * 0.05))
                for s_ in (-1, 1):
                    view.fill((255, 240, 180), (int(cx + s_ * t * 90), int(100 - wing * 0.6 + t * 30), 2, 2))
        elif sky == "saturno":  # la escala de oro que sube más allá de la vista
            for k in range(0, VIEW_H, 9):
                y = (k + frame // 3) % VIEW_H
                pygame.draw.line(view, (240, 210, 120), (cx - 14, y), (cx + 14, y), 1)
            pygame.draw.line(view, (240, 210, 120), (cx - 14, 0), (cx - 14, VIEW_H), 1)
            pygame.draw.line(view, (240, 210, 120), (cx + 14, 0), (cx + 14, VIEW_H), 1)
        elif sky == "luna":
            pygame.draw.circle(view, (236, 240, 250), (cx + 160, 70), 30)
            pygame.draw.circle(view, (210, 216, 232), (cx + 150, 62), 6)
            pygame.draw.circle(view, (210, 216, 232), (cx + 172, 82), 4)
        elif sky == "venere":
            for k in range(8):
                a = frame * 0.01 + k
                x, y = int(cx + 120 * math.cos(a)), int(110 + 40 * math.sin(a * 1.3))
                pygame.draw.polygon(view, (255, 160, 190), [(x, y + 3), (x - 3, y - 1), (x - 1, y - 3), (x, y - 1), (x + 1, y - 3), (x + 3, y - 1)])

    # ── dibujo ──────────────────────────────────────────────────────────
    def draw(self, view: pygame.Surface, cam: int, night: float) -> None:
        view.blit(self.sky_s, (0, 0))
        if self.night_s is not None and night > 0:
            self.night_s.set_alpha(int(255 * night))
            view.blit(self.night_s, (0, 0))
        view.blit(self.far, (-int(cam * 0.25), 0))
        view.blit(self.mid, (-int(cam * 0.55), 0))


class Atmosphere:
    """Partículas puramente visuales: brasas, ceniza, nieve, polvo de oro, pétalos."""

    def __init__(self, kind: str, seed: int):
        self.kind = kind
        self.rng = random.Random(seed)
        self.p: list[list[float]] = []
        n = {"embers": 90, "ash": 70, "snow": 130, "gold": 90, "petals": 50, "dust": 50, "rain": 140,
             "wind": 80, "fireflies": 30}.get(kind, 40)
        for _ in range(n):
            self.p.append(self._new(True))

    def _new(self, anywhere: bool) -> list[float]:
        r = self.rng
        x = r.uniform(0, VIEW_W)
        y = r.uniform(0, VIEW_H) if anywhere else (VIEW_H + 4 if self.kind in ("embers", "gold") else -4)
        k = self.kind
        if k == "embers":
            return [x, y, r.uniform(-0.2, 0.2), r.uniform(-0.9, -0.3), r.uniform(0.5, 1), r.random() * 6]
        if k == "snow":
            return [x, y, r.uniform(-0.3, 0.1), r.uniform(0.2, 0.6), r.uniform(0.4, 1), r.random() * 6]
        if k == "rain":
            return [x, y, -0.6, r.uniform(3, 5), 1, 0]
        if k == "wind":
            return [x, y, r.uniform(2.5, 5), r.uniform(-0.3, 0.3), r.uniform(0.3, 1), r.random() * 6]
        if k == "gold":
            return [x, y, r.uniform(-0.15, 0.15), r.uniform(-0.5, -0.1), r.uniform(0.4, 1), r.random() * 6]
        if k == "petals":
            return [x, y, r.uniform(0.2, 0.6), r.uniform(0.2, 0.5), r.uniform(0.5, 1), r.random() * 6]
        if k == "fireflies":
            return [x, y, 0, 0, r.uniform(0.4, 1), r.random() * 6]
        return [x, y, r.uniform(-0.1, 0.1), r.uniform(0.02, 0.15), r.uniform(0.3, 0.8), r.random() * 6]

    def update(self, wind: float = 0.0) -> None:
        for q in self.p:
            q[5] += 0.05
            if self.kind == "fireflies":
                q[0] += math.sin(q[5] * 1.3) * 0.4
                q[1] += math.cos(q[5] * 0.9) * 0.3
            else:
                q[0] += q[2] + math.sin(q[5]) * 0.15 + wind
                q[1] += q[3]
            if q[1] < -8 or q[1] > VIEW_H + 8 or q[0] < -10 or q[0] > VIEW_W + 10:
                q[:] = self._new(False)
                if self.kind == "wind":
                    q[0] = -6

    def draw(self, view: pygame.Surface, glow: pygame.Surface, cam_dx: float) -> None:
        k = self.kind
        for q in self.p:
            x, y, a = int(q[0]), int(q[1]), q[4]
            if k == "embers":
                c = (255, int(120 + 100 * a), 40)
                view.fill(c, (x, y, 1, 1))
                glow.fill((int(120 * a), int(50 * a), 10), (x // 4, y // 4, 1, 1), special_flags=pygame.BLEND_ADD)
            elif k == "snow":
                v = int(180 + 70 * a)
                view.fill((v, v, 255), (x, y, 1 + (a > 0.8), 1 + (a > 0.8)))
            elif k == "rain":
                pygame.draw.line(view, (120, 130, 110), (x, y), (x - 1, y + 4))
            elif k == "wind":
                pygame.draw.line(view, (200, 150, 190), (x, y), (x - int(6 * a), y))
            elif k == "gold":
                c = (255, int(220 + 30 * a), int(140 * a))
                view.fill(c, (x, y, 1, 1))
                glow.fill((int(90 * a), int(80 * a), int(30 * a)), (x // 4, y // 4, 1, 1), special_flags=pygame.BLEND_ADD)
            elif k == "petals":
                view.fill((255, 220, 230), (x, y, 2, 1))
            elif k == "fireflies":
                b = 0.5 + 0.5 * math.sin(q[5] * 3)
                view.fill((int(200 * b), int(255 * b), int(120 * b)), (x, y, 1, 1))
                glow.fill((int(40 * b), int(70 * b), int(20 * b)), (x // 4, y // 4, 1, 1), special_flags=pygame.BLEND_ADD)
            else:
                v = int(140 * a)
                view.fill((v, v, v), (x, y, 1, 1))


class FX:
    """Partículas de juego (visual, fuera de la simulación determinista)."""

    def __init__(self) -> None:
        self.p: list[list] = []  # x, y, vx, vy, color, vida, gravedad, brillo
        self.rings: list[list] = []  # x, y, r, vida, color
        self.shake = 0.0
        self.rng = random.Random(7)

    def burst(self, x, y, n, colors, speed=2.5, life=(20, 40), grav=0.25, glow=True, up=1.5):
        r = self.rng
        for _ in range(n):
            ang = r.uniform(0, math.tau)
            sp = r.uniform(0.3, 1) * speed
            self.p.append([x, y, math.cos(ang) * sp, math.sin(ang) * sp - up, r.choice(colors), r.randint(*life), grav, glow])

    def handle(self, ev: tuple) -> None:
        kind, x, y = ev[0], ev[1], ev[2]
        if kind == "boom":
            self.burst(x, y, 70, [(255, 240, 200), (255, 180, 60), (220, 60, 30), (120, 20, 20), (236, 230, 214)], 3.5)
            self.rings.append([x, y, 2, 18, (255, 200, 120)])
            self.shake = max(self.shake, 6)
        elif kind == "blood":
            self.burst(x, y - 3, 14, [(160, 10, 10), (220, 30, 30), (236, 230, 214)], 1.6, (14, 26), 0.3, False)
            self.shake = max(self.shake, 1.5)
        elif kind == "splash":
            self.burst(x, y, 16, [(200, 220, 255), (120, 160, 220)], 1.8, (12, 24), 0.3, False, 2.2)
        elif kind == "fire":
            self.burst(x, y, 18, [(255, 220, 90), (255, 120, 30), (180, 40, 10)], 1.2, (14, 30), -0.05)
        elif kind == "saved":
            self.burst(x, y, 12, [(255, 240, 180), (255, 255, 255)], 1.2, (24, 40), -0.06)
            self.rings.append([x, y, 1, 14, (255, 240, 200)])
        elif kind == "pickup":
            self.burst(x, y, 24, [ev[3], (255, 230, 120), (255, 255, 255)], 1.8, (20, 36), 0.02)
            self.rings.append([x, y, 2, 16, ev[3]])
        elif kind in ("cure", "grace"):
            self.burst(x, y, 30, [(160, 255, 200), (255, 255, 255), (120, 200, 255)], 1.4, (24, 44), -0.05)
            self.rings.append([x, y, 4, 22, (160, 255, 220)])
        elif kind == "pacify":
            self.burst(x, y, 36, [(255, 220, 90), (255, 255, 200)], 2.2, (20, 40), 0.05)
            self.rings.append([x, y, 4, 24, (255, 220, 120)])
        elif kind == "dust":
            self.burst(x, y, 3, [(150, 130, 110), (110, 90, 80)], 0.8, (8, 16), 0.15, False, 0.5)
        elif kind in ("infect", "bubo"):
            self.burst(x, y, 6, [(120, 160, 40), (90, 120, 30)], 0.6, (16, 26), -0.03, False)
        elif kind == "foco":
            self.burst(x, y, 20, [(100, 140, 30), (70, 90, 30)], 0.8, (30, 50), -0.03, False)
        elif kind in ("orange", "swap", "dome", "release"):
            col = {"orange": (255, 150, 40), "swap": (160, 20, 30), "dome": (240, 210, 160), "release": (90, 120, 255)}[kind]
            self.burst(x, y, 40, [col, (255, 255, 255)], 2.4, (20, 46), 0.04)
            self.rings.append([x, y, 4, 26, col])

    def update(self) -> None:
        for q in self.p:
            q[0] += q[2]
            q[1] += q[3]
            q[3] += q[6]
            q[2] *= 0.98
            q[5] -= 1
        self.p = [q for q in self.p if q[5] > 0]
        for r in self.rings:
            r[2] += 1.6
            r[3] -= 1
        self.rings = [r for r in self.rings if r[3] > 0]
        self.shake *= 0.86

    def draw(self, view: pygame.Surface, glow: pygame.Surface, cam: int) -> None:
        for q in self.p:
            x, y = int(q[0]) - cam, int(q[1])
            view.fill(q[4], (x, y, 1, 1))
            if q[7]:
                c = q[4]
                glow.fill((c[0] // 3, c[1] // 3, c[2] // 3), (x // 4, y // 4, 1, 1), special_flags=pygame.BLEND_ADD)
        for r in self.rings:
            a = r[3] / 26
            c = tuple(int(v * a) for v in r[4])
            pygame.draw.circle(view, c, (int(r[0]) - cam, int(r[1])), int(r[2]), 1)


class Renderer:
    """Escena → luz → bloom → post. Todo a 640×296 lógicos."""

    def __init__(self, world: World, sprites: Sprites, quality: int = 2):
        self.world = world
        self.sp = sprites
        self.q = quality
        t = world.terrain
        self.tsurf = pygame.Surface((t.w, t.h), pygame.SRCALPHA)
        self.tglow = pygame.Surface((t.w // 4 + 1, t.h // 4 + 1))
        self.sync(full=True)
        th = world.theme
        lv = world.level
        self.back = Backdrop(t.w, th, lv.sky, lv.id * 101 + 7)
        self.atmo = Atmosphere(th.motes if "wind" not in world.mods else "wind", lv.id)
        self.fx = FX()
        self.light = pygame.Surface((VIEW_W // 2, VIEW_H // 2))
        self.glow = pygame.Surface((VIEW_W // 4, VIEW_H // 4))
        self.inv_layer = pygame.Surface((VIEW_W, VIEW_H), pygame.SRCALPHA)
        self.inv_glow = pygame.Surface((VIEW_W // 4, VIEW_H // 4))
        self.vignette = self._vignette()
        self.grain = [self._grain(k) for k in range(4)]
        self._hazard_layers()
        self.mini: pygame.Surface | None = None
        self.mini_age = 999
        self.smoke = self._smoke_layer() if "smoke" in world.mods else None
        self.reduce_motion = False  # sin temblor, grano ni parpadeos
        self.markers = True  # iconos de enfermedad (no depender solo del color)
        self.contrast = False  # luz ambiente más alta

    # ── recursos ────────────────────────────────────────────────────────
    @staticmethod
    def _vignette() -> pygame.Surface:
        yy, xx = np.mgrid[0:VIEW_H, 0:VIEW_W]
        dx = (xx - VIEW_W / 2) / (VIEW_W / 2)
        dy = (yy - VIEW_H / 2) / (VIEW_H / 2)
        d = np.sqrt(dx * dx * 0.8 + dy * dy)
        v = np.clip(1.15 - 0.55 * d ** 2.2, 0.25, 1) * 255
        arr = np.repeat(v[..., None], 3, axis=2).astype(np.uint8)
        s = pygame.Surface((VIEW_W, VIEW_H))
        pygame.surfarray.blit_array(s, arr.transpose(1, 0, 2))
        return s

    @staticmethod
    def _grain(seed: int) -> pygame.Surface:
        rng = np.random.default_rng(seed)
        v = (rng.random((VIEW_H, VIEW_W)) ** 9 * 14).astype(np.uint8)
        s = pygame.Surface((VIEW_W, VIEW_H))
        pygame.surfarray.blit_array(s, np.repeat(v[..., None], 3, axis=2).transpose(1, 0, 2))
        return s

    def _smoke_layer(self) -> pygame.Surface:
        rng = np.random.default_rng(5)
        n = fbm(VIEW_H, VIEW_W * 2, rng, 40, 4)
        a = (np.clip((n - 0.35) * 2.2, 0, 1) * 235).astype(np.uint8)
        s = pygame.Surface((VIEW_W * 2, VIEW_H), pygame.SRCALPHA)
        rgb = pygame.surfarray.pixels3d(s)
        rgb[:] = (18, 16, 20)
        del rgb
        al = pygame.surfarray.pixels_alpha(s)
        al[:] = a.T
        del al
        return s

    def _hazard_layers(self) -> None:
        hz = self.world.hazard
        th = self.world.theme
        rng = np.random.default_rng(11)
        self.liquid: list[pygame.Surface] = []
        self.fire: list[pygame.Surface] = []
        self.hz_glow = pygame.Surface((self.world.terrain.w // 4 + 1, VIEW_H // 4 + 1))
        liq = hz == HZ_LIQUID
        fire = (hz == HZ_FIRE) | (hz == HZ_PURGE)
        flip = hz == HZ_FLIP
        self.flipfx: list[pygame.Surface] = []
        if flip.any():
            h_, w_ = hz.shape
            yy, xx = np.mgrid[0:h_, 0:w_]
            for k in range(6):
                v = 0.5 + 0.5 * np.sin(yy * 0.35 + xx * 0.9 + k * 1.05)
                col = np.stack([120 + 120 * v, 90 + 90 * v, 200 + 55 * v], axis=-1)
                self.flipfx.append(_overlay(flip, col.astype(np.uint8), 90))
            self._glow_mask(flip, (90, 60, 160))
        h, w = hz.shape
        if liq.any():
            top = liq.copy()
            top[1:] &= ~liq[:-1]
            base = np.array(self.world.level.liquid or th.liquid, dtype=float)
            for k in range(4):
                col = np.zeros((h, w, 3))
                xx = np.arange(w)
                yy = np.arange(h)[:, None]
                wave = 0.75 + 0.25 * np.sin(xx[None, :] * 0.35 + k * 1.57 + yy * 0.6)
                col[:] = base[None, None, :] * wave[..., None]
                col[top] = np.minimum(base * 1.8 + 60, 255)
                self.liquid.append(_overlay(liq, col.astype(np.uint8), 220))
            if th.liquid_glow:
                self._glow_mask(liq, th.liquid)
        if fire.any():
            pal = np.array([(200, 40, 0), (255, 130, 0), (255, 215, 60), (255, 250, 200)], dtype=float)
            for k in range(4):
                n = rng.random(hz.shape)
                col = pal[np.minimum((n ** 1.5 * 4).astype(int), 3)]
                self.fire.append(_overlay(fire, col.astype(np.uint8), 225))
            self._glow_mask(fire, (255, 140, 40))

    def _glow_mask(self, mask: np.ndarray, color) -> None:
        h, w = mask.shape
        small = mask[: h - h % 4, : w - w % 4].reshape(h // 4, 4, w // 4, 4).mean(axis=(1, 3))
        arr = (small[..., None] * np.array(color)[None, None, :] * 0.9).clip(0, 255).astype(np.uint8)
        tmp = pygame.Surface((w // 4, h // 4))
        pygame.surfarray.blit_array(tmp, arr.transpose(1, 0, 2))
        self.hz_glow.blit(tmp, (0, 0), special_flags=pygame.BLEND_ADD)

    def sync(self, full: bool = False) -> None:
        t = self.world.terrain
        if t.dirty is None and not full:
            return
        x0, y0, x1, y1 = (0, 0, t.w, t.h) if full else t.dirty
        m = 4
        x0, y0 = max(0, x0 - m), max(0, y0 - m)
        x1, y1 = min(t.w, x1 + m), min(t.h, y1 + m)
        # el sombreado necesita contexto: calcula con margen y pinta solo la región
        cx0, cy0, cx1, cy1 = max(0, x0 - 4), max(0, y0 - 4), min(t.w, x1 + 4), min(t.h, y1 + 4)
        amb = sum(self.world.theme.ambient) / (3 * 255)
        rgb, alpha = shade_region(t.k[cy0:cy1, cx0:cx1], t.c[cy0:cy1, cx0:cx1], self.world.theme.rim, 0.3 + 0.55 * amb)
        sx, sy = x0 - cx0, y0 - cy0
        rgb = rgb[sy : sy + (y1 - y0), sx : sx + (x1 - x0)]
        alpha = alpha[sy : sy + (y1 - y0), sx : sx + (x1 - x0)]
        px = pygame.surfarray.pixels3d(self.tsurf)
        px[x0:x1, y0:y1] = rgb.transpose(1, 0, 2)
        del px
        pa = pygame.surfarray.pixels_alpha(self.tsurf)
        pa[x0:x1, y0:y1] = alpha.T
        del pa
        # brillo de las vetas (a 1/4)
        if self.world.theme.veins is not None:
            gx0, gy0, gx1, gy1 = x0 // 4, y0 // 4, min(t.w // 4, x1 // 4 + 1), min(t.h // 4, y1 // 4 + 1)
            e = t.e[gy0 * 4 : gy1 * 4, gx0 * 4 : gx1 * 4]
            if e.size:
                hh, ww = e.shape[0] // 4, e.shape[1] // 4
                small = e[: hh * 4, : ww * 4].reshape(hh, 4, ww, 4).mean(axis=(1, 3))
                arr = (small[..., None] * np.array(self.world.theme.veins)[None, None, :] * 1.1).clip(0, 255).astype(np.uint8)
                if hh and ww:
                    pg = pygame.surfarray.pixels3d(self.tglow)
                    pg[gx0 : gx0 + ww, gy0 : gy0 + hh] = arr.transpose(1, 0, 2)
                    del pg
        t.dirty = None
        self.mini_age = 999

    def minimap(self, size: tuple[int, int]) -> pygame.Surface:
        self.mini_age += 1
        if self.mini is None or self.mini_age > 20:
            base = pygame.Surface(self.tsurf.get_size())
            base.fill(self.world.theme.sky_bot)
            base.blit(self.tsurf, (0, 0))
            self.mini = pygame.transform.smoothscale(base, size)
            self.mini_age = 0
        return self.mini

    # ── dibujo ──────────────────────────────────────────────────────────
    def night_amount(self) -> float:
        w = self.world
        if "night" not in w.mods:
            return 0.0
        ph = w.tick_count % NIGHT_CYCLE
        start = NIGHT_CYCLE - NIGHT_LEN
        fade = 2 * TPS
        if ph < fade:
            return 1 - ph / fade if w.tick_count >= NIGHT_CYCLE else 0.0
        if ph < start - fade:
            return 0.0
        if ph < start:
            return (ph - (start - fade)) / fade
        return 1.0

    def draw(self, view: pygame.Surface, cam: int, frame: int, cursor: tuple[int, int] | None = None) -> None:
        w = self.world
        self.sync()
        for ev in w.fx:
            self.fx.handle(ev)
        w.fx.clear()
        self.fx.update()
        self.atmo.update(0.8 if w.rule_off("wind") else 0.0)
        night = self.night_amount()
        glow = self.glow
        glow.fill((0, 0, 0))
        # 1) fondo y glows lejanos
        self.back.draw(view, cam, night)
        for gx, gy, gr, gc in self.back.glows:
            x = gx - int(cam * 0.25)
            if -gr < x < VIEW_W + gr:
                flick = 0.8 + 0.2 * math.sin(frame * 0.07 + gx)
                view.blit(light_sprite(gr, tuple(int(c * 0.45 * flick) for c in gc), 2.4), (x - gr, gy - gr),
                          special_flags=pygame.BLEND_ADD)
        self.back.overlay(view, cam, frame)
        # 2) terreno
        view.blit(self.tsurf, (0, 0), pygame.Rect(cam, 0, VIEW_W, VIEW_H))
        if w.theme.veins is not None:
            pulse = 0.75 + 0.25 * math.sin(frame * 0.05)
            g2 = self.tglow.subsurface(pygame.Rect(cam // 4, 0, min(VIEW_W // 4, self.tglow.get_width() - cam // 4), VIEW_H // 4))
            tmp = g2.copy()
            tmp.fill((int(255 * pulse),) * 3, special_flags=pygame.BLEND_MULT)
            glow.blit(tmp, (0, 0), special_flags=pygame.BLEND_ADD)
        # 3) peligros
        if self.liquid:
            view.blit(self.liquid[(frame // 10) % len(self.liquid)], (0, 0), pygame.Rect(cam, 0, VIEW_W, VIEW_H))
        if self.fire:
            view.blit(self.fire[(frame // 4) % len(self.fire)], (0, 0), pygame.Rect(cam, 0, VIEW_W, VIEW_H))
        if self.flipfx:
            view.blit(self.flipfx[(frame // 5) % len(self.flipfx)], (0, 0), pygame.Rect(cam, 0, VIEW_W, VIEW_H))
        if self.liquid or self.fire or self.flipfx:
            glow.blit(self.hz_glow, (-cam // 4, 0), special_flags=pygame.BLEND_ADD)
        # 4) entidades
        lights: list[tuple[int, int, int, tuple[int, int, int]]] = []
        self._entities(view, glow, cam, frame, lights)
        if w.has_inv:
            lay, g2, l2 = self.inv_layer, self.inv_glow, []
            lay.fill((0, 0, 0, 0))
            g2.fill((0, 0, 0))
            self._entities(lay, g2, cam, frame, l2, inv=True)
            view.blit(pygame.transform.flip(lay, False, True), (0, 0))
            glow.blit(pygame.transform.flip(g2, False, True), (0, 0), special_flags=pygame.BLEND_ADD)
            lights += [(x, VIEW_H - 1 - y, r, c) for x, y, r, c in l2]
        # 5) partículas
        self.fx.draw(view, glow, cam)
        self.atmo.draw(view, glow, 0)
        if self.smoke is not None and not (w.reveal or w.lume or w.dioneo):
            off = (frame // 2 + cam // 2) % VIEW_W
            view.blit(self.smoke, (-off, 0))
        # 6) iluminación
        self._lighting(view, cam, frame, lights, night)
        # 7) bloom
        if self.q >= 1:
            big = pygame.transform.smoothscale(glow, (VIEW_W, VIEW_H))
            view.blit(big, (0, 0), special_flags=pygame.BLEND_ADD)
            if self.q >= 2:
                wide = pygame.transform.smoothscale(pygame.transform.smoothscale(glow, (VIEW_W // 16, VIEW_H // 16)), (VIEW_W, VIEW_H))
                view.blit(wide, (0, 0), special_flags=pygame.BLEND_ADD)
        # 8) post
        view.blit(self.vignette, (0, 0), special_flags=pygame.BLEND_MULT)
        if self.q >= 2 and not self.reduce_motion:
            view.blit(self.grain[frame % 4], (0, 0), special_flags=pygame.BLEND_ADD)
        if w.panic:
            view.fill((40, 0, 0), special_flags=pygame.BLEND_ADD)

    def _lighting(self, view, cam, frame, lights, night) -> None:
        w = self.world
        th = w.theme
        amb = np.array(th.ambient, dtype=float)
        if night:
            amb = amb * (1 - 0.72 * night)
        dark = (w.rule_off("dark") and not w.reveal) or (self.smoke is not None and not w.reveal and not w.dioneo)
        if dark:
            amb = amb * 0.12
        if w.reveal:
            amb = np.maximum(amb, 170)
        if self.contrast:
            amb = np.maximum(amb, 175)
        L = self.light
        L.fill(tuple(int(v) for v in amb))
        cand = th.candles or night > 0.3 or dark
        for x, y, r, c in lights:
            L.blit(light_sprite(r // 2, c), ((x - cam) // 2 - r // 2, y // 2 - r // 2), special_flags=pygame.BLEND_ADD)
        if cand:
            for Lm in w.lemmings:
                if Lm.removed:
                    continue
                flick = 1 + 0.12 * math.sin(frame * 0.4 + Lm.id)
                r = int((40 if dark else 36) * flick)
                col = (150, 110, 60) if not Lm.maestro else (110, 70, 50)
                L.blit(light_sprite(r // 2, col), ((Lm.x - cam) // 2 - r // 2, w.rmid(Lm) // 2 - r // 2),
                       special_flags=pygame.BLEND_ADD)
        for gx, gy, gr, gc in self.back.glows:
            x = gx - int(cam * 0.25)
            if -gr < x < VIEW_W + gr:
                L.blit(light_sprite(gr // 2, tuple(c // 3 for c in gc)), (x // 2 - gr // 2, gy // 2 - gr // 2),
                       special_flags=pygame.BLEND_ADD)
        if w.lume:
            self._lume(L, cam, frame)
        big = pygame.transform.smoothscale(L, (VIEW_W, VIEW_H))
        view.blit(big, (0, 0), special_flags=pygame.BLEND_MULT)
        if w.lume:  # el haz también se ve en el aire: polvo iluminado
            lx, ly, t = w.lume
            a = min(1.0, t / 40)
            beam = pygame.Surface((VIEW_W, VIEW_H), pygame.SRCALPHA)
            sx = lx - cam + ly
            pygame.draw.polygon(beam, (255, 230, 170, int(38 * a)),
                                [(sx - 18, 0), (sx + 26, 0), (sx + 26 - VIEW_H - 40, VIEW_H + 40), (sx - 18 - VIEW_H - 40, VIEW_H + 40)])
            view.blit(beam, (0, 0))

    def _lume(self, L: pygame.Surface, cam: int, frame: int) -> None:
        lx, ly, t = self.world.lume
        a = min(1.0, t / 40)
        sx = (lx - cam + ly) // 2
        poly = [(sx - 10, 0), (sx + 14, 0), (sx + 14 - VIEW_H // 2 - 20, VIEW_H // 2 + 20), (sx - 10 - VIEW_H // 2 - 20, VIEW_H // 2 + 20)]
        beam = pygame.Surface(L.get_size())
        pygame.draw.polygon(beam, (int(255 * a), int(230 * a), int(180 * a)), poly)
        L.blit(beam, (0, 0), special_flags=pygame.BLEND_ADD)

    def _entities(self, view, glow, cam, frame, lights, inv: bool = False) -> None:
        """Dibuja las entidades de un marco: el del mundo o el de quien cae hacia la luz."""
        w = self.world
        tick = w.tick_count
        for e in w.entrances:
            if e.inv != inv:
                continue
            self._font(view, e.x - cam, e.y, min(1.0, w.hatch / HATCH_TICKS), frame)
            lights.append((e.x, e.y - 14, 70, (120, 110, 150)))
        for ex in w.exits:
            if ex.inv != inv:
                continue
            self._exit(view, glow, ex.x - cam, ex.y, frame, w.cantica, w.level.special)
            lights.append((ex.x, ex.y - 14, 120, (255, 200, 120) if w.cantica != "paradiso" else (255, 255, 230)))
        if not inv:
            self._world_things(view, glow, cam, frame, lights)
        for g in w.guards:
            if g.inv == inv:
                self._guard(view, glow, g, cam, frame, lights)
        for p in w.pickups:
            if not p.taken and p.inv == inv:
                self._pickup(view, glow, p, cam, frame, lights)
        backwards = w.rule_off("backwards")
        stones = 0
        if w.cantica == "purgatorio" and w.peso >= 10:
            stones = max(1, w.total // max(1, w.peso // 10))
        for Lm in w.lemmings:
            if Lm.removed or Lm.inv != inv:
                continue
            name, i, dy = sprite_of(Lm, tick)
            who = "m" if Lm.maestro else "c" if Lm.child else "w"
            d = -Lm.dir if backwards and Lm.state == St.WALK else Lm.dir
            img = self.sp.get(name, i, d, who)
            if Lm.moria == 1:
                img = self.sp.tinted(img, (236, 230, 170))
            elif Lm.moria == 2:
                img = self.sp.tinted(img, (190, 210, 120))
            if Lm.state == St.BURN:
                img = self.sp.tinted(img, (255, 150, 60))
            elif "piombo" in w.mods and not Lm.maestro:  # «di fuor dorate son… ma dentro tutte piombo»
                img = self.sp.tinted(img, (215, 190, 120))
            ax = img.get_width() // 2 - (0 if d > 0 else 1)
            x, y = Lm.x - ax - cam, Lm.y - img.get_height() + 1 + dy
            if Lm.state == St.EXIT:
                img = img.copy()
                img.set_alpha(255 - 20 * Lm.frame)
            view.blit(img, (x, y))
            if Lm.moria == 2:
                view.fill((60, 120, 20), (Lm.x - cam + (2 if d > 0 else -3), Lm.y - 7, 2, 2))
            if self.markers and Lm.moria:  # forma, no solo color: «!» fiebre, cruz roja bubón
                mx_, my_ = Lm.x - cam, Lm.y - 20
                if Lm.moria == 1:
                    view.fill((255, 230, 80), (mx_, my_, 1, 3))
                    view.fill((255, 230, 80), (mx_, my_ + 4, 1, 1))
                else:
                    view.fill((255, 60, 50), (mx_ - 1, my_ + 1, 3, 1))
                    view.fill((255, 60, 50), (mx_, my_, 1, 3))
            if Lm.bomb is not None:
                dd = str(min(5, math.ceil(Lm.bomb / TPS)))
                view.blit(self.sp.digits[dd], (Lm.x - 1 - cam, Lm.y - 19))
            if Lm.state == St.BUILD and Lm.bricks <= 3 and frame % 16 < 8:
                view.fill((255, 225, 40), (Lm.x - cam, Lm.y - 16, 1, 2))
            if Lm.state == St.BLOCK and frame % 20 < 3:
                self.fx.burst(Lm.x + 4 * (1 if frame % 40 < 20 else -1), Lm.y - 7, 2, [(200, 20, 20)], 0.6, (6, 12), 0.2, False, 0.2)
            if Lm.maestro:
                lights.append((Lm.x, Lm.y - 8, 30, (140, 90, 40)))
                if w.flame_said:
                    view.fill((255, 140, 40), (Lm.x - cam, Lm.y - 15 - (frame // 3) % 3, 1, 2))
            if Lm.grace:
                view.fill((80, 110, 255), (Lm.x - cam, Lm.y - 15, 1, 1))
            if Lm.medico:  # sombrero de ala y máscara de pico
                hx, hy = Lm.x - cam, Lm.y - 12 + dy
                view.fill((30, 26, 30), (hx - 3, hy - 1, 7, 1))
                view.fill((30, 26, 30), (hx - 1, hy - 3, 3, 2))
                view.fill((236, 226, 200), (hx + 2 * d, hy + 2, 2, 1))
                view.fill((236, 226, 200), (hx + 3 * d, hy + 3, 1, 1))
                if (frame // 10 + Lm.id) % 6 == 0:
                    glow.fill((10, 40, 20), ((Lm.x - cam) // 4, (Lm.y - 8) // 4, 1, 1), special_flags=pygame.BLEND_ADD)
            if w.lume and Lm.fervor == 0 and Lm.state == St.WALK:
                glow.fill((40, 36, 20), ((Lm.x - cam) // 4, (Lm.y - 8) // 4, 1, 1), special_flags=pygame.BLEND_ADD)
            if stones and Lm.id % stones == 0 and not Lm.maestro:  # el Peso hecho piedra
                pygame.draw.circle(view, (120, 116, 110), (Lm.x - cam - 2 * d, Lm.y - 10), 3)
                view.fill((170, 166, 160), (Lm.x - cam - 2 * d - 1, Lm.y - 12, 2, 1))
            if "paradiso" in w.mods and Lm.fervor > FERVOR_SLOW and (tick + Lm.id) % 80 < 24:
                k = (frame // 2) % 4
                view.fill((255, 255, 255), (Lm.x - cam - 1 + k % 3, Lm.y - 16 - k // 2, 1, 1))  # deslumbrado
            if Lm.stare:
                view.fill((230, 60, 40), (Lm.x - cam + 2 * d, Lm.y - 15, 1, 1))


    def _world_things(self, view, glow, cam, frame, lights) -> None:
        """Lo que solo existe en el marco del mundo: peligros, trampas, gigantes, árboles."""
        w = self.world
        for v in w.vents:
            on = w.vent_on(v)
            x0 = v[0] - cam
            pygame.draw.rect(view, (70, 60, 56), (x0 - 2, v[2] - 3, v[1] - v[0] + 4, 3))
            pygame.draw.rect(view, (30, 20, 18), (x0, v[2] - 2, v[1] - v[0], 2))
            for leg in (-3, 3):  # Inf. XIX: los simoníacos, cabeza abajo, con los pies fuera
                lx = (v[0] + v[1]) // 2 - cam + leg
                pygame.draw.line(view, (200, 150, 120), (lx, v[2] - 3), (lx + leg // 3, v[2] - 10), 2)
                view.fill((255, 200, 80) if on or frame % 8 < 4 else (255, 120, 40), (lx + leg // 3 - 1, v[2] - 12, 3, 2))
            if on:
                for k in range(v[1] - v[0]):
                    h = 6 + int(6 * abs(math.sin(frame * 0.5 + k)))
                    pygame.draw.line(view, (255, 180 - h * 6, 40), (x0 + k, v[2] - 2), (x0 + k, v[2] - 2 - h))
                lights.append(((v[0] + v[1]) // 2, v[2] - 6, 60, (255, 120, 40)))
                glow.fill((120, 50, 10), ((x0) // 4, (v[2] - 12) // 4, (v[1] - v[0]) // 4 + 1, 3), special_flags=pygame.BLEND_ADD)
            else:
                view.fill((200, 70, 20), (x0 + (frame // 3) % max(1, v[1] - v[0]), v[2] - 3, 1, 1))
        for b in w.boulders:
            x, y = b[3] - cam, b[2]
            rot = (b[3] // 3) % 4
            pygame.draw.circle(view, (90, 80, 70), (x, y - 7), 7)
            pygame.draw.circle(view, (130, 118, 100), (x - 2, y - 9), 3)
            pygame.draw.line(view, (60, 50, 44), (x - 5 + rot, y - 12), (x + 3 - rot, y - 2))
            if w.boulder_moving(b):
                pygame.draw.line(view, (60, 50, 44), (x - 12 * b[4], y - 7), (x - 18 * b[4], y - 7))
        if w.fire_y < VIEW_H:
            fy = int(w.fire_y)
            for x in range(0, VIEW_W, 2):
                h = 6 + int(8 * abs(math.sin(frame * 0.2 + (x + cam) * 0.13)))
                pygame.draw.line(view, (255, 200 - h * 6, 40), (x, fy), (x, fy - h), 2)
            view.fill((255, 120, 30), (0, fy, VIEW_W, VIEW_H - fy))
            glow.fill((160, 60, 10), (0, fy // 4 - 3, VIEW_W // 4, VIEW_H // 4 - fy // 4 + 3), special_flags=pygame.BLEND_ADD)
            lights.append((cam + VIEW_W // 4, fy, 300, (255, 130, 50)))
            lights.append((cam + 3 * VIEW_W // 4, fy, 300, (255, 130, 50)))
        for x, y in w.statues:
            img = self.sp.get("frozen", 0, 1)
            view.blit(img, (x - 5 - cam, y - 13))
        for fx_, fy_ in w.focos:
            r = 9 + int(2 * math.sin(frame * 0.1 + fx_))
            pygame.draw.circle(view, (70, 90, 20), (fx_ - cam, fy_ - 2), r, 1)
            view.fill((110, 140, 30), (fx_ - cam - 2, fy_ - 3, 5, 2))
        for c in w.corpses:
            view.fill((150, 140, 120), (c[0] - cam - 3, c[1] - 2, 7, 2))
        for r in w.rats:
            x, y = r[0] - cam, r[1]
            view.fill((60, 50, 46), (x - 2, y - 3, 5, 3))
            view.fill((60, 50, 46), (x + 2 * r[2], y - 4, 2, 2))
            view.fill((40, 32, 30), (x - 3 * r[2], y - 2, 3, 1))
            view.fill((255, 60, 40), (x + 3 * r[2], y - 4, 1, 1))
        if w.child is not None:
            img = self.sp.get("walk", 0, 1 if (frame // 90) % 2 else -1, "c")
            view.blit(img, (w.child[0] - 5 - cam, w.child[1] - 13))
            if frame % 60 < 40:
                view.fill((255, 240, 180), (w.child[0] - cam, w.child[1] - 16, 1, 2))
        if w.soul is not None:
            sx, sy = w.soul[0] - cam, w.soul[1]
            a = 0.5 + 0.5 * math.sin(frame * 0.2)
            pygame.draw.circle(view, (int(200 * a) + 55, int(200 * a) + 55, 255), (sx, sy - 8 - int(3 * a)), 2)
            lights.append((w.soul[0], sy - 8, 40, (120, 120, 200)))
        if w.level.special == "caravaggio":
            self._caravaggio(view, glow, cam, frame, lights)
        if w.lure:
            x, y = w.lure[0] - cam, w.lure[1]
            pygame.draw.circle(view, (255, 140, 30), (x, y - 3), 3)
            view.fill((60, 120, 40), (x, y - 7, 2, 2))
            lights.append((w.lure[0], y, 50, (255, 140, 40)))
        for d_ in w.drops:  # lluvia de fuego
            x, y = d_[0] - cam, d_[1]
            if -2 < x < VIEW_W + 2:
                pygame.draw.line(view, (255, 200, 90), (x, y), (x + 1, y - 5))
                view.fill((255, 250, 210), (x, y, 1, 1))
                glow.fill((90, 40, 8), (x // 4, y // 4, 1, 2), special_flags=pygame.BLEND_ADD)
        if w.banner:
            bx = int(w.banner[0])
            by = w._floor_at(min(max(bx, 0), w.tn.w - 1)) or VIEW_H - 20
            x = bx - cam
            pygame.draw.line(view, (120, 100, 80), (x, by - 34), (x, by - 2), 1)
            for k in range(10):
                wave = int(2 * math.sin(frame * 0.25 + k * 0.7))
                view.fill((230, 220, 200) if k % 4 else (200, 40, 30), (x + 1 + k, by - 34 + wave, 1, 7))
            for k in range(7):  # avispas y tábanos
                a = frame * 0.2 + k * 0.9
                view.fill((240, 200, 60), (x + int(18 * math.cos(a * (1 + k % 3 * 0.3))), by - 24 + int(10 * math.sin(a * 1.7)), 1, 1))
            lights.append((bx, by - 28, 50, (200, 180, 140)))
        for tx, ty in w.trees:  # Purg. XXII: el árbol de fruta y el agua que cae
            x = tx - cam
            pygame.draw.line(view, (90, 66, 40), (x, ty), (x, ty - 28), 3)
            pygame.draw.polygon(view, (60, 120, 50), [(x - 16, ty - 26), (x + 16, ty - 26), (x + 8, ty - 44), (x - 8, ty - 44)])
            for k in range(6):
                view.fill((230, 50, 40), (x - 12 + k * 5, ty - 30 - (k % 2) * 8, 2, 2))
            for k in range(4):
                yy = ty - 50 + (frame // 2 + k * 6) % 26
                view.fill((150, 200, 255), (x + 14, yy, 1, 2))
        for sx_, sy_, nm, _line, _said in w.sabios:  # los sabios del castillo
            x = sx_ - cam
            pygame.draw.polygon(view, (200, 196, 180), [(x - 4, sy_), (x + 4, sy_), (x + 2, sy_ - 11), (x - 2, sy_ - 11)])
            pygame.draw.circle(view, (220, 190, 160), (x, sy_ - 13), 2)
            pygame.draw.arc(view, (90, 160, 70), (x - 3, sy_ - 17, 6, 5), 0, math.pi, 1)
            lights.append((sx_, sy_ - 10, 40, (160, 160, 130)))
        for ax_, ay_ in w.anteo:  # el gigante, desde el fondo del pozo
            base = w._floor_at(min(ax_ + 18, w.tn.w - 1)) or VIEW_H - 8
            x = ax_ - cam + 22
            body = (88, 74, 70)
            pygame.draw.rect(view, body, (x - 8, ay_ + 6, 16, base - ay_ - 6))
            pygame.draw.circle(view, (120, 100, 90), (x, ay_), 7)
            view.fill((255, 80, 40), (x - 3, ay_ - 1, 2, 1))
            view.fill((255, 80, 40), (x + 2, ay_ - 1, 2, 1))
            reach = int(2 * math.sin(frame * 0.05))
            pygame.draw.line(view, body, (x - 6, ay_ + 10), (ax_ - cam + 2, ay_ + 2 + reach), 4)
            pygame.draw.circle(view, (120, 100, 90), (ax_ - cam + 2, ay_ + 1 + reach), 3)
            lights.append((ax_ + 22, ay_ + 20, 70, (180, 120, 90)))
        for ph in w.phantoms:
            x0, y0, x1, y1 = ph["r"]
            if ph["on"]:
                glow.fill((40, 40, 50), ((x0 - cam) // 4, y0 // 4, (x1 - x0) // 4 + 1, 1), special_flags=pygame.BLEND_ADD)
            elif frame % 40 < 30:
                for xx in range(x0, x1, 3):
                    view.fill((150, 150, 170), (xx - cam, y0, 1, 1))
        for b in w.boats:  # Flegias a popa, con el remo
            fx_ = b["x"] - cam + (2 if b["dir"] < 0 else 20)
            by = b["y"]
            pygame.draw.polygon(view, (50, 40, 46), [(fx_ - 3, by), (fx_ + 3, by), (fx_ + 2, by - 14), (fx_ - 2, by - 14)])
            pygame.draw.circle(view, (150, 130, 120), (fx_, by - 16), 3)
            view.fill((255, 70, 30), (fx_ - 1, by - 17, 1, 1))
            sway = int(4 * math.sin(frame * 0.12))
            pygame.draw.line(view, (110, 80, 50), (fx_ + 2, by - 12), (fx_ + 6 + sway, by + 6), 2)
            lights.append((b["x"] + 12, by - 10, 60, (160, 140, 100)))
        for r in w.snakes:  # las serpientes de los ladrones
            x, y = r[0] - cam, r[1]
            pts = [(x - k * r[2], y - 1 - int(1.5 * math.sin(frame * 0.4 + k))) for k in range(8)]
            pygame.draw.lines(view, (70, 140, 60), False, pts, 2)
            view.fill((230, 40, 30), (x + r[2], y - 2, 1, 1))
        if "flames" in w.mods:  # los consejeros fraudulentos, cada uno en su llama
            for k in range(6):
                fxw = (k * 211 + frame * 0.2 * (1 if k % 2 else -1)) % w.tn.w
                fy_ = w._floor_at(int(fxw) % w.tn.w) or VIEW_H - 10
                x = int(fxw) - cam
                if -10 < x < VIEW_W + 10:
                    for j in range(5):
                        h = 10 + int(4 * math.sin(frame * 0.3 + j + k))
                        pygame.draw.line(view, (255, 160 - j * 20, 40), (x - 2 + j, fy_ - 1), (x - 2 + j, fy_ - h + abs(j - 2) * 2))
                    glow.fill((90, 40, 8), (x // 4, (fy_ - 8) // 4, 2, 2), special_flags=pygame.BLEND_ADD)
                    lights.append((int(fxw), fy_ - 8, 50, (255, 130, 40)))
        if w.level.id == 6:  # Paolo e Francesca, «che 'nsieme vanno»
            for k in range(2):
                fx_ = (frame * 1.3 + k * 9) % (VIEW_W + 80) - 40
                fy_ = 60 + 18 * math.sin(frame * 0.02 + k * 0.4) + k * 6
                pygame.draw.polygon(view, (236, 200, 210), [(fx_, fy_), (fx_ - 9, fy_ - 2), (fx_ - 6, fy_ + 3)])
                pygame.draw.circle(view, (240, 210, 190), (int(fx_ + 1), int(fy_ - 1)), 2)
                lights.append((int(fx_) + cam, int(fy_), 40, (200, 140, 170)))

    # ── piezas ──────────────────────────────────────────────────────────
    def _font(self, view, x, y, opened, frame) -> None:
        """La pila bautismal por la que entra la Compagnia."""
        top = y - 22
        stone, dark, hi = (150, 140, 130), (40, 34, 36), (200, 190, 176)
        for cx_ in (x - 10, x + 10):  # cuelga de cadenas desde la bóveda
            for cy_ in range(top % 4, top, 4):
                view.fill((90, 84, 80), (cx_, cy_, 1, 3))
        pygame.draw.ellipse(view, stone, (x - 14, top, 28, 8))
        pygame.draw.ellipse(view, dark, (x - 11, top + 1, 22, 5))
        pygame.draw.polygon(view, stone, [(x - 13, top + 4), (x + 13, top + 4), (x + 8, top + 12), (x - 8, top + 12)])
        pygame.draw.line(view, hi, (x - 12, top + 4), (x - 7, top + 11))
        pygame.draw.rect(view, stone, (x - 3, top + 12, 6, 4))
        if opened > 0:
            a = int(140 * opened)
            pygame.draw.ellipse(view, (90, 120, 200), (x - 10, top + 2, 20, 3))
            for k in range(3):
                yy = top + 16 + ((frame // 2 + k * 5) % 12)
                view.fill((150, 180, 255) if a > 70 else (90, 110, 160), (x - 1 + (k - 1) * 3, yy, 1, 2))

    def _exit(self, view, glow, x, y, frame, cantica, special) -> None:
        if cantica == "paradiso" or special == "final":
            for k in range(4):
                r = 9 + k * 4 + int(2 * math.sin(frame * 0.08 + k))
                pygame.draw.circle(view, (255, 250, 220 - k * 30), (x, y - 12), r, 1)
            pygame.draw.circle(view, (255, 255, 255), (x, y - 12), 6)
            glow.blit(light_sprite(9, (200, 190, 140)), (x // 4 - 9, (y - 12) // 4 - 9), special_flags=pygame.BLEND_ADD)
            return
        stone = (150, 130, 110) if cantica != "purgatorio" else (220, 210, 190)
        pygame.draw.rect(view, (8, 4, 10), (x - 7, y - 20, 14, 20))
        pygame.draw.circle(view, (8, 4, 10), (x, y - 20), 7)
        pygame.draw.rect(view, stone, (x - 10, y - 20, 3, 20))
        pygame.draw.rect(view, stone, (x + 7, y - 20, 3, 20))
        pygame.draw.arc(view, stone, (x - 10, y - 30, 20, 20), 0, math.pi, 3)
        inner = (255, 210, 120) if cantica != "purgatorio" else (200, 230, 255)
        pygame.draw.rect(view, inner, (x - 5, y - 18, 10, 18))
        pygame.draw.circle(view, inner, (x, y - 18), 5)
        glow.blit(light_sprite(6, (160, 120, 60)), (x // 4 - 6, (y - 14) // 4 - 6), special_flags=pygame.BLEND_ADD)
        for tx in (x - 13, x + 12):  # braseros
            pygame.draw.rect(view, (90, 70, 50), (tx - 1, y - 8, 3, 8))
            for k in range(4):
                c = (255, 230, 80) if (frame // 3 + k) % 3 == 0 else (255, 120, 30)
                view.fill(c, (tx + (k % 2) - (k % 3 == 2), y - 10 - k - (frame // 4 + k) % 2, 1, 1))
            glow.fill((70, 30, 6), (tx // 4 - 1, (y - 12) // 4 - 1, 3, 3), special_flags=pygame.BLEND_ADD)

    def _pickup(self, view, glow, p: Pickup, cam, frame, lights) -> None:
        x, y = p.x - cam, p.y - 8 + int(2 * math.sin(frame * 0.08 + p.x))
        if x < -10 or x > VIEW_W + 10:
            return
        if p.kind == "pagina":
            pygame.draw.rect(view, (240, 228, 196), (x - 3, y - 3, 7, 9))
            for k in range(3):
                view.fill((120, 90, 60), (x - 2, y - 1 + k * 2, 5, 1))
            glow.fill((50, 46, 30), (x // 4, y // 4, 2, 2), special_flags=pygame.BLEND_ADD)
            lights.append((p.x, y, 30, (120, 110, 80)))
            return
        if p.kind == "oficio":  # el oficio escondido de Neifile: un rollo con cinta verde
            pygame.draw.rect(view, (226, 210, 170), (x - 4, y - 2, 9, 5))
            pygame.draw.circle(view, (200, 184, 140), (x - 4, y), 2)
            pygame.draw.circle(view, (200, 184, 140), (x + 5, y), 2)
            view.fill((60, 170, 80), (x, y - 2, 1, 5))
            glow.fill((20, 40, 20), (x // 4, y // 4, 1, 1), special_flags=pygame.BLEND_ADD)
            return
        if p.kind == "giunco":
            for k in range(4):
                pygame.draw.line(view, (120, 160, 70), (x - 3 + k * 2, y + 8), (x - 4 + k * 2 + (frame // 20 + k) % 2, y - 4))
            return
        col = PALLE_INFO[p.kind][2]
        pygame.draw.circle(view, (240, 196, 70), (x, y), 5)  # campo de oro
        pygame.draw.circle(view, col, (x, y), 4)
        if p.kind == "giglio":
            view.fill((255, 220, 80), (x - 1, y - 2, 3, 1))
            view.fill((255, 220, 80), (x, y - 3, 1, 4))
        view.fill((255, 255, 255), (x - 2, y - 2, 2, 1))
        sp = (frame // 3 + p.x) % 24
        if sp < 4:
            view.fill((255, 255, 255), (x + 2 - sp // 2, y - 5 + sp, 1, 1))
        glow.blit(light_sprite(3, tuple(v // 2 for v in col)), (x // 4 - 3, y // 4 - 3), special_flags=pygame.BLEND_ADD)
        lights.append((p.x, y, 36, tuple(min(255, v + 60) for v in col)))

    def _caravaggio(self, view, glow, cam, frame, lights) -> None:
        """Michelangelo Merisi espera en el Antepurgatorio, con su paleta."""
        w = self.world
        x = int(w.terrain.w * 0.62)
        y = w._floor_at(x) or VIEW_H - 20
        sx = x - cam
        pygame.draw.rect(view, (30, 22, 20), (sx - 3, y - 12, 7, 10))
        pygame.draw.circle(view, (210, 160, 120), (sx, y - 15), 3)
        view.fill((30, 20, 14), (sx - 3, y - 18, 7, 2))
        view.fill((30, 22, 20), (sx - 2, y - 2, 2, 2))
        view.fill((30, 22, 20), (sx + 1, y - 2, 2, 2))
        pygame.draw.ellipse(view, (170, 120, 70), (sx + 4, y - 10, 7, 4))
        for k, c in enumerate(((200, 30, 30), (240, 200, 80), (250, 240, 220))):
            view.fill(c, (sx + 5 + k * 2, y - 9, 1, 1))
        lights.append((x + 40, y - 60, 90, (200, 170, 120)))

    def _guard(self, view, glow, g: Guardian, cam, frame, lights) -> None:
        x, y = g.x - cam, g.y
        if x < -40 or x > VIEW_W + 40:
            return
        a = g.anim
        dim = g.pacified
        k = g.kind
        eyes = (255, 60, 20)
        if k in ("caronte", "flegias"):
            body = (60, 54, 60)
            pygame.draw.polygon(view, body, [(x - 7, y), (x + 7, y), (x + 4, y - 22), (x - 4, y - 22)])
            pygame.draw.circle(view, (170, 160, 150), (x, y - 25), 4)
            pygame.draw.line(view, (220, 220, 220), (x - 3, y - 22), (x - 1, y - 16), 2)  # barba
            pygame.draw.line(view, (110, 80, 50), (x + 8, y - 30), (x + 6, y + 2), 2)  # remo
            eye_y = y - 26
        elif k == "cerbero":
            pygame.draw.ellipse(view, (60, 40, 34), (x - 12, y - 14, 24, 12))
            for dx in (-9, 0, 9):
                hy = y - 18 - int(2 * math.sin(a * 0.15 + dx))
                pygame.draw.circle(view, (70, 46, 38), (x + dx, hy), 4)
                view.fill(eyes if not dim else (80, 60, 50), (x + dx + 1, hy - 1, 2, 1))
            for lx in (-9, -4, 4, 9):
                view.fill((50, 34, 30), (x + lx, y - 3, 2, 3))
            eye_y = None
        elif k in ("furie", "arpie"):
            eye_y = None
            for dx in (-8, 0, 8):
                bob = int(3 * math.sin(a * 0.2 + dx))
                pygame.draw.polygon(view, (90, 30, 40), [(x + dx - 3, y - 4 + bob), (x + dx + 3, y - 4 + bob), (x + dx, y - 18 + bob)])
                pygame.draw.circle(view, (200, 160, 140), (x + dx, y - 19 + bob), 2)
                wing = 6 + int(3 * math.sin(a * 0.4 + dx))
                pygame.draw.line(view, (60, 20, 30), (x + dx, y - 14 + bob), (x + dx - wing, y - 20 + bob))
                pygame.draw.line(view, (60, 20, 30), (x + dx, y - 14 + bob), (x + dx + wing, y - 20 + bob))
                if not dim:
                    view.fill(eyes, (x + dx, y - 20 + bob, 1, 1))
        elif k in ("angelo", "pietro", "giacomo", "giovanni", "catone"):
            robe = (250, 250, 255) if k == "angelo" else (200, 150, 90) if k == "catone" else (240, 220, 180)
            pygame.draw.polygon(view, robe, [(x - 7, y), (x + 7, y), (x + 3, y - 20), (x - 3, y - 20)])
            pygame.draw.circle(view, (240, 200, 170), (x, y - 23), 3)
            if k == "angelo":
                for s in (-1, 1):
                    pygame.draw.polygon(view, (255, 255, 255), [(x, y - 18), (x + s * 14, y - 28 - int(2 * math.sin(a * 0.1))), (x + s * 9, y - 8)])
                pygame.draw.line(view, (255, 240, 150), (x + 6, y - 14), (x + 10, y - 32), 2)  # espada
            else:
                pygame.draw.circle(view, (255, 220, 120), (x, y - 24), 6, 1)  # aureola
                if k == "catone":
                    pygame.draw.line(view, (240, 240, 240), (x - 2, y - 21), (x, y - 14), 2)
            lights.append((g.x, y - 18, 70, (255, 250, 220)))
            eye_y = None
        else:  # lupa, minosse, pluto, centauri y demás
            body = {"lupa": (90, 90, 96), "minosse": (70, 40, 40), "pluto": (90, 70, 40), "centauri": (120, 80, 50),
                    "lonza": (190, 150, 70), "leone": (176, 130, 60)}.get(k, (80, 50, 50))
            if k in ("lupa", "centauri", "lonza", "leone"):
                pygame.draw.ellipse(view, body, (x - 10, y - 12, 20, 9))
                pygame.draw.circle(view, body, (x - 10, y - 14), 4)
                for lx in (-7, -3, 4, 8):
                    view.fill(body, (x + lx, y - 4, 2, 4))
                if k == "lonza":  # «di pel macolato era coverta»
                    for sx_ in (-6, -1, 4):
                        view.fill((70, 50, 20), (x + sx_, y - 10, 2, 2))
                if k == "leone":
                    pygame.draw.circle(view, (120, 80, 30), (x - 10, y - 14), 6)
                    pygame.draw.circle(view, body, (x - 10, y - 14), 4)
                if k == "centauri":
                    pygame.draw.rect(view, (200, 150, 110), (x - 12, y - 24, 4, 10))
                    pygame.draw.arc(view, (150, 110, 60), (x - 20, y - 26, 8, 14), -1.4, 1.4, 1)
                eye_y = y - 15
                x -= 11
            else:
                pygame.draw.polygon(view, body, [(x - 9, y), (x + 9, y), (x + 6, y - 24), (x - 6, y - 24)])
                pygame.draw.circle(view, body, (x, y - 27), 5)
                if k == "minosse":
                    pts = [(x + 8 + int(6 * math.sin(t * 0.5 + a * 0.1)), y - 4 - t * 2) for t in range(10)]
                    pygame.draw.lines(view, (110, 60, 50), False, pts, 2)
                if k == "pluto":
                    pygame.draw.circle(view, (240, 196, 70), (x - 9, y - 12), 3)
                eye_y = y - 28
        if eye_y is not None and not dim:
            view.fill(eyes, (x - 2, eye_y, 2, 1))
            view.fill(eyes, (x + 1, eye_y, 2, 1))
            glow.fill((140, 30, 10), (x // 4, eye_y // 4, 1, 1), special_flags=pygame.BLEND_ADD)
        if not dim and k not in ("angelo", "pietro", "giacomo", "giovanni", "catone"):
            lights.append((g.x, y - 14, 50, (200, 60, 30)))
        if not dim and GUARDS[k][2] and g.touched:
            frac = g.timer / (GUARDS[k][2] * TPS)
            pygame.draw.arc(view, (255, 240, 180), (g.x - cam - 8, y - 46, 16, 16), math.pi / 2, math.pi / 2 + frac * math.tau, 2)


def skill_shadow(w: World, L: Lemming, skill: Skill) -> list[tuple[int, int]]:
    """Puntos (marco del alma) por donde irá el oficio, como las sombras de NeoLemmix."""
    t = w.ti if L.inv else w.tn
    pts: list[tuple[int, int]] = []
    x, y, d = L.x, L.y, L.dir
    steel = lambda xx, yy: 0 <= yy < t.h and 0 <= xx < t.w and t.k[yy, xx] in (STEEL,)  # noqa: E731
    if skill == Skill.CAPOMASTRO:
        for k in range(BRICKS):
            for dx in range(0, 6, 2):
                pts.append((x + 2 * k * d + dx * d, y - 1 - k))
    elif skill == Skill.PIAGNONE:
        for k in range(0, 200, 2):
            xx = x + k * d
            if steel(xx, y - 4) or not (0 <= xx < t.w):
                break
            pts += [(xx, y - 10), (xx, y)]
    elif skill == Skill.MINATORE:
        for k in range(0, 80):
            xx, yy = x + 2 * k * d, y + k
            if steel(xx, yy) or yy >= t.h:
                break
            pts += [(xx, yy - 10), (xx + 2 * d, yy)]
    elif skill == Skill.BECCHINO:
        for k in range(0, 160, 2):
            if steel(x, y + k) or y + k >= t.h:
                break
            pts += [(x - 5, y + k), (x + 5, y + k)]
    elif skill == Skill.BUBBONE:
        for a in range(0, 360, 12):
            pts.append((x + int(BOMB_RADIUS * math.cos(math.radians(a))), y - 6 + int(BOMB_RADIUS * math.sin(math.radians(a)))))
    elif skill == Skill.MEDICO:
        for a in range(0, 360, 10):
            pts.append((x + int(MEDICO_RANGE * math.cos(math.radians(a))), y - 6 + int(MEDICO_RANGE * math.sin(math.radians(a)))))
    if L.inv:
        pts = [(px, VIEW_H - 1 - py) for px, py in pts]
    return pts


def _overlay(mask: np.ndarray, colors: np.ndarray, alpha: int) -> pygame.Surface:
    h, w = mask.shape
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    rgb = pygame.surfarray.pixels3d(surf)
    a = pygame.surfarray.pixels_alpha(surf)
    rgb[mask.T] = colors[mask]
    a[mask.T] = alpha
    del rgb, a
    return surf


# ═══════════════════════════════════════════════════════════════════════════
# 7. SONIDO — síntesis pura: canto llano, laude, polifonía, laúd
# ═══════════════════════════════════════════════════════════════════════════

SR = 22050
NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def _freq(name: str) -> float:
    return 440.0 * 2 ** ((NOTE[name[:-1]] + 12 * (int(name[-1]) + 1) - 69) / 12)


def _env(n: int, decay: float) -> np.ndarray:
    return np.exp(-np.linspace(0, decay, n))


def _adsr(n: int, a: float = 0.05, r: float = 0.2) -> np.ndarray:
    e = np.ones(n)
    na, nr = max(1, int(n * a)), max(1, int(n * r))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return e


def _tone(freq, dur: float, wave: str = "sine", decay: float = 3.0) -> np.ndarray:
    n = int(SR * dur)
    f = np.broadcast_to(np.asarray(freq, dtype=float), (n,))
    phase = np.cumsum(f) / SR
    match wave:
        case "square":
            sig = np.sign(np.sin(phase * math.tau))
        case "tri":
            sig = 2 * np.abs(2 * (phase % 1) - 1) - 1
        case _:
            sig = np.sin(phase * math.tau)
    return sig * _env(n, decay)


def _noise(dur: float, decay: float, rng: np.random.Generator, smooth: int = 1) -> np.ndarray:
    n = int(SR * dur)
    x = rng.uniform(-1, 1, n)
    if smooth > 1:
        x = np.convolve(x, np.ones(smooth) / smooth, mode="same") * math.sqrt(smooth)
    return x * _env(n, decay)


def _sweep(f0: float, f1: float, dur: float) -> np.ndarray:
    return np.linspace(f0, f1, int(SR * dur))


def _voice(freq: float, dur: float, vowel: str = "a", vib: float = 0.006) -> np.ndarray:
    """Voz coral aditiva con formantes aproximados y vibrato."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = freq * (1 + vib * np.sin(math.tau * 5.2 * t + freq))
    phase = np.cumsum(f) / SR
    formants = {"a": (750, 1150), "o": (480, 850), "u": (330, 700), "e": (500, 1700), "i": (300, 2300)}[vowel]
    out = np.zeros(n)
    for h in range(1, 14):
        fh = freq * h
        w = sum(math.exp(-((fh - F) / 160) ** 2) for F in formants) + 0.25 / h
        out += w * np.sin(math.tau * h * phase + h)
    return out / 3.5 * _adsr(n, 0.12, 0.25)


def _bell(freq: float, dur: float) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for ratio, amp, dec in ((1, 1, 1.6), (2.76, 0.5, 2.4), (5.4, 0.25, 3.6), (8.93, 0.12, 5)):
        out += amp * np.sin(math.tau * freq * ratio * t) * np.exp(-t * dec)
    return out / 1.8


def _pluck(freq: float, dur: float, rng: np.random.Generator, bright: float = 0.5) -> np.ndarray:
    """Karplus-Strong vectorizado por bloques: el laúd de la villa."""
    n = int(SR * dur)
    p = max(2, int(SR / freq))
    buf = rng.uniform(-1, 1, p)
    out = np.empty(n)
    k = 0
    prev = buf
    while k < n:
        m = min(p, n - k)
        out[k : k + m] = prev[:m]
        shifted = np.roll(prev, 1)
        prev = (0.5 + bright * 0.0) * (prev + shifted) * 0.996
        k += m
    return out * _adsr(n, 0.002, 0.1)


def _mix(*parts: tuple[np.ndarray, float]) -> np.ndarray:
    n = max(len(a) for a, _ in parts)
    out = np.zeros(n)
    for a, g in parts:
        out[: len(a)] += a * g
    return out


def _place(out: np.ndarray, sig: np.ndarray, at: float, gain: float = 1.0) -> None:
    s = int(at * SR)
    if s >= len(out):
        return
    e = min(len(out), s + len(sig))
    out[s:e] += sig[: e - s] * gain


# Dies irae (secuencia gregoriana, s. XIII): incipit
DIES_IRAE = "F3 E3 F3 D3 E3 C3 D3 D3 F3 F3 G3 F3 E3 D3 C3 E3 F3 E3 D3".split()
# Lauda original en modo dórico, al estilo de los laudarios de las cofradías
LAUDA = "D4 E4 F4 G4 A4 A4 G4 F4 E4 F4 G4 E4 D4 - A4 C5 B4 A4 G4 A4 F4 G4 A4 G4 F4 E4 D4 -".split()
BALLATA = "A4 B4 C5 D5 E5 D5 C5 B4 A4 G4 A4 B4 C5 B4 A4 - E5 D5 C5 B4 C5 A4 B4 G4 A4 - - -".split()


def compose(style: str) -> np.ndarray:
    rng = np.random.default_rng(1348)
    if style == "inferno" or style == "cocito":
        dur = 22.0
        out = np.zeros(int(SR * dur))
        t = np.arange(len(out)) / SR
        root = 73.4 if style == "inferno" else 110
        out += 0.18 * np.sin(math.tau * root * t) * (0.7 + 0.3 * np.sin(math.tau * 0.11 * t))
        out += 0.12 * np.sin(math.tau * root * 1.5 * t + 1)
        out += 0.05 * np.sin(math.tau * root * 2.01 * t)
        step = 0.95
        for k, nt in enumerate(DIES_IRAE):
            v = _voice(_freq(nt) * (1 if style == "inferno" else 2), step * 1.15, "u" if style == "inferno" else "o")
            _place(out, v, 1.0 + k * step, 0.35)
        if style == "inferno":
            for k in range(0, 22, 2):  # cadenas y tambor
                _place(out, _tone(_sweep(90, 38, 0.5), 0.5, decay=5), k + 0.5, 0.5)
                ch = _noise(0.25, 9, rng, 1) * np.sin(math.tau * 2400 * np.arange(int(SR * 0.25)) / SR)
                _place(out, ch, k + 1.4, 0.12)
        else:
            for k in range(8):
                _place(out, _bell(_freq(rng.choice(["E5", "B5", "G5", "D6"])), 3.0), rng.uniform(0, 19), 0.07)
        return out
    if style == "purgatorio" or style == "limbo":
        step = 0.5
        dur = len(LAUDA) * step * 2 + 1
        out = np.zeros(int(SR * dur))
        t = np.arange(len(out)) / SR
        out += 0.08 * np.sin(math.tau * 73.4 * t) + 0.05 * np.sin(math.tau * 110 * t)
        for rep in range(2):
            for k, nt in enumerate(LAUDA):
                if nt == "-":
                    continue
                at = 0.5 + (rep * len(LAUDA) + k) * step
                _place(out, _voice(_freq(nt), step * 1.2, "a" if rep == 0 else "o"), at, 0.32)
                if rep == 1:  # la segunda voz entra a la quinta inferior
                    f = _freq(nt) * 2 / 3
                    _place(out, _voice(f, step * 1.2, "o"), at, 0.18)
                if style == "purgatorio" and k % 2 == 0:
                    _place(out, _pluck(_freq(nt) / 2, 0.8, rng), at, 0.12)
        return out
    if style == "paradiso":
        chords = [("D4", "F#4", "A4"), ("G3", "B3", "D4"), ("A3", "C#4", "E4"), ("B3", "D4", "F#4"),
                  ("G3", "B3", "D4"), ("A3", "C#4", "E4"), ("D4", "F#4", "A4"), ("D4", "A4", "D5")]
        step = 3.0
        out = np.zeros(int(SR * (len(chords) * step + 2)))
        for k, ch in enumerate(chords):
            for nt in ch:
                for det in (0.997, 1.003):
                    v = _voice(_freq(nt) * det, step * 1.4, "a", 0.003)
                    _place(out, v, k * step, 0.12)
        for _ in range(16):
            _place(out, _bell(_freq(rng.choice(["D6", "E6", "F#6", "A6", "B6", "D7"])), 2.5), rng.uniform(0, len(out) / SR - 3), 0.06)
        return out
    if style == "firenze" or style == "villa":
        step = 0.32
        dur = len(BALLATA) * step * 2 + 1
        out = np.zeros(int(SR * dur))
        for rep in range(2):
            for k, nt in enumerate(BALLATA):
                if nt == "-":
                    continue
                at = 0.3 + (rep * len(BALLATA) + k) * step
                f = _freq(nt) * (1 if style == "villa" else 0.5)
                _place(out, _pluck(f, 1.0, rng), at, 0.34)
                if k % 4 == 0:
                    _place(out, _pluck(f / 2, 1.4, rng), at, 0.22)
        if style == "firenze":
            for k in range(0, int(dur), 4):  # la campana de difuntos
                _place(out, _bell(146.8, 4.0), k + 0.2, 0.25)
        return out
    return np.zeros(int(SR * 2))


# ── Voz: el italiano se lee casi como se escribe, así que unas reglas bastan ──
_IT_VOW = "aeiou"
FORMANTS = {
    "a": (750, 1200, 2500), "e": (480, 1800, 2500), "i": (300, 2250, 3000), "o": (480, 850, 2400),
    "u": (320, 750, 2300), "w": (320, 750, 2300), "j": (300, 2200, 3000), "m": (280, 1100, 2200),
    "n": (280, 1600, 2600), "N": (280, 1900, 2700), "l": (360, 1300, 2700), "L": (300, 1900, 2700),
    "r": (450, 1300, 1700), "v": (300, 1100, 2300), "z": (300, 1700, 2600), "dZ": (300, 1900, 2600),
}


def it_phonemes(text: str) -> list[str]:
    """Grafemas italianos → fonemas sencillos. «." y "," son pausas."""
    t = text.lower().translate(str.maketrans("àáèéìíòóùúâêîôû", "aaeeiioouuaeiou"))
    out: list[str] = []
    i, n = 0, len(t)

    def at(k):
        return t[k] if 0 <= k < n else "#"

    def isv(ch):
        return ch in _IT_VOW and ch != ""

    while i < n:
        c, nx = t[i], at(i + 1)
        if c in ".;:!?«»":
            out.append("||")
        elif c in ", ":
            out.append("|")
        elif c in _IT_VOW:
            if c == "i" and isv(nx) and not isv(at(i - 1)) and at(i - 1) != "|":
                out.append("j")
            elif c == "u" and at(i - 1) in "qg" and isv(nx):
                out.append("w")
            else:
                out.append(c)
        elif c == "c":
            if nx == "h":
                out.append("k")
                i += 1
            elif nx in "ei":
                out.append("tS")
                if nx == "i" and isv(at(i + 2)):
                    i += 1
            else:
                out.append("k")
        elif c == "g":
            if nx == "h":
                out.append("g")
                i += 1
            elif nx == "l" and at(i + 2) == "i":
                out.append("L")
                i += 2 if isv(at(i + 3)) else 1
            elif nx == "n":
                out.append("N")
                i += 1
            elif nx in "ei":
                out.append("dZ")
                if nx == "i" and isv(at(i + 2)):
                    i += 1
            else:
                out.append("g")
        elif c == "s":
            if nx == "c" and at(i + 2) in "ei":
                out.append("S")
                i += 1
                if at(i + 1) == "i" and isv(at(i + 2)):
                    i += 1
            elif isv(at(i - 1)) and isv(nx):
                out.append("z")
            else:
                out.append("s")
        elif c == "z":
            out.append("ts")
        elif c == "q":
            out.append("k")
        elif c == "x":
            out += ["k", "s"]
        elif c in "jy":
            out.append("i")
        elif c == "h":
            pass
        elif c.isalpha():
            out.append(c if c in "bdfgklmnprstv" else "")
        if out and len(out) >= 2 and out[-1] and out[-1] == out[-2] and out[-1] not in _IT_VOW and not out[-1].startswith("|"):
            out[-1] = out[-1] + ":"  # consonante geminada
            out.pop(-2)
        i += 1
    return [p for p in out if p]


def _voiced(f0: float, fmts: tuple[int, int, int], dur: float, amp: float = 1.0) -> np.ndarray:
    n = int(SR * dur)
    if n <= 0:
        return np.zeros(0)
    t = np.arange(n) / SR
    f = f0 * (1 + 0.004 * np.sin(math.tau * 5.5 * t))
    phase = np.cumsum(f) / SR
    out = np.zeros(n)
    for h in range(1, int(4200 / f0) + 1):
        fh = f0 * h
        w = sum(math.exp(-((fh - F) / (90 + 30 * k)) ** 2) / (1 + k * 0.6) for k, F in enumerate(fmts)) + 0.02 / h
        out += w * np.sin(math.tau * h * phase)
    return out * amp


def _hiss(dur: float, rng: np.random.Generator, color: str) -> np.ndarray:
    n = int(SR * dur)
    x = rng.uniform(-1, 1, n)
    if color == "s":
        x = np.diff(np.diff(x, prepend=0), prepend=0) * 0.5
    elif color == "S":
        x = np.diff(x, prepend=0)
        x = np.convolve(x, np.ones(2) / 2, mode="same")
    else:
        x = np.convolve(x, np.ones(4) / 4, mode="same")
    return x


def synth_italian(text: str, f0: float) -> np.ndarray:
    """Recitado sintético: fuente armónica + formantes, ruido para fricativas y explosiones."""
    ph = it_phonemes(text)[:160]
    rng = np.random.default_rng(len(text))
    parts: list[np.ndarray] = []
    total = max(1, len(ph))
    for k, p in enumerate(ph):
        gem = p.endswith(":")
        p = p.rstrip(":")
        prog = k / total
        nxt = ph[k + 1] if k + 1 < len(ph) else "||"
        pitch = f0 * (1.12 - 0.25 * prog)
        if p in _IT_VOW:
            long_ = nxt in ("|", "||") or (k + 2 < len(ph) and ph[k + 2] in ("|", "||"))
            d = 0.12 if long_ else 0.072
            if long_:
                pitch *= 0.95
            seg = _voiced(pitch, FORMANTS[p], d)
        elif p in ("|", "||"):
            seg = np.zeros(int(SR * (0.05 if p == "|" else 0.22)))
        elif p in ("m", "n", "N", "l", "L", "w", "j", "v", "z"):
            d = 0.05 * (1.8 if gem else 1)
            seg = _voiced(pitch, FORMANTS[p], d, 0.45 if p in "mnN" else 0.7)
            if p in "vz":
                seg += _hiss(d, rng, "s" if p == "z" else "f") * 0.25
        elif p == "r":
            d = 0.055 * (1.8 if gem else 1)
            seg = _voiced(pitch, FORMANTS["r"], d, 0.7)
            seg *= 0.55 + 0.45 * np.sin(math.tau * 28 * np.arange(len(seg)) / SR)
        elif p in ("f", "s", "S"):
            d = 0.07 * (1.6 if gem else 1)
            seg = _hiss(d, rng, p) * (0.35 if p == "f" else 0.55)
        elif p in ("p", "t", "k", "b", "d", "g", "tS", "dZ", "ts"):
            close = 0.04 * (1.8 if gem else 1)
            seg = np.zeros(int(SR * close))
            if p in ("b", "d", "g", "dZ"):
                seg = _voiced(pitch, (250, 900, 2400), close, 0.25)
            burst = _hiss(0.012, rng, "s" if p in ("t", "ts") else "S" if p in ("tS", "dZ") else "f")
            burst *= np.linspace(1, 0, len(burst)) * 0.7
            seg = np.concatenate([seg, burst])
            if p in ("tS", "dZ", "ts"):
                seg = np.concatenate([seg, _hiss(0.05, rng, "S" if p != "ts" else "s") * 0.45])
        else:
            continue
        if len(seg) > 16:
            fade = min(len(seg) // 3, int(SR * 0.006))
            seg[:fade] *= np.linspace(0, 1, fade)
            seg[-fade:] *= np.linspace(1, 0, fade)
        parts.append(seg)
    if not parts:
        return np.zeros(1)
    sig = np.concatenate(parts)
    peak = np.abs(sig).max() or 1
    return sig / peak * 0.8


VOICE_PITCH = {
    "Virgilio": 108, "Il Maestro": 92, "Beatrice": 236, "San Bernardo": 118, "Savonarola": 128, "Matelda": 246,
    "Brunelleschi": 132, "Botticelli": 142, "Caravaggio": 116, "Dioneo": 152, "Filostrato": 128, "Panfilo": 138,
    "Pier della Vigna": 100, "L'Angelo": 300, "Caronte": 76, "Cerbero": 64, "Pluto": 70, "Minosse": 72,
}


class Sfx:
    def __init__(self, enabled: bool):
        self.ok = False
        self.voices = True
        self.vol = 0.8
        self.vch: pygame.mixer.Channel | None = None
        self._said: dict[tuple[str, str], pygame.mixer.Sound] = {}
        self._voice_req: tuple[str, str] | None = None
        self.music_on = enabled
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.tracks: dict[str, pygame.mixer.Sound] = {}
        self.current: str | None = None
        self.channel: pygame.mixer.Channel | None = None
        if not enabled:
            return
        try:
            pygame.mixer.init(SR, -16, 2, 512)
            init = pygame.mixer.get_init()
        except pygame.error:
            return
        if not init:
            return
        pygame.mixer.set_num_channels(24)
        self.channels = init[2]
        rng = np.random.default_rng(3)
        lib = {
            "assign": _bell(1320, 0.12) * 0.6,
            "letsgo": _mix((_voice(_freq("D4"), 0.9, "a"), 1), (_voice(_freq("A4"), 0.9, "a"), 0.7)),
            "door": _noise(0.4, 6, rng, 40),
            "splat": _noise(0.18, 8, rng, 6),
            "boom": _mix((_noise(0.7, 5, rng, 3), 1.3), (_tone(_sweep(120, 30, 0.7), 0.7, decay=3), 0.8)),
            "yippee": _mix((_bell(1568, 0.5), 0.7), (_bell(2093, 0.4), 0.4)),
            "ting": _bell(2100, 0.4),
            "drown": _tone(_sweep(500, 120, 0.4) * (1 + 0.1 * np.sin(np.arange(int(SR * 0.4)) / 300)), 0.4, "sine", 2),
            "burn": _noise(0.35, 4, rng, 2),
            "ohno": _tone(_sweep(700, 300, 0.3), 0.3, "tri", decay=1),
            "brick": _tone(500, 0.03, "square", decay=8) * 0.4,
            "warn": _tone(1000, 0.05, "square", decay=2) * 0.6,
            "trap": np.concatenate([_noise(0.08, 2, rng, 1), _tone(70, 0.3, decay=4)]),
            "click": _tone(900, 0.02, decay=6) * 0.4,
            "coin": np.concatenate([_bell(1975, 0.08), _bell(2637, 0.35)]) * 0.7,
            "palla": _mix((_bell(880, 0.6), 0.6), (_bell(1320, 0.5), 0.3)),
            "combo": np.concatenate([_voice(_freq(n), 0.22, "a", 0.0) for n in ("A4", "C#5", "E5")]) * 1.4,
            "pagina": _noise(0.25, 7, rng, 12) * 0.5,
            "cure": np.concatenate([_bell(_freq(n), 0.25)[: int(SR * 0.12)] for n in ("D6", "F#6", "A6", "D7")]) * 0.6,
            "bribe": np.concatenate([_bell(_freq(n), 0.2)[: int(SR * 0.1)] for n in ("E6", "G6", "B6")]) * 0.6,
            "lume": _mix((_voice(_freq("D5"), 1.4, "a", 0.002), 1), (_voice(_freq("A5"), 1.4, "a", 0.002), 0.6)),
            "panic": _tone(_sweep(300, 900, 0.5), 0.5, "square", 1.5) * 0.5,
        }
        self.sounds = {k: self._make(v * 0.32) for k, v in lib.items()}
        self.ok = True

    def _make(self, mono: np.ndarray) -> pygame.mixer.Sound:
        a = (np.clip(mono, -1, 1) * 32767).astype(np.int16)
        if self.channels == 2:
            a = np.column_stack([a, a])
        return pygame.sndarray.make_sound(np.ascontiguousarray(a))

    def play(self, name: str) -> None:
        if self.ok and name in self.sounds:
            ch = self.sounds[name].play()
            if ch:
                ch.set_volume(self.vol)

    def speak(self, who: str, text: str) -> None:
        """Recita en italiano el texto, con la voz (el tono) de quien habla."""
        if not self.ok or not self.voices:
            return
        key = (who, text[:80])
        snd = self._said.get(key)
        if snd is not None:
            self._voice_play(snd)
            return
        self._voice_req = key

        def work() -> None:
            f0 = VOICE_PITCH.get(who, 200 + (sum(map(ord, who)) % 5) * 12 if who else 150)
            s = self._make(synth_italian(text, f0) * 0.55)
            if len(self._said) > 64:
                self._said.clear()
            self._said[key] = s
            if self._voice_req == key:  # si entretanto habló otro, este calla
                self._voice_play(s)

        threading.Thread(target=work, daemon=True).start()

    def _voice_play(self, snd: pygame.mixer.Sound) -> None:
        if self.vch:
            self.vch.stop()
        self.vch = snd.play()
        if self.vch:
            self.vch.set_volume(self.vol * 0.9)

    def set_volume(self, v: float) -> None:
        self.vol = max(0.0, min(1.0, v))
        if self.channel:
            self.channel.set_volume(self.vol)

    def music(self, style: str | None) -> None:
        if not self.ok:
            return
        if style == "silence":
            style = None
        if not self.music_on or style is None:
            if self.channel:
                self.channel.fadeout(600)
            self.current = None
            return
        if style == self.current and self.channel and self.channel.get_busy():
            return
        if style not in self.tracks:
            self.tracks[style] = self._make(compose(style) * 0.5)
        if self.channel:
            self.channel.fadeout(500)
        self.channel = self.tracks[style].play(-1, fade_ms=900)
        if self.channel:
            self.channel.set_volume(self.vol)
        self.current = style

    def toggle(self, style: str | None) -> None:
        self.music_on = not self.music_on
        self.current = None
        self.music(style)


# ═══════════════════════════════════════════════════════════════════════════
# 8. TEXTOS — pagine, códice, Brigata, finales
# ═══════════════════════════════════════════════════════════════════════════

VERSES = {
    "proemio": [
        ("Umana cosa è aver compassione degli afflitti.", "Decameron, Proemio"),
    ],
    "inferno": [
        ("Nel mezzo del cammin di nostra vita / mi ritrovai per una selva oscura, / ché la diritta via era smarrita.", "Inf. I, 1–3"),
        ("Per me si va ne la città dolente, / per me si va ne l'etterno dolore, / per me si va tra la perduta gente.", "Inf. III, 1–3"),
        ("Lasciate ogne speranza, voi ch'intrate.", "Inf. III, 9"),
        ("Vuolsi così colà dove si puote / ciò che si vuole, e più non dimandare.", "Inf. III, 95–96"),
        ("Amor, ch'a nullo amato amar perdona", "Inf. V, 103"),
        ("Nessun maggior dolore / che ricordarsi del tempo felice / ne la miseria", "Inf. V, 121–123"),
        ("Pape Satàn, pape Satàn aleppe!", "Inf. VII, 1"),
        ("Considerate la vostra semenza: / fatti non foste a viver come bruti, / ma per seguir virtute e canoscenza.", "Inf. XXVI, 118–120"),
        ("La bocca sollevò dal fiero pasto / quel peccator", "Inf. XXXIII, 1–2"),
        ("Poscia, più che 'l dolor, poté 'l digiuno.", "Inf. XXXIII, 75"),
        ("E quindi uscimmo a riveder le stelle.", "Inf. XXXIV, 139"),
    ],
    "purgatorio": [
        ("Per correr miglior acque alza le vele / omai la navicella del mio ingegno", "Purg. I, 1–2"),
        ("libertà va cercando, ch'è sì cara, / come sa chi per lei vita rifiuta.", "Purg. I, 71–72"),
        ("Ricorditi di me, che son la Pia; / Siena mi fé, disfecemi Maremma", "Purg. V, 133–134"),
        ("Ahi serva Italia, di dolore ostello, / nave sanza nocchiere in gran tempesta", "Purg. VI, 76–77"),
        ("Era già l'ora che volge il disio / ai navicanti e 'ntenerisce il core", "Purg. VIII, 1–2"),
        ("Credette Cimabue ne la pittura / tener lo campo, e ora ha Giotto il grido", "Purg. XI, 94–95"),
        ("Non è il mondan romore altro ch'un fiato / di vento", "Purg. XI, 100–101"),
        ("puro e disposto a salire a le stelle.", "Purg. XXXIII, 145"),
    ],
    "paradiso": [
        ("La gloria di colui che tutto move / per l'universo penetra, e risplende / in una parte più e meno altrove.", "Par. I, 1–3"),
        ("E 'n la sua volontade è nostra pace", "Par. III, 85"),
        ("Tu proverai sì come sa di sale / lo pane altrui, e come è duro calle / lo scendere e 'l salir per l'altrui scale.", "Par. XVII, 58–60"),
        ("Vergine Madre, figlia del tuo figlio, / umile e alta più che creatura", "Par. XXXIII, 1–2"),
        ("l'amor che move il sole e l'altre stelle.", "Par. XXXIII, 145"),
    ],
}


def verse_of(i: int) -> tuple[str, str]:
    c = cantica_of(i)
    vs = VERSES[c]
    if i == 100:
        return VERSES["paradiso"][-1]
    if i == 34:
        return VERSES["inferno"][-1]
    if i == 1:
        return VERSES["inferno"][0]
    return vs[i % len(vs)]


CODEX = [
    ("Flagelantes de 1349", "Hábito blanco y cruz roja; 33 días y medio de penitencia; obediencia a los Maestros.", "dato"),
    ("Condena papal", "Clemente VI publicó una bula contra ellos el 20 de octubre de 1349.", "dato"),
    ("Flagelantes y contagio", "Algunas ciudades notaron brotes de peste al paso de las procesiones.", "dato, con matiz"),
    ("Las palle", "8 bolas en Cosimo, 7 en Piero, 6 en Lorenzo (Sheldon & Newell, 1906).", "dato"),
    ("La palla azul", "1465: Luis XI concede la bola superior azul con tres lises de oro.", "dato"),
    ("«Palle, palle, palle!»", "Grito de guerra de los partidarios mediceos.", "dato"),
    ("Origen de las palle", "Píldoras, bezantes del Arte del Cambio, naranjas: ninguna probada.", "tesis"),
    ("Hoguera de las Vanidades", "7 de febrero de 1497, Piazza della Signoria.", "dato"),
    ("Dante y Boccaccio en la hoguera", "Que fueran objetivo específico: fuente única. Pendiente de verificar.", "fuente única"),
    ("Caravaggio y la peste", "La peste de 1576–77 se llevó a su padre y a sus abuelos. Tenía seis años.", "dato"),
    ("Caravaggio y el perdón", "Murió en 1610, en el exilio, esperando el perdón papal.", "dato"),
    ("Caravaggio en el Antepurgatorio", "Junto a los muertos violentos que se arrepintieron (Purg. V).", "tesis nuestra"),
    ("El niño del Proemio", "Fue en Milán y dos siglos después de 1348: no en Florencia.", "licencia"),
    ("El Maestro cierra la fila", "El diseño lo quería primero; aquí sale el último para que protegerlo sea posible.", "licencia"),
    ("Mezcla de épocas", "1300, 1348, s. XV, 1571–1610: el más allá dantesco está fuera del tiempo.", "licencia"),
    ("Las bolge de Malebolge", "Los falsos consejeros son la 8.ª bolgia: aquí, el nivel 29.", "dato"),
    ("Lucifer y el centro de la Tierra", "Dante y Virgilio bajan por el pelo de Lucifer y, al pasar el centro, se dan la vuelta (Inf. XXXIV).", "dato"),
    ("Anteo", "El gigante, sin cadenas, baja a los dos poetas al fondo del pozo (Inf. XXXI).", "dato"),
    ("La lluvia de fuego", "«Sovra tutto 'l sabbion, d'un cader lento, / piovean di foco dilatate falde» (Inf. XIV).", "dato"),
    ("La cúpula como paraguas", "Brunelleschi no protegió a nadie del fuego: usamos su doble casco como cobijo.", "licencia"),
    ("Gravedad hacia la luz", "En el Paraíso no hay suelo: la Compagnia cae hacia arriba. Es nuestra lectura de Par. I.", "tesis nuestra"),
    ("Las siete P", "El Ángel graba siete P en la frente de Dante; cada cornisa borra una (Purg. IX).", "dato"),
    ("Las voces", "Síntesis por formantes que pronuncia el italiano moderno de cada subtítulo, no el del Trecento.", "licencia"),
    ("La barca de Flegias", "Flegias lleva a Dante y Virgilio por la Estigia hasta Dite (Inf. VIII).", "dato"),
    ("Las tres fieras", "La lonza, el león y la loba cierran el camino; Virgilio propone «altro viaggio» (Inf. I).", "dato"),
    ("El rodeo de Caronte", "No hay pasarela en el Aqueronte de Dante: es la alternativa del diseño al óbolo.", "licencia"),
    ("DILIGITE IUSTITIAM", "Las almas de Júpiter escriben con luces «Diligite iustitiam qui iudicatis terram» (Par. XVIII).", "dato"),
    ("Hipócritas", "Capas doradas por fuera y de plomo por dentro (Inf. XXIII).", "dato"),
    ("El Medico de la peste", "La máscara de pico es del siglo XVII; en 1348 los médicos no la llevaban. Ni curaban así.", "licencia"),
    ("Cien almas", "Cada nivel suelta cien disciplinati: la procesión entera.", "licencia"),
]

BRIGATA = {
    "Pampinea": "la sensata",
    "Filomena": "la piadosa",
    "Neifile": "la ingenua",
    "Filostrato": "el melancólico",
    "Fiammetta": "la apasionada",
    "Elissa": "la aguda",
    "Dioneo": "el gamberro",
    "Lauretta": "la burlona",
    "Emilia": "la soñadora",
    "Panfilo": "el magnánimo",
}


def brigata_lines(gi: int, camp: Campaign, pct: float | None) -> list[tuple[str, str]]:
    names = list(BRIGATA)
    king = GIORNATE[gi][0]
    p = camp.peso
    lines = [(king, f"Hoy reino yo. El tema: «{GIORNATE[gi][1].lower()}».")]
    if pct is None:
        lines.append(("Pampinea", "Salgamos de Florencia mientras podamos. Contaremos historias y no azotes."))
    elif pct >= 70:
        lines.append(("Filomena", f"Han llegado casi todos: {pct:.0f} de cada cien. Eso también es un milagro."))
    elif pct >= 40:
        lines.append(("Filostrato", f"Un {pct:.0f} %… Los que faltan no vuelven en ninguna novela."))
    else:
        lines.append(("Elissa", f"Un {pct:.0f} %. La procesión mata más que la peste, y lo hace cantando."))
    if p == 0:
        lines.append(("Emilia", "No llevan nada encima. Así se sube."))
    elif p < 15:
        lines.append(("Neifile", f"Pesan {p}. Poco. ¿O no?"))
    else:
        lines.append(("Dioneo", f"¡{p} de Peso! Ni Pluto arrastra tanto. Ya pagarán en las cornisas."))
    if camp.congiura:
        lines.append(("Lauretta", f"{camp.congiura} traición(es) en el historial. El Cocito tiene buena memoria."))
    if not camp.maestro:
        lines.append(("Panfilo", "Ya no tienen Maestro. Quizá por fin tengan camino."))
    lines.append((names[(gi + 6) % 10], "Y ahora, la novela de hoy. Pero antes, ellos."))
    return lines


ENDINGS = {
    "rosa": ("I · La Rosa Cándida",
             ["Queda una sola acción posible, y la Compagnia la hace: suelta el lirio.",
              "Sin escudo, sin Maestro y sin látigo, entran en la Rosa.",
              "l'amor che move il sole e l'altre stelle."]),
    "limbo": ("II · Il Limbo",
              ["Llegan al Empíreo, pero no pueden mirar.",
               "Los supervivientes vuelven al castillo de los sabios, sin culpa ni gracia.",
               "No es castigo. Es la nostalgia de algo que se vio de lejos."]),
    "giorni": ("III · I Trentatré Giorni e Mezzo",
               ["El Maestro Lapo cruza solo la última puerta y anuncia que la penitencia se ha cumplido.",
                "Detrás de él no hay nadie. La puerta da a Florencia, 1348. La peste ha vuelto.",
                "La procesión vuelve a empezar. Dies irae, dies illa."]),
}

SAVONAROLA = [
    "¡Arrojad al fuego los espejos, los naipes, los afeites!",
    "Florencia, haz penitencia mientras aún arde la hoguera.",
    "Los libros vanos, al fuego; las almas, al cielo.",
    "No es la llama la que quema: es la vanidad que lleváis encima.",
]

MOD_TEXT = {
    "wind": "La bufera: el viento arrastra a quien cae o planea.",
    "night": "De noche no se sube (Purg. VII): al caer el sol, la Compagnia se detiene.",
    "dark": "Ojos cosidos con alambre: solo se ve alrededor de cada alma.",
    "smoke": "Humo negro: solo el Lume de Caravaggio, Botticelli o Dioneo lo apartan.",
    "fast": "Acedia: corren sin descanso y no pueden pararse (sin Flagellante).",
    "return": "Aquí las palle pueden devolverse: Mayús + tecla de la palla, −3 de Peso.",
    "backwards": "Los adivinos caminan mirando atrás.",
    "slowskills": "Capas de plomo: los oficios van a mitad de velocidad.",
    "moria2": "Falsarios: la Moria contagia al doble.",
    "nodeath": "Limbo: aquí nadie muere.",
    "stones": "Soberbios: el Peso se vuelve piedra y frena la marcha.",
    "silence": "Saturno: silencio total.",
    "paradiso": "En el Paraíso el Flagellante ya no bloquea: solo se queda inmóvil.",
    "firerain": "Lluvia de fuego sobre el arenal.",
    "trees": "Árboles con fruta inalcanzable: quien pasa se queda mirando.",
    "lux": "Gravedad hacia la luz: aquí se cae hacia arriba.",
    "blink": "Plataformas que aparecen y desaparecen, como las promesas.",
    "ghost": "Cornisas ocultas: solo el Lume, Botticelli o Dioneo las hacen aparecer.",
    "venus": "Venus: el alma que camina sola va más despacio; la horda tiende a agruparse.",
    "banner": "Los ignavos corren tras un estandarte. La Compagnia lo sigue si no la paras.",
    "ice": "El hielo del Cocito: no hay manera de pararse del todo.",
    "suicidi": "Bosque de los suicidas: cada excavación sangra (+1 de Peso).",
}

# Subtítulos: cada plantilla en español → (inglés, italiano moderno). La voz recita el italiano.
TR: dict[str, tuple[str, str]] = {
    "Primum Mobile: las palle rojas se disuelven en la luz. Solo queda el lirio.":
        ("Primum Mobile: the red palle dissolve into light. Only the lily remains.",
         "Primo Mobile: le palle rosse si sciolgono nella luce. Resta solo il giglio."),
    "El Cocito cobra la traición: {n} alma(s) quedan presas en el hielo de la Antenora.":
        ("Cocytus collects for treason: {n} soul(s) stay trapped in the ice of Antenora.",
         "Il Cocito riscuote il tradimento: {n} anime restano prigioniere nel ghiaccio dell'Antenora."),
    "Aviñón, 20 de octubre de 1349: la bula de Clemente VI condena a los flagelantes.":
        ("Avignon, 20 October 1349: the bull of Clement VI condemns the flagellants.",
         "Avignone, venti ottobre 1349: la bolla di Clemente sesto condanna i flagellanti."),
    "Trepa por su pelo. Al otro lado del centro de la Tierra están las estrellas.":
        ("Climb down his hair. Beyond the centre of the Earth are the stars.",
         "Scendi per il suo pelo. Oltre il centro della Terra ci sono le stelle."),
    "Aquí no se cae hacia abajo: se cae hacia la luz. Mira arriba.":
        ("Here you do not fall down: you fall towards the light. Look up.",
         "Qui non si cade in basso: si cade verso la luce. Guarda in alto."),
    "El Ángel graba siete P en cada frente. Cada cornisa borrará una.":
        ("The Angel carves seven P on every brow. Each terrace will erase one.",
         "L'angelo incide sette P su ogni fronte. Ogni cornice ne cancellerà una."),
    "Virgilio se ha ido. Llega Beatrice, velada, entre flores.":
        ("Virgil is gone. Beatrice arrives, veiled, among flowers.",
         "Virgilio se n'è andato. Arriva Beatrice, velata, tra i fiori."),
    "Cada rama que se rompe aquí sangra. Excavar cuesta Peso.":
        ("Every branch broken here bleeds. Digging costs Weight.",
         "Ogni ramo spezzato qui sanguina. Scavare costa Peso."),
    "Privilegio di Dioneo: quince segundos sin la regla de este lugar.":
        ("Dioneo's privilege: fifteen seconds free of this place's rule.",
         "Privilegio di Dioneo: quindici secondi senza la regola di questo luogo."),
    "El Flagellante deja el látigo y sigue a los demás.":
        ("The Flagellant lays down the whip and follows the others.",
         "Il flagellante posa la frusta e segue gli altri."),
    "«Perché mi schiante?» (Inf. XIII). El bosque sangra: +1 de Peso.":
        ("«Perché mi schiante?» (Inf. XIII). The wood bleeds: +1 Weight.",
         "«Perché mi schiante?» Il bosco sanguina: più uno di Peso."),
    "La gracia no se compra. El Ángel no se mueve; tu Peso, sí.":
        ("Grace cannot be bought. The Angel does not move; your Weight does.",
         "La grazia non si compra. L'angelo non si muove; il tuo Peso sì."),
    "La naranja amarga rueda. Las almas la siguen.":
        ("The bitter orange rolls. The souls follow it.",
         "L'arancia amara rotola. Le anime la seguono."),
    "Cosme y Damián: {n} curados. Quince segundos de inmunidad.":
        ("Cosmas and Damian: {n} healed. Fifteen seconds of immunity.",
         "Cosma e Damiano: {n} guariti. Quindici secondi di immunità."),
    "Brunelleschi: doble casco, sin cimbra. Bajo la cúpula no llueve fuego.":
        ("Brunelleschi: double shell, no centring. Under the dome no fire falls.",
         "Brunelleschi: doppia calotta, senza centina. Sotto la cupola non piove fuoco."),
    "Brunelleschi: doble casco, sin cimbra. Un puente donde no lo había.":
        ("Brunelleschi: double shell, no centring. A bridge where there was none.",
         "Brunelleschi: doppia calotta, senza centina. Un ponte dove non c'era."),
    "Botticelli dibuja la Mappa dell'Inferno: todo queda a la vista.":
        ("Botticelli draws the Map of Hell: everything is laid bare.",
         "Botticelli disegna la Mappa dell'Inferno: tutto è svelato."),
    "Caravaggio pinta: un haz oblicuo elige a quien toca. Dejan de azotarse.":
        ("Caravaggio paints: a slanting beam chooses whom it touches. They stop scourging themselves.",
         "Caravaggio dipinge: un fascio obliquo sceglie chi tocca. Smettono di flagellarsi."),
    "El escudo de Lorenzo cae girando hasta perderse. Ya no hay nada que llevar.":
        ("Lorenzo's shield falls spinning until it is lost. There is nothing left to carry.",
         "Lo stemma di Lorenzo cade girando fino a perdersi. Non c'è più niente da portare."),
    "Dos almas cambian de lugar. Alguien, en algún sitio, lo cobrará.":
        ("Two souls swap places. Someone, somewhere, will collect.",
         "Due anime si scambiano di posto. Qualcuno, da qualche parte, presenterà il conto."),
    "Adhaesit pavimento anima mea. Una palla menos, tres de Peso menos.":
        ("Adhaesit pavimento anima mea. One palla less, three Weight less.",
         "Adhaesit pavimento anima mea. Una palla in meno, tre di Peso in meno."),
    "El óbolo cae en la mano del guardián. Pasad.":
        ("The obol drops into the guardian's hand. Pass.",
         "L'obolo cade nella mano del guardiano. Passate."),
    "{name} se arroja sobre la naranja. El paso queda libre.":
        ("{name} pounces on the orange. The way is clear.",
         "{name} si getta sull'arancia. Il passo è libero."),
    "26 de abril de 1478. {name} se vuelve contra los suyos. Dante lo anota.":
        ("26 April 1478. {name} turns on its own. Dante takes note.",
         "Ventisei aprile 1478. {name} si rivolta contro i suoi. Dante prende nota."),
    "Catón ve el junco ceñido: «Va dunque, e fa che tu costui ricinghe / d'un giunco schietto» (Purg. I).":
        ("Cato sees the girded reed: «Va dunque, e fa che tu costui ricinghe / d'un giunco schietto» (Purg. I).",
         "Catone vede il giunco: «Va dunque, e fa che tu costui ricinghe d'un giunco schietto»."),
    "Llega el messo del cielo: la puerta de Dite se abre con una varita.":
        ("The heavenly messenger arrives: the gate of Dis opens at a touch of his wand.",
         "Arriva il messo del cielo: la porta di Dite si apre con una verghetta."),
    "{name}: «Pasad». La espera era la prueba.":
        ("{name}: «Pass». The waiting was the test.",
         "{name}: «Passate». L'attesa era la prova."),
    "Il Maestro Lapo cierra la procesión, látigo en mano.":
        ("Master Lapo closes the procession, whip in hand.",
         "Il Maestro Lapo chiude la processione, frusta in mano."),
    "El Maestro cruza la puerta. «Ya os lo dije: el látigo salva.»":
        ("The Master crosses the gate. «I told you so: the whip saves.»",
         "Il Maestro varca la porta. «Ve l'avevo detto: la frusta salva.»"),
    "El Maestro ha llegado: el resto lo sigue con más ritmo.":
        ("The Master has arrived: the rest follow him at a quicker pace.",
         "Il Maestro è arrivato: gli altri lo seguono con passo più svelto."),
    "Ha caído el Maestro. La Compagnia, sin pastor, corre en pánico.":
        ("The Master has fallen. The Compagnia, shepherdless, runs in panic.",
         "Il Maestro è caduto. La Compagnia, senza pastore, corre nel panico."),
    "Filostrato suspira: los amantes no se separan.":
        ("Filostrato sighs: lovers are not parted.",
         "Filostrato sospira: gli amanti non si separano."),
    "Filomena: «infortunio con final feliz». Un alma vuelve a la fila.":
        ("Filomena: «misfortune with a happy ending». A soul rejoins the line.",
         "Filomena: «sventura a lieto fine». Un'anima torna nella fila."),
    "«Attienti ben, ché per cotali scale… conviensi dipartir da tanto male.» Ahora el suelo es el techo.":
        ("«Attienti ben, ché per cotali scale… conviensi dipartir da tanto male.» Now the floor is the ceiling.",
         "«Attienti ben, ché per cotali scale, conviensi dipartir da tanto male.» Ora il pavimento è il soffitto."),
    "Quien cruza el fuego entero sale limpio. Quien se para, arde.":
        ("Whoever crosses the whole fire comes out clean. Whoever stops, burns.",
         "Chi attraversa tutto il fuoco ne esce puro. Chi si ferma, brucia."),
    "Un niño huérfano de la peste se une a la fila. Se llama Michelangelo. (Licencia: Milán, 1577.)":
        ("A child orphaned by the plague joins the line. His name is Michelangelo. (Licence: Milan, 1577.)",
         "Un bambino orfano della peste si unisce alla fila. Si chiama Michelangelo."),
    "Una de las llamas habla con la voz del Maestro. Dice que él solo dio consejo.":
        ("One of the flames speaks with the Master's voice. It says it only gave advice.",
         "Una delle fiamme parla con la voce del Maestro. Dice di aver dato solo un consiglio."),
    "El estandarte se pierde en la niebla. Los ignavos se quedan sin nadie a quien seguir.":
        ("The banner is lost in the fog. The neutrals are left with no one to follow.",
         "L'insegna si perde nella nebbia. Gli ignavi restano senza nessuno da seguire."),
    "Neifile: «con ingenio». Un {skill} más escondido en el camino.":
        ("Neifile: «by wit». One more {skill} hidden along the way.",
         "Neifile: «con ingegno». Un {skill} in più nascosto sul cammino."),
    "Una pagina salvada de las llamas.":
        ("A page saved from the flames.", "Una pagina salvata dalle fiamme."),
    "Era falsa. Lauretta se ríe: «burla en general».":
        ("It was fake. Lauretta laughs: «tricks in general».", "Era falsa. Lauretta ride: «beffe in generale»."),
    "El escudo está lleno: la {palla} cede su hueco.":
        ("The shield is full: the {palla} gives up its place.", "Lo stemma è pieno: la {palla} cede il suo posto."),
    "«Palle, palle, palle!» La Compagnia corre al doble.":
        ("«Palle, palle, palle!» The Compagnia runs at double speed.", "«Palle, palle, palle!» La Compagnia corre al doppio."),
    "Con Peso no se asciende: cada alma que llega quema un punto ({n} restantes).":
        ("No one ascends with Weight: each soul that arrives burns one point ({n} left).",
         "Con il Peso non si sale: ogni anima che arriva ne brucia un punto, ne restano {n}."),
    "Un bezante compra un segundo intento de la cornisa: más días, +2 de Peso.":
        ("A bezant buys a second attempt at the terrace: more days, +2 Weight.",
         "Un bisante compra un secondo tentativo della cornice: più giorni, più due di Peso."),
    "Un ladrón se vuelve serpiente (Inf. XXV).":
        ("A thief turns into a serpent (Inf. XXV).", "Un ladro diventa serpente."),
    "La lonza": ("The leopard", "La lonza"),
    "«...una lupa, che di tutte brame / sembiava carca». Distráela.":
        ("«...una lupa, che di tutte brame / sembiava carca». Distract her.",
         "«Una lupa, che di tutte brame sembiava carca». Distraila."),
    "«…una lonza leggera e presta molto». Por aquí no se pasa.":
        ("«…una lonza leggera e presta molto». No way through here.",
         "«Una lonza leggera e presta molto». Di qui non si passa."),
    "«…con la test'alta e con rabbiosa fame». Tampoco por aquí: «a te convien tenere altro viaggio».":
        ("«…con la test'alta e con rabbiosa fame». Not here either: «a te convien tenere altro viaggio».",
         "«Con la test'alta e con rabbiosa fame». Nemmeno di qui: «a te convien tenere altro viaggio»."),
    "«Caron dimonio, con occhi di bragia». Paga el óbolo.":
        ("«Caron dimonio, con occhi di bragia». Pay the obol.", "«Caron dimonio, con occhi di bragia». Paga l'obolo."),
    "Minos juzga y ciñe la cola. Se deja convencer.":
        ("Minos judges and wraps his tail. He can be persuaded.", "Minosse giudica e cinge la coda. Si lascia convincere."),
    "Tres bocas. Virgilio le echó tierra; tú, una naranja.":
        ("Three mouths. Virgil threw earth; you, an orange.", "Tre bocche. Virgilio gli gettò la terra; tu, un'arancia."),
    "«Pape Satàn, pape Satàn aleppe!» Habla en monedas.":
        ("«Pape Satàn, pape Satàn aleppe!» He speaks in coins.", "«Pape Satàn, pape Satàn aleppe!» Parla in monete."),
    "El barquero de la Estigia cobra el pasaje.":
        ("The ferryman of the Styx charges the fare.", "Il nocchiero dello Stige si fa pagare il passaggio."),
    "Las Furias cierran Dite. Solo un mensajero del cielo abre.":
        ("The Furies bar Dis. Only a messenger from heaven opens it.", "Le Furie chiudono Dite. Solo un messo del cielo apre."),
    "Quirón y sus arqueros. Un señuelo los aparta.":
        ("Chiron and his archers. A lure draws them away.", "Chirone e i suoi arcieri. Un'esca li allontana."),
    "Las harpías anidan en el bosque de los suicidas.":
        ("The Harpies nest in the wood of the suicides.", "Le Arpie fanno il nido nel bosco dei suicidi."),
    "Catón exige el junco: humildad antes de subir.":
        ("Cato demands the reed: humility before climbing.", "Catone esige il giunco: umiltà prima di salire."),
    "Los excomulgados esperan. Esperar también es trabajo.":
        ("The excommunicated wait. Waiting is work too.", "Gli scomunicati aspettano. Anche aspettare è lavoro."),
    "El ángel abre a quien espera. La gracia no se compra.":
        ("The angel opens to those who wait. Grace cannot be bought.", "L'angelo apre a chi aspetta. La grazia non si compra."),
    "Examen de fe. Espera la pregunta.": ("Examination on faith. Await the question.", "Esame di fede. Attendi la domanda."),
    "Examen de esperanza.": ("Examination on hope.", "Esame di speranza."),
    "Examen de caridad.": ("Examination on charity.", "Esame di carità."),
    "Anteo, sin cadenas: «mettine giù». Llega a su mano y te baja al fondo.":
        ("Antaeus, unchained: «mettine giù». Reach his hand and he lowers you to the bottom.",
         "Anteo, senza catene: «mettine giù». Raggiungi la sua mano e ti porta sul fondo."),
    "¡Arrojad al fuego los espejos, los naipes, los afeites!":
        ("Throw the mirrors, the cards, the cosmetics into the fire!", "Gettate nel fuoco gli specchi, le carte, i belletti!"),
    "Florencia, haz penitencia mientras aún arde la hoguera.":
        ("Florence, do penance while the pyre still burns.", "Firenze, fa' penitenza finché il rogo arde ancora."),
    "Los libros vanos, al fuego; las almas, al cielo.":
        ("Vain books to the fire; souls to heaven.", "I libri vani al fuoco; le anime al cielo."),
    "No es la llama la que quema: es la vanidad que lleváis encima.":
        ("It is not the flame that burns: it is the vanity you carry.", "Non è la fiamma che brucia: è la vanità che portate addosso."),
    "«Quelli è Omero poeta sovrano» (Inf. IV, 88).": ("«Quelli è Omero poeta sovrano» (Inf. IV, 88).", "«Quelli è Omero poeta sovrano»."),
    "«…il maestro di color che sanno» (Inf. IV, 131).": ("«…il maestro di color che sanno» (Inf. IV, 131).", "«Il maestro di color che sanno»."),
    "«Averoìs, che 'l gran comento feo» (Inf. IV, 144).": ("«Averoìs, che 'l gran comento feo» (Inf. IV, 144).", "«Averoìs, che 'l gran comento feo»."),
    "Dies irae, dies illa…": ("Dies irae, dies illa…", "Dies irae, dies illa."),
    "«Libero, dritto e sano è tuo arbitrio… per ch'io te sovra te corono e mitrio.» (Purg. XXVII)":
        ("«Libero, dritto e sano è tuo arbitrio… per ch'io te sovra te corono e mitrio.» (Purg. XXVII)",
         "«Libero, dritto e sano è tuo arbitrio, per ch'io te sovra te corono e mitrio.»"),
}
LANGS = ("es", "en", "it")
LANG_NAMES = {"es": "español", "en": "English", "it": "italiano"}


def tr(text: str, lang: str, **kw) -> str:
    """Traduce una plantilla de mensaje al idioma de los subtítulos (o de la voz)."""
    if lang != "es" and text in TR:
        text = TR[text][LANGS.index(lang) - 1]
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):
        return text


# ═══════════════════════════════════════════════════════════════════════════
# 9. INTERFAZ — predela, escudo, mapa de la Commedia, villa, finales
# ═══════════════════════════════════════════════════════════════════════════

SAVE_FILE = Path.home() / ".pydanteshell.json"
GOLD = (232, 190, 92)
GOLD_D = (150, 110, 46)
INK = (24, 16, 14)
PARCH = (236, 224, 196)
UI_FG = (240, 232, 214)
UI_DIM = (150, 136, 120)
UI_ACC = (255, 210, 110)
UI_BAD = (230, 80, 64)
UI_OK = (150, 220, 140)
CANTICA_COL = {"proemio": (200, 150, 110), "inferno": (230, 90, 50), "purgatorio": (130, 180, 230), "paradiso": (255, 230, 150)}
SKILL_X0, SKILL_W = 4, 37
BTN_RR_DN, BTN_RR_UP, BTN_PAUSE, BTN_FF, BTN_NUKE = range(5)
BTN_X = [344, 366, 390, 412, 434]
MINI = pygame.Rect(478, VIEW_H + 6, 158, 40)
SLOT_KEYS = [pygame.K_q, pygame.K_w, pygame.K_e, pygame.K_r, pygame.K_t, pygame.K_y, pygame.K_u, pygame.K_i]


class Save:
    def __init__(self) -> None:
        self.data = {"unlocked": 0, "levels": {}, "pagine": [], "seen": [], "dioneo": {}}
        try:
            d = json.loads(SAVE_FILE.read_text())
            if isinstance(d, dict):
                self.data.update(d)
        except (OSError, ValueError):
            pass

    def write(self) -> None:
        try:
            SAVE_FILE.write_text(json.dumps(self.data))
        except OSError:
            pass

    @property
    def unlocked(self) -> int:
        return int(self.data.get("unlocked", 0))

    @property
    def opts(self) -> dict:
        o = self.data.setdefault("opts", {})
        for k, v in {"music": True, "voices": True, "quality": 2, "volume": 8, "fullscreen": False, "lang": "es",
                     "infinite": True, "motion": True, "markers": True, "contrast": False, "shadows": True}.items():
            o.setdefault(k, v)
        return o

    def camp_for(self, i: int) -> Campaign:
        lv = self.data["levels"]
        for j in range(i - 1, -1, -1):
            if str(j) in lv:
                c = Campaign.from_json(lv[str(j)].get("camp"))
                break
        else:
            c = Campaign()
        c.dioneo = not self.data["dioneo"].get(str(giornata_of(i)), False)
        return c

    def best(self, i: int) -> dict:
        return self.data.setdefault("best", {}).get(str(i), {})

    def record_best(self, i: int, w: World) -> tuple[int, bool]:
        """Guarda el mejor resultado y devuelve (estrellas, ¿récord nuevo?)."""
        stars = level_stars(w.saved, w.level.to_save, w.total)
        b = self.data.setdefault("best", {})
        old = b.get(str(i), {})
        new = w.saved > old.get("saved", -1) or (w.saved == old.get("saved") and w.tick_count < old.get("ticks", 10**9))
        if new:
            b[str(i)] = {"saved": w.saved, "ticks": w.tick_count, "stars": max(stars, old.get("stars", 0))}
        self.write()
        return stars, new and bool(old)

    def record(self, i: int, w: World, camp: Campaign) -> None:
        self.data["levels"][str(i)] = {"saved": w.saved, "total": w.total, "camp": camp.to_json()}
        if w.pagina and i not in self.data["pagine"]:
            self.data["pagine"].append(i)
        if w.dioneo_used:
            self.data["dioneo"][str(giornata_of(i))] = True
        self.data["unlocked"] = max(self.unlocked, min(N_LEVELS - 1, i + 1))
        self.write()

    def pct(self) -> float | None:
        lv = self.data["levels"]
        if not lv:
            return None
        s = sum(v["saved"] for v in lv.values())
        t = sum(v["total"] for v in lv.values())
        return 100 * s / max(1, t)


def camp_after(w: World) -> Campaign:
    lv = w.level
    peso = w.peso
    notes = w.notes
    if lv.special == "leteo" and peso < 15:
        if peso:
            notes.append(f"El Leteo borra la memoria del pecado: −{peso} de Peso")
        peso = 0
    if "magnanimo" in w.mods:
        extra = max(0, w.saved - lv.to_save)
        if extra and peso:
            notes.append(f"Magnanimidad de Panfilo: −{min(peso, extra)} de Peso")
        peso -= extra
    if "giglio" in w.shield:
        peso = min(peso, 30)
    maestro = w.maestro_saved if w.maestro_due else False
    return Campaign(max(0, peso), list(w.shield), maestro, w.congiura, w.camp_in.dioneo and not w.dioneo_used)


@dataclass
class PlayState:
    idx: int
    world: World
    renderer: Renderer
    camp: Campaign
    cam: int = 0
    skill: Skill = Skill.PELLEGRINO
    paused: bool = False
    ff: bool = False
    acc: float = 0.0
    log: list[list] = field(default_factory=list)
    pilot: Autopilot | Replay | None = None
    demo: bool = False
    nuke_hold: int = 0
    nuke_armed: int = 0
    msg_seen: int = 0
    speed: int = 4
    snaps: deque = field(default_factory=lambda: deque(maxlen=45))
    rewinds: int = 0
    rr_hold: int = 0
    hold_t: int = 0
    end_wait: float = 0.0
    aborted: bool = False
    armed: int | None = None
    swap_a: int | None = None
    artist: str | None = None
    smooth_cam: float = 0.0


def draw_skill_icon(surf: pygame.Surface, skill: Skill, cx: int, cy: int, s: float, col=(240, 232, 214)) -> None:
    """Iconos de la predela, dibujados a resolución de pantalla."""
    def P(x, y):
        return int(cx + x * s), int(cy + y * s)

    lw = max(1, int(s))
    match skill:
        case Skill.PELLEGRINO:  # bordón y venera
            pygame.draw.line(surf, col, P(-3, 8), P(3, -9), lw * 2)
            pygame.draw.circle(surf, col, P(4, -9), int(2 * s))
            pygame.draw.arc(surf, (240, 200, 160), (*P(-8, -2), int(8 * s), int(8 * s)), 0, math.pi, lw)
            for k in range(-2, 3):
                pygame.draw.line(surf, (240, 200, 160), P(-4, 2), P(-4 + k * 1.6, -2), lw)
        case Skill.GERIONE:  # alas en espiral
            for sgn in (-1, 1):
                pts = [P(sgn * (1 + t * 0.9), -2 - math.sin(t * 0.6) * 5) for t in range(9)]
                pygame.draw.lines(surf, col, False, pts, lw * 2)
            pygame.draw.circle(surf, col, P(0, 4), int(2.4 * s))
        case Skill.BUBBONE:  # el bubón con mecha
            pygame.draw.circle(surf, (200, 50, 40), P(0, 2), int(6 * s))
            pygame.draw.circle(surf, (120, 160, 40), P(-2, 0), int(2 * s))
            pygame.draw.line(surf, col, P(3, -3), P(6, -8), lw)
            pygame.draw.circle(surf, (255, 200, 60), P(6, -9), int(1.5 * s))
        case Skill.FLAGELLANTE:  # látigo de tres colas
            pygame.draw.line(surf, (160, 110, 60), P(-6, 7), P(-1, -1), lw * 2)
            for k in (-1, 0, 1):
                pts = [P(-1 + t, -1 - t * 0.9 + math.sin(t + k) * 1.5 + k * 1.5) for t in range(7)]
                pygame.draw.lines(surf, (220, 40, 40), False, pts, lw)
        case Skill.CAPOMASTRO:  # escalera y cúpula
            for k in range(4):
                pygame.draw.rect(surf, (230, 180, 120), (*P(-7 + k * 3, 6 - k * 3), int(4 * s), int(2 * s)))
            pygame.draw.arc(surf, col, (*P(-2, -9), int(10 * s), int(10 * s)), 0, math.pi, lw * 2)
        case Skill.PIAGNONE:  # puño
            pygame.draw.rect(surf, (226, 176, 134), (*P(-5, -4), int(9 * s), int(8 * s)), border_radius=int(2 * s))
            for k in range(3):
                pygame.draw.line(surf, INK, P(-3 + k * 2.5, -4), P(-3 + k * 2.5, -1), lw)
            pygame.draw.line(surf, col, P(5, -2), P(9, -2), lw)
            pygame.draw.line(surf, col, P(5, 1), P(10, 1), lw)
        case Skill.MINATORE:  # pico
            pygame.draw.line(surf, (160, 110, 60), P(-6, 7), P(4, -5), lw * 2)
            pygame.draw.arc(surf, col, (*P(-2, -10), int(12 * s), int(10 * s)), 0.3, 2.8, lw * 2)
        case Skill.BECCHINO:  # pala
            pygame.draw.line(surf, (160, 110, 60), P(0, -9), P(0, 2), lw * 2)
            pygame.draw.polygon(surf, col, [P(-4, 2), P(4, 2), P(3, 8), P(0, 10), P(-3, 8)])
        case Skill.MEDICO:  # redoma de triaca con cruz verde
            pygame.draw.polygon(surf, col, [P(-2, -9), P(2, -9), P(2, -4), P(6, 4), P(4, 8), P(-4, 8), P(-6, 4), P(-2, -4)], lw)
            pygame.draw.polygon(surf, (80, 190, 110), [P(-5, 4), P(5, 4), P(4, 7), P(-4, 7)])
            pygame.draw.line(surf, (120, 230, 140), P(0, -2), P(0, 3), lw)
            pygame.draw.line(surf, (120, 230, 140), P(-2, 0), P(2, 0), lw)


class App:
    def __init__(self, args: argparse.Namespace):
        pygame.init()
        info = pygame.display.Info()
        s = max(1, args.scale) if args.scale else 0
        if info.current_w > 0 and info.current_h > 0:
            fit = max(1, min(info.current_w // LW, (info.current_h - 60) // LH))
            s = fit if not s else min(s, fit)
        self.s = max(1, s or 2)
        self.save = Save()
        self.fullscreen = args.fullscreen or self.save.opts["fullscreen"]
        self._make_window()
        pygame.display.set_caption(TITLE)
        self.clock = pygame.time.Clock()
        self.view = pygame.Surface((VIEW_W, VIEW_H))
        self._fonts()
        self.sprites = Sprites()
        self.sfx = Sfx(not args.mute)
        o = self.save.opts
        self.sfx.music_on = self.sfx.music_on and o["music"]
        self.sfx.voices = o["voices"]
        self.sfx.set_volume(o["volume"] / 10)
        self.quality = 0 if args.lowfx else int(o["quality"])
        self.lang = o["lang"] if o["lang"] in LANGS else "es"
        self.infinite = True  # los oficios no se agotan nunca
        self.opt_sel = 0
        # mando: cursor virtual y ejes
        self.pads: list = []
        self.pad_active = False
        self.vcur = [VIEW_W / 2, VIEW_H / 2]
        self.pad_axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "lt": 0.0, "rt": 0.0}
        self.pad_held: set[int] = set()
        self.pad_combo = 0
        try:
            from pygame._sdl2 import controller as sdlc

            sdlc.init()
            self._sdlc = sdlc
            self.pads = [sdlc.Controller(i) for i in range(sdlc.get_count()) if sdlc.is_controller(i)]
        except (ImportError, pygame.error, AttributeError):
            self._sdlc = None
        self.unlocked = N_LEVELS - 1 if args.all else min(self.save.unlocked, N_LEVELS - 1)
        self.sel = self.unlocked
        self.mode = "title"
        self.menu_sel = 0
        self.frame = 0
        self.p: PlayState | None = None
        self.preview: tuple[int, World, Renderer] | None = None
        self.result: dict | None = None
        self.giornata: dict | None = None
        self.ending: dict | None = None
        self.scroll = 0
        self.title_scene = TitleScene(self.sprites)
        self.args = args
        self.hide_hud = False
        self.toasts: list[list] = []
        self.endless: dict | None = None
        if args.replay:
            data = json.loads(Path(args.replay).read_text())
            self.start_play(int(data["level"]), pilot=Replay(data["commands"]), demo=True)
        elif args.demo is not None:
            self.start_play(args.demo, pilot=Autopilot(get_level(args.demo).solution), demo=True)
        elif args.level is not None:
            self.sel = args.level
            self.open_level(args.level)

    def _make_window(self) -> None:
        flags = pygame.SCALED | pygame.FULLSCREEN if self.fullscreen else 0
        if self.fullscreen:
            self.screen = pygame.display.set_mode((LW * self.s, LH * self.s), flags)
        else:
            self.screen = pygame.display.set_mode((LW * self.s, LH * self.s))

    def _fonts(self) -> None:
        s = self.s
        serif = None
        for name in ("ebgaramond", "garamond", "librebaskerville", "cormorantgaramond", "dejavuserif", "liberationserif", "freeserif"):
            path = pygame.font.match_font(name)
            if path:
                serif = path
                break
        bold = pygame.font.match_font("dejavuserif", bold=True) or serif

        def F(sz, b=False, it=False):
            f = pygame.font.Font(bold if b else serif, int(sz * s))
            f.set_italic(it)
            return f

        self.f_huge = F(30, True)
        self.f_title = F(20, True)
        self.f_big = F(12.5, True)
        self.f_med = F(9.5)
        self.f_it = F(9.5, it=True)
        self.f_small = F(7.5)
        self.f_tiny = F(6.5)
        self.f_micro = F(5.2)
        self.f_nano = F(4.4)

    # ── utilidades de dibujo ─────────────────────────────────────────────
    def R(self, x: float, y: float, w: float, h: float) -> pygame.Rect:
        s = self.s
        return pygame.Rect(int(x * s), int(y * s), int(w * s), int(h * s))

    def text(self, msg: str, font: pygame.font.Font, pos, color=UI_FG, center=False, right=False, shadow=True, alpha=255):
        img = font.render(msg, True, color)
        x, y = pos[0] * self.s, pos[1] * self.s
        if center:
            x -= img.get_width() / 2
        elif right:
            x -= img.get_width()
        if alpha < 255:
            img.set_alpha(alpha)
        if shadow:
            sh = font.render(msg, True, (0, 0, 0))
            sh.set_alpha(min(alpha, 170))
            self.screen.blit(sh, (x + self.s * 0.6, y + self.s * 0.6))
        self.screen.blit(img, (x, y))
        return img.get_width() / self.s

    def wrap(self, msg: str, font: pygame.font.Font, width: float) -> list[str]:
        words, lines, cur = msg.split(), [], ""
        for w_ in words:
            t = (cur + " " + w_).strip()
            if font.size(t)[0] / self.s > width and cur:
                lines.append(cur)
                cur = w_
            else:
                cur = t
        if cur:
            lines.append(cur)
        return lines

    def para(self, msg, font, x, y, width, color=UI_FG, center=False, lh=None) -> float:
        lh = lh or font.get_linesize() / self.s
        for k, line in enumerate(self.wrap(msg, font, width)):
            self.text(line, font, (x + (width / 2 if center else 0), y + k * lh), color, center=center)
        return y + len(self.wrap(msg, font, width)) * lh

    def panel(self, x, y, w, h, alpha=200, border=GOLD) -> None:
        r = self.R(x, y, w, h)
        surf = pygame.Surface(r.size, pygame.SRCALPHA)
        surf.fill((14, 10, 12, alpha))
        self.screen.blit(surf, r.topleft)
        pygame.draw.rect(self.screen, border, r, max(1, self.s // 2))
        pygame.draw.rect(self.screen, GOLD_D, r.inflate(-4 * self.s, -4 * self.s), 1)

    def blit_full(self) -> None:
        """Escena a sangre: la vista de 640×296 recortada para llenar 640×360."""
        h = LH * self.s
        w = int(VIEW_W * LH / VIEW_H * self.s)
        big = pygame.transform.smoothscale(self.view, (w, h)) if self.quality else pygame.transform.scale(self.view, (w, h))
        self.screen.blit(big, (-(w - LW * self.s) // 2, 0))

    def blit_view(self, shake: float = 0.0, oy: int = 0) -> None:
        dx, dy = 0, oy
        if shake > 0.4:
            dx = int(random.uniform(-shake, shake))
            dy = int(random.uniform(-shake, shake))
        big = pygame.transform.scale(self.view, (VIEW_W * self.s, VIEW_H * self.s))
        self.screen.blit(big, (dx * self.s, dy * self.s))

    # ── transiciones ─────────────────────────────────────────────────────
    def open_level(self, idx: int) -> None:
        lv = get_level(idx)
        gi = lv.giornata
        if idx >= 1 and gi not in self.save.data["seen"] and (idx - 1) % 10 == 0:
            self.save.data["seen"].append(gi)
            self.save.write()
            self.giornata = {"gi": gi, "next": idx, "t": 0}
            self.mode = "giornata"
            self.sfx.music("villa")
            return
        self.open_preview(idx)

    def open_preview(self, idx: int) -> None:
        camp = self.save.camp_for(idx)
        if idx >= N_LEVELS:
            camp = Campaign(maestro=False)
        w = World(get_level(idx), camp, infinite=self.infinite)
        self.preview = (idx, w, self.renderer(w))
        self.mode = "preview"
        self.sfx.music(get_level(idx).cantica if get_level(idx).cantica != "proemio" else "firenze")

    def renderer(self, w: World) -> Renderer:
        r = Renderer(w, self.sprites, self.quality)
        o = self.save.opts
        r.reduce_motion = not o["motion"]
        r.markers = o["markers"]
        r.contrast = o["contrast"]
        return r

    def start_play(self, idx: int, pilot=None, demo: bool = False) -> None:
        camp = self.save.camp_for(idx) if not demo and idx < N_LEVELS else Campaign(maestro=idx < N_LEVELS)
        if self.preview and self.preview[0] == idx and pilot is None:
            _, w, r = self.preview
        else:
            w = World(get_level(idx), camp, infinite=True)
            r = self.renderer(w)
        self.preview = None
        cam = w.entrances[0].x - VIEW_W // 2 if w.entrances else 0
        self.p = PlayState(idx, w, r, camp, cam=self._clamp_cam(w, cam), pilot=pilot, demo=demo)
        self.p.smooth_cam = self.p.cam
        self.p.skill = next((k for k in SKILLS if w.skills[k] > 0), Skill.PELLEGRINO)
        self.mode = "play"
        self.sfx.play("door")
        self.sfx.music(THEMES[w.level.theme].music if "silence" not in w.mods else None)

    def finish_play(self) -> None:
        p = self.p
        assert p is not None
        w = p.world
        ok = w.success and not p.aborted
        verse = None
        ending = None
        if ok and not p.demo and p.idx < N_LEVELS:
            camp = camp_after(w)
            self.save.record(p.idx, w, camp)
            if p.idx == 67:
                pct = self.save.pct() or 0
                w.notes.append(f"Eunoè, la memoria del bien: has salvado al {pct:.0f} % de las almas de la Commedia")
            self.unlocked = max(self.unlocked, min(N_LEVELS - 1, p.idx + 1))
            if w.pagina:
                verse = verse_of(p.idx)
            if p.idx == N_LEVELS - 1:
                ending = self.decide_ending(w, camp)
        stars, record = (0, False)
        if ok and not p.demo:
            stars, record = self.save.record_best(p.idx, w)
            if p.idx == DAILY_ID:
                self.save.data.setdefault("daily", {})[w.level.name] = max(w.saved, self.save.data.get("daily", {}).get(w.level.name, 0))
            if p.idx >= ENDLESS_ID and self.endless is not None:
                self.endless["n"] += 1
                best = max(self.save.data.get("endless_best", 0), self.endless["n"])
                self.save.data["endless_best"] = best
            self.save.write()
        if not p.demo:
            self.check_achievements(w, ok, ending)
        self.result = {"idx": p.idx, "saved": w.saved, "total": w.total, "need": w.level.to_save, "ok": ok, "stars": stars,
                       "record": record,
                       "log": p.log, "demo": p.demo, "saved_file": None, "notes": list(w.notes), "verse": verse,
                       "peso": w.peso, "peso0": p.camp.peso, "maestro": w.maestro_saved, "ending": ending, "t": 0}
        self.mode = "result"

    def decide_ending(self, w: World, camp: Campaign) -> str:
        pct = self.save.pct() or 0
        if pct < 40 or w.maestro_saved:
            return "giorni"
        if pct > 70 and camp.peso == 0 and "giglio" not in w.shield:
            return "rosa"
        return "limbo"

    @staticmethod
    def _clamp_cam(w: World, cam: float) -> int:
        return int(max(0, min(cam, w.terrain.w - VIEW_W)))

    # ── bucle ────────────────────────────────────────────────────────────
    def run(self) -> None:
        while True:
            dt = self.clock.tick(60)
            self.frame += 1
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return
                if ev.type in PAD_EVENTS:
                    for ev2 in self.pad_event(ev):
                        if getattr(self, f"on_{self.mode}")(ev2) == "quit":
                            return
                    continue
                if ev.type == pygame.MOUSEMOTION:
                    self.pad_active = False
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_m and self.mode != "play" or (
                        ev.type == pygame.KEYDOWN and ev.key == pygame.K_m and pygame.key.get_mods() & pygame.KMOD_CTRL):
                    self.sfx.toggle(self.sfx.current or "inferno")
                    continue
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F11:
                    self.fullscreen = not self.fullscreen
                    self._make_window()
                    continue
                if getattr(self, f"on_{self.mode}")(ev) == "quit":
                    return
            if self.mode == "play":
                self.update_play(dt)
            self.screen.fill((8, 6, 8))
            getattr(self, f"draw_{self.mode}")()
            if self.toasts:
                self.draw_toasts()
            pygame.display.flip()

    # ── título ───────────────────────────────────────────────────────────
    MENU = ["Comenzar el viaje", "La Commedia (mapa)", "Giudizio del giorno", "Infinito", "Pagine salvate", "Logros",
            "Códice histórico", "Opciones", "Salir"]

    def on_title(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                return "quit"
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.menu_sel = (self.menu_sel - 1) % len(self.MENU)
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.menu_sel = (self.menu_sel + 1) % len(self.MENU)
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                return self.menu_go()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            my = ev.pos[1] / self.s
            k = int((my - 170) // 18)
            if 0 <= k < len(self.MENU):
                self.menu_sel = k
                return self.menu_go()
        elif ev.type == pygame.MOUSEMOTION:
            my = ev.pos[1] / self.s
            k = int((my - 170) // 18)
            if 0 <= k < len(self.MENU):
                self.menu_sel = k
        return None

    def menu_go(self):
        self.sfx.play("assign")
        match self.menu_sel:
            case 0:
                self.sel = self.unlocked
                self.open_level(self.unlocked)
            case 1:
                self.mode = "map"
            case 2:
                self.start_daily()
            case 3:
                self.endless = {"n": 0, "seed": random.randrange(10**9)}
                self.next_endless()
            case 4:
                self.mode = "pagine"
            case 5:
                self.scroll = 0
                self.mode = "logros"
            case 6:
                self.scroll = 0
                self.mode = "codex"
            case 7:
                self.opt_sel = 0
                self.mode = "options"
            case 8:
                return "quit"
        return None

    # ── modos ────────────────────────────────────────────────────────────
    def start_daily(self) -> None:
        """Giudizio del giorno: un nivel nuevo cada día, el mismo para todos, con su récord."""
        today = datetime.date.today()
        name = f"Giudizio del {today.isoformat()}"
        make_variant(DAILY_ID, today.toordinal() * 7919, name)
        self.open_preview(DAILY_ID)

    def next_endless(self) -> None:
        """Infinito: niveles generados uno tras otro hasta que falle la Compagnia."""
        assert self.endless is not None
        n = self.endless["n"]
        lid = ENDLESS_ID + n
        CUSTOM.pop(lid - 1, None)
        make_variant(lid, self.endless["seed"] + n * 104729, f"Infinito · círculo {n + 1}")
        self.open_preview(lid)

    # ── logros ───────────────────────────────────────────────────────────
    def check_achievements(self, w: World, ok: bool, ending: str | None) -> None:
        got = self.save.data.setdefault("ach", [])
        best = self.save.data.get("best", {})
        conds = {
            "primo": ok and w.level.id == 0,
            "michelangelo": w.child_saved,
            "tutti": ok and w.saved >= w.total,
            "riveder": ok and w.level.id == 34,
            "leggero": ok and w.level.id == 67 and w.peso == 0,
            "palle": w.combo_hit,
            "medico": w.cured >= 30,
            "dioneo": w.dioneo_used,
            "dies": w.nuking,
            "maestro": w.maestro_saved,
            "pagine10": len(self.save.data["pagine"]) >= 10,
            "pagine101": len(self.save.data["pagine"]) >= N_LEVELS,
            "stelle": sum(1 for v in best.values() if v.get("stars") == 3) >= 10,
            "giudizio": ok and w.level.id == DAILY_ID,
            "infinito": bool(self.endless) and self.endless["n"] >= 5,
            "rosa": ending == "rosa", "limbo": ending == "limbo", "giorni": ending == "giorni",
        }
        for k, v in conds.items():
            if v and k not in got:
                got.append(k)
                self.toasts.append([ACHIEVEMENTS[k][0], 5 * 60])
                self.sfx.play("combo")
        self.save.write()

    def stars(self, x: float, y: float, n: int, r: float, total: int = 3) -> None:
        """Estrellas dibujadas (no todas las fuentes tienen ★)."""
        s = self.s
        for k in range(total):
            cx, cy = (x + k * r * 2.6) * s, y * s
            pts = []
            for j in range(10):
                rr = r * s if j % 2 == 0 else r * s * 0.45
                a = -math.pi / 2 + j * math.pi / 5
                pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
            if k < n:
                pygame.draw.polygon(self.screen, GOLD, pts)
            pygame.draw.polygon(self.screen, GOLD_D, pts, 1)

    def draw_toasts(self) -> None:
        y = LH - 92
        for t in self.toasts:
            t[1] -= 1
            a = min(255, t[1] * 6)
            self.panel(LW / 2 - 150, y, 300, 22, min(220, a))
            self.text(f"Logro: {t[0]}" if not t[0].startswith("foto") else t[0], self.f_med, (LW / 2, y + 5), GOLD, center=True, alpha=a)
            y -= 26
        self.toasts = [t for t in self.toasts if t[1] > 0]

    def on_logros(self, ev):
        if ev.type == pygame.KEYDOWN or (ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3)):
            self.mode = "title"
        return None

    def draw_logros(self) -> None:
        bg = cached_gradient(LW * self.s, LH * self.s, (30, 22, 18), (10, 6, 6))
        self.screen.blit(bg, (0, 0))
        got = set(self.save.data.get("ach", []))
        self.text(f"LOGROS — {len(got)} de {len(ACHIEVEMENTS)}", self.f_title, (LW / 2, 8), GOLD, center=True)
        best = self.save.data.get("best", {})
        stars = sum(v.get("stars", 0) for v in best.values())
        self.text(f"Estrellas: {stars} de {3 * N_LEVELS}  ·  Mejor racha en Infinito: {self.save.data.get('endless_best', 0)}",
                  self.f_small, (LW / 2, 34), UI_DIM, center=True)
        for k, (key, (name, desc)) in enumerate(ACHIEVEMENTS.items()):
            col, row = k % 2, k // 2
            x, y = 24 + col * 304, 52 + row * 32
            on = key in got
            self.panel(x, y, 292, 28, 200 if on else 120, GOLD if on else GOLD_D)
            if on:
                self.stars(x + 12, y + 8, 1, 4)
            self.text(name, self.f_med, (x + 20, y + 2), UI_ACC if on else UI_DIM)
            self.text(desc, self.f_tiny, (x + 8, y + 16), UI_FG if on else UI_DIM)
        self.text("Cualquier tecla: volver", self.f_tiny, (LW / 2, 348), UI_DIM, center=True)

    # ── opciones ─────────────────────────────────────────────────────────
    OPTS = ["music", "voices", "lang", "quality", "volume", "fullscreen", "motion", "markers", "contrast", "shadows", "back"]

    def on_options(self, ev):
        if ev.type != pygame.KEYDOWN and not (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1):
            return None
        o = self.save.opts
        key = getattr(ev, "key", pygame.K_RETURN)
        if ev.type == pygame.MOUSEBUTTONDOWN:
            k = int((ev.pos[1] / self.s - 92) // 20)
            if 0 <= k < len(self.OPTS):
                self.opt_sel = k
        if key == pygame.K_ESCAPE:
            self.mode = "title"
            return None
        if key in (pygame.K_UP, pygame.K_w):
            self.opt_sel = (self.opt_sel - 1) % len(self.OPTS)
            return None
        if key in (pygame.K_DOWN, pygame.K_s):
            self.opt_sel = (self.opt_sel + 1) % len(self.OPTS)
            return None
        item = self.OPTS[self.opt_sel]
        delta = -1 if key in (pygame.K_LEFT, pygame.K_a) else 1
        if key not in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d, pygame.K_RETURN, pygame.K_SPACE):
            return None
        match item:
            case "music":
                o["music"] = not o["music"]
                self.sfx.toggle(self.sfx.current or "inferno")
            case "voices":
                o["voices"] = self.sfx.voices = not o["voices"]
                self.sfx.speak("Virgilio", "Or va, ch'un sol volere è d'ambedue")
            case "lang":
                self.lang = LANGS[(LANGS.index(self.lang) + delta) % len(LANGS)]
                o["lang"] = self.lang
            case "quality":
                o["quality"] = self.quality = 0 if self.quality else 2
            case "motion" | "markers" | "contrast" | "shadows":
                o[item] = not o[item]
            case "volume":
                o["volume"] = max(0, min(10, o["volume"] + delta))
                self.sfx.set_volume(o["volume"] / 10)
                self.sfx.play("assign")
            case "fullscreen":
                o["fullscreen"] = self.fullscreen = not self.fullscreen
                self._make_window()
            case "back":
                self.mode = "title"
        self.save.write()
        return None

    def draw_options(self) -> None:
        self.title_scene.draw(self.view, self.frame)
        self.blit_full()
        dim = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        self.screen.blit(dim, (0, 0))
        o = self.save.opts
        self.text("OPCIONES", self.f_title, (LW / 2, 50), GOLD, center=True)
        vals = {
            "music": ("Música", "sí" if o["music"] else "no"),
            "voices": ("Voces (recitado en italiano)", "sí" if o["voices"] else "no"),
            "lang": ("Subtítulos", LANG_NAMES[self.lang]),
            "quality": ("Luz y bloom", "alta" if self.quality else "baja"),
            "volume": ("Volumen", "▮" * o["volume"] + "▯" * (10 - o["volume"])),
            "fullscreen": ("Pantalla completa", "sí" if self.fullscreen else "no"),
            "motion": ("Movimiento (temblor, grano)", "sí" if o["motion"] else "reducido"),
            "markers": ("Iconos de enfermedad", "sí" if o["markers"] else "no"),
            "contrast": ("Alto contraste", "sí" if o["contrast"] else "no"),
            "shadows": ("Sombras de los oficios", "sí" if o["shadows"] else "no"),
            "back": ("Volver", ""),
        }
        for k, item in enumerate(self.OPTS):
            y = 92 + k * 20
            sel = k == self.opt_sel
            name, val = vals[item]
            if sel:
                r = self.R(170, y - 3, 300, 19)
                g = pygame.Surface(r.size, pygame.SRCALPHA)
                g.fill((120, 30, 20, 140))
                self.screen.blit(g, r.topleft)
                pygame.draw.rect(self.screen, GOLD, r, 1)
            self.text(name, self.f_med, (186, y), UI_ACC if sel else UI_FG)
            self.text(val, self.f_med, (454, y), UI_FG, right=True)
        self.text("↑↓ elegir · ←→ / Enter cambiar · Esc volver   ·   Mando: cruceta, A, B", self.f_tiny, (LW / 2, 340), UI_DIM, center=True)

    # ── mando ────────────────────────────────────────────────────────────
    def pad_event(self, ev) -> list:
        """Traduce el mando: en los menús a teclas; en la partida, a órdenes."""
        sdl = self._sdlc
        out: list = []
        if sdl is None:
            return out
        if ev.type == pygame.CONTROLLERDEVICEADDED:
            try:
                self.pads.append(sdl.Controller(ev.device_index))
            except pygame.error:
                pass
            return out
        if ev.type == pygame.CONTROLLERAXISMOTION:
            v = ev.value / 32767
            name = {pygame.CONTROLLER_AXIS_LEFTX: "lx", pygame.CONTROLLER_AXIS_LEFTY: "ly", pygame.CONTROLLER_AXIS_RIGHTX: "rx",
                    pygame.CONTROLLER_AXIS_TRIGGERLEFT: "lt", pygame.CONTROLLER_AXIS_TRIGGERRIGHT: "rt"}.get(ev.axis)
            if name is None:
                return out
            old = self.pad_axes[name]
            self.pad_axes[name] = v
            if self.mode == "play" and name in ("lt", "rt") and old < 0.5 <= v and self.p and not self.p.demo:
                self.apply(("rr", self.p.world.rr + (5 if name == "rt" else -5)))
            return out
        if ev.type == pygame.CONTROLLERBUTTONUP:
            self.pad_held.discard(ev.button)
            if ev.button in (pygame.CONTROLLER_BUTTON_BACK, pygame.CONTROLLER_BUTTON_START):
                self.pad_combo = 0
            return out
        if ev.type != pygame.CONTROLLERBUTTONDOWN:
            return out
        b = ev.button
        self.pad_held.add(b)
        key = lambda k: pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="")  # noqa: E731
        if self.mode != "play" or self.p is None:
            m = {pygame.CONTROLLER_BUTTON_DPAD_UP: pygame.K_UP, pygame.CONTROLLER_BUTTON_DPAD_DOWN: pygame.K_DOWN,
                 pygame.CONTROLLER_BUTTON_DPAD_LEFT: pygame.K_LEFT, pygame.CONTROLLER_BUTTON_DPAD_RIGHT: pygame.K_RIGHT,
                 pygame.CONTROLLER_BUTTON_A: pygame.K_RETURN, pygame.CONTROLLER_BUTTON_START: pygame.K_RETURN,
                 pygame.CONTROLLER_BUTTON_B: pygame.K_ESCAPE, pygame.CONTROLLER_BUTTON_Y: pygame.K_v}
            if b in m:
                out.append(key(m[b]))
            return out
        p = self.p
        w = p.world
        self.pad_active = True
        x, y, inside = self.world_mouse()
        held = self.pad_held
        if b == pygame.CONTROLLER_BUTTON_A and inside and not p.demo:
            if p.armed is not None:
                self.use_armed(x, y)
            else:
                best, _ = w.pick(x, y, p.skill)
                if best is not None:
                    self.apply(("assign", best.id, str(p.skill)))
        elif b == pygame.CONTROLLER_BUTTON_B:
            p.armed = p.swap_a = None
        elif b == pygame.CONTROLLER_BUTTON_X and "arancia" in w.shield and not p.demo:
            self.apply(("palla", w.shield.index("arancia"), x, y))
        elif b == pygame.CONTROLLER_BUTTON_Y and p.armed is not None and not p.demo:
            self.use_armed(x, y)
        elif b in (pygame.CONTROLLER_BUTTON_DPAD_LEFT, pygame.CONTROLLER_BUTTON_DPAD_RIGHT) and w.shield:
            step = 1 if b == pygame.CONTROLLER_BUTTON_DPAD_RIGHT else -1
            p.armed = 0 if p.armed is None else (p.armed + step) % len(w.shield)
            self.sfx.play("click")
        elif b == pygame.CONTROLLER_BUTTON_DPAD_UP or b == pygame.CONTROLLER_BUTTON_DPAD_DOWN:
            p.armed = None
        elif b in (pygame.CONTROLLER_BUTTON_LEFTSHOULDER, pygame.CONTROLLER_BUTTON_RIGHTSHOULDER):
            step = 1 if b == pygame.CONTROLLER_BUTTON_RIGHTSHOULDER else -1
            p.skill = SKILLS[(SKILLS.index(p.skill) + step) % len(SKILLS)]
            self.sfx.play("click")
        elif b == pygame.CONTROLLER_BUTTON_START:
            if pygame.CONTROLLER_BUTTON_BACK in held:
                self.pad_combo = 1
            else:
                p.paused = not p.paused
        elif b == pygame.CONTROLLER_BUTTON_BACK:
            if pygame.CONTROLLER_BUTTON_START in held:
                self.pad_combo = 1
            elif not p.demo:
                self.apply(("dioneo",))
        elif b == pygame.CONTROLLER_BUTTON_RIGHTSTICK:
            p.ff = not p.ff
        return out

    def draw_title(self) -> None:
        self.sfx.music("inferno")
        self.title_scene.draw(self.view, self.frame)
        self.blit_full()
        t = self.frame
        k = LH / VIEW_H
        self.text("PER ME SI VA NE LA CITTÀ DOLENTE", self.f_tiny, (LW / 2, (VIEW_H - 54 - 129) * k), (170, 130, 110),
                  center=True, alpha=min(255, t * 2))
        a = min(255, t * 3)
        self.text("DANTE'S HELL", self.f_huge, (LW / 2, 18), (255, 206, 120), center=True, alpha=a)
        self.text("D I S C I P L I N A T I", self.f_big, (LW / 2, 60), (236, 230, 214), center=True, alpha=a)
        self.text("«Palle, palle, palle!» — una commedia per lemming", self.f_it, (LW / 2, 80), UI_DIM, center=True, alpha=a)
        for k, item in enumerate(self.MENU):
            y = 170 + k * 18
            sel = k == self.menu_sel
            if sel:
                r = self.R(16, y - 2, 200, 16)
                g = pygame.Surface(r.size, pygame.SRCALPHA)
                g.fill((120, 30, 20, 120))
                self.screen.blit(g, r.topleft)
                pygame.draw.rect(self.screen, GOLD, r, 1)
            label = item
            if k == 0:
                label = ("Continuar" if self.unlocked else "Comenzar") + f" — {self.level_label(self.unlocked)}"
            self.text(label, self.f_med, (116, y), UI_ACC if sel else UI_FG, center=True)
        self.text("↑↓ Enter · F11 pantalla completa · M música · Esc salir", self.f_tiny, (LW / 2, 346), UI_DIM, center=True)

    def level_label(self, i: int) -> str:
        lv = get_level(i)
        return f"{i} · {lv.place}"

    # ── mapa de la Commedia ──────────────────────────────────────────────
    @staticmethod
    @lru_cache(maxsize=1)
    def node_positions() -> list[tuple[float, float]]:
        pos = [(108.0, 48.0)]
        for k in range(1, 35):  # el embudo
            depth = k / 34
            wdt = 92 * (1 - depth * 0.85)
            pos.append((108 + wdt * math.sin(k * 1.15), 62 + depth * 250))
        for k in range(33):  # la montaña
            h = k / 32
            wdt = 88 * (1 - h * 0.9)
            pos.append((322 + wdt * math.sin(k * 1.05 + 0.5), 312 - h * 250))
        for k in range(33):  # los cielos
            ang = k * 0.62
            r = 96 * (1 - k / 34) + 6
            pos.append((532 + r * math.cos(ang), 180 + r * 0.95 * math.sin(ang)))
        return pos

    def on_map(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.mode = "title"
            elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                self.sel = min(N_LEVELS - 1, self.sel + 1)
            elif ev.key in (pygame.K_LEFT, pygame.K_a):
                self.sel = max(0, self.sel - 1)
            elif ev.key in (pygame.K_UP, pygame.K_w):
                self.sel = min(N_LEVELS - 1, self.sel + 10)
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.sel = max(0, self.sel - 10)
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE) and self.sel <= self.unlocked:
                self.open_level(self.sel)
            elif ev.key == pygame.K_v and self.sel <= self.unlocked:
                self.start_play(self.sel, pilot=Autopilot(get_level(self.sel).solution), demo=True)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            mx, my = ev.pos[0] / self.s, ev.pos[1] / self.s
            best = min(range(N_LEVELS), key=lambda i: (self.node_positions()[i][0] - mx) ** 2 + (self.node_positions()[i][1] - my) ** 2)
            bx, by = self.node_positions()[best]
            if (bx - mx) ** 2 + (by - my) ** 2 < 64:
                if best == self.sel and best <= self.unlocked:
                    self.open_level(best)
                self.sel = best
        return None

    def draw_map(self) -> None:
        self.sfx.music("limbo")
        scr = self.screen
        bg = cached_gradient(LW * self.s, LH * self.s, (16, 8, 10), (40, 26, 30))
        scr.blit(bg, (0, 0))
        # títulos de cantica
        for x, name, col in ((108, "INFERNO", CANTICA_COL["inferno"]), (322, "PURGATORIO", CANTICA_COL["purgatorio"]),
                             (532, "PARADISO", CANTICA_COL["paradiso"])):
            self.text(name, self.f_big, (x, 8), col, center=True)
        # siluetas: embudo, monte, esferas
        s = self.s
        pygame.draw.polygon(scr, (60, 20, 16), [(int(14 * s), int(40 * s)), (int(202 * s), int(40 * s)), (int(120 * s), int(318 * s)), (int(96 * s), int(318 * s))], 1)
        pygame.draw.polygon(scr, (40, 60, 90), [(int(222 * s), int(326 * s)), (int(422 * s), int(326 * s)), (int(330 * s), int(50 * s)), (int(314 * s), int(50 * s))], 1)
        for k in range(9):
            pygame.draw.circle(scr, (90, 80, 50), (int(532 * s), int(180 * s)), int((14 + k * 11) * s), 1)
        pos = self.node_positions()
        pts = [(int(x * s), int(y * s)) for x, y in pos]
        pygame.draw.lines(scr, (110, 90, 70), False, pts[:35], max(1, s // 2))
        pygame.draw.lines(scr, (80, 100, 130), False, pts[35:68], max(1, s // 2))
        pygame.draw.lines(scr, (150, 130, 80), False, pts[68:], max(1, s // 2))
        done = self.save.data["levels"]
        for i, (x, y) in enumerate(pos):
            c = CANTICA_COL[cantica_of(i)]
            locked = i > self.unlocked
            col = (70, 60, 56) if locked else c
            r = 3.2 if str(i) in done else 2.4
            if i % 10 == 1 and i > 1:
                pygame.draw.circle(scr, GOLD_D, (int(x * s), int(y * s)), int((r + 2.5) * s), 1)
            pygame.draw.circle(scr, col, (int(x * s), int(y * s)), int(r * s))
            if i in self.save.data["pagine"]:
                pygame.draw.circle(scr, (255, 250, 220), (int(x * s), int(y * s)), int(1 * s))
            if self.save.best(i).get("stars") == 3:
                pygame.draw.circle(scr, GOLD, (int(x * s), int(y * s)), int((r + 1.5) * s), 1)
            if i == self.sel:
                pulse = 5 + math.sin(self.frame * 0.15) * 1.5
                pygame.draw.circle(scr, (255, 255, 255), (int(x * s), int(y * s)), int(pulse * s), 1)
        lv = get_level(self.sel)
        self.panel(150, 326, 340, 32, 220)
        st = done.get(str(self.sel))
        b = self.save.best(self.sel)
        stat = f"  ·  récord {b['saved']}/100 ({b.get('stars', 0)}/3 estrellas)" if b else ""
        del st
        lock = "  (bloqueado)" if self.sel > self.unlocked else ""
        self.text(f"{self.sel} · {lv.place} — {lv.canto}{lock}", self.f_med, (320, 328), UI_ACC, center=True)
        self.text(f"«{lv.name}» · {lv.difficulty} · Giornata {roman(lv.giornata + 1)} ({GIORNATE[lv.giornata][0]}){stat}",
                  self.f_small, (320, 342), UI_FG, center=True)
        self.text("←→ nivel · ↑↓ ±10 · Enter jugar · V ver solución · Esc volver", self.f_tiny, (LW - 4, 2), UI_DIM, right=True)
        camp = self.save.camp_for(self.unlocked)
        self.text(f"Peso {camp.peso}", self.f_small, (4, 2), UI_ACC)

    # ── la villa: interludio del Decamerón ───────────────────────────────
    def on_giornata(self, ev):
        g = self.giornata
        assert g is not None
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.mode = "map"
        elif ev.type == pygame.KEYDOWN or (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1):
            if g["t"] < 60:
                g["t"] = 600
            else:
                self.open_preview(g["next"])
        return None

    def draw_giornata(self) -> None:
        g = self.giornata
        assert g is not None
        g["t"] += 1
        gi = g["gi"]
        draw_villa(self.view, self.frame, gi, self.sprites)
        self.blit_view()
        king, tema, _, desc = GIORNATE[gi]
        self.text(f"GIORNATA {roman(gi + 1)}", self.f_title, (LW / 2, 8), GOLD, center=True)
        self.text(f"{'Rey' if king in ('Filostrato', 'Dioneo', 'Panfilo') else 'Reina'}: {king}  ·  {tema}", self.f_med,
                  (LW / 2, 34), UI_FG, center=True)
        self.panel(40, 258, 560, 100, 215)
        lines = brigata_lines(gi, self.save.camp_for(g["next"]), self.save.pct())
        shown = min(len(lines), 1 + g["t"] // 70)
        y = 263
        for who, line in lines[:shown]:
            self.text(f"{who}", self.f_small, (52, y + 1), UI_ACC)
            y = self.para(line, self.f_it, 120, y, 470) + 2
        self.text(f"Modificador: {desc}", self.f_small, (LW / 2, 50), (190, 255, 190), center=True)
        self.text("Enter para seguir", self.f_tiny, (LW / 2, 348), UI_DIM, center=True)

    # ── previa del nivel ─────────────────────────────────────────────────
    def on_preview(self, ev):
        assert self.preview is not None
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.mode = "map"
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.start_play(self.preview[0])
            elif ev.key == pygame.K_v:
                self.start_play(self.preview[0], pilot=Autopilot(get_level(self.preview[0]).solution), demo=True)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.start_play(self.preview[0])
        return None

    def draw_preview(self) -> None:
        assert self.preview is not None
        idx, w, r = self.preview
        lv = w.level
        cam = int((math.sin(self.frame * 0.004) * 0.5 + 0.5) * max(0, w.terrain.w - VIEW_W))
        r.draw(self.view, cam, self.frame)
        self.blit_view()
        dim = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 120))
        self.screen.blit(dim, (0, 0))
        col = CANTICA_COL[lv.cantica]
        self.text(f"{CANTICHE[lv.cantica].upper()} · {lv.canto}", self.f_small, (LW / 2, 10), col, center=True)
        self.text(lv.place, self.f_title, (LW / 2, 22), UI_FG, center=True)
        self.text(f"«{lv.name}»", self.f_it, (LW / 2, 50), UI_ACC, center=True)
        self.panel(30, 70, 580, 254, 200)
        y = 78
        if w.maestro_due:
            y = self.para(f"«{lv.sermon}»", self.f_it, 44, y, 552, (230, 210, 200))
            self.text("— Il Maestro Lapo", self.f_small, (596, y), UI_DIM, right=True)
            y += 14
        y = self.para(lv.hint, self.f_med, 44, y, 552, UI_FG) + 2
        self.text(f"— {lv.guide}", self.f_small, (596, y - 2), UI_DIM, right=True)
        y += 12
        pct = round(100 * lv.to_save / lv.total)
        days = f"{DAYS:g} días"
        self.text(f"{lv.total} disciplinati · salvar {lv.to_save} ({pct} %) · {days} ({lv.minutes} min) · cadenza {lv.rr} · {lv.difficulty}",
                  self.f_med, (LW / 2, y), UI_ACC, center=True)
        y += 16
        skills = [f"{SKILL_ACTION[k].capitalize()} ∞" for k in SKILLS if w.has_skill(k)]
        y = self.para("  ·  ".join(skills), self.f_small, 44, y, 552, UI_OK, center=True) + 4
        gm = GIORNATE[lv.giornata]
        self.text(f"Giornata {roman(lv.giornata + 1)} — {gm[0]}: {gm[3]}", self.f_small, (LW / 2, y), (200, 200, 240), center=True)
        y += 12
        for m in sorted(lv.mods):
            if m in MOD_TEXT and y < 300:
                self.text("· " + MOD_TEXT[m], self.f_small, (LW / 2, y), (240, 200, 160), center=True)
                y += 11
        sh = ", ".join(PALLE_INFO[p][0] for p in w.shield) or "vacío"
        self.text(f"Escudo de {SHIELD_OWNER[lv.cantica]} ({len(w.shield)}/{w.slots}): {sh}  ·  Peso {w.peso}",
                  self.f_small, (LW / 2, 306), (230, 220, 200), center=True)
        b = self.save.best(idx)
        if b:
            self.text(f"Tu récord: {b['saved']} almas", self.f_small, (LW / 2 - 20, 320), GOLD, center=True)
            self.stars(LW / 2 + 40, 325, b.get("stars", 0), 4)
        self.text("Enter o clic: empezar · V: ver la solución · Esc: mapa", self.f_tiny, (LW / 2, 340), UI_DIM, center=True)

    # ── partida ──────────────────────────────────────────────────────────
    def apply(self, cmd: Command) -> bool:
        p = self.p
        assert p is not None
        ok = p.world.do(cmd)
        if ok:
            p.log.append([p.world.tick_count, *cmd])
        self.drain_events()
        return ok

    def drain_events(self) -> None:
        p = self.p
        assert p is not None
        ev = p.world.events
        for name in dict.fromkeys(ev):
            self.sfx.play(name)
        ev.clear()
        w = p.world
        if w.msg_serial != p.msg_seen and w.messages:
            p.msg_seen = w.msg_serial
            text, _, who, kw = w.messages[-1]
            self.sfx.speak(who, tr(text, "it", **kw))

    def world_mouse(self) -> tuple[int, int, bool]:
        assert self.p is not None
        if self.pad_active:
            x, y = int(self.vcur[0]), int(self.vcur[1])
            return x + int(round(self.p.smooth_cam)), y, y < VIEW_H
        mx, my = pygame.mouse.get_pos()
        x, y = mx // self.s, my // self.s
        return x + int(round(self.p.smooth_cam)), y, y < VIEW_H

    def on_play(self, ev):
        p = self.p
        assert p is not None
        w = p.world
        if ev.type == pygame.KEYDOWN:
            k = ev.key
            mods = pygame.key.get_mods()
            if k == pygame.K_ESCAPE:
                if p.armed is not None:
                    p.armed = p.swap_a = None
                else:
                    p.aborted = True
                    self.finish_play()
            elif k in (pygame.K_SPACE, pygame.K_p):
                p.paused = not p.paused
            elif k == pygame.K_f:
                p.speed = {1: 2, 2: 4, 4: 8, 8: 1}.get(p.speed if p.ff else 1, 2)
                p.ff = p.speed > 1
            elif k == pygame.K_BACKSPACE and not p.demo:
                self.rewind()
            elif k == pygame.K_PERIOD and p.paused:
                self.step_once()
            elif k == pygame.K_F5 and not p.demo:
                self.start_play(p.idx)
            elif k == pygame.K_h:
                self.hide_hud = not self.hide_hud
            elif k == pygame.K_F12:
                self.photo()
            elif k == pygame.K_m:
                self.sfx.toggle(THEMES[w.level.theme].music)
            elif k == pygame.K_n:
                self.press_nuke()
            elif k == pygame.K_DELETE:
                p.nuke_hold = 1
            elif k == pygame.K_d and not p.demo:
                self.apply(("dioneo",))
            elif k == pygame.K_c and not p.demo and "cambio" in w.shield:
                self.apply(("tempo", w.shield.index("cambio")))
            elif k == pygame.K_TAB and p.armed is not None and p.armed < len(w.shield) and w.shield[p.armed] == "mecenate":
                p.artist = ARTISTS[(ARTISTS.index(p.artist or w.next_artist()) + 1) % 3]
                self.sfx.play("click")
            elif k == pygame.K_RETURN and w.compagnia_done and w.maestro_out:
                w.maestro_wait = 10**9
            elif pygame.K_1 <= k <= pygame.K_9:
                p.skill = SKILLS[k - pygame.K_1]
                self.sfx.play("click")
            elif k in SLOT_KEYS and not p.demo:
                slot = SLOT_KEYS.index(k)
                if slot < len(w.shield):
                    if mods & pygame.KMOD_SHIFT:
                        self.apply(("return", slot))
                    elif w.shield[slot] == "giglio" and w.level.special == "final":
                        self.apply(("palla", slot, w.exits[0].x if w.exits else 0, 100))
                    else:
                        p.armed = None if p.armed == slot else slot
                        p.swap_a = None
                        self.sfx.play("click")
            elif k in (pygame.K_PLUS, pygame.K_KP_PLUS, pygame.K_EQUALS, pygame.K_F2):
                if not p.demo:
                    self.apply(("rr", w.rr + 5))
            elif k in (pygame.K_MINUS, pygame.K_KP_MINUS, pygame.K_F1):
                if not p.demo:
                    self.apply(("rr", w.rr - 5))
        elif ev.type == pygame.KEYUP and ev.key == pygame.K_DELETE:
            p.nuke_hold = 0
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3):
            mx, my = ev.pos[0] / self.s, ev.pos[1] / self.s
            if my < VIEW_H:
                if p.demo:
                    return None
                x, y, _ = self.world_mouse()
                if ev.button == 3 and p.armed is None and "arancia" in w.shield:
                    self.apply(("palla", w.shield.index("arancia"), x, y))
                elif p.armed is not None:
                    self.use_armed(x, y)
                elif ev.button == 1:
                    best, _ = w.pick(x, y, p.skill)
                    if best is not None:
                        self.apply(("assign", best.id, str(p.skill)))
            elif ev.button == 1:
                if MINI.collidepoint(mx, my):
                    self.minimap_jump(mx)
                elif mx < SKILL_X0 + len(SKILLS) * SKILL_W:
                    i = int((mx - SKILL_X0) // SKILL_W)
                    if 0 <= i < len(SKILLS):
                        p.skill = SKILLS[i]
                        self.sfx.play("click")
                else:
                    for bi, bx in enumerate(BTN_X):
                        if bx <= mx < bx + (20 if bi < 4 else 40):
                            self.press_button(bi)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            p.rr_hold = 0
        elif ev.type == pygame.MOUSEMOTION and ev.buttons[0]:
            mx, my = ev.pos[0] / self.s, ev.pos[1] / self.s
            if MINI.collidepoint(mx, my):
                self.minimap_jump(mx)
        elif ev.type == pygame.MOUSEMOTION and ev.buttons[1]:
            p.cam = self._clamp_cam(w, p.cam - ev.rel[0] / self.s)
        elif ev.type == pygame.MOUSEWHEEL:
            if ev.x:
                p.cam = self._clamp_cam(w, p.cam - ev.x * 16)
            else:
                i = (SKILLS.index(p.skill) - ev.y) % len(SKILLS)
                p.skill = SKILLS[i]
                self.sfx.play("click")
        return None

    def use_armed(self, x: int, y: int) -> None:
        p = self.p
        assert p is not None
        w = p.world
        slot = p.armed
        assert slot is not None
        if slot >= len(w.shield):
            p.armed = None
            return
        kind = w.shield[slot]
        if kind == "congiura" and w.guard_near(x, y) is None:
            L, _ = w.pick(x, y, None)
            if L is None:
                return
            if p.swap_a is None:
                p.swap_a = L.id
                self.sfx.play("click")
                return
            if self.apply(("swap", slot, p.swap_a, L.id)):
                p.armed = p.swap_a = None
            return
        if kind == "mecenate":
            ok = self.apply(("mecenate", slot, x, y, p.artist or w.next_artist()))
            p.artist = None
        else:
            ok = self.apply(("palla", slot, x, y))
        if ok:
            p.armed = None
        else:
            self.sfx.play("ting")

    def press_nuke(self) -> None:
        p = self.p
        assert p is not None
        if p.demo:
            return
        if p.nuke_armed > 0:
            self.apply(("nuke",))
            p.nuke_armed = 0
        else:
            p.nuke_armed = 60

    def press_button(self, i: int) -> None:
        p = self.p
        assert p is not None
        if i in (BTN_RR_DN, BTN_RR_UP):
            if not p.demo:
                p.rr_hold = -1 if i == BTN_RR_DN else 1
                p.hold_t = 0
                self.apply(("rr", p.world.rr + p.rr_hold))
        elif i == BTN_PAUSE:
            p.paused = not p.paused
        elif i == BTN_FF:
            p.ff = not p.ff
        elif i == BTN_NUKE:
            self.press_nuke()

    def minimap_jump(self, mx: float) -> None:
        p = self.p
        assert p is not None
        frac = (mx - MINI.x) / MINI.w
        p.cam = self._clamp_cam(p.world, frac * p.world.terrain.w - VIEW_W / 2)

    def update_play(self, dt: int) -> None:
        p = self.p
        assert p is not None
        w = p.world
        if self.pads:
            ax = self.pad_axes
            if abs(ax["lx"]) > 0.15 or abs(ax["ly"]) > 0.15:
                self.pad_active = True
                self.vcur[0] = max(0, min(VIEW_W - 1, self.vcur[0] + ax["lx"] * 5))
                self.vcur[1] = max(0, min(VIEW_H - 1, self.vcur[1] + ax["ly"] * 5))
            if abs(ax["rx"]) > 0.2:
                p.cam = self._clamp_cam(w, p.cam + ax["rx"] * 8)
            if self.pad_combo:
                self.pad_combo += 1
                if self.pad_combo > 120:
                    self.pad_combo = 0
                    if not p.demo:
                        self.apply(("nuke",))
        keys = pygame.key.get_pressed()
        speed = 9 if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] else 4
        if keys[pygame.K_LEFT]:
            p.cam -= speed
        if keys[pygame.K_RIGHT]:
            p.cam += speed
        if pygame.mouse.get_focused():
            mx, my = pygame.mouse.get_pos()
            if my < VIEW_H * self.s:
                if mx < 4 * self.s:
                    p.cam -= speed
                elif mx > (LW - 4) * self.s:
                    p.cam += speed
        p.cam = self._clamp_cam(w, p.cam)
        if p.nuke_armed > 0:
            p.nuke_armed -= 1
        if p.nuke_hold:
            p.nuke_hold += 1
            if p.nuke_hold > 120:
                p.nuke_hold = 0
                if not p.demo:
                    self.apply(("nuke",))
        if p.rr_hold:
            p.hold_t += 1
            if p.hold_t > 12 and p.hold_t % 3 == 0:
                self.apply(("rr", w.rr + p.rr_hold))
        if w.done:
            p.end_wait += dt
            if p.end_wait > 1600:
                self.finish_play()
            return
        if p.paused:
            return
        p.acc = min(p.acc + dt, 250)
        while p.acc >= TICK_MS:
            p.acc -= TICK_MS
            for _ in range(p.speed if p.ff else 1):
                if w.done:
                    break
                self.step_once()
                w = p.world

    def step_once(self) -> None:
        """Un tick de simulación, con la instantánea para rebobinar cada dos segundos."""
        p = self.p
        assert p is not None
        w = p.world
        if w.done:
            return
        if not p.demo and w.tick_count % (2 * TPS) == 0 and (not p.snaps or p.snaps[-1][0] != w.tick_count):
            p.snaps.append((w.tick_count, w.snapshot(), len(p.log)))
        if p.pilot:
            p.pilot.step(w, self.apply)
        w.tick()
        self.drain_events()

    def rewind(self) -> None:
        """Vuelve unos tres segundos atrás. Lo hecho después se borra del registro."""
        p = self.p
        assert p is not None
        now = p.world.tick_count
        while p.snaps and p.snaps[-1][0] > now - 3 * TPS and len(p.snaps) > 1:
            p.snaps.pop()
        if not p.snaps:
            return
        tick, snap, nlog = p.snaps[-1]
        w = World.thaw(snap)
        p.world = w
        p.renderer.world = w
        p.renderer.fx = FX()
        p.renderer.sync(full=True)
        del p.log[nlog:]
        p.rewinds += 1
        p.end_wait = 0
        self.sfx.play("lume")

    def photo(self) -> None:
        path = Path.cwd() / f"dantes_hell_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            pygame.image.save(self.screen, str(path))
            self.toasts.append([f"foto guardada: {path.name}", 3 * 60])
        except (OSError, pygame.error):
            pass

    def draw_play(self) -> None:
        p = self.p
        assert p is not None
        w = p.world
        p.smooth_cam += (p.cam - p.smooth_cam) * 0.35
        cam = int(round(p.smooth_cam))
        x, y, inside = self.world_mouse()
        hover, count = w.pick(x, y, p.skill) if inside else (None, 0)
        p.renderer.draw(self.view, cam, self.frame)
        pygame.mouse.set_visible(not inside and not self.pad_active)
        if inside:
            vx = x - cam
            col = (255, 255, 255) if p.armed is None else PALLE_INFO[w.shield[p.armed]][2] if p.armed < len(w.shield) else (255, 255, 255)
            if hover is not None and p.armed is None:
                pygame.draw.rect(self.view, col, (hover.x - 6 - cam, w.rmid(hover) - 8, 13, 15), 1)
                if self.save.opts["shadows"] and w.can_assign(hover, p.skill):
                    for k_, (sx, sy) in enumerate(skill_shadow(w, hover, p.skill)):
                        if (k_ + self.frame // 4) % 3 == 0:
                            self.view.fill((255, 255, 210), (sx - cam, sy, 1, 1))
            elif p.armed is not None:
                pygame.draw.circle(self.view, col, (vx, y), 10 + int(2 * math.sin(self.frame * 0.3)), 1)
                pygame.draw.circle(self.view, col, (vx, y), 2)
            else:
                for a, b in (((-5, 0), (-2, 0)), ((2, 0), (5, 0)), ((0, -5), (0, -2)), ((0, 2), (0, 5))):
                    pygame.draw.line(self.view, col, (vx + a[0], y + a[1]), (vx + b[0], y + b[1]))
        self.blit_view(p.renderer.fx.shake if self.save.opts["motion"] else 0)
        if self.hide_hud:  # modo foto
            return
        self.draw_hud(hover, count)
        self.draw_panel()

    def draw_hud(self, hover: Lemming | None, count: int) -> None:
        p = self.p
        assert p is not None
        w = p.world
        lv = w.level
        if sum(w.theme.ambient) > 600:
            self.screen.blit(self.scrim(), (0, 0))
        days = DAYS * w.time_left / max(1, w.time_total)
        d_int, half = int(days), days - int(days) >= 0.5
        self.text(f"Día {d_int}{'½' if half else ''}", self.f_big, (8, 4), (255, 220, 160) if days > 5 else UI_BAD)
        pct = round(100 * w.saved / max(1, w.total))
        need = round(100 * lv.to_save / max(1, w.total))
        self.text(f"Salvados {pct} % / {need} %   ·   En marcha {w.alive}   ·   Caídos {w.dead}", self.f_small, (8, 22),
                  UI_OK if w.saved >= lv.to_save else UI_FG)
        self.text(f"{lv.place} — «{lv.name}»", self.f_tiny, (8, 34), UI_DIM)
        ps = p_marks(lv.id)
        if ps is not None:
            self.text("Frente: " + ("P " * ps if ps else "limpia"), self.f_tiny, (8, 58), (230, 130, 110))
        flags = []
        if p.demo:
            flags.append("DEMO")
        if p.paused:
            flags.append("PAUSA")
        if p.ff:
            flags.append(f"» ×{p.speed}")
        if p.rewinds:
            flags.append(f"⟲ {p.rewinds}")
        if w.night:
            flags.append("NOCHE: no se sube")
        if w.combo:
            flags.append("PALLE, PALLE, PALLE!")
        if w.panic:
            flags.append("¡PÁNICO!")
        if w.dioneo:
            flags.append(f"Privilegio di Dioneo {w.dioneo // TPS + 1}s")
        if w.lume:
            flags.append("Lume")
        if flags:
            self.text("   ".join(flags), self.f_small, (LW / 2, 4), UI_ACC, center=True)
        if p.paused:
            self.panel(110, 100, 420, 124, 210)
            rows = ["Retroceso: rebobinar 3 s · «.»: un paso · F: ×1/×2/×4/×8 · F5: reiniciar · H: ocultar HUD · F12: foto",
                    "1–9 / rueda: oficio · clic: asignar · ←→ / bordes / minimapa: cámara",
                    "Q W E R T Y U I: armar palla · clic: usarla · clic derecho: lanzar naranja",
                    "Mayús + tecla: devolver palla (avaros) · D: Privilegio di Dioneo",
                    "+ / −: cadenza · F: avance ×4 · Supr 2 s (o N dos veces): Dies Irae",
                    "C: un bezante compra más días (Purgatorio) · Tab: artista del Mecenate",
                    "Espacio: seguir · Esc: abandonar · M: música · F11: pantalla completa"]
            self.text("PAUSA", self.f_big, (LW / 2, 106), GOLD, center=True)
            for k, row in enumerate(rows):
                self.text(row, self.f_small, (LW / 2, 126 + k * 13), UI_FG, center=True)
        self.draw_shield(w, p.armed)
        # mensajes (Virgilio, guardianes, Brigata…)
        y = VIEW_H - 14
        for text, ttl, who, kw in reversed(w.messages[-3:]):
            a = min(255, ttl * 8)
            text = tr(text, self.lang, **kw)
            line = f"{who}: {text}" if who and not text.startswith(who) else text
            for k, ln in enumerate(reversed(self.wrap(line, self.f_it, 520))):
                self.text(ln, self.f_it, (LW / 2, y - k * 11), (250, 236, 210), center=True, alpha=a)
            y -= 11 * len(self.wrap(line, self.f_it, 520)) + 2
        if w.compagnia_done and w.maestro_out:
            self.text("Solo queda el Maestro. Enter: dejarle atrás.", self.f_med, (LW / 2, 60), UI_ACC, center=True)
        if hover is not None:
            tag = STATE_NAMES[hover.state]
            if hover.maestro:
                tag = "Il Maestro Lapo (no acepta oficios)"
            elif hover.child:
                tag = "Michelangelo, el niño"
            if hover.climber:
                tag += " · escala"
            if hover.floater:
                tag += " · planea"
            if hover.medico:
                tag += " · cura"
            if hover.moria:
                tag += " · " + ("con fiebre" if hover.moria == 1 else "peste grave: solo acepta Explotar o Curar")
            if hover.fervor > FERVOR_SLOW:
                tag += " · se azota"
            self.text(f"{tag}  ({count})", self.f_small, (8, 46), (255, 230, 150))
        if p.armed is not None and p.armed < len(w.shield):
            kind = w.shield[p.armed]
            msg = PALLE_INFO[kind][1]
            if kind == "congiura" and p.swap_a is not None:
                msg = "Elige la segunda alma."
            if kind == "mecenate":
                art = p.artist or w.next_artist()
                msg = f"Artista: {art.capitalize()} (Tab cambia: Brunelleschi · Botticelli · Caravaggio)"
            self.text(f"{PALLE_INFO[kind][0]}: {msg}  (clic para usar · Esc cancela)", self.f_small, (LW / 2, 18), UI_ACC, center=True)

    @lru_cache(maxsize=1)
    def scrim(self) -> pygame.Surface:
        """Velo oscuro tras el HUD cuando el cielo es demasiado claro."""
        h = 64 * self.s
        surf = pygame.Surface((LW * self.s, h), pygame.SRCALPHA)
        for y in range(h):
            a = int(150 * (1 - y / h) ** 1.4)
            pygame.draw.line(surf, (20, 12, 6, a), (0, y), (LW * self.s, y))
        return surf

    def draw_shield(self, w: World, armed: int | None) -> None:
        """Escudo mediceo: campo de oro, bolas de gules, la azul arriba."""
        s = self.s
        cx, top = LW - 46, 6
        wd, ht = 64, 74
        pts = [(cx - wd / 2, top), (cx + wd / 2, top), (cx + wd / 2, top + ht * 0.55), (cx, top + ht), (cx - wd / 2, top + ht * 0.55)]
        spts = [(int(x * s), int(y * s)) for x, y in pts]
        pygame.draw.polygon(self.screen, (196, 150, 50), spts)
        inner = [(int((cx + (x - cx) * 0.88) * s), int((top + 3 + (y - top) * 0.9) * s)) for x, y in pts]
        pygame.draw.polygon(self.screen, (238, 196, 84), inner)
        pygame.draw.polygon(self.screen, (120, 80, 30), spts, max(1, s // 2))
        n = w.slots
        # disposición en orla, como en el escudo real
        layout = {8: [(0, 10), (-16, 20), (16, 20), (-20, 34), (20, 34), (-14, 48), (14, 48), (0, 60)],
                  7: [(0, 10), (-16, 22), (16, 22), (-18, 37), (18, 37), (-9, 52), (9, 52)],
                  6: [(0, 10), (-15, 25), (15, 25), (-15, 41), (15, 41), (0, 55)]}[n]
        order = list(range(n))
        shield = list(w.shield)
        # el lirio siempre va arriba
        if "giglio" in shield:
            shield.remove("giglio")
            shield.insert(0, "giglio")
        for k in order:
            dx, dy = layout[k]
            x, y = int((cx + dx) * s), int((top + dy) * s)
            r = int(6 * s)
            if k < len(shield):
                kind = shield[k]
                col = PALLE_INFO[kind][2]
                pygame.draw.circle(self.screen, col, (x, y), r)
                pygame.draw.circle(self.screen, (255, 255, 255), (x - r // 3, y - r // 3), max(1, r // 4))
                if kind == "giglio":
                    pygame.draw.circle(self.screen, (255, 220, 80), (x, y), max(1, r // 3))
                real = w.shield.index(kind) if kind in w.shield else k
                key = "QWERTYUI"[real] if real < 8 else ""
                self.text(key, self.f_tiny, (x / s - 2, y / s - 4), INK, shadow=False)
                if armed is not None and armed == real:
                    pygame.draw.circle(self.screen, (255, 255, 255), (x, y), r + 2 * s, max(1, s // 2))
            else:
                pygame.draw.circle(self.screen, (180, 140, 60), (x, y), r, 1)
        self.text(f"Peso {w.peso}", self.f_small, (cx, top + ht + 2), UI_ACC if w.peso < 15 else UI_BAD, center=True)
        bar = self.R(cx - 28, top + ht + 13, 56, 3)
        pygame.draw.rect(self.screen, (60, 40, 30), bar)
        pygame.draw.rect(self.screen, (220, 90, 60), self.R(cx - 28, top + ht + 13, 56 * min(1, w.peso / 40), 3))

    def draw_panel(self) -> None:
        p = self.p
        assert p is not None
        w = p.world
        s = self.s
        top = VIEW_H
        mx, my = pygame.mouse.get_pos()
        mx, my = mx / s, my / s
        if my >= top and SKILL_X0 <= mx < SKILL_X0 + len(SKILLS) * SKILL_W and not self.pad_active:
            hk = SKILLS[int((mx - SKILL_X0) // SKILL_W)]
            self.text(f"{SKILL_ACTION[hk].capitalize()} ({SKILL_NAMES[hk]}): {SKILL_HELP[hk]}", self.f_small, (8, top - 12), (255, 236, 190))
        # la predela: madera oscura y oro
        bg = cached_gradient(LW * s, PANEL_H * s, (54, 34, 24), (22, 14, 10))
        self.screen.blit(bg, (0, top * s))
        pygame.draw.line(self.screen, GOLD, (0, top * s), (LW * s, top * s), max(1, s))
        for i, sk in enumerate(SKILLS):
            x = SKILL_X0 + i * SKILL_W
            sel = sk == p.skill
            if sk == Skill.FLAGELLANTE and w.level.id >= 99:  # en el último cielo ya no hay látigo
                pygame.draw.rect(self.screen, (18, 12, 10), self.R(x + 1, top + 5, SKILL_W - 2, PANEL_H - 9))
                continue
            r = self.R(x + 1, top + 5, SKILL_W - 2, PANEL_H - 9)
            pygame.draw.rect(self.screen, (70, 26, 22) if sel else (30, 20, 26), r)
            # arco apuntado
            arc = [(int((x + 1) * s), int((top + 16) * s)), (int((x + SKILL_W / 2) * s), int((top + 5) * s)),
                   (int((x + SKILL_W - 1) * s), int((top + 16) * s))]
            pygame.draw.polygon(self.screen, (22, 14, 10), [(r.left, r.top), (r.right, r.top), arc[2], arc[1], arc[0]])
            pygame.draw.lines(self.screen, GOLD if sel else GOLD_D, False, [(r.left, r.bottom), arc[0], arc[1], arc[2], (r.right, r.bottom)],
                              max(1, s // 2) + (1 if sel else 0))
            pygame.draw.line(self.screen, GOLD_D, (r.left, r.bottom), (r.right, r.bottom), max(1, s // 2))
            n = w.has_skill(sk)
            label = "∞" if w.infinite and n else str(w.skills[sk]) if n else "–"
            col = (240, 232, 214) if n else (90, 80, 76)
            draw_skill_icon(self.screen, sk, int((x + SKILL_W / 2) * s), int((top + 31) * s), s * 0.9, col)
            self.text(label, self.f_small if label != "∞" else self.f_med, (x + SKILL_W / 2, top + 11), UI_ACC if n else UI_DIM, center=True)
            self.text(f"{i + 1}", self.f_micro, (x + 3, top + 7), UI_DIM, shadow=False)
            name = SKILL_ACTION[sk]
            nf = self.f_micro if self.f_micro.size(name)[0] / s <= SKILL_W - 4 else self.f_nano
            self.text(name, nf, (x + SKILL_W / 2, top + PANEL_H - 11),
                      UI_ACC if sel else (205, 190, 165) if n else UI_DIM, center=True, shadow=False)
        labels = [("−", str(w.rr_min)), ("+", str(w.rr)), ("‖", ""), ("»", ""), ("Dies Irae", "")]
        for bi, bx in enumerate(BTN_X):
            wd = 20 if bi < 4 else 40
            r = self.R(bx, top + 8, wd - 2, PANEL_H - 14)
            on = (bi == BTN_PAUSE and p.paused) or (bi == BTN_FF and p.ff) or (bi == BTN_NUKE and (p.nuke_armed or p.nuke_hold))
            pygame.draw.rect(self.screen, (80, 30, 22) if on else (30, 20, 26), r)
            pygame.draw.rect(self.screen, GOLD_D, r, max(1, s // 2))
            lab, num = labels[bi]
            if bi == BTN_NUKE:
                col = UI_BAD if (p.nuke_armed % 10 < 5 or not p.nuke_armed) else UI_FG
                self.text("Dies", self.f_small, (bx + wd / 2 - 1, top + 16), col, center=True)
                self.text("Irae", self.f_small, (bx + wd / 2 - 1, top + 28), col, center=True)
                if p.nuke_hold:
                    pygame.draw.rect(self.screen, UI_BAD, self.R(bx + 2, top + PANEL_H - 12, (wd - 6) * p.nuke_hold / 120, 2))
            else:
                self.text(lab, self.f_big, (bx + wd / 2 - 1, top + 20), UI_FG, center=True)
                if num:
                    self.text(num, self.f_tiny, (bx + wd / 2 - 1, top + 10), UI_ACC, center=True)
        self.text("cadenza", self.f_tiny, (BTN_X[0] + 20, top + PANEL_H - 11), UI_DIM, center=True)
        mini = p.renderer.minimap((MINI.w * s, MINI.h * s))
        self.screen.blit(mini, (MINI.x * s, MINI.y * s))
        pygame.draw.rect(self.screen, GOLD_D, self.R(MINI.x - 1, MINI.y - 1, MINI.w + 2, MINI.h + 2), 1)
        fx, fy = MINI.w / w.terrain.w, MINI.h / w.terrain.h
        for L in w.lemmings:
            c = (255, 220, 120) if not L.moria else (160, 220, 60)
            self.screen.fill(c, self.R(MINI.x + L.x * fx, MINI.y + (w.rmid(L)) * fy, 1, 1))
        for g in w.guards:
            if not g.pacified:
                self.screen.fill(UI_BAD, self.R(MINI.x + g.x * fx - 1, MINI.y + (g.y - 6) * fy, 2, 2))
        pygame.draw.rect(self.screen, (255, 255, 255), self.R(MINI.x + p.cam * fx, MINI.y, VIEW_W * fx, MINI.h), 1)
        self.text(f"Giornata {roman(w.level.giornata + 1)} · Dioneo: {'libre' if w.dioneo_avail and not w.dioneo_used else 'gastado'}",
                  self.f_tiny, (MINI.x + MINI.w / 2, top + PANEL_H - 11), UI_DIM, center=True, shadow=False)

    # ── resultado ────────────────────────────────────────────────────────
    def on_result(self, ev):
        r = self.result
        assert r is not None
        if ev.type != pygame.KEYDOWN and not (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1):
            return None
        key = getattr(ev, "key", pygame.K_RETURN)
        if key == pygame.K_ESCAPE:
            self.sel = min(self.unlocked, r["idx"] + (1 if r["ok"] else 0), N_LEVELS - 1)
            self.mode = "map"
        elif key == pygame.K_s and not r["demo"]:
            path = Path.cwd() / f"pydanteshell_nivel{r['idx']:03d}.json"
            try:
                path.write_text(json.dumps({"level": r["idx"], "commands": r["log"], "infinite": self.infinite}))
                r["saved_file"] = path.name
            except OSError as exc:
                r["saved_file"] = f"error: {exc}"
        elif key == pygame.K_r:
            self.open_preview(r["idx"])
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            if r["ending"]:
                self.ending = {"kind": r["ending"], "t": 0}
                self.mode = "ending"
                return None
            if r["idx"] >= ENDLESS_ID and self.endless is not None:
                if r["ok"]:
                    self.next_endless()
                else:
                    self.endless = None
                    self.mode = "title"
                return None
            if r["idx"] == DAILY_ID:
                self.mode = "title"
                return None
            nxt = r["idx"] + 1 if r["ok"] and not r["demo"] else r["idx"]
            if nxt >= N_LEVELS and r["idx"] < N_LEVELS or r["idx"] >= N_LEVELS and r["ok"]:
                self.mode = "map"
            else:
                self.sel = nxt
                self.open_level(nxt)
        return None

    def draw_result(self) -> None:
        r = self.result
        assert r is not None
        r["t"] += 1
        p = self.p
        if p is not None:
            p.renderer.draw(self.view, int(p.smooth_cam), self.frame)
            self.blit_view()
        pygame.mouse.set_visible(True)
        dim = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 150))
        self.screen.blit(dim, (0, 0))
        lv = get_level(r["idx"])
        pct = round(100 * r["saved"] / max(1, r["total"]))
        need = round(100 * r["need"] / max(1, r["total"]))
        self.panel(80, 30, 480, 300, 225)
        self.text(f"{lv.place} — «{lv.name}»", self.f_big, (LW / 2, 40), UI_ACC, center=True)
        big = "Salvados" if r["ok"] else "No bastan"
        self.text(f"{big}: {pct} %", self.f_title, (LW / 2, 62), UI_OK if r["ok"] else UI_BAD, center=True)
        self.text(f"Hacía falta el {need} %  ·  {r['saved']} de {r['total']} (mínimo {r['need']})", self.f_med, (LW / 2, 92), center=True)
        if r.get("stars"):
            self.stars(LW / 2 + 112, 74, r["stars"], 6)
            if r.get("record"):
                self.text("¡récord!", self.f_small, (LW / 2 + 110, 84), GOLD)
        if r["idx"] >= ENDLESS_ID and self.endless is not None:
            self.text(f"Infinito: racha {self.endless['n']} · mejor {self.save.data.get('endless_best', 0)}",
                      self.f_small, (LW / 2, 300), UI_ACC, center=True)
        if r["saved"] == r["total"]:
            msg = "Ni una sola alma perdida. Filomena llora de alegría."
        elif r["ok"]:
            msg = "La Compagnia sigue. El Maestro dice que gracias al látigo; tú sabes que no."
        elif r["saved"] == 0:
            msg = "Ninguno. «Lasciate ogne speranza»… pero inténtalo otra vez."
        else:
            msg = "Faltan almas. Virgilio no reprocha: espera."
        self.para(msg, self.f_it, 100, 110, 440, UI_FG, center=True)
        y = 140
        self.text(f"Peso: {r['peso0']} → {max(0, r['peso'])}", self.f_med, (LW / 2, y), UI_ACC, center=True)
        y += 14
        for n in r["notes"][:5]:
            self.text("· " + n, self.f_small, (LW / 2, y), (230, 200, 170), center=True)
            y += 11
        if r["maestro"]:
            self.text("El Maestro Lapo ha llegado vivo.", self.f_small, (LW / 2, y), (200, 180, 220), center=True)
            y += 11
        if r["verse"]:
            v, cite = r["verse"]
            y += 6
            self.text("Pagina salvata", self.f_small, (LW / 2, y), GOLD, center=True)
            y = self.para(v, self.f_it, 110, y + 12, 420, PARCH, center=True)
            self.text(cite, self.f_tiny, (LW / 2, y + 1), UI_DIM, center=True)
        nxt = "el final" if r["ending"] else "siguiente" if r["ok"] and not r["demo"] else "reintentar"
        line = f"Enter: {nxt} · R: repetir · Esc: mapa" + ("" if r["demo"] else " · S: guardar repetición")
        self.text(line, self.f_small, (LW / 2, 312), UI_DIM, center=True)
        if r["saved_file"]:
            self.text(f"Guardado: {r['saved_file']}", self.f_tiny, (LW / 2, 324), UI_DIM, center=True)

    # ── finales ──────────────────────────────────────────────────────────
    def on_ending(self, ev):
        if ev.type == pygame.KEYDOWN or (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1):
            if self.ending and self.ending["t"] > 120:
                if self.ending["kind"] == "giorni":  # la procesión vuelve a empezar
                    self.sel = 0
                    self.open_level(0)
                else:
                    self.mode = "title"
        return None

    def draw_ending(self) -> None:
        e = self.ending
        assert e is not None
        e["t"] += 1
        t = e["t"]
        kind = e["kind"]
        v = self.view
        if kind == "rosa":
            self.sfx.music("paradiso")
            v.fill((255, 252, 240))
            cx, cy = VIEW_W // 2, VIEW_H // 2
            for ring in range(12):
                for k in range(16 + ring * 3):
                    ang = k / (16 + ring * 3) * math.tau + t * 0.002 * (1 + ring % 3)
                    r = 10 + ring * 14
                    c = (255, 240 - ring * 6, 200 - ring * 10)
                    pygame.draw.circle(v, c, (int(cx + r * math.cos(ang)), int(cy + r * math.sin(ang) * 0.6)), 5 - ring // 4)
            glow = light_sprite(80, (255, 250, 220))
            v.blit(glow, (cx - 80, cy - 80), special_flags=pygame.BLEND_ADD)
        elif kind == "limbo":
            self.sfx.music("limbo")
            if not hasattr(self, "_limbo_bg"):
                self._limbo_bg = Backdrop(VIEW_W, THEMES["limbo"], "", 5)
            self._limbo_bg.draw(v, 0, 0)
            v.fill((70, 70, 80), (0, VIEW_H - 40, VIEW_W, 40))
        else:
            self.sfx.music("inferno")
            self.title_scene.draw(v, self.frame)
        self.blit_full()
        title, lines = ENDINGS[kind]
        a = min(255, t * 2)
        col = INK if kind == "rosa" else UI_FG
        self.text(title, self.f_title, (LW / 2, 30), col if kind != "rosa" else (140, 100, 40), center=True, alpha=a, shadow=kind != "rosa")
        for k, line in enumerate(lines):
            aa = max(0, min(255, (t - 60 - k * 90) * 3))
            if aa:
                self.text(line, self.f_it, (LW / 2, 260 + k * 16), col, center=True, alpha=aa, shadow=kind != "rosa")
        pct = self.save.pct() or 0
        if t > 360:
            self.text(f"Almas salvadas en la Commedia: {pct:.0f} %  ·  Pagine: {len(self.save.data['pagine'])}/101",
                      self.f_small, (LW / 2, 340), col, center=True, shadow=kind != "rosa")

    # ── pagine y códice ──────────────────────────────────────────────────
    def on_pagine(self, ev):
        if ev.type == pygame.KEYDOWN or (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3):
            if getattr(ev, "key", None) in (pygame.K_ESCAPE, pygame.K_RETURN, None):
                self.mode = "title"
        return None

    def draw_pagine(self) -> None:
        bg = cached_gradient(LW * self.s, LH * self.s, (40, 30, 24), (18, 12, 10))
        self.screen.blit(bg, (0, 0))
        got = sorted(self.save.data["pagine"])
        self.text("PAGINE SALVATE", self.f_title, (LW / 2, 8), GOLD, center=True)
        self.text(f"{len(got)} de 101 — Dante y Boccaccio, rescatados de la hoguera", self.f_small, (LW / 2, 34), UI_DIM, center=True)
        for i in range(N_LEVELS):
            x = 20 + (i % 26) * 23
            y = 52 + (i // 26) * 20
            col = PARCH if i in got else (60, 50, 44)
            pygame.draw.rect(self.screen, col, self.R(x, y, 16, 14))
            self.text(str(i), self.f_tiny, (x + 8, y + 2), INK if i in got else (100, 90, 80), center=True, shadow=False)
        mx, my = pygame.mouse.get_pos()
        mx, my = mx / self.s, my / self.s
        hov = None
        for i in range(N_LEVELS):
            x = 20 + (i % 26) * 23
            y = 52 + (i // 26) * 20
            if x <= mx < x + 16 and y <= my < y + 14:
                hov = i
        show = hov if hov is not None and hov in got else (got[-1] if got else None)
        self.panel(60, 140, 520, 180, 200)
        if show is None:
            self.para("Aún no hay pagine. Están escondidas en cada nivel, sobre el camino: deja que un disciplinato pase por encima.",
                      self.f_it, 80, 200, 480, UI_FG, center=True)
        else:
            v, cite = verse_of(show)
            self.text(f"Nivel {show} · {get_level(show).place}", self.f_small, (LW / 2, 150), UI_ACC, center=True)
            y = 180
            for part in v.split(" / "):
                self.text(part, self.f_it, (LW / 2, y), PARCH, center=True)
                y += 16
            self.text(cite, self.f_small, (LW / 2, y + 6), UI_DIM, center=True)
        self.text("Esc: volver", self.f_tiny, (LW / 2, 346), UI_DIM, center=True)

    def on_codex(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                self.mode = "title"
            elif ev.key == pygame.K_DOWN:
                self.scroll = min(len(CODEX) - 1, self.scroll + 1)
            elif ev.key == pygame.K_UP:
                self.scroll = max(0, self.scroll - 1)
        elif ev.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, min(len(CODEX) - 1, self.scroll - ev.y))
        return None

    def draw_codex(self) -> None:
        bg = cached_gradient(LW * self.s, LH * self.s, (30, 24, 20), (12, 8, 8))
        self.screen.blit(bg, (0, 0))
        self.text("CÓDICE — dónde termina la historia", self.f_title, (LW / 2, 8), GOLD, center=True)
        self.text("Un juego que se alimenta de la historia le debe al jugador saber qué es dato, qué es tesis y qué es licencia.",
                  self.f_small, (LW / 2, 34), UI_DIM, center=True)
        y = 54
        tag_col = {"dato": UI_OK, "tesis": (240, 200, 120), "licencia": (230, 140, 200)}
        for name, desc, tag in CODEX[self.scroll :]:
            if y > 330:
                break
            col = next((c for k, c in tag_col.items() if tag.startswith(k)), (200, 200, 230))
            self.text(name, self.f_med, (24, y), UI_ACC)
            self.text(f"[{tag}]", self.f_small, (616, y + 1), col, right=True)
            y = self.para(desc, self.f_small, 40, y + 13, 560, UI_FG) + 6
        self.text("↑↓ desplazar · Esc volver", self.f_tiny, (LW / 2, 348), UI_DIM, center=True)


PAD_EVENTS = {getattr(pygame, n) for n in ("CONTROLLERDEVICEADDED", "CONTROLLERAXISMOTION", "CONTROLLERBUTTONDOWN",
                                            "CONTROLLERBUTTONUP") if hasattr(pygame, n)}


def p_marks(i: int) -> int | None:
    """Las siete P que el Ángel graba en la frente: cada cornisa borra una."""
    if not 41 <= i <= 67:
        return None
    cornici = [(42, 45), (46, 48), (49, 51), (52, 54), (55, 57), (58, 60), (61, 63)]
    done = sum(1 for lo, hi in cornici if i > hi)
    return max(0, 7 - done)


ACHIEVEMENTS = {
    "primo": ("Primo passo", "Sacar a la Compagnia de Florencia, 1348."),
    "michelangelo": ("Il bambino", "Salvar al niño huérfano de la peste."),
    "tutti": ("Nessuno perduto", "Salvar a las 100 almas de un nivel."),
    "riveder": ("A riveder le stelle", "Salir del Infierno por la natural burella."),
    "leggero": ("Puro e disposto", "Terminar el Purgatorio con Peso 0."),
    "palle": ("Palle, palle, palle!", "Coger tres palle en diez segundos."),
    "medico": ("Cosme y Damián", "Curar a 30 almas en un nivel."),
    "dioneo": ("Il privilegio", "Usar el Privilegio de Dioneo."),
    "dies": ("Dies irae", "Rendirse con el botón humillante."),
    "maestro": ("Il Maestro arriva", "Que el Maestro llegue vivo a una salida."),
    "pagine10": ("Dieci pagine", "Salvar diez pagine de la hoguera."),
    "pagine101": ("La biblioteca", "Salvar las 101 pagine."),
    "stelle": ("Dieci volte tre", "Tres estrellas en diez niveles."),
    "giudizio": ("Giudizio del giorno", "Superar un desafío diario."),
    "infinito": ("Senza fine", "Superar cinco círculos seguidos en Infinito."),
    "rosa": ("La candida rosa", "Ver el final I."),
    "limbo": ("Il nobile castello", "Ver el final II."),
    "giorni": ("Trentatré giorni e mezzo", "Ver el final III."),
}


def level_stars(saved: int, need: int, total: int) -> int:
    """★ superado · ★★ a medio camino entre el mínimo y todos · ★★★ ni una sola alma perdida."""
    if saved < need:
        return 0
    if saved >= total:
        return 3
    return 2 if saved >= (need + total) / 2 else 1


def roman(n: int) -> str:
    vals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, r in vals:
        while n >= v:
            out += r
            n -= v
    return out


def draw_villa(view: pygame.Surface, frame: int, gi: int, sprites: Sprites, limbo: bool = False) -> None:
    """La villa de Fiesole: diez jóvenes en un jardín, lejos de la peste."""
    sky = vertical_gradient(VIEW_W, VIEW_H, (110, 150, 200) if not limbo else (60, 60, 80), (250, 220, 180) if not limbo else (130, 130, 140))
    view.blit(sky, (0, 0))
    rng = random.Random(gi)
    for k in range(4):  # colinas
        prof = ridge(rng, VIEW_W, 170 + k * 22, 18, 0.5)
        col = (90 - k * 10, 120 - k * 6, 70 - k * 8) if not limbo else (80 - k * 8,) * 3
        pygame.draw.polygon(view, col, [(0, VIEW_H)] + [(x, int(prof[x])) for x in range(VIEW_W)] + [(VIEW_W - 1, VIEW_H)])
    for x in range(20, VIEW_W, 46):  # cipreses
        h = 50 + (x * 7) % 30
        pygame.draw.ellipse(view, (30, 50, 30) if not limbo else (50, 50, 56), (x, 200 - h, 12, h + 10))
    # Florencia humeando a lo lejos
    pygame.draw.ellipse(view, (120, 90, 90), (470, 150, 30, 26))
    for k in range(6):
        y = 150 - k * 12 - (frame // 4) % 12
        pygame.draw.circle(view, (90, 80, 80), (485 + int(6 * math.sin(k + frame * 0.01)), y), 6 + k)
    # fuente
    pygame.draw.ellipse(view, (200, 200, 190), (290, 214, 60, 14))
    pygame.draw.rect(view, (200, 200, 190), (316, 196, 8, 22))
    for k in range(8):
        a = frame * 0.1 + k
        pygame.draw.circle(view, (180, 210, 255), (320 + int(14 * math.sin(a)), 196 - abs(int(8 * math.cos(a)))), 1)
    pygame.draw.rect(view, (120, 150, 80) if not limbo else (90, 90, 90), (0, 226, VIEW_W, VIEW_H - 226))
    colors = [(200, 60, 60), (60, 90, 180), (220, 190, 80), (70, 140, 90), (180, 80, 160), (230, 230, 230),
              (200, 120, 50), (90, 60, 140), (150, 200, 220), (120, 60, 40)]
    for k, name in enumerate(BRIGATA):
        ang = math.pi * (0.1 + 0.8 * k / 9)
        x = int(320 - 230 * math.cos(ang))
        y = int(236 + 24 * math.sin(ang))
        c = colors[k]
        pygame.draw.polygon(view, c, [(x - 5, y), (x + 5, y), (x + 2, y - 12), (x - 2, y - 12)])
        pygame.draw.circle(view, (230, 190, 150), (x, y - 15), 3)
        if k == gi:  # corona de laurel
            pygame.draw.arc(view, (60, 160, 60), (x - 4, y - 21, 8, 6), 0, math.pi, 2)
        if (frame // 30 + k) % 10 == 0:
            pygame.draw.line(view, (255, 255, 255), (x + 4, y - 18), (x + 8, y - 22))


class TitleScene:
    """La puerta del Infierno, la procesión con velas y las brasas."""

    def __init__(self, sprites: Sprites):
        self.sp = sprites
        th = THEMES["inferno"]
        self.back = Backdrop(VIEW_W, th, "", 3)
        self.atmo = Atmosphere("embers", 1)
        self.light = pygame.Surface((VIEW_W // 2, VIEW_H // 2))
        self.glow = pygame.Surface((VIEW_W // 4, VIEW_H // 4))
        self.vig = Renderer._vignette()
        ground = pygame.Surface((VIEW_W, 60), pygame.SRCALPHA)
        rng = np.random.default_rng(2)
        k = np.zeros((60, VIEW_W), dtype=np.uint8)
        k[6:, :] = DIRT
        col, _ = colorize(k, th, rng)
        rgb, al = shade_region(k, col, th.rim)
        px = pygame.surfarray.pixels3d(ground)
        px[:] = rgb.transpose(1, 0, 2)
        del px
        pa = pygame.surfarray.pixels_alpha(ground)
        pa[:] = al.T
        del pa
        self.ground = ground

    def draw(self, v: pygame.Surface, frame: int) -> None:
        self.back.draw(v, 0, 0)
        g = self.glow
        g.fill((0, 0, 0))
        gy = VIEW_H - 54
        v.blit(self.ground, (0, gy))
        # la puerta
        cx = VIEW_W // 2
        pygame.draw.rect(v, (40, 30, 30), (cx - 70, gy - 120, 140, 126))
        pygame.draw.rect(v, (6, 2, 4), (cx - 46, gy - 96, 92, 102))
        pygame.draw.circle(v, (6, 2, 4), (cx, gy - 96), 46, draw_top_left=True, draw_top_right=True)
        pygame.draw.rect(v, (70, 56, 50), (cx - 70, gy - 132, 140, 14))
        inner = pygame.Surface((80, 90))
        inner.fill((80, 20, 6))
        v.blit(inner, (cx - 40, gy - 84), special_flags=pygame.BLEND_ADD)
        g.blit(light_sprite(16, (180, 60, 20)), (cx // 4 - 16, (gy - 50) // 4 - 16), special_flags=pygame.BLEND_ADD)
        # procesión
        lights = []
        n = 14
        for k in range(n):
            x = int((frame * 0.35 + k * 26) % (VIEW_W + 60)) - 30
            y = gy + 6
            img = self.sp.get("whip" if (frame // 12 + k) % 7 == 0 else "walk", frame // 6 + k, 1, "m" if k == n - 1 else "w")
            v.blit(img, (x - 5, y - 13))
            lights.append((x, y - 8))
        self.atmo.update()
        self.atmo.draw(v, g, 0)
        L = self.light
        L.fill((60, 34, 36))
        L.blit(light_sprite(70, (220, 120, 60)), (cx // 2 - 70, (gy - 50) // 2 - 70), special_flags=pygame.BLEND_ADD)
        for x, y in lights:
            L.blit(light_sprite(14, (170, 120, 70)), (x // 2 - 14, y // 2 - 14), special_flags=pygame.BLEND_ADD)
        for gx, gyy, gr, gc in self.back.glows:
            L.blit(light_sprite(gr // 2, tuple(c // 3 for c in gc)), (gx // 2 - gr // 2, gyy // 2 - gr // 2), special_flags=pygame.BLEND_ADD)
        v.blit(pygame.transform.smoothscale(L, (VIEW_W, VIEW_H)), (0, 0), special_flags=pygame.BLEND_MULT)
        for x, y in lights:
            g.fill((60, 40, 20), (x // 4, y // 4, 1, 1), special_flags=pygame.BLEND_ADD)
        v.blit(pygame.transform.smoothscale(g, (VIEW_W, VIEW_H)), (0, 0), special_flags=pygame.BLEND_ADD)
        wide = pygame.transform.smoothscale(pygame.transform.smoothscale(g, (VIEW_W // 16, VIEW_H // 16)), (VIEW_W, VIEW_H))
        v.blit(wide, (0, 0), special_flags=pygame.BLEND_ADD)
        v.blit(self.vig, (0, 0), special_flags=pygame.BLEND_MULT)


# ═══════════════════════════════════════════════════════════════════════════
# 10. SELFTEST Y CALIBRACIÓN (sin ventana)
# ═══════════════════════════════════════════════════════════════════════════


def _lab(width: int = 160, floor: int = 120, mods: frozenset[str] = frozenset()) -> World:
    """Mundo de laboratorio: suelo plano, sin entradas, oficios de sobra."""
    lv = Level(id=-1, name="lab", place="lab", canto="", cantica="inferno", giornata=0, difficulty="", total=0,
               to_save=0, rr=50, minutes=1, skills={s: 99 for s in SKILLS}, theme="inferno",
               map=tuple("." * (width // CELL) for _ in range(ROWS)), solution=(), mods=mods)
    w = World(lv, Campaign(maestro=False))
    w.terrain.k[:] = AIR
    w.terrain.k[floor:, :] = DIRT
    w.hatch = HATCH_TICKS
    w.released = 0
    return w


def _put(w: World, x: int, y: int, state: St = St.WALK, d: int = 1) -> Lemming:
    L = Lemming(len(w.lemmings), x, y, d, state)
    w._add(L)
    return L


def _run(w: World, n: int) -> None:
    for _ in range(n):
        w.tick()


def selftest(quick: bool = False) -> int:
    fails = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal fails
        print(f"  [{'ok' if cond else 'FALLO'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
        fails += not cond

    print("Física de la Compagnia:")
    for h, passes in ((6, True), (7, False)):
        w = _lab()
        w.terrain.k[120 - h : 120, 40:80] = DIRT
        L = _put(w, 30, 120)
        _run(w, 20)
        ok = (L.x > 40 and L.y == 120 - h) if passes else (L.dir == -1 and L.x < 40)
        check(f"escalón de {h} px {'se sube' if passes else 'es un muro'}", ok, f"x={L.x} y={L.y}")
    for drop, survives in ((60, True), (61, False)):
        w = _lab()
        L = _put(w, 50, 120 - drop, St.FALL)
        _run(w, 40)
        st = L.state if not L.removed else "muerto"
        check(f"caída de {drop} px {'se sobrevive' if survives else 'mata'}",
              (st == St.WALK) if survives else (st in (St.SPLAT, "muerto")), str(st))
    w = _lab()
    w.shield = ["giglio"]
    L = _put(w, 50, 40, St.FALL)
    _run(w, 60)
    check("el Giglio amortigua una caída mortal", not L.removed and L.state == St.WALK and L.grace, str(L.state))
    w = _lab()
    L = _put(w, 50, 120, St.FALL)
    L.floater = True
    w.terrain.k[120:, :] = AIR
    w.terrain.k[150:, :] = DIRT
    L.y = 40
    _run(w, 200)
    check("el Gerione sobrevive a 110 px", not L.removed and L.state == St.WALK, str(L.state))
    w = _lab(200)
    L = _put(w, 40, 120)
    w.assign(L.id, Skill.CAPOMASTRO)
    _run(w, BRICKS * BRICK_TICKS + 2)
    bricks = int((w.terrain.k[:120] != AIR).sum())
    check("el Capomastro pone 12 ladrillos de 6 px", bricks == BRICKS * 6, f"{bricks} px")
    check("y termina 12 px más alto", L.y == 120 - BRICKS, f"y={L.y}")
    w = _lab(200)
    w.terrain.k[104:120, 68:120] = DIRT  # cornisa de 2 bloques
    L = _put(w, 40, 120)
    w.assign(L.id, Skill.CAPOMASTRO)
    F = _put(w, 20, 120)
    up = False
    for _ in range(BRICKS * BRICK_TICKS + 400):
        w.tick()
        up |= F.y == 104 and F.x > 68
    check("la escalera llega a una cornisa de 16 px", up, f"x={F.x} y={F.y}")
    w = _lab()
    w.terrain.k[120:, :] = STEEL
    L = _put(w, 60, 120)
    w.assign(L.id, Skill.BUBBONE)
    _run(w, BOMB_TICKS + OHNO_TICKS + 5)
    check("la pietra serena resiste el bubón", int((w.terrain.k == STEEL).sum()) == (VIEW_H - 120) * 160 and L.removed)
    w = _lab()
    L = _put(w, 60, 120)
    w.assign(L.id, Skill.FLAGELLANTE)
    w.assign(L.id, Skill.BUBBONE)
    _run(w, BOMB_TICKS + OHNO_TICKS + 5)
    check("el bubón abre un cráter en la roca", w.terrain.k[121, 60] == AIR and w.terrain.k[121, 80] == DIRT)
    w = _lab()
    w.terrain.k[135:, :] = STEEL
    L = _put(w, 60, 120)
    w.assign(L.id, Skill.BECCHINO)
    _run(w, 200)
    check("el Becchino se para en la piedra", L.state == St.WALK and L.y == 135, f"{L.state} y={L.y}")
    w = _lab(200)
    w.terrain.k[90:120, 60:90] = DIRT
    L = _put(w, 55, 120)
    w.assign(L.id, Skill.PIAGNONE)
    _run(w, 120)
    check("el Piagnone atraviesa un muro", L.x > 90 and L.state == St.WALK, f"x={L.x} {L.state}")
    w = _lab()
    L = _put(w, 30, 120)
    w.assign(L.id, Skill.MINATORE)
    _run(w, MINE_TICKS * 10 + 1)
    check("el Minatore baja en diagonal 1:2", L.y == 130 and L.x == 50, f"x={L.x} y={L.y}")
    w = _lab()
    w.terrain.k[60:120, 70:80] = DIRT
    L = _put(w, 60, 120)
    L.climber = True
    crowned = False
    for _ in range(200):
        w.tick()
        crowned |= L.state == St.WALK and L.y == 60 and 70 <= L.x < 80
    check("el Pellegrino corona el muro", crowned, f"x={L.x} y={L.y} {L.state}")
    w = _lab()
    blk = _put(w, 60, 120)
    w.assign(blk.id, Skill.FLAGELLANTE)
    L = _put(w, 40, 120)
    _run(w, 30)
    check("el Flagellante da media vuelta a los demás", L.dir == -1 and L.x < 60, f"x={L.x}")
    w = _lab(mods=frozenset({"paradiso"}))
    blk = _put(w, 60, 120)
    w.assign(blk.id, Skill.FLAGELLANTE)
    L = _put(w, 40, 120)
    _run(w, 40)
    check("en el Paraíso el Flagellante ya no bloquea", L.x > 60, f"x={L.x}")

    print("Moria, palle y guardianes:")
    w = _lab()
    sick = _put(w, 60, 120)
    sick.moria = 2
    sick.state = St.BLOCK
    others = [_put(w, 56 + k, 120) for k in range(6)]
    for o in others:
        o.state = St.BLOCK
    _run(w, 400)
    check("el Flagellante enfermo contagia a su alrededor", sum(o.moria > 0 for o in others) >= 3,
          str([o.moria for o in others]))
    w.shield = ["medicinale"]
    check("la Palla Medicinale cura", w.do(("palla", 0, 60, 114)) and all(o.moria == 0 for o in others))
    check("y suma 1 de Peso", w.peso == 1, str(w.peso))
    w = _lab()
    g = Guardian("caronte", 100, 120)
    w.guards.append(g)
    L = _put(w, 60, 120)
    _run(w, 80)
    check("Caronte no deja pasar", L.x < 100, f"x={L.x}")
    w.shield = ["cambio"]
    check("el óbolo lo aplaca", w.do(("palla", 0, 100, 110)) and g.pacified)
    _run(w, 120)
    check("y la fila pasa", L.x > 100 or L.dir == 1, f"x={L.x}")
    w = _lab()
    g = Guardian("angelo", 100, 120)
    w.guards.append(g)
    w.shield = ["cambio"]
    w.do(("palla", 0, 100, 110))
    check("la gracia no se compra: +7 de Peso y el Ángel quieto", w.peso == 7 and not g.pacified, f"peso={w.peso}")
    w = _lab()
    for k in range(3):
        w.pickups.append(Pickup("medicinale", 70 + 10 * k, 120))
    L = _put(w, 60, 120)
    _run(w, 60)
    check("tres palle en diez segundos: «Palle, palle, palle!»", w.combo > 0 and len(w.shield) == 3)

    w = _lab()
    doc = _put(w, 40, 120)
    sick = [_put(w, 60 + k * 3, 120) for k in range(4)]
    for o in sick:
        o.moria = 2
        o.state = St.BLOCK
    w.foco_test = w.focos.append((70, 120))
    check("el Medico acepta el oficio", w.assign(doc.id, Skill.MEDICO) and doc.medico)
    _run(w, 60)
    check("el Medico cura la Moria y apaga los focos a su paso",
          all(o.moria == 0 and o.immune > 0 for o in sick) and not w.focos, str([o.moria for o in sick]))

    print("Gravedad, gigantes y fuego:")
    w = _lab()
    w.terrain.k[:60, :] = DIRT  # techo
    w.hazard[100:120, 70:72] = HZ_FLIP
    L = _put(w, 60, 120)
    flipped = False
    for _ in range(80):
        w.tick()
        flipped |= L.inv and L.state == St.WALK
    check("en el centro de la Tierra la gravedad se invierte", flipped and w.ry(L) == 59, f"inv={L.inv} y={w.ry(L)}")
    w = _lab()
    w.terrain.k[:] = AIR
    w.terrain.k[60:, :80] = DIRT
    w.terrain.k[140:, 80:] = DIRT
    w.anteo = [(79, 60)]
    L = _put(w, 60, 60)
    _run(w, 80)
    check("Anteo baja al alma al fondo del pozo", not L.removed and L.y == 140 and L.state == St.WALK, f"{L.state} y={L.y}")
    w = _lab(mods=frozenset({"firerain"}))
    w.shield = ["mecenate"]
    w.art_queue = ["brunelleschi"]
    w.do(("palla", 0, 80, 110))
    check("Brunelleschi levanta una cúpula sobre el arenal", w.canopies == 1 and w.terrain.k[120 - 30, 80] == DIRT)
    w = _lab(mods=frozenset({"blink"}))
    w.phantoms.append({"r": (40, 100, 80, 104), "kind": "blink", "on": False, "mask": None})
    _run(w, 2)
    on = w.terrain.k[101, 50] == DIRT
    _run(w, BLINK_ON + 2)
    check("las promesas de la Luna aparecen y desaparecen", on and w.terrain.k[101, 50] == AIR)
    w = _lab(mods=frozenset({"paradiso"}))
    blk = _put(w, 60, 120)
    w.assign(blk.id, Skill.FLAGELLANTE)
    w.skills[Skill.PIAGNONE] = 0
    check("en el Paraíso al Flagellante se le convence de seguir", w.assign(blk.id, Skill.PIAGNONE) and blk.state == St.WALK)

    w = _lab()
    w.infinite = True
    w.skills = {s: 0 for s in SKILLS}
    a, b = _put(w, 40, 120), _put(w, 80, 120)
    check("con oficios infinitos no se gastan", w.assign(a.id, Skill.CAPOMASTRO) and w.assign(b.id, Skill.CAPOMASTRO)
          and w.skills[Skill.CAPOMASTRO] == 0)

    print("Subtítulos y formato de nivel:")
    lines = [g[3] for g in GUARDS.values()] + SAVONAROLA + [s[1] for s in SABIOS]
    missing = [t for t in lines if t not in TR]
    check("todas las voces tienen subtítulo en inglés e italiano", not missing, str(missing[:2]))
    check("el italiano se lee como se escribe", it_phonemes("gli occhi sciagurati") == ["L", "i", "|", "o", "k:", "i", "|", "S", "a", "g", "u", "r", "a", "t", "i"],
          str(it_phonemes("gli occhi sciagurati")))
    lv = get_level(33)
    back = level_from_json(json.loads(json.dumps(level_to_json(lv))), 1001)
    CUSTOM[1001] = back
    w1, _ = simulate(33, Autopilot(lv.solution))
    w2, _ = simulate(1001, Autopilot(back.solution))
    CUSTOM.pop(1001)
    check("un nivel exportado a JSON y vuelto a leer se juega igual", (w1.saved, w1.tick_count) == (w2.saved, w2.tick_count),
          f"{w1.saved}/{w1.tick_count} vs {w2.saved}/{w2.tick_count}")

    print("Rebobinado y niveles generados:")
    lv = get_level(13)
    wa = World(lv)
    pa = Autopilot(lv.solution)
    log: list = []

    def ap(cmd, w=wa):
        ok = w.do(cmd)
        if ok:
            log.append([w.tick_count, *cmd])
        return ok
    for _ in range(600):
        pa.step(wa, ap)
        wa.tick()
    snap = wa.snapshot()
    for _ in range(900):
        pa.step(wa, ap)
        wa.tick()
    wb = World.thaw(snap)
    rest = Replay([c for c in log if c[0] >= 600])
    for _ in range(900):
        rest.step(wb, wb.do)
        wb.tick()
    check("rebobinar y rehacer da la misma partida", (wa.saved, wa.dead, int(wa.tn.k.sum())) == (wb.saved, wb.dead, int(wb.tn.k.sum())),
          f"{wa.saved}/{wa.dead} vs {wb.saved}/{wb.dead}")
    check("el marco del revés sobrevive al rebobinado", wb.ti.k.base is not None and wb.ti.k[0, 0] == wb.tn.k[-1, 0])
    v = make_variant(DAILY_ID, 12345, "prueba")
    wv, _ = simulate(DAILY_ID, Autopilot(v.solution))
    CUSTOM.pop(DAILY_ID, None)
    check("un Giudizio del giorno se puede resolver", wv.saved >= v.to_save, f"{wv.saved}/{v.to_save}")
    check("las estrellas: ★ mínimo, ★★ a medio camino, ★★★ todas",
          (level_stars(50, 60, 100), level_stars(60, 60, 100), level_stars(85, 60, 100), level_stars(100, 60, 100)) == (0, 1, 2, 3))

    print("La Commedia (solución de referencia en cada nivel):")
    idxs = range(N_LEVELS) if not quick else range(0, N_LEVELS, 10)
    for i in idxs:
        lv = get_level(i)
        widths = {len(r) for r in lv.map}
        w, log = simulate(i, Autopilot(lv.solution))
        wh, _ = simulate(i, Autopilot(lv.solution), Campaign(HEAVY.peso, list(HEAVY.shield), False))
        check(f"{i:3d}. {lv.place[:34]:34s} {w.saved:3d}/{wh.saved:3d}/{lv.total} (mín. {lv.to_save})",
              w.success and wh.success and len(widths) == 1 and len(lv.map) == ROWS, f"anchos {sorted(widths)}, ticks {w.tick_count}")
        if i % 10 == 0:
            w2, _ = simulate(i, Replay(log))
            check("      la repetición reproduce la partida", (w2.saved, w2.dead, w2.tick_count) == (w.saved, w.dead, w.tick_count),
                  f"{w2.saved}/{w2.dead}/{w2.tick_count} vs {w.saved}/{w.dead}/{w.tick_count}")
    print("Todo bien." if not fails else f"{fails} fallo(s).")
    return 1 if fails else 0


HEAVY = Campaign(peso=30, shield=["congiura", "mecenate", "mecenate", "cambio", "cambio", "arancia", "arancia", "medicinale"],
                 maestro=False)


def calibrate() -> int:
    """Almas que salva la solución de referencia, en el peor de dos casos: una Compagnia
    ligera (sin Peso ni palle) y una cargada (Peso 30, escudo lleno)."""
    out = {}
    for i in range(N_LEVELS):
        lv = get_level(i)
        light, _ = simulate(i, Autopilot(lv.solution))
        heavy, _ = simulate(i, Autopilot(lv.solution), Campaign(HEAVY.peso, list(HEAVY.shield), False))
        out[i] = min(light.saved, heavy.saved)
        print(f"{i:3d} {lv.place[:30]:30s} {light.saved}/{heavy.saved}/{lv.total}", file=sys.stderr)
    items = ", ".join(f"{k}: {v}" for k, v in out.items())
    print("CALIBRATION: dict[int, int] = {" + items + "}")
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# Formato de nivel (§20 del diseño): exportar e importar JSON
# ═══════════════════════════════════════════════════════════════════════════


def level_to_json(lv: Level) -> dict:
    _, _, ents, exs = parse_map(lv.map)
    rule = lambda r: {k: (str(v) if isinstance(v, StrEnum) else list(v) if isinstance(v, tuple) else v)  # noqa: E731
                      for k, v in ((f, getattr(r, f)) for f in Rule.__slots__) if v != getattr(Rule(None), k)}
    return {
        "id": lv.id, "name": lv.name, "place": lv.place, "cantica": lv.cantica, "canto": lv.canto,
        "giornata": lv.giornata + 1, "difficulty": lv.difficulty.lower(), "seed": 1348 + lv.id, "theme": lv.theme,
        "physics": {"gravity": "up" if "lux" in lv.mods else "flip" if lv.special == "lucifero" else "down"},
        "map": list(lv.map),
        "entrance": [{"x": e.x, "y": e.y, "dir": e.dir, "inv": e.inv} for e in ents],
        "count": lv.total, "release_rate": lv.rr, "exits": [{"x": e.x, "y": e.y, "inv": e.inv} for e in exs],
        "save_required": lv.to_save, "save_required_pct": round(100 * lv.to_save / max(1, lv.total)),
        "time_days": DAYS, "minutes": lv.minutes,
        "skills": {s.value: n for s, n in lv.skills.items()},
        "palle": [{"type": p.kind, "x": p.x, "y": p.y, "artist": p.artist, "need": p.need, "inv": p.inv} for p in lv.pickups],
        "guards": [{"type": g.kind, "x": g.x, "y": g.y, "inv": g.inv} for g in lv.guards],
        "hazards": {"vents": [list(v) for v in lv.vents], "boulders": [list(b) for b in lv.boulders],
                    "boats": [list(b) for b in lv.boats], "rising_fire": list(lv.fire) if lv.fire else None,
                    "phantoms": [list(p) for p in lv.phantoms]},
        "mods": sorted(lv.mods), "special": lv.special, "sky": lv.sky,
        "moria": {"initial_infected": lv.moria[0], "rats": lv.moria[1]},
        "hint": lv.hint, "sermon": lv.sermon, "guide": lv.guide,
        "reference_solution": [rule(r) for r in lv.solution],
    }


def level_from_json(d: dict, lid: int = 1000) -> Level:
    """Lee un nivel en el formato del diseño. Solo «map» es obligatorio."""
    rows = tuple(d["map"])
    if len({len(r) for r in rows}) != 1:
        raise ValueError("todas las filas del mapa deben medir lo mismo")
    rows = tuple("." * len(rows[0]) for _ in range(max(0, ROWS - len(rows)))) + rows[:ROWS]
    cantica = d.get("cantica", "inferno")
    if cantica not in CANTICHE:
        cantica = "inferno"
    total = int(d.get("count", 20))
    skills = {s: int(d.get("skills", {}).get(s.value, 0)) for s in SKILLS}

    def rule(r: dict) -> Rule:
        kw = {"skill": None, **r}
        if kw.get("skill"):
            kw["skill"] = Skill(kw["skill"])
        if kw.get("state"):
            kw["state"] = St(kw["state"])
        if "y" in kw:
            kw["y"] = tuple(kw["y"])
        return Rule(**{k: v for k, v in kw.items() if k in Rule.__slots__})

    hz = d.get("hazards", {}) or {}
    fire = hz.get("rising_fire")
    gi = max(0, min(9, int(d.get("giornata", 1)) - 1))
    theme = d.get("theme", {"inferno": "inferno", "purgatorio": "monte", "paradiso": "paradiso"}.get(cantica, "inferno"))
    return Level(
        id=lid, name=d.get("name", "Nivel propio"), place=d.get("place", d.get("name", "Nivel propio")),
        canto=d.get("canto", ""), cantica=cantica, giornata=gi, difficulty=str(d.get("difficulty", "pellegrino")).capitalize(),
        total=total, to_save=int(d.get("save_required", math.ceil(total * d.get("save_required_pct", 50) / 100))),
        rr=int(d.get("release_rate", 50)), minutes=int(d.get("minutes", max(1, round(d.get("time_days", DAYS) / DAYS * 5)))),
        skills=skills, theme=theme if theme in THEMES else "inferno", map=rows,
        solution=tuple(rule(r) for r in d.get("reference_solution", [])),
        pickups=tuple(PickSpec(p["type"], int(p["x"]), int(p["y"]), p.get("artist", ""), bool(p.get("need")), bool(p.get("inv")))
                      for p in d.get("palle", [])),
        guards=tuple(GuardSpec(g["type"], int(g["x"]), int(g["y"]), bool(g.get("inv"))) for g in d.get("guards", [])),
        vents=tuple(tuple(v) for v in hz.get("vents", [])), boulders=tuple(tuple(b) for b in hz.get("boulders", [])),
        boats=tuple(tuple(b) for b in hz.get("boats", [])), fire=tuple(fire) if fire else None,
        phantoms=tuple(tuple(p) for p in hz.get("phantoms", [])),
        mods=frozenset(d.get("mods", [])), special=d.get("special", ""), sky=d.get("sky", ""),
        moria=(int(d.get("moria", {}).get("initial_infected", 0)), bool(d.get("moria", {}).get("rats", False))),
        hint=d.get("hint", ""), sermon=d.get("sermon", SERMONS[0]), guide=d.get("guide", "Virgilio"),
    )


def export_levels(folder: str) -> int:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for i in range(N_LEVELS):
        (out / f"{i:03d}.json").write_text(json.dumps(level_to_json(get_level(i)), ensure_ascii=False, indent=1))
    print(f"{N_LEVELS} niveles exportados a {out}/")
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# 11. BUCLE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pydanteshell", description="Dante's Hell — Disciplinati. Lemmings en la Divina Comedia.")
    ap.add_argument("--level", type=int, choices=range(N_LEVELS), metavar="N", help="ir al nivel N (0–100)")
    ap.add_argument("--scale", type=int, default=0, help="escala de la ventana (por defecto, la mayor que quepa)")
    ap.add_argument("--fullscreen", action="store_true", help="pantalla completa")
    ap.add_argument("--selftest", action="store_true", help="probar física, palle y los 101 niveles sin ventana")
    ap.add_argument("--quick", action="store_true", help="con --selftest: solo uno de cada diez niveles")
    ap.add_argument("--calibrate", action="store_true", help="medir cuántas almas salva cada solución de referencia")
    ap.add_argument("--replay", metavar="FICHERO", help="reproducir una partida grabada")
    ap.add_argument("--demo", type=int, choices=range(N_LEVELS), metavar="N", help="ver la solución del nivel N")
    ap.add_argument("--mute", action="store_true", help="sin sonido")
    ap.add_argument("--lowfx", action="store_true", help="sin bloom ni grano (equipos modestos)")
    ap.add_argument("--all", action="store_true", help="desbloquear toda la Commedia")
    ap.add_argument("--export-levels", metavar="CARPETA", help="escribir los 101 niveles en JSON (formato del diseño)")
    ap.add_argument("--custom", metavar="NIVEL.json", help="jugar un nivel propio en JSON")
    ap.add_argument("--daily", action="store_true", help="jugar el Giudizio del giorno")
    ap.add_argument("--endless", action="store_true", help="modo Infinito")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(args.quick)
    if args.calibrate:
        return calibrate()
    if args.export_levels:
        return export_levels(args.export_levels)
    if args.custom:
        CUSTOM[1000] = level_from_json(json.loads(Path(args.custom).read_text()))
        args.level = None
        app = App(args)
        app.open_preview(1000)
        app.run()
        pygame.quit()
        return 0
    app = App(args)
    if args.daily:
        app.start_daily()
    elif args.endless:
        app.endless = {"n": 0, "seed": random.randrange(10**9)}
        app.next_endless()
    app.run()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
