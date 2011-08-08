from lxml import etree

def validate_dom_config_xml(xml_filename, xsd_real_filename, xsd_sim_filename):
    """
    This method will look a bit hack'ish.  
    The dom configs for the real doms is a bit problematic as the elements
    can occur in any order ( probably due to hand editing the files )  This 
    means we have to use xsd:all ( or list all possible orders of arguments -
    which will be large due to the number of possible elements ).  You cannot
    use an xsd:all inside a choice as that makes the resulting grammar 
    non-determinisitc.  

    So we get around this problem by reading the document in an unvalidated 
    fashion, look for a simulation tag, and then validate the xml file 
    depending on that tag.  Any simplifications I could come up with would
    require altering the format for the dom config files, or editing all
    configs neither of which is desirable.
    """

    with open(xml_filename, 'r') as xml_fd:
        doc_xml = etree.parse(xml_fd)

    found_simulation = False
    
    dom_configs = doc_xml.findall('domConfig')
    for dconfig in dom_configs:
        simulation = dconfig.findall('simulation')
        if len(simulation)!=0:
            found_simulation = True

    # now we know the type of the file
    if found_simulation:
        with open(xsd_sim_filename, 'r') as xsd_sim_fd:
            xmlschema_doc = etree.parse(xsd_sim_fd)
        xsd_sim = etree.XMLSchema(xmlschema_doc)

        if xsd_sim.validate(doc_xml):
            return (True, "")
        else:
            return (False, "%s" % xsd_sim.error_log)
    else:

        with open(xsd_real_filename, 'r') as xsd_real_fd:
            xmlschema_doc = etree.parse(xsd_real_fd)
        xsd_real = etree.XMLSchema(xmlschema_doc)

        if xsd_real.validate(doc_xml):
            return (True, "")
        else:
            return (False, "%s" % xsd_real.error_log)


def validate_xml(xml_filename, xsd_filename):
    """Arguments:
    xml_filename: path to an xml file
    xsd_filename: path to an xsd file used to validate the xml file

    Returns: ( a tuple ) - 
    (valid, reason) ->
        valid - is true if the xml file is validated by the schema and false otherwise
        reason - text describing why the xml file is invalid if it is invalid
    """
    
    # real dom config xsd
    with open(xsd_filename, 'r') as xsd_fd:
        xmlschema_doc = etree.parse(xsd_fd)
    xsd = etree.XMLSchema(xmlschema_doc)

    with open(xml_filename, 'r') as doc_fd:
        doc_xml = etree.parse(doc_fd)

    if xsd.validate(doc_xml):
        return (True, "")
    else:
        return (False, "%s" % xsd.error_log)

    
