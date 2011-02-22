from utils import ip
from utils.DashXMLLog import DashXMLLog
from utils.DashXMLLog import DashXMLLogException
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


    def test_dashxmllog(self):
        a = DashXMLLog()
        a.setRun(117554)
        a.setConfig("sps-IC79-Erik-Changed-TriggerIDs-V151")
        a.setStartTime(55584.113903)
        a.setEndTime(55584.227695)
        a.setTermCond("SUCCESS")
        a.setEvents(24494834)
        a.setMoni(60499244)
        a.setTcal(4653819)
        a.setSN(47624256)
        
        try:
            docStr = a.documentToString(indent="")
            expectedDocStr = """<?xml version="1.0" ?>
<?xml-stylesheet type="text/xsl" href="/2001/xml/DAQRunlog.xsl"?>
<DAQRunlog>
<Config>
sps-IC79-Erik-Changed-TriggerIDs-V151
</Config>
<EndTime>
55584.227695
</EndTime>
<Events>
24494834
</Events>
<Moni>
60499244
</Moni>
<SN>
47624256
</SN>
<StartTime>
55584.113903
</StartTime>
<Tcal>
4653819
</Tcal>
<TermCondition>
SUCCESS
</TermCondition>
<run>
117554
</run>
</DAQRunlog>
"""
            self.assertEqual(docStr, expectedDocStr)
        except DashXMLLogException:
            self.fail("Dash XML Log Code raised an exception")


if __name__ == "__main__":
    unittest.main()

        


if __name__ == "__main__":
    unittest.main()

        
