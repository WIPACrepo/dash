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


class DashXMLLog(object):
    """
    This class will generate an xml logging file for dash.
    The purpose is to generate this for Kirill.
    Apparently he was parsing dash.log and generating a log file.
    The parsing would break as people changed the format of the
    dash.log file.  This code will let you generate an xml log that
    will meet at least his requirements.  You can add more fields to
    this with the 'set_field' method.

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

    FAILURE = "Failure"
    SUCCESS = "Success"
    IN_PROGRESS = "In Progress"

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

    def __parse_date_time(self, fld):
        if fld is None:
            return None
        if isinstance(fld, DAQDateTime) or isinstance(fld, datetime):
            return fld
        mtch = self.DATE_PAT.match(str(fld))
        if mtch is None:
            raise ValueError("Unparseable date string \"%s\"" % fld)
        dtflds = []
        for i in range(6):
            dtflds.append(int(mtch.group(i+1)))
        if mtch.group(8) is None:
            return DAQDateTime(dtflds[0], dtflds[1], dtflds[2], dtflds[3],
                               dtflds[4], dtflds[5], dtflds[6])

        sstr = mtch.group(8)
        if len(sstr) > 10:
            raise ValueError("Bad subseconds for date string \"%s\"" % fld)
        sstr += "0" * (10 - len(sstr))
        return DAQDateTime(dtflds[0], dtflds[1], dtflds[2], dtflds[3],
                           dtflds[4], dtflds[5], dtflds[6], int(sstr))

    @property
    def path(self):
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

    def set_field(self, field_name, field_val):
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

    def get_field(self, field_name):
        if field_name not in self._fields:
            return None
        return self._fields[field_name]

    @property
    def run_number(self):
        """Get the value for the required 'run' field"""
        fld = self.get_field("run")
        if fld is None:
            return None
        return int(fld)

    @run_number.setter
    def run_number(self, run_num):
        """Set the value for the required 'run' field

        Args:
            run_num: a run number
        """

        self.set_field("run", run_num)

    @property
    def run_config_name(self):
        """Get the name of the config file used for this run"""
        return self.get_field("Config")

    @run_config_name.setter
    def run_config_name(self, config_name):
        """Set the name of the config file used for this run

        Args:
            config_name: the name of the config file for this run
        """
        self.set_field("Config", config_name)

    @property
    def cluster_config_name(self):
        """Get the name of the cluster file used for this run"""
        return self.get_field("Cluster")

    @cluster_config_name.setter
    def cluster_config_name(self, cluster):
        """Set the name of the cluster used for this run

        Args:
            cluster: the name of the cluster for this run
        """
        self.set_field("Cluster", cluster)

    @property
    def start_time(self):
        """Get the start time for this run"""
        return self.__parse_date_time(self.get_field("StartTime"))

    @start_time.setter
    def start_time(self, start_time):
        """Set the start time for this run

        Args:
            start_time: the start time for this run
        """
        self.set_field("StartTime", start_time)

    @property
    def end_time(self):
        """Get the end time for this run"""
        return self.__parse_date_time(self.get_field("EndTime"))

    @end_time.setter
    def end_time(self, end_time):
        """Set the end time for this run

        Args:
            end_time: the end time for this run
        """
        self.set_field("EndTime", end_time)

    def set_first_good_time(self, first_time):
        """Set the first good time for this run

        Args:
            first_time: the first good time for this run
        """
        self.set_field("FirstGoodTime", first_time)

    @property
    def first_good_time(self):
        """Get the first good time for this run"""
        return self.__parse_date_time(self.get_field("FirstGoodTime"))

    def set_last_good_time(self, last_time):
        """Set the last time for this run

        Args:
            last_time: the last time for this run
        """
        self.set_field("LastGoodTime", last_time)

    @property
    def last_good_time(self):
        """Get the last time for this run"""
        return self.__parse_date_time(self.get_field("LastGoodTime"))

    @property
    def run_status(self):
        """
        Get the final status for this run:
        True - the run succeeded
        False - the run failed
        None - The status is unknown
        """
        fld = self.get_field("TermCondition")
        if fld is None:
            return None
        if fld == self.FAILURE:
            return True
        if fld == self.SUCCESS:
            return False
        if fld == self.IN_PROGRESS:
            return None
        raise ValueError("Bad termination condition \"%s\"" % fld)

    @run_status.setter
    def run_status(self, had_error):
        """
        Set the termination condition for this run

        If 'has_error' is:
        True - the run succeeded
        False - the run failed
        None - The status is unknown
        """
        if had_error:
            term_cond = self.FAILURE
        elif had_error is not None:
            term_cond = self.SUCCESS
        else:
            term_cond = self.IN_PROGRESS
        self.set_field("TermCondition", term_cond)

    @property
    def num_physics(self):
        """Get the number of events for this run"""
        fld = self.get_field("Events")
        if fld is None:
            return None
        return int(fld)

    @num_physics.setter
    def num_physics(self, events):
        """Set the number of events for this run

        Args:
            events: the number of events for this run
        """
        self.set_field("Events", events)

    @property
    def num_moni(self):
        """Get the number of monitoring events for this run"""
        fld = self.get_field("Moni")
        if fld is None:
            return None
        return int(fld)

    @num_moni.setter
    def num_moni(self, moni):
        """Set the number of monitoring events for this run

        Args:
            moni: the number of monitoring events for this run
        """
        self.set_field("Moni", moni)

    @property
    def num_tcal(self):
        """Get the number of time calibration events for this run"""
        fld = self.get_field("Tcal")
        if fld is None:
            return None
        return int(fld)

    @num_tcal.setter
    def num_tcal(self, tcal):
        """Set the number of time calibration events for this run

        Args:
            tcal: the number of time calibration events for this run
        """
        self.set_field("Tcal", tcal)

    @property
    def num_sn(self):
        """Get the number of supernova events for this run"""
        fld = self.get_field("SN")
        if fld is None:
            return None
        return int(fld)

    @num_sn.setter
    def num_sn(self, val):
        """Set the number of supernova events for this run

        Args:
            sn: the number of supernova events for this run
        """
        self.set_field("SN", val)

    @property
    def version_info(self):
        """Get the release/revision tuple for this run"""
        rel = self.get_field("Release")
        if rel is not None:
            rev = self.get_field("Revision")
            if rev is not None:
                return (rel, rev)
        return (None, None)

    @version_info.setter
    def version_info(self, args):
        """Set the pDAQ release/revision info

        Args:
            rel: pDAQ release name
            rev: pDAQ revision information
        """
        try:
            rel, rev = args
        except ValueError:
            raise ValueError("Expected list/tuple argument, not %s (%s)" %
                             (type(args), str(args)))

        self.set_field("Release", rel)
        self.set_field("Revision", rev)

    def _build_document(self):
        """Take the internal fields dictionary, the _root_elem_name,
        and the style sheet url to build an xml document.
        """
        # check for all required xml fields
        fields_known = list(self._fields.keys())
        for required_key in self._required_fields:
            if required_key not in fields_known:
                raise DashXMLLogException("Missing Required Field %s" %
                                          (required_key, ))

        doc = minidom.Document()
        processing_instr = doc.createProcessingInstruction(
            "xml-stylesheet",
            "type=\"text/xsl\" href=\"%s\"" % self._style_sheet_url)
        doc.appendChild(processing_instr)

        # create the base element
        base = doc.createElement(self._root_elem_name)
        doc.appendChild(base)

        for key in sorted(fields_known):
            elem = doc.createElement(key)
            base.appendChild(elem)

            val = doc.createTextNode("%s" % self._fields[key])
            elem.appendChild(val)

        return doc

    def write_log(self):
        """Build an xml document with stored state and write it to a file

        Args:
            file_name: the name of the file to which we should write the
            xml log file
        """
        doc_str = self.document_to_kirill_string()

        with open(self.path, "w") as fout:
            fout.write(doc_str)

    def document_to_string(self, indent="\t"):
        """Return a string containing the generated xml document

        Args:
            indent: the indentation character.  used in testing
        """
        doc = self._build_document()

        return doc.toprettyxml(indent=indent)

    def document_to_kirill_string(self):
        """Apparently some people don't quite know how to download an
        xml parser so we have to write out xml files in a specific format
        to fit a broken hand rolled xml parser"""

        doc = self._build_document()

        if doc.encoding is None:
            disp_str = "<?xml version=\"1.0\"?>"
        else:
            disp_str = "<?xml version=\"1.0\" encoding=\"%s\"?>" % \
                (doc.encoding)

        # okay here look for any and all processing instructions
        for node in doc.childNodes:
            if node.nodeType == doc.PROCESSING_INSTRUCTION_NODE:
                disp_str = "%s\n%s" % (disp_str, node.toxml())

        root_kids = doc.getElementsByTagName(self._root_elem_name)[0]
        disp_str = "%s\n<%s>" % (disp_str, self._root_elem_name)
        for kid in root_kids.childNodes:
            disp_str = "%s\n\t%s" % (disp_str, kid.toxml())
        disp_str = "%s\n</%s>" % (disp_str, self._root_elem_name)

        return disp_str

    @classmethod
    def format_summary(cls, num, config, result, start_time, end_time,
                       num_events, num_moni, num_tcal, num_sn):
        return {
            "num": num,
            "config": config,
            "result": result,
            "startTime": start_time,
            "endTime": end_time,
            "numEvents": num_events,
            "numMoni": num_moni,
            "numTcal": num_tcal,
            "numSN": num_sn,
        }

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

        root_list = parsed.getElementsByTagName("DAQRunlog")
        if len(root_list) == 0:
            raise MalformedFileException("No DAQRunlog entries found" +
                                         " in \"%s\"" % path)
        elif len(root_list) > 1:
            raise MalformedFileException("Multiple DAQRunlog entries found" +
                                         " in \"%s\"" % path)

        run_xml = DashXMLLog()
        for node in root_list[0].childNodes:
            if node.nodeType != minidom.Node.ELEMENT_NODE:
                continue
            for kid in node.childNodes:
                if kid.nodeType != minidom.Node.TEXT_NODE:
                    continue
                val = kid.nodeValue.strip()
                if val == "None":
                    val = None
                run_xml.set_field(node.tagName, val)

        return run_xml

    def summary(self):
        "Return a dictionary of run summary data"
        fld = self.get_field("TermCondition")
        if fld == self.FAILURE:
            term_cond = "FAILED"
        elif fld == self.SUCCESS:
            term_cond = "SUCCESS"
        elif fld == self.IN_PROGRESS:
            term_cond = "RUNNING"
        else:
            term_cond = "??%s??" % fld

        return self.format_summary(self.run_number, self.run_config_name,
                                   term_cond, str(self.start_time),
                                   str(self.end_time), self.num_physics,
                                   self.num_moni, self.num_tcal,
                                   self.num_sn)


def main():
    "Main program"

    dashlog = DashXMLLog()
    dashlog.run_number = 117554
    dashlog.run_config_name = "sps-IC79-Erik-Changed-TriggerIDs-V151"
    dashlog.start_time = 55584.113903
    dashlog.end_time = 55584.227695
    dashlog.set_first_good_time(55584.113903)
    dashlog.set_last_good_time(55584.227695)
    dashlog.run_status = False
    dashlog.num_physics = 24494834
    dashlog.num_moni = 60499244
    dashlog.num_tcal = 4653819
    dashlog.num_sn = 47624256

    dashlog.set_field("ExtraField", 50)
    # print dashlog.document_to_string()
    # dashlog.dispLog()


if __name__ == "__main__":
    main()
