<!--slidoc-defaults --pace=1 -->
# audio+delay plugin example

<script type="x-slidoc-plugin"> AudioPace = {
init: function(start,end){
    console.log('AudioPace.init:', this.pluginId, start, end);
	this.start = start;
    this.end = end;
    this.audioElement = document.getElementById(this.pluginId+'-audio');
    // Pre-load audio file
    this.audioElement.src = this.audioElement.dataset.src+'#t='+this.start+','+this.end;
},

enterSlide: function(paceStart){
    console.log('AudioPace.enterSlide:', this.pluginId, paceStart, this.end - this.start);
	if (!paceStart)
	    return null;
	var delaySec = this.end - this.start;
	var audioElem = this.audioElement;
	function hideElem(hide) { audioElem.style.display = hide ? 'none' : null; }
    this.audioElement.addEventListener('loadeddata', function() {
	    setTimeout(hideElem, delaySec*1000.);
        hideElem(true);
	    audioElem.play();
	});
    this.audioElement.src = this.audioElement.dataset.src+'#t='+this.start+','+this.end;
	return delaySec;
},

leaveSlide: function(){
    console.log('AudioPace.leaveSlide:', this.pluginId);
},

buttonClick: function(){
    console.log('AudioPace.buttonClick:', this.pluginId);
	var html = '<b>Audio Plugin</b>';
	Slidoc.showPopup(html);
}

}

/* HEAD:

BUTTON: &#x260A;

BODY:
<audio id="%(pluginId)s-audio" data-src="wheel.mp3" controls>
<p>Your browser does not support the <code>audio</code> element.</p>
</audio>

*/

// AudioPace </script>


=AudioPace(0,4) 

---

## Next slide

=AudioPace(4,8) 

---

## Last slide
