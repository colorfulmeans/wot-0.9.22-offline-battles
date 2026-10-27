"""Retire lobby-only playback before #1513 rebuilds map sound resources."""


def retire_lobby_music(module):
    """Use stock destroy semantics; a stopped event would replay during init.

    Loading, combat and result music have their own owners. Never unload banks
    or replace native sound objects here. The original module remains live.
    """
    controller = getattr(module, 'g_musicController', None)
    if controller is None:
        return False
    events = controller._MusicController__musicEvents
    music = events[module.MusicController._MUSIC_EVENT]
    if music.getEventId() != module.MUSIC_EVENT_LOBBY:
        return False
    controller.stopMusic()
    return True
