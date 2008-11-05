#!/usr/bin/env python

import StringIO, time, unittest
from DAQLogClient import DAQLog
from DAQMoni import BeanFieldNotFoundException, DAQMoni, MoniData

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
        k = self.__mbeanDict[bean].keys()
        k.sort()
        return k

    def listMBeans(self):
        k = self.__mbeanDict.keys()
        k.sort()
        return k

class MockRPCClient(object):
    def __init__(self, mbeans):
        self.mbean = MockMBeanClient(mbeans)

class MockData(MoniData):
    def __init__(self, name, daqID, fname, addr, port, rpcClient):
        self.__client = rpcClient
        self.__stringFile = None

        super(MockData, self).__init__(name, daqID, fname, addr, port)

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

    def __init__(self, log, moniPath, interval, IDs, names, daqIDs, addrs,
                 mbeanPorts):
        super(MockMoni, self).__init__(log, moniPath, interval, IDs, names,
                                       daqIDs, addrs, mbeanPorts, True)

    def createData(cls, name, daqId, fname, addr, port):
        return cls.__MOCK['%s-%s' % (name, daqId)]

    def setMockData(cls, data):
        cls.__MOCK = data
    setMockData = classmethod(setMockData)

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

    def testCreate(self):
        mbeans = {'abean' : {'a':1, 'b':2}}

        client = MockRPCClient(mbeans)

        name = 'xyz'
        daqId = 515

        md = MockData(name, daqId, None, None, 5, client)

        expStr = '%s-%d' % (name, daqId)
        self.assertEquals(expStr, str(md),
                          'Expected "%s", not "%s"' % (expStr, str(md)))

    def testUnfix(self):
        strVals = { 'a':'123', 'b':['123', '123'], 'c':'abc'}

        vals = MoniData.unFixValue(strVals)
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

        client = MockRPCClient(mbeans)

        name = 'xyz'
        daqId = 515

        md = MockData(name, daqId, None, None, 5, client)

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
        name = 'xyz'
        daqId = 515

        MockMoni.setMockData({'%s-%d' % (name, daqId) : None, })

        moniPath = 'x'
        addr = 'foo'
        port = 678

        appender = MockAppender('log')
        appender.addExpectedExact(('Creating moni output file %s/%s-%d.moni' +
                                   ' (remote is %s:%d)') %
                                  (moniPath, name, daqId, addr, port))

        compId = 1

        MockMoni(DAQLog(appender), moniPath, None, (compId, ),
                 {compId:name, }, {compId:daqId, }, {compId:addr, },
                 {compId:port, })

        appender.checkEmpty()

    def testSingleBean(self):
        mbeans = {'abean' : {'a':1, 'b':2}}

        client = MockRPCClient(mbeans)

        name = 'xyz'
        daqId = 515
        addr = 'foo'
        port = 678

        md = MockData(name, daqId, None, addr, port, client)

        MockMoni.setMockData({'%s-%d' % (name, daqId) : md, })

        moniPath = 'x'

        appender = MockAppender('log')
        appender.addExpectedExact(('Creating moni output file %s/%s-%d.moni' +
                                   ' (remote is %s:%d)') %
                                  (moniPath, name, daqId, addr, port))

        compId = 1

        moni = MockMoni(DAQLog(appender), moniPath, None, (compId, ),
                        {compId:name, }, {compId:daqId, }, {compId:addr, },
                        {compId:port, })

        appender.checkEmpty()

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

        appender.checkEmpty()

    def testDoMoni(self):
        mbeans = {'abean' : {'a':1, 'b':2}}

        client = MockRPCClient(mbeans)

        name = 'xyz'
        daqId = 515
        addr = 'foo'
        port = 678

        md = MockData(name, daqId, None, addr, port, client)

        MockMoni.setMockData({'%s-%d' % (name, daqId) : md, })

        moniPath = 'x'

        appender = MockAppender('log')
        appender.addExpectedExact(('Creating moni output file %s/%s-%d.moni' +
                                   ' (remote is %s:%d)') %
                                  (moniPath, name, daqId, addr, port))

        compId = 1

        moni = MockMoni(DAQLog(appender), moniPath, None, (compId, ),
                        {compId:name, }, {compId:daqId, }, {compId:addr, },
                        {compId:port, })

        appender.checkEmpty()

        moni.doMoni()


        lines = md.getOutputLines()

        tries = 0
        while len(lines) == 0 and tries < 10:
            time.sleep(0.1)
            lines = md.getOutputLines()
            tries += 1

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

        appender.checkEmpty()

if __name__ == '__main__':
    unittest.main()
