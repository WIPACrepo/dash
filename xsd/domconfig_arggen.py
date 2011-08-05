import sys, os
import glob

from lxml import etree

def validate_real_xml(xml_filename, xsd_real_filename):

    # real dom config xsd
    xsd_real_fd = open(xsd_real_filename, 'r')
    xmlschema_doc = etree.parse(xsd_real_fd)

    xsd_real = etree.XMLSchema(xmlschema_doc)

    doc = open(xml_filename, 'r').read()
    doc_xml = etree.XML(doc)

    real_valid = False
    
    if xsd_real.validate(doc_xml):
        print "valid REAL xml file"
        xsd_real_fd.close()
        return True
    else:
        xsd_real_fd.close()
        return False


def argcollect(xml_filename, arg_dict):
    
    with open(xml_filename, 'r') as doc_fd:
        doc = etree.parse(doc_fd)
        
    root = doc.getroot()
    domConfigs = root.findall('domConfig')

    for dconfig in domConfigs:
        localC = dconfig.findall('localCoincidence')[0]

        for c in localC.getchildren():
            tag = c.tag
            txt = c.text
            
            try:
                val = float(txt)
            except ValueError:
                continue
            except TypeError:
                continue

            try:
                arg_dict[tag].append(val)
            except KeyError:
                arg_dict[tag] = []
                arg_dict[tag].append(val)

        for c in dconfig.getchildren():
            tag = c.tag
            txt = c.text
            
            try:
                val = float(txt)
            except ValueError:
                continue
            except TypeError:
                continue

            if val<-32000:
                # filter out the two huge negative 
                # values for the mpe trigger
                continue

            
            try:
                arg_dict[tag].append(val)
            except KeyError:
                arg_dict[tag] = []
                arg_dict[tag].append(val)
            
    return arg_dict


if __name__ == "__main__":

    # Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
    if os.environ.has_key("PDAQ_HOME"):
        metaDir = os.environ["PDAQ_HOME"]
    else:
        sys.path.append('..')
        from locate_pdaq import find_pdaq_trunk
        metaDir = find_pdaq_trunk()

    config_path = os.path.join(metaDir, "config")
    dom_config_path = os.path.join(config_path, "domconfigs")
    xsd_path = os.path.join(config_path, "xsd")

    cfg_files = glob.glob(os.path.join(dom_config_path, 'sps*.xml'))

    args = {}

    for cfg in cfg_files:
        print "validating ", cfg
        if validate_real_xml(cfg, os.path.join(xsd_path, 'domconfig-real.xsd')):
            args = argcollect(cfg, args)

    print "Dom Configuration Integer Arguments:"
    for arg_name in args:
        print arg_name

        max_val = max(args[arg_name])
        min_val = min(args[arg_name])
        avg_val = sum(args[arg_name])/len(args[arg_name])


        print "Argument Named: %s" % arg_name
        print "\tMax value: %.2f" % max_val
        print "\tMin value: %.2f" % min_val
        print "\tAvg value: %.2f" % avg_val



    
