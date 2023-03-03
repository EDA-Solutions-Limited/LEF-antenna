#!/usr/bin/env python

import os
import re
import sys
import json

import subprocess

def readrdb(inf):
    """Read Calibre's output file and return a data structure organized by netname"""
    rv = dict()

    header = inf.readline()
    while True:
        rulename = inf.readline()
        if rulename == '':
            break
        checkhead = inf.readline()
        chd = checkhead.rstrip().split(" ",3)
        (rc,orc,tlc) = [int(i) for i in chd[:3]]

        assert rc==0
        assert orc == 0
        text = []
        for i in range(tlc):
            text.append(inf.readline())
        
        fields = text[-1].rstrip().split()
        vals = dict()
        for f in fields:
            eqidx = f.index('=')
            n=f[:eqidx]
            v=f[eqidx+1:]
            vals[n]=v
        if vals['NETNAME']:
            dcidx = rulename.index('::')
            r = rulename[:dcidx].split("_")
            n = vals['NETNAME']
            rv.setdefault(n,dict()).setdefault(int(r[1]),{})[r[2]]=float(vals['VALUE'])
    return rv


def leftoken(inf):
    """Read a LEF file from a file-like object and yield the tokens"""
    data = inf.read()

    data = re.sub(r"#[^\n]*\n","",data)

    pos = 0
    while pos < len(data):
        while pos < len(data) and data[pos].isspace():
            pos +=1

        if not pos < len(data):
            break

        st = pos
        if data[st] == '"':
            pos = data.index('"',st+1)+1
            assert(data[pos].isspace())
        else:
            while pos < len(data) and not data[pos].isspace():
                pos+=1

        if st < pos:
            yield data[st:pos]


def getlayermap(inf):
    """Read a GDS layermap file and return the data organized by layer name"""
    rv = dict()
    for line in inf:
        line = re.sub(r"#.*","",line).rstrip()
        if not line:
            continue

        d = line.split(None,5)
        assert len(d) >= 4

        d[2]=int(d[2])
        d[3]=int(d[3])

        rv.setdefault(d[0],[]).append(d[1:])

    return rv


def findval(needle, haystack):
    """Utility function to pull data form LEF datastructure"""
    for h in haystack:
        if h[0] == needle:
            if h[-1] == ';':
                return h[1:-1]
            return h[1:]

    raise ValueError(repr((needle,haystack)))


if __name__== "__main__":
    
    # gather command line arguments
    if len(sys.argv) < 6:
        sys.stdout.write("wrong number of arguments.  Usage is LEFfile GDSlayermap GDSfile CellName ConfigFile\n")
        exit(2)

    gdsname = sys.argv[3]
    cellname = sys.argv[4]

    configdata = json.load(open(sys.argv[5],'rb'))

    # Create the Calibre deck
    outsvrf = open("out.svrf","wb")

    # Standard boilerplate header
    outsvrf.write("""LAYOUT PATH  "%s"
LAYOUT PRIMARY "%s"
LAYOUT SYSTEM GDSII

DRC RESULTS DATABASE "drc.results" ASCII 
DRC MAXIMUM RESULTS 1000
DRC MAXIMUM VERTEX 4096

DRC CELL NAME YES CELL SPACE XFORM
DRC SUMMARY REPORT "drc.summary" REPLACE HIER

VIRTUAL CONNECT COLON NO
VIRTUAL CONNECT REPORT NO

DRC ICSTATION YES
DRC INCREMENTAL CONNECT YES
"""%(gdsname,cellname))


    # read the GDS layer map file
    inlm = open(sys.argv[2],'rb')
    gdsdata = getlayermap(inlm)

    # define interesting sections of the LEF file to extract from the parser
    sections = {('PROPERTYDEFINITIONS',):0,('UNITS',):0,('VIARULE',):2,('LAYER',):1,("VIA",):1,('SITE',):1}

    layers = list()

    # read and parse the LEF file
    inlef = open(sys.argv[1],'rb')
    lt = leftoken(inlef)
    stack = list()
    children = None
    while True:
        try:
            stmt = lt.next()
        except StopIteration:
            break
        stoks = [stmt,]
        #print repr(stmt)


        iofs = 0
        key = tuple(stack) + (stmt,)
        if key in sections:
            for i in range(sections[key]):
                stoks.append(lt.next())
            stack.append(stmt)
            iofs = -1
            if stmt == "LAYER":
                children = list()
                children.append(stoks)
                layers.append(children)
        elif stmt == 'END':
            stoks.append(lt.next())
            if stoks[1] == 'LIBRARY':
                assert not stack
            else:
                stack.pop()
                iofs = 1
            children = None
        else:
            while stoks[-1] != ';':
                stoks.append(lt.next())
            if children is not None:
                children.append(stoks)


            
    # iterate through the layers in the LEF file and the extra layers in the config file
    #   create the section of the calibre deck that maps the various GDS numbers to the needed layers

    # a large offset so we can define meta-layers to merge together mutiple real GDS layers
    lc = 10000
    for l in layers+[ [[None,i]] for i in configdata['extralayers']]:
        lname = l[0][1]
        if lname == "OVERLAP":
            continue
        if not lname in gdsdata:
            print "WARNING: layer %s not in gds layers"%(lname)
            continue
        #print l
        #print gdsdata[lname]
        outsvrf.write("LAYER %s %d\n"%(lname,lc))
        lm = sorted(set((tuple(i[1:3]) for i in gdsdata[lname])))

        # some hard coded layer suffixes we've seen that get merged in with layers
        for suf in ("_NET","_PIN","BAR","_E1","_E2"):
            if lname+suf in gdsdata:
                lm += sorted(set((tuple(i[1:3]) for i in gdsdata[lname+suf])))

        for i in lm:
            outsvrf.write("LAYER MAP %d DATATYPE %d %d\n"%(i[0],i[1],lc))
            outsvrf.write("LAYER MAP %d TEXTTYPE %d %d\n"%(i[0],i[1],lc))
            #print "LAYER MAP",i[0],"DATATYPE",i[1],lc
        outsvrf.write("\n")
        outsvrf.flush()
        lc +=1


    # find the lowest routing layer in the LEF file
    firstrouting = None
    frname = None
    for i in range(len(layers)):
        if findval('TYPE',layers[i])[0] == "ROUTING":
            firstrouting=i
            frname = layers[i][0][1]
            break

    # climb the metal stack and record the routing layers
    routelayers=list()
    for i in range(firstrouting,len(layers)):
        (typ,) = findval('TYPE',layers[i])
        if typ == "ROUTING":
            routelayers.append(layers[i][0][1])

    # all route layers allow port labels
    outsvrf.write("TEXT LAYER " + " ".join(routelayers) + "\n\n")

    # add the user-provided SVRF data
    #   this must define layers named gate and diffct, and connect up through the lowest routing layer
    outsvrf.write("\n// START prepsvrf section\n\n")
    outsvrf.write(configdata['prepsvrf'])
    outsvrf.write("\n// END prepsvrf section\n\n")

    # iterate up the routing stack, building each layer and then extracting the metal, diff and gate areas
    for i in range(firstrouting,len(layers)):
        (typ,) = findval('TYPE',layers[i])

        if typ == "OVERLAP":
            continue

        lname = layers[i][0][1]
        #print i,lname,typ
        outsvrf.write("CONNECT %s %s\n"%(layers[i-1][0][1],lname))
        if typ == 'ROUTING':
            outsvrf.write("""NAR_%d_self { 
  NET AREA RATIO %s [AREA(%s)] > 0 RDB ONLY outdata.rdb
}
NAR_%d_selfperim {
  NET AREA RATIO %s [PERIMETER(%s)] > 0 RDB ONLY outdata.rdb
}
NAR_%d_diff {
  NET AREA RATIO diffct [AREA(diffct)] >0 RDB ONLY outdata.rdb
}
NAR_%d_gate {
  NET AREA RATIO gate [AREA(gate)] >0 RDB ONLY outdata.rdb
}
"""%(i,lname,lname,i,lname,lname,i,i))
        if typ == 'CUT':
            outsvrf.write("""NAR_%d_self {
    NET AREA RATIO %s [AREA(%s)] > 0 RDB ONLY outdata.rdb
}
"""%(i,lname,lname))    

    outsvrf.close()

    # invoke Calibre using the generated SVRF file and the user-provided GDS file / cellname
    skipcalibre = False
    if not skipcalibre:
        calibrelog = open("calibrelog.txt","w")
        rv = subprocess.call(['calibre','-drc','-hier','out.svrf'],stdout=calibrelog)
        if rv != 0:
            print "ERROR: Calibre returns",repr(rv)
            print "See calibrelog.txt for details"
            exit(1)
        assert rv == 0

    # read in the RDB file Calibre created and process it into LEF format
    rdb = readrdb(open("outdata.rdb","rb"))
    for (net,ndb) in rdb.iteritems():
        print "PIN",net
        lastgate = None
        lastdiff = None
        for layer in sorted(ndb.keys()):
            ldb = ndb[layer]
            leflayer = layers[layer]
            lname = leflayer[0][1]
            ltype = findval('TYPE',leflayer)[0]

            # if thickness is not provided, report the perimiter (as opposed to sidewall area)
            thickness = 1.
            try:
                thickness = findval('THICKNESS',leflayer)[0]
            except:
                pass

            #print "\t#",layer,lname,ldb,ltype

            if 'self' in ldb:
                if ltype == 'ROUTING':
                    print "\tANTENNAPARTIALMETALAREA %f LAYER %s ;"%(ldb['self'],lname)
                else:
                    print "\tANTENNAPARTIALCUTAREA %f LAYER %s ;"%(ldb['self'],lname)
            if 'selfperim' in ldb:
                print "\tANTENNAPARTIALMETALSIDEAREA %f LAYER %s ;"%(ldb['selfperim']*thickness,lname)
            if 'diff' in ldb:
                v=ldb['diff']
                if v != lastdiff:
                    print "\tANTENNADIFFAREA %f LAYER %s ;"%(ldb['diff'],lname)
                lastdiff = v
            if 'gate' in ldb:
                v = ldb['gate']
                if v != lastgate:
                    print "\tANTENNAGATEAREA %f LAYER %s ;"%(ldb['gate'],lname)
                lastgate = v
        print "END",net
