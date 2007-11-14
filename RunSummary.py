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

class SnippetRunRec:
    """
    Storage class to store, parse and massage HTML snippets
    """
    def __init__(self, fileName):
        # Snippet sample for illustrative purposes only, to help explain the regexp below:
        sample_snippet_html = """

<tr>
<td align=center>100887</td>
<td align=center bgcolor="eeeeee">2007-02-22&nbsp;00:56:43.728586</td>
<td align=center><font size=-2>4496203</font></td>
<td align=center bgcolor="eeeeee">2007-02-22&nbsp;01:01:44.038826</td>
<td align=center><font size=-2>4496504</font></td>
<td align=center bgcolor="eeeeee">300</td>
<td align=center>20207</td>
<td align=center bgcolor="eeeeee">67.36</td>
<td align=center bgcolor=CCFFCC><a href="100887_20070222_010150_000306/daqrun100887//run.html">SUCCESS</a></td>
<td align=left>sps-icecube-only-001</td>
</tr>
"""

        self.txt      = open(fileName).read()
        self.config   = None
        self.startDay = None
        self.endDay   = None
        self.release  = None
        m = search(r'<tr>.+?<td.+?>.+?</td>\s*<td.+?>(\S+)</td>', self.txt, S)
        if m: self.release = m.group(1)
        m = search(r'.+?(\d\d\d\d\-\d\d\-\d\d).nbsp.+?(\d\d\d\d\-\d\d\-\d\d).nbsp.+?<td.+?>(\S+?)</td>\s*?</tr>',
                   self.txt, S)
        if m:
            self.startDay = m.group(1)
            self.endDay   = m.group(2)
            self.config   = m.group(3)
    
    def html(self, lastRelease, lastConfig, lastStartDay):
        """
        Return HTML, but grey out repeated dates and configurations for visual clarity
        """
        grey = "999999"
        ret = self.txt
        if lastConfig == self.config and self.config != None:
            ret = sub(self.config, "<FONT COLOR=%s>%s</FONT>" % (grey, self.config), ret)
        if lastStartDay == self.startDay and self.startDay != None:
            ret = sub(self.startDay, "<FONT COLOR=%s>%s</FONT>" % (grey, self.startDay), ret)
        if lastRelease == self.release and self.release != None:
            ret = sub(self.release, "<FONT COLOR=%s>%s</FONT>" % (grey, self.release), ret)
        return ret

def checkForRunningProcesses():
    c = popen("pgrep -fl 'python .+RunSummary.py'", "r")
    l = c.read()
    num = len(l.split('\n'))
    if num < 3: return False # get extra \n at end of command
    return True

def check_make_or_exit(dir):
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

def getStatusColor(status):
    # Calculate status color
    statusColor = "EFEFEF"
    if status == "FAIL":
        statusColor = "FF3300"
    elif status == "INCOMPLETE":
        statusColor = "FF9999"
    elif status == "SUCCESS":
        statusColor = "CCFFCC"
    return statusColor

def fmt(s):
    if s != None: return sub('\s', '&nbsp;', str(s))
    return " "

def generateSnippet(snippetFile, runNum, release, starttime, stoptime, dtsec,
                    configName, runDir, status, nEvents):
    snippet = open(snippetFile, 'w')
    
    statusColor = getStatusColor(status)
    
    evStr = "?"
    if nEvents is not None: evStr = nEvents
    if release is None: release = ""

    rateStr = None
    try:
       if dtsec > 0 and nEvents > 0: rateStr = "%2.2f" % (float(nEvents)/float(dtsec))
    except TypeError, t:
       rateStr = "?"
    print >>snippet, """
    <tr>
    <td align=center>%d</td>
    <td align=center bgcolor="eeeeee">%s</td>
    <td align=center>%s</td>
    <td align=center bgcolor="eeeeee">%s</td>
    <td align=center>%s</td>
    <td align=center bgcolor="eeeeee">%s</td>
    <td align=center>%s</td>
    <td align=center bgcolor=%s><a href="%s">%s</a></td>
    <td align=left>%s</td>
    </tr>
    """ % (runNum, release, fmt(starttime), fmt(stoptime),
           fmt(dtsec), evStr, fmt(rateStr),
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

def dtSeconds(t0, t1):
    if t0 == None or t1 == None: return None
    dt = t1-t0
    return dt.days*86400 + dt.seconds

def toSeconds(t):
    if t == None: return None
    return t.days*86400 + t.seconds

def makeRunReport(snippetFile, dashFile, release, infoPat, runInfo, configName,
                      status, nEvents, absRunDir, relRunDir):

    starttime = dashTime(getDashEvent(dashFile, r'Started run \d+ on run set'))
    stoptime  = dashTime(getDashEvent(dashFile, r'Stopping run'))
    if not stoptime:
        stoptime = dashTime(getDashEvent(dashFile, r'Recovering from failed run'))
    if not stoptime:
        stoptime = dashTime(getDashEvent(dashFile, r'Failed to start run'))
    if not stoptime:
        print "WARNING: no stop time for %s!" % dashFile
        dtsec    = None
    else:
        j0 = jan0(stoptime.year)
        #startsec = dtSeconds(j0, starttime)
        #stopsec  = dtSeconds(j0, stoptime)
        dtsec    = dtSeconds(starttime, stoptime)

    match = search(infoPat, runInfo)
    if not match:
        print "WARNING: run info from file name (%s) doesn't match canonical pattern (%s), skipping!" % \
              (runInfo, infoPat)              
        return
    runNum = int(match.group(1))
    year   = int(match.group(2))
    month  = int(match.group(3))
    day    = int(match.group(4))
    hr     = int(match.group(5))
    mins   = int(match.group(6))
    sec    = int(match.group(7))
    dur    = int(match.group(8))

    generateSnippet(snippetFile, runNum, release, starttime, stoptime, dtsec,
                    configName, relRunDir+"/run.html", status, nEvents)
    makeSummaryHtml(absRunDir, runNum, release, configName, status, nEvents,
                    starttime, stoptime, dtsec)

def escapeBraces(txt):
    """
    Escape HTML control characters '<' and '>' so that preformatted text appears
    correctly in a Web page.
    """
    return txt.replace(">","&GT;").replace("<","&LT;")

def makeSummaryHtml(logLink, runNum, release, configName, status, nEvents,
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

    eventStr = "(check monitoring files)"
    if nEvents is not None: eventStr = nEvents
    if release is None: release = ""

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
            getStatusColor(status), status)

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
    
    check_make_or_exit(opt.outputDir)

    latestTime = getLatestFileTime(opt.spadeDir)
    doneTime   = getDoneFileTime(opt.outputDir)
    if latestTime and doneTime and latestTime < doneTime and not opt.replaceAll: raise SystemExit

    runDir = join(opt.outputDir, "runs")
    check_make_or_exit(runDir)

    picFile = "/net/user/pdaq/daq-reports/images/icecube_pale.jpg"
    if not exists(picFile):
        print "%s doesn't exist!" % picFile; raise SystemExit

    firstSummaryHtml = runDir + "/index.html"
    allSummaryHtml   = runDir + "/all.html"
    firstSummaryFile = open(firstSummaryHtml, "w")
    allSummaryFile   = open(allSummaryHtml, "w")
    print runDir
    if search(r'daq-reports/spts64', runDir):
        title = "SPTS64 Run Summaries"
    elif search(r'daq-reports/sps', runDir):
        title = "SPS Run Summaries"
    else:
        title = "IceCube DAQ Run Summaries"
    top = """
    <head><title>%s</title></head>
    <html>
    <body background='%s'>
    <table>
    <tr>
     <td>
      <img src="/net/user/pdaq/daq-reports/images/header.gif">
     </td>
     <td valign="bottom">
      <A HREF="http://internal.icecube.wisc.edu/status/detector-summary.xml">Current SPS Status</A><br>
      <A HREF="http://internal.icecube.wisc.edu/status/detector-daily.xml">Daily SPS Status</A><br>
      Detailed <A HREF="http://icecube.berkeley.edu/i3-monitoring/2007/monitor.shtml">Detector Monitoring</A> (UCB)
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
    """ % (title, picFile)

    print >>allSummaryFile, top
    print >>firstSummaryFile, top

    tarlist = recursiveGetTarFiles(opt.spadeDir)
    if opt.inclusionDir:
        processInclusionDir(opt.inclusionDir)
        tarlist += recursiveGetTarFiles(opt.inclusionDir)
    tarlist.sort(cmp)

    numRuns          = 0
    maxFirstFileRuns = 100
    prevRun          = None
    prevConfig       = None
    prevStartDay     = None
    prevRelease      = None
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
            check_make_or_exit(outDir)
            tarFile     = f
            extractedTarball = False

            size = getFileSize(tarFile)
            if opt.maxTarMegs and size > opt.maxTarMegs*100000:
                continue

            copyFile    = outDir + "/" + basename(f)
            datTar      = outDir + "/" + prefix + runInfoString + ".dat.tar"
            snippetFile = outDir + "/.snippet"
            linkDir     = runInfoString + "/"
            nEvents     = None

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

                        s = search(r'Version Info:.+\s+(\S+)\s+\d+\n', dashContents)
                        if s: release = s.group(1)
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
                              configName, status, nEvents, runDir+"/"+linkDir,
                              linkDir)

            if prevRun and (runNum != prevRun-1):
                skippedRun = True
            else:
                skippedRun = False
            prevRun = runNum
            
            # Write summaries for first 100 runs only:
            skipper = """<TR HEIGHT=2>
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
            
            numRuns += 1
            runRec = SnippetRunRec(snippetFile)
            
            if numRuns < maxFirstFileRuns:
                if(skippedRun): print >>firstSummaryFile, skipper
                print >>firstSummaryFile, runRec.html(prevRelease, prevConfig, prevStartDay)
                firstSummaryFile.flush()
            elif numRuns == maxFirstFileRuns:
                print >>firstSummaryFile, """
                </table>
                <font size=+2>Click <A HREF="all.html">here</A> for a complete list of runs.<P></font>
                </body>
                </html>
                """
                firstSummaryFile.close()    

            # Write all summaries:
            if(skippedRun): print >>allSummaryFile, skipper
            try:
                print >>allSummaryFile, runRec.html(prevRelease, prevConfig, prevStartDay)
            except IOError, e:
                print "WARNING: couldn't read snippet file (%s)" % exc_string()

            prevConfig   = runRec.config
            prevStartDay = runRec.startDay
            prevRelease  = runRec.release
            
            allSummaryFile.flush()
            
    print >>allSummaryFile, """
    </table>
    </body>
    </html>
    """
    allSummaryFile.close()

    touchDoneFile(opt.outputDir)

if __name__ == "__main__": main()
