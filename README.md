# Slidoc: A Markdown-based lecture management system

Slidoc manages a collection of lectures written using
[Markdown](https://daringfireball.net/projects/markdown/), which is a
very simple and popular markup syntax. Markdown files are plain text
files saved using extension `.md`. They can be edited using text
editors like Emacs, vi, [Atom](https://atom.io/), and Sublime Text.

Slidoc can publish a set of Markdown files as static HTML files,
[reveal.js](http://lab.hakim.se/reveal-js/) slideshows and
[Jupyter notebooks](https://jupyter-notebook-beginner-guide.readthedocs.org/en/latest/).
It can also create a table of contents, generate an index, manage
questions and analyze concept dependencies.

---

The design goals of Slidoc are:

 1. The raw file format should be as close as possible to the final display format

 2. No specialized software should be required to reorganize/reorder
 the lecture material.

Using the plain text Markdown file format, with some extensions,
accomplishes both these goals. With this format, many open source
tools can be used to process the files. Version control is easy and
sites like [GitHub](https://github.com) can be used to store and share
them.

This README.md provides examples and tests for Slidoc.

Concepts: slides; markdown

---

## Installation and dependencies

All the Slidoc scripts are located in the `src` directory. The
`templates` sub-directory is also needed. Download and unzip/untar to
install. To test, publish this `README.md` file in a temporary
directory:

    ../src/slidoc.py --slides=black ../README.md

Open the `toc.html` file created by the above command in a browser.

Slidoc uses [mistune](https://github.com/lepture/mistune) for HTML
exports, which needs to be installed. It also automatically loads
[reveal.js](https://github.com/hakimel/reveal.js/) for slideshows
(except for presentation mode, which requires the `notes` plugin for
`reveal.js` to be installed in a web-accessible directory).

---

## Lecture management

Say the root directory is `Course`. Typically, all lectures would be
stored in a `Lectures` subddirectory with ordered names like
`prefix-lecture01.md`.

To export some or all lectures to `html` format for web publishing,
create a sub-directory, say `Publish`. In that directory, type:

    slidoc.py ../Lectures/prefix-lecture??.md

The above command will create files named `prefix-lecture01.html` and
so on in that directory. Additionally, it will create two files,
`toc.html` (table of contents) and `ind.html` (concept index).
The files in the `Publish` directory can be served from a web server,
say by renaming `toc.html` to `index.html` using the
`--toc=index.html` option.

Alternatively, the `--combine=all.html` option can be added, which
will combine all the lectures, table of contents and index into a
single file `all.html`, which can be published or shared.

Concepts: lecture management; index, concepts

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

    md2md.py --noconcepts --nonotes doc.md

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

- `--images=import,web,embed --combine=all.html`: Import all image
references, embed them as data URLs and create a single, large,
self-contained HTML document.

- `--images=export,embed`: Export all data URLs from document as local
files, and convert all Markdown image references to HTML `<img>` tags.

---

## Slidoc extensions

Slidoc recognizes several extensions to standard Markdown to
process slides in a lecture.

- Each file begins with a Level 1 title header (`# Lecture Title`)

- Slides are separated by lines with three horizontal dashes (`---`)

- Each slide may have an optional Level 2 header (`## Slide title`)

---

- Two additional pieces of information may optionally be included in
  each slide: a list of concepts and additional notes. (A concept list
  may appear anywhere in the slide, but notes can only appear at the
  very end of the slide.)

Example:

    Concepts: topic1, subtopic1; topic2; another topic, sub topic
 
    Notes: Additional material

Notes:
Concept lists are semicolon-separated and use the syntax `topic,
subtopic` where `topic/subtopic` is a space-separated phrase and
`subtopic` is optional. Concepts are not visible during a slideshow, but are
displayed in the printed version of the lecture.

The concept list is used to generate the index, and the first concept
is assumed to be the main concept discussed in the slide. If there is
no main concept, then the special concept `null` should be specified
as the first concept.

Notes are additional material that are displayed in the printed
version of the lecture. For normal slideshows, notes are not visible
in the main slide, but are normally displayed in vertical slides below
the main slide. (The separator `--` may be used to generate multiple
Notes slides in the vertical.)

An alternative presentation mode, with two views, is also available
for slideshows. In this case, notes are not displayed in the normal
view but only displayed in the presenter view.

---

## Question slides

Slidoc distinguishes between normal slides and slides with
questions. Questions are slides of the form:

    Question statement

    Answer: X

    Concepts: ...

where `X` can be `a`, `b`, etc. for multiple-choice questions, a
number for numeric answers, or some text for open-ended answers. For
unspecified answers, `X` should be as `choice`, `number`, or `text`.
Correct text answers with markup, or spanning multiple lines, can be
provided as Notes or in the next slide with a Level 3 header
containing the word `answer`.

The optional concepts list for questions is analyzed by Slidoc
for dependencies.

Concepts: questions; concept list 

---

### Slide with answer

Level 3 header will not be listed in table of contents. The `--hide=[Aa]nswer`
can be used to hide this answer slide. The `--strip` option will
remove it completely.

---

## Concept dependency analysis

To analyze concept dependency for lectures and exercises delivered,
create a temporary subdirectory and use a command like:

    slidoc.py --qindex=qind.html --crossref=xref.html ../Lectures/prefix-lecture0[1-6].md ../Lectures/prefix-exercise0[123].md

This will generate the concept dependency analysis for the first six
lectures and the first three exercises in the files `index.html`
(concepts index), `qind.html` (questions index), and `xref.html`
(cross-referencing info).

The `qind.html` file has a map analyzing each question for all the
concepts it covers, and relating it to other questions which cover a
subset of these concepts.

Concepts: concept dependency analysis; index, questions

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

    slidoc.py --hide=[Aa]answer --strip ... 

will strip answers completely from the printable `.html` files.

Concepts: answers, hiding; answers, stripping

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

Concepts: slideshow

Notes: To customize the presentation further, edit the
`templates/reveal_template.html` template file.

---

## Slideshow shortcuts

In a `reaveal.js` slideshow, the following keyboard shortcuts may be
useful:

- `f` to enter fullscreen mode, `ESC` to exit

- `o` to enter outline mode, `ESC` to exit

- `Home` (or `Fn+Left Arrow`) for first slide 

- `End` (or `Fn+Right Arrow`) for last slide 

- `?` to display keyboard shortcuts

Concepts: keyboard shortcuts; slideshow

---

## Using presentation mode

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

Concepts: presentation mode

---

## Additional command line options

The `slidoc.py` supports several additional command line
options. Use the following command to display them:

    slidoc.py -i

These options include:

* `--fsize` Font size for `.html` files, e.g., `90%`, `16px`

* `--ffamily` Font family for `.html` files, e.g., `Arial`, `sans-serif`

* `--number` Number all untitled slides (useful for generating
  question banks)

---

The remaining slides are example slides used to illustrate the Markdown
slide format and to test `slidoc.py`

---

## Inline and block formulas

Inline Latex-style formulas are supported via the backtick-dollar ... dollar-backtick
syntax. For example,

    `$ \alpha = \beta *\gamma* \delta $`

renders inline as `$\alpha = \beta *\gamma* \delta$`

Block equations are also supported using the double-dollar syntax:

    $$
    \alpha = \beta *\gamma* \delta
    $$

renders as

$$
\alpha = \beta *\gamma* \delta
$$

(Slideshow: Use Down arrow to view vertical slides with notes)

Concepts: equations; mathjax 

Notes: Equations are also allowed in notes: `$\alpha = \omega$` 

(The ``--`` separator below can be used to create additional
vertical slides containing notes.)

--

Use double backticks (or multiple lines) for inline code with
dollar signs at beginning/end:
``$ beginning dollar``,
``ending dollar
$``)

---

## Code snippets

Code snippets can be included using the *fenced* syntax or the 4-space
indented syntax.

_Fenced_ code snippet

```
def func(a):
    return a**2
```

When converting to notebook format, fenced code is converted to a code cell. 

**Indented** code snippet

    def func2(b):
        return b**2

When converting to notebook format, indented code is not converted to
a code cell (unless explicitly requested).

Concepts: code, fenced; code, indented

---

Slide with no header

*Slides with no header are omitted from the table of contents.*


---

## Slide with image

Flowchart example of image inserted using Markdown syntax:

![El Nino time series](images/elnino.png)

Alternatively, an internal image reference can be used:

![El Nino time series][blank.gif]

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

Slidoc also supports an extension to the Markdown title syntax that
embeds attributes `align`, `height`, and `width` in the title of an
image (either in the link itself or in the definition, in case of a
reference)

![Flowchart](http://upload.wikimedia.org/wikipedia/commons/d/d6/FlowchartExample.png 'title width=100% height=100')


---

## Interactive multiple choice question

This is a multiple choice question that uses the `A.. ` notation
allowing interactive response. (The space after the `..` is required.)
Click on a choice to view the correct answer.

A.. Option1

B.. Option2

C.. Option3

D.. Option4

Answer: B

Concepts: questions, interactive; questions, multiple choice

Notes: This illustrates the interactive format of a multiple choice question.

---

This is a question with a numeric response (no header)

What is the square root of `6.25`?

Answer: 2.5

Concepts: questions, numeric response

---

## Simple function (question)

Write a python function to add two numbers.

Answer: text

Concepts: questions, text response 

Notes: This is an example of an open-ended text answer question.

---

### Simple function (answer)

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

To leave correct answer unspecified for a multiple-choice question,
use the string "choice"

A.. ``Option 1a`` or perhaps ``Option 1b``

B.. ``Option 2a`` or perhaps ``Option 2b``

C.. ``Option 3a`` or
perhaps ``Option 3b``

D.. ``Option 4a`` or
perhaps ``Option 4b``

Answer: choice

Notes: Some info on the correct response.

---

## Open numeric response question

To leave answer unspecified, use the string "number"

Answer: number

---

## Open text response question

To leave answer unspecified, use the string "text"

Answer: text

---

### Open text response question answer

Solution to open response question

Notes: Notes on answer to
open response question
