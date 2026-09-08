import ctypes
import time
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QPoint
from PyQt6.QtGui import QCursor

LEFT_MOUSE_BUTTON = 0x01
KEY_DOWN = 0x8000
WM_HOTKEY = 0x0312
MOD_NONE = 0x0000

VK_F1 = 0x70
VK_F2 = 0x71
VK_F3 = 0x72
VK_F4 = 0x73

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# 20 clicks per second while M1 is held
AUTO_SHOOT_CPS = 20.0
AUTO_SHOOT_INTERVAL = 1.0 / AUTO_SHOOT_CPS

USER32 = getattr(ctypes, "windll", None)
if USER32 is not None:
    USER32 = ctypes.windll.user32
    KERNEL32 = ctypes.windll.kernel32

_pending_dx = 0.0
_pending_dy = 0.0
_next_auto_click = 0.0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouse_data", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("extra_info", ctypes.POINTER(ctypes.c_ulong)),
    )


class INPUTUNION(ctypes.Union):
    _fields_ = (("mouse", MOUSEINPUT),)


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = (
        ("type", ctypes.c_ulong),
        ("data", INPUTUNION),
    )


def _send_input(flags, dx=0, dy=0):
    """Low-level SendInput – same path used for recoil mouse movement."""
    if USER32 is None:
        return
    mouse_input = MOUSEINPUT(dx, dy, 0, flags, 0, None)
    input_event = INPUT(INPUT_MOUSE, INPUTUNION(mouse=mouse_input))
    USER32.SendInput(1, ctypes.byref(input_event), ctypes.sizeof(INPUT))


def _send_click():
    """One full left click (down then up), same API as recoil movement."""
    _send_input(MOUSEEVENTF_LEFTDOWN)
    _send_input(MOUSEEVENTF_LEFTUP)


class GlobalHotkeyFilter(QAbstractNativeEventFilter):
    """
    Registers F1-F4 as *global* Windows hotkeys via RegisterHotKey.
    These fire even when the app is not focused (e.g. while in-game).
    """

    def __init__(self, on_f1, on_f2, on_f3=None, on_f4=None):
        super().__init__()
        self.callbacks = {
            1: on_f1,  # F1 - recoil toggle
            2: on_f2,  # F2 - softaim toggle
            3: on_f3,  # F3 - auto-shoot ON
            4: on_f4,  # F4 - auto-shoot OFF
        }
        self.virtual_keys = {1: VK_F1, 2: VK_F2, 3: VK_F3, 4: VK_F4}
        self.registered_ids = []

        if USER32 is not None:
            for hotkey_id, vk in self.virtual_keys.items():
                if self.callbacks.get(hotkey_id) is None:
                    continue
                if USER32.RegisterHotKey(None, hotkey_id, MOD_NONE, vk):
                    self.registered_ids.append(hotkey_id)

    def poll_fallback(self):
        """Handle configured keys whose global registration was unavailable."""
        if USER32 is None:
            return
        for hotkey_id, vk in self.virtual_keys.items():
            if hotkey_id in self.registered_ids:
                continue
            if USER32.GetAsyncKeyState(vk) & 1:
                callback = self.callbacks.get(hotkey_id)
                if callback is not None:
                    callback()

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_HOTKEY:
                cb = self.callbacks.get(msg.wParam)
                if cb is not None:
                    cb()
                return True, 0
        return False, 0

    def unregister(self):
        if USER32 is not None:
            for hotkey_id in self.registered_ids:
                USER32.UnregisterHotKey(None, hotkey_id)
            self.registered_ids.clear()

    def __del__(self):
        self.unregister()


def set_high_process_priority():
    """HIGH_PRIORITY_CLASS so the 10 ms timer stays reliable in-game."""
    if USER32 is not None:
        process = KERNEL32.GetCurrentProcess()
        KERNEL32.SetPriorityClass(process, 0x00000080)  # HIGH_PRIORITY_CLASS


def is_left_mouse_held():
    """Physical left mouse button held (works regardless of focus)."""
    return USER32 is not None and bool(
        USER32.GetAsyncKeyState(LEFT_MOUSE_BUTTON) & KEY_DOWN
    )


def move_cursor(dx, dy):
    global _pending_dx, _pending_dy

    _pending_dx += float(dx)
    _pending_dy += float(dy)

    whole_dx = int(_pending_dx)
    whole_dy = int(_pending_dy)

    _pending_dx -= whole_dx
    _pending_dy -= whole_dy

    if not whole_dx and not whole_dy:
        return

    if USER32 is not None:
        _send_input(MOUSEEVENTF_MOVE, whole_dx, whole_dy)
    else:
        current = QCursor.pos()
        QCursor.setPos(current + QPoint(whole_dx, whole_dy))


def move_cursor_to_point(x, y):
    """Move the cursor to an absolute screen position."""
    if USER32 is not None:
        USER32.SetCursorPos(int(x), int(y))
    else:
        QCursor.setPos(int(x), int(y))


def turn_on(toggle_button, sensitivity, operator_detected=False):
    toggle_button.setChecked(True)
    if not operator_detected:
        move_cursor(sensitivity["horizontal_sens"], sensitivity["vertical_sens"])


def move_cursor_if_mouse1_held(
    toggle_button,
    sensitivity,
    auto_shoot_enabled=False,
    operator_detected=False,
):
    """
    Called every 10 ms from the high-priority timer.

    Recoil:     toggle ON + M1 held  -> move mouse
    Auto-shoot: enabled  + M1 held  -> click at 20 CPS
    """
    global _next_auto_click

    held = is_left_mouse_held()

    # Recoil compensation
    if toggle_button.isChecked() and held and not operator_detected:
        move_cursor(
            sensitivity["horizontal_sens"],
            sensitivity["vertical_sens"],
        )

    # Auto-shoot - exact same condition style as recoil
    if not auto_shoot_enabled or not held:
        _next_auto_click = 0.0
        return

    now = time.perf_counter()

    if _next_auto_click == 0.0:
        _next_auto_click = now  # fire on first frame of the hold

    if now >= _next_auto_click:
        _send_click()
        _next_auto_click += AUTO_SHOOT_INTERVAL

        # Avoid a burst if the process was stalled
        if _next_auto_click < now - AUTO_SHOOT_INTERVAL:
            _next_auto_click = now + AUTO_SHOOT_INTERVAL
