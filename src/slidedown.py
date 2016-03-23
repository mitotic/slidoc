#!/usr/bin/env python

"""Slidedown is a Markdown based lecture management system.
Markdown filters with mistune, with support for MathJax, keyword indexing etc.
Use $$ ... $$ for block math
Use `$ ... $` for inline math (use ``stuff`` for inline code that has dollar signs at the beginning/end)
Used from markdown.py

See slidedown.md for examples and test cases in Markdown.

Usage examples:
./slidedown.py --hide='[Aa]nswer' --slides=black,zenburn,200% ../Lectures/course-lecture??.md

"""
# Copyright (c) IPython Development Team.
# Modified by R. Saravanan
# Distributed under the terms of the Modified BSD License.

from __future__ import print_function

import os
import re
import sys

from collections import defaultdict, OrderedDict

import mistune

from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound

from xml.etree import ElementTree

def make_id_from_header(header):
    """Make ID string from header string"""
    return re.sub(r'\s*,\s*', ',', re.sub(r'\s+', ' ', header)).replace(' ', '-')

def make_file_id(filename, id_str, fprefix=''):
    return filename[len(fprefix):] + '#' + id_str
    
def make_q_label(filename, question_number, fprefix=''):
    return filename[len(fprefix):]+('.q%03d' % question_number)

def html2text(element):
    """extract inner text from html
    
    Analog of jQuery's $(element).text()
    """
    if isinstance(element, str):
        try:
            element = ElementTree.fromstring(element)
        except Exception:
            # failed to parse, just return it unmodified
            return element
    
    text = element.text or ""
    for child in element:
        text += html2text(child)
    text += (element.tail or "")
    return text

def add_to_index(first_tags, sec_tags, tags, filename, slide_id, header=''):
    if not tags:
        return

    if tags[0] != 'null':
        # List non-null primary tag
        if filename not in first_tags[tags[0]]:
            first_tags[tags[0]][filename] = []

        if header:
            first_tags[tags[0]][filename].append( (slide_id, header) )

    for tag in tags[1:]:
        # Secondary tags
        if filename not in sec_tags[tag]:
            sec_tags[tag][filename] = []

        if header:
            sec_tags[tag][filename].append( (slide_id, header) )


def make_index(first_tags, sec_tags, href, only_headers=False, fprefix=''):
    # if not only_headers, link to file if no headers available
    covered_first = defaultdict(set)
    fsuffixes = OrderedDict()
    tag_list = list(set(first_tags.keys()+sec_tags.keys()))
    tag_list.sort()
    out_list = []
    if href:
        out_list.append('<b>INDEX</b><ul>\n')

    prev_tag_comps = []
    for tag in tag_list:
        tag_comps = tag.split(',')
        tag_str = tag
        if href:
            if not prev_tag_comps or prev_tag_comps[0][0] != tag_comps[0][0]:
                out_list.append('</ul><b>%s</b>\n<ul style="list-style-type: none;">\n' % tag_comps[0][0].upper())
            elif prev_tag_comps and prev_tag_comps[0] != tag_comps[0]:
                out_list.append('&nbsp;\n')
            else:
                tag_str = '___, ' + ','.join(tag_comps[1:])
        
        for fname in first_tags[tag].keys():
            # First tags in each file
            covered_first[fname].add(tag)

        files = list(set(first_tags[tag].keys()+sec_tags[tag].keys()))
        files.sort()
        fsuffix = []
        if href and files:
            out_list.append('<li id="%s"><b>%s</b>:\n' % (make_id_from_header(tag), tag_str))

        start = True
        for fname in files:
            fsuffix.append( fname[len(fprefix):] )
            if href:
                first_headers = first_tags[tag].get(fname,[])
                sec_headers = sec_tags[tag].get(fname,[])
                if not first_headers and not sec_headers and not only_headers:
                    # Link to file (no headers available)
                    if not start:
                        out_list.append(', ')
                    out_list.append('<a href="%s%s" target="_blank"><b>%s</b></a>' % (href, fname+'.html', fname))
                else:
                    for slide_id, slide_header in first_headers:
                        if not start:
                            out_list.append(', ')
                        start = False
                        out_list.append('<a href="%s%s" target="_blank"><b>%s</b></a>' % (href, fname+'.html#'+slide_id, slide_header))
                    for slide_id, slide_header in sec_headers:
                        if not start:
                            out_list.append(', ')
                        start = False
                        out_list.append('<a href="%s%s" target="_blank">%s</a>' % (href, fname+'.html#'+slide_id, slide_header))
        if href and files:
            out_list.append('</li>\n')

        fsuffixes[tag] = fsuffix
        prev_tag_comps = tag_comps

    if href:
        out_list.append('</ul>\n')
        
    return fsuffixes, covered_first, ''.join(out_list)


class Dummy(object):
    pass

Global = Dummy()

Global.first_tags = defaultdict(OrderedDict)
Global.sec_tags = defaultdict(OrderedDict)
Global.first_qtags = defaultdict(OrderedDict)
Global.sec_qtags = defaultdict(OrderedDict)
Global.questions = OrderedDict()
Global.concept_questions = defaultdict(list)


class MathBlockGrammar(mistune.BlockGrammar):
    block_math = re.compile(r'^\$\$(.*?)\$\$', re.DOTALL)
    latex_environment = re.compile(r'^\\begin\{([a-z]*\*?)\}(.*?)\\end\{\1\}',
                                                re.DOTALL)
    meldr_header =   re.compile(r'^ {0,3}<!--meldr-(\w+)\s+(.*?)-->\s*?\n')
    meldr_answer =   re.compile(r'^ {0,3}([Aa]ns|[Aa]nswer):(.*?)(\n|$)')
    meldr_concepts = re.compile(r'^ {0,3}([Cc]oncepts):(.*?)(\n|$)')
    meldr_notes =    re.compile(r'^ {0,3}([Nn]otes):\s*?((?=\S)|\n)')
    minirule =       re.compile(r'^(--) *(?:\n+|$)')

class MathBlockLexer(mistune.BlockLexer):
    default_rules = ['block_math', 'latex_environment', 'meldr_header', 'meldr_answer', 'meldr_concepts', 'meldr_notes', 'minirule'] + mistune.BlockLexer.default_rules

    def __init__(self, rules=None, **kwargs):
        if rules is None:
            rules = MathBlockGrammar()
        super(MathBlockLexer, self).__init__(rules, **kwargs)

    def parse_block_math(self, m):
        """Parse a $$math$$ block"""
        self.tokens.append({
            'type': 'block_math',
            'text': m.group(1)
        })

    def parse_latex_environment(self, m):
        self.tokens.append({
            'type': 'latex_environment',
            'name': m.group(1),
            'text': m.group(2)
        })

    def parse_meldr_header(self, m):
         self.tokens.append({
            'type': 'meldr_header',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_meldr_answer(self, m):
         self.tokens.append({
            'type': 'meldr_answer',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_meldr_concepts(self, m):
         self.tokens.append({
            'type': 'meldr_concepts',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_meldr_notes(self, m):
         self.tokens.append({
            'type': 'meldr_notes',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_minirule(self, m):
        self.tokens.append({'type': 'minirule'})

    
class MathInlineGrammar(mistune.InlineGrammar):
    meldr_choice = re.compile(r"^ {0,3}([a-pA-P])\.\. +")
    math =         re.compile(r"^`\$(.+?)\$`", re.DOTALL)
    block_math =   re.compile(r"^\$\$(.+?)\$\$", re.DOTALL)
    text =         re.compile(r'^[\s\S]+?(?=[\\<!\[_*`~$]|https?://| {2,}\n|$)')


class MathInlineLexer(mistune.InlineLexer):
    default_rules = ['meldr_choice', 'block_math', 'math'] + mistune.InlineLexer.default_rules

    def __init__(self, renderer, rules=None, **kwargs):
        if rules is None:
            rules = MathInlineGrammar()
        super(MathInlineLexer, self).__init__(renderer, rules, **kwargs)

    def output_meldr_choice(self, m):
        return self.renderer.meldr_choice(m.group(1).upper())

    def output_math(self, m):
        return self.renderer.inline_math(m.group(1))

    def output_block_math(self, m):
        return self.renderer.block_math(m.group(1))

    
class MarkdownWithMath(mistune.Markdown):
    def __init__(self, renderer, **kwargs):
        if 'inline' not in kwargs:
            kwargs['inline'] = MathInlineLexer
        if 'block' not in kwargs:
            kwargs['block'] = MathBlockLexer
        super(MarkdownWithMath, self).__init__(renderer, **kwargs)
        
    def output_block_math(self):
        return self.renderer.block_math(self.token['text'])

    def output_latex_environment(self):
        return self.renderer.latex_environment(self.token['name'], self.token['text'])

    def output_meldr_header(self):
        return self.renderer.meldr_header(self.token['name'], self.token['text'])

    def output_meldr_answer(self):
        return self.renderer.meldr_answer(self.token['name'], self.token['text'])

    def output_meldr_concepts(self):
        return self.renderer.meldr_concepts(self.token['name'], self.token['text'])

    def output_meldr_notes(self):
        return self.renderer.meldr_notes(self.token['name'], self.token['text'])

    def output_minirule(self):
        return self.renderer.minirule()

    def render(self, text):
        html = super(MarkdownWithMath, self).render(text)
        return html + self.renderer.end_notes() + self.renderer.end_hide()

    
class IPythonRenderer(mistune.Renderer):
    def __init__(self, **kwargs):
        super(IPythonRenderer, self).__init__(**kwargs)
        self.file_header = ''
        self.header_list = []
        self.hide_end = None
        self.notes_end = None
        self.section_number = 0
        self.question_number = 0
        self.untitled_number = 0
        self.slide_number = 0
        self._new_slide()
        self.first_id = self.get_slide_id()

    def _new_slide(self):
        self.slide_number += 1
        self.choice_end = None
        self.cur_choice = ''
        self.cur_qtype = ''
        self.cur_header = ''
        self.cur_answer = False
        self.slide_concepts = ''
        self.first_para = True

    def get_slide_id(self):
        return 'slide%02d-%03d' % (self.options['filenumber'], self.slide_number)

    def start_block(self, id_str, display='none', style=''):
        prefix =          '<!--meldr-block-begin['+id_str+']-->\n'
        end_str = '</div>\n<!--meldr-block-end['+id_str+']-->\n'
        suffix =  '<div class="%s %s" style="display: %s;">\n' % (id_str, style, display)
        return prefix, suffix, end_str

    def end_hide(self):
        s = self.hide_end or ''
        self.hide_end = None
        return s

    def end_notes(self):
        s = self.notes_end or ''
        self.notes_end = None
        return s

    def minirule(self):
        """Treat minirule as a linebreak"""
        return '<br>\n'

    def hrule(self):
        """Rendering method for ``<hr>`` tag."""
        if self.choice_end:
            prefix = self.choice_end

        self._new_slide()

        hide_prefix = self.end_hide()
        if self.options["cmd_args"].norule or (self.options["cmd_args"].strip and hide_prefix):
            html = '<p id="%s"></p>' % self.get_slide_id()
        elif self.options.get('use_xhtml'):
            html = '<hr id="%s"/>\n' % self.get_slide_id()
        else:
            html = '<hr id="%s">\n' % self.get_slide_id()

        return self.end_notes()+hide_prefix+html
    
    def paragraph(self, text):
        """Rendering paragraph tags. Like ``<p>``."""
        if not self.cur_header and self.first_para:
            self.untitled_number += 1
            if self.options["cmd_args"].number:
                text = ('%d. ' % self.untitled_number) + text
        self.first_para = False
        return super(IPythonRenderer, self).paragraph(text)

    def header(self, text, level, raw=None):
        """Handle markdown headings
        """
        hide_block = self.options["cmd_args"].hide and re.search(self.options["cmd_args"].hide, text)
        html = super(IPythonRenderer, self).header(text, level, raw=raw)
        if level > 3 or (level == 3 and not (hide_block and self.hide_end is None)):
            # Ignore higher level headers (except for level 3 hide block)
            return html

        try:
            hdr = ElementTree.fromstring(html)
        except Exception:
            # failed to parse, just return it unmodified
            return html

        text = html2text(hdr).strip()

        prefix = ''
        suffix = ''
        hdr_prefix = ''
        if level == 1:
            # Level 1 (file) header
            if not self.file_header:
                # Ignore multiple Level 1 headers
                if self.options['filenumber']:
                    hdr_prefix = '%d. ' % self.options['filenumber']

                self.cur_header = hdr_prefix + text
                self.file_header = self.cur_header

                if not self.options["cmd_args"].noheaders:
                    suffix = '__HEADER_LIST__'

        else:
            # Level 2/3 header
            if level == 2:
                # New section
                self.section_number += 1
                if self.options['filenumber']:
                    hdr_prefix =  '%d.%d ' % (self.options['filenumber'], self.section_number)
                self.cur_header = hdr_prefix + text
                self.header_list.append( (self.get_slide_id(), self.cur_header) )

            # Close previous blocks
            prefix = self.end_notes()+self.end_hide()
            self.hide_end = ''

            if hide_block:
                # Hide answer/solution
                id_str = self.get_slide_id() + '-hide'
                ans_prefix, suffix, end_str = self.start_block(id_str)
                self.hide_end = end_str
                prefix = prefix + ans_prefix
                hdr.set('class', 'meldr-clickable' )
                hdr.set('onclick', "toggleBlock('"+id_str+"')" )

        if hdr_prefix:
            hdr.text = hdr_prefix + (hdr.text or '')

        ##a = ElementTree.Element("a", {"class" : "anchor-link", "href" : "#" + self.get_slide_id()})
        ##a.text = u' '
        ##hdr.append(a)

        # Known issue of Python3.x, ElementTree.tostring() returns a byte string
        # instead of a text string.  See issue http://bugs.python.org/issue10942
        # Workaround is to make sure the bytes are casted to a string.
        return prefix + ElementTree.tostring(hdr) + '\n' + suffix


    # Pass math through unaltered - mathjax does the rendering in the browser
    def block_math(self, text):
        return '$$%s$$' % text

    def latex_environment(self, name, text):
        return r'\begin{%s}%s\end{%s}' % (name, text, name)

    def inline_math(self, text):
        return '`$%s$`' % text

    def meldr_header(self, name, text):
        if name == "type" and text:
            params = text.split()
            type_code = params[0]
            if type_code in ("choice", "multichoice", "number", "text", "point", "line"):
                self.cur_qtype = type_code
                self.question_number += 1
             
        return ''

    def meldr_choice(self, name):
        if not self.cur_qtype:
            self.cur_qtype = 'choice'
            self.question_number += 1
        elif self.cur_qtype != 'choice':
            print("    ****CHOICE-ERROR: %s: Line '%s.. ' implies multiple choice question in '%s'" % (self.options["filename"], name, self.cur_header), file=sys.stderr)
            return name+'.. '

        prefix = ''
        if not self.cur_choice:
            prefix = '<blockquote>\n'
            self.choice_end = '</blockquote>\n'

        self.cur_choice = name

        id_str = self.get_slide_id()
        return prefix+'''<span id="%(id)s-choice-%(opt)s" class="meldr-clickable %(id)s-choice" onclick="choiceClick(this, '%(id)s', %(qno)d, '%(opt)s');"+'">%(opt)s</span>. ''' % {'id': id_str, 'opt': name, 'qno': self.question_number}

    
    def meldr_answer(self, name, text):
        if self.cur_answer:
            # Ignore multiple answers
            return ''
        self.cur_answer = True

        choice_prefix = ''
        if self.choice_end:
            choice_prefix = self.choice_end
            self.choice_end = ''

        if not self.cur_qtype:
            self.question_number += 1

            if text.lower() in ('choice', 'multichoice', 'number', 'text', 'point', 'line'):
                self.cur_qtype = text.lower()
                text = ''
            elif len(text) == 1 and text.isalpha():
                self.cur_qtype = 'choice'
            elif text and text[0].isdigit():
                self.cur_qtype = 'number'
            else:
                self.cur_qtype = 'text'

        if self.options['cmd_args'].strip or not text:
            # Strip correct answers
            return choice_prefix+name.capitalize()+':'+'\n'

        if self.options['cmd_args'].hide:
            id_str = self.get_slide_id()
            attrs_ans = {'id': id_str+'-answer' }
            attrs_corr = {'id': id_str+'-correct'}
            if self.cur_choice:
                attrs_ans.update({'style': 'display: none;'})
            else:
                attrs_ans.update({'class' : 'meldr-clickable', 'onclick': "answerClick(this, '%s', %d, '');" % (id_str, self.question_number)} )
                attrs_corr.update({'style': 'display: none;'})
            ans_elem = ElementTree.Element('div', attrs_ans)
            ans_elem.text = name.capitalize()+': '
            span_corr = ElementTree.Element('span', attrs_corr)
            span_corr.text = text.upper() if len(text) == 1 else text
            ans_elem.append(span_corr)
            span_resp = ElementTree.Element('span', {'id': id_str+'-resp'})
            ans_elem.append(span_resp)
            return choice_prefix+ElementTree.tostring(ans_elem)+'\n'
        else:
            return choice_prefix+name.capitalize()+': '+text+'\n'


    def meldr_concepts(self, name, text):
        if not text:
            return ''

        if self.notes_end is not None:
            print("    ****CONCEPT-ERROR: %s: 'Concepts: %s' line after Notes: ignored in '%s'" % (self.options["filename"], text, self.cur_header), file=sys.stderr)
            return ''

        if self.slide_concepts:
            print("    ****CONCEPT-ERROR: %s: Extra 'Concepts: %s' line ignored in '%s'" % (self.options["filename"], text, self.cur_header), file=sys.stderr)
            return ''

        self.slide_concepts = text

        tags = [x.strip() for x in text.split(";")]
        nn_tags = tags[1:] if tags and tags[0] == 'null' else tags[:]   # Non-null tags

        if nn_tags and (self.options["cmd_args"].index or self.options["cmd_args"].qindex):
            # Track/check tags
            if self.cur_qtype in ("choice", "multichoice", "number", "text", "point", "line"):
                # Question
                nn_tags.sort()
                q_id = make_file_id(self.options["filename"], self.get_slide_id())
                q_concept_id = ';'.join(nn_tags)
                q_pars = (self.options["filename"], self.get_slide_id(), self.cur_header, self.question_number, q_concept_id)
                Global.questions[q_id] = q_pars
                Global.concept_questions[q_concept_id].append( q_pars )
                for tag in nn_tags:
                    if tag not in Global.first_tags and tag not in Global.sec_tags:
                        print("        CONCEPT-WARNING: %s: '%s' not covered before '%s'" % (self.options["filename"], tag, self.cur_header), file=sys.stderr)

                add_to_index(Global.first_qtags, Global.sec_qtags, tags, self.options["filename"], self.get_slide_id(), self.cur_header)
            else:
                # Not question
                add_to_index(Global.first_tags, Global.sec_tags, tags, self.options["filename"], self.get_slide_id(), self.cur_header)

        if self.options['cmd_args'].strip or self.options['cmd_args'].noconcepts:
            # Strip concepts
            return ''

        id_str = self.get_slide_id()+'-concepts'
        tag_html = '<div class="meldr-clickable" onclick="toggleInline(this)">%s: <span id="%s" style="display: none;">' % (name.capitalize(), id_str)

        if self.options["cmd_args"].index or self.options["cmd_args"].qindex:
            first = True
            for tag in tags:
                if not first:
                    tag_html += '; '
                first = False
                tag_html += '<a href="%s%s#%s" target="_blank">%s</a>' % (self.options['cmd_args'].href, self.options['cmd_args'].index, make_id_from_header(tag), tag)
        else:
            tag_html += text

        tag_html += '</span></div>'

        return tag_html+'\n'

    
    def meldr_notes(self, name, text):
        if self.notes_end is not None:
            # Additional notes prefix in slide; strip it
            return ''
        hide_notes = self.cur_answer
        id_str = self.get_slide_id() + '-notes'
        disp_block = 'none' if hide_notes else 'block'
        prefix, suffix, end_str = self.start_block(id_str, display=disp_block, style='meldr-notes')
        self.notes_end = end_str
        return prefix + ('''<a id="%s" class="meldr-clickable" onclick="toggleBlock('%s')" style="display: %s;">Notes:</a>\n''' % (id_str, id_str, 'none' if hide_notes else 'inline')) + suffix


    def table_of_contents(self, filepath='', filenumber=0):
        if len(self.header_list) < 1:
            return ''

        toc = ['<ul style="list-style-type: none;">' if filenumber else '<ol>']

        for id_str, header in self.header_list:  # Skip first header
            elem = ElementTree.Element("a", {"class" : "header-link", "href" : filepath+"#"+id_str})
            elem.text = header
            toc.append('<li>'+ElementTree.tostring(elem)+'</li>')

        toc.append('</ul>\n')
        return '\n'.join(toc)

    def block_code(self, code, lang=None):
        """Rendering block level code. ``pre > code``.
        """
        if lang:
            try:
                lexer = get_lexer_by_name(lang, stripall=True)
            except ClassNotFound:
                code = lang + '\n' + code
                lang = None

        if not lang:
            return '\n<pre><code>%s</code></pre>\n' % \
                mistune.escape(code)

        formatter = HtmlFormatter()
        return highlight(code, lexer, formatter)

    
def markdown2html_mistune(source, filename, cmd_args, filenumber=0, prev_file='', next_file=''):
    """Convert a markdown string to HTML using mistune, returning (first_header, html)"""
    renderer = IPythonRenderer(escape=False, filename=filename, cmd_args=cmd_args, filenumber=filenumber)

    content_html = MarkdownWithMath(renderer=renderer).render(source)

    if not cmd_args.noheaders:
        nav_html = ''
        if cmd_args.toc:
            nav_html += '<a href="%s%s">%s</a>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;' % (cmd_args.href, cmd_args.toc, 'CONTENTS')
        if prev_file:
            nav_html += '<a href="%s%s">%s</a>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;' % (cmd_args.href, prev_file, 'PREV')
        if next_file:
            nav_html += '<a href="%s%s">%s</a>' % (cmd_args.href, next_file, 'NEXT')

        content_html += '<p></p>' + '<a href="#%s">%s</a>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;' % (renderer.first_id, 'TOP') + nav_html
        headers_html = renderer.table_of_contents(filenumber=filenumber)
        if headers_html:
            headers_html = nav_html + headers_html
            if 'meldr-notes' in content_html:
                headers_html += '<p></p><a href="#" onclick="toggleBlock('+"'meldr-notes'"+');">Hide all notes</a>'

        content_html = content_html.replace('__HEADER_LIST__', headers_html)

    if cmd_args.strip:
        # Strip out notes, answer slides
        content_html = re.sub(r"<!--meldr-block-begin\[([-\w]+)\](.*?)<!--meldr-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    file_toc = renderer.table_of_contents(cmd_args.href+filename+'.html', filenumber=filenumber)

    return (renderer.file_header or filename, file_toc, renderer.first_id, content_html)

Mathjax_js = '''<script type="text/x-mathjax-config">
  MathJax.Hub.Config({
    tex2jax: {
      inlineMath: [ ['`$','$`'], ["$$$","$$$"] ],
      processEscapes: false
    }
  });
</script>
<script src='https://cdn.mathjax.org/mathjax/latest/MathJax.js?config=TeX-AMS-MML_HTMLorMML'></script>
'''

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Convert from Markdown to HTML')
    parser.add_argument('--dry_run', help='Do not create any HTML files (index only)', action="store_true")
    parser.add_argument('--fsize', help='Font size in %% or px (default: 90%%)', default='90%')
    parser.add_argument('--ffamily', help='Font family ("Arial,sans-serif,...")', default="'Helvetica Neue', Helvetica, 'Segoe UI', Arial, freesans, sans-serif")
    parser.add_argument('--hide', metavar='REGEX', help='Hide sections matching header regex (e.g., "[Aa]nswer")')
    parser.add_argument('--header', help='HTML header file for ToC')
    parser.add_argument('--href', help='URL prefix to link local HTML files (default: "./")', default='./')
    parser.add_argument('--index', metavar='FILE', help='index file (default: ind.html)', default='ind.html')
    parser.add_argument('--noconcepts', help='Strip concept lists', action="store_true")
    parser.add_argument('--noheaders', help='No clickable list of headers', action="store_true")
    parser.add_argument('--norule', help='Suppress horizontal rule separating slides', action="store_true")
    parser.add_argument('--nosections', help='No section numbering', action="store_true")
    parser.add_argument('--notebook', help='Create notebook files', action="store_true")
    parser.add_argument('--number', help='Number untitled slides (e.g., question numbering)', action="store_true")
    parser.add_argument('--overwrite', help='Overwrite files', action="store_true")
    parser.add_argument('--qindex', metavar='FILE', help='question index file (default: qind.html)', default='qind.html')
    parser.add_argument('--toc', metavar='FILE', help='Table of contents file (default: toc.html)', default='toc.html')
    parser.add_argument('--slides', metavar='THEME,CODE_THEME,FSIZE,NOTES_PLUGIN', help='Create slides with reveal.js theme(s) (e.g., ",zenburn,190%%")')
    parser.add_argument('--strip', help='Strip answers, concepts, notes, answer slides', action="store_true")
    parser.add_argument('file', help='Markdown filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)
    cmd_args = parser.parse_args()

    scriptdir = os.path.dirname(os.path.realpath(__file__))
    templates = {}
    for tname in ('doc', 'toc', 'reveal'):
        f = open(scriptdir+'/templates/'+tname+'_template.html')
        templates[tname] = f.read()
        f.close()

    fnames = []
    for f in cmd_args.file:
        fcomp = os.path.splitext(os.path.basename(f.name))
        fnames.append(fcomp[0])
        if fcomp[1] != '.md':
            sys.exit('Invalid file extension for '+f.name)

        if cmd_args.notebook and os.path.exists(fcomp[0]+'.ipynb') and not cmd_args.overwrite and not cmd_args.dry_run:
            sys.exit("File %s.ipynb already exists. Delete it or specify --overwrite" % fcomp[0])

    nb_args = Dummy()
    if cmd_args.notebook:
        nb_args.href = cmd_args.href
        nb_args.norule = cmd_args.norule
        nb_args.indented = False
        nb_args.noconcepts = True
        nb_args.nomarkup = False
        nb_args.nonotes = False

    style_str = ''
    if cmd_args.fsize:
        style_str += 'font-size: ' + cmd_args.fsize + ';'
    if cmd_args.ffamily:
        style_str += 'font-family: ' + cmd_args.ffamily + ';'

    if cmd_args.slides:
        reveal_themes = cmd_args.slides.split(',')
        reveal_themes += [''] * (4-len(reveal_themes))
        reveal_pars = { 'reveal_theme': reveal_themes[0] or 'white',
                        'highlight_theme': reveal_themes[1] or 'github',
                        'reveal_fsize': reveal_themes[2] or '200%',
                        'reveal_separators': 'data-separator-notes="^Notes:"' if reveal_themes[3] else 'data-separator-vertical="^(Notes:|--\\n)"',
                        'reveal_notes': reveal_themes[3],  # notes plugin local install directory e.g., 'reveal.js/plugin/notes'
                        'reveal_cdn': 'https://cdnjs.cloudflare.com/ajax/libs/reveal.js/3.2.0',
                        'highlight_cdn': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/9.2.0',
                        'reveal_title': '', 'reveal_md': ''}
    else:
        reveal_pars = ''

    flist = []
    fprefix = None
    for j, f in enumerate(cmd_args.file):
        md_text = f.read()
        f.close()

        fname = fnames[j]
        prev_file = fnames[j-1]+".html" if j > 0 else ''
        next_file = fnames[j+1]+".html" if j < len(cmd_args.file)-1 else ''

        if fprefix == None:
            fprefix = fname
        else:
            # Find common filename prefix
            while fprefix:
                if fname[:len(fprefix)] == fprefix:
                    break
                fprefix = fprefix[:-1]

        filenumber = 0 if cmd_args.nosections else (j+1)

        # Strip annotations
        md_text = re.sub(r"(^|\n) {0,3}[Aa]nnotation:(.*?)(\n|$)", '', md_text)

        fheader, file_toc, first_id, md_html = markdown2html_mistune(md_text, filename=fname, cmd_args=cmd_args,
                                                                     filenumber=filenumber, prev_file=prev_file, next_file=next_file)

        outname = fname+".html"
        flist.append( (fname, outname, fheader, file_toc) )

        if cmd_args.dry_run:
            print("Indexed ", outname+":", fheader, file=sys.stderr)
        else:
            params = {'body_style': style_str, 'math_js': Mathjax_js if '$$' in md_text else '',
                      'first_id': first_id, 'content': md_html }
            out = open(outname, "w")
            out.write(templates['doc'] % params)
            out.close()
            print("Created ", outname+":", fheader, file=sys.stderr)

            if cmd_args.slides:
                reveal_md = re.sub(r'(^|\n) {0,3}[Cc]oncepts:(.*?)(\n|$)', '', md_text)
                reveal_md = re.sub(r'\$\$\$(.+?)\$\$\$', r'`$\1$`', reveal_md)
                reveal_md = re.sub(r'(^|\n)\$\$(.+?)\$\$', r'`$$\2$$`', reveal_md, flags=re.DOTALL)

                if cmd_args.strip:
                    reveal_md = re.sub(r'(^|\n) {0,3}([Aa]ns|[Aa]nswer):.*?(\n|$)', r'\3', reveal_md)
                    reveal_md = re.sub(r'(^|\n) {0,3}([Nn]otes):.*?(\n *\n---|$)', r'\3', reveal_md, flags=re.DOTALL)

                    if cmd_args.hide:
                        reveal_md = re.sub(r'(^|\n *\n--- *\n( *\n)+) {0,3}#{2,3}[^#][^\n]*'+cmd_args.hide+r'.*?(\n *\n--- *\n|$)', r'\1', reveal_md, flags=re.DOTALL)
                
                sfilename = fname+"-slides.html"
                sfile = open(sfilename, "w")
                reveal_pars['reveal_title'] = fname
                reveal_pars['reveal_md'] = reveal_md
                sfile.write(templates['reveal'] % reveal_pars)
                sfile.close()
                print("Created ", sfilename, file=sys.stderr)

            if cmd_args.notebook:
                import md2nb
                md_parser = md2nb.MDParser(nb_args)
                nfilename = fname+".ipynb"
                nfile = open(nfilename, "w")
                nb_text = md_parser.parse_cells(md_text)
                nfile.write(nb_text)
                print("Created ", nfilename, file=sys.stderr)

    if cmd_args.toc:
        if cmd_args.header:
            header_file = open(cmd_args.header)
            header_insert = header_file.read()
            header_file.close()
        else:
            header_insert = ''

        toc_html = []
        toc_html.append('<blockquote>\n')
        toc_html.append('<ol>\n' if cmd_args.nosections else '<ul style="list-style-type: none;">\n')
        ifile = 0
        for fname, outname, fheader, file_toc in flist:
            ifile += 1
            id_str = 'toc%02d' % ifile
            slide_link = ''
            if cmd_args.slides:
                slide_link = ',&nbsp; <a href="%s%s" target="_blank">%s</a>' % (cmd_args.href, fname+"-slides.html", 'slides')
            nb_link = ''
            if cmd_args.notebook and cmd_args.href.startswith('http://'):
                nb_link = ',&nbsp; <a href="%s%s%s.ipynb">%s</a>' % (md2nb.Nb_convert_url_prefix, cmd_args.href[len('http://'):], fname, 'notebook')
            doc_link = '<a href="%s%s">%s</a>' % (cmd_args.href, outname, 'document')

            toggle_link = '<a href="#" onclick="toggleTOC(%s);"><b>%s</b></a>' % ("'"+id_str+"'", fheader)
            toc_html.append('<li>%s&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(<em>%s%s%s</em>)</li>\n' % (toggle_link, doc_link, slide_link, nb_link))

            f_toc_html = '<div id="'+id_str+'" class="filetoc" style="display: none;">'+file_toc+'<p></p></div>'
            toc_html.append(f_toc_html)

        toc_html.append('</ol>\n' if cmd_args.nosections else '</ul>\n')

        if cmd_args.index:
            toc_html.append('<a href="%s%s" target="_blank">%s</a><br>\n' % (cmd_args.href, cmd_args.index, 'INDEX'))
        toc_html.append('</blockquote>\n')

        if cmd_args.slides:
            toc_html.append('<em>Note</em>: When viewing slides, type ? for help or click <a target="_blank" href="https://github.com/hakimel/reveal.js/wiki/Keyboard-Shortcuts">here</a>.\nSome slides can be navigated vertically.')

        if not cmd_args.dry_run:
            tocfile = open(cmd_args.toc, 'w')
            tocfile.write(templates['toc'] % {'insert': header_insert, 'content': ''.join(toc_html)})
            tocfile.close()
            print("Created ToC in", cmd_args.toc, file=sys.stderr)

    if cmd_args.index:
        fsuffixes, covered_first, index_html = make_index(Global.first_tags, Global.sec_tags, cmd_args.href, fprefix=fprefix)
        if not cmd_args.dry_run:
            indexfile = open(cmd_args.index, 'w')
            if cmd_args.toc:
                indexfile.write('<a href="%s%s">%s</a><p></p>\n' % (cmd_args.href, cmd_args.toc, 'BACK TO CONTENTS'))
            indexfile.write('<b>CONCEPT</b>\n')
            indexfile.write(index_html)
            indexfile.close()
            print("Created index in", cmd_args.index, file=sys.stderr)

        concfilename = 'concepts.txt'
        concfile = open(concfilename, 'w')
        print("File prefix: "+fprefix, file=concfile)
        print("\nConcepts -> files mapping:", file=concfile)
        for tag, fsuffix in fsuffixes.items():
            print("%-32s:" % tag, ', '.join(fsuffix), file=concfile)

        print("\n\nFirst concepts in each file:", file=concfile)
        for fname, outname, fheader, file_toc in flist:
            tlist = list(covered_first[fname])
            tlist.sort()
            print('%-24s:' % fname[len(fprefix):], '; '.join(tlist), file=concfile)
        concfile.close()
        print("Created concept listings in", concfilename, file=sys.stderr)

    if cmd_args.qindex and Global.first_qtags:
        import itertools
        qout_list = []
        if cmd_args.toc:
            qout_list.append('<a href="%s%s">%s</a><p></p>' % (cmd_args.href, cmd_args.toc, 'BACK TO CONTENTS'))
        qout_list.append('<b>QUESTION CONCEPT</b>\n')
        fsuffixes, covered_first, qindex_html = make_index(Global.first_qtags, Global.sec_qtags, cmd_args.href, only_headers=True, fprefix=fprefix)
        qout_list.append(qindex_html)
        qout_list.append('\n\n<p><b>CONCEPT SUB-QUESTIONS</b><br>Sub-questions are questions that address combinatorial (improper) concept subsets of the original question concept set. (*) indicates a variant that explores all the same concepts.</p>\n')
        qout_list.append('<ul style="list-style-type: none;">\n')

        for fname, slide_id, header, qnumber, concept_id in Global.questions.values():
            q_id = make_file_id(fname, slide_id)
            qout_list.append('<li><a href="%s%s.html#%s">%s: %s</a>: ' % (cmd_args.href, fname, slide_id, make_q_label(fname, qnumber, fprefix), header))
            ctags = concept_id.split(';')
            n = len(ctags)
            for m in range(n):
                for subtags in itertools.combinations(ctags, n-m):
                    subtags = list(subtags)
                    subtags.sort()
                    sub_concept_id = ';'.join(subtags)
                    sub_num = str(n-m) if m else '*'
                    for sub_fname, sub_slide_id, sub_header, sub_qnumber, sub_concept_id in Global.concept_questions.get(sub_concept_id, []):
                        sub_q_id = make_file_id(sub_fname, sub_slide_id)
                        if sub_q_id != q_id:
                            qout_list.append('<a href="%s%s.html#%s">%s</a><sup>%s</sup>, ' % (cmd_args.href, sub_fname, sub_slide_id, make_q_label(sub_fname, sub_qnumber, fprefix), sub_num))
                
            qout_list.append('</li>\n')
        qout_list.append('</ul>\n')
        if not cmd_args.dry_run:
            qindexfile = open(cmd_args.qindex, 'w')
            qindexfile.write(''.join(qout_list))
            qindexfile.close()
            print("Created qindex in", cmd_args.qindex, file=sys.stderr)
