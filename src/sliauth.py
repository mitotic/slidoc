#!/usr/bin/env python

'''
Slidoc authentication utilities

'''

from __future__ import print_function

import base64
import datetime
import hashlib
import hmac
import json
import time
import urllib
import urllib2

TRUNCATE_DIGEST = 8

DIGEST_ALGORITHM = hashlib.md5

def digest_hex(s, n=TRUNCATE_DIGEST):
    return DIGEST_ALGORITHM(s).hexdigest()[:n]

def gen_hmac_token(key, message):
    token = base64.b64encode(hmac.new(key, message, DIGEST_ALGORITHM).digest())
    return token[:TRUNCATE_DIGEST]

def gen_user_token(key, user_id):
    return gen_hmac_token(key, 'id:'+user_id)

def gen_admin_token(key, admin_user_id):
    return gen_hmac_token(key, 'admin:'+admin_user_id)

def gen_late_token(key, user_id, session_name, date_str):
    # Use date string of the form '1995-12-17T03:24'
    token = date_str+':'+gen_hmac_token(key, 'late:%s:%s:%s' % (user_id, session_name, date_str) )
    return token

def str_encode(value):
    return value.encode('utf-8') if isinstance(value, unicode) else value

def safe_quote(value):
    return urllib.quote(str_encode(value), safe='')

def get_utc_date(date_time_str):
    """Convert local date string of the form yyyy-mm-ddThh:mm to UTC (unless it already ends with 'Z')"""
    if date_time_str and not date_time_str.endswith('Z'):
        try:
            date_time_str = datetime.datetime.utcfromtimestamp(time.mktime(time.strptime(date_time_str, "%Y-%m-%dT%H:%M"))).strftime("%Y-%m-%dT%H:%M") + 'Z'
        except Exception, excp:
            raise Exception("Error in parsing date '%s'; expect local time to be formatted like 2016-05-04T11:59 (%s)" % (date_time_str, excp))

    return date_time_str

def parse_date(date_time_str):
    """Parse ISO format date, with or without Z suffix denoting UTC, to return datetime object (containing local time)
       Return None on error
    """
    if date_time_str.endswith('Z'):
        # UTC time step (add local time offset)
        offset_sec = time.mktime(datetime.datetime.now().timetuple()) - time.mktime(datetime.datetime.utcnow().timetuple())
        date_time_str = date_time_str[:-1]
    else:
        offset_sec = 0

    if len(date_time_str) == 16:
        # yyyy-mm-ddThh:mm
        format = "%Y-%m-%dT%H:%M"
    elif len(date_time_str) == 19:
        # yyyy-mm-ddThh:mm:ss
        format = "%Y-%m-%dT%H:%M:%S"
    else:
        format = "%Y-%m-%dT%H:%M:%S.%f"

    try:
        return datetime.datetime.fromtimestamp(time.mktime(time.strptime(date_time_str, format)) + offset_sec)
    except Exception:
        return None

def create_date(epoch_ms=None):
    """Create datetime object from epoch milliseconds (i.e., milliseconds since Jan. 1, 1970)"""
    return datetime.datetime.now() if epoch_ms is None else datetime.datetime.fromtimestamp(epoch_ms/1000)

def epoch_ms(date_time=None):
    """Return epoch milliseconds (i.e., milliseconds since Jan. 1, 1970) for datetime object"""
    if date_time:
        return time.mktime(date_time.timetuple())*1000.0 + date_time.microsecond/1000.0
    else:
        return epoch_ms(datetime.datetime.now())

def iso_date(date_time=None, utc=False):
    """Return ISO date time string for local time (or UTC time)"""
    if not date_time:
        date_time = datetime.datetime.now()
    if utc:
        return datetime.datetime.utcfromtimestamp(epoch_ms(date_time)/1000.0).isoformat() + 'Z'
    else:
        return date_time.isoformat()

def json_default(obj):
    if isinstance(obj, datetime.datetime):
        return iso_date(obj, utc=True)
    raise TypeError("%s not serializable" % type(obj))

def http_post(url, params_dict=None):
    req = urllib2.Request(url, urllib.urlencode(params_dict)) if params_dict else urllib2.Request(url)
    try:
        response = urllib2.urlopen(req)
    except Exception, excp:
        raise Exception('ERROR in accessing URL %s: %s' % (url, excp))
    result = response.read()
    try:
        result = json.loads(result)
    except Exception, excp:
        result = {'result': 'error', 'error': 'Error in http_post: result='+str(result)+': '+str(excp)}
    return result

def read_settings(sheet_url, hmac_key, settings_sheet):
    user_token = gen_admin_token(hmac_key, 'admin')
    get_params = {'sheet': settings_sheet, 'get': '1', 'all': '1', 'getheaders': '1', 'admin': 'admin', 'token': user_token}
    retval = http_post(sheet_url, get_params)
    if retval['result'] != 'success':
        raise Exception("Error in accessing '%s': %s" % (settings_sheet, retval['error']))
    rows = retval.get('value')
    if not rows:
        raise Exception("Error: Empty sheet '%s'" % settings_sheet)
    return get_settings(rows)

def get_settings(rows):
    settings = {}
    for row in rows:
        name, value = row[:2]
        name = name.strip()
        value = str(value).strip()
        if value.lower() in ('on', 'true', 'yes'):
            value = True
        elif value.lower() in ('off', 'false', 'no'):
            value = False
        settings[name] = value
    return settings

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Generate slidoc HMAC authentication tokens')
    parser.add_argument('-a', '--auth_key', help='Digest authentication key (required)')
    parser.add_argument('-s', '--session', help='Session name')
    parser.add_argument('--due_date', metavar='DATE_TIME', help="Due date yyyy-mm-ddThh:mm local time (append ':00.000Z' for UTC)")
    parser.add_argument('user', help='user name(s)', nargs=argparse.ONE_OR_MORE)
    cmd_args = parser.parse_args()

    if not cmd_args.auth_key:
        sys.exit('Must specify digest authentication key')

    for user in cmd_args.user:
        if cmd_args.due_date:
            token = gen_late_token(cmd_args.auth_key, user, cmd_args.session, get_utc_date(cmd_args.due_date))
        else:
            token = gen_user_token(cmd_args.auth_key, user)
        print(user+':',  token)
