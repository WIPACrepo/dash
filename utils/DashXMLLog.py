import os

import re
from datetime import datetime
from xml.dom import minidom
from DAQTime import DAQDateTime


class DashXMLLogException(Exception):
    pass


class FileNotFoundException(DashXMLLogException):
    pass


class MalformedFileException(DashXMLLogException):
    pass


class DashXMLLog:
    """
    This class will generate an xml logging file for dash.
    The purpose is to generate this for Kirill.
    Apparently he was parsing dash.log and generating a log file.
    The parsing would break as people changed the format of the
    dash.log file.  This code will let you generate an xml log that
    will meet at least his requirements.  You can add more fields to
    this with the 'setField' method.

    A minimum xml logging file should look like this:

    <?xml version="1.0"?>
    <?xml-stylesheet type="text/xsl" href="/2011/xml/DAQRunlog.xsl"?>
    <DAQRunlog>
    <run>117554</run>
    <Release>Dartmoor</Release>
    <Revision>0:0</Revision>
    <Cluster>sps</Cluster>
    <Config>sps-IC79-Erik-Changed-TriggerIDs-V151</Config>
    <StartTime>55584.113903</StartTime>
    <EndTime>55584.227695</EndTime>
    <FirstGoodTime>55584.123003</FirstGoodTime>
    <LastGoodTime>55584.216579</LastGoodTime>
    <TermCondition>SUCCESS</TermCondition>
    <Events>24494834</Events>
    <Moni>60499244</Moni>
    <Tcal>4653819</Tcal>
    <SN>47624256</SN>
    </DAQRunlog>
    """

    DATE_PAT = re.compile(r"(\d\d\d\d)-(\d\d)-(\d\d)\s+" +
                          r"(\d\d?):(\d\d):(\d\d)(\.(\d+))?")

    def __init__(self, dir_name=None, file_name="run.xml",
                 root_elem_name="DAQRunlog",
                 style_sheet_url="/2001/xml/DAQRunlog.xsl"):
        self._dir_name = dir_name
        self._file_name = file_name
        self._path = None

        self._fields = {}
        self._root_elem_name = root_elem_name
        self._style_sheet_url = style_sheet_url

        self._required_fields = ["run", "Release", "Revision", "Cluster",
                                 "Config", "StartTime", "EndTime",
                                 "FirstGoodTime", "LastGoodTime",
                                 "TermCondition", "Events", "Moni", "Tcal",
                                 "SN"]

    def __parseDateTime(self, fld):
        if fld is None:
            return None
        if type(fld) == DAQDateTime or type(fld) == datetime:
            return fld
        m = self.DATE_PAT.match(str(fld))
        if not m:
            raise ValueError("Unparseable date string \"%s\"" % fld)
        dtflds = []
        for i in xrange(6):
            dtflds.append(int(m.group(i+1)))
        if m.group(8) is None:
            subsec = 0
        else:
            ss = m.group(8)
            if len(ss) > 10:
                raise ValueError("Bad subseconds for date string \"%s\"" % fld)
            ss += "0" * (10 - len(ss))
            dtflds.append(int(ss))
        return DAQDateTime(dtflds[0], dtflds[1], dtflds[2], dtflds[3],
                           dtflds[4], dtflds[5], dtflds[6])

    def getPath(self):
        if self._path is None:
            if self._dir_name is not None:
                file_name = os.path.join(self._dir_name, self._file_name)
            else:
                file_name = "run.xml"

                next_num = 1
                while os.path.exists(file_name):
                    file_name = "run-%d.xml" % next_num
                    next_num += 1

            self._path = file_name

        return self._path

    def setField(self, field_name, field_val):
        """Store the name and value for a field in this log file

        Args:
            field_name: A text name for this field
            field_value: A value to associate with this field
            ( must be formattable by %%s )

        Returns:
            Nothing
        """
        if field_name == self._root_elem_name:
            raise DashXMLLogException("cannot duplicate the root element name")

        if field_name in self._fields:
            # field already defined
            # should we do something?
            pass

        self._fields[field_name] = field_val

    def getField(self, field_name):
        if not self._fields.has_key(field_name):
            return None
        return self._fields[field_name]

    def setRun(self, run_num):
        """Set the value for the required 'run' field

        Args:
            run_num: a run number
        """

        self.setField("run", run_num)

    def getRun(self):
        """Get the value for the required 'run' field"""
        fld = self.getField("run")
        if fld is None:
            return None
        return int(fld)

    def setConfig(self, config_name):
        """Set the name of the config file used for this run

        Args:
            config_name: the name of the config file for this run
        """
        self.setField("Config", config_name)

    def getConfig(self):
        """Get the name of the config file used for this run"""
        return self.getField("Config")

    def setCluster(self, cluster):
        """Set the name of the cluster used for this run

        Args:
            cluster: the name of the cluster for this run
        """
        self.setField("Cluster", cluster)

    def getCluster(self):
        """Get the name of the cluster file used for this run"""
        return self.getField("Cluster")

    def setStartTime(self, start_time):
        """Set the start time for this run

        Args:
            start_time: the start time for this run
        """
        self.setField("StartTime", start_time)

    def getStartTime(self):
        """Get the start time for this run"""
        return self.__parseDateTime(self.getField("StartTime"))

    def setEndTime(self, end_time):
        """Set the end time for this run

        Args:
            end_time: the end time for this run
        """
        self.setField("EndTime", end_time)

    def getEndTime(self):
        """Get the end time for this run"""
        return self.__parseDateTime(self.getField("EndTime"))

    def setFirstGoodTime(self, first_time):
        """Set the first good time for this run

        Args:
            first_time: the first good time for this run
        """
        self.setField("FirstGoodTime", first_time)

    def getFirstGoodTime(self):
        """Get the first good time for this run"""
        return self.__parseDateTime(self.getField("FirstGoodTime"))

    def setLastGoodTime(self, last_time):
        """Set the last time for this run

        Args:
            last_time: the last time for this run
        """
        self.setField("LastGoodTime", last_time)

    def getLastGoodTime(self):
        """Get the last time for this run"""
        return self.__parseDateTime(self.getField("LastGoodTime"))

    def setTermCond(self, had_error):
        """Set the termination condition for this run

        Args:
            term_cond: the termination condition for this run
            (False if the run succeeded, True if there was an error)
        """
        if had_error:
            term_cond = "Failure"
        else:
            term_cond = "Success"
        self.setField("TermCondition", term_cond)

    def getTermCond(self):
        """Get the termination condition for this run"""
        fld = self.getField("TermCondition")
        if fld is None:
            return None
        if fld == "Failure":
            return True
        if fld == "Success":
            return False
        raise ValueError("Bad termination condition \"%s\"" % fld)

    def setEvents(self, events):
        """Set the number of events for this run

        Args:
            events: the number of events for this run
        """
        self.setField("Events", events)

    def getEvents(self):
        """Get the number of events for this run"""
        fld = self.getField("Events")
        if fld is None:
            return None
        return int(fld)

    def setMoni(self, moni):
        """Set the number of monitoring events for this run

        Args:
            moni: the number of monitoring events for this run
        """
        self.setField("Moni", moni)

    def getMoni(self):
        """Get the number of monitoring events for this run"""
        fld = self.getField("Moni")
        if fld is None:
            return None
        return int(fld)

    def setTcal(self, tcal):
        """Set the number of time calibration events for this run

        Args:
            tcal: the number of time calibration events for this run
        """
        self.setField("Tcal", tcal)

    def getTcal(self):
        """Get the number of time calibration events for this run"""
        fld = self.getField("Tcal")
        if fld is None:
            return None
        return int(fld)

    def setSN(self, sn):
        """Set the number of supernova events for this run

        Args:
            sn: the number of supernova events for this run
        """
        self.setField("SN", sn)

    def getSN(self):
        """Get the number of supernova events for this run"""
        fld = self.getField("SN")
        if fld is None:
            return None
        return int(fld)

    def setVersionInfo(self, rel, rev):
        """Set the pDAQ release/revision info

        Args:
            rel: pDAQ release name
            rev: pDAQ revision information
        """
        self.setField("Release", rel)
        self.setField("Revision", rev)

    def getVersionInfo(self):
        """Get the release/revision tuple for this run"""
        rel = self.getField("Release")
        if rel is not None:
            rev = self.getField("Revision")
            if rev is not None:
                return (rel, rev)
        return (None, None)

    def _build_document(self):
        """Take the internal fields dictionary, the _root_elem_name,
        and the style sheet url to build an xml document.
        """
        # check for all required xml fields
        fields_known = self._fields.keys()
        fields_known.sort()
        for requiredKey in self._required_fields:
            if requiredKey not in fields_known:
                raise DashXMLLogException(
                    "Missing Required Field %s" % requiredKey)

        doc = minidom.Document()
        processingInstr = doc.createProcessingInstruction(
            "xml-stylesheet",
            "type=\"text/xsl\" href=\"%s\"" % self._style_sheet_url)
        doc.appendChild(processingInstr)

        # create the base element
        base = doc.createElement(self._root_elem_name)
        doc.appendChild(base)

        for key in fields_known:
            elem = doc.createElement(key)
            base.appendChild(elem)

            val = doc.createTextNode("%s" % self._fields[key])
            elem.appendChild(val)

        return doc

    def writeLog(self):
        """Build an xml document with stored state and write it to a file

        Args:
            file_name: the name of the file to which we should write the
            xml log file
        """
        docStr = self.documentToKirillString()

        fd = open(self.getPath(), "w")
        fd.write(docStr)
        fd.close()

    def documentToString(self, indent="\t"):
        """Return a string containing the generated xml document

        Args:
            indent: the indentation character.  used in testing
        """
        doc = self._build_document()

        return doc.toprettyxml(indent=indent)

    def documentToKirillString(self):
        """Apparently some people don't quite know how to download an
        xml parser so we have to write out xml files in a specific format
        to fit a broken hand rolled xml parser"""

        doc = self._build_document()

        if(doc.encoding == None):
            dispStr = "<?xml version=\"1.0\"?>"
        else:
            dispStr = "<?xml version=\"1.0\" encoding=\"%s\"?>" % \
                (doc.encoding)

        # okay here look for any and all processing instructions
        for n in doc.childNodes:
            if(n.nodeType == doc.PROCESSING_INSTRUCTION_NODE):
                dispStr = "%s\n%s" % (dispStr, n.toxml())

        n = doc.getElementsByTagName(self._root_elem_name)[0]
        dispStr = "%s\n<%s>" % (dispStr, self._root_elem_name)
        for n in n.childNodes:
            dispStr = "%s\n\t%s" % (dispStr, n.toxml())
        dispStr = "%s\n</%s>" % (dispStr, self._root_elem_name)

        return dispStr

    @classmethod
    def parse(cls, dir_name=None, file_name="run.xml"):
        if dir_name is None:
            path = file_name
        else:
            path = os.path.join(dir_name, file_name)
        if not os.path.exists(path):
            raise FileNotFoundException("File \"%s\" does not exist" % path)

        try:
            parsed = minidom.parse(path)
        except Exception as ex:
            raise MalformedFileException(
                "Bad run file \"%s\": %s" % (path, ex))

        rootList = parsed.getElementsByTagName("DAQRunlog")
        if len(rootList) == 0:
            raise MalformedFileException("No DAQRunlog entries found" +
                                         " in \"%s\"" % path)
        elif len(rootList) > 1:
            raise MalformedFileException("Multiple DAQRunlog entries found" +
                                         " in \"%s\"" % path)

        runXML = DashXMLLog()
        for node in rootList[0].childNodes:
            if node.nodeType != minidom.Node.ELEMENT_NODE:
                continue
            for kid in node.childNodes:
                if kid.nodeType != minidom.Node.TEXT_NODE:
                    continue
                val = kid.nodeValue.strip()
                if val == "None":
                    val = None
                runXML.setField(node.tagName, val)


        return runXML

    def summary(self):
        "Return a dictionary of run summary data"
        fld = self.getField("TermCondition")
        if fld is None:
            termCond = "UNKNOWN"
        elif fld == "Failure":
            termCond = "FAILED"
        elif fld == "Success":
            termCond = "SUCCESS"
        else:
            termCond = "??%s??" % fld

        return {
            "num": self.getRun(),
            "config": self.getConfig(),
            "result": termCond,
            "startTime": str(self.getStartTime()),
            "endTime": str(self.getEndTime()),
            "numEvents": self.getEvents(),
            "numMoni": self.getMoni(),
            "numTcal": self.getTcal(),
            "numSN": self.getSN(),
        }


if __name__ == "__main__":
    a = DashXMLLog()
    a.setRun(117554)
    a.setConfig("sps-IC79-Erik-Changed-TriggerIDs-V151")
    a.setStartTime(55584.113903)
    a.setEndTime(55584.227695)
    a.setFirstGoodTime(55584.113903)
    a.setLastGoodTime(55584.227695)
    a.setTermCond(False)
    a.setEvents(24494834)
    a.setMoni(60499244)
    a.setTcal(4653819)
    a.setSN(47624256)

    a.setField("ExtraField", 50)
    #print a.documentToString()
    #a.dispLog()
