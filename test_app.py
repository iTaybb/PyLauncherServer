import sys
import unittest
import time

class TestPyServer(unittest.TestCase):
    def setUp(self):
        pass
    def test_dependencies(self):
        self.assertTrue(sys.version_info >= (3, 4))
    def test_dummy(self):
        time.sleep(1)
        self.assertTrue(True)