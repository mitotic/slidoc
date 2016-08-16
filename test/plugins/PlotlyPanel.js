PlotlyPanel = {
    // Data plotting plugin

    init: function(plotObj) {
	// plotObj = {traces: [{x:[...], y:[...]}, layout: {xaxis: {...}, yaxis: {..}}, annotate: text} }
	Slidoc.log('Slidoc.Plugins.PlotlyPanel.init:', arguments, this.slideData);
	var data = plotObj.traces;
	var layout = { margin: { t: 5, b: 35 },
		       xaxis: {},
		       yaxis: {} };
	updateObj(layout, plotObj.layout);
	if (plotObj.annotate)
	    layout.annotations = simpleAnnotate(plotObj.annotate);
	this.plotElem = document.getElementById(this.slideId+'-plot');
	Plotly.plot(this.plotElem, data, layout);
	this.slideData.plot = this;
    },

    updateTrace: function(newX, newY, name, n) {
	var utrace = {};
	if (newX)
	    utrace.x = [newX];
	if (newY)
	    utrace.y = [newY];
	if (name)
	    utrace.name = name;
	Plotly.restyle(this.plotElem, utrace, [n||0]);
    },

    addTrace: function (newX, newY, name, lineStyle, color) {
	var trace = { x: newX, y: newY,  mode: 'lines', name: name||'',
		      line: {color: color||'green', dash: lineStyle||'dash'}
		    };
	Plotly.addTraces(this.plotElem, trace);
    },

    updateAxisRange: function (axis, autorange) {
	var updates = {};
	updates[axis+'axis.autorange'] = autorange || false;
	Plotly.relayout(this.plotElem, updates);
    },

    updateAnnotation: function (text) {
	Plotly.relayout(this.plotElem, {annotations:simpleAnnotate(text)});
    }
}

function simpleAnnotate(text, xoffset, yoffset) {
    return [ {
        x: xoffset || 0.75,
        y: yoffset || 0.75,
        xref: 'paper',
        yref: 'paper',
        text: text,
	showarrow: false
    } ];
}

function updateObj(obj, updates) {
    var keys = Object.keys(updates);
    for (var j=0; j<keys.length; j++) {
	var key = keys[j];
	if (key in obj && typeof obj[key] === 'object') {
            updateObj(obj[key], updates[key]);
	} else if (typeof updates[key] === 'object') {
            obj[key] = Array.isArray(updates[key]) ? [] : {};
	    updateObj(obj[key], updates[key]);
	} else {
            obj[key] = updates[key];
        }
    }
}
/* PluginHead:
   <script src="https://cdn.plot.ly/plotly-1.2.0.min.js"></script>
   PluginBody:
   <div id="%(pluginSlideId)s-plot" style="width:600px;height:250px;"></div>
*/
