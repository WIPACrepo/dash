#!/usr/bin/env python

import unittest
from CnCServer import DAQClient

class TestDAQClient(unittest.TestCase):
    def testInit(self):
        DAQClient('foo', 0, 'localhost', 543, 0, [])

if __name__ == '__main__':
    unittest.main()
