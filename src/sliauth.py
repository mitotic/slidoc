#!/usr/bin/env python

'''
Slidoc authentication utilities

'''

from __future__ import print_function

import base64
import datetime
import hashlib
import hmac
import io
import json
import re
import sys
import time
import urllib
import urllib2

VERSION = '0.97.14d'

USER_COOKIE_PREFIX = 'slidoc_user'
SITE_COOKIE_PREFIX = 'slidoc_site'

FUTURE_DATE = 'future'

SLIDOC_OPTIONS_RE = re.compile(r'^ {0,3}(<!--slidoc-(defaults|options)\s+(.*?)-->|Slidoc:\s+(.*?))\s*(\n|\r|$)')

SESSION_NAME_FMT = '%s%02d'
SESSION_NAME_RE     = re.compile(r'^([a-zA-Z]\w*[a-zA-Z_])(\d\d)$')
SESSION_NAME_TOP_RE = re.compile(r'^([a-zA-Z]\w*[a-zA-Z])$')

RESTRICTED_SESSIONS = ('exam', 'final', 'midterm', 'quiz', 'test')

# Set to None to disable restricted checks
RESTRICTED_SESSIONS_RE = re.compile('(' + '|'.join(RESTRICTED_SESSIONS) + ')', re.IGNORECASE)

def get_version(sub=False):
    return sub_version(VERSION) if sub else VERSION

def sub_version(version):
    # Returns portion of version that should match
    # (For versions with letter suffix, just drop letter; otherwise, drop last number)
    return version[:-1] if version[-1].isalpha() else '.'.join(version.split('.')[:-1])

TRUNCATE_DIGEST = 8

DIGEST_ALGORITHM = hashlib.md5

def digest_hex(s, n=TRUNCATE_DIGEST):
    return DIGEST_ALGORITHM(s).hexdigest()[:n]

def gen_hmac_token(key, message):
    token = base64.b64encode(hmac.new(key, message, DIGEST_ALGORITHM).digest())
    return token[:TRUNCATE_DIGEST]

def gen_auth_prefix(user_id, role, sites):
    return ':%s:%s:%s' % (user_id, role, sites)

def gen_auth_token(key, user_id, role='', sites='', prefixed=False):
    prefix = gen_auth_prefix(user_id, role, sites)
    token = gen_hmac_token(key, prefix)
    return prefix+':'+token if prefixed else token

def gen_locked_token(key, user_id, site, session):
    token = gen_hmac_token(key, 'locked:%s:%s:%s' % (user_id, site, session))
    return '%s:%s:%s' % (site, session, token)

def gen_qr_code(text, border=4, pixel=15, raw_image=False):
    try:
        import qrcode
    except ImportError:
        raise Exception('Please install pillow and qrcode packages, e.g., conda install pillow; pip install qrcode')

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=pixel,
        border=border,
        )

    qr.add_data(text)
    qr.make(fit=True)

    img = qr.make_image()

    img_io = io.BytesIO()
    img.save(img_io, "png")
    img_io.seek(0)
    img_data = img_io.getvalue()

    if raw_image:
        return img_data
    else:
        return "data:image/gif;base64,"+img_data.encode("base64")

def gen_site_key(key, site):
    return gen_hmac_token(key, 'site:'+site)

def gen_site_auth_token(site, key, user_id, role='', prefixed=False):
    return gen_auth_token(gen_site_key(key, site), user_id, role=role, prefixed=prefixed)

def gen_late_token(key, user_id, site_name, session_name, date_str):
    # Use date string of the form '1995-12-17T03:24'
    token = date_str+':'+gen_hmac_token(key, 'late:%s:%s:%s:%s' % (user_id, site_name, session_name, date_str) )
    return token

def normalize_newlines(s):
    return s.replace('\r\n', '\n').replace('\r', '\n')

def str_encode(value, errors='strict'):
    return value.encode('utf-8', errors) if isinstance(value, unicode) else value

def safe_quote(value):
    return urllib.quote(str_encode(value), safe='')

def safe_unquote(value):
    return urllib.unquote(value)

def ordered_stringify(value, default=None):
    # json.dumps with sorted keys for dicts.
    # (compatible with Javscript object key ordering provided there are no keys of string type consisting solely of digits)
    return json.dumps(value, default=default, sort_keys=True)

def get_utc_date(date_time_str, pre_midnight=False):
    """Convert local date string of the form yyyy-mm-ddThh:mm (or yyyy-mm-dd) to UTC (unless it already ends with 'Z')"""
    if date_time_str and not date_time_str.endswith('Z'):
        if re.match(r'^\d\d\d\d-\d\d-\d\d$', date_time_str):
            date_time_str += 'T23:59' if pre_midnight else 'T00:00'
        try:
            date_time_str = datetime.datetime.utcfromtimestamp(time.mktime(time.strptime(date_time_str, "%Y-%m-%dT%H:%M"))).strftime("%Y-%m-%dT%H:%M") + 'Z'
        except Exception, excp:
            raise Exception("Error in parsing date '%s'; expect local time to be formatted like 2016-05-04T11:59 (%s)" % (date_time_str, excp))

    return date_time_str

def parse_date(date_time_str, pre_midnight=False):
    """Parse ISO format date, with or without Z suffix denoting UTC, to return datetime object (containing local time)
       Return None on error
    """
    if not date_time_str:
        return None

    if isinstance(date_time_str, datetime.datetime):
        return date_time_str

    if re.match(r'^\d\d\d\d-\d\d-\d\d$', date_time_str):
        date_time_str += 'T23:59' if pre_midnight else 'T00:00'

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
    if date_time and isinstance(date_time, (str, unicode)):
        date_time = parse_date(date_time)

    if date_time:
        return time.mktime(date_time.timetuple())*1000.0 + date_time.microsecond/1000.0
    else:
        return epoch_ms(datetime.datetime.now())

def iso_date(date_time=None, utc=False, nosec=False, nosubsec=False):
    """Return ISO date time string YYYY-MM-DDThh:mm:ss for local time (or UTC time)"""
    if not date_time:
        date_time = datetime.datetime.now()

    if isinstance(date_time, (str, unicode)):
        date_time = parse_date(date_time)

    if utc:
        retval = datetime.datetime.utcfromtimestamp(epoch_ms(date_time)/1000.0).isoformat() + 'Z'
    else:
        retval = date_time.isoformat()

    return retval[:16] if nosec else (retval[:19] if nosubsec else retval)

def print_date(date_time=None, weekday=False, long_date=False, prefix_time=False, not_now=False):
    if not date_time:
        if not_now:
            return ''
        date_time = datetime.datetime.now()

    if isinstance(date_time, (str, unicode)):
        date_time = parse_date(date_time)

    fmt = '%b %d, %Y' if long_date else '%d%b%y'
    if prefix_time:
        fmt = '%H:%M ' + fmt
    if weekday:
        fmt = '%a, ' + fmt

    date_str = date_time.strftime(fmt)
    return date_str if long_date else date_str.lower()

def json_default(obj):
    if isinstance(obj, datetime.datetime):
        return iso_date(obj, utc=True)
    raise TypeError("%s not serializable" % type(obj))

def read_first_line(file):
    # Read first line of file and rewind it
    first_line = file.readline()
    file.seek(0)
    return first_line

def http_post(url, params_dict=None, add_size_info=False):
    req = urllib2.Request(url, urllib.urlencode(params_dict)) if params_dict else urllib2.Request(url)
    try:
        response = urllib2.urlopen(req)
    except Exception, excp:
        raise Exception('ERROR in accessing URL %s: %s' % (url, excp))
    result = response.read()
    result_bytes = len(result)
    try:
        result = json.loads(result)
        if add_size_info:
            result['bytes'] = result_bytes
    except Exception, excp:
        result = {'result': 'error', 'error': 'Error in http_post: result='+str(result)+': '+str(excp)}
    return result

def read_sheet(sheet_url, hmac_key, sheet_name, site=''):
    # Returns [rows, headers]
    auth_key = gen_site_key(hmac_key, site) if site else hmac_key
    user_token = gen_auth_token(auth_key, 'admin', 'admin', prefixed=True)
    get_params = {'sheet': sheet_name, 'proxy': 1, 'get': '1', 'all': '1', 'getheaders': '1', 'admin': 'admin', 'token': user_token}
    retval = http_post(sheet_url, get_params)
    if retval['result'] != 'success':
        raise Exception("Error in accessing %s %s: %s" % (site, sheet_name, retval['error']))
    if not retval.get('value'):
        raise Exception("No data when reading sheet %s %s: %s" % (site, sheet_name, retval['error']))
    return retval['value'][1:], retval['value'][0]

def get_settings(rows):
    if not rows:
        raise Exception("Error: Empty settings sheet")
    settings = {}
    for row in rows:
        if not row or not row[0].strip():
            continue
        name = row[0].strip()
        value = ''
        if len(row) > 1:
            if type(row[1]) in (str, unicode):
                value = row[1].strip()
            elif row[1]:                   # None, False, or 0 become null string
                row[1] = str(row[1])
        settings[name] = value
    return settings

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Generate slidoc HMAC authentication tokens')
    parser.add_argument('-a', '--auth_key', help='Root authentication key')
    parser.add_argument('-k', '--site_auth_key', help='Site authentication key')
    parser.add_argument('-q', '--qrcode', help='write QR code for locked token to stdout', action='store_true')
    parser.add_argument('-r', '--role', help='Role admin/grader')
    parser.add_argument('-s', '--session', help='Session name')
    parser.add_argument('-t', '--site', help='Site name')
    parser.add_argument('--due_date', metavar='DATE_TIME', help="Due date yyyy-mm-ddThh:mm local time (append ':00.000Z' for UTC)")
    parser.add_argument('user', help='user name(s)', nargs=argparse.ZERO_OR_MORE)
    cmd_args = parser.parse_args()

    if not cmd_args.auth_key and not cmd_args.site_auth_key:
        sys.exit('Must specify either root authentication key or site authentication key')

    if cmd_args.site_auth_key:
        auth_key = cmd_args.site_auth_key
    elif cmd_args.site:
        auth_key = gen_site_key(cmd_args.auth_key, cmd_args.site)
    else:
        auth_key = cmd_args.auth_key

    if not cmd_args.user:
        print((cmd_args.site or '')+' auth key =', auth_key, file=sys.stderr)

    for user in cmd_args.user:
        if cmd_args.due_date:
            token = gen_late_token(auth_key, user, cmd_args.site or '', cmd_args.session, get_utc_date(cmd_args.due_date, pre_midnight=True))
        elif cmd_args.session:
            token = gen_locked_token(auth_key, user, cmd_args.site or '', cmd_args.session)
            if cmd_args.qrcode:
                print(gen_qr_code(token, raw_image=True))
        else:
            token = gen_auth_token(auth_key, user, cmd_args.role or '', prefixed=cmd_args.role)

        print(user+' token =',  token, file=sys.stderr)
