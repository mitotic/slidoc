Upload = {
    // Simple upload plugin

    init: function(fileTypes) {
	// Use either as standalone upload plugin
	//    =Upload('doc,docx')
	// Or as upload response plugin
	//    Answer: Upload/ipynb;...
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
	    this.viewer.fileType = fileInfo.fileType;
	}
    },

    display: function (response, pluginResp) {
	Slidoc.log('Slidoc.Plugins.Upload.display:', this, response, pluginResp);
	var fileInfo = this.qattributes && this.persist[this.qattributes.qnumber];
	if (fileInfo) {
	    this.confirmMsgElem.textContent = 'Successfully uploaded '+fileInfo.origName+' on '+(new Date(fileInfo.uploadTime));
	    this.confirmLoadElem.href = fileInfo.loadURL;
	} else {
	    this.confirmMsgElem.textContent = 'Nothing uploaded';
	    this.confirmLoadElem.href = '';
	}
	if (this.viewer.displayURL) {
	    if (fileInfo)
		this.viewer.displayURL(fileInfo.loadURL, fileInfo.fileType);
	    else
		this.viewer.displayURL('', '');
	}
    },

    uploaded: function(value) {
	Slidoc.log('Slidoc.Plugins.Upload.uploaded:', value);
	var loadURL = location.host + value.url;
	if (this.fileType == 'ipynb') {
	    // Append "query" using "%3F" as nbviewer chomps up normal queries
	    loadURL += '%3F' + value.fileKey;
	    if (location.protocol == 'https:')
		loadURL = 'https://nbviewer.jupyter.org/urls/'+loadURL;
	    else
		loadURL = 'http://nbviewer.jupyter.org/url/'+loadURL;
	} else {
	    loadURL = '//'+loadURL;
	}
	this.persist[this.qattributes.qnumber] = {origName: this.origName, fileType: this.fileType, upload: value, loadURL: loadURL,
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
	if (!evt.target || !evt.target.files)
	    return;
	var files = evt.target.files; // FileList object
	if (files.length != 1) {
	    alert("Please select a single file");
	    return;
	}

	var file = files[0];
	this.origName = file.name;
	this.fileType = ((file.type ? fileTypeMap[file.type]:'') || file.name.split('.').slice(-1)[0]).toLowerCase();
	if (this.fileTypes.indexOf(this.fileType) < 0) {
	    alert('Invalid file type '+this.fileType+'; expecting one of '+this.fileTypes);
	    return;
	}

	var fileDesc = file.name+', '+file.size+' bytes';
	if (file.lastModifiedDate)
	    fileDesc += ', last modified: '+file.lastModifiedDate.toLocaleDateString();

	var loadCallback = function(result) {
	    if (!result || result.error) {
		alert('Error in uploading file: '+( (result && result.error) ? result.error : ''));
		return;
	    }
	    this.uploaded(result.value);
	}

	var filePrefix = '';
	var qno = this.qattributes ? 'q'+this.qattributes.qnumber : '';
	if (qno)
	    filePrefix += qno + '/' + this.sessionName + '-' + qno;
	else
	    filePrefix += this.sessionName;

	var match = /^([- \w]+)(,\s*([A-Z]).*)$/i.exec(this.displayName||'');
	if (match)
	    filePrefix += '-' + match[1].trim().replace(' ','-').toLowerCase() + (match[3] ? '-'+match[3].toLowerCase() : '');	    

	var dataParams = {filename: file.name, mimeType: file.type, filePrefix: filePrefix}
	var loadHandler = function(loadEvt) {
	    var arrBuffer = loadEvt.target.result;
	    Slidoc.log('Slidoc.Plugins.Upload.fileUpload.loadHandler:', file.name, file.type, arrBuffer.byteLength);
	    this.remoteCall('_uploadData', loadCallback.bind(this), dataParams, arrBuffer.byteLength);
	    if (!window.GService)
		alert('No upload service');
	    GService.rawWS(arrBuffer);
	};

	var reader = new FileReader();
	reader.onload = loadHandler.bind(this);
	reader.onerror = function(loadEvt) {
	    alert("Failed to read file "+file.name+" (code="+loadEvt.target.error.code+")");
	};

	reader.readAsArrayBuffer(file);
    },
    
    response: function (retry, callback) {
	Slidoc.log('Slidoc.Plugins.Upload.response:', retry, !!callback);
	var fileInfo = this.qattributes && this.persist[this.qattributes.qnumber];
	if (!fileInfo && !window.confirm('Answer file not uploaded. Do you want to give up on trying to upload it?'))
	    return;

	if (fileInfo) {
	    var response = fileInfo.origName;
	    var pluginResp = {name: this.name, score: 1, correctAnswer: '', filename: fileInfo.upload.name,
			      time: fileInfo.uploadTime, fileType: this.fileType, url: fileInfo.upload.url,
			      fileKey: fileInfo.upload.fileKey};
	    this.remoteCall('lockFile', null, fileInfo.upload.url);
	} else {
	    var response = '';
	    var pluginResp = {name: '', score: null, correctAnswer: ''};
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
   </div>
*/
