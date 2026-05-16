"""AltScreen — pyte Screen subclass with alternate screen buffer support.

pyte ignores DECSET modes 47/1047/1049 (alternate screen buffer). TUI apps
like vim, htop, and Claude Code use mode 1049 to switch to a blank screen
and restore the original on exit. This subclass intercepts those modes and
maintains dual buffers.
"""

from __future__ import annotations

import copy

import pyte

# pyte's set_mode/reset_mode receive private modes with values as-is
# (the private flag is passed as a kwarg). We match on the raw mode numbers.
_ALT_SCREEN_MODES = frozenset({47, 1047, 1049})


class AltScreen(pyte.Screen):
    """Screen with alternate buffer, generation counter, and idle-friendly API."""

    def __init__(self, columns: int, lines: int) -> None:
        super().__init__(columns, lines)
        self._main_buffer: dict | None = None
        self._main_cursor: tuple[int, int] | None = None
        self._in_alt_screen: bool = False
        self._generation: int = 0

    # -- Properties -----------------------------------------------------------

    @property
    def in_alt_screen(self) -> bool:
        return self._in_alt_screen

    @property
    def generation(self) -> int:
        return self._generation

    # -- Mode intercepts ------------------------------------------------------

    def set_mode(self, *modes: int, **kwargs: bool) -> None:
        super().set_mode(*modes, **kwargs)
        if kwargs.get("private") and _ALT_SCREEN_MODES & set(modes):
            if not self._in_alt_screen:
                save_cursor = 1049 in modes
                self._enter_alt_screen(save_cursor=save_cursor)

    def reset_mode(self, *modes: int, **kwargs: bool) -> None:
        super().reset_mode(*modes, **kwargs)
        if kwargs.get("private") and _ALT_SCREEN_MODES & set(modes):
            if self._in_alt_screen:
                restore_cursor = 1049 in modes
                self._leave_alt_screen(restore_cursor=restore_cursor)

    # -- Buffer swap ----------------------------------------------------------

    def _enter_alt_screen(self, *, save_cursor: bool = False) -> None:
        self._main_buffer = copy.deepcopy(dict(self.buffer))
        if save_cursor:
            self._main_cursor = (self.cursor.x, self.cursor.y)
        # Clear the screen for the alternate buffer.
        # pyte's buffer is a defaultdict — deleting keys makes it return
        # default (blank) Char objects for every cell.
        self.buffer.clear()
        self.dirty.update(range(self.lines))
        self._in_alt_screen = True

    def _leave_alt_screen(self, *, restore_cursor: bool = False) -> None:
        if self._main_buffer is not None:
            self.buffer.clear()
            self.buffer.update(self._main_buffer)
            self._main_buffer = None
        if restore_cursor and self._main_cursor is not None:
            self.cursor.x, self.cursor.y = self._main_cursor
            self._main_cursor = None
        self.dirty.update(range(self.lines))
        self._in_alt_screen = False

    # -- Generation tracking --------------------------------------------------

    def draw(self, data: str) -> None:
        super().draw(data)
        self._generation += 1
