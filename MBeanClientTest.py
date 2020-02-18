#!/usr/bin/env python

import unittest
from DAQClient import BeanLoadException, MBeanClient

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class MBeanAgentException(Exception):
    pass


class MockMBeanAgent(object):
    # 'invalid-name' checks are disabled because those methods are
    # emulating Java methods

    def __init__(self):
        self.__mbean_dict = {}

    def __validate_bean(self, bean):
        self.__validate_dict()
        if bean not in self.__mbean_dict:
            raise MBeanAgentException("Unknown MBean \"%s\"" % bean)
        if isinstance(self.__mbean_dict[bean], Exception):
            tmp_except = self.__mbean_dict[bean]
            raise tmp_except

    def __validate_bean_field(self, bean, fld):
        self.__validate_dict()
        self.__validate_bean(bean)
        if fld not in self.__mbean_dict[bean]:
            raise MBeanAgentException("Unknown MBean \"%s\" attribute \"%s\"" %
                                      (bean, fld))
        if isinstance(self.__mbean_dict[bean][fld], Exception):
            raise self.__mbean_dict[bean][fld]

    def __validate_dict(self):
        if isinstance(self.__mbean_dict, Exception):
            raise self.__mbean_dict

    def get(self, bean, fld):
        self.__validate_bean_field(bean, fld)
        return self.__mbean_dict[bean][fld]

    def listMBeans(self):  # pylint: disable=invalid-name
        self.__validate_dict()
        return list(self.__mbean_dict.keys())

    def listGetters(self, bean):  # pylint: disable=invalid-name
        self.__validate_bean(bean)
        return list(self.__mbean_dict[bean].keys())

    def setMBeans(self, mbean_dict):  # pylint: disable=invalid-name
        self.__mbean_dict = mbean_dict


class MockRPCClient(object):
    def __init__(self, host, port, agent):
        self.mbean = agent


class MostlyMBeanClient(MBeanClient):
    def __init__(self, comp_name, host, port, agent):
        self.__agent = agent
        super(MostlyMBeanClient, self).__init__(comp_name, host, port)

    def create_client(self, host, port):
        return MockRPCClient(host, port, self.__agent)


class TestMBeanClient(unittest.TestCase):
    def test_fail_and_recover(self):
        agent = MockMBeanAgent()

        client_name = "foo"

        bean = "beanA"
        fld = "fldA"
        val = "valA"

        client = MostlyMBeanClient(client_name, "localhost", 123, agent)

        agent.setMBeans(MBeanAgentException("Test fail"))
        try:
            client.get(bean, fld)
        except BeanLoadException as ble:
            if not str(ble).startswith("Cannot load %s MBean \"%s:%s\": " %
                                       (client_name, bean, fld)):
                self.fail("Unexpected exception: " + exc_string())

        agent.setMBeans({bean: MBeanAgentException("Test fail"), })
        try:
            client.get(bean, fld)
        except BeanLoadException as ble:
            if not str(ble).startswith("Cannot load %s MBean \"%s:%s\": " %
                                       (client_name, bean, fld)):
                self.fail("Unexpected exception: " + exc_string())

        agent.setMBeans({bean: {fld: val, }, })
        real_val = client.get(bean, fld)
        self.assertEqual(val, real_val, "Expected value \"%s\", not \"%s\"" %
                         (val, real_val))

        bean_list = client.get_bean_names()
        self.assertTrue(bean_list is not None,
                        "Bean name list should not be None")
        self.assertEqual(len(bean_list), 1, "Expected one bean name, not %s" %
                         bean_list)
        self.assertEqual(bean_list[0], bean,
                         "Expected bean name \"%s\", not \"%s\"" %
                         (bean, bean_list[0]))

        fld_list = client.get_bean_fields(bean)
        self.assertTrue(fld_list is not None,
                        "Field name list should not be None")
        self.assertEqual(len(fld_list), 1, "Expected one bean name, not %s" %
                         fld_list)
        self.assertEqual(fld_list[0], fld,
                         "Expected bean field \"%s\", not \"%s\"" %
                         (fld, fld_list[0]))

        client.reload()

        try:
            bean_list = client.get_bean_names()
            self.fail("get_bean_names should throw an exception")
        except:
            pass

        try:
            bean_list = client.get_bean_fields(bean)
            self.fail("get_bean_fields should throw an exception")
        except:
            pass


if __name__ == '__main__':
    unittest.main()
