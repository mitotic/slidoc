<!--slidoc-defaults --hide="[Aa]nswer" --features=equation_number,incremental_slides -->
# Slidoc: A slide-oriented document management system using Markdown

Slidoc manages a collection of lectures and exercises written using
[Markdown](https://daringfireball.net/projects/markdown/), which is a
very simple and popular markup syntax. The lectures and exercises can
include text, images, interactive questions, and equations (using LaTeX
notation).

Markdown files are plain text files saved using extension `.md`. They
can be edited using text editors like Emacs, vi,
[Atom](https://atom.io/), and
[StackEdit](https://stackedit.io). Slidoc can publish the Markdown
files as static HTML files,
[reveal.js](http://lab.hakim.se/reveal-js/) slideshows and/or
[Jupyter notebooks](https://jupyter-notebook-beginner-guide.readthedocs.org/en/latest/).
It can also create a table of contents, generate an index, manage
questions and analyze concept dependencies.

The HTML files generated by Slidoc can be shared via email or hosted
using free resources such as
[public Dropbox folders](http://www.dropboxwiki.com/tips-and-tricks/host-websites-with-dropbox),
[Github project web sites](https://pages.github.com) etc.

---

The design goals of Slidoc documents are:

 1. Easy to write.

 2. Easy to read.

 3. Easy to interact with.

 4. Track understanding of concepts.

This README file provides documentation, examples and tests for Slidoc.

Notes: Using the widely-used Markdown file format, with some
extensions for equations and interactivity, accomplishes the first
goal. With this format, plain text editors and many other open source
tools (such as [Pandoc](http://pandoc.org)) can be used to edit and
process the files. Version control is easy and sites like
[GitHub](https://github.com) can be used to store and share the files.

The remaining goals are achieved using plain vanilla HTML files with
embedded Javascript, allowing easy navigation between slides and
lectures. The format is mobile-friendly and allows "index navigation",
i.e., scrolling through portions of different lectures that discuss
same concept. The embedded Javascript also provides interactivity,
allowing users to answer embedded questions, tallying scores and
tracking understanding of concepts.

Concepts: Slidoc, design goals; slides, Markdown

---

## Installation and dependencies

Slidoc has minimal dependencies. All the Slidoc scripts are located in
the `src` directory. The `templates` sub-directory is also
needed. Download from [Github](https://github.com/mitotic/slidoc) and
unzip/untar to install. To test, publish this `README.md` file in a
temporary directory using the following command:

    ../src/slidoc.py ../README.md

Open the `README.html` file created by the above command in a browser.

Slidoc uses [mistune](https://github.com/lepture/mistune) for HTML
exports, which is included in the `src` directory for
convenience. HTML documents produced by Slidoc automatically load the
[Mathjax](https://www.mathjax.org) library to display equations.

---

## Lecture management

Say the root directory is `Course`. Typically, all lectures would be
stored in a `Lectures` subddirectory with ordered names like
`prefix-lecture01.md`.

To export some or all lectures to `html` format for web publishing,
create a sub-directory, say `Publish`. In that directory, type:

    slidoc.py --outfile=all.html ../Lectures/prefix-lecture??.md

The above command will combine all the lectures, table of contents and
index into a single file `all.html`, which can be published on the web
or shared. (If `--outfile` is not specified, the output file name is
derived from the first input file.)

Alternatively, the `--index_files=toc,ind,qind` option can be used to
generate separate HTML files.  This will create files named
`prefix-lecture01.html` and so on in the `Publish`
directory. Additionally, it will create three files, `toc.html` (table
of contents) , `ind.html` (concept index), and `qind.html` (question
index). These are static web files which can be served from any web
server. In addition to free services such as
[public Dropbox folders](http://www.dropboxwiki.com/tips-and-tricks/host-websites-with-dropbox)
and [Github project web sites](https://pages.github.com), low-cost web
hosting services like [Site44](https://www.site44.com) and
[NearlyFreeSpeech.net](https://www.nearlyfreespeech.net) are also
worth considering.

Concepts: lecture management; index, concepts

---

## Editing Markdown

Markdown files are plain text files saved using extension `.md`. They
can be edited using text editors like Emacs, vi,
[Atom](https://atom.io/), and [StackEdit](https://stackedit.io).  The
[Markdown Preview Plus](https://atom.io/packages/markdown-preview-plus)
package for Atom supports live rendering of Markdown (with math) while
you edit. There is also a
[Chrome extension](https://chrome.google.com/webstore/detail/markdown-preview-plus/febilkbfcbhebfnokafefeacimjdckgl?hl=en-US)
of the same name to render Markdown in the browser.

Concepts: Markdown, editing

---

## Slidoc document structure

Slidoc recognizes several extensions to standard Markdown to
process slides in a lecture.

- Each file begins with a Level 1 title header (`# Lecture Title`) in
  the first slide.

- Each new slide may have an optional Level 2 header (`## Slide title`)
  (Higher-level headers may also be used, but they will not be numbered.)

- If a Level 2 header is not present at the start of a slide, a
  *horizontal rule*, i.e., a line with three or more horizontal dashes
  (`---`), may be used to indicate the start of a slide.

Notes: Any Level 1 header other than the first one will be treated
like a Level 2 header.

Concepts: ; Slidoc, document structure

---

## Concepts and Notes

Two additional pieces of information may optionally be included in
each slide: a list of concepts and additional notes. A concept list
may appear anywhere in the slide, but notes can only appear at the
very end of the slide.

Example:

    Concepts: topic1, subtopic1; topic2; another topic, sub topic
 
    Notes: Additional material

Concept lists are used generate an automatic concept index. Indexing
is done separately for regular slides and question slides. Slidoc
supports concept chain navigation. Starting from the index, you can
easily navigate between all places in the document where a particular
concept is discussed.

Concepts: concepts, list; concepts, multiple;; concepts, tracking

Notes:
Concept lists are semicolon-separated and use the syntax `topic,
subtopic` where `topic/subtopic` is a space-separated phrase and
`subtopic` is optional. Concepts are not visible during a slideshow, but are
displayed in the printed version of the lecture.

The first concept in the list is assumed to be the primary concept
relevant to the slide. Additional concepts are treated as secondary
concepts. If there is no primary concept, then the concept list should
start with a semicolon (see previous slide). If there are multiple
primary concepts, then a double semicolon should be used to separate
them from secondary concepts (as in this slide).

Notes are additional material that appear below the main content. In
slideshow mode (see below), notes are normally shown collapsed (or
hidden) in the slide for compactness, but may be expanded and scrolled
into view.

---

## Slideshow mode and quick navigation

Slidoc features a built-in "slideshow" mode, allowing you to switch
seamlessly between scroll view and slide view anywhere in the
document. Slide view is enabled by clicking on the square
(<span>&#9635;</span>) icon on the bottom left.  The Escape key may
also be used to enter/exit slide mode. Pressing `?` during a slideshow
displays a list of keyboard shortcuts.

The slideshow mode can be used for quick navigation around the document:

- Press Escape to enter slideshow

- Use `h`, `e`, `p`, `n`, or left/right arrow keys to move around quickly

- Press Escape to exit slideshow

Concepts: slideshow; navigation

Notes: Unlike a true slideshow, vertical scrolling is permitted in each
slide, allowing essentially unlimited supporting material such as
Notes.

---

## Incremental lists

Specifying the command option `--features=incremental_slides` enables
incremental display of lists and fragments in slideshows using
[Pandoc syntax](http://pandoc.org/README.html#incremental-lists).

> - Block quoted lists (like this) are displayed incrementally.

> - Use the *Down* arrow to display incremental elements.

> - The keyboard shortcut `i` may also be used.

The ellipsis (`...`) may also be to indicate incremental display of
remaining paragraphs.

...

Alternatively, the CSS classes `slidoc-incremental1`,
`slidoc-incremental2` and so on may be added to elements for
incremental display (see [Another slide with images](#)).

...

Final paragraph.

Concepts: incremental display; lists, incremental 

---

## Paced mode

Slidoc supports a restrictive type of slideshow mode known as the
paced mode, where the user is forced to view the document as a
sequence of slides. Information about the state of a paced slideshow
is saved in the persistent local storage of the browser, using the
filename as the key. It is enabled by the option:

    --pace=pace_level,delay_sec,try_count,try_delay

* `pace_level` if non-zero, implies that document is to be viewed in
  in an incremental fashion, as a slideshow, until the last slide is
  reached. (If less than two, switching to scrolling view is
  permitted.)

* `delay_sec` if non-zero, forces a minimum delay between slides

* `try_count` if non-zero, forces each question to be attempted at
  least this many times (except for multiple-choice, where only one
  attempt is required).

* `try_delay` if non-zero, forces a wait after an incorrect attempt.

The Notes portion of a question slide is hidden until a correct
response is received or all tries are exhausted.

Concepts: paced mode

---

## Adaptive assessment in paced mode

Slides can normally be advanced only one at a time in paced mode. This
means that "slide skipping", i.e., forward slide navigation through
[internal links](#int-link) is typically not used in paced
mode. However, if a set of consecutive questions is answered
correctly, forward slide navigation is enabled. Thus, a single forward
slide link can be included in the final question in a sequence to
enable *adaptive assessment*. (The forward link could be hidden in the
Notes portion, so that it only becomes visible after the question is
answered.)

If you answer the sequence of questions correctly, you earn the
privilege of skipping the next several slides (up to the forward link
destination). The skipped portion may contain extra questions and
explanatory material aimed at those who failed to answer
correctly. Those who earn the privilege of skipping the extra
questions automatically receive full credit for those
questions. However, they may still choose to answer some or all of the
extra questions (without penalty for answering incorrectly).

Concepts: adaptive assessment 

---

## Scores and concept understanding analysis

When you attempt each question in a Slidoc document, along with the
score, the concepts associated with that question are also tracked.
The score is displayed on the top right corner.  By clicking on the
score, you can view a list of concepts associated with the questions
that you answered incorrectly, sorted in decreasing order of
difficulty.

---

## Concept dependency analysis

To analyze concept dependency for lectures and exercises delivered,
create a temporary subdirectory and use a command like:

    slidoc.py --index_files=toc,ind,qind --crossref=xref.html ../Lectures/prefix-lecture0[1-6].md ../Lectures/prefix-exercise0[123].md

This will generate the concept dependency analysis for the first six
lectures and the first three exercises in the files `ind.html`
(concepts index), `qind.html` (questions index), and `xref.html`
(cross-referencing info).

The `qind.html` file has a map analyzing each question for all the
concepts it covers, and relating it to other questions which cover a
subset of these concepts.

Concepts: concept dependency analysis; index, questions

---

## Internal links and numbering {#int-link}

Slidoc supports internal links that refer to other slides using a
 `#` in the reference syntax:
 
    [text](#header)

If `header` is the same as text, a simpler notation may be used:

    [text](#)

Headers (at all levels) are automatically referrable. For example,
see [another answer](#Simple function code answer) or
[Simple function code answer](#).

If the header name is too long to be conveniently linked, a shorter
reference can be appended to the header using the notation:

    ## header {#short-ref}

like the one that links to [this slide](#int-link). Short references
may only contain letters, digits, underscores, hyphens and dots.

Notes: To refer to an arbitrary portion of non-header text, define the
reference using the notation:

    [phrase]{#mnemonic}

This [phrase]{#mnemonic} can be referred to elsewhere as [phrase](#mnemonic):

    [phrase](#mnemonic)

Double hash `##` links may be used to refer to concept index entries, like
[markdown](##) or [multiple-choice questions](##questions, multiple choice):

    [markdown](##) OR [multiple-choice questions](##questions, multiple choice)

Link prefixes of the form `#:` may be used to append automatically
generated counter values, like figure numbers:

    [Figure ]{#:my_figure}. Figure caption

[Figure ]{#:my_figure} can then can be referred to elsewhere as

	[Figure ](#:my_figure)

Look at [Figure ](#:my_figure). For figure numbers with sections
(e.g., 1.2), use `#::my_sectional_figure`.

For references, the above syntax allows for two options:

    [Newton (1687)](#ref-newton1687)

    []{#ref-newton1687} Newton, I., 1687: ... 

for author-based references like [Newton (1687)](#ref-newton1687)

[]{#ref-newton1687} Newton, I., 1687: ...  

Alternatively,

    [[](#:ref-einstein1905)]

    []{#:ref-einstein1905}. Einstein, A., 1905: ... 

for numeric references[[](#:ref-einstein1905)].

[]{#:ref-einstein1905}. Einstein, A., 1905: ... 

---

## Question slides

Slidoc distinguishes between normal slides and slides with
questions. Questions are slides of the form:

    Question statement

    Answer: X

    Concepts: ...

where `X` can be `a`, `b`, etc. for multiple-choice questions, a
number for numeric answers, or some text for open-ended answers. For
unspecified answers, `X` should be `choice`, `number`, or `text`.
Correct text answers with markup, or spanning multiple lines, can be
provided as Notes or in the next slide with a Level 3 header
containing the word `answer`.

The optional concepts list for questions is analyzed by Slidoc
for dependencies.

Concepts: questions; concept list 


---

### Slide with answer

Level 3 header will not be listed in table of contents. The `--hide=[Aa]nswer`
can be used to hide this answer slide.

Notes: Adding the `--strip=hidden` option will remove it completely.

---

## Hidden headers {.slidoc-hidden}

Pandoc-style attributes may added to headers, as shown above, to hide
headers. This may be useful if the slide already contains an image
including the header text.

---

## Hiding and/or stripping solutions

By specifying a match pattern (regex) for slide titles, answers in
question slides and text slides containing answers can be hidden at
first glance. Clicking on the answer prefix or the slide title will
reveal the answers. The following command will hide all slides with
the string `Answer` or `answer` in the title (as well as answers
specified in question slides).

    slidoc.py --hide=[Aa]answer ... 

The following command

    slidoc.py --hide=[Aa]answer --strip=hidden ... 

will strip answers completely from the printable `.html` files.

Concepts: answers, hiding; answers, stripping

---

## Converting to Jupyter Notebooks

Lecture files may be converted to
[Jupyter notebooks](https://jupyter-notebook-beginner-guide.readthedocs.org/en/latest/)
by specifying the `--notebook` option to `slidoc.py`.
By default, concept lists are stripped during this conversion process.

Alternatively, to simply convert to notebooks, use the `md2nb.py` command:

    md2nb.py ../Lectures/prefix-lecture03.md ../Lectures/prefix-lecture04.md

By default, all fenced code blocks are converted to code
cells. Specifiying the `--indented` option also converts indented code
blocks to code cells. Use the `-h` option to list all command options.

The reverse conversion, from notebook to Markdown format, can be
accomplished using `nb2md.py`. Another script, `md2md.py`, can be used to
transform Markdown documents by removing concept lists,
embedding/exporting images etc.

Concepts: jupyter notebook; code, fenced; code, indented

---

## Managing images

Handling images is a bit hard when using Markdown. For Slidoc,
the convention is to use web URLs or to store images in a local
subdirectory named `images` and include references of the form

    ![alt text](images/figure1.png)

The script `md2md.py` can be used to apply several Markdown
tranformations as follows:

    md2md.py --strip=concepts,notes doc.md

The above example creates a new file `doc-modified.md` with concept lists and
notes stripped out.

Notes: Other supported operations include:

- `--fence|--unfence`: Convert fenced code to indented code and vice versa

- `--images=check,web`: Check that all image references in the document are
valid, including web references.

- `--images=copy --dest_dir=...`: Copy all image references to
destination

- `--images=import,web`: Import all image references into the document
as data URLs (including web URLs)

- `--images=import,web,embed`: Import all image
references, embed them as data URLs and create a single, large,
self-contained HTML document.

- `--images=export,embed`: Export all data URLs from document as local
files, and convert all Markdown image references to HTML `<img>` tags.

- `--strip=extensions`: Strip `slidoc`-specific extensions.

---

## Viewing slides with reveal.js

Slidoc supports creating slideshows using
[reveal.js](http://lab.hakim.se/reveal-js/). To enable it, specify
`--slides=THEME,CODE_THEME,FSIZE,NOTES_PLUGIN` the option. This will
create a `*-slides.html` file will be created for each source file.

a. `THEME`: Text theme for `reveal.js`, e.g., `black`, `white`, [(more)](http://lab.hakim.se/reveal-js/#/themes)

b. `CODE_THEME`: Code theme for `highlight.js`, e.g., `github`, `zenburn`, [(more)](https://highlightjs.org/static/demo/)

c. `FSIZE`: Font size, e.g., `200%`

d. `NOTES_PLUGIN`: Local directory where the `notes` plugin is
installed (for presentation mode, see below)

Any of the above can be a null string, or be omitted, e.g. `--slides=,`
or `--slides=,,190%`

Concepts: reveal.js; slideshow, reveal.js

Notes: To customize the presentation further, edit the
`templates/reveal_template.html` template file.

Notes appear as a vertical slide. The separator `--` may be used to
split up the notes as multiple slides in the vertical. An alternative
presentation mode, with two views, is also available. In this case,
notes are not displayed in the normal view but only displayed in the
presenter view.

---

## reveal.js shortcuts

In a `reveal.js` slideshow, the following keyboard shortcuts may be
useful:

- `f` to enter fullscreen mode, `ESC` to exit

- `o` to enter outline mode, `ESC` to exit

- `Home` (or `Fn+Left Arrow`) for first slide 

- `End` (or `Fn+Right Arrow`) for last slide 

- `?` to display keyboard shortcuts

Concepts: reveal.js, keyboard shortcuts; slideshow, reveal.js

---

## reveal.js presentation mode

`reveal.js` has a presentation mode which displays a timer, notes for
the current slide, as well as a preview of the next slide. This mode
requires the installation of the notes plugin files in a local
subdirectory where the contents files are located (symlinking should
also work).

If the plugin is installed in `reveal.js/plugin/notes`, use the
command

    slidoc.py --slides=,,,reveal.js/plugin/notes

to generate the slides file.

When viewing slides, type `s` to open a new browser window with the
presentation mode. Turn off any mirroring of displays. Display the
standard window on the projected window and the presentation window in
the desktop/laptop window.

Concepts: reveal.js, presentation mode

---

## Printing slidoc documents

Although `slidoc` are best viewed as HTM documents, sometime you may
need to print them or save them as PDF files.

You can create a single document from a set of Markdown files, open it
in the browser, and select the *Show all chapters* option. You can
then print it or save it as PDF. (The `--printable` option can be used
to preserve internal links when printing, but it should not be used
for web view.)

To customize what appears in the document, you can use the `--strip`
option. It accepts a list of comma-separated values from the list
`answers,chapters,concepts,contents,hidden,navigate,notes,rule,sections`

You can also specity `--strip=all` or `--strip=all,but,...`

Concepts: printing; PDF


---

## Additional command line options

The `slidoc.py` supports several additional command line
options. Use the following command to display them:

    slidoc.py -h

These options include:

* `--css` To use custom CSS file (by modifying `templates/doc_custom.css`) 

* `--toc_header` To insert custom Markdown or HTML header before Table of Contents

* `--features=equation_number` To automatically number Mathjax equations 

* `--features=untitled_number` Number all untitled slides (useful for generating
  question banks)

Default options for the `slidoc.py` command can be specified in the first
line of the first file using the following format:

    <!--slidoc-defaults --hide="[Aa]nswer" --features=equation_number -->

The above line appears as the first line of this README file. (These
options can be overridden by explicity specifying options in the
command line.)

Concepts: command line, options; options, default

---

The remaining slides are example slides used to illustrate the Markdown
slide format and to test `slidoc.py`

---

## Inline and block formulas

Inline formulas are supported using the LaTeX-style syntax. For
example,

    \(\alpha = \beta *\gamma* \delta\)

renders inline as \(\alpha = \beta *\gamma* \delta\). Enable the
`--features=tex_math` option if you want to use the TeX `$` syntax:

    $\alpha = \beta *\gamma* \delta$

which would render as $\alpha = \beta *\gamma* \delta$.

Block equations are also supported using the LaTeX block syntax:

    \[
      \alpha = \beta *\gamma* \delta
    \]

renders as

\[
\alpha = \beta *\gamma* \delta
\]

Can also use Latex-style equation blocks:

    \begin{equation}
       \label{eq:a}
       E = mc^2
    \end{equation}

which renders as

\begin{equation}
   \label{eq:a}
   E = mc^2
\end{equation}

Using the `--features=equation_number` option for automatic equation numbering, you
can refer to the above equation inline as

    \(\ref{eq:a}\)

which renders as (\(\ref{eq:a}\))

Concepts: equations; mathjax 

Notes: Equations are also allowed in notes: \(\alpha = \omega\) 

(The ``--`` separator below can be used to create additional
vertical slides containing notes in `reveal.js`.)

---

## Code snippets

Code snippets can be included using the *fenced* syntax or the 4-space
indented syntax.

_Fenced_ code snippet

```python
def sq(a):
    return a**2
print 'The square of 4 is', sq(4)
```

```nb_output
The square of 4 is 16
```

When converting to notebook format, fenced code is converted to a code
cell. For fenced code, the pseudo-language `nb_output` can be used to
indicate the output produced by executing a notebook cell (as shown
above).

**Indented** code snippet

    def sq(b):
        return b**2
    print 'The square of 4 is', sq(4)

When converting to notebook format, indented code is not converted to
a code cell (unless explicitly requested).

Concepts: code, fenced; code, indented

---

Slide with no header

*Slides with no header are omitted from the table of contents.*


---

## Slide with image

Flowchart example of image (*[Image ](#:elnino1)*) inserted using Markdown syntax:

![El Nino time series](images/elnino.png)

*[Image ]{#:elnino1}*: El Nino time series

Alternatively, an internal image reference can be used:

![El Nino time series][blank.gif]

*[Image ]{#:elnino2}*: Another El Nino time series

The reference `blank.gif` can be defined elsewhere in the
document. The definition can be a web URL or a data URL:

    [blank.gif]: data: URL "title height=100"

[blank.gif]: data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw== 'file=MyImage.png height=50' 

---

## Another slide with images

Images can also be inserted directly as HTML tags (allowing control
over height/width)

    <img height=100 src="http://upload.wikimedia.org/wikipedia/commons/d/d6/FlowchartExample.png">

<img height=100 src="http://upload.wikimedia.org/wikipedia/commons/d/d6/FlowchartExample.png">

*[Image ]{#:flowchart}*: Flowchart

Slidoc also supports an extension to the Markdown title syntax that
embeds attributes `align`, `height`, and `width` in the title of an
image (either in the link itself or in the definition, in case of a
reference). Style classes can also be included using the `.class`
notation, such as in the example below that incrementally displays the image.

![Flowchart](http://upload.wikimedia.org/wikipedia/commons/d/d6/FlowchartExample.png 'title width=100% height=100 .slidoc-incremental1')

*[Image ]{#:resized}*: Resized image

Concepts: image, metadata; image, style; image, incremental

---

## Interactive questions

Slidoc supports a simple format for framing interactive questions.
For multiple-choice questions, the format is similar to the
[Aiken format](https://docs.moodle.org/24/en/Aiken_format) used by
Learning Management Systems like Moodle. For numeric response
questions, formulas (similar to Excel macros) may be used to randomize
the question (see [Interactive numerical response question](#)). Text
response ("essay") questions are also supported.

The next slide contains a multiple choice question that uses the `A.. `
notation allowing interactive response. (The space after the `..` is
required.) Click on a choice to view the correct answer.

Concepts: questions, interactive; questions, multiple-choice; questions, numeric response; questions, formulas; questions, text response

---

In Shakespeare's play *Hamlet*, the protagonist agonizes over
answering a multiple-choice question. What choice does he agonize
over?

A.. Letter A

B.. Letter B

C.. Letter C

D.. Letter D

Answer: B

Concepts: questions, interactive; questions, multiple-choice

Notes:

    To be or not to be-that is the question:
    Whether 'tis nobler in the mind to suffer
    The slings and arrows of outrageous fortune,
    Or to take arms against a sea of troubles,
    And, by opposing, end them. 

---

## Interactive numerical response question

What is the square root of `=sqrtTest.number();6.25`?


PluginDef: sqrtTest = {
// Sample code for embedding Javascript formulas ("macros") in questions and answers.
// Plugin object sqrtTest is automatically attached to global object SlidocPlugins
// Special function init is called for each slide. 
// Define formulas as functions in the plugin object.
// Special function expect should return the expected answer. 
// Use this.pluginId for a slide-specific ID.
// Use this.randomNumber() to generate uniform random number between 0 and 1.
// Use this.randomNumber(min, max) to pick equally probable integer values between min and max (inclusive).
// (Random number choices will only change if the session is reset.)
// Define any persistent objects after the plugin object (in an anonymous namespace). 
//
    init: function() {
	    console.log('sqrtTest.init:', this.pluginId);
  	    // Pick a random integer between 2 and 19, and then divide by 2 
	    var randInt = this.randomNumber(2,19);
	    randVals[this.pluginId] = (0.5*randInt).toFixed(1);
    },

    number: function() {
	    console.log('sqrtTest.number:', this.pluginId, randVals[this.pluginId]);
	    return (randVals[this.pluginId]*randVals[this.pluginId]).toFixed(2);
    },

    expect: function() {
	    console.log('sqrtTest.expect:', this.pluginId, randVals[this.pluginId]);
	    return randVals[this.pluginId]+' +/- '+'0.1';
    }
}
var randVals = {}; // Optional persistent object
PluginEnd:


Answer: sqrtTest.expect();2.5 +/- 0.1

Concepts: questions, numeric response; questions, formulas; questions, randomized

Notes: An optional error range may be provided after `+/-`.

Embedded javascript functions may be used as formulas, using the notation

    =plugin_name.func_name()

To display a default reference value, append it, separated by a
semicolon (`;`). View the raw Markdown text for this document to see
the embedded javascript code that randomizes the question.

---

## Text response

The dinosaur named tyrant lizard is more commonly known as?

Answer: T.Rex OR T Rex OR T-Rex OR Tyrannosaurus Rex

Concepts: questions, text response

Notes: The upper-case OR is used to separate correct answer options,
which are not case-sensitive. If a correct answer option includes a
space (e.g., `T Rex`, it is compared to the user response with
normalized spaces, i.e, `T Rex` would be considered correct, but not
`TRex`). If the correct answer option does not include a space, such as
the answer to a coding question, then all spaces are stripped from the
user response before comparison, i.e., `T.Rex` and `T. Rex` would be
considered correct.

---

## Simple function code (question)

Write a python function to add two numbers.

Answer: text/code

Concepts: questions, text response 

Notes: This is an example of an open-ended text answer question.

---

### Simple function code answer

The answer

```
def add(a, b):
    c = a + b
    return c
```

Notes: The above function accepts two arguments and returns the sum of
the two arguments.

--

This is an example to test hiding of answer slides.

---

## Tables (markdown extension)

| Item      | Value | Qty |
| --------- | -----:|:--: |
| Computer  | $1600 | 5   |
| Phone     |   $12 | 12  |
| Pipe      |    $1 |234  |

---

## Open multiple choice question

What is the best way to deal with climate change?

A.. Mitigation

B.. Adaptation

C.. Geoengineering

D.. Move to Mars

Answer: choice

Notes: If no correct answer is provided, all answers are scored as
being correct.

---

## Open numeric response question

What number is the answer to the Ultimate Question of Life, the Universe and Everything?

Answer: number

Notes: All answers are assumed correct.

---

## Open text response question

To be or not to be - that is the question. What is the answer?

Answer: text

Notes: All answers are assumed correct.

---

### Open text response question answer

Solution to open response question

Notes: Notes on answer to
open response question

---

## Linking Slidoc sessions a Google Docs spreadsheet

Slidoc paced sessions may be linked to a Google Docs spreadsheet. The
spreadhseet will be updated with information for each user such as the
last access time, slides viewed, questions answered etc. To create the
link, first create a Google Docs spreadsheet, say `sheets101`. Then
attach the script `scripts/slidoc_sheets.js` to `sheets101` using the
`Tools->Script Editor...` menu item. Complete instructions are
provided in the comments in `slidoc_sheets.js`.  Additional
information may also be found in this
[blog post](http://railsrescue.com/blog/2015-05-28-step-by-step-setup-to-send-form-data-to-google-sheets/).
After attaching the script, you can use the *Current web app URL* for
`sheets101` in the command line to generate the HTML documents:

    slidoc.py --google_docs=spreadsheet_url ... 

By default, users will use a unique user name or other identifier
(such as the email address) when they start a paced session. The
Google Docs spreadsheet `sheets101` will contain a separate sheet for
each session, and also an index sheet named `sessions_slidoc`, with
information about all sessions, including any submission due dates
(which can be edited). You can also choose to create a `roster_slidoc`
sheet to restrict user access (see comments in `slidoc_sheets.js` for
more).  The spreadsheet will display a `Slidoc` menu for managing
users and analyzing sessions.

When you set up `slidoc_sheets.js`, you have the option of specifying
a secret HMAC key that you can use to generate login and/or late
submission tokens. The secret can be any printable character string
(usually without spaces). If you use a secret key, include it in the
`slidoc` command, and use the `sliauth.py` command to generate access
tokens:

    slidoc.py --google_docs=spreadsheet_url,key --due_date 2016-05-03T23:59 ...
    sliauth.py -k key user_name(s) # For login tokens 
    sliauth.py -k key -s session_name --due_date 2016-05-10T23:59 user_name(s) # For late submission tokens 

The `Slidoc` menu in the spreadsheet can also be used to automatically
generate and email login tokens and late submission tokens to users
(if the `roster_slidoc` sheet is set up). User may use the late
submission token `none` to submit late without credit.

Submitted sessions can be graded by logging in with user name `admin`
and HMAC key as the token. Change the `gradeDate` entry in the
`sessions_slidoc` sheet to a non-null date value to release the grades
to users after completion of grading.

Notes: Instead of token access, you can require users to authenticate using
their Google account. You will need to create a Web Application attached to your
Google account, obtain its `ClientID` and `API key` and use it as
follows:

    slidoc.py --google_docs=spreadsheet_url,hmac_key,client_id,apiKey ...

[Getting access keys for your application:](https://developers.google.com/api-client-library/javascript/features/authentication#overview)
To get access keys, go to the
[Google Developers Console](https://console.developers.google.com/)
and specify your application's name and the Google APIs it will
access. For simple access, Google generates an API key that uniquely
identifies your application in its transactions with the Google Auth
server.

For authorized access, you must also tell Google your website's
protocol and domain. In return, Google generates a client ID. Your
application submits this to the Google Auth server to get an OAuth 2.0
access token.

Concepts: google docs; due date; login token; late submission token

---

## Embed Jupyter Notebook

A Jupyter Notebook can be embedded in a slide. To enable that, copy
the `Slidoc`-generated `README.html` version of this file to a
subdirectory `files` of the notebook server working directory. The
start the server as follows:

    jupyter notebook --NotebookApp.extra_static_paths='["./files"]'

The notebook server will then statically serve the HTML file from the
following link: `http://localhost:8888/static/README.html`

Within the slide, include the following `iframe` HTML element:

    <iframe src="http://localhost:8888/notebooks/README.ipynb" style="width:720px; height:600px;"></iframe>

Concepts: notebook, embed
