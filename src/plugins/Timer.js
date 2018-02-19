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

	relayCall: function(isAdmin, fromUser, methodName) // Extra args
	{
	    var extraArgs = Array.prototype.slice.call(arguments).slice(3);
	    if (isAdmin)
		return this[methodName].apply(this, extraArgs);

	    return false;
	},

	timeout: function() {
	    Slidoc.log('Slidoc.Plugins.Timer.timeout:');
	},

	stop: function() {
	    Slidoc.log('Slidoc.Plugins.Timer.stop:');
	    if (this.timer) {
		clearInterval(this.timer);
		this.timer = null;
	    }
	    Slidoc.sendEvent('', -1, 'Timer.clockTick', this.timerValue.value);
	    this.timerValue.disabled = null;
	    this.timerButton.value = PLAY;
	    this.timerValue.classList.remove('slidoc-red');
	},

	start: function() {
	    Slidoc.log('Slidoc.Plugins.Timer.start:');
	    this.stop();
	    this.timerButton.value = STOP;
	    this.timerValue.disabled = 'disabled';
	    this.timerValue.classList.remove('slidoc-red');
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
	    if (value < 10) {
		if (value % 2)
		    this.timerValue.classList.add('slidoc-red');
		else
		    this.timerValue.classList.remove('slidoc-red');
	    }
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
	    Slidoc.sendEvent('', -1, 'Timer.clockTick', value);
	    if (!value) {
		this.stop();
		Slidoc.sendEvent('', -1, 'Timer.timeout');
	    }
	}
    },

    init: function() {
	if (Slidoc.PluginManager.submitted()) {
	    this.global.timerButton.style.display = 'none';
	    this.global.timerValue.style.display = 'none';
	}
    }
};

var PLAY = '\u25BA';
var STOP = '\u25FC';
var CLOCK = '\u23F0';

/* HEAD:
   <style>
   input.slidoc-plugin-Timer-value {width: 4em;};
   </style>
   TOP:
   <input type="button" id="%(pluginLabel)s-timerbutton"
   class="slidoc-clickable slidoc-button slidoc-plugin-Timer-button"
   value=""
   onclick="Slidoc.Plugins['%(pluginName)s'][''].timerClick();"></input>
   <input type="number" step="10" id="%(pluginLabel)s-timervalue"
   class="slidoc-plugin-Timer-value"
   value="60"></input>
*/
