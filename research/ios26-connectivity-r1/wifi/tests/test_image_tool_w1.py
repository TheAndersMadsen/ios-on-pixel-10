#!/usr/bin/env python3
"""HOST ONLY. ../image_tool-w1.patch: the join tokens pass phone_extra, everything else stays refused.
  test_image_tool_w1.py TOOLS_DIR      TOOLS_DIR: a tools/ copy with the patch applied (run.sh makes one in scratch)."""
import sys, unittest
sys.dont_write_bytecode = True
sys.path[:0] = [sys.argv.pop(1)]
import image_tool as T


class W1(unittest.TestCase):
    def ok(self, s):
        return T.phone_extra(s)

    def bad(self, s):
        with self.assertRaises(SystemExit):
            T.phone_extra(s)

    def test_join_tokens(self):
        self.assertEqual(self.ok('blazer_wifi=1 blazer_wifi_stage=8 blazer_wifi_join=1'),
                         ['blazer_wifi=1', 'blazer_wifi_stage=8', 'blazer_wifi_join=1'])
        self.ok('blazer_wifi_run=120')

    def test_still_refused(self):
        for t in ('blazer_wifi_stage=9', 'blazer_wifi_join=2', 'blazer_wifi_net=2', 'blazer_wifi_ios=1', 'blazer_wifi_idx_tcm=1',
                  'blazer_wifi_mem_atu=1', 'blazer_wifi_run=1000', 'blazer_usbnet=1'):
            self.bad(t)


if __name__ == '__main__':
    unittest.main(verbosity=2)
