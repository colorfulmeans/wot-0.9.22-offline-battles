from gui.mods.offline_lan_0922 import hotfix_20260916

hotfix_20260916.install()

from gui.mods.offline_lan_0922 import bootstrap


def init():
    bootstrap.init()


def fini():
    bootstrap.fini()
