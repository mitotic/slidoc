"""
Upload plugin
"""

import os
import sys

class Upload(object):
    def __init__(self, pluginManager, path, userId):
        print >> sys.stderr, 'Upload.__init__:', path, userId
        self.pluginManager = pluginManager
        self.path = path
        self.userId = userId

    def _uploadData(self, dataParams, contentLength, content=None):
        print >> sys.stderr, 'Upload._uploadData:', dataParams, contentLength, type(content)
        if content is None:
            raise Exception('Upload._uploadData: ERROR no content')
        if len(content) != contentLength:
            return {'result': 'error', 'error': 'Incorrect data upload: expected '+str(contentLength)+' but received '+str(len(content))+ 'bytes'}

        try:
            filename = self.userId
            extn = os.path.splitext(dataParams.get('filename',''))[1]
            if extn:
                filename += extn
            if dataParams.get('filePrefix'):
                filename = dataParams.get('filePrefix') + '-' +filename

            # Prepend session name to file path
            filepath = (os.path.splitext(self.path)[0]+'/' if self.path else '') + filename

            url = self.pluginManager.writeFile(filepath, content, restricted=True)

            return {'result': 'success', 'value': {'url': url, 'name': os.path.basename(filepath)}}
        except Exception, err:
            print >> sys.stderr, 'Upload._uploadData: ERROR', str(err)
            return {'result': 'error', 'error': 'Error in saving uploaded data'}
