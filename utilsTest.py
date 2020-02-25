#!/usr/bin/env python

from __future__ import print_function

import os
import tempfile
import unittest

from lxml import etree
from utils import ip
from utils.DashXMLLog import DashXMLLog
from utils.Machineid import Machineid


class TestUtils(unittest.TestCase):
    @classmethod
    def normalize_xml(cls, xml_str):
        tree = etree.fromstring(xml_str)
        for element in tree.iter("*"):
            if element.text is not None:
                element.text = element.text.strip()
        return etree.tostring(tree)

    def test_is_loopback_ip_addr(self):

        # test is_loopback_address
        for addr in ['127.0.0.1', '127.0.1.1', '127.1.1.1']:
            self.assertTrue(ip.is_loopback_address(addr))

        self.assertFalse(ip.is_loopback_address('128.0.0.0'))

    def test_is_valid_addr(self):
        # test is_valid_address
        for addr in ['128.1.2', '128.', '58.1.1', '0', None]:
            self.assertFalse(ip.is_valid_address(addr))

        # test get_local_address as well as is_valid_address
        self.assertTrue(ip.is_valid_address(ip.get_local_address()))

    def test_convert_localhost_to_ip_addr(self):
        # test convert_localhost_to_address
        # don't touch a non localhost address
        self.assertEqual(ip.convert_localhost_to_address('fred'), 'fred')
        self.assertEqual(ip.convert_localhost_to_address('localhost'),
                         ip.get_local_address())

    def test_machineid(self):
        mid = Machineid("access.spts.icecube.wisc.edu")
        self.assertTrue(mid.is_build_host)
        self.assertFalse(mid.is_control_host)
        self.assertFalse(mid.is_unknown_host)

        self.assertTrue(mid.is_spts_cluster)
        self.assertFalse(mid.is_sps_cluster)
        self.assertFalse(mid.is_unknown_cluster)

        mid = Machineid("access.icecube.southpole.usap.gov")
        self.assertTrue(mid.is_build_host)
        self.assertFalse(mid.is_control_host)
        self.assertFalse(mid.is_unknown_host)

        self.assertTrue(mid.is_sps_cluster)
        self.assertFalse(mid.is_spts_cluster)
        self.assertFalse(mid.is_unknown_cluster)

        mid = Machineid("expcont.icecube.southpole.usap.gov")
        self.assertFalse(mid.is_build_host)
        self.assertTrue(mid.is_control_host)
        self.assertFalse(mid.is_unknown_host)

        self.assertTrue(mid.is_sps_cluster)
        self.assertFalse(mid.is_spts_cluster)
        self.assertFalse(mid.is_unknown_cluster)

        mid = Machineid("mnewcomb-laptop")
        self.assertFalse(mid.is_build_host)
        self.assertFalse(mid.is_control_host)
        self.assertTrue(mid.is_unknown_host)

        self.assertFalse(mid.is_sps_cluster)
        self.assertFalse(mid.is_spts_cluster)
        self.assertTrue(mid.is_unknown_cluster)

    def test_dashxmllog(self):
        dlog = DashXMLLog()
        dlog.run_number = 117554
        dlog.run_config_name = "sps-IC79-Erik-Changed-TriggerIDs-V151"
        dlog.cluster_config_name = "sps-cluster"
        dlog.start_time = 55584.113903
        dlog.end_time = 55584.227695
        dlog.run_status = False
        dlog.num_physics = 24494834
        dlog.num_moni = 60499244
        dlog.num_tcal = 4653819
        dlog.num_sn = 47624256
        dlog.set_first_good_time(55584.123456)
        dlog.set_last_good_time(55584.210987)
        dlog.version_info = ("RelName", "revA:revB")

        doc_str = dlog.document_to_string(indent="")

        expected_doc_str = """<?xml version="1.0" ?>
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

        real_str = self.normalize_xml(doc_str)
        exp_str = self.normalize_xml(expected_doc_str)

        self.assertEqual(real_str, exp_str)

        (fdout, tmppath) = tempfile.mkstemp(suffix=".xml")
        try:
            os.write(fdout, expected_doc_str.encode("utf-8"))
            os.close(fdout)

            dirnm, filenm = os.path.split(tmppath)

            nulog = DashXMLLog.parse(dirnm, filenm)

            new_str = self.normalize_xml(nulog.document_to_string(indent=""))

            self.assertEqual(new_str, exp_str)
        finally:
            os.remove(tmppath)


if __name__ == "__main__":
    unittest.main()
