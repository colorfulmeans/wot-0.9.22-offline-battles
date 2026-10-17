import sys
import types
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import destructibles_compat as compat
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor


class TreeDescriptorRetryTests(unittest.TestCase):
    def setUp(self):
        self.callbacks = {}
        self.serial = 0
        def callback(delay, function):
            self.serial += 1
            self.callbacks[self.serial] = function
            return self.serial
        self.bw = types.SimpleNamespace(callback=callback,
            player=lambda: types.SimpleNamespace(spaceID=10),
            cancelCallback=lambda key: self.callbacks.pop(key, None))
        patcher = mock.patch.dict(sys.modules, {'BigWorld': self.bw})
        patcher.start(); self.addCleanup(patcher.stop)
        compat.reset_safe_descriptor_cache()
        self.addCleanup(compat.reset_safe_descriptor_cache)
        self.manager = types.SimpleNamespace(getSpaceID=lambda: 10)
        self.area = types.SimpleNamespace(g_cache=object(), g_destructiblesManager=self.manager)

    def test_pending_native_animation_is_replayed_once_when_ready(self):
        original = mock.Mock()
        wrapped = compat._tree_descriptor_boundary(self.area, original, True)
        args = (10, 22, 7, 0., None, 1, True, object(), object())
        with mock.patch.object(compat, 'inspect_destructible_desc',
                side_effect=(('pending', None), ('resolved', {'type': 1}))):
            wrapped(self.manager, *args)
            original.assert_not_called()
            self.callbacks.pop(1)()
        original.assert_called_once_with(self.manager, *args)
        self.assertFalse(compat._DESC_PENDING_CALLS)

    def test_pending_effect_cannot_cross_a_replaced_manager(self):
        original = mock.Mock()
        wrapped = compat._tree_descriptor_boundary(self.area, original)
        with mock.patch.object(compat, 'inspect_destructible_desc', return_value=('pending', None)):
            wrapped(self.manager, 22, 7, 'fractureEffect', 0.)
            self.area.g_destructiblesManager = object()
            self.callbacks.pop(1)()
        original.assert_not_called()
        self.assertFalse(compat._DESC_PENDING_CALLS)

    def test_actual_chunk_retirement_cancels_pending_native_arguments(self):
        wrapped = compat._tree_descriptor_boundary(self.area, mock.Mock())
        with mock.patch.object(compat, 'inspect_destructible_desc', return_value=('pending', None)):
            wrapped(self.manager, 22, 7, 'fractureEffect', 0.)
            compat.invalidate_safe_descriptor_chunk(22, retire_calls=True)
        self.assertFalse(self.callbacks)
        self.assertFalse(compat._DESC_PENDING_CALLS)

    def test_descriptor_cache_refresh_keeps_pending_callback_in_same_lifetime(self):
        wrapped = compat._tree_descriptor_boundary(self.area, mock.Mock())
        with mock.patch.object(compat, 'inspect_destructible_desc', return_value=('pending', None)):
            wrapped(self.manager, 22, 7, 'fractureEffect', 0.)
            compat.invalidate_safe_descriptor_chunk(22)
        self.assertTrue(self.callbacks)

    def test_tree_identity_uses_stock_initial_matrix_after_the_live_tree_moves(self):
        initial = object()
        signature = (1, 2, 3)
        self.manager._DestructiblesManager__destrInitialMatrices = {(22, 7): initial}
        self.area.DESTR_TYPE_TREE = 1
        bw = types.SimpleNamespace(wg_getDestructibleEffectCategory=lambda *args: 1,
            wg_getChunkMatrix=lambda *args: types.SimpleNamespace(translation=object()),
            wg_getDestructibleMatrix=mock.Mock(side_effect=AssertionError('fallen matrix is not identity')))
        math = types.SimpleNamespace(Matrix=lambda value: value)
        catalog = {'tree_instances': {(22, 7): {'signature': signature,
            'descriptor_filename': 'tree', 'filename': 'tree'}}}
        with mock.patch.dict(sys.modules, {'Math': math}), \
                mock.patch.object(sensor, '_destructible_catalog', catalog), \
                mock.patch.dict(sensor.__dict__, {'g_offh_destr_catalog_tree_names': {}}), \
                mock.patch.object(sensor, '_catalog_instance_for_matrix_1513',
                    return_value=(signature, None)) as locate:
            self.assertEqual(('exact', 'tree'), sensor._resolve_catalog_tree_name_1513(
                bw, self.area, 10, 22, 7, 8, None))
        self.assertIs(initial, locate.call_args.args[0])
