from validate_configs import validate_dom_config_sps, validate_dom_config_spts
import glob
import os
import sys

if __name__ == "__main__":

    sys.path.append('..')
    from locate_pdaq import find_pdaq_config
    config_path = find_pdaq_config()
    dom_config_path = os.path.join(config_path, "domconfigs")

    print "Checking spts configuration files:"
    cfg_files = glob.glob(os.path.join(dom_config_path, 'spts*.xml'))
    for cfg in cfg_files:

        valid, errors = validate_dom_config_spts(cfg)
        print os.path.basename(cfg)

        if not valid:
            print "-" * 60

            print "File %s is not valid" % cfg
            print "Reason: %s" % errors
            print "-" * 60
            print "\n" * 2

    # test the rng validation on all SPS dom config xml files
    print "Checking sps configuration files:"
    cfg_files = glob.glob(os.path.join(dom_config_path, 'sps*.xml'))
    for cfg in cfg_files:

        valid, errors = validate_dom_config_sps(cfg)

        if not valid:
            print "-" * 60

            print "File %s is not valid" % cfg
            print "Reason: %s" % errors
            print "-" * 60
            print "\n" * 2
