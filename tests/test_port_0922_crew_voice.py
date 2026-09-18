"""Gender survives garage retirement and every native voice reset owner."""
import types
import unittest

import test_port_0922_offline_services_ui as ui_fixture
from gui.mods.offline_lan_0922 import crew_voice


class CrewVoiceTests(unittest.TestCase):
    def test_battle_freezes_gender_before_the_garage_selection_is_retired(self):
        from unittest import mock
        import test_port_0922_battle_runtime as runtime_fixture
        module = runtime_fixture._mounted_current_vehicle_module()
        module.g_currentVehicle.item.crew = ((0, types.SimpleNamespace(
            descriptor=types.SimpleNamespace(role='commander', group=13))),)
        battle = runtime_fixture.BattleRuntime(runtime_fixture._runtime())
        with mock.patch.dict('sys.modules', {'CurrentVehicle': module}):
            self.assertEqual(13, battle._garage_loadout_snapshot()['crew_group'])
            module.g_currentVehicle.isPresent = lambda: False
            module.g_currentVehicle.item = None
            self.assertEqual(13, battle._garage_loadout_snapshot()['crew_group'])

    def test_only_the_mounted_commander_owns_the_composite_group(self):
        def member(role, group):
            return types.SimpleNamespace(descriptor=types.SimpleNamespace(role=role, group=group))
        self.assertEqual(14, crew_voice.commander_group((
            (2, member('loader', 1)), (0, member('commander', 14)))))
        self.assertEqual(13, crew_voice.commander_group((member('commander', 13),)))
        self.assertEqual(0, crew_voice.commander_group(((0, None),)))

    def test_standard_national_settings_and_postmortem_use_attached_gender(self):
        calls = []
        class Modes(object):
            def setCurrentNation(self, nation, gender='male'):
                calls.append((nation, gender))
                return 'native-result'
        original = Modes.setCurrentNation
        patches = []
        def patch(owner, name, value):
            patches.append((owner, name, getattr(owner, name)))
            setattr(owner, name, value)
        attached = types.SimpleNamespace(id=10)
        player = types.SimpleNamespace(fakeServer=object(),
            getVehicleAttached=lambda: attached,
            arena=types.SimpleNamespace(vehicles={10: {'crewGroup': 13}, 11: {'crewGroup': 0}}))
        garage = types.SimpleNamespace(isPresent=lambda: True, item=types.SimpleNamespace(
            crew=((0, types.SimpleNamespace(descriptor=types.SimpleNamespace(
                role='commander', group=1))),)))
        exports = {
            'BigWorld': {'player': lambda: player},
            'CurrentVehicle': {'g_currentVehicle': garage},
            'SoundGroups': {'SoundModes': Modes,
                'CREW_GENDER_SWITCHES': types.SimpleNamespace(
                    DEFAULT='male', MALE='male', FEMALE='female')},
        }
        try:
            with ui_fixture.native_modules(exports):
                crew_voice.install(patch)
                modes = Modes()
                # Standard (Chinese) reset and native national refresh.
                self.assertEqual('native-result', modes.setCurrentNation('default'))
                modes.setCurrentNation('germany', 'male')
                self.assertEqual([('default', 'female'), ('germany', 'female')], calls)
                # Spectating another vehicle and starting another round must
                # not reuse the departed female commander's switch.
                attached.id = 11
                modes.setCurrentNation('france', 'female')
                self.assertEqual(('france', 'male'), calls[-1])
                attached.id = 99
                modes.setCurrentNation('ussr', 'female')
                self.assertEqual(('ussr', 'female'), calls[-1])
                player.arena = None
                modes.setCurrentNation('default')
                self.assertEqual(('default', 'female'), calls[-1])
                player.fakeServer = None
                modes.setCurrentNation('default')
                self.assertEqual(('default', 'male'), calls[-1])
        finally:
            for owner, name, value in reversed(patches):
                setattr(owner, name, value)
        self.assertIs(Modes.setCurrentNation, original)


if __name__ == '__main__':
    unittest.main()
