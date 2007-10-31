#!/usr/bin/env python
#
# Produce a report of the hourly and total data rates for all the components
# in the IceCube DAQ, using data from the pDAQ .moni files.

import os, re, sys, time

PRINT_VERBOSE = False
EXTRA_VERBOSE = False
DATA_ONLY = False

MONISEC_PAT = \
    re.compile(r'^(.*):\s+(\d+-\d+-\d+ \d+:\d+:\d+)\.(\d+):\s*$')
MONILINE_PAT = re.compile(r'^\s+([^:]+):\s+(.*)$')

TIMEFMT = '%Y-%m-%d %H:%M:%S'
TIME_INTERVAL = 3600 # 1 hour

COMP_FIELDS = {
    'amandaHub' :
        { 'moniData' : 'RecordsSent',
          'snData' : 'RecordsSent',
          'tcalData' : 'RecordsSent',
          #'rdoutReq' : 'TotalRecordsReceived',
          'rdoutReq' : 'RecordsReceived',
          'rdoutData' : 'RecordsSent' },
    'stringHub' :
        { 'stringHit' : 'RecordsSent',
          'moniData' : 'RecordsSent',
          'snData' : 'RecordsSent',
          'tcalData' : 'RecordsSent',
          #'rdoutReq' : 'TotalRecordsReceived',
          'rdoutReq' : 'RecordsReceived',
          'rdoutData' : 'RecordsSent' },
    'icetopHub' :
        { 'icetopHit' : 'RecordsSent',
          'moniData' : 'RecordsSent',
          'snData' : 'RecordsSent',
          'tcalData' : 'RecordsSent',
          #'rdoutReq' : 'TotalRecordsReceived',
          'rdoutReq' : 'RecordsReceived',
          'rdoutData' : 'RecordsSent' },
    'inIceTrigger' :
        { #'stringHit' : 'TotalRecordsReceived',
        'stringHit' : 'RecordsReceived',
          'trigger' : 'RecordsSent' },
    'iceTopTrigger' :
        { #'icetopHit' : 'TotalRecordsReceived',
        'icetopHit' : 'RecordsReceived',
        'trigger' : 'RecordsSent' },
    'amandaTrigger' :
        { #'selfContained' : 'TotalRecordsReceived',
        'selfContained' : 'RecordsReceived',
          'trigger' : 'RecordsSent' },
    'globalTrigger' :
        { #'trigger' : 'TotalRecordsReceived',
        'trigger' : 'RecordsReceived',
          'glblTrig' : 'RecordsSent' },
    'eventBuilder' :
        { #'glblTrig' : 'TotalRecordsReceived',
          'glblTrig' : 'RecordsReceived',
          'rdoutReq' : 'RecordsSent',
          #'rdoutData' : 'TotalRecordsReceived',
          'rdoutData' : 'RecordsReceived',
          'backEnd' : 'NumEventsSent' },
    'secondaryBuilders' :
        { #'moniData' : 'TotalRecordsReceived',
          'moniData' : 'RecordsReceived',
          'moniBuilder' : 'TotalDispatchedData',
          #'snData' : 'TotalRecordsReceived',
          'snData' : 'RecordsReceived',
          'snBuilder' : 'TotalDispatchedData',
          #'tcalData' : 'TotalRecordsReceived',
          'tcalData' : 'RecordsReceived',
          'tcalBuilder' : 'TotalDispatchedData',
          },
}

class Component(object):
    """Component name/number"""

    def __init__(self, fileName=None):
        if fileName is None:
            compName = 'unknown'
            compNum = 0
        else:
            if len(fileName) < 5 or fileName[-5:] != '.moni':
                raise ValueError, 'Non-moni filename "%s"' % fileName

            baseName = os.path.basename(fileName)
            idx = baseName.rfind('-')
            if idx <= 0:
                raise ValueError, \
                    "Didn't find '-' separator in \"%s\"" % fileName

            compName = baseName[:idx]
            if not COMP_FIELDS.has_key(compName):
                raise ValueError, 'Unknown component "%s" in "%s"' % \
                    (compName, fileName)

            try:
                compNum = int(baseName[idx+1:-5])
            except:
                compNum = 0

            if compName == 'stringHub':
                if compNum % 100 == 0:
                    compName = 'amandaHub'
                elif compNum % 100 > 80:
                    compName = 'icetopHub'

        self.name = compName
        self.num = compNum

        self.fullStr = None
        self.hash = None

    def __hash__(self):
        if self.hash is None:
            self.hash = ((hash(self.name) * 100) % sys.maxint) + \
                (self.num % 100)
        return self.hash

    def __str__(self):
        if self.fullStr is None:
            if self.num == 0:
                self.fullStr = self.name
            else:
                self.fullStr = "%s-%d" % (self.name, self.num)

        return self.fullStr

def computeRates(dataDict):
    """Compute rates from the data saved in the data dictionary"""
    keys = dataDict.keys()
    keys.sort()

    prevTime = None
    firstTime = None

    rates = []

    for k in keys:
        if prevTime is None:
            firstTime = k
        else:
            secs = k - prevTime
            vals = dataDict[k] - dataDict[prevTime]
            rates.append(float(vals) / float(secs))

        prevTime = k

    if len(rates) == 0:
        rates = None
        totRate = None
    elif len(rates) == 1:
        totRate = rates[0]
        rates = None
    else:
        totSecs = prevTime - firstTime
        totVals = dataDict[prevTime] - dataDict[firstTime]
        totRate = float(totVals) / float(totSecs)

    return (totRate, rates)

def fixValue(valStr):
    """
    Convert a string containing a single integer or a list of integers
    into a single long value.
    """
    if not valStr.startswith('['):
        return long(valStr)

    tot = 0
    idx = 0
    while idx < len(valStr) and valStr[idx] != ']':
        nxt = valStr.find(',', idx)
        if nxt < idx:
            nxt = valStr.find(']', idx)
        subStr = valStr[idx+1:nxt]
        try:
            tot += long(subStr)
        except ValueError, ex:
            print >>sys.stderr, \
                "Couldn't get integer value for '%s' ('%s' idx %d nxt %d)" % \
                (subStr, valStr, idx, nxt)
        idx = nxt + 1

    return tot

def processDir(dirName):
    """Process all .moni files in the specified directory"""
    allData = {}
    for entry in os.listdir(dirName):
        if entry.endswith('.log') or entry.endswith('.html'):
            continue

        try:
            comp = Component(entry)
        except ValueError, msg:
            print >>sys.stderr, str(msg)
            continue

        allData[comp] = processFile(os.path.join(dirName, entry), comp)

    return allData

def processFile(fileName, comp):
    """Process the specified file"""
    if not COMP_FIELDS.has_key(comp.name):
        flds = None
    else:
        flds = COMP_FIELDS[comp.name]

    data = {}

    secName = None
    secTime = None

    secLastSaved = {}
    secSeenData = {}

    fd = open(fileName, 'r')
    for line in fd:
        line = line.rstrip()
        if len(line) == 0:
            secName = None
            secTime = None
            continue

        if secName is not None:
            m = MONILINE_PAT.match(line)
            if m:
                name = m.group(1)
                vals = m.group(2)

                if flds is None or flds[secName] == name:
                    if secTime > secLastSaved[secName] + TIME_INTERVAL:
                        newVal = fixValue(vals)
                        if newVal > 0:
                            data[secName][secTime] = newVal
                            secLastSaved[secName] = secTime
                    elif vals != '0':
                        secSeenData[secName] = (secTime, vals)
                continue

        m = MONISEC_PAT.match(line)
        if m:
            nm = m.group(1)
            if not flds.has_key(nm):
                continue

            secName = nm
            mSec = float(m.group(3)) / 1000000.0
            secTime = time.mktime(time.strptime(m.group(2), TIMEFMT)) + mSec

            if not data.has_key(secName):
                data[secName] = {}
                secLastSaved[secName] = 0.0
                secSeenData[secName] = None

    for k in data:
        if not secSeenData.has_key(k) or secSeenData[k] is None:
            continue

        (lastTime, lastVals) = secSeenData[k]
        if not data[k].has_key(lastTime):
            data[k][lastTime] = fixValue(lastVals)

    return data

def reportDataRates(allData):
    """Report the DAQ data rates"""
    if not DATA_ONLY:
        print 'Data Rates:'
    reportList = [('stringHub', 'stringHit'),
                  ('inIceTrigger', 'stringHit'),
                  ('icetopHub', 'icetopHit'),
                  ('iceTopTrigger', 'icetopHit'),
                  ('amandaTrigger', 'selfContained'),
                  ('amandaTrigger', 'trigger'), ('inIceTrigger', 'trigger'),
                  ('iceTopTrigger', 'trigger'),
                  ('globalTrigger', 'trigger'), ('globalTrigger', 'glblTrig'),
                  ('eventBuilder', 'glblTrig'), ('eventBuilder', 'rdoutReq'),
                  ('amandaHub', 'rdoutReq'), ('stringHub', 'rdoutReq'),
                  ('icetopHub', 'rdoutReq'),
                  ('amandaHub', 'rdoutData'), ('stringHub', 'rdoutData'),
                  ('icetopHub', 'rdoutData'),
                  ('eventBuilder', 'rdoutData'),
                  ('eventBuilder', 'backEnd')
                  ]
    reportRatesInternal(allData, reportList)

def reportMonitorRates(allData):
    """Report the DAQ monitoring rates"""
    print 'Monitoring Rates:'
    reportList = [('amandaHub', 'moniData'), ('stringHub', 'moniData'),
                  ('icetopHub', 'moniData'), ('secondaryBuilders', 'moniData'),
                  ('secondaryBuilders', 'moniBuilder')]
    reportRatesInternal(allData, reportList)

def reportRatesInternal(allData, reportList):
    """Report the rates for the specified set of values"""
    compKeys = allData.keys()
    compKeys.sort()

    combinedComp = None
    combinedField = None
    combinedRate = None

    for rptTuple in reportList:
        isCombined = rptTuple[0].endswith('Hub') or \
            (rptTuple[0].endswith('Trigger') and
             rptTuple[0] != 'globalTrigger' and rptTuple[1] == 'trigger')
                 
        if combinedField is not None:
            if not isCombined or combinedField != rptTuple[1]:
                print '    %s.%s: %f' % \
                    (combinedComp, combinedField, combinedRate)
                combinedComp = None
                combinedField = None
                combinedRate = None

        if isCombined:
            if combinedField is None:
                combinedComp = 'All %ss' % rptTuple[0]
                combinedField = rptTuple[1]
                combinedRate = 0.0
            elif combinedComp != None:
                if rptTuple[0].endswith('Hub'):
                    combinedComp = 'All Hubs'
                else:
                    combinedComp = 'All Triggers'

        needNL = False
        for comp in compKeys:
            if not comp.name == rptTuple[0]:
                continue

            for sect in allData[comp]:
                if sect != rptTuple[1]:
                    continue

                rateTuple = computeRates(allData[comp][sect])
                if not isCombined or PRINT_VERBOSE:
                    if not isCombined:
                        indent = ''
                    else:
                        indent = '    '
                    if rateTuple[0] is None:
                        print '    %s%s.%s: Not enough data' % \
                            (indent, comp, sect)
                    elif rateTuple[1] is None:
                        print '    %s%s.%s: %f' % \
                            (indent, comp, sect, rateTuple[0])
                    else:
                        if EXTRA_VERBOSE:
                            print '    %s%s.%s: %s  Total: %f' % \
                                (indent, comp, sect, str(rateTuple[1]),
                                 rateTuple[0])
                        else:
                            print '    %s%s.%s: %f' % \
                                (indent, comp, sect, rateTuple[0])
                    needNL = False

                if combinedRate is not None and rateTuple[0] is not None:
                    combinedRate += rateTuple[0]

        if needNL:
            print ''
            needNL = False

def reportSupernovaRates(allData):
    """Report the DAQ supernova rates"""
    print 'Supernova Rates:'
    reportList = [('amandaHub', 'snData'), ('stringHub', 'snData'),
                  ('icetopHub', 'snData'), ('secondaryBuilders', 'snData'),
                  ('secondaryBuilders', 'snBuilder')]
    reportRatesInternal(allData, reportList)

def reportTimeCalRates(allData):
    """Report the DAQ time calibration rates"""
    print 'TimeCal Rates:'
    reportList = [('amandaHub', 'tcalData'), ('stringHub', 'tcalData'),
                  ('icetopHub', 'tcalData'), ('secondaryBuilders', 'tcalData'),
                  ('secondaryBuilders', 'tcalBuilder')]
    reportRatesInternal(allData, reportList)

def reportRates(allData):
    """Report the DAQ rates"""
    if not DATA_ONLY:
        reportMonitorRates(allData)
        reportSupernovaRates(allData)
        reportTimeCalRates(allData)
    reportDataRates(allData)

if __name__ == "__main__":
    badArg = False
    dirList = []
    fileList = []
    for arg in sys.argv[1:]:
        if arg == '-v':
            if not PRINT_VERBOSE:
                PRINT_VERBOSE = True
            else:
                EXTRA_VERBOSE = True
        elif arg == '-vv':
            PRINT_VERBOSE = True
            EXTRA_VERBOSE = True
        elif arg == '-d':
            DATA_ONLY = True
        elif os.path.isdir(arg):
            dirList.append(arg)
        elif os.path.exists(arg):
            fileList.append(arg)
        else:
            print >>sys.stderr, 'Unknown argument "%s"' % arg
            badArg = True

    if len(dirList) > 0 and len(fileList) > 0:
        print >>sys.stderr, 'Cannot specify both directories and files'
        badArg = True
    elif len(dirList) == 0 and len(fileList) == 0:
        print >>sys.stderr, 'Please specify a moni file or directory'
        badArg = True

    if badArg:
        print >>sys.stderr, 'Usage: %s' + \
            ' [-d(ataOnly)]' + \
            ' [-v(erbose)]' + \
            ' (moniDir | moniFile [...])'
        sys.exit(1)

    if len(fileList) > 0:
        allData = {}
        for f in fileList:
            try:
                comp = Component(f)
            except ValueError, msg:
                print >>sys.stderr, str(msg)
                comp = Component()

            allData[comp] = processFile(f, comp)
            reportRates(allData)
    else:
        for d in dirList:
            print 'Directory ' + d
            allData = processDir(d)
            reportRates(allData)
