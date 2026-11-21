"""Robot14 has a separate build entry; no legacy motor tuning options."""
import unittest
import catalog

class Robot14Catalog(unittest.TestCase):
    def test_separate_safe_profile(self):
        p = catalog.profile('Robot14')
        self.assertEqual(p['cmake_options'], {'PICO_APP': 'Robot14'})
        self.assertEqual(p['base_mode'], 'Custom')
        self.assertEqual(p['board_baud'], 115200)
        self.assertIn('启动只读', p['description'])
        self.assertEqual(sum(x['id']=='Robot14' for x in catalog.builtins()), 1)
