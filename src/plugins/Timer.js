Timer = {
    // Simple Timer plugin
    global: {
	initGlobal: function() {
	    Slidoc.log('Slidoc.Plugins.Timer.setup.initGlobal:');
	    this.timerButton = document.getElementById(this.pluginLabel+'-timerbutton');
	    this.timerValue = document.getElementById(this.pluginLabel+'-timervalue');
	    this.timer = null;
	    this.timerValue.value = 60;
	    if (this.testUser) {
		this.stop();
	    } else {
		this.timerButton.value = CLOCK;
		this.timerButton.disabled = 'disabled';
		this.timerValue.disabled = 'disabled';
	    }
	},

	stop: function() {
	    Slidoc.log('Slidoc.Plugins.Timer.stop:');
	    if (this.timer) {
		clearInterval(this.timer);
		this.timer = null;
	    }
	    Slidoc.sendEvent(-1, 'Timer.clockTick', this.timerValue.value);
	    this.timerValue.disabled = null;
	    this.timerButton.value = PLAY;
	},

	start: function() {
	    Slidoc.log('Slidoc.Plugins.Timer.start:');
	    this.stop();
	    this.timerButton.value = STOP;
	    this.timerValue.disabled = 'disabled';
	    this.timer = setInterval(this.advance.bind(this), 1*1000);
	},

	timerClick: function() {
	    Slidoc.log('Slidoc.Plugins.Timer.timerClick:');
	    if (this.timerButton.value == PLAY) {
		this.start();
	    } else {
		this.stop();
	    }
	},
	
	clockTick: function(value) {
	    Slidoc.log('Slidoc.Plugins.Timer.clockTick:', value);
	    this.timerValue.value = ''+value;
	},

	advance: function() {
	    Slidoc.log('Slidoc.Plugins.Timer.advance:');
	    try {
		var value = parseInt(this.timerValue.value);
		if (value > 0) {
		    value = value - 1;
		} else {
		    value = 0;
		}
	    } catch(err) {
		Slidoc.log('Slidoc.Plugins.Timer.advance: Error '+err);
		value = 0;
	    }
	    this.clockTick(value);
	    Slidoc.sendEvent(-1, 'Timer.clockTick', value);
	    if (!value)
		this.stop();
	}
    }
};

var PLAY = '\u25BA';
var STOP = '\u25FC';
var CLOCK = '\u23F0';

/* PluginHead:
   <style>
   input.slidoc-plugin-Timer-value {width: 4em;};
   </style>
   PluginTop:
   <input type="button" id="%(pluginLabel)s-timerbutton"
   class="slidoc-clickable slidoc-button slidoc-plugin-Timer-button"
   value=""
   onclick="Slidoc.Plugins['%(pluginName)s'][''].timerClick();"></input>
   <input type="number" step="10" id="%(pluginLabel)s-timervalue"
   class="slidoc-plugin-Timer-value"
   value="60"></input>
*/
