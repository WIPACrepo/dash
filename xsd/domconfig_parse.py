from validate_configs import validate_dom_config_sps, validate_dom_config_spts
import glob
import os
import sys

if __name__ == "__main__":

    # Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
    if "PDAQ_HOME" in os.environ:
        metaDir = os.environ["PDAQ_HOME"]
    else:
        sys.path.append('..')
        from locate_pdaq import find_pdaq_trunk
        metaDir = find_pdaq_trunk()

    config_path = os.path.join(metaDir, "config")
    dom_config_path = os.path.join(config_path, "domconfigs")
    xsd_path = os.path.join(config_path, "xsd")

    # test the xsd  parsing on all dom config xml files
    print "Checking sps configuration files:"
    invalid_list = []
    cfg_files = glob.glob(os.path.join(dom_config_path, 'sps*.xml'))
    for cfg in cfg_files:

        valid, errors = validate_dom_config_sps(cfg)

        if not valid:
            print "-" * 60

            print "File %s is not valid" % cfg
            #print "Reason: %s" % errors
            invalid_list.append((cfg, errors))

    print "Printing errors found in sps configuration files:"
    for f, errs in invalid_list:
        print errs
        print "-" * 80

    # test the xsd  parsing on all dom config xml files
    print "Checking spts configuration files:"
    invalid_list = []
    cfg_files = glob.glob(os.path.join(dom_config_path, 'spts*.xml'))
    for cfg in cfg_files:

        valid, errors = validate_dom_config_spts(cfg)

        if not valid:
            print "-" * 60

            print "File %s is not valid" % cfg
            #print "Reason: %s" % errors
            invalid_list.append((cfg, errors))

    print "Printing errors found in sps configuration files:"
    for f, errs in invalid_list:
        print errs
        print "-" * 80
