"""Read-only, bounded focus/dialog evidence for spike-profile game sessions."""
import json
import os


class FocusProbe:
    def __init__(self, executable):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.types = ctypes, wintypes
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        declarations = {
            'GetForegroundWindow': ([], wintypes.HWND),
            'IsWindowVisible': ([wintypes.HWND], wintypes.BOOL),
            'IsIconic': ([wintypes.HWND], wintypes.BOOL),
            'GetWindowThreadProcessId': ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            'GetWindowTextW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetClassNameW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'EnumWindows': ([self.callback, wintypes.LPARAM], wintypes.BOOL),
            'EnumChildWindows': ([wintypes.HWND, self.callback, wintypes.LPARAM], wintypes.BOOL),
        }
        for name, (args, result) in declarations.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = args, result
        for name, args, result in (
            ('OpenProcess', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
            ('QueryFullProcessImageNameW', [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                          ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        ):
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        self.executable = os.path.normcase(os.path.realpath(executable))
        self.paths = {}

    def _pid(self, window):
        pid = self.types.DWORD()
        self.user.GetWindowThreadProcessId(window, self.ctypes.byref(pid))
        return pid.value

    def _image(self, pid):
        if pid in self.paths:
            return self.paths[pid]
        result = ''
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if handle:
            try:
                text = self.ctypes.create_unicode_buffer(32768)
                size = self.types.DWORD(len(text))
                if self.kernel.QueryFullProcessImageNameW(handle, 0, text, self.ctypes.byref(size)):
                    result = text.value
            finally:
                self.kernel.CloseHandle(handle)
        # Retry inaccessible processes; retain only a bounded successful cache.
        if result:
            if len(self.paths) >= 64:
                self.paths.clear()
            self.paths[pid] = result
        return result

    def _text(self, window, function='GetWindowTextW'):
        buffer = self.ctypes.create_unicode_buffer(512)
        getattr(self.user, function)(window, buffer, len(buffer))
        return buffer.value

    def read(self):
        foreground = self.user.GetForegroundWindow()
        foreground_pid = self._pid(foreground) if foreground else 0
        windows, games = [], []

        @self.callback
        def collect(window, unused):
            if self.user.IsWindowVisible(window):
                pid = self._pid(window)
                image = self._image(pid)
                windows.append((window, pid, image))
                if image and os.path.normcase(os.path.realpath(image)) == self.executable:
                    games.append({'handle': int(window), 'pid': pid,
                                  'minimized': bool(self.user.IsIconic(window)),
                                  'focused': window == foreground})
            return True

        if not self.user.EnumWindows(collect, 0):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        game_pids = {row['pid'] for row in games}
        dialogs = []
        for window, pid, image in windows:
            if (len(dialogs) >= 8 or pid not in game_pids | {foreground_pid} or
                    self._text(window, 'GetClassNameW') != '#32770'):
                continue
            children = []

            @self.callback
            def child_text(child, unused):
                text = self._text(child)
                if text and len(children) < 16:
                    children.append(text)
                return len(children) < 16

            self.user.EnumChildWindows(window, child_text, 0)
            dialogs.append({'pid': pid, 'image': image, 'title': self._text(window),
                            'text': children})
        return {'foreground': {'handle': int(foreground or 0), 'pid': foreground_pid,
                               'image': self._image(foreground_pid),
                               'title': self._text(foreground) if foreground else '',
                               'class': self._text(foreground, 'GetClassNameW') if foreground else ''},
                'game_windows': sorted(games, key=lambda row: row['handle']),
                'dialogs': dialogs}


def monitor_focus(stop, executable, write, reader=None, interval=0.25, limit=128):
    """Observe changes only; never activate, hide, close or move a window."""
    try:
        reader = reader or FocusProbe(executable).read
        previous, emitted = None, 0
        while not stop.is_set() and emitted < limit:
            snapshot = reader()
            if snapshot != previous:
                write('WINDOW FOCUS ' + json.dumps(snapshot, ensure_ascii=True, sort_keys=True))
                previous, emitted = snapshot, emitted + 1
            if stop.wait(interval):
                break
        if emitted >= limit:
            write('WINDOW FOCUS limit reached; further changes omitted')
    except Exception as error:
        write('WINDOW FOCUS unavailable: %s: %s' % (type(error).__name__, error))
