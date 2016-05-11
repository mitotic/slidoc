#!/usr/bin/env python

'''
Slidoc authentication utilities

'''

from __future__ import print_function

import base64
import datetime
import hashlib
import hmac
import time

TRUNCATE_DIGEST = 8

def gen_hmac_token(key, message):
    token = base64.b64encode(hmac.new(key, message, hashlib.md5).digest())
    return token[:TRUNCATE_DIGEST]

def gen_late_token(key, email, session_name, date_str):
    # Use date string '1995-12-17T03:24:00.000Z' (need the 00.000Z part due to bug in GoogleApps)
    token = date_str+':'+gen_hmac_token(key, '%s:%s:%s' % (email, session_name, date_str) )
    return token

def get_utc_date(date_time):
    """Convert local date of the form yyyy-mm-ddThh:mm to UTC (unless it ends with 'Z')"""
    if date_time and not date_time.endswith('Z'):
        try:
            date_time = datetime.datetime.utcfromtimestamp(time.mktime(time.strptime(date_time, "%Y-%m-%dT%H:%M"))).strftime("%Y-%m-%dT%H:%M") + 'Z'
        except Exception, excp:
            raise Exception("Error in parsing date '%s'; expect local time to be formatted like 2016-05-04T11:59 (%s)" % (date_time, excp))

    return date_time

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Generate slidoc HMAC authentication tokens')
    parser.add_argument('-k', '--key', help='HMAC key (required)')
    parser.add_argument('-s', '--session', help='Session name')
    parser.add_argument('--due_date', metavar='DATE_TIME', help="Due date yyyy-mm-ddThh:mm local time (append ':00.000Z' for UTC)")
    parser.add_argument('user', help='user name(s)', nargs=argparse.ONE_OR_MORE)
    cmd_args = parser.parse_args()

    if not cmd_args.key:
        sys.exit('Must specify HMAC key')

    for user in cmd_args.user:
        email = user.lower() if '@' in user else user.lower()+'@slidoc'
        if cmd_args.due_date:
            token = gen_late_token(cmd_args.key, email, cmd_args.session, get_utc_date(cmd_args.due_date))
        else:
            token = gen_hmac_token(cmd_args.key, email)
        print(user+':',  token)