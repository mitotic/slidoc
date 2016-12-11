#!/usr/bin/env python

'''
Slidoc printing:

Use following command to create session.html:
  slidoc.py --gsheet_url=... --auth_key=... --proxy_url=http://localhost:8687/_proxy --pace=1 --printable --debug session.md

  Printing only works for --pace=0, or --pace=1 with --printable

And then
  sdprint.py --gsheet_url=... --auth_key=... --localhost_port=8687 --debug title=... --users=aaa,bbb session.html

If using an active proxy, i.e., http://host/session.html, omit the --localhost_port option.
DO NOT specify  --proxy_url=/_websocket


NOTE:

1. The OS X Carbon (32-bit) version seems to work better

2. Inserting very large figures messes up the fonts. Resize figures for better results.

3. Use 'lp -o StapleLocation=UpperLeft filenames ...' for printing

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
import sdserver

ROSTER_SHEET = 'roster_slidoc'
PORT = 8687

def http_post(url, params_dict):
    data = urllib.urlencode(params_dict)
    req = urllib2.Request(url, data)
    try:
        response = urllib2.urlopen(req)
    except Exception, excp:
        sys.exit('ERROR in accessing URL %s: %s' % (url, excp))
    result = response.read()
    try:
        result = json.loads(result)
    except Exception, excp:
        pass
    return result

def get_roster(sheet_url, hmac_key, session_name):
    # Returns roster as OrderedDict or None if no roster sheet
    user = 'admin'
    user_token = sliauth.gen_admin_token(hmac_key, user)

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

class Application(tornado.web.Application):
    def __init__(self):
        settings = dict(
            debug=options.debug
        )

        handlers = [ ]

        handlers += [ (r"/_proxy", sdserver.ProxyHandler),
                      (r"/", sdserver.HomeHandler)
                    ]

        super(Application, self).__init__(handlers, **settings)

def start_ioloop():
    IOLoop.current().start()

def stop_ioloop():
    IOLoop.current().stop()
    sys.exit(0)

def sigterm(signal, frame):
    print("sdprint: sigterm", file=sys.stderr)
    IOLoop.current().add_callback(stop_ioloop)

def main():
    define("auth_key", default="", help="Digest authentication key for admin user")
    define("debug", default=False, help="Debug mode")
    define("gsheet_url", default="", help="Google sheet URL")

    define("users", default="", help="'Comma-separated list of userIDs, or 'all'")
    define("localhost_port", default=0, help="Port number to be used for localhost proxy, if any", type=int)
    define("staple", default=False, help="Send to printer using lp command for stapling")
    define("title", default="", help="Document title")
    args = tornado.options.parse_command_line()
    if not args:
        sys.exit("Please specify one or more Slidoc session files (session_name.html or http://host/session_name.html)")

    session_list = []
    for arg in args:
        file_html = ''
        session_file = arg
        match = re.match(r'^https?://[-.\w]+(:\d+)?/(.+)$', session_file)
        if match:
            session_name = os.path.splitext(os.path.basename(match.group(2)))[0]
        else:
            session_name = os.path.splitext(os.path.basename(session_file))[0]
            if options.localhost_port:
                f = open(session_file)
                file_html = f.read()
                f.close()

        if options.localhost_port:
            session_file = 'http://localhost:%d' % options.localhost_port
        session_list.append( (session_name, session_file, file_html) )

    def start_print():
        for session_name, session_file, file_html in session_list:
            sdserver.Options.update(auth_key=options.auth_key, debug=options.debug, gsheet_url=options.gsheet_url, _index_html=file_html)

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
                    token = sliauth.gen_user_token(options.auth_key, userId)
                else:
                    outname = session_name+'.pdf'
                    token = ''
                print("****Generating %s: %s" % (outname, name), file=sys.stderr)
                cmd_args = ['wkhtmltopdf', '-s', 'Letter', '--print-media-type',
                            '--margin-top', '15',
                            '--margin-bottom', '20',
                            '--javascript-delay', '8000',
                            '--header-spacing', '2', '--header-font-size', '10',
                            '--header-right', '[page] of [toPage]',
                            '--header-center', options.title or session_name,
                            ]
                if userId:
                    cmd_args += ['--header-left', name+' ('+userId+')']
                    cmd_args += ['--cookie', 'slidoc_server', '%s::%s:' % (userId, token)]
                if options.debug:
                    cmd_args += ['--debug-javascript']
                cmd_args += [session_file, outname]

                ##print("****Command:", cmd_args, file=sys.stderr)

                subprocess.check_call(cmd_args)
                if options.staple:
                    print("****Sending to printer for stapling:", outname, file=sys.stderr)
                    lp_cmd = ['lp', '-o', 'StapleLocation=UpperLeft', outname]
                    subprocess.check_call(cmd_args)

        print('sdprint: Actions completed', file=sys.stderr)
        if options.localhost_port:
            IOLoop.current().add_callback(stop_ioloop)

    if options.localhost_port:
        import sdproxy
        sdproxy.Options.update(AUTH_KEY=options.auth_key, DEBUG=options.debug, SHEET_URL=options.gsheet_url)
        if not options.debug:
            logging.getLogger('tornado.access').disabled = True
        http_server = tornado.httpserver.HTTPServer(Application())
        http_server.listen(options.localhost_port)
        print("Listening on port", options.localhost_port, file=sys.stderr)
        signal.signal(signal.SIGINT, sigterm)
        print_thread = threading.Thread(target=start_print)
        print_thread.start()
        start_ioloop()
    else:
        start_print()

if __name__ == '__main__':
    main()
