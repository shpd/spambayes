#! /usr/bin/env python
# At the moment, this requires Python 2.3 from CVS

# A driver for the classifier module and Tim's tokenizer that you can
# call from procmail.  This one uses Neil's cdb module.  Will it be
# faster than Berkeley DB hashes?

"""Usage: %(program)s [options]

Where:
    -h
        show usage and exit
    -g PATH
        mbox or directory of known good messages (non-spam) to train on.
    -s PATH
        mbox or directory of known spam messages to train on.
    -u PATH
        mbox of unknown messages.  A ham/spam decision is reported for each.
    -p FILE
        use file as the persistent store.  loads data from this file if it
        exists, and saves data to this file at the end.  Default: %(DEFAULTDB)s
    -f
        run as a filter: read a single message from stdin, add an
        %(DISPHEADER)s header, and write it to stdout.
"""

import sys
import os
import getopt
import mailbox
import glob
import email
import classifier
import errno
import cdb
import cPickle as pickle

program = sys.argv[0] # For usage(); referenced by docstring above

# Name of the header to add in filter mode
DISPHEADER = "X-Hammie-Disposition"

# Default database name
DEFAULTDB = "hammie.db"

# Tim's tokenizer kicks far more booty than anything I would have
# written.  Score one for analysis ;)
from tokenizer import tokenize

from cdbwrap import CDBShelf

class CDBDict(CDBShelf):
    """Constant Database Dictionary

    This wraps a cdb to make it look even more like a dictionary.

    Call it with the name of your database file.  Optionally, you can
    specify a list of keys to skip when iterating.  This only affects
    iterators; things like .keys() still list everything.  For instance:

    >>> d = DBDict('/tmp/goober.db', ('skipme', 'skipmetoo'))
    >>> d['skipme'] = 'booga'
    >>> d['countme'] = 'wakka'
    >>> print d.keys()
    ['skipme', 'countme']
    >>> for k in d.iterkeys():
    ...     print k
    countme

    """
    
    def __init__(self, dbname, iterskip=()):
        CDBShelf.__init__(self, dbname)
        self.iterskip = iterskip

    def __iter__(self, fn=lambda k,v: (k,v)):
        for key in self.dict.iterkeys():
            val = self.get(key)
            if key not in self.iterskip:
                yield fn(key, val)

    def __setitem__(self, key, value):
        v = pickle.dumps(value, 1)
        self.dict[key] = v

    def iteritems(self):
        return self.__iter__()

    def iterkeys(self):
        return self.__iter__(lambda k,v: k)

    def itervalues(self):
        return self.__iter__(lambda k,v: v)

    def items(self):
        ret = []
        for i in self.iteritems():
            ret.append(i)
        return ret

    def keys(self):
        ret = []
        for i in self.iterkeys():
            ret.append(i)
        return ret

    def values(self):
        ret = []
        for i in self.itervalues():
            ret.append(i)
        return ret

    def __contains__(self, name):
        return self.has_key(name)

    
class PersistentGrahamBayes(classifier.GrahamBayes):
    """A persistent GrahamBayes classifier

    This is just like classifier.GrahamBayes, except that the dictionary
    is a database.  You take less disk this way, I think, and you can
    pretend it's persistent.  It's much slower training, but much faster
    checking, and takes less memory all around.

    On destruction, an instantiation of this class will write it's state
    to a special key.  When you instantiate a new one, it will attempt
    to read these values out of that key again, so you can pick up where
    you left off.

    """

    # XXX: Would it be even faster to remember (in a list) which keys
    # had been modified, and only recalculate those keys?  No sense in
    # going over the entire word database if only 100 words are
    # affected.

    # XXX: Another idea: cache stuff in memory.  But by then maybe we
    # should just use ZODB.

    def __init__(self, dbname):
        classifier.GrahamBayes.__init__(self)
        self.statekey = "saved state"
        self.wordinfo = CDBDict(dbname, (self.statekey,))

        self.restore_state()

    def __del__(self):
        #super.__del__(self)
        self.save_state()

    def save_state(self):
        self.wordinfo[self.statekey] = (self.nham, self.nspam)

    def restore_state(self):
        if self.wordinfo.has_key(self.statekey):
            self.nham, self.nspam = self.wordinfo[self.statekey]


class DirOfTxtFileMailbox:

    """Mailbox directory consisting of .txt files."""

    def __init__(self, dirname, factory):
        self.names = glob.glob(os.path.join(dirname, "*.txt"))
        self.factory = factory

    def __iter__(self):
        for name in self.names:
            try:
                f = open(name)
            except IOError:
                continue
            yield self.factory(f)
            f.close()


def getmbox(msgs):
    """Return an iterable mbox object given a file/directory/folder name."""
    def _factory(fp):
        try:
            return email.message_from_file(fp)
        except email.Errors.MessageParseError:
            return ''

    if msgs.startswith("+"):
        import mhlib
        mh = mhlib.MH()
        mbox = mailbox.MHMailbox(os.path.join(mh.getpath(), msgs[1:]),
                                 _factory)
    elif os.path.isdir(msgs):
        # XXX Bogus: use an MHMailbox if the pathname contains /Mail/,
        # else a DirOfTxtFileMailbox.
        if msgs.find("/Mail/") >= 0:
            mbox = mailbox.MHMailbox(msgs, _factory)
        else:
            mbox = DirOfTxtFileMailbox(msgs, _factory)
    else:
        fp = open(msgs)
        mbox = mailbox.PortableUnixMailbox(fp, _factory)
    return mbox

def train(bayes, msgs, is_spam):
    """Train bayes with all messages from a mailbox."""
    mbox = getmbox(msgs)
    i = 0
    for msg in mbox:
        i += 1
        # XXX: Is the \r a Unixism?  I seem to recall it working in DOS
        # back in the day.  Maybe it's a line-printer-ism ;)
        sys.stdout.write("\r%6d" % i)
        sys.stdout.flush()
        bayes.learn(tokenize(msg), is_spam, False)
    print

def formatclues(clues, sep="; "):
    """Format the clues into something readable."""
    return sep.join(["%r: %.2f" % (word, prob) for word, prob in clues])

def filter(bayes, input, output):
    """Filter (judge) a message"""
    msg = email.message_from_file(input)
    prob, clues = bayes.spamprob(tokenize(msg), True)
    if prob < 0.9:
        disp = "No"
    else:
        disp = "Yes"
    disp += "; %.2f" % prob
    disp += "; " + formatclues(clues)
    msg.add_header(DISPHEADER, disp)
    output.write(msg.as_string(unixfrom=(msg.get_unixfrom() is not None)))

def score(bayes, msgs):
    """Score (judge) all messages from a mailbox."""
    # XXX The reporting needs work!
    mbox = getmbox(msgs)
    i = 0
    spams = hams = 0
    for msg in mbox:
        i += 1
        prob, clues = bayes.spamprob(tokenize(msg), True)
        isspam = prob >= 0.9
        if isspam:
            spams += 1
            print "%6s %4.2f %1s" % (i, prob, isspam and "S" or "."),
            print formatclues(clues)
        else:
            hams += 1
    print "Total %d spam, %d ham" % (spams, hams)

def usage(code, msg=''):
    """Print usage message and sys.exit(code)."""
    if msg:
        print >> sys.stderr, msg
        print >> sys.stderr
    print >> sys.stderr, __doc__ % globals()
    sys.exit(code)

def main():
    """Main program; parse options and go."""
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hdfg:s:p:u:')
    except getopt.error, msg:
        usage(2, msg)

    if not opts:
        usage(2, "No options given")

    pck = DEFAULTDB
    good = spam = unknown = None
    do_filter = usedb = False
    for opt, arg in opts:
        if opt == '-h':
            usage(0)
        elif opt == '-g':
            good = arg
        elif opt == '-s':
            spam = arg
        elif opt == '-p':
            pck = arg
        elif opt == "-f":
            do_filter = True
        elif opt == '-u':
            unknown = arg
    if args:
        usage(2, "Positional arguments not allowed")

    save = False

    bayes = PersistentGrahamBayes(pck)

    if good:
        print "Training ham:"
        train(bayes, good, False)
        save = True
    if spam:
        print "Training spam:"
        train(bayes, spam, True)
        save = True

    if save:
        bayes.update_probabilities()

    if do_filter:
        filter(bayes, sys.stdin, sys.stdout)

    if unknown:
        score(bayes, unknown)

if __name__ == "__main__":
    main()
