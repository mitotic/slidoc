#!/usr/bin/env python

'''
Slidoc printing:

  sdprint.py --auth_key=SITE_KEY --gsheet_url=http://localhost:8081/geos210-f17/site_name/_proxy ---debug --users=aaa,bbb http://localhost:8081/site_name/_private/session/session01.html

NOTE:

1. Use --printable --fontsize=12,9 --delay_sec=... options for best results in printing sessions

2. Use 'lp -o StapleLocation=UpperLeft filenames ...' for printing+stapling

3. wkhtmltopdf: The OS X Carbon (32-bit) version seems to work better
                Inserting very large figures messes up the fonts. Resize figures for better results.


'''

from __future__ import print_function

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import urllib
import urllib2

from collections import defaultdict, OrderedDict

import tornado.auth
import tornado.escape
import tornado.httpserver
import tornado.options
import tornado.web
import tornado.websocket

from tornado.options import define, options
from tornado.ioloop import IOLoop

import sliauth

ROSTER_SHEET = 'roster_slidoc'
PORT = 8687

def http_get(url, params_dict):
    try:
        return urllib2.urlopen(url + ('?'+urllib.urlencode(params_dict) if params_dict else '')).read()
    except Exception, excp:
        sys.exit('ERROR in accessing GET URL %s: %s' % (url, excp))

def http_post(url, params_dict):
    data = urllib.urlencode(params_dict)
    req = urllib2.Request(url, data)
    try:
        response = urllib2.urlopen(req)
    except Exception, excp:
        sys.exit('ERROR in accessing POST URL %s: %s' % (url, excp))
    result = response.read()
    try:
        result = json.loads(result)
    except Exception, excp:
        pass
    return result

def get_roster(sheet_url, hmac_key, session_name):
    # Returns roster as OrderedDict or None if no roster sheet
    user = 'admin'
    user_token = sliauth.gen_auth_token(hmac_key, user, 'admin', prefixed=True)

    get_params = {'sheet': ROSTER_SHEET, 'id': session_name, 'admin': user, 'token': user_token,
                  'get': '1', 'getheaders': '1', 'all': '1'}
    retval = http_post(sheet_url, get_params)

    if retval['result'] != 'success':
        if retval['error'].startswith('Error:NOSHEET:'):
            return None
        else:
            sys.exit("Error in accessing roster session '%s': %s" % (session_name, retval['error']))
    all_rows = retval.get('value')
    headers = retval['headers']
    if headers[1] != 'id' or headers[0] != 'name':
        sys.exit('Incorrect roster headers: '+str(headers))
    return OrderedDict( (x[1], x[0]) for x in all_rows)

def start_ioloop():
    IOLoop.current().start()

def stop_ioloop():
    IOLoop.current().stop()
    sys.exit(0)

def sigterm(signal, frame):
    print("sdprint: sigterm", file=sys.stderr)
    IOLoop.current().add_callback(stop_ioloop)

def main():
    def config_parse(path):
        tornado.options.parse_config_file(path, final=False)

    define("config", type=str, help="Path to config file", callback=config_parse)

    define("auth_key", default="", help="Site authentication key")
    define("debug", default=False, help="Debug mode")
    define("wkhtmltopdf", default=False, help="Use wkhtmltopdf instead of headless Chrome")
    define("gsheet_url", default="", help="Google sheet URL")

    define("users", default="", help="'Comma-separated list of userIDs, or 'all'")
    define("staple", default=False, help="Send to printer using lp command for stapling")
    define("doc_title", default="", help="Document title")
    args = tornado.options.parse_command_line()
    if not args:
        sys.exit("Please specify one or more Slidoc session files (session_name.html or http://host/session_name.html)")

    session_list = []
    for arg in args:
        file_html = ''
        server_url = ''
        rel_path = ''
        site_prefix = ''
        session_file = arg
        match = re.match(r'^(https?://[-.\w]+(\:\d+)?)(/[a-zA-Z][\w-]*)?(/((_private/)?[\w-]+/)([\w-]+).html)$', session_file)
        if not match:
            sys.exit('Invalid session URL: '+arg)
        server_url = match.group(1)
        site_prefix = match.group(3) or ''
        rel_path = match.group(4)
        session_name = os.path.splitext(match.group(7))[0]

        session_list.append( (server_url, site_prefix, rel_path, session_name, session_file, file_html) )

    def start_print():
        for server_url, site_prefix, rel_path, session_name, session_file, file_html in session_list:
            if options.users:
                ucomps = options.users.split(',')
                roster = get_roster(options.gsheet_url, options.auth_key, session_name)
                if len(ucomps) == 1 and ucomps[0] == 'all':
                    if roster is None:
                        sys.exit('Roster sheet not found for session '+session_name)
                    user_list = roster.items()
                elif roster is None:
                    user_list = [(user, user) for user in ucomps]
                else:
                    user_list = []
                    for user in ucomps:
                        if user not in roster:
                            sys.exit("User ID "+user+" not found in roster")
                        user_list.append( (user, roster[user]) )
            else:
                user_list = [('', '')]

            for userId, name in user_list:
                if userId:
                    lastname, _, firstmiddle = name.partition(',')
                    lastname = lastname.strip().replace(' ','_').replace('#','_')
                    firstmiddle = firstmiddle.strip()
                    namesuffix = lastname.capitalize()+(firstmiddle[0].upper() if firstmiddle else '')
                    outname = session_name+'-'+namesuffix+'-'+userId + '.pdf'
                    token = sliauth.gen_auth_token(options.auth_key, userId, prefixed=True)
                else:
                    outname = session_name+'.pdf'
                    token = ''
                print("****Generating %s: %s" % (outname, name), file=sys.stderr)
                if options.wkhtmltopdf:
                    cmd_args = ['wkhtmltopdf', '-s', 'Letter', '--print-media-type',
                                '--margin-top', '15',
                                '--margin-bottom', '20',
                                '--javascript-delay', '8000',
                                '--header-spacing', '2', '--header-font-size', '10',
                                '--header-right', '[page] of [toPage]',
                                '--header-center', options.doc_title or session_name,
                                ]
                    if userId:
                        cmd_args += ['--header-left', name+' ('+userId+')']
                        cmd_args += ['--cookie', 'slidoc_server', '%s::%s:' % (userId, token)]
                    if options.debug:
                        cmd_args += ['--debug-javascript']
                    cmd_args += [session_file, outname]

                else:
                    upload_key = sliauth.gen_hmac_token(options.auth_key, 'upload:')
                    token = sliauth.gen_hmac_token(upload_key, 'nonce:'+userId)
                    nonce = http_get(server_url+'/_nonce'+site_prefix, {'userid': userId, 'token': token})
                    batchToken = sliauth.gen_hmac_token(upload_key, 'batch:'+userId+':'+nonce)
                    query = '?'+urllib.urlencode({'auth': userId+':'+batchToken})
                    session_url = server_url+'/_batch_login'+site_prefix+query+'&'+urllib.urlencode({'next': site_prefix+rel_path+'?print=1'})
                    cmd_args = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                                '--headless', '--disable-gpu',
                                '--print-to-pdf='+outname]
                    if options.debug:
                        cmd_args += ['--enable-logging', '--v=1']
                    cmd_args += [session_url]

                if options.debug:
                    print("****Command:", cmd_args, file=sys.stderr)

                subprocess.check_call(cmd_args)
                if options.staple:
                    print("****Sending to printer for stapling:", outname, file=sys.stderr)
                    lp_cmd = ['lp', '-o', 'StapleLocation=UpperLeft', outname]
                    subprocess.check_call(cmd_args)
                else:
                    print("****Generated:", outname, file=sys.stderr)
                    print("", file=sys.stderr)

        print('sdprint: Actions completed', file=sys.stderr)

    start_print()

if __name__ == '__main__':
    main()
