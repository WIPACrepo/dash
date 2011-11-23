#!/usr/bin/env python

import unittest
from DAQClient import BeanLoadException, MBeanClient

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

from DAQMocks import MockAppender


class MBeanAgentException(Exception):
    pass


class MockMBeanAgent(object):
    def __init__(self):
        self.__mbeanDict = {}

    def __validateBean(self, bean):
        self.__validateDict()
        if not bean in self.__mbeanDict:
            raise MBeanAgentException("Unknown MBean \"%s\"" % bean)
        if isinstance(self.__mbeanDict[bean], Exception):
            tmp_except = self.__mbeanDict[bean]
            raise tmp_except

    def __validateBeanField(self, bean, fld):
        self.__validateDict()
        self.__validateBean(bean)
        if not fld in self.__mbeanDict[bean]:
            raise MBeanAgentException("Unknown MBean \"%s\" attribute \"%s\"" %
                                      (bean, fld))
        if isinstance(self.__mbeanDict[bean][fld], Exception):
            raise self.__mbeanDict[bean][fld]

    def __validateDict(self):
        if isinstance(self.__mbeanDict, Exception):
            raise self.__mbeanDict

    def get(self, bean, fld):
        self.__validateBeanField(bean, fld)
        return self.__mbeanDict[bean][fld]

    def listMBeans(self):
        self.__validateDict()
        return self.__mbeanDict.keys()

    def listGetters(self, bean):
        self.__validateBean(bean)
        return self.__mbeanDict[bean].keys()

    def setMBeans(self, mbeanDict):
        self.__mbeanDict = mbeanDict


class MockRPCClient(object):
    def __init__(self, host, port, agent):
        self.mbean = agent


class MostlyMBeanClient(MBeanClient):
    def __init__(self, compName, host, port, agent):
        self.__agent = agent
        super(MostlyMBeanClient, self).__init__(compName, host, port)

    def createRPCClient(self, host, port):
        return MockRPCClient(host, port, self.__agent)


class TestMBeanClient(unittest.TestCase):
    def testFailAndRecover(self):
        agent = MockMBeanAgent()

        clientName = "foo"

        bean = "beanA"
        fld = "fldA"
        val = "valA"

        client = MostlyMBeanClient(clientName, "localhost", 123, agent)

        agent.setMBeans(MBeanAgentException("Test fail"))
        try:
            client.get(bean, fld)
        except BeanLoadException as ble:
            if not str(ble).startswith("Cannot get list of %s MBeans: " %
                                       clientName):
                self.fail("Unexpected exception: " + exc_string())

        agent.setMBeans({bean: MBeanAgentException("Test fail"), })
        try:
            client.get(bean, fld)
        except BeanLoadException as ble:
            if not str(ble).startswith("Cannot load %s MBeans %s: " %
                                       (clientName, [bean, ])):
                self.fail("Unexpected exception: " + exc_string())

        agent.setMBeans({bean: {fld: val, }, })
        realVal = client.get(bean, fld)
        self.assertEqual(val, realVal, "Expected value \"%s\", not \"%s\"" %
                         (val, realVal))

        agent.setMBeans(MBeanAgentException("Ignored"))

        beanList = client.getBeanNames()
        self.assertTrue(beanList is not None,
                        "Bean name list should not be None")
        self.assertEqual(len(beanList), 1, "Expected one bean name, not %s" %
                         beanList)
        self.assertEqual(beanList[0], bean,
                         "Expected bean name \"%s\", not \"%s\"" %
                         (bean, beanList[0]))

        fldList = client.getBeanFields(bean)
        self.assertTrue(fldList is not None,
                        "Field name list should not be None")
        self.assertEqual(len(fldList), 1, "Expected one bean name, not %s" %
                         fldList)
        self.assertEqual(fldList[0], fld,
                         "Expected bean field \"%s\", not \"%s\"" %
                         (fld, fldList[0]))

        client.reloadBeanInfo()

        try:
            beanList = client.getBeanNames()
            self.fail("getBeanNames should throw an exception")
        except:
            pass

        try:
            beanList = client.getBeanFields(bean)
            self.fail("getBeanFields should throw an exception")
        except:
            pass

if __name__ == '__main__':
    unittest.main()
