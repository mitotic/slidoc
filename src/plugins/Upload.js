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
	if (!this.qattributes || Slidoc.PluginManager.answered(this.qattributes.qnumber) || Slidoc.PluginManager.lateSession()) {
	    // Upload only works with questions
	    this.uploadElem.style.display = 'none';
	    document.getElementById(this.pluginId+'-uploadlabel').style.display = 'none';
	    return;
	}

	var fTypes = (fileTypes || this.qattributes.qtype.split('/')[1]).trim().split(',');
	Slidoc.log('Slidoc.Plugins.Upload.init:', fTypes);
	this.fileTypes = [];
	for (var j=0; j<fTypes.length; j++)
	    this.fileTypes.push(fTypes[j].trim().toLowerCase());
			       

	var fileInfo = this.qattributes && this.persist[this.qattributes.qnumber];
	Slidoc.log('Slidoc.Plugins.Upload.init2:', fileInfo);
	if (fileInfo && fileInfo.loadURL) {
	    this.display();
	    this.viewer.initURL = fileInfo.loadURL;
	    this.viewer.fileType = fileInfo.upload.fileType || fileInfo.fileType; // fileInfo.fileType for backward compatibility
	}
    },

    display: function (response, pluginResp) {
	Slidoc.log('Slidoc.Plugins.Upload.display:', this, response, pluginResp);
	var fileInfo = this.qattributes && this.persist[this.qattributes.qnumber];
	if (fileInfo) {
	    this.confirmMsgElem.textContent = 'Successfully uploaded '+(fileInfo.upload.origName||fileInfo.origName)+' on '+(new Date(fileInfo.uploadTime)); // fileInfo.origName for backward compatibility
	    this.confirmLoadElem.href = fileInfo.loadURL;
	} else {
	    this.confirmMsgElem.textContent = 'Nothing uploaded';
	    this.confirmLoadElem.href = "javascript:alert('Nothing uploaded')";
	}
	var dirPrefix = 'Late';
	this.lateElem.innerHTML = '';
	this.remoteCall('lateUploads', this.lateUploadsCallback.bind(this), dirPrefix, this.userId);
	if (this.viewer.displayURL) {
	    if (fileInfo)
		this.viewer.displayURL(fileInfo.loadURL, fileInfo.upload.fileType|| fileInfo.fileType); // fileInfo.fileType for backward compatibility
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
	    if (furl.match(/.ipynb$/)) {
		// Append "query" using "%3F" as nbviewer chomps up normal queries
		loadURL += '%3F' + fkey;
		if (location.protocol == 'https:')
		    loadURL = 'https://nbviewer.jupyter.org/urls/'+loadURL;
		else
		    loadURL = 'http://nbviewer.jupyter.org/url/'+loadURL;
	    } else {
		loadURL = '//'+loadURL+'?'+fkey;
	    }
	    html.push('<li><a href="'+loadURL+'" target="_blank">'+flabel+'</a></li>\n');
	}
	this.lateElem.innerHTML = 'Late uploads:<ul>\n'+html.join('\n')+'</ul>\n';
    },

    uploaded: function(value) {
	Slidoc.log('Slidoc.Plugins.Upload.uploaded:', value);
	var loadURL = location.host + value.url;
	if (value.fileType == 'ipynb') {
	    // Append "query" using "%3F" as nbviewer chomps up normal queries
	    loadURL += '%3F' + value.fileKey;
	    if (location.protocol == 'https:')
		loadURL = 'https://nbviewer.jupyter.org/urls/'+loadURL;
	    else
		loadURL = 'http://nbviewer.jupyter.org/url/'+loadURL;
	} else {
	    loadURL = '//'+loadURL+'?'+value.fileKey;
	}
	this.persist[this.qattributes.qnumber] = {upload: value, loadURL: loadURL,
						  uploadTime: Date.now()};
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
	    filePrefix += qno + '/' + this.sessionName + '-' + qno;
	else
	    filePrefix += this.sessionName;

	filePrefix += Slidoc.makeUserFileSuffix(this.displayName);

	var teamName = (this.qattributes.team == 'response') ? (Slidoc.PluginManager.teamName()||'') : '';

	Slidoc.uploadHandler(this.name, this.uploaded.bind(this), filePrefix, teamName, this.fileTypes, evt);
    },
    
    response: function (retry, callback) {
	Slidoc.log('Slidoc.Plugins.Upload.response:', retry, !!callback);
	var fileInfo = this.qattributes && this.persist[this.qattributes.qnumber];
	if (!fileInfo && !window.confirm('Answer file not uploaded. Do you want to give up on trying to upload it?'))
	    return;

	if (fileInfo) {
	    var response = fileInfo.upload.origName;
	    var pluginResp = {name: this.name, score: 1, correctAnswer: '', filename: fileInfo.upload.name,
			      time: fileInfo.uploadTime, fileType: fileInfo.upload.fileType, url: fileInfo.upload.url,
			      fileKey: fileInfo.upload.fileKey};
	    this.remoteCall('lockFile', null, fileInfo.upload.url);
	} else {
	    var response = '';
	    var pluginResp = {name: this.name, score: null, correctAnswer: ''};
	}

	if (callback)
	    callback(response, pluginResp);
    }
};

var fileTypeMap = {
    'application/pdf': 'pdf'
};
		   

/* PluginHead: ^(,?ipynb|,?pdf|,?gif|,?jpg|,?jpeg|,?png)+$
   <style>
     .slidoc-plugin-Upload-body {
     font-size: 0.66em;
   }
   </style>
   PluginBody:
   <span id="%(pluginId)s-uploadlabel">Select file or drag-and-drop over button:</span>
   <input type="file" id="%(pluginId)s-uploadbutton" 
   class="slidoc-clickable slidoc-button slidoc-plugin-Upload-button %(pluginId)s-uploadbutton"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].fileUpload(this);"></input>
   <div id="%(pluginId)s-uploadconfirm">
     <span id="%(pluginId)s-uploadconfirm-msg"></span>
     <a id="%(pluginId)s-uploadconfirm-load" target="_blank" href="">Click here to view/download</a>
   </div><div id="%(pluginId)s-uploadlate"></div>
*/
