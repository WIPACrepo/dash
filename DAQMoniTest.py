#!/usr/bin/env python

import StringIO, time, unittest
from DAQLogClient import DAQLog
from DAQMoni import BeanFieldNotFoundException, DAQMoni, FileMoniData

from DAQMocks import MockAppender

class MockMBeanClient(object):
    def __init__(self, mbeanDict):
        self.__mbeanDict = mbeanDict

    def get(self, bean, fld):
        return self.__mbeanDict[bean][fld]

    def getAttributes(self, bean, fldList):
        attrs = {}
        for f in fldList:
            attrs[f] = self.__mbeanDict[bean][f]
        return attrs

    def listGetters(self, bean):
        if self.__mbeanDict is None:
            return []

        k = self.__mbeanDict[bean].keys()
        k.sort()
        return k

    def listMBeans(self):
        if self.__mbeanDict is None:
            return []

        k = self.__mbeanDict.keys()
        k.sort()
        return k

class MockRPCClient(object):
    def __init__(self, addr, port, mbeans):
        self.__addr = addr
        self.__port = port
        self.mbean = MockMBeanClient(mbeans)

    def __str__(self):
        return '%s:%d' % (self.__addr, self.__port)

class MockFileData(FileMoniData):
    def __init__(self, name, daqID, addr, port, rpcClient):
        self.__client = rpcClient
        self.__stringFile = None

        super(MockFileData, self).__init__(name, daqID, addr, port, None)

    def getOutputLines(self):
        if self.__stringFile is None:
            return None
        return self.__stringFile.getvalue().split('\n')

    def getRPCClient(self, addr, port):
        return self.__client

    def openFile(self, fname):
        if self.__stringFile is None:
            self.__stringFile = StringIO.StringIO()
        return self.__stringFile

class MockMoni(DAQMoni):
    __MOCK = None
    __CLIENT = {}

    def __init__(self, log, moniPath, IDs, names, daqIDs, addrs, mbeanPorts):
        super(MockMoni, self).__init__(log, moniPath, IDs, names, daqIDs,
                                       addrs, mbeanPorts, DAQMoni.TYPE_FILE,
                                       quiet=True)

    def clear(cls):
        cls.__MOCK = None
        cls.__CLIENT.clear()
    clear = classmethod(clear)

    def createBothData(cls, name, daqId, addr, port, fname):
        raise Exception('Unimplemented')
    createBothData = classmethod(createBothData)

    def createFileData(cls, name, daqId, addr, port, fname):
        key = '%s-%s' % (name, daqId)
        if cls.__MOCK is not None and cls.__MOCK.has_key(key):
            raise Exception('MockData already created for %s' % key)
        if cls.__CLIENT.has_key(key):
            md = MockFileData(name, daqId, addr, port, cls.__CLIENT[key])
            if cls.__MOCK is None:
                cls.__MOCK = {}
            cls.__MOCK[key] = md
            return md
        raise Exception('No MockFileData found for %s' % key)
    createFileData = classmethod(createFileData)

    def createLiveData(cls, name, daqId, addr, port):
        raise Exception('Unimplemented')
    createLiveData = classmethod(createLiveData)

    def getMockData(cls, name, daqId):
        if cls.__MOCK is None:
            raise Exception('No MockData objects have been created')

        key = '%s-%s' % (name, daqId)
        if not cls.__MOCK.has_key(key):
            raise Exception('No MockData found for %s' % key)

        return cls.__MOCK[key]
    getMockData = classmethod(getMockData)

    def setRPCClient(cls, name, daqId, client):
        key = '%s-%d' % (name, daqId)
        cls.__CLIENT[key] = client
    setRPCClient = classmethod(setRPCClient)

class TestDAQMoni(unittest.TestCase):
    def __buildLines(self, mbeans, time):
        lines = []

        bSrt = mbeans.keys()
        bSrt.sort()
        for b in bSrt:
            if len(mbeans[b]) == 0:
                continue

            lines.append('%s: %s:' % (b, time))

            fSrt = mbeans[b].keys()
            fSrt.sort()
            for f in fSrt:
                lines.append('\t%s: %s' % (f, str(mbeans[b][f])))
            lines.append('')
        lines.append('')
        return lines

    def setUp(self):
        MockMoni.clear()

    def testUnfix(self):
        strVals = { 'a':'123', 'b':['123', '123'], 'c':'abc'}

        vals = FileMoniData.unFixValue(strVals)
        for k in vals:
            if k == 'a':
                good = 123
                self.assertEquals(type(good), type(vals[k]),
                                  'Expected %s, not %s' % (str(type(good)),
                                                           str(type(vals[k]))))
                self.assertEquals(good, vals[k],
                                  'Expected %s, not %s' % (str(good),
                                                           str(vals[k])))
            elif k == 'b':
                good = 123
                for v in vals[k]:
                    self.assertEquals(type(good), type(v),
                                      'Expected %s, not %s' % (str(type(good)),
                                                               str(type(v))))
                    self.assertEquals(good, v,
                                      'Expected %s, not %s' % (str(good),
                                                               str(v)))
            elif k == 'c':
                good = 'abc'
                self.assertEquals(type(good), type(vals[k]),
                                  'Expected %s, not %s' % (str(type(good)),
                                                           str(type(vals[k]))))
                self.assertEquals(good, vals[k],
                                  'Expected %s, not %s' % (str(good),
                                                           str(vals[k])))

    def testMonitor(self):
        mbeans = {'abean' : {'fldInt':123, 'fldFloat':54.32},
                  'bbean' : {'fldArray':[123, 45.67, 'eight']},
                  'cbean' : {},
                  'dbean' : {'fldDict':{'i':1, 'f':2.3}},
                  'ebean' : {'a':'123', 'b':'45.67'}}

        addr = None
        port = 5

        client = MockRPCClient(addr, port, mbeans)

        name = 'xyz'
        daqId = 515

        md = MockFileData(name, daqId, addr, port, client)

        time = 'now'
        md.monitor(time)

        expLines = self.__buildLines(mbeans, time)
        lines = md.getOutputLines()

        self.assertEquals(len(expLines), len(lines),
                          'Expected %d lines, not %s' % (len(expLines),
                                                         len(lines)))
        for i in range(len(expLines)):
            self.assertEquals(expLines[i], lines[i],
                              'Expected line#%d "%s", not "%s"' %
                              (i, expLines[i], lines[i]))

    def testCreate(self):
        addr = 'foo'
        port = 678

        client = MockRPCClient(addr, port, None)

        name = 'xyz'
        daqId = 515

        MockMoni.setRPCClient(name, daqId, client)

        moniPath = 'x'

        appender = MockAppender('log')
        appender.addExpectedExact(('Creating moni output file %s/%s-%d.moni' +
                                   ' (remote is %s:%d)') %
                                  (moniPath, name, daqId, addr, port))

        compId = 1

        MockMoni(DAQLog(appender), moniPath, (compId, ),
                 {compId:name, }, {compId:daqId, }, {compId:addr, },
                 {compId:port, })

        appender.checkStatus(10)

    def testSingleBean(self):
        mbeans = {'abean' : {'a':1, 'b':2}}

        addr = 'foo'
        port = 678

        client = MockRPCClient(addr, port, mbeans)

        name = 'xyz'
        daqId = 515

        MockMoni.setRPCClient(name, daqId, client)

        moniPath = 'x'

        appender = MockAppender('log')
        appender.addExpectedExact(('Creating moni output file %s/%s-%d.moni' +
                                   ' (remote is %s)') %
                                  (moniPath, name, daqId, str(client)))

        compId = 1

        moni = MockMoni(DAQLog(appender), moniPath, (compId, ),
                        {compId:name, }, {compId:daqId, }, {compId:addr, },
                        {compId:port, })

        appender.checkStatus(10)

        badId = compId + 1
        badBean = 'xxx'
        badFld = 'yyy'

        try:
            moni.getSingleBeanField(badId, badBean, badFld)
            self.fail('Should have failed due to bogus ID')
        except BeanFieldNotFoundException, e:
            self.assertEquals(str(e), 'Component %d not found' % badId,
                              'Unexpected error: ' + str(e))

        try:
            moni.getSingleBeanField(compId, badBean, badFld)
            self.fail('Should have failed due to bogus bean')
        except BeanFieldNotFoundException, e:
            self.assertEquals(str(e),
                              'Bean %s not in list of beans for ID %d (%s-%d)' %
                              (badBean, compId, name, daqId),
                              'Unexpected error: ' + str(e))

        bean = mbeans.keys()[0]

        try:
            moni.getSingleBeanField(compId, bean, badFld)
            self.fail('Should have failed due to bogus bean field')
        except BeanFieldNotFoundException, e:
            expMsg = 'Bean %s field %s not in list of bean fields (%s)' % \
                (bean, badFld, str(mbeans[bean].keys()))
            self.assertEquals(str(e), expMsg,
                              'Unexpected error: ' + str(e))

        fld = mbeans[bean].keys()[0]
        val = moni.getSingleBeanField(compId, bean, fld)
        self.assertEquals(mbeans[bean][fld], val,
                              'Expected bean %s fld %s val %s, not %s ' %
                          (bean, fld, str(mbeans[bean][fld]), str(val)))

        appender.checkStatus(10)

    def testDoMoni(self):
        mbeans = {'abean' : {'a':1, 'b':2}}

        addr = 'foo'
        port = 678

        client = MockRPCClient(addr, port, mbeans)

        name = 'xyz'
        daqId = 515

        MockMoni.setRPCClient(name, daqId, client)

        moniPath = 'x'

        appender = MockAppender('log')
        appender.addExpectedExact(('Creating moni output file %s/%s-%d.moni' +
                                   ' (remote is %s)') %
                                  (moniPath, name, daqId, str(client)))

        compId = 1

        moni = MockMoni(DAQLog(appender), moniPath, (compId, ),
                        {compId:name, }, {compId:daqId, }, {compId:addr, },
                        {compId:port, })

        appender.checkStatus(10)

        moni.doMoni()

        tries = 0
        while moni.isActive() and tries < 10:
            time.sleep(0.1)
            tries += 1

        md = MockMoni.getMockData(name, daqId)
        lines = md.getOutputLines()
        self.failUnless(len(lines) > 0, "doMoni didn't print anything")
        self.failUnless(len(lines[0]) > 0, "doMoni printed a blank line")
        self.assertEquals(':', lines[0][-1],
                          'No colon at end of "%s"' % lines[0])

        bean = mbeans.keys()[0]
        prefix = lines[0][0:len(bean)+2]
        self.assertEquals(bean + ': ', prefix,
                          'Expected "%s: " at front of "%s"' % (bean, lines[0]))
        expLines = self.__buildLines(mbeans, lines[0][len(prefix):-1])

        self.assertEquals(len(expLines), len(lines),
                          'Expected %d lines, not %s' % (len(expLines),
                                                         len(lines)))
        for i in range(len(expLines)):
            self.assertEquals(expLines[i], lines[i],
                              'Expected line#%d "%s", not "%s"' %
                              (i, expLines[i], lines[i]))

        appender.checkStatus(10)

if __name__ == '__main__':
    unittest.main()
