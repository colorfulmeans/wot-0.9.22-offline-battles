import copy
import types
import unittest
from unittest import mock
import test_port_0922_bootstrap_lifecycle as harness


class DefaultStyleStockTests(unittest.TestCase):
    def setUp(self):
        self.bootstrap, unused, unused, unused, unused, unused, self.modules = harness.BootstrapLifecycleTests()._load()
        self.snapshot = {'vehicles':[{'vehicleTypeCompactDescr':101},{'vehicleTypeCompactDescr':102}],
                         'wallet':{'gold':10}}
        self.types = {101:types.SimpleNamespace(name='first'),102:types.SimpleNamespace(name='second')}
        self.styles = {1:types.SimpleNamespace(isRent=True,rentCount=100,filter=None),
                       128:types.SimpleNamespace(isRent=False,rentCount=1,filter=types.SimpleNamespace(
                           matchVehicleType=lambda v:v.name=='first'))}

    def test_native_filter_controls_hidden_grant_and_exact_rental_units(self):
        self.bootstrap._grant_default_styles(self.snapshot,self.styles,self.types)
        self.assertEqual({1:{101:100,102:100},128:{101:1}},self.snapshot['customizationItems'][4])
        self.assertEqual({'gold':10},self.snapshot['wallet'])

    def test_used_or_sold_inventory_is_not_reset_on_next_start(self):
        self.bootstrap._grant_default_styles(self.snapshot,self.styles,self.types)
        self.snapshot['customizationItems'][4][1][101]=15
        self.snapshot['customizationItems'][4].pop(128)
        before=copy.deepcopy(self.snapshot)
        self.bootstrap._grant_default_styles(self.snapshot,self.styles,self.types)
        self.assertEqual(before,self.snapshot)

    def test_existing_greater_stock_is_preserved_and_missing_copy_is_added(self):
        self.snapshot['customizationItems']={4:{1:{101:300}},2:{5:{0:4}}}
        self.bootstrap._grant_default_styles(self.snapshot,self.styles,self.types)
        self.assertEqual({101:300,102:100},self.snapshot['customizationItems'][4][1])
        self.assertEqual({5:{0:4}},self.snapshot['customizationItems'][2])

    def test_real_bootstrap_new_account_does_not_auto_grant_styles(self):
        unused,snapshot=harness.BootstrapLifecycleTests()._build(save_mode='new_account')
        self.assertNotIn('styleStockVersion',snapshot)
        self.assertNotIn('customizationItems',snapshot)
