#!/usr/bin/env python

# RunSummary.py
# Reporting for pDAQ runs at UW and Pole
# jacobsen@npxdesigns.com
# Dec. 06/Jan. 07
#

import tarfile
import optparse
import datetime
import time
from sys import stderr, argv
from os import listdir, mkdir, environ, stat, popen, symlink, unlink
from os.path import exists, isdir, abspath, basename, join
from shutil import copy
from re import *
from exc_string import *
from tarfile import TarFile

class BadSnippetFormatException(Exception): pass
class BadDayTimeException(Exception):       pass

def datetimeFromDayTime(day, time):
    """
    Convert day, time strings to a single datetime object
    """
    dp = search('^(\d\d\d\d)-(\d\d)-(\d\d)$', day)
    tp = search('^(\d\d):(\d\d):(\d\d)$', time)
    if (not dp) or (not tp):
        raise BadDayTimeException(day+","+time)
    return datetime.datetime(int(dp.group(1)),
                             int(dp.group(2)),
                             int(dp.group(3)),
                             int(tp.group(1)),
                             int(tp.group(2)),
                             int(tp.group(3)))

def dayTime(s):
    """
    Pull out day, time strings from YYYY-MM-DD hh:mm:ss in <s>
    """
    n = search("""
    (\d\d\d\d-\d\d-\d\d).*? # yyyymmdd
    (\d\d:\d\d:\d\d).*?     # hhmmss
    """, s, S|X)
    if n:
        return (n.group(1), n.group(2))
    else:
        return (None, None)

class SnippetRunRec:
    """
    Storage class to store, parse and massage HTML snippets
    """
    def __init__(self, fileName):
        self.txt       = open(fileName).read()
        self.run       = None
        self.config    = None
        self.startDay  = None
        self.stopDay   = None
        self.release   = None
        self.startTime = None
        self.stopTime  = None
        m = search("""
           <tr>.*?                                           # Start table
           <td.*?div\ class="run"\s*>(.*?)</div></td>.*?     # Run
           <td.*?div\ class="release"\s*>(.*?)</div></td>.*? # Release
           <td.*?div\ class="start"  \s*>(.*?)</div></td>.*? # Start time
           <td.*?div\ class="stop"   \s*>(.*?)</div></td>.*? # Stop time
           <td.*?div\ class="config" \s*>(.*?)</div></td>.*? # Config
           """, self.txt, S|X)
        
        if m:
            self.run       = int(m.group(1))
            self.release   = m.group(2)
            start          = m.group(3)
            stop           = m.group(4)
            self.config    = m.group(5)

            self.startDay, self.startTime = dayTime(start)
            self.stopDay,  self.stopTime  = dayTime(stop)
                      
        else:
            raise BadSnippetFormatException(self.txt)
    def __str__(self): return "%d %s %s %s %s %s %s" % (self.run, self.release,
                                                        self.startDay, self.startTime,
                                                        self.stopDay,  self.stopTime,
                                                        self.config)
    def colorTableCell(html, label, color):
        ret = ""
        found = False
        for line in html.split('\n'):
            m = search("""
            <td.*?div\ class="%s.*?"\s*> # Start cell, pick out label
            (.*?)                        # Contents
            </div></td>                  # End cell
            """ % label, line, X)
            if m:
                found = True
                contents = m.group(1)
                n = search("""
                <a\ href=.+?> # Pick out symlinks
                (.+?)        # Contents
                </a>         
                """, contents, X)
                if n: contents = n.group(1)
                # Pick out first part of space-separated content
                #  this is slightly kludgy but the easiest way to make
                #  HH:MM:SS *not* greyed-out
                n = search("(.+?)&nbsp;", contents)
                if n: contents = n.group(1)
                line = sub(">%s<" % contents,
                           ">%s<" % ("<FONT COLOR='%s'>%s</FONT>" % (color,contents)),
                           line)
            ret += line+"\n"
        if not found:
            raise Exception("ERROR: label %s not found!" % label)
        return ret
    colorTableCell = staticmethod(colorTableCell)
    
    def html(self, lastRelease, lastConfig, lastStartDay, lastStopDay):
        """
        Return HTML, but grey out repeated dates and configurations for visual clarity
        """
        grey = "999999"
        ret = self.txt
        if lastConfig == self.config and self.config != None:
            ret = SnippetRunRec.colorTableCell(ret, "config",  grey)
        if lastStartDay == self.startDay and self.startDay != None:
            ret = SnippetRunRec.colorTableCell(ret, "start",   grey)
        if lastStopDay == self.stopDay and self.stopDay != None:
            ret = SnippetRunRec.colorTableCell(ret, "stop",   grey)
        if lastRelease == self.release and self.release != None:
            ret = SnippetRunRec.colorTableCell(ret, "release", grey)
        return ret

def checkForRunningProcesses():
    c = popen("pgrep -fl 'python .+RunSummary.py'", "r")
    l = c.read()
    num = len(l.split('\n'))
    if num < 3: return False # get extra \n at end of command
    return True

def makeDirOrExit(dir):
    if not exists(dir):
        # print ("Creating %s... " % dir),
        try: mkdir(dir, 0755)
        except Exception, e:
            print "Couldn't mkdir %s: %s!" % (dir, e)
            raise SystemExit
        # print "OK."

def getFileSize(f): return stat(f)[6]
def getFileTime(f): return stat(f)[8]

def getLatestFileTime(dir):
    l = listdir(dir)
    latest = None
    for f in l:
        if not search("SPS-pDAQ-run", f): continue
        stat_dat = stat("%s/%s" % (dir, f))
        mtim = stat_dat[8]
        if mtim > latest or latest == None: latest = mtim
    if latest == None: return None
    return datetime.datetime.fromtimestamp(latest)

def touchDoneFile(outputDir):
    x=open(outputDir+"/"+".done", "w")
    print >>x, " "
    x.close()

def getDoneFileTime(outputDir):
    f = outputDir+"/.done"
    if not exists(f): return None
    stat_dat = stat(f)
    return datetime.datetime.fromtimestamp(stat_dat[8])

def eventsRepr(nEvents, cumEvents):
    """
    Convert cumulative event count cumEvents, or (preferably) definitive
    event count nEvents, into a string representation
    """
    evStr = "?"
    if cumEvents is not None: evStr = "<font color=b0c4de>&ge;</font>%s" % cumEvents
    if nEvents is not None: evStr = str(nEvents)
    return evStr

def getStatusColor(status, nEvents, cumEvents):
    # Calculate status color
    yellow  = "F0E68C"
    red     = "FF3300"
    magenta = "FF9999"
    green   = "CCFFCC"
    
    statusColor = "EFEFEF"
    if status == "FAIL":
        statusColor = red
        if type(nEvents).__name__ == "int" and nEvents > 0:
            statusColor = yellow
        if type(cumEvents).__name__ == "int" and cumEvents > 0:
            statusColor = yellow
    elif status == "INCOMPLETE":
        statusColor = magenta
    elif status == "SUCCESS":
        statusColor = green
    return statusColor

def fmt(s):
    if s != None: return sub('\s', '&nbsp;', str(s))
    return " "

def yyyymmdd(t):
    if t is None: return ""
    return "%d-%02d-%02d" % (t.year, t.month, t.day)

def hhmmss(t):
    if t is None: return ""
    return "%02d:%02d:%02d" % (t.hour, t.minute, t.second)

def dashTime(str):
    "Get datetime object from string in form 'yyyy-mm-dd hh:mm:ss.uuuuuu'"
    if not str: return None
    match = search(r'(\d\d\d\d)-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)\.(\d\d\d\d\d\d)', str)
    if not match: return None
    return datetime.datetime(int(match.group(1)),
                             int(match.group(2)),
                             int(match.group(3)),
                             int(match.group(4)),
                             int(match.group(5)),
                             int(match.group(6)),
                             int(match.group(7)))

def generateSnippet(snippetFile, runNum, release, starttime, stoptime, dtsec,
                    rateStr, configName, runDir, status, nEvents, cumEvents):
    snippet = open(snippetFile, 'w')
    
    statusColor = getStatusColor(status, nEvents, cumEvents)
    
    evStr = eventsRepr(nEvents, cumEvents)
    if release is None: release = ""

    startday  = yyyymmdd(starttime)
    starttime = hhmmss(starttime)
    stopday   = yyyymmdd(stoptime)
    stoptime  = hhmmss(stoptime)
    
    print >>snippet, """
    <tr>
    <td align=center>                 <div class="run"    >%d</div></td>
    <td align=center bgcolor="eeeeee"><div class="release">%s</div></td>
    <td align=center>                 <div class="start"  >%s&nbsp;%s</div></td>
    <td align=center bgcolor="eeeeee"><div class="stop"   >%s&nbsp;%s</div></td>
    <td align=center>                 <div class="deltat" >%s</div></td>
    <td align=center bgcolor="eeeeee"><div class="nevents">%s</div></td>
    <td align=center>                 <div class="rate"   >%s</div></td>
    <td align=center bgcolor=%s>      <div class="status" ><a href="%s">%s</a></div></td>
    <td align=left>                   <div class="config" >%s</div></td>
    </tr>
    """ % (runNum, release, startday, starttime, stopday, stoptime,
           fmt(dtsec), evStr, rateStr,
           statusColor, runDir, status, configName)
    snippet.close()
    return

def makeTable(files, name):
    html = ""
    if files:
        html += "<PRE>\n\n</PRE><TABLE>"
        virgin = True
        for l in files:
            html += "<TR>"
            if virgin: html += r'<TD ALIGN="right"><FONT COLOR=888888>%s</FONT></TD>' % name
            else: html += "<TD></TD>"
            virgin = False
            html += r'<TD><A HREF="%s">%s</A></TD>' % (l, l)
            html += "</TR>"
        html += "</TABLE>"
    return html

def getDashEvent(dashFile, pat):
    df = open(dashFile, "r")
    ret = None
    for l in df.readlines():
        if search(pat, l):
            match = search(r'^DAQRun \[(.+?)\]', l)
            if match:
                ret = match.group(1)
                break
    df.close()
    return ret

def jan0(year):
    return datetime.datetime(year, 1, 1, 0, 0, 0)

def dtSeconds(t0, t1):
    if t0 == None or t1 == None: return None
    dt = t1-t0
    return dt.days*86400 + dt.seconds

def toSeconds(t):
    if t == None: return None
    return t.days*86400 + t.seconds

def makeRunReport(snippetFile, dashFile, release, infoPat, runInfo, configName,
                      status, nEvents, cumEvents, lastTimeStr, absRunDir, relRunDir):
    """
    Calculate start and stop times, duration and rate.  Make HTML summary line
    and summary page for the run.  If the run failed, use the last "good" event
    count and rate (cumEvents and lastTimeStr) to calculate rate.
    """
    starttime = dashTime(getDashEvent(dashFile, 'Started run \d+ on run set'))
    stoptime  = dashTime(getDashEvent(dashFile, 'Stopping run'))
    lasttime  = dashTime(lastTimeStr)
    dtsec     = None
    if not stoptime:
        stoptime = dashTime(getDashEvent(dashFile, r'Recovering from failed run'))
    if not stoptime:
        stoptime = dashTime(getDashEvent(dashFile, r'Failed to start run'))
    if not stoptime:
        stoptime = lasttime

    rateStr = ""
    if stoptime:
        if status == "SUCCESS":
            dtsec  = dtSeconds(starttime, stoptime)
            if dtsec > 0:
                rateStr = "%2.2f" % (float(nEvents)/float(dtsec))
        else:
            dtsec  = dtSeconds(starttime, lasttime)
            if dtsec > 0 and cumEvents > 0: # Skip runs w/ zero 'cumEvents' since it misses
                                            # Azriel's requirements for rate calculation
                rateStr = "%2.2f" % (float(cumEvents)/float(dtsec))

    match = search(infoPat, runInfo)
    if not match:
        print "WARNING: run info from file name (%s) doesn't match canonical pattern (%s), skipping!" % \
              (runInfo, infoPat)              
        return
    runNum = int(match.group(1))

    generateSnippet(snippetFile, runNum, release, starttime, stoptime, dtsec, rateStr,
                    configName, relRunDir+"/run.html", status, nEvents, cumEvents)
    makeSummaryHtml(absRunDir, runNum, release, configName, status, nEvents, cumEvents,
                    starttime, stoptime, dtsec)

def escapeBraces(txt):
    """
    Escape HTML control characters '<' and '>' so that preformatted text appears
    correctly in a Web page.
    """
    return txt.replace(">","&GT;").replace("<","&LT;")

def makeSummaryHtml(logLink, runNum, release, configName, status, nEvents, cumEvents,
                    starttime, stoptime, dtsec):
    
    files = listdir(logLink)
    mons  = []
    logs  = []
    for f in files:
        if search(r'\.log$', f): logs.append(f)
        if search(r'\.moni$', f): mons.append(f)
    mons.sort()
    logs.sort()

    html = open(logLink+"/run.html", "w")

    if release is None: release = ""

    eventStr = eventsRepr(nEvents, cumEvents)

    print >>html, "<HEAD><TITLE>Run %d</TITLE></HEAD>" % runNum
    print >>html, "<HTML>"
    print >>html, "<TABLE><TR><TD BGCOLOR=EEEEEE VALIGN=TOP>"
    print >>html, """
<TABLE>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Run</FONT></TD><TD><FONT SIZE=+3>%d</FONT></TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>pDAQ&nbsp;Release</FONT></TD><TD>%s</TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Configuration</FONT></TD><TD>%s</TD></TR>
 <TR><TD ALIGN="right" VALIGN="top">
  <FONT COLOR=888888>Start Date</FONT></TD><TD VALIGN="top">%s</TD>
 </TR>
 <TR><TD ALIGN="right" VALIGN="top">
  <FONT COLOR=888888>End Date</FONT></TD><TD VALIGN="top">%s</TD>
 </TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Duration</FONT></TD><TD>%s seconds</TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Events</FONT></TD><TD>%s</TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Status</FONT></TD><TD BGCOLOR=%s>%s</TD></TR>
</TABLE>
     """ % (runNum, release, configName, fmt(starttime), fmt(stoptime), dtsec, eventStr,
            getStatusColor(status, nEvents, cumEvents), status)

    print >>html, makeTable(logs, "Logs")
    print >>html, makeTable(mons, "Monitoring")
    
    print >>html, "</TD><TD VALIGN=top>"
        
    dashlog = logLink+"/dash.log"
    if exists(dashlog):
        print >>html, "<PRE>"
        print >>html, escapeBraces(open(dashlog).read())
        print >>html, "</PRE>"
        
    print >>html, "</TD></TR></TABLE>"
    print >>html, "</HTML>"
    html.close()

infoPat = r'(\d+)_(\d\d\d\d)(\d\d)(\d\d)_(\d\d)(\d\d)(\d\d)_(\d+)'

def cmp(a, b):
    amatch = search(infoPat, a)
    bmatch = search(infoPat, b)
    if not amatch: return 0
    if not bmatch: return 0
    n = 2
    for n in [2, 3, 4, 5, 6, 7, 1, 8]:
        ia = int(amatch.group(n)); ib = int(bmatch.group(n))
        if ia != ib: return ib-ia
    return 0

def processInclusionDir(dir):
    """
    Prep 'included-by-hand' directories so that they look like SPADEd tarballs;
    do the best we can, pick the last log time from dash.log to name the tarball
    """
    l = listdir(dir)
    for dirfile in l:
        m = search(r'^daqrun(\d+)$', dirfile)
        if m:
            run = int(m.group(1))
            dashFile = join(dir, dirfile, 'dash.log')
            if exists(dashFile):
                tarFile = None
                for f in open(dashFile).readlines():
                    p = search(r'^DAQRun \[(\d+)-(\d+)-(\d+) (\d+):(\d+):(\d+)', f)
                    if p:
                        tarFile = join(dir, "SPS-pDAQ-run-%d_%04d%02d%02d_%02d%02d%02d_000000.dat.tar" % \
                                       (run,
                                        int(p.group(1)),
                                        int(p.group(2)),
                                        int(p.group(3)),
                                        int(p.group(4)),
                                        int(p.group(5)),
                                        int(p.group(6))))
                if tarFile and not exists(tarFile): # !
                    tf = TarFile(tarFile, "w")
                    tf.add(join(dir, dirfile), dirfile, True)
                    tf.close()
        
def recursiveGetTarFiles(dir):
    l = listdir(dir)
    ret = []
    for f in l:
        fq = "%s/%s" % (dir, f)
        if isdir(fq):
            ret += recursiveGetTarFiles(fq)
        else:
            if search("SPS-pDAQ-run-%s" % infoPat, f):
                ret.append("%s/%s" % (dir, f))
    return ret

def makePlaceHolderFile(shortName, dir, size):
    x = open(dir+"/"+shortName, "w")
    print >>x, "(FILE TOO LARGE (%s bytes), NOT EXTRACTED)" % size
    x.close()
    
def daysOf(f):
    t = getFileTime(f)
    now = int(time.time())
    dt = now-t
    # print "daysOf %s %d %d %d" % (f, t, now, dt)
    return dt/86400

def createTopHTML(runDir, liveTime24hr=None, liveTime7days=None, refresh=None):
    bodyHTML = "<BODY>"
    logoHTML = ""
    bodyFile = "/net/user/pdaq/daq-reports/images/icecube_pale.jpg"
    logoFile = "/net/user/pdaq/daq-reports/images/header.gif"
    if exists(bodyFile): bodyHTML = "<BODY background='%s'>" % bodyFile
    if exists(logoFile): logoHTML = "<IMG SRC='%s'>" % logoFile

    if refresh:
        refreshHTML = "<META http-equiv='refresh' content='%d'>" % refresh
    else:
        refreshHTML = ""
        
    if search(r'daq-reports/spts64', runDir):
        title = "SPTS64 Run Summaries"
    elif search(r'daq-reports/sps', runDir):
        title = "SPS Run Summaries"
    else:
        title = "IceCube DAQ Run Summaries"
    if liveTime24hr != None and liveTime7days != None:
        lt = """
<table>
<tr><td align=right><font color="555555">24 hour livetime:</font></td><td>%2.2f%%</td></tr>
<tr><td align=right><font color="555555"  >7 day livetime:</font></td><td>%2.2f%%</td></tr>
<tr>
<td colspan=2 width=200px>
<font size="-2" color="777777">
Fine print: live time is calculated up to the end of the most recent run.
At times, run information may be delayed by 24 hours or longer, so detector uptime should be considered
a lower limit.  Times are based on best guess start and end times for the pDAQ run.
</font>
</td>
</tr>
</table>

""" % (liveTime24hr, liveTime7days)
    else:
        lt = ""
        
    top = """
    <head>
    <title>%s</title>
    %s
    </head>
    <html>
    %s
    <table>
    <tr>
     <td valign="top">
      %s<br>
      <A HREF="http://internal.icecube.wisc.edu/status/detector-summary.xml">Current SPS Status</A><br>
      <A HREF="http://internal.icecube.wisc.edu/status/detector-daily.xml">Daily SPS Status</A><br>
      Detailed <A HREF="http://icecube.berkeley.edu/i3-monitoring/2007/monitor.shtml">Detector Monitoring</A> (UCB)
     </td>
     <td>
      %s
     </td>
    </tr>
    </table>
    <br>
    <table>
    <tr>
     <td align=center><b><font size=-1>Run</font></b></td>
     <td align=center><b><font size=-1>Release</font></b></td>
     <td align=center><b><font size=-1>Run Start Time</font></b></td>
     <td align=center><b><font size=-1>Run Stop Time</font></b></td>
     <td align=center><b><font size=-1>Duration (seconds)</font></b></td>
     <td align=center><b><font size=-1>Num. Events</font></b></td>
     <td align=center><b><font size=-1>Rate (Hz)</font></b></td>
     <td align=center><b><font size=-1>Status</font></b></td>
     <td align=left><b><font size=-1>Config</font></b></td>
    </tr>
    """ % (title, refreshHTML, bodyHTML, logoHTML, lt)
    return top

def createBotHtml(isSubset=False):
    if isSubset:
        return """
</table>
<font size=+2>Click <A HREF="all.html">here</A> for a complete list of runs.<P></font>
</body>
</html>
"""
    else:
        return """
</table>
</body>
</html>
"""

# HTML snippet for separating missing runs
def skipper():
    return """<TR HEIGHT=2>
<TD ALIGN=center>...</TD>
<TD BGCOLOR='eeeeee'></TD>
<TD></TD>
<TD BGCOLOR='eeeeee'></TD>
<TD></TD>
<TD BGCOLOR='eeeeee'></TD>
<TD></TD>
<TD BGCOLOR='eeeeee'></TD>
<TD></TD>
<TD BGCOLOR='eeeeee'></TD>
</TR>"""

findpat = "^\d+_(\d\d\d\d\d\d\d\d)_(\d\d\d\d\d\d)_\d+$"

def byDate(a, b):
    pa = search(findpat, a)
    pb = search(findpat, b)
    if (not pa) or (not pb): return 0
    if pa.group(1) > pb.group(1): return -1
    if pa.group(1) < pb.group(1): return 1
    if pa.group(2) > pb.group(2): return -1
    if pa.group(2) < pb.group(2): return 1
    return 0

def findall(pat, l):
    ret = []
    for item in l:
        if search(pat, item): ret.append(item)
    return ret

def getSortedRunReportDirs(outputDir):
    rundirs = findall(findpat, listdir(outputDir))
    rundirs.sort(byDate)
    return [join(outputDir, x) for x in rundirs]

def getRunRecs(sortedDirs):
    for dir in sortedDirs:
        sf = join(dir, ".snippet")
        if exists(sf):
            try:
                rec = SnippetRunRec(sf)
                yield rec
            except BadSnippetFormatException, e:
                print "WARNING: HTML summary for %d is corrupt ('%s')!" % (rec, e)

def getLiveTimes(runDirs):
    """
    Calculate live time based on run snippets stored in directory list runDirs
    Add increments of time going backwards through recent runs until a run boundary
    is reached which exceeds the 24hr or 7day interval; use only the parts of the
    run which live inside that interval.
    """
    lastTime    = None
    lastLess24h = None
    lastLess7d  = None
    sum24h      = 0
    sum7d       = 0
    done24h     = False
    done7d      = False
    for rec in getRunRecs(runDirs):
        runStop = datetimeFromDayTime(rec.stopDay, rec.stopTime)
        if not lastTime:
            lastTime = runStop
            lastLess24h = lastTime - datetime.timedelta(1) # 1 day earlier
            lastLess7d  = lastTime - datetime.timedelta(7) # 1 week earlier
        try:
            runStart = datetimeFromDayTime(rec.startDay, rec.startTime)
        except TypeError, t: # Skip runs with missing start times
            continue
        
        if runStop <= lastLess24h:
            done24h = True
        if runStop <= lastLess7d:
            done7d  = True

        if not done24h:
            startMark = runStart
            if startMark <= lastLess24h:
                startMark = lastLess24h
                done24h = True
            dt = runStop-startMark
            inc = dt.days*86400 + dt.seconds
            sum24h += inc

        if not done7d:
            startMark  = runStart
            if startMark <= lastLess7d:
                startMark = lastLess7d
                done7d = True
            dt = runStop-startMark
            inc = dt.days*86400 + dt.seconds
            sum7d += inc
            
        if done24h and done7d:
            break
    return (sum24h*100./86400., sum7d*100./(86400.*7.))

def generateOutputPage(runDirName, runDirectories, liveTime24hr, liveTime7days, htmlName,
                       maxRuns=None):
    prevRelease  = None
    prevConfig   = None
    prevStartDay = None
    prevStopDay  = None
    prevRun      = None
    numRuns      = 0
    print "Making", htmlName
    htmlFile = open(join(runDirName, htmlName), "w")
    print >>htmlFile, createTopHTML(runDirName, liveTime24hr, liveTime7days,
                                    maxRuns and 300 or None) # Refresh abbreviated page every 5min
    for rec in getRunRecs(runDirectories):
        if prevRun and (rec.run != prevRun-1):
            skippedRun = True
        else:
            skippedRun = False
        prevRun = rec.run
        if skippedRun: print >>htmlFile, skipper()
        print >>htmlFile, rec.html(prevRelease, prevConfig, prevStartDay, prevStopDay)
        htmlFile.flush()
        if rec.config   is not None: prevConfig   = rec.config
        if rec.startDay is not None: prevStartDay = rec.startDay
        if rec.stopDay  is not None: prevStopDay  = rec.stopDay
        if rec.release  is not None: prevRelease  = rec.release
        numRuns += 1
        if maxRuns is not None and numRuns >= maxRuns:
            break
    print >>htmlFile, createBotHtml(maxRuns != None and True or False)
    htmlFile.close()

def main():
    p = optparse.OptionParser()
    p.add_option("-s", "--spade-dir",   action="store", type="string", dest="spadeDir")
    p.add_option("-o", "--output-dir",  action="store", type="string", dest="outputDir")
    p.add_option("-a", "--replace-all", action="store_true",           dest="replaceAll")
    p.add_option("-v", "--verbose",     action="store_true",           dest="verbose")
    p.add_option("-m", "--max-mb",      action="store", type="int",    dest="maxTarMegs")
    p.add_option("-l", "--use-symlinks",
                                        action="store_true",           dest="useSymlinks")
    p.add_option("-i", "--ignore-process",
                                        action="store_true",           dest="ignoreExisting")
    p.add_option("-t", "--oldest-time", action="store", type="int",    dest="oldestTime")
    p.add_option("-x", "--max-extract-file-mb",
                                        action="store", type="float",  dest="maxFileMegs")
    p.add_option("-r", "--remove-intermediate-tarballs",
                                        action="store_true",           dest="removeTars")
    p.add_option("-p", "--process-inclusions",
                                        action="store", type="string", dest="inclusionDir")
    
    p.set_defaults(spadeDir       = "/mnt/data/spade/localcopies/daq",
                   outputDir      = "%s/public_html/daq-reports" % environ["HOME"],
                   verbose        = False,
                   maxTarMegs     = None,
                   maxFileMegs    = None,
                   useSymlinks    = False,
                   ignoreExisting = False,
                   removeTars     = False,
                   inclusionDir   = False,
                   oldestTime     = 100000,
                   replaceAll     = False)

    opt, args = p.parse_args()

    if not opt.ignoreExisting and checkForRunningProcesses():
        print "RunSummary.py is already running."
        raise SystemExit
    
    if not exists(opt.spadeDir):
        print "Can't find %s... giving up." % opt.spadeDir
        raise SystemExit

    if opt.inclusionDir and not exists(opt.inclusionDir):
        print "Can't find inclusion dir %s... giving up." % opt.inclusionDir
        raise SystemExit
    
    makeDirOrExit(opt.outputDir)

    latestTime = getLatestFileTime(opt.spadeDir)
    doneTime   = getDoneFileTime(opt.outputDir)
    if latestTime and doneTime and latestTime < doneTime and not opt.replaceAll: raise SystemExit

    runDir = join(opt.outputDir, "runs")
    makeDirOrExit(runDir)

    tarlist = recursiveGetTarFiles(opt.spadeDir)
    if opt.inclusionDir:
        processInclusionDir(opt.inclusionDir)
        tarlist += recursiveGetTarFiles(opt.inclusionDir)
    tarlist.sort(cmp)

    maxFirstFileRuns = 100
    for f in tarlist:
        prefix = 'SPS-pDAQ-run-'
        if search(r'.done$', f): continue # Skip SPADE .done semaphores
        if search(r'.sem$', f):  continue # Skip SPADE .sem  semaphores
        match = search(r'%s(\S+?)\.' % prefix, f)
        if match:
            runInfoString = match.group(1)
            match = search(infoPat, runInfoString)
            if not match: continue
            runNum = int(match.group(1))
            outDir = runDir + "/" + runInfoString
            makeDirOrExit(outDir)
            tarFile     = f
            extractedTarball = False

            size = getFileSize(tarFile)
            if opt.maxTarMegs and size > opt.maxTarMegs*100000:
                continue

            copyFile    = outDir + "/" + basename(f)
            datTar      = outDir + "/" + prefix + runInfoString + ".dat.tar"
            snippetFile = outDir + "/.snippet"
            linkDir     = runInfoString + "/"
            nEvents     = None # End of run accounting
            cumEvents   = None # Cumulative event accounting
            lastTimeStr = None
            # Skip files older than oldestTime weeks
            if daysOf(tarFile) > opt.oldestTime: continue

            if opt.verbose: print "%s -> %s" % (f, runInfoString)

            # Skip if tarball has already been copied
            if not exists(snippetFile) or opt.replaceAll:
                # Move tarballs into target run directories
                if not exists(copyFile) or not exists(datTar):
                    tarSize = getFileSize(tarFile)
                    if opt.useSymlinks: vec = "-(l)->"
                    else: vec = "->"
                    if opt.verbose: print "%s(%dB) %s %s/" % (f, tarSize, vec, outDir)

                    # Copy or symlink tarball first
                    if not exists(copyFile):
                        if opt.useSymlinks:
                            symlink(tarFile, copyFile)
                        else:
                            copy(tarFile, copyFile)
                            
                    if not tarfile.is_tarfile(copyFile):
                        if opt.verbose: print "WARNING: bad tar file %s!" % copyFile
                        continue

                    # Extract top tarball
                    if datTar != copyFile:
                        
                        if opt.verbose: print "OPEN(%s)" % copyFile
                        tar = tarfile.open(copyFile)
                        
                        for el in tar.getnames():
                            if search('\.dat\.tar$', el):
                                if opt.verbose: print "Extract %s -> %s" % (el, outDir)
                                tar.extract(el, outDir)
                                extractedTarball = True
                                
                        if opt.verbose: print "CLOSE"
                        tar.close()

                    if not exists(datTar):
                        raise Exception("Tarball %s didn't contain %s!", copyFile, datTar)

                # Extract contents
                status = None; configName = None
                tar = tarfile.open(datTar)
                
                dashFile = None # Pick up during extraction
                release  = None 
                for el in tar.getnames():

                    # Extract contents if not already extracted
                    if opt.replaceAll or not exists("%s/%s" % (outDir, el)):
                        if opt.verbose: print "extracting %s..." % el
                        fsiz = tar.getmember(el).size
                        if opt.maxFileMegs and fsiz > opt.maxFileMegs*1000*1000:
                            if opt.verbose: print "SKIPPING %s (%d bytes)" % (el, fsiz)
                            makePlaceHolderFile(el, outDir, fsiz)
                            continue
                        tar.extract(el, outDir)
                        
                    # Find dash.log
                    if search(r'dash.log', el):
                        dashFile = outDir + "/" + el
                        dashContents = open(dashFile).read()

                        # Get status
                        s = search(r'Run terminated (.+).', dashContents)
                        if s:
                            if s.group(1)=="SUCCESSFULLY": status = "SUCCESS"
                            else: status = "FAIL"

                        s = search(r'config name (.+?)\n', dashContents)
                        if s: configName = s.group(1)
                        else:
                            s = search(r'Run configuration: (.+?)\n', dashContents)
                            if s: configName = s.group(1)

                        s = search(r'\]\s+(\d+).+?events collected', dashContents)
                        if s: nEvents = int(s.group(1))

                        s = search(r'Version Info:.+\s+(\S+)\s+(\d+)\n', dashContents)
                        if s: release = "%s_%s" % (s.group(1), s.group(2)) 

                        lines = findall('\[(.+?)\]\s+(\d+) physics events \(.+? Hz\)\,', dashContents)
                        if lines:
                            lastTimeStr = lines[-1][0]
                            cumEvents   = int(lines[-1][1])
                        
                    # Remember more precise unpacked location for link
                    if search(r'(daqrun\d+)/$', el): 
                        linkDir = runInfoString + "/" + el

                tar.close()

                # Cleanup intermediate tar files
                if extractedTarball and opt.removeTars:
                    if opt.verbose: print "REMOVING %s..." % datTar
                    unlink(datTar)

                if configName == None: continue
                if status == None: status = "INCOMPLETE"

                # Make HTML snippet for run summaries
                makeRunReport(snippetFile, dashFile, release, infoPat, runInfoString, 
                              configName, status, nEvents, cumEvents, lastTimeStr,
                              runDir+"/"+linkDir, linkDir)

    # Iterate over generated directories to find livetime, etc.
    runDirectories = getSortedRunReportDirs(runDir)
    liveTime24hr, liveTime7days = getLiveTimes(runDirectories)
    print "24 hour livetime = %2.3f%%; 7 day livetime = %2.3f%%" % (liveTime24hr, liveTime7days)
    # Produce final output
    generateOutputPage(runDir, runDirectories, liveTime24hr, liveTime7days, "index.html", 100)
    generateOutputPage(runDir, runDirectories, liveTime24hr, liveTime7days, "all.html")
    touchDoneFile(opt.outputDir)

if __name__ == "__main__": main()
