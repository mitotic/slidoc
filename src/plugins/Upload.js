Upload = {
    // Simple upload plugin

    init: function(fileTypes) {
	// Use either as standalone upload plugin
	//    =Upload('doc,docx')
	// Or as upload response plugin
	//    Answer: Upload/ipynb;...
	this.lateElem = document.getElementById(this.pluginId+'-uploadlate');
	this.confirmMsgElem = document.getElementById(this.pluginId+'-uploadconfirm-msg');
	this.confirmLoadElem = document.getElementById(this.pluginId+'-uploadconfirm-load');
	this.uploadElem = document.getElementById(this.pluginId+'-uploadbutton');
	this.uploadElem.addEventListener('change', this.fileUpload.bind(this), false);

	this.viewer = {};
	Slidoc.log('Slidoc.Plugins.Upload.init:', this.displayName);
	if (!this.qattributes || Slidoc.PluginManager.answered(this.qattributes.qnumber) || Slidoc.PluginManager.lateSession()) {
	    // Upload only works with unanswered questions (for non-late sessions)
	    this.confirmMsgElem.textContent = Slidoc.PluginManager.lateSession() ? 'Late session - no uploads allowed' : ''
	    this.confirmLoadElem.style.display = 'none';
	    this.uploadElem.style.display = 'none';
	    try {
		document.getElementById(this.pluginId+'-uploadlabel').style.display = 'none';
	    } catch(err) {
	    }
	    return;
	}

	var fTypes = (fileTypes || this.qattributes.qtype.split('/')[1]).trim().split(',');
	Slidoc.log('Slidoc.Plugins.Upload.init:', fTypes);
	this.fileTypes = [];
	for (var j=0; j<fTypes.length; j++)
	    this.fileTypes.push(fTypes[j].trim().toLowerCase());
			       
	var fileInfo = this.qattributes && this.persist[this.qattributes.qnumber];
	var loadURL = this.loadPath(fileInfo);
	Slidoc.log('Slidoc.Plugins.Upload.init2:', fileInfo, loadURL);
	if (fileInfo && loadURL) {
	    this.display();
	    this.viewer.initURL = loadURL;
	    this.viewer.fileType = fileInfo.upload.fileType || fileInfo.fileType; // fileInfo.fileType for backward compatibility
	}
    },

    display: function (response, pluginResp) {
	Slidoc.log('Slidoc.Plugins.Upload.display:', this, response, pluginResp);
	var fileInfo = this.qattributes && this.persist[this.qattributes.qnumber];
	var dispURL = this.loadPath(fileInfo, pluginResp);
	if (dispURL) {
	    // origName is untrusted content; always display as plain text, not HTML
	    this.confirmMsgElem.textContent = 'Successfully uploaded '+(fileInfo ? (fileInfo.upload.origName||fileInfo.origName) : (pluginResp.origName||''))+' on '+(new Date(fileInfo ? fileInfo.uploadTime : pluginResp.time)); // fileInfo.origName for backward compatibility
	    this.confirmLoadElem.href = dispURL;
	} else {
	    this.confirmMsgElem.textContent = 'Nothing uploaded';
	    this.confirmLoadElem.href = "javascript:alert('Nothing uploaded')";
	}
	this.lateElem.innerHTML = '';
	this.remoteCall('lateUploads', this.lateUploadsCallback.bind(this), this.userId);
	if (this.viewer.displayURL) {
	    if (dispURL)
		this.viewer.displayURL(dispURL, pluginResp ? pluginResp.fileType : (fileInfo.upload.fileType|| fileInfo.fileType)); // fileInfo.fileType for backward compatibility
	    else
		this.viewer.displayURL('', '');
	}
    },

    lateUploadsCallback: function(uploadList) {
	Slidoc.log('Slidoc.Plugins.Upload.lateUploadsCallback:', uploadList);
	if (!uploadList || !uploadList.length)
	    return;
	var html = [];
	for (var j=0; j<uploadList.length; j++) {
	    var flabel = uploadList[j][0];
	    var furl = uploadList[j][1];
	    var fkey = uploadList[j][2];
	    var loadURL = location.host + furl;
	    loadURL = this.loadPrefix(loadURL, fkey, furl.match(/.ipynb$/));
	    html.push('<li><a href="'+loadURL+'" target="_blank">'+flabel+'</a></li>\n');
	}
	this.lateElem.innerHTML = '<b>Late uploads:</b><ul>\n'+html.join('\n')+'</ul>\n';
    },

    loadPrefix: function (loadURL, fileKey, notebook) {
	///Slidoc.log('Slidoc.Plugins.Upload.loadPrefix:', loadURL, fileKey, notebook);
	if (notebook) {
	    // Append "query" using "%3F" as nbviewer chomps up normal queries
	    loadURL += '%3F' + fileKey;
	    if (location.protocol == 'https:')
		return 'https://nbviewer.jupyter.org/urls/'+loadURL;
	    else
		return 'http://nbviewer.jupyter.org/url/'+loadURL;
	} else {
	    return '//'+loadURL+'?'+fileKey;
	}
    },

    loadPath: function(fileInfo, pluginResp) {
	///Slidoc.log('Slidoc.Plugins.Upload.loadPath:', fileInfo, pluginResp);
	if (!fileInfo && !pluginResp)
	    return '';

	if (pluginResp) {
	    var url = pluginResp.url || '';
	    var filename = pluginResp.filename || '';
	    var fileType = pluginResp.fileType || '';
	} else {
	    if (fileInfo.loadURL)         // Backwards compatibility
		return fileInfo.loadURL;

	    url = fileInfo.upload.url;
	    filename = fileInfo.upload.name;
	    fileType = fileInfo.upload.fileType;
	}

	if (!url)
	    return '';

	// Sanitize URL as it is untrusted content
	url = url.replace(/\.\./g, '');

	var loadURL = location.host + Slidoc.PluginManager.sitePrefix + Slidoc.PluginManager.pluginDataPath + '/' + this.name + url;

	var fileKey = Slidoc.PluginManager.getFileKey(filename, this.qattributes.team == 'response');
	return this.loadPrefix(loadURL, fileKey, fileType == 'ipynb');
    },

    uploaded: function(value) {
	Slidoc.log('Slidoc.Plugins.Upload.uploaded:', value);
	this.persist[this.qattributes.qnumber] = {upload: value, uploadTime: Date.now()};
	this.display(value.name);
	Slidoc.PluginManager.saveSession(); // Save upload info
    },

    disable: function (displayCorrect) {
	Slidoc.log('Slidoc.Plugins.Upload.disable:', displayCorrect);
	this.uploadElem.disabled = 'disabled';
    },

    fileUpload: function (evt) {
	Slidoc.log('Slidoc.Plugins.Upload.fileUpload:', evt);
	var filePrefix = '';
	var qno = this.qattributes ? 'q'+this.qattributes.qnumber : '';
	if (qno)
	    filePrefix += qno + '/' + this.sessionName + '--' + qno + '-';
	else
	    filePrefix += this.sessionName + '--';

	filePrefix += Slidoc.makeUserFileSuffix(this.displayName);

	var teamName = (this.qattributes.team == 'response') ? (Slidoc.PluginManager.teamName()||'') : '';

	Slidoc.uploadHandler(this.name, this.uploaded.bind(this), filePrefix, teamName, this.fileTypes, evt);
    },
    
    response: function (retry, callback) {
	Slidoc.log('Slidoc.Plugins.Upload.response:', retry, !!callback);
	var fileInfo = this.qattributes && this.persist[this.qattributes.qnumber];
	if (!fileInfo && !window.confirm('Answer file not uploaded. Do you want to give up on trying to upload it?\nSelect Cancel to re-try file upload or OK to give up'))
	    return false;

	if (fileInfo) {
	    var response = fileInfo.upload.origName;
	    var pluginResp = {name: this.name, score: 1, correctAnswer: '', filename: fileInfo.upload.name, origName: fileInfo.upload.origName,
			      time: fileInfo.uploadTime, fileType: fileInfo.upload.fileType, url: fileInfo.upload.url};
	    ///this.remoteCall('lockFile', null, fileInfo.upload.url); //Disabled to allow unsubmission etc.
	} else {
	    var response = '';
	    var pluginResp = {name: this.name, score: null, correctAnswer: ''};
	}

	if (callback)
	    callback(response, pluginResp);
	return true;
    }
};

var fileTypeMap = {
    'application/pdf': 'pdf'
};
		   

/* HEAD: ^(,?ipynb|,?pdf|,?gif|,?jpg|,?jpeg|,?png)+$
   <style>
     .slidoc-plugin-Upload-body {
     font-size: 0.66em;
   }
   </style>

   BODY:
   <span id="%(pluginId)s-uploadlabel">Select file or drag-and-drop over button:</span>
   <input type="file" id="%(pluginId)s-uploadbutton" 
   class="slidoc-clickable slidoc-button slidoc-plugin-Upload-button %(pluginId)s-uploadbutton"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].fileUpload(this);"></input>
   <div id="%(pluginId)s-uploadconfirm">
     <span id="%(pluginId)s-uploadconfirm-msg"></span>
     <a id="%(pluginId)s-uploadconfirm-load" target="_blank" href="">Click here to view/download</a>
   </div><div id="%(pluginId)s-uploadlate"></div>
*/
