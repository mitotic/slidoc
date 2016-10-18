"""
Upload plugin
"""

import datetime
import os
import os.path
import sys

ADMINUSER_ID = 'admin'

class Upload(object):
    def __init__(self, pluginManager, path, userId):
        print >> sys.stderr, 'Upload.__init__:', path, userId
        self.pluginManager = pluginManager
        self.path = path
        self.userId = userId

    def lockFile(self, fileURL):
        print >> sys.stderr, 'Upload.lockFile:', fileURL
        self.pluginManager.lockFile(fileURL)

    def lateUploads(self, dirPrefix, userId=''):
        print >> sys.stderr, 'Upload.lateUploads:', dirPrefix, userId
        if not userId or self.userId != ADMINUSER_ID:
            userId = self.userId

        dirpath = (os.path.splitext(self.path)[0]+'/' if self.path else '') + dirPrefix
        path_url_list = self.pluginManager.dirFiles(dirpath, restricted=True)
        time_path_url_list = [[os.path.getmtime(path_url[0])]+path_url for path_url in path_url_list]
        time_path_url_list.sort(reverse=True)
        retvals = []
        for ftime, fpath, furl in time_path_url_list:
            fhead = os.path.splitext(os.path.basename(fpath))[0]
            if fhead == userId or fhead.endswith('-'+userId):
                time_str = datetime.datetime.fromtimestamp(ftime).ctime()
                retvals.append( [time_str, furl, self.pluginManager.getFileKey(fpath)] )
        return retvals

    def _uploadData(self, dataParams, contentLength, content=None):
        print >> sys.stderr, 'Upload._uploadData:', dataParams, contentLength, type(content)
        if content is None:
            raise Exception('Upload._uploadData: ERROR no content')
        if len(content) != contentLength:
            return {'result': 'error', 'error': 'Incorrect data upload: expected '+str(contentLength)+' but received '+str(len(content))+ 'bytes'}

        if self.userId != ADMINUSER_ID:
            userId = self.userId
        else:
            userId = dataParams.get('userId') or self.userId
        try:
            filename = dataParams.get('teamName') or userId
            extn = os.path.splitext(dataParams.get('filename',''))[1]
            if extn:
                filename += extn
            if dataParams.get('filePrefix'):
                filename = dataParams.get('filePrefix') + '-' +filename

            # Prepend session name to file path
            filepath = (os.path.splitext(self.path)[0]+'/' if self.path else '') + filename

            fileKey = self.pluginManager.getFileKey(filepath)
            fileURL = self.pluginManager.writeFile(filepath, content, restricted=True)

            return {'result': 'success', 'value': {'name': os.path.basename(filepath), 'url': fileURL, 'fileKey': fileKey}}
        except Exception, err:
            print >> sys.stderr, 'Upload._uploadData: ERROR', str(err)
            return {'result': 'error', 'error': 'Error in saving uploaded data'}
