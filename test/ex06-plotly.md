# Plotly plugin example

<slidoc-script> InteractivePlot = {
    // Data generation plugin
	init: function(xmin, xmax, initval, minval, maxval, stepval) {
		Slidoc.log('Slidoc.Plugins.InteractivePlot.init:', arguments, this.slideData);
		this.xmin = 0 || xmin;
		this.xmax = 10 || xmax;
		this.val = initval || 1;
		this.valCorrect = null;
		this.slider = {label: "\\(\\alpha\\)", units: "",
		               initval:this.val, minval:minval||0, maxval:maxval||100,
		               stepval:stepval||1,
		               newValue: this.newValue.bind(this)}

		var xy = equation(this.val, this.xmin, this.xmax);
	    var data = [{x: xy[0], y: xy[1]}];
	    var layout = { margin: { t: 25, b: 35 },
		               xaxis: {title: "X"},
		               yaxis: {title: "Y"},
			  		   title: "alpha="+this.val};
	    this.plotElem = document.getElementById(this.slideId+'-plot');
	    Plotly.plot(this.plotElem, data, layout);
	},

	newValue: function (value) {
		// Modify x, y data
		Slidoc.log('Slidoc.Plugins.InteractivePlot.newValue:', value);
		this.val = value;
		var xy = equation(this.val, this.xmin, this.xmax);
		Plotly.restyle(this.plotElem, {x: [xy[0]], y: [xy[1]]} );
		Plotly.relayout(this.plotElem, {title: "alpha="+this.val});
	},
};

// Static variables in anonymous context (accessible to the plugin methods)
var nPoints = 300;

function equation(alpha, xmin, xmax) {
	// Compute y=x*(x-alpha)*(x-5)
	var x = [];
	var y = [];
	var delta = (xmax - xmin)/nPoints;
	for (var j=0; j<nPoints; j++) {
	    x.push(xmin + (j+1)*delta);
	    y.push(x[j]*(x[j]-alpha)*(x[j]-5));
    }
	return [x, y];
}
/* HEAD:
<script src="https://cdn.plot.ly/plotly-1.2.0.min.js"></script>
BODY:
<div id="%(pluginSlideId)s-plot" style="width:600px;height:250px;"></div>
*/

// InteractivePlot </slidoc-script>


<slidoc-embed> InteractivePlot(0, 10, 2, 0, 10, 0.1)
\(y = x (x - \alpha) (x-5)\)

%(pluginBody)s

</slidoc-embed>

=Slider(SlidePlugins.InteractivePlot.slider)

