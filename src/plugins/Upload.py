"""
Upload plugin
"""

import datetime
import os
import os.path
import re
import sys

ADMINUSER_ID = 'admin'

class Upload(object):
    allowedExtn = set(['.dat', '.doc', '.docx', '.gif', '.json', '.jpeg', 'jpg', '.pdf', '.ppt', '.pptx', '.png', '.txt', '.xls', '.xlsx', '.zip'])
    lateDir = 'Late'
    QDIR_RE = re.compile(r'^q\d+$')
    @classmethod
    def safeName(cls, s, userId=False):
        if userId:
            return re.sub(r'[^\w.@-]', '_', s)
        else:
            return re.sub(r'[^\w-]', '_', s)

    def __init__(self, pluginManager, path, userId, userRole):
        ## print >> sys.stderr, 'Upload.__init__:', path, userId
        self.pluginManager = pluginManager
        self.path = path
        self.userId = userId
        self.userRole = userRole

    def lockFile(self, serverParams, fileURL):
        # Best not to use lockFile, as results are somewhat unpredictable with cloud-backed up filesystems
        print >> sys.stderr, 'Upload.lockFile:', serverParams, fileURL
        self.pluginManager.lockFile(fileURL)

    def lateUploads(self, serverParams, userId=''):
        ## print >> sys.stderr, 'Upload.lateUploads:', serverParams, userId
        if not userId or not self.pluginManager.adminRole(self.userRole, alsoGrader=True):
            # Only admin/grader can access all users
            userId = self.userId

        dirpath = (os.path.splitext(self.path)[0]+'/' if self.path else '') + self.lateDir
        path_url_list = self.pluginManager.dirFiles(dirpath, restricted=True)
        time_path_url_list = [[os.path.getmtime(path_url[0])]+path_url for path_url in path_url_list]
        time_path_url_list.sort(reverse=True)
        retvals = []
        for ftime, fpath, furl in time_path_url_list:
            fhead, fextn = os.path.splitext(os.path.basename(fpath))
            if fhead == userId:
                flabel = ''
            elif fhead.endswith('-'+userId):
                flabel = fhead[:-len('-'+userId)]
            else:
                continue
            time_str = datetime.datetime.fromtimestamp(ftime).ctime()
            retvals.append( [flabel+fextn+': '+time_str, furl, self.pluginManager.getFileKey(fpath)] )
        return retvals

    def _uploadData(self, serverParams, dataParams, contentLength, content=None):
        # Note: dataParams is under user control, and should be considered untrusted for non-admin users
        print >> sys.stderr, 'Upload._uploadData:', serverParams, dataParams, contentLength, type(content)
        if content is None:
            raise Exception('Upload._uploadData: ERROR no content')
        if len(content) != contentLength:
            return {'result': 'error', 'error': 'Incorrect data upload: expected '+str(contentLength)+' but received '+str(len(content))+ 'bytes'}

        prefixDir, _, prefixName = dataParams.get('filePrefix').rpartition('/')
        filePrefix = self.safeName(prefixName)

        if prefixDir:
            if prefixDir != self.lateDir and not self.QDIR_RE.match(dir):
                raise Exception('Upload._uploadData: ERROR Disallowed directory prefix '+prefixDir)

            filePrefix = os.path.join(prefixDir, filePrefix)

        if serverParams.get('pastDue') and prefixDir != self.lateDir:
            raise Exception('Upload._uploadData: ERROR Please use "Late file upload" option in "Submitted" menu past the due date - '+serverParams['pastDue'])
        temname = dataParams.get('filename','')

        extn = os.path.splitext(temname)[1] or '.dat'  # Enforce non-null file extension for safety
        if extn == '.ipynb':
            # Make notebooks not easily openable by user (for security, as they contain executable code)
            extn = '.json'

        if extn not in self.allowedExtn:
            raise Exception('Upload._uploadData: ERROR Disallowed file extension in '+temname)

        teamName = self.safeName(dataParams.get('teamName', ''))

        if self.pluginManager.adminRole(self.userRole, alsoGrader=True):
            # Only admin/grader can access other users
            userId = self.safeName(dataParams.get('userId', ''), userId=True) or self.userId
        else:
            # Non-admin; use userId from servver
            userId = self.userId

        try:
            # Safe file name: (Late|q1)/sessionName--name-initial--userId.extn
            filename = teamName or userId   # Note: userId may contain periods; enforce non-null file extension for safety
            filename += extn
                
            if filePrefix:
                filename = filePrefix + '--' +filename
            filename = filename.replace('..', '') # Redundant (for extra file access security)

            # Prepend session name to file path
            filepath = (os.path.splitext(self.path)[0]+'/' if self.path else '') + filename

            fileURL = self.pluginManager.writeFile(filepath, content, restricted=True)

            return {'result': 'success', 'value': {'name': os.path.basename(filepath), 'url': fileURL}}
        except Exception, err:
            print >> sys.stderr, 'Upload._uploadData: ERROR', str(err)
            return {'result': 'error', 'error': 'Error in saving uploaded data'}
