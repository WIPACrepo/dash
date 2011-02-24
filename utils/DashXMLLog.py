from xml.dom.minidom import Document


class DashXMLLogException(Exception):
    pass


class DashXMLLog:
    """
    This class will generate an xml logging file for dash.  The purpose is to generate this for
    Kirill.  Apparently he was parsing dash.log and generating a log file.  The parsing would break
    as people changed the format of the dash.log file.  This code will let you generate an xml log that
    will meet at least his requirements.  You can add more fields to this with the 'setField" method.

    A minimum xml logging file should look like this:
    
    <?xml version="1.0"?>
    <?xml-stylesheet type="text/xsl" href="/2011/xml/DAQRunlog.xsl"?>
    <DAQRunlog>
    <run>117554</run>
    <Config>sps-IC79-Erik-Changed-TriggerIDs-V151</Config>
    <StartTime>55584.113903</StartTime>
    <EndTime>55584.227695</EndTime>
    <TermCondition>SUCCESS</TermCondition>
    
    <Events>24494834</Events>
    <Moni>60499244</Moni>
    <Tcal>4653819</Tcal>
    <SN>47624256</SN>
    </DAQRunlog>
    """

    def __init__(self, root_elem_name="DAQRunlog", style_sheet_url="/2001/xml/DAQRunlog.xsl"):
        self._fields = {}
        self._root_elem_name = root_elem_name
        self._style_sheet_url = style_sheet_url
        
        self._required_fields = [ "run", "Config", "StartTime", "EndTime", 
                                  "TermCondition", "Events", "Moni", "Tcal", 
                                  "SN" ]


    def setField(self, field_name, field_val):
        """Store the name and value for a field in this log file
        
        Args:
            field_name: A text name for this field
            field_value: A value to associate with this field ( must be formattable by %%s )

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

    def setRun(self, run_num):
        """Set the value for the required 'run' field
        
        Args:
            run_num: a run number
        """

        self.setField("run", run_num)

    def setConfig(self, config_name):
        """Set the name of the config file used for this run
        
        Args:
            config_name: the name of the config file for this run
        """
        self.setField("Config", config_name)

    def setStartTime(self, start_time):
        """Set the start time for this run

        Args:
            start_time: the start time for this run
        """
        self.setField("StartTime", start_time)

    def setEndTime(self, end_time):
        """Set the end time for this run
        
        Args:
            end_time: the end time for this run
        """
        self.setField("EndTime", end_time)

    def setTermCond(self, term_cond):
        """Set the termination condition for this run
        
        Args:
            term_cond: the termination condition for this run
        """
        self.setField("TermCondition", term_cond)

    def setEvents(self, events):
        """Set the number of events for this run

        Args:
            events: the number of events for this run
        """
        self.setField("Events", events)
        
    def setMoni(self, moni):
        """Set the number of moni events for this run

        Args:
            moni: the number of moni events for this run
        """
        self.setField("Moni", moni)

    def setTcal(self, tcal):
        """Set the number of tcal events for this run

        Args:
            tcal: the number of tcal events for this run
        """
        self.setField("Tcal", tcal)

    def setSN(self, sn):
        """Set the number of sn events for this run
        
        Args:
            sn: the number of sn events for this run
        """
        self.setField("SN", sn)

    def _build_document(self):
        """Take the internal fields dictionary, the _root_elem_name, and the style sheet url to build
        an xml document.
        """
        # check for all required xml fields
        fields_known = self._fields.keys()
        fields_known.sort()
        for requiredKey in self._required_fields:
            if requiredKey not in fields_known:
                raise DashXMLLogException("Missing Required Field %s" % requiredKey)

        doc = Document()
        processingInstr = doc.createProcessingInstruction("xml-stylesheet",
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

    def writeLog(self, file_name):
        """Build an xml document with stored state and write it to a file
        
        Args:
            file_name: the name of the file to which we should write the xml log file
        """
        docStr = self.documentToKirillString()
        
        fd = open(file_name, "w")
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
        """Apparently some people don't quite know how to download an xml parser so we have to write out xml files in
        a specific format to fit a broken hand rolled xml parser"""

        doc = self._build_document()
        
        if(doc.encoding==None):
            dispStr = "<?xml version=\"1.0\"?>"
        else:
            dispStr = "<?xml version=\"1.0\" encoding=\"%s\"?>" % (doc.encoding)
            
        # okay here look for any and all processing instructions
        for n in doc.childNodes:
            if(n.nodeType==doc.PROCESSING_INSTRUCTION_NODE):
                dispStr="%s\n%s" % (dispStr, n.toxml())

        n = doc.getElementsByTagName(self._root_elem_name)[0]
        dispStr = "%s\n<%s>" % (dispStr, self._root_elem_name)
        for n in n.childNodes:
            dispStr="%s\n\t%s" % ( dispStr, n.toxml())
        dispStr = "%s\n</%s>" % (dispStr, self._root_elem_name)

        return dispStr



if __name__ == "__main__":
    a = DashXMLLog()
    a.setRun(117554)
    a.setConfig("sps-IC79-Erik-Changed-TriggerIDs-V151")
    a.setStartTime(55584.113903)
    a.setEndTime(55584.227695)
    a.setTermCond("SUCCESS")
    a.setEvents(24494834)
    a.setMoni(60499244)
    a.setTcal(4653819)
    a.setSN(47624256)

    a.setField("ExtraField", 50)
    #print a.documentToString()
    a.dispLog()

        
