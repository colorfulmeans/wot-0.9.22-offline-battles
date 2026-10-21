from __future__ import print_function

"""Native GUI LAN waiting room using client skin bitmaps for #1513.

The room presents the reviewed 0.8.2 waiting-room law: a live room status, one
map selector and one start button. The launcher owns the server address, so
this room never edits it.

Exact #1513 evidence for the native surface used here:

- ``GUI.Simple``, ``GUI.Window`` and ``GUI.Text`` with the property names below:
  ``scripts/client/PostProcessing/ChainView.pyc`` and
  ``scripts/client/bwobsolete_tests/GUITest.pyc``.
- Vertex colour does not tint this client's textured quads. The room therefore
  uses the pinned client's window/button bitmaps, decoded to RGBA DDS with
  native frame nine-slice sizing, and BLEND for their original alpha;
  cursor and legacy service controls retain their proven white/black textures.
- Mod-owned Microsoft YaHei fonts provide dynamic Chinese glyphs. The waiting
  room uses 12 px body/button text and a 16 px title, following the stock
  settings-window reference. Other service panels keep their 16 px font.
- ``GUI.addRoot`` / ``GUI.delRoot`` / ``GUI.reSort`` and an overlay at
  ``position.z = 0.1`` with ``focus`` and ``moveFocus``:
  ``scripts/client/new_year/fade_window.pyc``.
- Mouse script methods ``handleMouseClickEvent``, ``handleMouseEnterEvent``,
  ``handleMouseLeaveEvent`` and ``handleMouseButtonEvent``: ``ChainView.pyc``.
- The lobby's own arrow is Flash, not a native shape: ``Cursor.attachCursor``
  in ``gui/Scaleform/managers/Cursor.pyc`` sets ``mcursor.visible = False`` and
  calls ``BigWorld.setCursor(mcursor)``, then ``Cursor.show`` draws the arrow
  through ``as_showCursorS`` inside ``gui/flash/Cursor.swf``. So the native
  cursor is only an input source here, and ``gui/mouse_cursors.xml`` is 12
  bytes in this build. This room activates it the same way, unpainted, and
  draws its own arrow so the player sees exactly one pointer.
- A child's CLIP position is relative to the PARENT rect, not the screen: a
  pointer parented to the 680 px panel tracked at exactly half the mouse
  displacement in a 1360 px window. The arrow is therefore a set of GUI roots
  placed at absolute clip coordinates.
"""

import sys
import time

from gui.mods.offline_lan_0922 import ui_i18n
from gui.mods.offline_lan_0922.ui_i18n import as_text, tr

# Legacy white/black primitives remain owned by the cursor and service panels.
PANEL_TEXTURE = 'gui/maps/offline_lan/waiting_panel.dds'
BUTTON_TEXTURE = 'gui/maps/offline_lan/waiting_button.dds'
START_TEXTURE = 'gui/maps/offline_lan/waiting_start.dds'
FIELD_TEXTURE = 'gui/maps/offline_lan/waiting_field.dds'
CONTROL_TEXTURE = 'system/maps/col_white.dds'
OUTLINE_TEXTURE = 'system/maps/col_black.dds'
CONTROL_TEXT_COLOUR = (16, 26, 36, 255)
CONTROL_HOVER_COLOUR = (14, 82, 140, 255)
ROOM_TEXT_COLOUR = (178, 178, 160, 255)
ROOM_HOVER_COLOUR = (255, 222, 141, 255)
PANEL_FONT = ui_i18n.CHINESE_FONT
# GUI.Text.font takes a name relative to system/fonts, as stock addLabel does.
ROOM_FONT = 'offline_lan_waiting.font'
OVERLAY_Z = 0.1
# Smaller z draws in front. The buttons render at CONTROL_Z and the pointer at
# z=0 did not, so the pointer keeps the same 0.01 step inside that band.
CONTROL_Z = 0.05
CONTROL_FRAME_OFFSET = 0.01
PANEL_WIDTH = 640
PANEL_HEIGHT = 330
PANEL_SAFE_MARGIN = 16
PANEL_RAISE_PIXELS = 24
# The stock queue title and vehicle footer stay outside this vertical band.
ROOM_TOP_FRACTION = 0.265
ROOM_BOTTOM_FRACTION = 0.78
POINTER_TICK_SECONDS = 0.03
RANDOM_MAP_OPTION = 'server_random'

_TEAM_SELECT_CONTROLS = ('team1', 'team2', 'team_random')
_TEAM_SELECT_ACTIONS = {
    'team1': 1, 'team_random': 0, 'team2': 2,
}
_TEAM_CAPACITY_LABELS = ('team1_capacity', 'team2_capacity')
_TEAM_SIZE_CONTROLS = (
    'team1_down', 'team1_up', 'team2_down', 'team2_up')
_TEAM_SIZE_ACTIONS = {
    'team1_down': (1, -1), 'team1_up': (1, 1),
    'team2_down': (2, -1), 'team2_up': (2, 1),
}
_BOT_TIER_CONTROLS = ('tier_previous', 'tier', 'tier_next')
BOT_TIER_OPTIONS = (
    ('random', 'Random'), ('same', 'Same tier'),
    ('minus1_0', 'Tier -1 / 0'), ('0_plus1', 'Tier 0 / +1'),
    ('minus1_plus1', 'Tier -1 / +1'),
    ('0_plus2', 'Tier 0 / +1 / +2'),
    ('minus2_0', 'Tier -2 / -1 / 0'),
)
_BOT_SKILL_CONTROLS = ('skill_previous', 'skill', 'skill_next')
# Menu order starts with the unchanged mixed default. Wire preset values and
# rating distributions are unchanged; labels match the launcher difficulty names.
BOT_SKILL_OPTIONS = (
    ('mixed', 'Mixed'), ('easy', 'Rookie'), ('relaxed', 'Regular'),
    ('hard', 'Veteran'), ('brutal', 'Elite'),
)


def _LEFT_MOUSE_KEY():
    """Return this client's left-mouse key constant, or None."""
    try:
        import Keys
    except ImportError:
        return None
    return getattr(Keys, 'KEY_LEFTMOUSE', None)


def _log(message):
    sys.stdout.write('[Offline LAN 0.9.22] %s\n' % message)


def friendly_map_name(map_name):
    """Turn a server geometry name into a readable room label."""
    if map_name == RANDOM_MAP_OPTION:
        return tr('Random')
    if ui_i18n.language() == 'zh':
        try:
            import ArenaType
            for arena in ArenaType.g_cache.values():
                if (getattr(arena, 'geometryName', None) == map_name and
                        getattr(arena, 'gameplayName', None) == 'ctf'):
                    name = getattr(arena, 'name', None)
                    if name:
                        return as_text(name)
        except (ImportError, AttributeError):
            pass
    parts = as_text(map_name or '').split('_')
    prefix = ''
    if parts and parts[0].isdigit():
        prefix = parts[0] + ' - '
        parts = parts[1:]
    return prefix + (' '.join([part.capitalize() for part in parts]) or
                     tr('Unknown'))


def friendly_round_length(seconds):
    """Return the battle time suffix for the start button, or ''.

    The stock map window owns this value.  A room whose owner never published
    one keeps the plain button rather than showing an invented round length.
    """
    if isinstance(seconds, bool) or seconds is None:
        return ''
    try:
        minutes = int(seconds) // 60
    except (TypeError, ValueError, OverflowError):
        return ''
    if minutes <= 0:
        return ''
    return tr('  -  %d MIN') % minutes


def friendly_bot_tier_mode(mode):
    for value, label in BOT_TIER_OPTIONS:
        if value == mode:
            return tr(label)
    return tr('Random')


def friendly_bot_skill_mode(mode):
    for value, label in BOT_SKILL_OPTIONS:
        if value == mode:
            return tr(label)
    return tr('Mixed')


def panel_geometry(screen_size, size=None):
    """Fit the room uniformly between the stock mode title and tank footer.

    Independent service panels retain their previous geometry. Room controls
    use parent-relative CLIP coordinates, so scaling the root also scales their
    positions, frames and hit rectangles together.
    """
    try:
        width, height = screen_size or (1024.0, 768.0)
        width, height = float(width), float(height)
    except (TypeError, ValueError):
        width, height = 1024.0, 768.0
    if width <= 0.0 or height <= 0.0:
        width, height = 1024.0, 768.0
    available_width = max(1.0, width - 2.0 * PANEL_SAFE_MARGIN)
    available_height = max(1.0, height - 2.0 * PANEL_SAFE_MARGIN)
    nominal_width, nominal_height = size or (PANEL_WIDTH, PANEL_HEIGHT)
    if (nominal_width, nominal_height) != (PANEL_WIDTH, PANEL_HEIGHT):
        panel_width = min(float(nominal_width), available_width)
        panel_height = min(float(nominal_height), available_height)
        raise_limit = max(0.0, (height-panel_height)*0.5-PANEL_SAFE_MARGIN)
        raise_pixels = min(float(PANEL_RAISE_PIXELS), raise_limit)
        return panel_width, panel_height, 2.0*raise_pixels/height
    top = height * ROOM_TOP_FRACTION
    bottom = height * ROOM_BOTTOM_FRACTION
    scale = min(1.0, available_width / nominal_width,
                (bottom-top) / nominal_height)
    return (nominal_width * scale, nominal_height * scale,
            1.0 - (top+bottom) / height)


class NativeSurface(object):
    """The native GUI calls this room needs from the exact client."""

    def __init__(self, gui_module=None):
        if gui_module is None:
            import GUI as gui_module
        self._gui = gui_module
        self._saved_cursor = None

    def window(self):
        return self._gui.Window(PANEL_TEXTURE)

    def simple(self, texture=''):
        return self._gui.Simple(texture)

    def text(self):
        return self._gui.Text('')

    def add_root(self, component):
        self._gui.addRoot(component)

    def remove_root(self, component):
        self._gui.delRoot(component)

    def resort(self):
        self._gui.reSort()

    def cursor_position(self):
        """Clip-space mouse position, the coordinate system ChainView reads."""
        position = self._gui.mcursor().position
        return float(position[0]), float(position[1])

    def cursor_is_active(self):
        return bool(self._gui.mcursor().active)

    def show_cursor(self):
        """Activate the native cursor without painting it.

        ``Cursor.attachCursor`` does the same: the lobby's arrow is Flash, and
        this build's ``gui/mouse_cursors.xml`` is 12 bytes, so a visible
        mcursor only shows the OS pointer beside the room's own arrow.
        Activating it is still what makes ``mcursor.position`` track.
        """
        import BigWorld
        if self._saved_cursor is not None:
            return True
        cursor = self._gui.mcursor()
        saved = (bool(getattr(cursor, 'active', False)),
                 getattr(cursor, 'visible', False))
        try:
            cursor.visible = False
            BigWorld.setCursor(cursor)
        except Exception:
            # A failed takeover is not ownership. Restore the two values which
            # were sampled before the attempt and leave no committed token.
            try:
                cursor.visible = saved[1]
                BigWorld.setCursor(cursor if saved[0] else None)
            except Exception:
                pass
            raise
        self._saved_cursor = saved
        return True

    def cursor_state(self):
        """Return the live native cursor state for the pointer diagnostic."""
        cursor = self._gui.mcursor()
        return {
            'active': getattr(cursor, 'active', None),
            'visible': getattr(cursor, 'visible', None),
            'position': tuple(getattr(cursor, 'position', ())),
        }

    def screen_size(self):
        """Return the screen size in pixels, or None when unavailable."""
        resolution = getattr(self._gui, 'screenResolution', None)
        if not callable(resolution):
            return None
        try:
            width, height = resolution()
            width, height = float(width), float(height)
        except (TypeError, ValueError):
            return None
        if width <= 0.0 or height <= 0.0:
            return None
        return width, height

    def hide_cursor(self):
        """Put the cursor back exactly as the lobby had it.

        Handing the device cursor back instead left the garage with no pointer
        at all: the lobby draws its arrow in Flash over an attached, unpainted
        mcursor, and it never reattaches one it did not detach.
        """
        import BigWorld
        cursor = self._gui.mcursor()
        saved = self._saved_cursor
        if saved is None:
            return False
        active, visible = saved
        cursor.visible = visible
        BigWorld.setCursor(cursor if active else None)
        # Keep the token when either native restore call raises so a repeated
        # close can retry the exact lobby state instead of guessing defaults.
        self._saved_cursor = None
        return True

    def tick(self, delay, function):
        import BigWorld
        return BigWorld.callback(delay, function)

    def cancel_tick(self, handle):
        import BigWorld
        BigWorld.cancelCallback(handle)


class _ControlScript(object):
    """Mouse target for one room control."""

    def __init__(self, room, role):
        self._room = room
        self._role = role

    def handleMouseEvent(self, unused_component, unused_event):
        """#1513 delivers mouse MOVE here; there is no move-specific method.

        A component with ``moveFocus`` set but no ``handleMouseEvent`` never
        completes the engine's move path.  Returning False keeps the event
        propagating so the tooltip and drag managers still see it.
        """
        self._room.move_pointer()
        return False

    def handleMouseClickEvent(self, unused_component):
        self._room.activate(self._role)
        return True

    def handleMouseEnterEvent(self, unused_component):
        self._room.hover(self._role)
        # Do not consume the crossing: swallowing it would also cut the stock
        # mouse-event chain below the native GUI for this event.
        return False

    def handleMouseLeaveEvent(self, unused_component):
        self._room.hover(None)
        return False

    def handleMouseButtonEvent(self, unused_component, event):
        return bool(getattr(event, 'key', None) == _LEFT_MOUSE_KEY())

    def handleKeyEvent(self, unused_event):
        return False


class WaitingRoomUI(object):
    """A reversible native room used instead of the stock map picker."""

    panel_size = (PANEL_WIDTH, PANEL_HEIGHT)
    panel_font = ROOM_FONT
    control_text_colour = (211, 210, 190, 255)
    control_hover_colour = ROOM_HOVER_COLOUR

    def _control_texture(self, role):
        if role in ('tier', 'skill', 'map') or role.startswith('skill_choice_'):
            return FIELD_TEXTURE
        return START_TEXTURE if role == 'start' else BUTTON_TEXTURE

    # The stock picker can only present the elected host.  This room also
    # presents the players who wait for that host.
    guest_view = True

    def __init__(self, request_start, map_pool, status=None, on_close=None,
                 host=None, surface=None, random_supported=None,
                 request_team=None, team_status=None,
                 request_team_size=None, initial_map=None,
                 on_map_selected=None, bot_tier_status=None,
                 request_bot_tier_mode=None, open_map_picker=None,
                 round_seconds=None, bot_skill_status=None,
                 request_bot_skill_mode=None, training_status=None,
                 toggle_training_bots=None):
        self._training_status = training_status or (lambda: (False, False))
        self._toggle_training_bots = toggle_training_bots
        self._request_start = request_start
        self._map_pool = map_pool
        self._status = status or (lambda: '')
        self._on_close = on_close
        self._host = host or (lambda: False)
        self._random_supported = random_supported or (lambda: True)
        self._request_team = request_team
        self._request_team_size = request_team_size
        self._team_status = team_status or (lambda: {})
        self._bot_tier_status = bot_tier_status or (lambda: {})
        self._request_bot_tier_mode = request_bot_tier_mode
        self._bot_skill_status = bot_skill_status or (lambda: {})
        self._request_bot_skill_mode = request_bot_skill_mode
        self._on_map_selected = on_map_selected
        # The stock map window is the room's map browser: it presents the
        # #1513 map images this native surface cannot draw.  Its owner opens
        # it, because the room must release the screen and the native cursor
        # first - the lobby movie and every Scaleform view inside it draw at
        # z 0.5, behind this room at z 0.1.
        self._open_map_picker = open_map_picker
        self._round_seconds = round_seconds or (lambda: None)
        self._surface = surface
        self._panel = None
        self._controls = {}
        self._labels = {}
        self._cursor_acquired = False
        self._pointer_parts = []
        self._pointer_tick = None
        self._pointer_logged = None
        self._pointer_moves = 0
        self._pointer_ticks = 0
        self._open = False
        self._root_attached = False
        self._hovered = None
        self._selected_map = initial_map
        self._message = ''
        self._pending_team_sizes = {}
        self._pending_bot_tier_mode = None
        self._pending_bot_skill_mode = None
        self._skill_menu_open = False
        self._layout_receipt = None

    def install(self):
        """Build the native components without showing them."""
        if self._panel is not None:
            return True
        surface = self._surface
        if surface is None:
            surface = NativeSurface()
        panel = surface.window()
        controls = {}
        labels = {}
        self._set(panel, 'horizontalPositionMode', 'CLIP')
        self._set(panel, 'verticalPositionMode', 'CLIP')
        self._set(panel, 'widthMode', 'PIXEL')
        self._set(panel, 'heightMode', 'PIXEL')
        self._set(panel, 'horizontalAnchor', 'CENTER')
        self._set(panel, 'verticalAnchor', 'CENTER')
        self._set(panel, 'width', PANEL_WIDTH)
        self._set(panel, 'height', PANEL_HEIGHT)
        # The original client window bitmap supplies its own colour and alpha.
        self._set(panel, 'materialFX', 'BLEND')
        self._set(panel, 'colour', (5, 12, 20, 245))
        self._set(panel, 'position', (0.0, 0.0, OVERLAY_Z))
        # Every stock root that hosts a live pointer sets focus AND moveFocus
        # (GUI.Flash, createMovieGUI, FadeWindow, ChainView).  focus alone is
        # the keyboard list and leaves the root out of the move path entirely.
        self._set(panel, 'focus', True)
        self._set(panel, 'mouseButtonFocus', False)
        self._set(panel, 'crossFocus', False)
        self._set(panel, 'moveFocus', True)
        self._set(panel, 'script', _ControlScript(self, None))
        # wg_inputKeyMode belongs to FlashGUIComponent in this build, so a
        # GUI.Window can never accept it.  Setting it only logged a skip.
        self._set(panel, 'visible', False)
        self._apply_layout(panel=panel, surface=surface)
        # Design in actual pixels, then convert once to parent-relative CLIP.
        # The root can shrink on short displays but never grows beyond 640x330.
        def position(x, y, z):
            return (2.0*x/PANEL_WIDTH-1.0, 1.0-2.0*y/PANEL_HEIGHT, z)

        def make_control(role, x, y, width, height=22):
            return self._make_control(role, position(x, y, CONTROL_Z),
                2.0*width/PANEL_WIDTH, 2.0*height/PANEL_HEIGHT,
                panel=panel, controls=controls, surface=surface)

        def make_label(role, text, x, y, width, anchor='CENTER', colour=None):
            return self._make_label(role, text, position(x, y, 0.0),
                2.0*width/PANEL_WIDTH, 32.0/PANEL_HEIGHT, anchor=anchor,
                colour=ROOM_TEXT_COLOUR if colour is None else colour,
                panel=panel, labels=labels, surface=surface)

        # Two compact selector columns; map and team rows occupy the full form.
        for role, x, y, width in (
                ('tier_previous', 34, 104, 24), ('tier', 164, 104, 232),
                ('tier_next', 294, 104, 24),
                ('skill_previous', 346, 104, 24), ('skill', 476, 104, 232),
                ('skill_next', 606, 104, 24),
                ('map', 250, 142, 456), ('random', 554, 142, 128),
                ('team1_down', 34, 180, 24), ('team1_up', 294, 180, 24),
                ('team2_down', 346, 180, 24), ('team2_up', 606, 180, 24),
                ('team1', 116, 220, 188), ('team2', 320, 220, 188),
                ('team_random', 524, 220, 188),
                ('close', 67, 311, 90), ('start', 528, 311, 180)):
            make_control(role, x, y, width, 26 if role == 'start' else 22)
        make_label('title', tr('LAN WAITING ROOM'), 12, 12, 610,
                   anchor='LEFT', colour=(219, 219, 204, 255))
        make_label('room', '', 22, 49, 596, anchor='LEFT')
        make_label('players', '', 22, 72, 596, anchor='LEFT')
        for role, text, x, y, width in (
                ('tier_previous', '<', 34, 104, 24), ('tier', '', 164, 104, 224),
                ('tier_next', '>', 294, 104, 24),
                ('skill_previous', '<', 346, 104, 24), ('skill', '', 476, 104, 224),
                ('skill_next', '>', 606, 104, 24),
                ('map', '', 250, 142, 448), ('random', tr('RANDOM MAP'), 554, 142, 120),
                ('team1_down', '-', 34, 180, 24), ('team1_capacity', '', 164, 180, 232),
                ('team1_up', '+', 294, 180, 24), ('team2_down', '-', 346, 180, 24),
                ('team2_capacity', '', 476, 180, 232), ('team2_up', '+', 606, 180, 24),
                ('team1', tr('TEAM 1'), 116, 220, 180),
                ('team2', tr('TEAM 2'), 320, 220, 180),
                ('team_random', tr('RANDOM'), 524, 220, 180),
                ('start', tr('START BATTLE'), 528, 311, 172),
                ('close', tr('LEAVE'), 67, 311, 82)):
            make_label(role, text, x, y, width, colour=self.control_text_colour)
        make_label('message', '', 22, 269, 596, anchor='LEFT')
        # Put the dropdown directly below its own field. Its five hit/text
        # surfaces share the same geometry, including when the root shrinks.
        for index, (value, caption) in enumerate(BOT_SKILL_OPTIONS):
            role = 'skill_choice_' + value
            y = 127 + 22*index
            make_control(role, 476, y, 232)
            make_label(role, tr(caption), 476, y, 224,
                       colour=self.control_text_colour)
        # Component construction is fallible on the native client. Commit the
        # installed state only after the complete graph exists.
        self._surface = surface
        self._panel = panel
        self._controls = controls
        self._labels = labels
        return True

    def _apply_layout(self, panel=None, surface=None):
        panel = self._panel if panel is None else panel
        surface = self._surface if surface is None else surface
        if panel is None or surface is None:
            return False
        reader = getattr(surface, 'screen_size', None)
        try:
            screen_size = reader() if callable(reader) else None
        except Exception:
            screen_size = None
        width, height, y = panel_geometry(screen_size, self.panel_size)
        for role, label in self._labels.items():
            label.font = self._font_for_label(role)
        self._set(panel, 'width', width)
        self._set(panel, 'height', height)
        self._set(panel, 'position', (0.0, y, OVERLAY_Z))
        receipt = (screen_size, width, height, y)
        if self.panel_font == ROOM_FONT and receipt != self._layout_receipt:
            _log('LAN room layout screen=%r design=%dx%d applied=(%r,%r) '
                 'clip_y=%.4f fonts=(body:%s,title:%s)' % (
                     screen_size, PANEL_WIDTH, PANEL_HEIGHT,
                     panel.width, panel.height, y, ROOM_FONT, PANEL_FONT))
            self._layout_receipt = receipt
        return True

    def _font_for_label(self, role):
        if self.panel_font == ROOM_FONT and role == 'title':
            return PANEL_FONT
        return self.panel_font

    @staticmethod
    def _set(component, name, value):
        setattr(component, name, value)

    @staticmethod
    def _set_optional(component, name, value):
        try:
            setattr(component, name, value)
        except (AttributeError, TypeError, ValueError):
            _log('LAN waiting room skipped the %s property' % name)

    def _make_control(self, role, position, width, height, panel=None,
                      controls=None, surface=None):
        panel = self._panel if panel is None else panel
        controls = self._controls if controls is None else controls
        surface = self._surface if surface is None else surface
        component = surface.simple(self._control_texture(role))
        for name, value in (
                ('horizontalPositionMode', 'CLIP'),
                ('verticalPositionMode', 'CLIP'),
                ('widthMode', 'CLIP'), ('heightMode', 'CLIP'),
                ('horizontalAnchor', 'CENTER'), ('verticalAnchor', 'CENTER'),
                ('position', position), ('width', width), ('height', height),
                ('materialFX', 'BLEND'), ('colour', (255, 255, 255, 255)),
                ('focus', True), ('mouseButtonFocus', True),
                ('crossFocus', True), ('moveFocus', True),
                ('visible', False)):
            self._set(component, name, value)
        self._set(component, 'script', _ControlScript(self, role))
        panel.addChild(component)
        controls[role] = component
        return component

    def _make_label(self, role, text, position, width, height, anchor='LEFT',
                    colour=(255, 255, 255, 255), panel=None, labels=None,
                    surface=None):
        panel = self._panel if panel is None else panel
        labels = self._labels if labels is None else labels
        surface = self._surface if surface is None else surface
        component = surface.text()
        # A missing font must reach the session's stock-window fallback,
        # not silently leave translated text in an unreviewed default font.
        component.font = self._font_for_label(role)
        for name, value in (
                ('text', as_text(text)),
                ('horizontalPositionMode', 'CLIP'),
                ('verticalPositionMode', 'CLIP'),
                ('widthMode', 'CLIP'), ('heightMode', 'CLIP'),
                ('horizontalAnchor', anchor), ('verticalAnchor', 'CENTER'),
                ('position', position), ('width', width), ('height', height),
                ('colour', colour), ('multiline', False),
                ('focus', False), ('mouseButtonFocus', False),
                ('crossFocus', False), ('moveFocus', False),
                ('visible', False)):
            self._set(component, name, value)
        panel.addChild(component)
        labels[role] = component
        return component

    def _options(self):
        maps = [name for name in (self._map_pool() or ())
                if name and name != RANDOM_MAP_OPTION]
        if maps and self._random_supported():
            return [RANDOM_MAP_OPTION] + maps
        return maps

    def _sync_selection(self):
        options = self._options()
        if options and self._selected_map not in options:
            self._set_selected_map(options[0])
        return options

    def _set_selected_map(self, map_name):
        if self._selected_map == map_name:
            return False
        self._selected_map = map_name
        if callable(self._on_map_selected):
            try:
                self._on_map_selected(map_name)
            except Exception as error:
                _log('LAN waiting room could not save the selected map: %s' %
                     error)
        return True

    def select_map(self, map_name):
        """Adopt one map chosen outside the room, such as in that window."""
        if not map_name:
            return False
        self._set_selected_map(map_name)
        self._message = ''
        self.refresh()
        return True

    def open(self):
        if self._open:
            self.refresh()
            return True
        if self._has_open_resources() and not self._cleanup_open_resources():
            _log('LAN waiting room could not retire a previous failed open')
            return False
        try:
            if self._panel is None:
                self.install()
            self._sync_selection()
            self._message = ''
            self._surface.add_root(self._panel)
            self._root_attached = True
            self._surface.resort()
            show_cursor = getattr(self._surface, 'show_cursor', None)
            if callable(show_cursor) and not self._acquire_cursor():
                raise RuntimeError('native cursor takeover failed')
            self._pointer_logged = None
            self._pointer_moves = 0
            self._pointer_ticks = 0
            if not self._build_pointer():
                raise RuntimeError('native pointer roots were not built')
            self._move_pointer()
            tick = getattr(self._surface, 'tick', None)
            if callable(tick) and not self._start_pointer_tick():
                raise RuntimeError('native pointer callback was not scheduled')
            if not self._refresh_contents():
                raise RuntimeError('native waiting room did not refresh')
        except Exception as error:
            self._open = False
            self._cleanup_open_resources()
            _log('LAN waiting room open failed: %s' % error)
            return False
        # No mouse callback can observe a half-built room. The public flag is
        # committed only after every native acquisition and the first paint.
        self._open = True
        _log('LAN waiting room opened')
        return True

    def _has_open_resources(self):
        return bool(
            self._root_attached or self._cursor_acquired or
            self._pointer_parts or self._pointer_tick is not None)

    def _detach_panel_root(self):
        if not self._root_attached:
            return False
        try:
            self._surface.remove_root(self._panel)
        except Exception as error:
            _log('LAN waiting room root not removed: %s' % error)
            return False
        self._root_attached = False
        return True

    def _cleanup_open_resources(self):
        """Undo a completed or partial open in strict reverse order."""
        complete = True
        if self._pointer_tick is not None and not self._stop_pointer_tick():
            complete = False
        if self._panel is not None:
            try:
                self._set(self._panel, 'visible', False)
            except Exception as error:
                _log('LAN waiting room panel not hidden: %s' % error)
        # Removal below is the actual ownership release. A visibility setter
        # failure must not leave cleanup pending after its root is gone.
        self._hide_pointer()
        if self._pointer_parts and not self._remove_pointer():
            complete = False
        if self._cursor_acquired and not self._release_cursor():
            complete = False
        if self._root_attached and not self._detach_panel_root():
            complete = False
        return complete and not self._has_open_resources()

    # Vertex colour is ignored on this client, so the arrow is white.  Each
    # entry is one row of the staircase: (left offset, top offset, width,
    # height) in pixels, measured from the tip.
    POINTER_ROWS = (
        (0, 0, 2, 2), (0, 2, 4, 2), (0, 4, 6, 2), (0, 6, 8, 2),
        (0, 8, 10, 2), (0, 10, 12, 2), (0, 12, 6, 2), (6, 12, 4, 4),
    )

    def move_pointer(self):
        """Public move hook: the control scripts call this on every move."""
        if not self._open:
            return False
        self._pointer_moves += 1
        return self._move_pointer()

    def _pixel_step(self):
        """Return one screen pixel in root CLIP units."""
        size = None
        reader = getattr(self._surface, 'screen_size', None)
        if callable(reader):
            try:
                size = reader()
            except Exception:
                size = None
        width, height = size if size else (1024.0, 768.0)
        return 2.0 / float(width), 2.0 / float(height)

    def _build_pointer(self):
        """Create the drawn arrow once, as standalone GUI roots.

        A child's CLIP position is relative to the PARENT rect, so a pointer
        parented to the 680 px panel moved at half the mouse displacement in a
        1360 px window.  A root's CLIP position is the screen position.

        A black layer one pixel larger sits behind the white one so the arrow
        stays readable over the white buttons as well as the hangar.
        """
        if self._pointer_parts:
            return False
        step_x, step_y = self._pixel_step()
        parts = []
        try:
            for texture, grow, depth in (
                    (OUTLINE_TEXTURE, 1.0,
                     CONTROL_Z - CONTROL_FRAME_OFFSET),
                    (CONTROL_TEXTURE, 0.0,
                     CONTROL_Z - 2 * CONTROL_FRAME_OFFSET)):
                for left, top, width, height in self.POINTER_ROWS:
                    part = self._surface.simple(texture)
                    for name, value in (
                            ('horizontalPositionMode', 'CLIP'),
                            ('verticalPositionMode', 'CLIP'),
                            ('widthMode', 'PIXEL'), ('heightMode', 'PIXEL'),
                            ('horizontalAnchor', 'CENTER'),
                            ('verticalAnchor', 'CENTER'),
                            ('position', (0.0, 0.0, depth)),
                            ('width', float(width) + 2.0 * grow),
                            ('height', float(height) + 2.0 * grow),
                            ('materialFX', 'SOLID'),
                            ('focus', False), ('mouseButtonFocus', False),
                            ('crossFocus', False), ('moveFocus', False),
                            ('visible', False)):
                        self._set(part, name, value)
                    self._surface.add_root(part)
                    # A CENTER anchor puts the component's middle on its
                    # position. Add the rollback token only after addRoot.
                    parts.append((
                        part, (left + width * 0.5) * step_x,
                        -(top + height * 0.5) * step_y, depth))
            resort = getattr(self._surface, 'resort', None)
            if callable(resort):
                resort()
        except Exception:
            self._pointer_parts = self._remove_pointer_entries(parts)
            raise
        self._pointer_parts = parts
        _log('LAN room pointer built parts=%d rows=%d' % (
            len(parts), len(self.POINTER_ROWS)))
        return True

    def _remove_pointer(self):
        """Drop the arrow roots so a reopen rebuilds them."""
        self._pointer_parts = self._remove_pointer_entries(
            self._pointer_parts)
        return not self._pointer_parts

    def _remove_pointer_entries(self, entries):
        """Remove committed roots in reverse order and retain failed tokens."""
        remaining = []
        for entry in reversed(list(entries)):
            part = entry[0]
            try:
                self._surface.remove_root(part)
            except Exception as error:
                _log('LAN room pointer root not removed: %s' % error)
                remaining.append(entry)
        remaining.reverse()
        return remaining

    def _move_pointer(self):
        """Follow ``mcursor.position`` with the drawn arrow."""
        if not self._pointer_parts:
            return False
        position = getattr(self._surface, 'cursor_position', None)
        if not callable(position):
            return False
        try:
            x, y = position()
        except Exception as error:
            _log('LAN room pointer read failed: %s' % error)
            return False
        for part, offset_x, offset_y, depth in self._pointer_parts:
            self._set(part, 'position', (x + offset_x, y + offset_y, depth))
            self._set(part, 'visible', True)
        self._report_pointer(x, y)
        return True

    _REPORTED_PROPERTIES = (
        'materialFX', 'widthMode', 'heightMode', 'horizontalPositionMode',
        'verticalPositionMode', 'horizontalAnchor', 'verticalAnchor',
        'position', 'width', 'height', 'colour', 'visible')

    def _describe(self, component):
        if component is None:
            return 'missing'
        pairs = ['parent=%s' % self._parent_of(component),
                 'texture=%r' % getattr(component, 'texture', None)]
        for name in self._REPORTED_PROPERTIES:
            pairs.append('%s=%r' % (name, getattr(component, name, None)))
        return ' '.join(pairs)

    def _parent_of(self, component):
        """Report whether a component is a panel child or a GUI root."""
        children = getattr(self._panel, 'children', None)
        try:
            values = list(children.values()) if hasattr(children, 'values') \
                else list(children or ())
        except Exception:
            return 'unknown'
        for value in values:
            if value is component or (isinstance(value, tuple) and
                                      len(value) == 2 and
                                      value[1] is component):
                return 'panel-child'
        return 'root'

    def _report_pointer(self, x, y):
        """Log the pointer beside a button the player can definitely see."""
        now = time.time()
        if self._pointer_logged is not None and (
                now - self._pointer_logged) < 1.0:
            return False
        self._pointer_logged = now
        _log('LAN room pointer mcursor=(%.4f, %.4f) moves=%d ticks=%d' % (
            x, y, self._pointer_moves, self._pointer_ticks))
        state = getattr(self._surface, 'cursor_state', None)
        if callable(state):
            try:
                _log('LAN room pointer native: %r' % (state(),))
            except Exception as error:
                _log('LAN room pointer native state failed: %s' % error)
        _log('LAN room pointer   part: %s' % self._describe(
            self._pointer_parts[-1][0]))
        _log('LAN room pointer button: %s' % self._describe(
            self._controls.get('close')))
        _log('LAN room pointer  panel: %s' % self._describe(self._panel))
        return True

    def _start_pointer_tick(self):
        """Follow the mouse from a callback instead of a GUI move event."""
        tick = getattr(self._surface, 'tick', None)
        if self._pointer_tick is not None or not callable(tick):
            return False
        handle = tick(POINTER_TICK_SECONDS, self._pointer_step)
        if handle is None:
            return False
        self._pointer_tick = handle
        return True

    def _pointer_step(self):
        self._pointer_tick = None
        if not self._open:
            return False
        self._pointer_ticks += 1
        self._move_pointer()
        return self._start_pointer_tick()

    def _stop_pointer_tick(self):
        handle = self._pointer_tick
        cancel = getattr(self._surface, 'cancel_tick', None)
        if handle is None or not callable(cancel):
            return False
        try:
            cancel(handle)
        except Exception:
            return False
        self._pointer_tick = None
        return True

    def _hide_pointer(self):
        complete = True
        for part, unused_x, unused_y, unused_z in self._pointer_parts:
            try:
                self._set(part, 'visible', False)
            except Exception as error:
                _log('LAN room pointer not hidden: %s' % error)
                complete = False
        return complete

    def _acquire_cursor(self):
        """Activate the native cursor while this room owns the screen.

        ``Cursor.attachCursor`` leaves the lobby's mcursor ACTIVE but with
        ``visible`` False on purpose, because the arrow the player normally
        sees is ``gui/flash/Cursor.swf`` drawn inside the lobby movie at
        z 0.5 - behind this room at z 0.1.  So an already-active cursor is not
        evidence that a visible pointer exists, and skipping the show on
        ``active`` left the room with no pointer of its own.
        """
        surface = self._surface
        show = getattr(surface, 'show_cursor', None)
        if not callable(show):
            return False
        self._log_cursor('before acquire')
        try:
            acquired = show()
        except Exception as error:
            _log('LAN waiting room could not show the cursor: %s' % error)
            return False
        if acquired is False:
            return False
        self._cursor_acquired = True
        self._log_cursor('after acquire')
        return True

    def _log_cursor(self, moment):
        """Record the native cursor state around every takeover."""
        reader = getattr(self._surface, 'cursor_state', None)
        if not callable(reader):
            return False
        try:
            _log('LAN room cursor %s: %r' % (moment, reader()))
        except Exception as error:
            _log('LAN room cursor %s unreadable: %s' % (moment, error))
            return False
        return True

    def _release_cursor(self):
        if not self._cursor_acquired:
            return False
        hide = getattr(self._surface, 'hide_cursor', None)
        if not callable(hide):
            return False
        try:
            released = hide()
        except Exception as error:
            _log('LAN waiting room could not release the cursor: %s' % error)
            return False
        if released is False:
            return False
        self._cursor_acquired = False
        self._log_cursor('after release')
        return True

    def refresh(self):
        if not self._open:
            return False
        return self._refresh_contents()

    def _refresh_contents(self):
        self._apply_layout()
        options = self._sync_selection()
        is_host = bool(self._host())
        team_status = self._team_status() or {}
        team_supported = bool(
            callable(self._request_team) and team_status.get('supported'))
        team_size_supported = bool(
            is_host and callable(self._request_team_size) and
            team_status.get('size_supported'))
        tier_status = self._bot_tier_status() or {}
        tier_supported = bool(
            is_host and callable(self._request_bot_tier_mode) and
            tier_status.get('supported'))
        tier_mode = tier_status.get('mode', 'random')
        if self._pending_bot_tier_mode == tier_mode:
            self._pending_bot_tier_mode = None
        shown_tier_mode = self._pending_bot_tier_mode or tier_mode
        self._set_text('tier', tr('BOT TIER: %s%s') % (
            friendly_bot_tier_mode(shown_tier_mode),
            '...' if self._pending_bot_tier_mode is not None else ''))
        skill_status = self._bot_skill_status() or {}
        skill_supported = bool(
            is_host and callable(self._request_bot_skill_mode) and
            skill_status.get('supported'))
        skill_mode = skill_status.get('mode', 'mixed')
        if self._pending_bot_skill_mode == skill_mode:
            self._pending_bot_skill_mode = None
        shown_skill_mode = self._pending_bot_skill_mode or skill_mode
        self._set_text('skill', tr('BOT SKILL: %s%s') % (
            friendly_bot_skill_mode(shown_skill_mode),
            '...' if self._pending_bot_skill_mode is not None else ''))
        preferred_team = team_status.get('preferred', 0)
        self._set_text('team_random', tr('RANDOM%s') % (
            tr(' (ON)') if preferred_team == 0 else ''))
        sizes = team_status.get('sizes') or {}
        for team in (1, 2):
            size = int(sizes.get(team, sizes.get(str(team), 15)))
            pending = self._pending_team_sizes.get(team)
            if pending == size:
                self._pending_team_sizes.pop(team, None)
                pending = None
            shown_size = pending if pending is not None else size
            self._set_text('team%d_capacity' % team,
                           tr('TEAM %d SIZE: %d%s') % (
                               team, shown_size,
                               '...' if pending is not None else ''))
            self._set_text('team%d' % team, tr('TEAM %d%s') % (
                team, tr('  (YOU)') if preferred_team == team else ''))
        lines = as_text(self._status() or '').splitlines()
        self._set_text('room', lines[0] if lines else '')
        self._set_text('players', lines[1] if len(lines) > 1 else '')
        if is_host:
            self._set_text('map', tr('MAP: %s') % (
                friendly_map_name(self._selected_map) if options else
                tr('waiting for the server map list')))
        else:
            self._set_text('map', lines[2] if len(lines) > 2 else
                           tr('The room host starts the battle.'))
        self._set_text('start', tr('START BATTLE') + friendly_round_length(
            self._round_seconds()))
        self._set_text('message', self._message)
        random_supported = bool(is_host and self._random_supported())
        for role, component in self._controls.items():
            visible = (team_supported if role in _TEAM_SELECT_CONTROLS else
                       team_size_supported if role in _TEAM_SIZE_CONTROLS else
                       tier_supported if role in _BOT_TIER_CONTROLS else
                       skill_supported if role in _BOT_SKILL_CONTROLS else
                       random_supported if role == 'random' else
                       role == 'close' or is_host)
            if role.startswith('skill_choice_'):
                visible = bool(self._skill_menu_open and skill_supported)
            self._set(component, 'visible', visible)
            label = self._labels.get(role)
            if label is not None:
                self._set(label, 'visible', visible)
        for role in _TEAM_CAPACITY_LABELS:
            self._set(self._labels[role], 'visible', team_supported)
        for role in ('title', 'room', 'players', 'tier', 'skill', 'map',
                     'message'):
            self._set(self._labels[role], 'visible', True)
        training, bots = self._training_status()
        self._set_text('title', tr('TRAINING ROOM') if training else tr('LAN WAITING ROOM'))
        if training:
            self._set_text('tier', tr('TRAINING BOTS: ON') if bots else tr('TRAINING BOTS: OFF'))
            if not self._message:
                self._set_text('message', tr('Training: no battle rewards or mission progress.'))
            for role in ('tier', 'tier_previous', 'tier_next'):
                self._set(self._controls[role], 'visible', is_host)
                self._set(self._labels[role], 'visible', True)
        # A dropdown covers these rows. Hide their native text/hit surfaces
        # together; this client otherwise draws their text through the menu.
        if self._skill_menu_open and skill_supported:
            for role in ('map', 'random', 'team1_down', 'team1_up', 'team2_down',
                         'team2_up', 'team1_capacity', 'team2_capacity',
                         'team1', 'team2', 'team_random', 'start'):
                if role in self._controls:
                    self._set(self._controls[role], 'visible', False)
                if role in self._labels:
                    self._set(self._labels[role], 'visible', False)
        self._paint()
        self._set(self._panel, 'visible', True)
        return True

    def _set_text(self, role, value):
        label = self._labels.get(role)
        if label is not None:
            self._set(label, 'text', as_text(value))

    def _paint(self):
        """Highlight native text without changing texture or input ownership."""
        preferred = (self._team_status() or {}).get('preferred', 0)
        selected = {0: 'team_random', 1: 'team1', 2: 'team2'}.get(preferred)
        for role in self._controls:
            label = self._labels.get(role)
            if label is None:
                continue
            self._set(label, 'colour', self.control_hover_colour
                      if role == self._hovered or role == selected
                      else self.control_text_colour)

    def hover(self, role):
        if not self._open:
            return False
        self._hovered = role
        self._paint()
        return True

    def activate(self, role):
        if not self._open:
            return False
        if role == 'close':
            self.close()
            if callable(self._on_close):
                self._on_close()
            return True
        if (role in _BOT_TIER_CONTROLS and self._training_status()[0] and
                self._host() and callable(self._toggle_training_bots)):
            self._toggle_training_bots()
            self.refresh()
            return True
        if role in _TEAM_SELECT_CONTROLS:
            return self._select_team(_TEAM_SELECT_ACTIONS[role])
        if role in _TEAM_SIZE_ACTIONS:
            team, step = _TEAM_SIZE_ACTIONS[role]
            return self._adjust_team_size(team, step)
        if role in _BOT_TIER_CONTROLS:
            return self._cycle_bot_tier_mode(
                -1 if role == 'tier_previous' else 1)
        if role == 'skill':
            status = self._bot_skill_status() or {}
            if not self._host() or not status.get('supported'):
                return False
            self._skill_menu_open = not self._skill_menu_open
            self.refresh()
            return True
        if role and role.startswith('skill_choice_'):
            if not self._skill_menu_open:
                return False
            return self._choose_bot_skill_mode(role[len('skill_choice_'):])
        if role in _BOT_SKILL_CONTROLS:
            self._skill_menu_open = False
            return self._cycle_bot_skill_mode(
                -1 if role == 'skill_previous' else 1)
        if not self._host():
            return False
        if role == 'map':
            return self._open_map_window()
        if role == 'random':
            return self._select_random_map()
        if role == 'start':
            return self._start()
        return False

    def _select_team(self, team):
        status = self._team_status() or {}
        if not callable(self._request_team) or not status.get('supported'):
            return False
        current_choice = status.get('preferred', status.get('team'))
        if current_choice == team:
            self._message = (tr('Random team selection is already on.')
                             if team == 0 else
                             tr('Already on Team %d.') % team)
            self.refresh()
            return True
        self._message = (tr('Requesting a random team...')
                         if team == 0 else
                         tr('Requesting Team %d...') % team)
        self.refresh()
        if self._request_team(team) is False:
            self._message = (tr('The server did not accept random selection.')
                             if team == 0 else
                             tr('The server did not accept Team %d.') % team)
            self.refresh()
            return False
        self.refresh()
        return True

    def _adjust_team_size(self, team, step):
        status = self._team_status() or {}
        if (not self._host() or not callable(self._request_team_size) or
                not status.get('size_supported')):
            return False
        sizes = status.get('sizes') or {}
        counts = status.get('counts') or {}
        current = self._pending_team_sizes.get(
            team, int(sizes.get(team, sizes.get(str(team), 15))))
        target = max(1, min(15, int(current) + int(step)))
        if target < int(counts.get(team, 0)):
            self._message = tr('Team %d already has %d player(s).') % (
                team, int(counts.get(team, 0)))
            self.refresh()
            return False
        if target == current:
            self._message = tr('Team %d size is already %d.') % (team, target)
            self.refresh()
            return True
        self._pending_team_sizes[team] = target
        self._message = tr('Setting Team %d size to %d...') % (team, target)
        self.refresh()
        if self._request_team_size(team, target) is False:
            self._pending_team_sizes.pop(team, None)
            self._message = tr('The server did not accept that team size.')
            self.refresh()
            return False
        return True

    def reject_team_size(self, team, message=None):
        """Retire one optimistic size after a server denial."""
        try:
            team = int(team)
        except (TypeError, ValueError):
            return False
        self._pending_team_sizes.pop(team, None)
        self._message = message or tr('The server did not accept that team size.')
        self.refresh()
        return True

    def _cycle_bot_tier_mode(self, step):
        status = self._bot_tier_status() or {}
        if (not self._host() or not callable(self._request_bot_tier_mode) or
                not status.get('supported')):
            return False
        current = self._pending_bot_tier_mode or status.get('mode', 'random')
        modes = [value for value, unused_label in BOT_TIER_OPTIONS]
        try:
            index = modes.index(current)
        except ValueError:
            index = 0
        target = modes[(index + int(step)) % len(modes)]
        self._pending_bot_tier_mode = target
        self._message = tr('Setting Bot tier preset...')
        self.refresh()
        if self._request_bot_tier_mode(target) is False:
            self._pending_bot_tier_mode = None
            self._message = tr('The server did not accept that Bot tier preset.')
            self.refresh()
            return False
        return True

    def _cycle_bot_skill_mode(self, step):
        status = self._bot_skill_status() or {}
        if (not self._host() or not callable(self._request_bot_skill_mode) or
                not status.get('supported')):
            return False
        current = self._pending_bot_skill_mode or status.get('mode', 'mixed')
        modes = [value for value, unused_label in BOT_SKILL_OPTIONS]
        try:
            index = modes.index(current)
        except ValueError:
            index = 0
        target = modes[(index + int(step)) % len(modes)]
        return self._choose_bot_skill_mode(target)

    def _choose_bot_skill_mode(self, target):
        status = self._bot_skill_status() or {}
        if (not self._host() or not callable(self._request_bot_skill_mode) or
                not status.get('supported') or
                target not in [value for value, caption in BOT_SKILL_OPTIONS]):
            return False
        self._skill_menu_open = False
        self._pending_bot_skill_mode = target
        self._message = tr('Setting Bot skill preset...')
        self.refresh()
        if self._request_bot_skill_mode(target) is False:
            self._pending_bot_skill_mode = None
            self._message = tr(
                'The server did not accept that Bot skill preset.')
            self.refresh()
            return False
        return True

    def reject_bot_skill_mode(self, unused_mode=None, message=None):
        self._pending_bot_skill_mode = None
        self._message = (message or
                         tr('The server did not accept that Bot skill '
                            'preset.'))
        self.refresh()
        return True

    def reject_bot_tier_mode(self, unused_mode=None, message=None):
        self._pending_bot_tier_mode = None
        self._message = (message or
                         tr('The server did not accept that Bot tier preset.'))
        self.refresh()
        return True

    def _open_map_window(self):
        """Ask this room's owner to raise the stock map window."""
        if not self._options():
            self._message = tr('The server has not published its map list yet.')
            self.refresh()
            return False
        if not callable(self._open_map_picker):
            self._message = tr('The stock map window is unavailable.')
            self.refresh()
            return False
        if self._open_map_picker() is False:
            self._message = tr('The stock map window could not open.')
            self.refresh()
            return False
        return True

    def _select_random_map(self):
        if not self._random_supported():
            self._message = tr('This LAN server does not offer a random map.')
            self.refresh()
            return False
        self._set_selected_map(RANDOM_MAP_OPTION)
        self._message = ''
        self.refresh()
        return True

    def _start(self):
        if not self._selected_map:
            self._message = tr('Choose a map first.')
            self.refresh()
            return False
        self._message = tr('Starting %s...') % friendly_map_name(
            self._selected_map)
        self.refresh()
        accepted = self._request_start(self._selected_map)
        if accepted is False:
            self._message = tr('The server did not accept that map.')
            self.refresh()
            return False
        return True

    def close(self):
        self._skill_menu_open = False
        had_resources = self._has_open_resources()
        if not self._open and not had_resources:
            return False
        self._open = False
        self._hovered = None
        if not self._cleanup_open_resources():
            _log('LAN waiting room close is pending native cleanup')
            return False
        _log('LAN waiting room closed')
        return True

    def uninstall(self):
        if ((self._open or self._has_open_resources()) and
                not self.close()):
            return False
        self._panel = None
        self._controls = {}
        self._labels = {}
        self._pointer_parts = []
        self._root_attached = False
        return True
