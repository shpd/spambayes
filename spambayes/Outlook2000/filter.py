# Filter, dump messages to and from Outlook Mail folders
# Author: Sean D. True, WebReply.Com
# October, 2002
# Copyright PSF, license under the PSF license

import sys, os
from win32com.client import Dispatch, constants
import pythoncom
import rule

def filter_message(message, mgr):
    try:
        headers = message.Fields[0x7D001E].Value
        headers = headers.encode('ascii', 'replace')
        body = message.Text.encode('ascii', 'replace')
        text = headers + body
    except pythoncom.com_error, d:
        print "Failed to get a message: %s" % (d,)
        return

    prob = mgr.hammie.score(text, evidence=False)
    num_rules = 0
    for rule in mgr.config.rules:
        if rule.enabled:
            try:
                if rule.Act(mgr, message, prob):
                    num_rules += 1
            except:
                print "Rule failed!"
                import traceback
                traceback.print_exc()
    return num_rules

def filter_folder(f, mgr, progress, filter):
    only_unread = filter.only_unread
    num_messages = 0
    hammie = mgr.hammie
    for message in mgr.YieldMessageList(f):
        if progress.stop_requested():
            break
        progress.tick()
        if only_unread and not message.Unread:
            continue
        if filter_message(message, mgr):
            num_messages += 1
        
    return num_messages


def filterer(mgr, progress, filter):
    if not filter.folder_ids:
        progress.error("You must specify at least one folder")
        return

    progress.set_status("Counting messages")
    folders = mgr.BuildFolderList(filter.folder_ids, filter.include_sub)
    num_msgs = 0
    for f in folders:
        num_msgs += f.Messages.Count + 1
    progress.set_max_ticks(num_msgs+3)
    num = 0
    for f in folders:
        progress.set_status("Filtering folder '%s'" % (f.Name.encode("ascii", "replace"),))
        num += filter_folder(f, mgr, progress, filter)
        if progress.stop_requested():
            return
    progress.set_status("Filter acted upon %d messages" % (num,))

def main():
    import manager
    mgr = manager.GetManager()

    import dialogs.FilterDialog
    d = dialogs.FilterDialog.FilterArrivalsDialog(mgr, rule.Rule, filterer)
    d.DoModal()
    mgr.Save()
    mgr.Close()

if __name__ == "__main__":
    main()
