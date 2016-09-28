Slider = {
    // Simple slider plugin

    init: function(slider) {
	// slider = { initval:, minval:, maxval:, stepval:, correctAnswer:,
	//            newValue: function(value){...}, displayCorrect: function(answer){...} }
	Slidoc.log('Slidoc.Plugins.Slider.init:', arguments, this.slideData);
	this.slider = slider;
	this.val = slider.initval || 1;
	this.minval = ('minval' in slider) ? slider.minval : Math.min(this.val,0);
	this.maxval = ('maxval' in slider) ? slider.maxval : Math.max(this.val,10);
	this.stepval = slider.stepval || 1;
	this.label = slider.label || '';
	this.units = slider.units || '';

	this.correctAnswer = null;
	this.errAnswer = 0.0;
	this.correctAnswerStr = '';
	if (slider.correctAnswer) {
	    var corrComps = Slidoc.PluginManager.splitNumericAnswer(slider.correctAnswer);
	    if (corrComps[0] != null && corrComps[1] != null) {
		this.correctAnswer = corrComps[0];
		this.errAnswer = corrComps[1];
		this.correctAnswerStr = slider.correctAnswer;
	    } else {
		Slidoc.log('Slider.init: Error in correct numeric answer:'+slider.correctAnswer);
	    }
	}

	this.labelElem = document.getElementById(this.pluginId+'-label');
	this.unitsElem = document.getElementById(this.pluginId+'-units');
	this.boxElem = document.getElementById(this.pluginId+'-box');
	this.buttonElem = document.getElementById(this.pluginId+'-boxbutton');

	this.sliderElem = document.getElementById(this.pluginId+'-sliderrange');
	this.minElem = document.getElementById(this.pluginId+'-slidermin');
	this.maxElem = document.getElementById(this.pluginId+'-slidermax');

	this.labelElem.innerHTML = this.label;
	this.unitsElem.innerHTML = this.units;
	this.boxElem.value = this.val;
	this.boxElem.min = this.minval;
	this.boxElem.max = this.maxval;
	this.sliderElem.value = this.val;
	this.sliderElem.min = this.minval;
	this.sliderElem.max = this.maxval;
	this.sliderElem.step = this.stepval||1;
	this.minElem.textContent = this.minval;
	this.maxElem.textContent = this.maxval;
    },

    modValue: function (elem) {
	// Modify x, y data
	Slidoc.log('Slidoc.Plugins.Slider.modValue', this.pluginId, elem);
	if (elem.id.slice(-10) == '-boxbutton') {
	    elem = this.boxElem;
	    this.sliderElem.value = elem.value;
	} else {
	    this.boxElem.value = elem.value;
	}
	this.val = elem.value;
	this.slider.newValue(this.val);
    },

    display: function (response, pluginResp) {
	Slidoc.log('Slidoc.Plugins.Slider.display:', this, response, pluginResp);
        try {
	    this.val = parseFloat(response);
	    this.sliderElem.value = this.val;
	    this.boxElem.value = this.val;
	    this.slider.newValue(this.val);
	} catch(err) {
	}
    },

    disable: function (displayCorrect) {
	Slidoc.log('Slidoc.Plugins.Slider.disable:');
	this.boxElem.disabled = 'disabled';
	this.buttonElem.disabled = 'disabled';
	this.sliderElem.disabled = 'disabled';
	if (displayCorrect && this.correctAnswer !== null) {
	    try { this.slider.displayCorrect(this.correctAnswer); } catch(err) {}
	}
    },

    response: function (retry, callback) {
	Slidoc.log('Slidoc.Plugins.Slider.response:', retry, !!callback);
	var pluginResp = {name: this.name};
	if (this.correctAnswer === null) {
	    pluginResp.score = null;
	} else {
	    pluginResp.correctAnswer = this.correctAnswerStr;
	    if (this.val >= this.correctAnswer-1.001*this.errAnswer &&
		this.val <= this.correctAnswer+1.001*this.errAnswer)
		pluginResp.score = 1;
            else
		pluginResp.score = 0;
	}
	if (callback)
	    callback(''+this.val, pluginResp);
    }
};

/* PluginHead:
   <style>
   .slidoc-plugin-Slider-text {
   margin-left: 2px;
   margin-right: 6px;
   font-size: 0.6em;
   }
   .slidoc-plugin-Slider-numbers {
   font-size: 0.6em;
   }
   input[type="number"].slidoc-plugin-Slider-input {
   width: 60px;
   }
   </style>

   PluginBody:
   <!-- Data range slider -->
   <div id="%(pluginId)s-input" class="slidoc-plugin-Slider-div">
   <span id="%(pluginId)s-label" class="slidoc-plugin-Slider-text"></span>
   <input type="number" id="%(pluginId)s-box"  class="slidoc-plugin-Slider-input" value="5"></input>
   <span id="%(pluginId)s-units" class="slidoc-plugin-Slider-text"></span>
   <input type="button" id="%(pluginId)s-boxbutton"  class="slidoc-plugin-Slider-input" value="plot"
   onclick="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].modValue(this);"></input>
   <br>
   <span id="%(pluginId)s-slidermin" class="slidoc-plugin-Slider-numbers"></span>
   <input type="range" id="%(pluginId)s-sliderrange"  class="slidoc-plugin-Slider-input" value="5" min="0" max="10"
   oninput="Slidoc.Plugins['%(pluginName)s']['%(pluginSlideId)s'].modValue(this);"></input>
   <span id="%(pluginId)s-slidermax" class="slidoc-plugin-Slider-numbers"></span>
   </div>

*/
