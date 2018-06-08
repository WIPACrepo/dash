#!/usr/bin/env python

import os
import tempfile
import unittest

from DAQConfig import DAQConfigException, DAQConfigParser
from RemoveHubs import create_config


class RemoveHubsTest(unittest.TestCase):
    def __get_config_dir(self):
        cur_dir = os.getcwd()
        tst_rsrc = os.path.join(cur_dir, 'src', 'test', 'resources',
                                'config')
        if not os.path.exists(tst_rsrc):
            cls.fail('Cannot find test resources')
        return tst_rsrc

    def testRemoveHub(self):
        cfg_dir = self.__get_config_dir()

        sps_cfg = "sps-IC40-IT6-Revert-IceTop-2017"
        cfg = DAQConfigParser.parse(cfg_dir, sps_cfg)

        # get a temporary file name
        (fdout, tmppath) = tempfile.mkstemp(suffix=".xml")
        os.close(fdout)
        os.remove(tmppath)

        new_path = create_config(cfg, (11, 44), None, new_name=tmppath)
        self.assertTrue(new_path is not None,
                        "create_config() should not return None")
        self.assertEqual(new_path, tmppath,
                          "Expected new path \"%s\", not \"%s\"" %
                          (tmppath, new_path))

    def testRemoveReplay(self):
        cfg_dir = self.__get_config_dir()

        sps_cfg = "replay-127138-local"
        cfg = DAQConfigParser.parse(cfg_dir, sps_cfg)

        # get a temporary file name
        (fdout, tmppath) = tempfile.mkstemp(suffix=".xml")
        os.close(fdout)
        os.remove(tmppath)

        try:
            create_config(cfg, (21, ), None, new_name=tmppath)
            self.fail("Should not be able to remove hub from replay config")
        except DAQConfigException:
            # expect this to fail
            pass


if __name__ == '__main__':
    unittest.main()
