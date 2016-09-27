Viewer = {
    // Simple file viewer plugin

    init: function(viewer) {
	Slidoc.log('Slidoc.Plugins.Viewer.init:', viewer);
	this.iframeElem = document.getElementById(this.pluginId+'-vieweriframe');
	this.imgElem = document.getElementById(this.pluginId+'-viewerimg');

	viewer.displayURL = this.displayURL.bind(this);
	if (viewer.initURL)
	    this.displayURL(viewer.initURL, viewer.fileType);
	    
    },

    displayURL: function (url, fileType) {
	Slidoc.log('Slidoc.Plugins.Viewer.displayURL:', this, url, fileType);
	if (fileType && fileType.match(/^(gif|jpg|jpeg|png)/)) {
	    this.imgElem.src = url;
	    this.imgElem.style.display = null;
	    this.iframeElem.src = '';
	    this.iframeElem.style.display = 'none';
	} else {
	    this.imgElem.src = '';
	    this.imgElem.style.display = 'none';
	    this.iframeElem.src = url;
	    this.iframeElem.style.display = null;
	}
    }
};

/* PluginHead:
   PluginBody:
   <img id="%(pluginId)s-viewerimg" src="" style="display: none;">
   <iframe id="%(pluginId)s-vieweriframe" src=""
   class="slidoc-plugin-Viewer-iframe %(pluginSlideId)s-vieweriframe"
   allowfullscreen frameborder="0" style="display: none;">
   </iframe>
*/
