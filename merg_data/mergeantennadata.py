#!/usr/bin/env python

import re
import os
import sys


def fixPinName(n):
    mo = re.match(r"^(\S+)\<(\d+)\>$",n)
    if not mo:
        return n
    return "%s[%d]"%(mo.group(1),int(mo.group(2),10))

def main():

    if len(sys.argv) != 4:
        print "USAGE: python mergeantennadata.py input_physical.lef input_antenna.lef output.lef"
        return 1

    inplef = open(sys.argv[1],'r')
    inalef = open(sys.argv[2],'r')
    outlef = open(sys.argv[3],'w')

    
    inpin = False
    curpin = None
    curpinname = None
    pindata = dict()
    for line in inalef:
        if line.startswith('PIN'):
            mo = re.match(r'^\s*PIN\s+(\S+)\s*$',line)
            assert mo,"Invalid pin line "+repr(line)
            assert not inpin,"Already in pin"
            curpinname = mo.group(1)
            inpin=True
            curpin = list()
            fixedpinname = fixPinName(curpinname)
            assert not fixedpinname in pindata,"duplicate pin"
            pindata[fixedpinname] = curpin
        elif line.startswith('END'):
            mo = re.match(r'^\s*END\s+(\S+)\s*$',line)
            assert mo,"Invalid end line "+repr(line)
            assert inpin,"END outside pin"
            assert mo.group(1)==curpinname,"Mismatched PIN/END"
            curpinname=None
            curpin=None
            inpin=False
        elif re.match(r"^\s*ANTENNA.*;\s*$",line):
            curpin.append(line)
        else:
            raise Exception("bad line "+repr(line))
            
    #print sorted(pindata.keys())
    
    sawpin = set()
    inpin = None
    savedindent="\t"
    for line in inplef:
        if 'PIN' in line:
            #print line
            mo = re.match(r"^\s*PIN\s+(\S+)\s+$",line)
            assert mo,"invalid pin line "+repr(line)
            assert not inpin
            inpin = mo.group(1)
        elif 'END' in line:
            mo = re.match(r"^\s*END\s+(\S+)\s+$",line)
            if mo:
                curpin = mo.group(1)
                if inpin == curpin:
                    sawpin.add(curpin)
                    #print repr(savedindent)
                    if curpin in pindata:
                        #outlef.write("+ "+curpin+"\n")
                        for al in pindata[curpin]:
                            outlef.write(savedindent+al.lstrip())
                    inpin =None
        if inpin is not None:
            mo = re.match(r"^(\s*)",line)
            savedindent=mo.group(1)
        outlef.write(line)

    missingpins = set(pindata.keys())-sawpin
    if missingpins:
        print "WARNING: found pins in antenna lef but not physical lef.  Ignored."
        for mp in missingpins:
            print "\t",mp

    notantpins = sawpin - set(pindata.keys())
    if notantpins:
        print "INFO: the following pins had no antenna info"
        for na in notantpins:
            print "\t",na

if __name__=="__main__":
    main()
