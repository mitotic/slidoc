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
			       
	this.confirmElem = document.getElementById(this.slideId+'-plugin-Upload-uploadconfirm');
	this.uploadElem = document.getElementById(this.slideId+'-plugin-Upload-uploadbutton');
	this.uploadElem.addEventListener('change', this.fileUpload.bind(this), false);

	this.response = '';
    },

    display: function (response, pluginResp) {
	Slidoc.log('Slidoc.Plugins.Upload.display:', this, response, pluginResp);
	this.confirmElem.textContent = this.response;
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
	var fType = fileTypeMap[file.type] || file.name.split('.').slice(-1);
	if (this.fileTypes.indexOf(fType.toLowerCase()) < 0) {
	    alert('Invalid file type '+fType+'; expecting one of '+this.fileTypes);
	    return;
	}

	var response = file.name+', '+file.size+' bytes';
	if (file.lastModifiedDate)
	    response += ', last modified: '+file.lastModifiedDate.toLocaleDateString();

	var loadCallback = function(result) {
	    if (!result || result.error) {
		alert('Error in uploading file: '+( (result && result.error) ? result.error : ''));
		return;
	    }
	    this.response = response;
	    this.confirmElem.textContent = this.response;
	}

	var loadHandler = function(loadEvt) {
	    var arrBuffer = loadEvt.target.result;
	    Slidoc.log('Slidoc.Plugins.Upload.fileUpload.loadHandler:', file.name, file.type, arrBuffer.byteLength);
	    this.remoteCall('uploadData', loadCallback.bind(this), file.name, file.type, arrBuffer.byteLength);
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
	var pluginResp = {name: this.name, score: null, answer: ''};
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
   PluginBody:
   <input type="file" id="%(pluginId)s-uploadbutton" 
   class="slidoc-clickable slidoc-button slidoc-plugin-upload-button %(pluginSlideId)s-upload-uploadbutton"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].fileUpload(this);"></input>
   <div id="%(pluginId)s-uploadconfirm"></div>
*/
