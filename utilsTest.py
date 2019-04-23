import unittest

from lxml import etree
from utils import ip
from utils.DashXMLLog import DashXMLLog
from utils.Machineid import Machineid


class TestUtils(unittest.TestCase):
    def normalizeXML(self, xmlStr):
        tree = etree.fromstring(xmlStr)
        for element in tree.iter("*"):
            if element.text is not None:
                element.text = element.text.strip()
        return etree.tostring(tree)

    def test_isLoopbackIPAddr(self):

        # test isLoopbackIPAddr
        for x in ['127.0.0.1', '127.0.1.1', '127.1.1.1']:
            self.assertTrue(ip.isLoopbackIPAddr(x))

        self.assertFalse(ip.isLoopbackIPAddr('128.0.0.0'))

    def test_isValidIPAddr(self):
        # test isValidIPAddr
        for x in ['128.1.2', '128.', '58.1.1', '0', None]:
            self.assertFalse(ip.isValidIPAddr(x))

        # test getLocalIpAddr as well as isValidIpAddr
        self.assertTrue(ip.isValidIPAddr(ip.getLocalIpAddr()))

    def test_convertLocalhostToIpAddr(self):
        # test convertLocalhostToIpAddr
        # don't touch a non localhost address
        self.assertEqual(ip.convertLocalhostToIpAddr('fred'), 'fred')
        self.assertEqual(ip.convertLocalhostToIpAddr('localhost'),
                         ip.getLocalIpAddr())

    def test_machineid(self):
        a = Machineid("access.spts.icecube.wisc.edu")
        self.assertTrue(a.is_build_host)
        self.assertFalse(a.is_control_host)
        self.assertFalse(a.is_unknown_host)

        self.assertTrue(a.is_spts_cluster)
        self.assertFalse(a.is_sps_cluster)
        self.assertFalse(a.is_unknown_cluster)

        a = Machineid("access.icecube.southpole.usap.gov")
        self.assertTrue(a.is_build_host)
        self.assertFalse(a.is_control_host)
        self.assertFalse(a.is_unknown_host)

        self.assertTrue(a.is_sps_cluster)
        self.assertFalse(a.is_spts_cluster)
        self.assertFalse(a.is_unknown_cluster)

        a = Machineid("expcont.icecube.southpole.usap.gov")
        self.assertFalse(a.is_build_host)
        self.assertTrue(a.is_control_host)
        self.assertFalse(a.is_unknown_host)

        self.assertTrue(a.is_sps_cluster)
        self.assertFalse(a.is_spts_cluster)
        self.assertFalse(a.is_unknown_cluster)

        a = Machineid("mnewcomb-laptop")
        self.assertFalse(a.is_build_host)
        self.assertFalse(a.is_control_host)
        self.assertTrue(a.is_unknown_host)

        self.assertFalse(a.is_sps_cluster)
        self.assertFalse(a.is_spts_cluster)
        self.assertTrue(a.is_unknown_cluster)

    def test_dashxmllog(self):
        a = DashXMLLog()
        a.setRun(117554)
        a.setConfig("sps-IC79-Erik-Changed-TriggerIDs-V151")
        a.setCluster("sps-cluster")
        a.setStartTime(55584.113903)
        a.setEndTime(55584.227695)
        a.setTermCond(False)
        a.setEvents(24494834)
        a.setMoni(60499244)
        a.setTcal(4653819)
        a.setSN(47624256)
        a.set_first_good_time(55584.123456)
        a.set_last_good_time(55584.210987)
        a.setVersionInfo("RelName", "revA:revB")

        docStr = a.documentToString(indent="")

        expectedDocStr = """<?xml version="1.0" ?>
<?xml-stylesheet type="text/xsl" href="/2001/xml/DAQRunlog.xsl"?>
<DAQRunlog>
<Cluster>sps-cluster</Cluster>
<Config>sps-IC79-Erik-Changed-TriggerIDs-V151</Config>
<EndTime>55584.227695</EndTime>
<Events>24494834</Events>
<FirstGoodTime>55584.123456</FirstGoodTime>
<LastGoodTime>55584.210987</LastGoodTime>
<Moni>60499244</Moni>
<Release>RelName</Release>
<Revision>revA:revB</Revision>
<SN>47624256</SN>
<StartTime>55584.113903</StartTime>
<Tcal>4653819</Tcal>
<TermCondition>Success</TermCondition>
<run>117554</run>
</DAQRunlog>
"""

        realStr = self.normalizeXML(docStr)
        expStr = self.normalizeXML(expectedDocStr)

        self.assertEqual(realStr, expStr)


if __name__ == "__main__":
    unittest.main()
