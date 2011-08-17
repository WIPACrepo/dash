from validate_configs import validate_trigger
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
    trigger_config_path = os.path.join(config_path, "trigger")
    xsd_path = os.path.join(config_path, "xsd")

    invalid_found = False
    trigger_configs = glob.glob(os.path.join(trigger_config_path, '*.xml'))
    for trigger_config in trigger_configs:
        valid, reason = validate_trigger(trigger_config)
        if not valid:
            print "File is not valid! (%s)" % trigger_config
            print "-"*60
            
            print ""
            print reason
            invalid_found = True

    if not invalid_found:
        print "No invalid trigger configuration files found"

    
