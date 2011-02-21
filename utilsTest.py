from utils import ip
import unittest

class TestUtils(unittest.TestCase):
    def test_isLoopbackIPAddr(self):
        
        # test isLoopbackIPAddr
        for x in [ '127.0.0.1', '127.0.1.1', '127.1.1.1']:
            self.assertTrue(ip.isLoopbackIPAddr(x))

        self.assertFalse(ip.isLoopbackIPAddr('128.0.0.0'))
        
    def test_isValidIPAddr(self):
        # test isValidIPAddr
        for x in [ '128.1.2', '128.', '58.1.1', '0', None ]:
            self.assertFalse(ip.isValidIPAddr(x))

        # test getLocalIpAddr as well as isValidIpAddr
        self.assertTrue(ip.isValidIPAddr(ip.getLocalIpAddr()))

    def test_convertLocalhostToIpAddr(self):
        # test convertLocalhostToIpAddr
        # don't touch a non localhost address
        self.assertEquals(ip.convertLocalhostToIpAddr('fred'), 'fred')
        self.assertEquals(ip.convertLocalhostToIpAddr('localhost'),
                          ip.getLocalIpAddr())


if __name__ == "__main__":
    unittest.main()

        
