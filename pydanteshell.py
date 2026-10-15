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
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
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


def release_interval(rr: int) -> int:
    """Ticks entre disciplinati para una cadenza 1–99."""
    return max(5, round((53 - rr // 2) * TPS / 17))


# Terreno (un byte por píxel)
AIR, DIRT, STEEL, OW_L, OW_R = range(5)
# Peligros (mapa aparte, no sólidos)
HZ_NONE, HZ_LIQUID, HZ_FIRE, HZ_PURGE = range(4)


class Skill(StrEnum):
    PELLEGRINO = "pellegrino"
    GERIONE = "gerione"
    BUBBONE = "bubbone"
    FLAGELLANTE = "flagellante"
    CAPOMASTRO = "capomastro"
    PIAGNONE = "piagnone"
    MINATORE = "minatore"
    BECCHINO = "becchino"


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
}
SKILL_HELP = {
    Skill.PELLEGRINO: "Trepa muros con el bordón",
    Skill.GERIONE: "Desciende en espiral, como a lomos de Gerión",
    Skill.BUBBONE: "Cinco segundos y revienta: abre un cráter y contagia",
    Skill.FLAGELLANTE: "Se planta y se azota; los demás rebotan. Contagia",
    Skill.CAPOMASTRO: "Doce ladrillos de escalera, como Brunelleschi",
    Skill.PIAGNONE: "Abre túnel a golpes, como los de Savonarola",
    Skill.MINATORE: "Excava en diagonal, como en Malebolge",
    Skill.BECCHINO: "Cava en vertical; entierra focos de peste",
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
    St.WALK: "En procesión",
    St.FALL: "Cayendo",
    St.FLOAT: "Gerione",
    St.CLIMB: "Pellegrino",
    St.HOIST: "Pellegrino",
    St.BLOCK: "Flagellante",
    St.BUILD: "Capomastro",
    St.SHRUG: "Capomastro",
    St.BASH: "Piagnone",
    St.MINE: "Minatore",
    St.DIG: "Becchino",
    St.OHNO: "¡Bubbone!",
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
#   ^  fuego   %  fuego que purifica (Purgatorio VII)
#   E  pila bautismal (entrada)    X  salida


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


@dataclass(frozen=True, slots=True)
class PickSpec:
    kind: str  # palla roja, «giglio», «pagina» o «giunco»
    x: int
    y: int
    artist: str = ""
    need: bool = False  # la exige un guardián de este nivel


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


CANTICHE = {"proemio": "Proemio", "inferno": "Inferno", "purgatorio": "Purgatorio", "paradiso": "Paradiso"}
SLOTS = {"proemio": 8, "inferno": 8, "purgatorio": 7, "paradiso": 6}
SHIELD_OWNER = {"proemio": "Cosimo il Vecchio", "inferno": "Cosimo il Vecchio", "purgatorio": "Piero il Gottoso",
                "paradiso": "Lorenzo il Magnifico"}
DIFFICULTIES = ["Penitente", "Pellegrino", "Disciplinato", "Dannato"]

GUARDS = {
    # tipo: (nombre, qué palla lo aplaca, abre solo tras N s [0 = nunca], frase)
    "lupa": ("La lupa", "arancia", 0, "«...una lupa, che di tutte brame / sembiava carca». Distráela."),
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
        P.update(place="Selva oscura", canto="Inf. I", theme="selva", name="Nel mezzo del cammin", guards=["lupa"],
                 palette=["wall"])
    elif i <= 3:
        P.update(place="Antinferno", canto="Inf. III", theme="acheronte", name="Gli ignavi", palette=["wall", "dig", "drop_mine"])
    elif i == 4:
        P.update(place="Acheronte", canto="Inf. III", theme="acheronte", name="Caron dimonio", guards=["caronte"],
                 palette=["pit", "wall"])
    elif i == 5:
        P.update(place="I · Limbo", canto="Inf. IV", theme="limbo", name="Il nobile castello", palette=["wall", "dig"],
                 mods={"nodeath"})
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
                 guards=["flegias"] if i == 11 else [], palette=["pit", "wall", "drop_float"])
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
                 guards=["arpie"] if i == 19 else [], palette=["wall", "dig", "drop_float"])
    elif i == 21:
        P.update(place="VII · Sabbione ardente", canto="Inf. XIV–XVI", theme="inferno", name="La pioggia di fuoco",
                 palette=["wall", "pit", "drop_mine"], extra=["mecenate"], mods={"firerain"})
    elif i == 22:
        P.update(place="Discesa di Gerione", canto="Inf. XVII", theme="inferno", name="Gerione",
                 palette=["drop_float", "drop_float"])
    elif i <= 31:
        bolge = [
            ("Adulatori", "Inf. XVIII", set()), ("Simoniaci", "Inf. XIX", {"vents"}), ("Indovini", "Inf. XX", {"backwards"}),
            ("Barattieri", "Inf. XXI–XXII", set()), ("Ipocriti", "Inf. XXIII", {"slowskills"}),
            ("Ladri", "Inf. XXIV–XXV", set()), ("Consiglieri fraudolenti", "Inf. XXVI–XXVII", set()),
            ("Seminatori di discordia", "Inf. XXVIII", set()), ("Falsari", "Inf. XXIX–XXX", {"moria2"}),
        ]
        nm, canto, m = bolge[i - 23]
        P.update(place=f"VIII · Malebolge — {nm}", canto=canto, theme="malebolge", name=nm,
                 palette=["wall", "pit", "drop_mine", "dig", "drop_float"], mods={x for x in m if x != "vents"},
                 extra=["vents"] if "vents" in m else [], moria=(3, False) if "moria2" in m else (0, False),
                 special="flame" if nm == "Consiglieri fraudolenti" else "")
    elif i == 32:
        P.update(place="Pozzo dei Giganti", canto="Inf. XXXI", theme="malebolge", name="Anteo",
                 palette=["drop_mine", "drop_float"])
    elif i == 33:
        P.update(place="IX · Cocito — Antenora", canto="Inf. XXXII–XXXIII", theme="cocito", name="La ghiaccia",
                 palette=["pit", "wall", "dig"], special="toll")
    elif i == 34:
        P.update(place="Lucifero", canto="Inf. XXXIV", theme="cocito", name="Lo 'mperador del doloroso regno",
                 palette=["wall"], extra=["climb"], special="lucifero")
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
                 mods={"night", "stones"})
    elif i <= 48:
        P.update(place="II · Invidiosi", canto="Purg. XIII–XV", theme="monte", name="Gli occhi cuciti",
                 palette=["ascend", "wall", "climb_up"], mods={"night", "dark"})
    elif i <= 51:
        P.update(place="III · Iracondi", canto="Purg. XV–XVII", theme="monte", name="Il fumo", palette=["ascend", "wall", "climb_up"],
                 mods={"smoke"})
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
                 name=title, palette=["ascend", "climb_up", "wall"], sky=sky, guide=guide, guards=g)
        if sky == "saturno":
            P["mods"] = {"silence"}
            P["palette"] = ["climb_up", "ascend"]
        if sky == "mercurio":
            P["extra"] = ["temptation"]
        if sky == "primum":
            P["special"] = "primum"
        if sky == "visione":
            P["special"] = "final"
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
        self.guards.append(GuardSpec(kind, self.c * CELL + 4, self.fy * CELL))
        self.flat(5, spot=False)
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


def build_level(i: int) -> Level:
    P = place_info(i)
    rng = random.Random(1348 * 31 + i * 977)
    cantica = cantica_of(i)
    mods = set(P["mods"])
    if cantica == "paradiso" and P["special"] != "final":
        mods.add("paradiso")
    span = {"proemio": (0, 1), "inferno": (1, 34), "purgatorio": (35, 67), "paradiso": (68, 100)}[cantica]
    prog = (i - span[0]) / max(1, span[1] - span[0])
    tier = min(3, int(prog * 4))
    descending = cantica in ("proemio", "inferno")
    total = 100 if P["special"] == "final" else 20 + round(30 * (i / 100))
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
            if choice == "pit":
                if pits or "fast" in mods:
                    choice = "wall"
                pits += 1 if choice == "pit" else 0
            seq.append(choice)
    if P["special"] == "lucifero":
        seq = ["wall", "climb"]
    # presupuesto vertical
    drops = {"drop_float": 10, "drop_mine": 9, "dig": 6}
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
    mb = MapBuilder(fy, mods)
    mb.start()
    guards = list(P["guards"])
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
    return _assemble(i, P, mb, mods, total, cantica, tier, seq=seq, rng=rng)


def _assemble(i, P, mb: MapBuilder, mods, total, cantica, tier, rr=50, seq=(), rng=None) -> Level:
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
    if "fast" in mods:
        skills[Skill.FLAGELLANTE] = 0
    # Coleccionables: palle y la pagina del nivel
    pickups = list(mb.pickups)
    flats = [f for f in mb.flats if all(abs(f[0] - p.x) > 24 for p in pickups)]
    rng.shuffle(flats)
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
    if flats and P["special"] != "final":
        x, y = flats.pop()
        pickups.append(PickSpec("pagina", x, y))
    elif P["special"] == "final":
        pickups.append(PickSpec("pagina", 360, 30 * CELL))
    vault = cantica == "inferno" and not mb.climbers and P["theme"] not in ("limbo",)
    rows = mb.rows(random.Random(i * 13 + 1) if vault else None)
    width = len(rows[0]) * CELL
    walk_s = width / TPS
    minutes = math.ceil((walk_s * 1.6 + total * release_interval(rr) / TPS + 50 + 25 * len(mb.guards)
                         + (40 if "night" in mods else 0)) / 60) + (2 if "slowskills" in mods else 1)
    target = [50, 60, 70, 80][tier] if i else 40
    if P["special"] == "final":
        target = 1
    cal = CALIBRATION.get(i)
    need_n = math.ceil(total * target / 100)
    to_save = min(need_n, cal) if cal is not None else max(1, math.ceil(total * 0.4))
    fire = None
    if P["special"] == "rogo":
        fire = (55 * TPS, 0.10)
    hint_bits = [HINTS[s] for s in dict.fromkeys(seq) if s in HINTS][:2]
    if mb.guards:
        hint_bits.append(GUARDS[mb.guards[0].kind][3])
    guide = P["guide"]
    lines = GUIDE_LINES[guide]
    hint = " ".join(hint_bits) or lines[i % len(lines)]
    return Level(
        id=i, name=P["name"], place=P["place"], canto=P["canto"], cantica=cantica, giornata=giornata_of(i),
        difficulty=DIFFICULTIES[tier], total=total, to_save=to_save, rr=rr, minutes=minutes, skills=skills,
        theme=P["theme"], map=rows, solution=tuple(rules), pickups=tuple(pickups), guards=tuple(mb.guards),
        vents=tuple(mb.vents), boulders=tuple(mb.boulders), mods=frozenset(mods), moria=P["moria"], fire=fire,
        sermon=SERMONS[i % len(SERMONS)], hint=hint, sky=P["sky"], special=P["special"], guide=guide,
        target_pct=target,
    )


@dataclass(slots=True)
class Entrance:
    x: int
    y: int
    dir: int


@dataclass(slots=True)
class Exit:
    x: int
    y: int


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
                case "E" | "e":
                    entrances.append(Entrance(x0 + CELL // 2, y0 + CELL, 1 if ch == "E" else -1))
                case "X":
                    exits.append(Exit(x0 + CELL // 2, y0 + CELL))
    entrances.sort(key=lambda e: e.x)
    return kinds, hazard, entrances, exits


# Calibración: almas que salva la solución de referencia en cada nivel
# (python pydanteshell.py --calibrate). El mínimo exigido nunca la supera.
CALIBRATION: dict[int, int] = {0: 21, 1: 20, 2: 21, 3: 21, 4: 20, 5: 22, 6: 22, 7: 19, 8: 22, 9: 12, 10: 17, 11: 22, 12: 23, 13: 24, 14: 24, 15: 19, 16: 22, 17: 24, 18: 24, 19: 26, 20: 26, 21: 22, 22: 27, 23: 25, 24: 16, 25: 25, 26: 26, 27: 21, 28: 23, 29: 22, 30: 26, 31: 17, 32: 30, 33: 29, 34: 30, 35: 30, 36: 31, 37: 31, 38: 31, 39: 32, 40: 32, 41: 32, 42: 33, 43: 33, 44: 33, 45: 34, 46: 34, 47: 34, 48: 34, 49: 35, 50: 35, 51: 35, 52: 36, 53: 36, 54: 36, 55: 28, 56: 35, 57: 36, 58: 37, 59: 38, 60: 38, 61: 29, 62: 36, 63: 35, 64: 29, 65: 30, 66: 40, 67: 40, 68: 40, 69: 41, 70: 41, 71: 41, 72: 42, 73: 42, 74: 42, 75: 42, 76: 43, 77: 43, 78: 43, 79: 44, 80: 44, 81: 44, 82: 45, 83: 45, 84: 45, 85: 46, 86: 46, 87: 46, 88: 46, 89: 47, 90: 47, 91: 47, 92: 48, 93: 48, 94: 48, 95: 48, 96: 49, 97: 49, 98: 49, 99: 50, 100: 100}


@lru_cache(maxsize=None)
def get_level(i: int) -> Level:
    return build_level(i)


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


@dataclass(slots=True)
class Guardian:
    kind: str
    x: int
    y: int
    pacified: bool = False
    touched: bool = False
    timer: int = 0
    anim: int = 0

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

    def __init__(self, level: Level, camp: Campaign | None = None, seed: int = 1348):
        self.level = level
        camp = camp or Campaign()
        self.camp_in = camp
        kinds, hazard, self.entrances, self.exits = parse_map(level.map)
        rng = np.random.default_rng(seed + level.id)
        theme = THEMES[level.theme]
        self.theme = theme
        colors, emis = colorize(kinds, theme, rng)
        self.terrain = Terrain(kinds, colors, emis, theme.brick)
        self.hazard = hazard
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
            for s in SKILLS:
                if self.skills[s]:
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
        self.guards = [Guardian(g.kind, g.x, g.y) for g in level.guards]
        self.pickups = [Pickup(p.kind, p.x, p.y, p.artist, p.need) for p in level.pickups]
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
        if self.toll:
            self.say(f"El Cocito cobra la traición: {self.toll} alma(s) quedan presas en el hielo de la Antenora.", "Virgilio")
        if level.special == "bulla":
            self.say("Aviñón, 20 de octubre de 1349: la bula de Clemente VI condena a los flagelantes.", "Virgilio")
        if level.special == "lucifero":
            self.say("Trepa por su pelo. Al otro lado del centro de la Tierra están las estrellas.", "Virgilio")

    # ── utilidades ───────────────────────────────────────────────────────
    def _floor_at(self, x: int) -> int | None:
        col = self.terrain.k[:, x]
        for y in range(8, self.terrain.h):
            if col[y] != AIR:
                return y
        return None

    def say(self, text: str, who: str = "") -> None:
        self.messages.append([text, 6 * TPS + len(text) * 2, who])

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

    def can_assign(self, L: Lemming, skill: Skill) -> bool:
        if L.removed or L.state in DOOMED or L.maestro:
            return False
        if L.moria == 2 and skill != Skill.BUBBONE:
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
        return False

    def lemmings_at(self, cx: int, cy: int) -> list[Lemming]:
        return [L for L in self.lemmings if not L.removed and abs(L.x - cx) <= 5 and L.y - 13 <= cy <= L.y + 2]

    def pick(self, cx: int, cy: int, skill: Skill | None) -> tuple[Lemming | None, int]:
        cands = self.lemmings_at(cx, cy)
        if not cands:
            return None, 0
        able = [L for L in cands if skill and self.can_assign(L, skill)]
        pool = able or cands
        best = min(pool, key=lambda L: (abs(L.x - cx) + abs(L.y - 6 - cy), L.id))
        return best, len(cands)

    def guard_near(self, x: int, y: int, r: int = 28) -> Guardian | None:
        best = None
        for g in self.guards:
            if not g.pacified and abs(g.x - x) <= r and abs(g.y - 10 - y) <= r + 6:
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
        if L is None or self.skills[skill] <= 0 or not self.can_assign(L, skill):
            return False
        self.skills[skill] -= 1
        L.fervor = 0
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

    def use_palla(self, slot: int, x: int, y: int) -> bool:
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
                self.fx.append(("orange", x, y))
                if g is not None and g.needs == "arancia":
                    self._pacify(g, f"{g.name} se arroja sobre la naranja. El paso queda libre.")
                    return True
                t = LURE_TICKS * (2 if "lure_long" in self.mods else 1)
                self.lure = [x, y, t]
                self.say("La naranja amarga rueda. Las almas la siguen.", "")
                return True
            case "medicinale":
                self._spend(slot)
                n = 0
                for L in self.lemmings:
                    if not L.removed and (L.x - x) ** 2 + (L.y - 6 - y) ** 2 <= 48 * 48:
                        n += L.moria > 0
                        L.moria = L.moria_t = 0
                        L.immune = IMMUNE_TICKS
                self.focos = [f for f in self.focos if (f[0] - x) ** 2 + (f[1] - y) ** 2 > 48 * 48]
                self.corpses = [c for c in self.corpses if (c[0] - x) ** 2 + (c[1] - y) ** 2 > 48 * 48]
                self.fx.append(("cure", x, y))
                self.events.append("cure")
                self.say(f"Cosme y Damián: {n} curados. Quince segundos de inmunidad.", "")
                return True
            case "mecenate":
                artist = self.pick_artist(slot)
                self._spend(slot)
                if artist == "brunelleschi":
                    for dy in range(3):
                        self.terrain.add_row(x - 30, x + 30, y + dy, np.array((236, 204, 150), dtype=np.uint8))
                    self.fx.append(("dome", x, y))
                    self.say("Brunelleschi: doble casco, sin cimbra. Un puente donde no lo había.", "Brunelleschi")
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
                self._pacify(g, f"26 de abril de 1478. {g.name} se vuelve contra los suyos. Dante lo anota.")
                return True
            case "giglio":
                if self.level.special == "final":
                    self.shield.pop(slot)
                    self.used["giglio"] = 1
                    self.fx.append(("release", x, y))
                    self.events.append("lume")
                    self.say("El escudo de Lorenzo cae girando hasta perderse. Ya no hay nada que llevar.", "San Bernardo")
                    return True
                return False
        return False

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
        self.fx.append(("swap", A.x, A.y))
        self.fx.append(("swap", B.x, B.y))
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
        self.fx.append(("pacify", g.x, g.y - 12))
        self.events.append("bribe")
        self.say(msg, g.name)

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
        self.blockers = [(L.x, L.y, BLOCK_RANGE) for L in self.lemmings
                         if L.state == St.BLOCK and not L.removed and "paradiso" not in self.mods]
        self.blockers += [(g.x, g.y, GUARD_RANGE) for g in self.guards if not g.pacified]
        night = self.night
        for L in self.lemmings:
            if L.removed:
                continue
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
                    self._pickups(L)
        if self.tick_count % 4 == 0:
            self._contagion()
        self._rats()
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
            L = Lemming(self.released, e.x, e.y, e.dir)
            if L.id in self.infect_ids:
                L.moria = 1
            self._add(L)
            self.released += 1
            self.release_timer = release_interval(self.rr)
        elif self.maestro_due and self.maestro is None:
            L = Lemming(10_000, e.x, e.y, e.dir, maestro=True)
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
        t = self.tick_count + L.id
        n = 2 if (self.rule_off("fast") or self.combo) else 1
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
        if L.state in NEEDS_FLOOR and not self.terrain.solid(L.x, L.y):
            self._set(L, St.FALL)
        match L.state:
            case St.WALK:
                L.fervor += 1
                if self.lure and abs(L.x - self.lure[0]) < (120 if "lure_bounce" in self.mods else 80) and abs(L.y - self.lure[1]) < 64:
                    if abs(L.x - self.lure[0]) > 3:
                        L.dir = 1 if self.lure[0] > L.x else -1
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
                    else:
                        self.saved += 1
                    self.events.append("yippee")
                    self.fx.append(("saved", L.x, L.y - 6))

    def _in_block_field(self, L: Lemming) -> bool:
        for bx, by, rng_ in self.blockers:
            if (bx, by) != (L.x, L.y) and abs(by - L.y) <= 8 and 0 < (bx - L.x) * L.dir <= rng_:
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
                self.fx.append(("grace", L.x, L.y - 6))
                self.events.append("cure")
                self._set(L, St.WALK)
                return
            self._set(L, St.SPLAT)
            self.events.append("splat")
            self.fx.append(("blood", L.x, L.y))
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
            self.fx.append(("dust", L.x + 4 * L.dir, L.y - 5))
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
        self.fx.append(("dust", L.x + 3 * L.dir, L.y - 2))
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
            self.fx.append(("dust", L.x, L.y))
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
            self.corpses.append([L.x, L.y, 0])
        if "resurrect" in self.mods and not self.resurrected and self.soul is None and cause in (St.SPLAT, St.DROWN, St.BURN):
            y = L.y if cause != St.DROWN else L.y - 8
            self.soul = [L.x, y, 12 * TPS, L.id]
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
        self.fx.append(("boom", L.x, L.y - 6))
        # el bubón esparce la peste
        for o in self.lemmings:
            if o is not L and not o.removed and not o.immune and not o.child and o.moria == 0:
                if (o.x - L.x) ** 2 + (o.y - L.y) ** 2 < 20 * 20 and self.rng.random() < 0.25:
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
            self.fx.append(("bubo", L.x, L.y - 6))
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
            sources.append((L.x, L.y, r, (0.015 if L.moria == 1 else 0.03) * k, L.id))
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
                if (L.x - sx) ** 2 + (L.y - sy) ** 2 <= r * r:
                    q = p * (1 + 0.5 * min(2.0, L.fervor / FERVOR_SLOW))
                    if self.rng.random() < q:
                        L.moria, L.moria_t = 1, 0
                        self.fx.append(("infect", L.x, L.y - 8))
                        break

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
            if L.removed or L.state in DOOMED:
                continue
            for v in self.vents:
                if self.vent_on(v) and v[0] <= L.x <= v[1] and abs(L.y - v[2]) <= 2:
                    self._set(L, St.BURN)
                    self.events.append("burn")
                    self.fx.append(("fire", L.x, L.y - 4))
                    break
            else:
                for b in self.boulders:
                    if self.boulder_moving(b) and abs(L.x - b[3]) < 7 and b[2] - 16 <= L.y <= b[2] + 1:
                        self._set(L, St.SPLAT)
                        self.events.append("trap")
                        self.fx.append(("blood", L.x, L.y))
                        break

    def _guards(self) -> None:
        for g in self.guards:
            g.anim += 1
            if g.pacified:
                continue
            auto = GUARDS[g.kind][2]
            if not g.touched:
                for L in self.lemmings:
                    if not L.removed and abs(L.x - g.x) < 30 and abs(L.y - g.y) < 10:
                        g.touched = True
                        self.say(GUARDS[g.kind][3], g.name)
                        break
            if g.kind == "catone" and self.giunco:
                self._pacify(g, "Catón ve el junco ceñido. «Andate, e fate che questo uom tu cinghe».")
            elif auto and g.touched:
                g.timer += 1
                if g.timer >= auto * TPS:
                    if g.kind == "furie":
                        self._pacify(g, "Llega el messo del cielo: la puerta de Dite se abre con una varita.")
                    else:
                        self._pacify(g, f"{g.name}: «Pasad». La espera era la prueba.")

    def _corpses(self) -> None:
        for c in self.corpses:
            c[2] += 1
            if c[2] == FOCO_TICKS:
                self.focos.append((c[0], c[1]))
                self.fx.append(("foco", c[0], c[1]))
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
            if not L.removed and L.state == St.WALK and abs(L.x - sx) < 8 and abs(L.y - sy) < 10:
                nid = 20_000 + self.soul[3]
                R = Lemming(nid, L.x, L.y, -L.dir, St.WALK)
                self._add(R)
                self.dead -= 1
                self.resurrected = True
                self.soul = None
                self.fx.append(("grace", L.x, L.y - 8))
                self.say("Filomena: «infortunio con final feliz». Un alma vuelve a la fila.", "Filomena")
                break

    def _hazards(self, L: Lemming) -> None:
        if L.state in DOOMED:
            return
        t = self.terrain
        if L.y >= t.h + 8:
            self._kill(L, St.SPLAT)
            return
        if L.y > self.fire_y:
            self._set(L, St.BURN)
            self.events.append("burn")
            self.fx.append(("fire", L.x, L.y - 4))
            return
        hy = L.y - 1
        if 0 <= L.x < t.w and 0 <= hy < t.h and "nodeath" not in self.mods:
            hz = self.hazard[hy, L.x]
            if hz == HZ_LIQUID:
                L.bomb = None
                self._set(L, St.DROWN)
                self.events.append("drown")
                self.fx.append(("splash", L.x, L.y))
                return
            if hz == HZ_FIRE or (hz == HZ_PURGE and L.state != St.WALK):
                L.bomb = None
                self._set(L, St.BURN)
                self.events.append("burn")
                self.fx.append(("fire", L.x, L.y - 4))
                return
            if hz == HZ_PURGE:
                if L.moria:
                    self.fx.append(("cure", L.x, L.y - 6))
                L.moria = L.moria_t = 0
                L.fervor = 0
                if not L.purified:
                    L.purified = True
                    if not self.purge_paid:
                        self.purge_paid = True
                        self.peso = max(0, self.peso - 10)
                        self.notes.append("Atravesó el muro de fuego: −10 de Peso")
                        self.say("Quien cruza el fuego entero sale limpio. Quien se para, arde.", "Virgilio")
        if L.state in EXITABLE:
            for e in self.exits:
                if abs(L.x - e.x) <= 3 and e.y - 8 <= L.y <= e.y + 1:
                    L.bomb = None
                    self._set(L, St.EXIT)
                    return
        if self.child is not None and not L.maestro and abs(L.x - self.child[0]) < 6 and abs(L.y - self.child[1]) < 8:
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
            self.say("Una de las llamas habla con la voz del Maestro: «…e consigliai frode».", "")
        if self.lume:
            lx, ly, _ = self.lume
            # haz diagonal de arriba-derecha a abajo-izquierda que pasa por (lx, ly)
            d = abs((L.x - lx) + (L.y - ly)) / 1.4142
            if d < 22:
                L.fervor = 0

    def _pickups(self, L: Lemming) -> None:
        for p in self.pickups:
            if p.taken or abs(L.x - p.x) > 5 or not (L.y - 14 <= p.y <= L.y + 2):
                continue
            if p.kind == "pagina":
                p.taken = True
                self.pagina = True
                self.events.append("pagina")
                self.fx.append(("pickup", p.x, p.y - 6, (250, 240, 200)))
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
                self.say(f"El escudo está lleno: la {PALLE_INFO[gone][0]} cede su hueco.", "")
            p.taken = True
            self.shield.append(p.kind)
            if p.kind == "mecenate":
                self.art_queue.append(p.artist or "caravaggio")
            self.fx.append(("pickup", p.x, p.y - 6, PALLE_INFO[p.kind][2]))
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
        if r.skill is None or world.skills[r.skill] <= 0:
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
        self.vignette = self._vignette()
        self.grain = [self._grain(k) for k in range(4)]
        self._hazard_layers()
        self.mini: pygame.Surface | None = None
        self.mini_age = 999
        self.smoke = self._smoke_layer() if "smoke" in world.mods else None

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
        h, w = hz.shape
        if liq.any():
            top = liq.copy()
            top[1:] &= ~liq[:-1]
            base = np.array(th.liquid, dtype=float)
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
        if self.liquid or self.fire:
            glow.blit(self.hz_glow, (-cam // 4, 0), special_flags=pygame.BLEND_ADD)
        # 4) entidades
        lights: list[tuple[int, int, int, tuple[int, int, int]]] = []
        self._entities(view, glow, cam, frame, lights)
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
        if self.q >= 2:
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
                L.blit(light_sprite(r // 2, col), ((Lm.x - cam) // 2 - r // 2, (Lm.y - 6) // 2 - r // 2),
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

    def _entities(self, view, glow, cam, frame, lights) -> None:
        w = self.world
        tick = w.tick_count
        for e in w.entrances:
            self._font(view, e.x - cam, e.y, min(1.0, w.hatch / HATCH_TICKS), frame)
            lights.append((e.x, e.y - 14, 70, (120, 110, 150)))
        for ex in w.exits:
            self._exit(view, glow, ex.x - cam, ex.y, frame, w.cantica, w.level.special)
            lights.append((ex.x, ex.y - 14, 120, (255, 200, 120) if w.cantica != "paradiso" else (255, 255, 230)))
        for v in w.vents:
            on = w.vent_on(v)
            x0 = v[0] - cam
            pygame.draw.rect(view, (70, 60, 56), (x0 - 2, v[2] - 3, v[1] - v[0] + 4, 3))
            pygame.draw.rect(view, (30, 20, 18), (x0, v[2] - 2, v[1] - v[0], 2))
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
        for g in w.guards:
            self._guard(view, glow, g, cam, frame, lights)
        for p in w.pickups:
            if not p.taken:
                self._pickup(view, glow, p, cam, frame, lights)
        if w.lure:
            x, y = w.lure[0] - cam, w.lure[1]
            pygame.draw.circle(view, (255, 140, 30), (x, y - 3), 3)
            view.fill((60, 120, 40), (x, y - 7, 2, 2))
            lights.append((w.lure[0], y, 50, (255, 140, 40)))
        backwards = w.rule_off("backwards")
        for Lm in w.lemmings:
            if Lm.removed:
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
            ax = img.get_width() // 2 - (0 if d > 0 else 1)
            x, y = Lm.x - ax - cam, Lm.y - img.get_height() + 1 + dy
            if Lm.state == St.EXIT:
                img = img.copy()
                img.set_alpha(255 - 20 * Lm.frame)
            view.blit(img, (x, y))
            if Lm.moria == 2:
                view.fill((60, 120, 20), (Lm.x - cam + (2 if d > 0 else -3), Lm.y - 7, 2, 2))
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
            if w.lume and Lm.fervor == 0 and Lm.state == St.WALK:
                glow.fill((40, 36, 20), ((Lm.x - cam) // 4, (Lm.y - 8) // 4, 1, 1), special_flags=pygame.BLEND_ADD)

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
            body = {"lupa": (90, 90, 96), "minosse": (70, 40, 40), "pluto": (90, 70, 40), "centauri": (120, 80, 50)}.get(k, (80, 50, 50))
            if k in ("lupa", "centauri"):
                pygame.draw.ellipse(view, body, (x - 10, y - 12, 20, 9))
                pygame.draw.circle(view, body, (x - 10, y - 14), 4)
                for lx in (-7, -3, 4, 8):
                    view.fill(body, (x + lx, y - 4, 2, 4))
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
    formants = {"a": (750, 1150), "o": (480, 850), "u": (330, 700), "e": (500, 1700)}[vowel]
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


class Sfx:
    def __init__(self, enabled: bool):
        self.ok = False
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
            self.sounds[name].play()

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
    "trees": "Árboles con fruta inalcanzable.",
}


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
SKILL_X0, SKILL_W = 4, 42
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
    rr_hold: int = 0
    hold_t: int = 0
    end_wait: float = 0.0
    aborted: bool = False
    armed: int | None = None
    swap_a: int | None = None
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


class App:
    def __init__(self, args: argparse.Namespace):
        pygame.init()
        info = pygame.display.Info()
        s = max(1, args.scale) if args.scale else 0
        if info.current_w > 0 and info.current_h > 0:
            fit = max(1, min(info.current_w // LW, (info.current_h - 60) // LH))
            s = fit if not s else min(s, fit)
        self.s = max(1, s or 2)
        self.fullscreen = args.fullscreen
        self._make_window()
        pygame.display.set_caption(TITLE)
        self.clock = pygame.time.Clock()
        self.view = pygame.Surface((VIEW_W, VIEW_H))
        self._fonts()
        self.sprites = Sprites()
        self.sfx = Sfx(not args.mute)
        self.quality = 0 if args.lowfx else 2
        self.save = Save()
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
        w = World(get_level(idx), camp)
        self.preview = (idx, w, Renderer(w, self.sprites, self.quality))
        self.mode = "preview"
        self.sfx.music(get_level(idx).cantica if get_level(idx).cantica != "proemio" else "firenze")

    def start_play(self, idx: int, pilot=None, demo: bool = False) -> None:
        camp = self.save.camp_for(idx) if not demo else Campaign()
        if self.preview and self.preview[0] == idx and pilot is None:
            _, w, r = self.preview
        else:
            w = World(get_level(idx), camp)
            r = Renderer(w, self.sprites, self.quality)
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
        if ok and not p.demo:
            camp = camp_after(w)
            self.save.record(p.idx, w, camp)
            self.unlocked = max(self.unlocked, min(N_LEVELS - 1, p.idx + 1))
            if w.pagina:
                verse = verse_of(p.idx)
            if p.idx == N_LEVELS - 1:
                ending = self.decide_ending(w, camp)
        self.result = {"idx": p.idx, "saved": w.saved, "total": w.total, "need": w.level.to_save, "ok": ok,
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
            pygame.display.flip()

    # ── título ───────────────────────────────────────────────────────────
    MENU = ["Comenzar el viaje", "La Commedia (mapa)", "Pagine salvate", "Códice histórico", "Salir"]

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
                self.mode = "pagine"
            case 3:
                self.scroll = 0
                self.mode = "codex"
            case 4:
                return "quit"
        return None

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
            if i == self.sel:
                pulse = 5 + math.sin(self.frame * 0.15) * 1.5
                pygame.draw.circle(scr, (255, 255, 255), (int(x * s), int(y * s)), int(pulse * s), 1)
        lv = get_level(self.sel)
        self.panel(150, 326, 340, 32, 220)
        st = done.get(str(self.sel))
        stat = f"  ·  salvadas {st['saved']}/{st['total']}" if st else ""
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
        skills = [f"{SKILL_NAMES[k]} {w.skills[k]}" for k in SKILLS if w.skills[k]]
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
        assert self.p is not None
        ev = self.p.world.events
        for name in dict.fromkeys(ev):
            self.sfx.play(name)
        ev.clear()

    def world_mouse(self) -> tuple[int, int, bool]:
        assert self.p is not None
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
                p.ff = not p.ff
            elif k == pygame.K_m:
                self.sfx.toggle(THEMES[w.level.theme].music)
            elif k == pygame.K_n:
                self.press_nuke()
            elif k == pygame.K_DELETE:
                p.nuke_hold = 1
            elif k == pygame.K_d and not p.demo:
                self.apply(("dioneo",))
            elif k == pygame.K_RETURN and w.compagnia_done and w.maestro_out:
                w.maestro_wait = 10**9
            elif pygame.K_1 <= k <= pygame.K_8:
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
                elif mx < SKILL_X0 + 8 * SKILL_W:
                    i = int((mx - SKILL_X0) // SKILL_W)
                    if 0 <= i < 8:
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
                i = (SKILLS.index(p.skill) - ev.y) % 8
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
        if self.apply(("palla", slot, x, y)):
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
            for _ in range(4 if p.ff else 1):
                if w.done:
                    break
                if p.pilot:
                    p.pilot.step(w, self.apply)
                w.tick()
                self.drain_events()

    def draw_play(self) -> None:
        p = self.p
        assert p is not None
        w = p.world
        p.smooth_cam += (p.cam - p.smooth_cam) * 0.35
        cam = int(round(p.smooth_cam))
        x, y, inside = self.world_mouse()
        hover, count = w.pick(x, y, p.skill) if inside else (None, 0)
        p.renderer.draw(self.view, cam, self.frame)
        if inside:
            vx = x - cam
            col = (255, 255, 255) if p.armed is None else PALLE_INFO[w.shield[p.armed]][2] if p.armed < len(w.shield) else (255, 255, 255)
            if hover is not None and p.armed is None:
                pygame.draw.rect(self.view, col, (hover.x - 6 - cam, hover.y - 14, 13, 15), 1)
            elif p.armed is not None:
                pygame.draw.circle(self.view, col, (vx, y), 10 + int(2 * math.sin(self.frame * 0.3)), 1)
                pygame.draw.circle(self.view, col, (vx, y), 2)
            else:
                for a, b in (((-5, 0), (-2, 0)), ((2, 0), (5, 0)), ((0, -5), (0, -2)), ((0, 2), (0, 5))):
                    pygame.draw.line(self.view, col, (vx + a[0], y + a[1]), (vx + b[0], y + b[1]))
        pygame.mouse.set_visible(not inside)
        self.blit_view(p.renderer.fx.shake)
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
        flags = []
        if p.demo:
            flags.append("DEMO")
        if p.paused:
            flags.append("PAUSA")
        if p.ff:
            flags.append("» ×4")
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
            self.panel(150, 100, 340, 96, 210)
            rows = ["1–8 / rueda: oficio · clic: asignar · ←→ / bordes / minimapa: cámara",
                    "Q W E R T Y U I: armar palla · clic: usarla · clic derecho: lanzar naranja",
                    "Mayús + tecla: devolver palla (avaros) · D: Privilegio di Dioneo",
                    "+ / −: cadenza · F: avance ×4 · Supr 2 s (o N dos veces): Dies Irae",
                    "Espacio: seguir · Esc: abandonar · M: música · F11: pantalla completa"]
            self.text("PAUSA", self.f_big, (LW / 2, 106), GOLD, center=True)
            for k, row in enumerate(rows):
                self.text(row, self.f_small, (LW / 2, 126 + k * 13), UI_FG, center=True)
        self.draw_shield(w, p.armed)
        # mensajes (Virgilio, guardianes, Brigata…)
        y = VIEW_H - 14
        for text, ttl, who in reversed(w.messages[-3:]):
            a = min(255, ttl * 8)
            line = f"{who}: {text}" if who else text
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
                tag += " · bordón"
            if hover.floater:
                tag += " · alas"
            if hover.moria:
                tag += " · " + ("FEBBRE" if hover.moria == 1 else "BUBBONE")
            if hover.fervor > FERVOR_SLOW:
                tag += " · se azota"
            self.text(f"{tag}  ({count})", self.f_small, (8, 46), (255, 230, 150))
        if p.armed is not None and p.armed < len(w.shield):
            kind = w.shield[p.armed]
            msg = PALLE_INFO[kind][1]
            if kind == "congiura" and p.swap_a is not None:
                msg = "Elige la segunda alma."
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
        # la predela: madera oscura y oro
        bg = cached_gradient(LW * s, PANEL_H * s, (54, 34, 24), (22, 14, 10))
        self.screen.blit(bg, (0, top * s))
        pygame.draw.line(self.screen, GOLD, (0, top * s), (LW * s, top * s), max(1, s))
        for i, sk in enumerate(SKILLS):
            x = SKILL_X0 + i * SKILL_W
            sel = sk == p.skill
            r = self.R(x + 1, top + 5, SKILL_W - 2, PANEL_H - 9)
            pygame.draw.rect(self.screen, (70, 26, 22) if sel else (30, 20, 26), r)
            # arco apuntado
            arc = [(int((x + 1) * s), int((top + 16) * s)), (int((x + SKILL_W / 2) * s), int((top + 5) * s)),
                   (int((x + SKILL_W - 1) * s), int((top + 16) * s))]
            pygame.draw.polygon(self.screen, (22, 14, 10), [(r.left, r.top), (r.right, r.top), arc[2], arc[1], arc[0]])
            pygame.draw.lines(self.screen, GOLD if sel else GOLD_D, False, [(r.left, r.bottom), arc[0], arc[1], arc[2], (r.right, r.bottom)],
                              max(1, s // 2) + (1 if sel else 0))
            pygame.draw.line(self.screen, GOLD_D, (r.left, r.bottom), (r.right, r.bottom), max(1, s // 2))
            n = w.skills[sk]
            col = (240, 232, 214) if n else (90, 80, 76)
            draw_skill_icon(self.screen, sk, int((x + SKILL_W / 2) * s), int((top + 33) * s), s * 0.95, col)
            self.text(str(n) if n else "–", self.f_small, (x + SKILL_W / 2, top + 13), UI_ACC if n else UI_DIM, center=True)
            self.text(f"{i + 1}", self.f_tiny, (x + 4, top + PANEL_H - 12), UI_DIM, shadow=False)
            if sel:
                self.text(SKILL_NAMES[sk], self.f_tiny, (x + SKILL_W / 2, top + PANEL_H - 12), UI_ACC, center=True)
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
            self.screen.fill(c, self.R(MINI.x + L.x * fx, MINI.y + (L.y - 4) * fy, 1, 1))
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
            self.sel = min(self.unlocked, r["idx"] + (1 if r["ok"] else 0))
            self.mode = "map"
        elif key == pygame.K_s and not r["demo"]:
            path = Path.cwd() / f"pydanteshell_nivel{r['idx']:03d}.json"
            try:
                path.write_text(json.dumps({"level": r["idx"], "commands": r["log"]}))
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
            nxt = r["idx"] + 1 if r["ok"] and not r["demo"] else r["idx"]
            if nxt >= N_LEVELS:
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

    print("La Commedia (solución de referencia en cada nivel):")
    idxs = range(N_LEVELS) if not quick else range(0, N_LEVELS, 10)
    for i in idxs:
        lv = get_level(i)
        widths = {len(r) for r in lv.map}
        w, log = simulate(i, Autopilot(lv.solution))
        check(f"{i:3d}. {lv.place[:34]:34s} {w.saved:3d}/{lv.total} (mín. {lv.to_save})",
              w.success and len(widths) == 1 and len(lv.map) == ROWS, f"anchos {sorted(widths)}, ticks {w.tick_count}")
        if i % 10 == 0:
            w2, _ = simulate(i, Replay(log))
            check("      la repetición reproduce la partida", (w2.saved, w2.dead, w2.tick_count) == (w.saved, w.dead, w.tick_count),
                  f"{w2.saved}/{w2.dead}/{w2.tick_count} vs {w.saved}/{w.dead}/{w.tick_count}")
    print("Todo bien." if not fails else f"{fails} fallo(s).")
    return 1 if fails else 0


def calibrate() -> int:
    out = {}
    for i in range(N_LEVELS):
        lv = get_level(i)
        w, _ = simulate(i, Autopilot(lv.solution))
        out[i] = w.saved
        print(f"{i:3d} {lv.place[:30]:30s} {w.saved}/{lv.total}", file=sys.stderr)
    items = ", ".join(f"{k}: {v}" for k, v in out.items())
    print("CALIBRATION: dict[int, int] = {" + items + "}")
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
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(args.quick)
    if args.calibrate:
        return calibrate()
    App(args).run()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
