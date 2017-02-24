Submit = {
    // Simple submit plugin

    init: function() {
	Slidoc.log('Slidoc.Plugins.Submit.init:', this);
	this.submitbutton = document.getElementById(this.pluginId+'-submitbutton');
	if (!this.paced)
	    this.submitbutton.disabled = 'disabled';
    }
};

/* HEAD:
   BODY:
   <input type="button" id="%(pluginId)s-submitbutton"  class="slidoc-clickable slidoc-button slidoc-plugin-Submit-button slidoc-noadmin slidoc-noprint slidoc-nograded" value="Submit"
   onclick="Slidoc.submitClick(this);"></input>
*/
