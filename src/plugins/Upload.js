Upload = {
    // Simple upload plugin

    init: function(fileTypes) {
	// Use either as standalone upload plugin
	//    =Upload('doc,docx')
	// Or as upload response plugin
	//    Answer: pdf,txt=Upload();...
	Slidoc.log('Slidoc.Plugins.Upload.init:', fileTypes);
	var fTypes = (fileTypes || this.correctAnswer || '').trim().split(',');
	this.fileTypes = [];
	for (var j=0; j<fTypes.length; j++)
	    this.fileTypes.push(fTypes[j].trim().toLowerCase());
			       
	this.confirmElem = document.getElementById(this.pluginId+'-uploadconfirm');
	this.uploadElem = document.getElementById(this.pluginId+'-uploadbutton');
	this.uploadElem.addEventListener('change', this.fileUpload.bind(this), false);

	this.response = '';
	this.fileType = '';
	this.viewer = {};
    },

    display: function (response, pluginResp) {
	Slidoc.log('Slidoc.Plugins.Upload.display:', this, response, pluginResp);
	this.response = response;
	this.confirmElem.textContent = this.response ? 'Successfully uploaded '+this.response.split('/').slice(-1) : 'Nothing uploaded';
	if (this.viewer.displayURL) {
	    if (this.fileType == 'ipynb')
		this.viewer.displayURL(this.response ? 'http://nbviewer.jupyter.org/url/'+location.host+this.response : '');
	    else
		this.viewer.displayURL(this.response ? '//'+location.host+this.response : '');
	}
    },

    disable: function (displayCorrect) {
	Slidoc.log('Slidoc.Plugins.Upload.disable:', displayCorrect);
	this.uploadElem.disabled = 'disabled';
    },

    fileUpload: function (evt) {
	Slidoc.log('Slidoc.Plugins.Upload.fileUpload:', evt);
	var files = evt.target.files; // FileList object
	if (files.length != 1) {
	    alert("Please select a single file");
	    return;
	}

	var file = files[0];
	this.fileType = (fileTypeMap[file.type] || file.name.split('.').slice(-1)).toLowerCase();
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
	    this.display(result.value.url || '');
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
	var pluginResp = {name: this.name, score: null, correctAnswer: ''};
	if (!this.response && !window.confirm('Answer file not uploaded. Do you want to give up on trying to upload it?'))
	    return;

	pluginResp.score = 1;
	if (callback)
	    callback(this.response, pluginResp);
    }
};

var fileTypeMap = {
    'application/pdf': 'pdf'
};
		   

/* PluginHead:
   <style>
     .slidoc-plugin-Upload-body {
     font-size: 0.66em;
   }
   </style>
   PluginBody:
   Select file or drag-and-drop over button:
   <input type="file" id="%(pluginId)s-uploadbutton" 
   class="slidoc-clickable slidoc-button slidoc-plugin-Upload-button %(pluginId)s-uploadbutton"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].fileUpload(this);"></input>
   <div id="%(pluginId)s-uploadconfirm"></div>
*/
