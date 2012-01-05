#! /usr/bin/env python

from sys import argv, stdout
from xml.etree import ElementTree

class geo:
	def __init__(self, str, pos, x, y, z):
		self.str = str
		self.pos = pos
		self.x   = x
		self.y   = y
		self.z   = z
	def __str__(self):
		return "%2.2d-%2.2d %.1f %.1f %.1f" % (self.str, self.pos, self.x, self.y, self.z)

def read_geo(f):
	gd = dict()
	while True:
		s = f.readline()
		if len(s) == 0: return gd
		toks = s.split()
		g = geo(int(toks[0]), int(toks[1]), 
				float(toks[2]), float(toks[3]), float(toks[4]))
		loc = "%2.2d-%2.2d" % (g.str, g.pos)
		gd[loc] = g
		
ddg = ElementTree.parse(open(argv.pop(1)))
gd  = read_geo(open(argv.pop(1)))

for ch in ddg.findall("string/dom"):
	try:
		channelId = int(ch.findtext("channelId"))
		stringId = channelId / 64
		position = channelId % 64 + 1
		loc = "%2.2d-%2.2d" % (stringId, position)
		if loc not in gd: continue
		#print channelId, gd[loc]
		for tag in ("xCoordinate", "yCoordinate", "zCoordinate"):
			xN  = ch.find(tag)
			if xN is None: ElementTree.SubElement(ch, tag)
			ch.find(tag).text = "%.1f" % gd[loc].__dict__[tag[0]]
	except TypeError, err:
		pass

ddg.write(stdout, "UTF-8")


	
