Viewer = {
    // Simple file viewer plugin

    init: function(viewer) {
	Slidoc.log('Slidoc.Plugins.Viewer.init:', viewer);
	this.iframeElem = document.getElementById(this.pluginId+'-vieweriframe');

	viewer.displayURL = this.displayURL.bind(this);
	if (viewer.initURL)
	    this.displayURL(viewer.initURL);
	    
    },

    displayURL: function (url) {
	Slidoc.log('Slidoc.Plugins.Viewer.displayURL:', this, url);
	this.iframeElem.src = url;
    }
};

/* PluginHead:
   PluginBody:
   <iframe id="%(pluginId)s-vieweriframe" src=""
   class="slidoc-plugin-Viewer-iframe %(pluginSlideId)s-vieweriframe"
   allowfullscreen frameborder="0">
   </iframe>
*/
