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

    print "Validating all runconfig files"
    print ""

    config_path = os.path.join(metaDir, "config")
    run_config_path = config_path
    xsd_path = os.path.join(config_path, "xsd")

    invalid_found = False
    run_configs = glob.glob(os.path.join(run_config_path, '*.xml'))

    # remove the default dom geometry file from the above list
    for entry in run_configs:
        basename = os.path.basename(entry)
        if basename=='default-dom-geometry.xml':
            run_configs.remove(entry)
            break

    for run_config in run_configs:
        valid, reason = validate_xml(run_config, os.path.join(xsd_path, 'runconfig.xsd'))
        if not valid:
            print "File is not valid! (%s)" % run_config
            print "-"*60
            
            print ""
            print reason
            invalid_found = True


    if not invalid_found:
        print "No invalid run configuration files found"

    
