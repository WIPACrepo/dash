from validate_configs import validate_xml
import glob, os, sys

if __name__ == "__main__":
    # Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
    if os.environ.has_key("PDAQ_HOME"):
        metaDir = os.environ["PDAQ_HOME"]
    else:
        sys.path.append('..')
        from locate_pdaq import find_pdaq_trunk
        metaDir = find_pdaq_trunk()

    print "Validating all trigger configuration files"
    print "Will only print a status when a corrupt file is found"
    print "Note that there are some corrupt trigger files, someone put quotes in the wrong place."
    print "-"*60
    print ""

    config_path = os.path.join(metaDir, "config")
    cluster_config_path = config_path
    xsd_path = os.path.join(config_path, "xsd")

    invalid_found = False
    clustercfg_configs = glob.glob(os.path.join(cluster_config_path, '*.cfg'))
    for clustercfg_config in clustercfg_configs:
        valid, reason = validate_xml(clustercfg_config, os.path.join(xsd_path, 'clustercfg.xsd'))
        if not valid:
            print "File is not valid! (%s)" % clustercfg_config
            print "-"*60
            
            print ""
            print reason
            invalid_found = True

    if not invalid_found:
        print "No invalid cluster configuration files found"

    
