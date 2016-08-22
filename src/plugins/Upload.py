"""
Upload plugin
"""

import os
import sys

class Upload(object):
    def __init__(self, path, userId):
        print >> sys.stderr, 'Upload.__init__:', path, userId
        self.path = path
        self.userId = userId

    def uploadData(self, dataName, dataType, contentLength, content):
        print >> sys.stderr, 'Upload.uploadData:', dataName, dataType, contentLength, type(content)
        if len(content) != contentLength:
            return {'result': 'error', 'error': 'Incorrect data upload: expected '+str(contentLength)+' but received '+str(len(content))+ 'bytes'}

        try:
            extn = os.path.splitext(dataName)[1]
            filename = self.userId
            if extn:
                filename += extn
            prefix = os.path.splitext(self.path)[0]+'/' if self.path else ''
            if prefix:
                os.makedirs(prefix[:-1])
            f = open(prefix+filename, 'w')
            f.write(content)
            f.close()
            return {'result': 'success', 'value': {}}
        except Exception, err:
            print >> sys.stderr, 'Upload.uploadData: ERROR', err.message
            return {'result': 'error', 'error': 'Error in saving uploaded data'}
