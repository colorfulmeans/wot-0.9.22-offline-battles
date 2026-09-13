from gui.mods.offline_lan_0922 import bootstrap
from gui.mods.offline_lan_0922 import ram_contact_armor


def init():
    ram_contact_armor.install(bootstrap)
    bootstrap.init()


def fini():
    bootstrap.fini()
