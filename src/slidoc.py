#!/usr/bin/env python

"""Slidoc is a Markdown based lecture management system.
Markdown filters with mistune, with support for MathJax, keyword indexing etc.
Use $$ ... $$ for block math
Use `$ ... $` for inline math (use ``$stuff`` for inline code that has dollar signs at the beginning/end)
Used from markdown.py

See slidoc.md for examples and test cases in Markdown.

Usage examples:
./slidoc.py --hide='[Aa]nswer' --slides=black,zenburn,200% ../Lectures/course-lecture??.md

"""
# Copyright (c) R. Saravanan, IPython Development Team (for MarkdownWithMath)
# Distributed under the terms of the Modified BSD License.

from __future__ import print_function

import argparse
import base64
import hashlib
import hmac
import os
import re
import shlex
import sys
import urllib
import urllib2

from collections import defaultdict, OrderedDict

import json
import mistune
import md2md

from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound

from xml.etree import ElementTree

MAX_QUERY = 500   # Maximum length of query string for concept chains
SPACER6 = '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
SPACER2 = '&nbsp;&nbsp;'
SPACER3 = '&nbsp;&nbsp;&nbsp;'

SYMS = {'prev': '&#9668;', 'next': '&#9658;', 'return': '&#8617;', 'up': '&#9650;', 'down': '&#9660;',
        'house': '&#8962;', 'circle': '&#9673;', 'square': '&#9635;', 'leftpair': '&#8647;', 'rightpair': '&#8649;'}

def make_file_id(filename, id_str, fprefix=''):
    return filename[len(fprefix):] + '#' + id_str
    
def make_chapter_id(chapnum):
    return 'slidoc%02d' % chapnum

def make_slide_id(chapnum, slidenum):
    return make_chapter_id(chapnum) + ('-%02d' % slidenum)

def make_q_label(filename, question_number, fprefix=''):
    return filename[len(fprefix):]+('.q%03d' % question_number)

def chapter_prefix(num, classes='', hide=False):
    attrs = ' style="display: none;"' if hide else ''
    return '\n<article id="%s" class="slidoc-container %s" %s> <!--chapter start-->\n' % (make_chapter_id(num), classes, attrs)

def concept_chain(slide_id, site_url):
    params = {'sid': slide_id, 'ixfilepfx': site_url+'/'}
    params.update(SYMS)
    return '\n<div id="%(sid)s-ichain" style="display: none;">CONCEPT CHAIN: <a id="%(sid)s-ichain-prev" class="slidoc-clickable-sym">%(prev)s</a>&nbsp;&nbsp;&nbsp;<b><a id="%(sid)s-ichain-concept" class="slidoc-clickable"></a></b>&nbsp;&nbsp;&nbsp;<a id="%(sid)s-ichain-next" class="slidoc-clickable-sym">%(next)s</a></div><p></p>\n\n' % params


def isfloat(value):
  try:
    float(value)
    return True
  except ValueError:
    return False

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

    # Save tags in proper case and then lowercase tags
    for tag in tags:
        if tag not in Global.all_tags:
            Global.all_tags[tag.lower()] = tag
        
    tags = [x.lower() for x in tags]

    if tags[0] != 'null':
        # List non-null primary tag
        if filename not in first_tags[tags[0]]:
            first_tags[tags[0]][filename] = []

        first_tags[tags[0]][filename].append( (slide_id, header) )

    for tag in tags[1:]:
        # Secondary tags
        if tag == 'null':
            continue
        if filename not in sec_tags[tag]:
            sec_tags[tag][filename] = []

        sec_tags[tag][filename].append( (slide_id, header) )


def make_index(first_tags, sec_tags, site_url, question=False, fprefix='', index_id='', index_file=''):
    # index_file would be null string for combined file
    id_prefix = 'slidoc-qindex-' if question else 'slidoc-index-'
    covered_first = defaultdict(dict)
    first_references = OrderedDict()
    tag_list = list(set(first_tags.keys()+sec_tags.keys()))
    tag_list.sort()
    out_list = []
    first_letters = []
    prev_tag_comps = []
    close_ul = '<br><li><a href="#%s" class="slidoc-clickable">TOP</a></li>\n</ul>\n' % index_id
    for tag in tag_list:
        tag_comps = tag.split(',')
        tag_str = Global.all_tags.get(tag, tag)
        first_letter = tag_comps[0][0]
        if not prev_tag_comps or prev_tag_comps[0][0] != first_letter:
            first_letters.append(first_letter)
            if out_list:
                out_list.append(close_ul)
            out_list.append('<b id="%s">%s</b>\n<ul style="list-style-type: none;">\n' % (id_prefix+first_letter.upper(), first_letter.upper()) )
        elif prev_tag_comps and prev_tag_comps[0] != tag_comps[0]:
            out_list.append('&nbsp;\n')
        else:
            tag_str = '___, ' + ','.join(tag_str.split(',')[1:])
        
        for fname, ref_list in first_tags[tag].items():
            # File includes this tag as primary tag
            if tag not in covered_first[fname]:
                covered_first[fname][tag] = ref_list[0]

        # Get sorted list of files with at least one reference (primary or secondary) to tag
        files = list(set(first_tags[tag].keys()+sec_tags[tag].keys()))
        files.sort()

        first_ref_list = []
        tag_id = '%s-concept-%s' % (index_id, md2md.make_id_from_text(tag))
        if files:
            out_list.append('<li id="%s"><b>%s</b>:\n' % (tag_id, tag_str))

        tag_index = []
        for fname in files:
            f_index  = [(fname, slide_id, header, 1) for slide_id, header in first_tags[tag].get(fname,[])]
            f_index += [(fname, slide_id, header, 2) for slide_id, header in sec_tags[tag].get(fname,[])]
            tag_index += f_index
            assert f_index, 'Expect at least one reference to tag in '+fname
            first_ref_list.append( f_index[0][:3] )

        tagid_list = [(fname[len(fprefix):] if index_file else '')+'#'+slide_id for fname, slide_id, header, reftype in tag_index]
        tagids_quoted = urllib.quote(';'.join(tagid_list), safe='')

        started = False
        j = 0
        for fname, slide_id, header, reftype in tag_index:
            j += 1
            if j > 1:
                out_list.append(', ')

            started = True
            query_str = '?tagindex=%d&tagconcept=%s&tagconceptref=%s&taglist=%s' % (j, urllib.quote(tag, safe=''),
                                                urllib.quote(index_file+'#'+tag_id, safe=''), tagids_quoted )
            if len(query_str) > MAX_QUERY:
                query_str = ''
            header = header or 'slide'
            header_html = '<b>%s</b>' % header if reftype == 1 else header
            if index_file:
                out_list.append('<a href="%s#%s" class="slidoc-clickable" target="_blank">%s</a>' % (site_url+fname+'.html'+query_str, slide_id, header_html))            
            else:
                out_list.append('''<a href="#%s" class="slidoc-clickable" onclick="Slidoc.chainStart('%s', '#%s');">%s</a>''' % (slide_id, query_str, slide_id, header_html))            

        if files:
            out_list.append('</li>\n')

        first_references[tag] = first_ref_list
        prev_tag_comps = tag_comps

    out_list.append(close_ul)
        
    out_list = ['<b>INDEX</b><blockquote>\n'] + ["&nbsp;&nbsp;".join(['<a href="#%s" class="slidoc-clickable">%s</a>' % (id_prefix+x.upper(), x.upper()) for x in first_letters])] + ['</blockquote>'] + out_list
    return first_references, covered_first, ''.join(out_list)


class Dummy(object):
    pass

Global = Dummy()

Global.first_tags = defaultdict(OrderedDict)
Global.sec_tags = defaultdict(OrderedDict)
Global.first_qtags = defaultdict(OrderedDict)
Global.sec_qtags = defaultdict(OrderedDict)

Global.all_tags = {}

Global.questions = OrderedDict()
Global.concept_questions = defaultdict(list)

Global.ref_tracker = dict()
Global.ref_counter = defaultdict(int)
Global.chapter_ref_counter = defaultdict(int)

class MathBlockGrammar(mistune.BlockGrammar):
    def_links = re.compile(  # RE-DEFINE TO INCLUDE SINGLE QUOTES
        r'^ *\[([^^\]]+)\]: *'  # [key]:
        r'<?([^\s>]+)>?'  # <link> or link
        r'''(?: +['"(]([^\n]+)['")])? *(?:\n+|$)'''
    )

    block_math = re.compile(r'^\$\$(.*?)\$\$', re.DOTALL)
    latex_environment = re.compile(r'^\\begin\{([a-z]*\*?)\}(.*?)\\end\{\1\}',
                                                re.DOTALL)
    slidoc_header =   re.compile(r'^ {0,3}<!--(meldr|slidoc)-(\w+)\s+(.*?)-->\s*?\n')
    slidoc_answer =   re.compile(r'^ {0,3}(Answer|Ans):(.*?)(\n|$)')
    slidoc_concepts = re.compile(r'^ {0,3}(Concepts):(.*?)(\n|$)')
    slidoc_notes =    re.compile(r'^ {0,3}(Notes):\s*?((?=\S)|\n)')
    minirule =        re.compile(r'^(--) *(?:\n+|$)')
    pause =           re.compile(r'^(\.\.\.) *(?:\n+|$)')

class MathBlockLexer(mistune.BlockLexer):
    def __init__(self, rules=None, **kwargs):
        if rules is None:
            rules = MathBlockGrammar()
        config = kwargs.get('config')
        slidoc_rules = ['block_math', 'latex_environment', 'slidoc_header', 'slidoc_answer', 'slidoc_concepts', 'slidoc_notes', 'minirule']
        if config and 'incremental' in config.features:
            slidoc_rules += ['pause']
        self.default_rules = slidoc_rules + mistune.BlockLexer.default_rules
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

    def parse_slidoc_header(self, m):
         self.tokens.append({
            'type': 'slidoc_header',
            'name': m.group(2).lower(),
            'text': m.group(3).strip()
        })

    def parse_slidoc_answer(self, m):
         self.tokens.append({
            'type': 'slidoc_answer',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_concepts(self, m):
         self.tokens.append({
            'type': 'slidoc_concepts',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_notes(self, m):
         self.tokens.append({
            'type': 'slidoc_notes',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_minirule(self, m):
        self.tokens.append({'type': 'minirule'})

    def parse_pause(self, m):
         self.tokens.append({
            'type': 'pause',
            'text': m.group(0)
        })

    
class MathInlineGrammar(mistune.InlineGrammar):
    slidoc_choice = re.compile(r"^ {0,3}([a-pA-P])\.\. +")
    math =          re.compile(r"^`\$(.+?)\$`")
    inline_js =     re.compile(r"^`=(\w+)\(\)(;([^`\n]+))?`")
    block_math =    re.compile(r"^\$\$(.+?)\$\$", re.DOTALL)
    text =          re.compile(r'^[\s\S]+?(?=[\\<!\[_*`~$]|https?://| {2,}\n|$)')
    internal_ref =  re.compile(
        r'^\[('
        r'(?:\[[^^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*'
        r')\]\s*\{\s*#([^^\}]*)\}'
    )

class MathInlineLexer(mistune.InlineLexer):
    def __init__(self, renderer, rules=None, **kwargs):
        if rules is None:
            rules = MathInlineGrammar()
        config = kwargs.get('config')
        slidoc_rules = ['slidoc_choice', 'block_math', 'math', 'internal_ref', 'inline_js']
        self.default_rules = slidoc_rules + mistune.InlineLexer.default_rules
        super(MathInlineLexer, self).__init__(renderer, rules, **kwargs)

    def output_slidoc_choice(self, m):
        return self.renderer.slidoc_choice(m.group(1).upper())

    def output_math(self, m):
        return self.renderer.inline_math(m.group(1))

    def output_inline_js(self, m):
        return self.renderer.inline_js(m.group(1), m.group(3))

    def output_block_math(self, m):
        return self.renderer.block_math(m.group(1))

    def output_link(self, m):
        if not m.group(0).startswith('!'):
            # Not image
            text = m.group(1)
            link = m.group(3)
            if link.startswith('#'):
                if link.startswith('##'):
                    # Link to index entry
                    tag = link[2:] or text
                    tag_hash = '#%s-concept-%s' % (self.renderer.index_id, md2md.make_id_from_text(tag))
                    tag_html = nav_link(text, self.renderer.options['config'].site_url, self.renderer.options['config'].index,
                                        hash=tag_hash, separate=self.renderer.options['config'].separate, target='_blank',
                                        keep_hash=True, printable=self.renderer.options['config'].printable)
                    return tag_html
                header_ref = md2md.ref_key(link[1:].lstrip(':'))
                if not header_ref:
                    header_ref = md2md.ref_key(text)
                if not header_ref:
                    print('LINK-ERROR: Null link', file=sys.stderr)
                    return None

                # Slidoc-specific hash reference handling
                ref_id = 'slidoc-ref-'+md2md.make_id_from_text(header_ref)
                classes = ["slidoc-clickable"]
                if ref_id not in Global.ref_tracker:
                    # Forward link
                    self.renderer.forward_link(ref_id)
                    classes.append('slidoc-forward-link ' + ref_id+'-forward-link')
                if link.startswith('#:'):
                    # Numbered reference
                    if ref_id in Global.ref_tracker:
                        num_label, _, ref_class = Global.ref_tracker[ref_id]
                        classes.append(ref_class)
                    else:
                        num_label = '_MISSING_SLIDOC_REF_NUM(#%s)' % ref_id
                    text += num_label
                return click_span(text, "Slidoc.go('#%s');" % ref_id, classes=classes,
                                  href='#'+ref_id if self.renderer.options['config'].printable else '')

        return super(MathInlineLexer, self).output_link(m)

    def output_internal_ref(self, m):
        text = m.group(1)
        text_key = md2md.ref_key(text)
        key = md2md.ref_key(m.group(2))
        header_ref = key.lstrip(':')
        if not header_ref:
            header_ref = text_key
        if not header_ref:
            print('REF-ERROR: Null reference', file=sys.stderr)
            return None

        # Slidoc-specific hash reference handling
        ref_id = 'slidoc-ref-'+md2md.make_id_from_text(header_ref)
        ref_class = ''
        if ref_id in Global.ref_tracker:
            print('REF-ERROR: Duplicate reference #%s (#%s)' % (ref_id, key), file=sys.stderr)
            ref_id += '-duplicate-'+md2md.generate_random_label()
        else:
            num_label = '??'
            if key.startswith(':'):
                # Numbered reference
                ref_class = 'slidoc-ref-'+md2md.make_id_from_text(text_key)
                if key.startswith('::') and 'chapters' not in self.options['config'].strip:
                    Global.chapter_ref_counter[text_key] += 1
                    num_label = "%d.%d" % (self.renderer.options['filenumber'], Global.chapter_ref_counter[text_key])
                else:
                    Global.ref_counter[text_key] += 1
                    num_label = "%d" % Global.ref_counter[text_key]
                text += num_label
            self.renderer.add_ref_link(ref_id, num_label, key, ref_class)
        return '''<span id="%s" class="slidoc-referable slidoc-referable-in-%s %s">%s</span>'''  % (ref_id, self.renderer.get_slide_id(), ref_class, text)

    def output_reflink(self, m):
        return super(MathInlineLexer, self).output_reflink(m)

    
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

    def output_slidoc_header(self):
        return self.renderer.slidoc_header(self.token['name'], self.token['text'])

    def output_slidoc_answer(self):
        return self.renderer.slidoc_answer(self.token['name'], self.token['text'])

    def output_slidoc_concepts(self):
        return self.renderer.slidoc_concepts(self.token['name'], self.token['text'])

    def output_slidoc_notes(self):
        return self.renderer.slidoc_notes(self.token['name'], self.token['text'])

    def output_minirule(self):
        return self.renderer.minirule()

    def output_pause(self):
        return self.renderer.pause(self.token['text'])

class MarkdownWithSlidoc(MarkdownWithMath):
    def __init__(self, renderer, **kwargs):
        super(MarkdownWithSlidoc, self).__init__(renderer, **kwargs)
        self.incremental = 'incremental' in self.renderer.options['config'].features

    def output_block_quote(self):
        if self.incremental:
            self.renderer.list_incremental(True)
        retval = super(MarkdownWithSlidoc, self).output_block_quote()
        if self.incremental:
            self.renderer.list_incremental(False)
        return retval

    def render(self, text, index_id='', qindex_id=''):
        self.renderer.index_id = index_id
        self.renderer.qindex_id = qindex_id
        html = super(MarkdownWithSlidoc, self).render(text)

        first_slide_pre = '<span id="%s-attrs" class="slidoc-attrs" style="display: none;">%s</span>\n' % (self.renderer.first_id, base64.b64encode(json.dumps(self.renderer.questions)))

        if self.renderer.qconcepts[0] or self.renderer.qconcepts[1]:
            # Include sorted list of concepts related to questions
            q_list = [sort_caseless(list(self.renderer.qconcepts[j])) for j in (0, 1)]
            first_slide_pre += '<span id="%s-qconcepts" class="slidoc-qconcepts" style="display: none;">%s</span>\n' % (self.renderer.first_id, base64.b64encode(json.dumps(q_list)))

        return self.renderer.slide_prefix(self.renderer.first_id)+first_slide_pre+concept_chain(self.renderer.first_id, self.renderer.options['config'].site_url)+html+self.renderer.end_slide('<!--last slide-->\n')

    
class MathRenderer(mistune.Renderer):
    def forward_link(self, ref_id):
        pass

    def add_ref_link(self, ref_id, num_label, key, ref_class):
        pass
    
    def block_math(self, text):
        return '$$%s$$' % text

    def latex_environment(self, name, text):
        return r'\begin{%s}%s\end{%s}' % (name, text, name)

    def inline_math(self, text):
        return '`$%s$`' % text

    def block_code(self, code, lang=None):
        """Rendering block level code. ``pre > code``.
        """
        lexer = None
        if code.endswith('\n\n'):
            code = code[:-1]
        if lang:
            try:
                lexer = get_lexer_by_name(lang, stripall=True)
            except ClassNotFound:
                code = lang + '\n' + code

        if not lexer:
            return '\n<pre><code>%s</code></pre>\n' % mistune.escape(code)

        formatter = HtmlFormatter()
        return highlight(code, lexer, formatter)

    
class SlidocRenderer(MathRenderer):
    header_attr_re = re.compile(r'^.*?(\s*\{\s*(#\S+)?([^#\}]*)?\s*\})\s*$')

    def __init__(self, **kwargs):
        super(SlidocRenderer, self).__init__(**kwargs)
        self.file_header = ''
        self.header_list = []
        self.concept_warnings = []
        self.hide_end = None
        self.notes_end = None
        self.section_number = 0
        self.untitled_number = 0
        self.qtypes = []
        self.questions = []
        self.qforward = defaultdict(list)
        self.qconcepts = [set(),set()]
        self.slide_number = 0
        self._new_slide()
        self.first_id = self.get_slide_id()
        self.index_id = ''                     # Set by render()
        self.qindex_id = ''                    # Set by render
        self.block_input_counter = 0
        self.block_test_counter = 0
        self.block_output_counter = 0
        self.load_python = False

    def _new_slide(self):
        self.slide_number += 1
        self.qtypes.append('')
        self.choice_end = None
        self.cur_choice = ''
        self.cur_qtype = ''
        self.cur_header = ''
        self.cur_answer = False
        self.slide_concepts = ''
        self.first_para = True
        self.incremental_level = 0
        self.incremental_list = False
        self.incremental_pause = False
        self.slide_block_test = []
        self.slide_block_output = []
        self.slide_forward_links = []

    def list_incremental(self, activate):
        self.incremental_list = activate
    
    def forward_link(self, ref_id):
        self.slide_forward_links.append(ref_id)

    def add_ref_link(self, ref_id, num_label, key, ref_class):
        Global.ref_tracker[ref_id] = (num_label, key, ref_class)
        if ref_id in self.qforward:
            cur_qno = len(self.questions)
            for qno in self.qforward.pop(ref_id):
                # (slide_number, number of questions skipped, class for forward link)
                skipped = cur_qno-qno-1 if self.qtypes[-1] else cur_qno-qno
                self.questions[qno-1]['skip'] = (self.slide_number, skipped, ref_id+'-forward-link')

    def inline_js(self, js_func, text):
        if 'inline_js' in self.options['config'].strip:
            return '<code>%s</code>' % (mistune.escape('='+js_func+'()' if text is None else text))
        slide_id = self.get_slide_id()
        classes = 'slidoc-inline-js'
        if slide_id:
            classes += ' slidoc-inline-js-in-'+slide_id
        return '<code class="%s" data-slidoc-js-function="%s">%s</code>' % (classes, js_func.replace('<', '&lt;').replace('>', '&gt;'), mistune.escape('='+js_func+'()' if text is None else text))

    def get_chapter_id(self):
        return make_chapter_id(self.options['filenumber'])

    def get_slide_id(self, slide_number=0):
        return make_slide_id(self.options['filenumber'], slide_number or self.slide_number)

    def start_block(self, block_type, id_str, display='none'):
        prefix =        '\n<!--slidoc-%s-block-begin[%s]-->\n' % (block_type, id_str)
        end_str = '</div>\n<!--slidoc-%s-block-end[%s]-->\n' % (block_type, id_str)
        suffix =  '<div class="slidoc-%s %s" style="display: %s;">\n' % (block_type, id_str, display)
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

    def pause(self, text):
        """Pause in display"""
        if 'incremental' in self.options['config'].features:
            self.incremental_pause = True
            self.incremental_level += 1
            return ''
        else:
            return text

    def slide_prefix(self, slide_id, classes=''):
        chapter_id, sep, _ = slide_id.partition('-')
        return '\n<section id="%s" class="slidoc-slide %s-slide %s"> <!--slide start-->\n' % (slide_id, chapter_id, classes)

    def hrule(self, implicit=False):
        """Rendering method for ``<hr>`` tag."""
        if self.choice_end:
            prefix = self.choice_end

        if implicit or 'rule' in self.options['config'].strip or (self.hide_end and 'hidden' in self.options['config'].strip):
            rule_html = ''
        elif self.options.get('use_xhtml'):
            rule_html = '<hr class="slidoc-noslide slidoc-noprint"/>\n'
        else:
            rule_html = '<hr class="slidoc-noslide slidoc-noprint">\n'

        end_html = self.end_slide(rule_html)
        self._new_slide()
        new_slide_id = self.get_slide_id()
        return end_html + self.slide_prefix(new_slide_id) + concept_chain(new_slide_id, self.options['config'].site_url)

    def end_slide(self, suffix_html=''):
        if self.qtypes[-1] and self.options['config'].pace and self.slide_forward_links:
            # Handle forward link in current question
            self.qforward[self.slide_forward_links[0]].append(len(self.questions))
            if len(self.slide_forward_links) > 1:
                print("    ****ANSWER-ERROR: %s: Multiple forward links in slide %s. Only first link enabled." % (self.options["filename"], self.slide_number), file=sys.stderr)

        return self.end_notes()+self.end_hide()+suffix_html+'</section><!--slide end-->\n' 

    def list_item(self, text):
        """Rendering list item snippet. Like ``<li>``."""
        if not self.incremental_list:
            return super(SlidocRenderer, self).list_item(text)
        self.incremental_level += 1
        return '<li class="slidoc-incremental%d">%s</li>\n' % (self.incremental_level, text)

    def paragraph(self, text):
        """Rendering paragraph tags. Like ``<p>``."""
        if not self.cur_header and self.first_para:
            self.untitled_number += 1
            if 'untitled_number' in self.options['config'].features:
                # Number untitled slides (e.g., as in question numbering) 
                text = ('%d. ' % self.untitled_number) + text
        self.first_para = False
        if not self.incremental_pause:
            return super(SlidocRenderer, self).paragraph(text)
        return '<p class="%s-incremental slidoc-incremental%d">%s</p>\n' % (self.get_slide_id(), self.incremental_level, text.strip(' '))

    def block_code(self, code, lang=None):
        """Rendering block level code. ``pre > code``.
        """
        if code.endswith('\n\n'):
            code = code[:-1]

        slide_id = self.get_slide_id()
        classes = 'slidoc-block-code slidoc-block-code-in-%s' % slide_id

        id_str = ''
    

        if lang in ('javascript_input','python_input'):
            lang = lang[:-6]
            classes += ' slidoc-block-input'
            self.block_input_counter += 1
            id_str = 'id="slidoc-block-input-%d"' % self.block_input_counter

        elif lang in ('javascript_test','python_test'):
            lang = lang[:-5]
            classes += ' slidoc-block-test'
            self.block_test_counter += 1
            self.slide_block_test.append(self.block_test_counter)
            id_str = 'id="slidoc-block-test-%d"' % self.block_test_counter
            if len(self.slide_block_test) > 1:
                classes += ' slidoc-block-multi'

        elif lang == 'nb_output':
            lang = lang[3:]
            classes += ' slidoc-block-output'
            self.block_output_counter += 1
            self.slide_block_output.append(self.block_output_counter)
            id_str = 'id="slidoc-block-output-%d"' % self.block_output_counter
            if len(self.slide_block_output) > 1:
                classes += ' slidoc-block-multi'

        lexer = None
        if lang and lang not in ('output',):
            classes += ' slidoc-block-lang-'+lang
            try:
                lexer = get_lexer_by_name(lang, stripall=True)
            except ClassNotFound:
                code = lang + '\n' + code

        if lexer:
            html = highlight(code, lexer, HtmlFormatter())
        else:
            html = '<pre><code>%s</code></pre>\n' % mistune.escape(code)
        
        return ('\n<div %s class="%s">\n' % (id_str, classes))+html+'</div>\n'

    def header(self, text, level, raw=None):
        """Handle markdown headings
        """
        html = super(SlidocRenderer, self).header(text, level, raw=raw)
        try:
            hdr = ElementTree.fromstring(html)
        except Exception:
            # failed to parse, just return it unmodified
            return html

        prev_slide_end = ''
        if self.cur_header and level <= 2:
            # Implicit horizontal rule before Level 1/2 header
            prev_slide_end = self.hrule(implicit=True)
        
        hdr_class = (hdr.get('class')+' ' if hdr.get('class') else '') + ('slidoc-referable-in-%s' % self.get_slide_id())
        if 'headers' in self.options['config'].strip:
            hdr_class += ' slidoc-hidden'

        text = html2text(hdr).strip()
        header_ref = ''
        match = self.header_attr_re.match(text)
        if match:
            # Header attributes found
            if match.group(2) and len(match.group(2)) > 1:
                short_id = match.group(2)[1:]
                if not re.match(r'^[-.\w]+$', short_id):
                    
                    print('REF-WARNING: Use only alphanumeric chars, hyphens and dots in references: %s' % text, file=sys.stderr)
                header_ref = md2md.ref_key(short_id)
            if match.group(3) and match.group(3).strip():
                attrs = match.group(3).strip().split()
                for attr in attrs:
                    if attr.startswith('.'):
                        hdr_class += ' ' + attr[1:]
            try:
                hdr = ElementTree.fromstring(html.replace(match.group(1),''))
                text = html2text(hdr).strip()
            except Exception:
                pass

        if not header_ref:
            header_ref = md2md.ref_key(text)
        ref_id = 'slidoc-ref-'+md2md.make_id_from_text(header_ref)
        if ref_id in Global.ref_tracker:
            print('REF-ERROR: Duplicate reference #%s (#%s)' % (ref_id, header_ref), file=sys.stderr)
        else:
            self.add_ref_link(ref_id, '??', header_ref, '')

        hdr.set('id', ref_id)

        hide_block = self.options['config'].hide and re.search(self.options['config'].hide, text)
        if level > 3 or (level == 3 and not (hide_block and self.hide_end is None)):
            # Ignore higher level headers (except for level 3 hide block, if no earlier header in slide)
            return ElementTree.tostring(hdr)

        pre_header = ''
        post_header = ''
        hdr_prefix = ''
        clickable_secnum = False
        if level <= 2 and not self.file_header:
            # First (file) header
            if 'chapters' not in self.options['config'].strip:
                hdr_prefix = '%d ' % self.options['filenumber']

            self.cur_header = hdr_prefix + text
            self.file_header = self.cur_header

            pre_header = '__PRE_HEADER__'
            post_header = '__POST_HEADER__'

        else:
            # Level 1/2/3 header
            if level <= 2:
                # New section
                self.section_number += 1
                if 'sections' not in self.options['config'].strip:
                    if 'chapters' not in self.options['config'].strip:
                        hdr_prefix =  '%d.%d ' % (self.options['filenumber'], self.section_number)
                    else:
                        hdr_prefix =  '%d ' % self.section_number
                    clickable_secnum = True
                self.cur_header = hdr_prefix + text
                self.header_list.append( (self.get_slide_id(), self.cur_header) )

            # Record header occurrence (preventing hiding of any more level 3 headers in the same slide)
            self.hide_end = ''

            if hide_block:
                # New block to hide answer/solution
                id_str = self.get_slide_id() + '-hide'
                pre_header, post_header, end_str = self.start_block('hidden', id_str)
                self.hide_end = end_str
                hdr_class += ' slidoc-clickable'
                hdr.set('onclick', "Slidoc.classDisplay('"+id_str+"');" )

        if clickable_secnum:
            span_prefix = ElementTree.Element('span', {} )
            span_prefix.text = hdr_prefix.strip()
            span_elem = ElementTree.Element('span', {})
            span_elem.text = ' '+ text
            hdr.text = ''
            for child in list(hdr):
                hdr.remove(child)
            hdr.append(span_prefix)
            hdr.append(span_elem)
        elif hdr_prefix:
            hdr.text = hdr_prefix + (hdr.text or '')

        ##a = ElementTree.Element("a", {"class" : "anchor-link", "href" : "#" + self.get_slide_id()})
        ##a.text = u' '
        ##hdr.append(a)

        # Known issue of Python3.x, ElementTree.tostring() returns a byte string
        # instead of a text string.  See issue http://bugs.python.org/issue10942
        # Workaround is to make sure the bytes are casted to a string.
        hdr.set('class', hdr_class)
        return prev_slide_end + pre_header + ElementTree.tostring(hdr) + '\n' + post_header

    def slidoc_header(self, name, text):
        if name == "type" and text:
            params = text.split()
            type_code = params[0]
            if type_code in ("choice", "multichoice", "number", "text", "point", "line"):
                self.cur_qtype = type_code
        return ''

    def slidoc_choice(self, name):
        if not self.cur_qtype:
            self.cur_qtype = 'choice'
        elif self.cur_qtype != 'choice':
            print("    ****CHOICE-ERROR: %s: Line '%s.. ' implies multiple choice question in '%s'" % (self.options["filename"], name, self.cur_header), file=sys.stderr)
            return name+'.. '

        prefix = ''
        if not self.cur_choice:
            prefix = '<blockquote>\n'
            self.choice_end = '</blockquote>\n'

        self.cur_choice = name

        params = {'id': self.get_slide_id(), 'opt': name, 'qno': len(self.questions)+1}
        if self.options['config'].hide or self.options['config'].pace:
            return prefix+'''<span id="%(id)s-choice-%(opt)s" class="slidoc-clickable %(id)s-choice" onclick="Slidoc.choiceClick(this, %(qno)d, '%(id)s', '%(opt)s');"+'">%(opt)s</span>. ''' % params
        else:
            return prefix+'''<span id="%(id)s-choice-%(opt)s" class="%(id)s-choice">%(opt)s</span>. ''' % params

    
    def slidoc_answer(self, name, text):
        if self.cur_answer:
            # Ignore multiple answers
            return ''
        self.cur_answer = True

        choice_prefix = ''
        if self.choice_end:
            choice_prefix = self.choice_end
            self.choice_end = ''

        correct_js = ''
        js_match = MathInlineGrammar.inline_js.match(text)
        if js_match:
            # Inline JS answer; strip function call
            if 'inline_js' not in self.options['config'].strip:
                correct_js = js_match.group(1)
            text = text[len(js_match.group(0)):].strip()
            if js_match.group(3) is not None:
                text = js_match.group(3) + text
            elif not text and correct_js:
                text = '='+correct_js+'()'

        qtype = ''
        num_match = re.match(r'^([-+/\d\.eE\s]+)$', text)
        if num_match and text.lower() != 'e':
            # Numeric default answer
            text = num_match.group(1).strip()
            ans, error = '', ''
            if '+/-' in text:
                ans, _, error = text.partition('+/-')
            elif ' ' in text.strip():
                comps = text.strip().split()
                if len(comps) == 2:
                    ans, error = comps
            else:
                ans = text
            ans, error = ans.strip(), error.strip()
            if isfloat(ans) and (not error or isfloat(error)):
                qtype = 'number'
                text = ans + (' +/- '+error if error else '')
            else:
                print("    ****ANSWER-ERROR: %s: 'Answer: %s' is not a valid numeric answer; expect 'ans +/- err'" % (self.options["filename"], text), file=sys.stderr)

        elif text.lower() in ('choice', 'multichoice', 'number', 'text', 'text/code', 'text/code=python', 'text/code=javascript', 'text/code=test', 'text/multiline', 'point', 'line'):
            # Unspecified answer
            qtype = text.lower()
            text = ''

        if not self.cur_qtype:
            if not qtype:
                # Determine question type from answer
                if len(text) == 1 and text.isalpha():
                    qtype = 'choice'
                else:
                    qtype = 'text'    # Default answer type

            self.cur_qtype = qtype

        elif qtype and qtype != self.cur_qtype:
            print("    ****ANSWER-ERROR: %s: 'Answer: %s' line ignored; expected 'Answer: %s'" % (self.options["filename"], qtype, self.cur_qtype), file=sys.stderr)

        if self.cur_qtype == 'text/code=python':
            self.load_python = True

        # Handle correct answer
        if self.cur_qtype == 'choice' and len(text) == 1:
            correct_text = text.upper()
            correct_html = correct_text
        else:
            correct_text = text
            correct_html = ''
            if text and not correct_js:
                try:
                    # Render any Markdown in correct answer
                    correct_html = MarkdownWithMath(renderer=MathRenderer(escape=False)).render(text) if text else ''
                    corr_elem = ElementTree.fromstring(correct_html)
                    correct_text = html2text(corr_elem).strip()
                    correct_html = correct_html[3:-5]
                except Exception, excp:
                    print("    ****ANSWER-ERROR: %s: 'Answer: %s' does not parse properly as html: %s'" % (self.options["filename"], correct_html, excp), file=sys.stderr)

        self.qtypes[-1] = self.cur_qtype
        self.questions.append({})
        self.questions[-1].update(qtype=self.cur_qtype, slide=self.slide_number, correct=correct_text)
        if correct_html and correct_html != correct_text:
            self.questions[-1].update(html=correct_html)
        if correct_js:
            self.questions[-1].update(js=correct_js)
        if self.block_input_counter:
            self.questions[-1].update(input=self.block_input_counter)
        if self.slide_block_test:
            self.questions[-1].update(test=self.slide_block_test)
        if self.slide_block_output:
            self.questions[-1].update(output=self.slide_block_output)

        if not self.options['config'].pace and ('answers' in self.options['config'].strip or (not text and not correct_js)):
            # Strip any correct answers
            return choice_prefix+name.capitalize()+':'+'<p></p>\n'

        hide_answer = self.options['config'].hide or self.options['config'].pace
        if len(self.slide_block_test) != len(self.slide_block_output):
            hide_answer = False
            print("    ****ANSWER-ERROR: %s: Test block count %d != output block_count %d" % (self.options["filename"], len(self.slide_block_test), len(self.slide_block_output)), file=sys.stderr)

        if not hide_answer:
            # No hiding of correct answers
            return choice_prefix+name.capitalize()+': '+correct_html+'<p></p>\n'

        id_str = self.get_slide_id()
        ans_params = {'sid': id_str,
                      'ans_type': self.cur_qtype,
                      'ans_text': name.capitalize(),
                      'ans_extras': '',
                      'click_extras': '''onclick="Slidoc.answerClick(this, %d, '%s', '%s');"''' % (len(self.questions), id_str, self.cur_qtype),
                      'inp_type': 'number' if self.cur_qtype == 'number' else 'text',
                      'inp_extras': ''
                      }
        if self.cur_choice:
            ans_params['ans_extras'] = 'style="display: none;"'
            ans_params['click_extras'] = 'style="display: none;"'
            ans_params['inp_extras'] = 'style="display: none;"'

        inp_elem1, inp_elem2 = '', ''
        if self.cur_qtype.startswith('text/'):
            inp_elem2 = '''<br><textarea id="%(sid)s-ansinput" name="textarea" class="slidoc-answer-textarea" cols="60" rows="5" %(inp_extras)s ></textarea>
'''
            if self.cur_qtype.startswith('text/code='):
                inp_elem2 += '<br><button id="%(sid)s-anscheck" class="slidoc-clickable" %(click_extras)s>Check</button>\n'
        else:
            inp_elem1 = '''<input id="%(sid)s-ansinput" type="%(inp_type)s" class="slidoc-answer-input" %(inp_extras)s onkeydown="Slidoc.inputKeyDown(event);"></input>'''

        ans_html = ('''<div id="%(sid)s-answer" class="slidoc-answer-container" %(ans_extras)s>
<span id="%(sid)s-ansprefix" style="display: none;">%(ans_text)s:</span>
<span id="%(sid)s-anstype" class="slidoc-answer-type" style="display: none;">%(ans_type)s</span>
'''+inp_elem1+'''
<button id="%(sid)s-ansclick" class="slidoc-clickable" %(click_extras)s>Answer</button>
<span id="%(sid)s-correct-mark" class="slidoc-correct-answer"></span>
<span id="%(sid)s-wrong-mark" class="slidoc-wrong-answer"></span>
<span id="%(sid)s-any-mark" class="slidoc-any-answer"></span>
<span id="%(sid)s-correct" class="slidoc-correct-answer" style="display: none;"></span>
'''+inp_elem2+'''
<pre><code id="%(sid)s-code-output" class="slidoc-code-output"></code></pre>
</div>
''') % ans_params

        return choice_prefix+ans_html+'\n'


    def slidoc_concepts(self, name, text):
        if not text:
            return ''

        ###if self.notes_end is not None:
        ###    print("    ****CONCEPT-ERROR: %s: 'Concepts: %s' line after Notes: ignored in '%s'" % (self.options["filename"], text, self.cur_header), file=sys.stderr)
        ###    return ''

        if self.slide_concepts:
            print("    ****CONCEPT-ERROR: %s: Extra 'Concepts: %s' line ignored in '%s'" % (self.options["filename"], text, self.cur_header), file=sys.stderr)
            return ''

        self.slide_concepts = text

        tags = [x.strip() for x in text.split(";")]
        nn_tags = tags[1:] if tags and tags[0] == 'null' else tags[:]   # Non-null tags

        if nn_tags and (self.options['config'].index or self.options['config'].qindex or self.options['config'].pace):
            # Track/check tags
            if self.qtypes[-1] in ("choice", "multichoice", "number", "text", "point", "line"):
                # Question
                nn_tags.sort()
                q_id = make_file_id(self.options["filename"], self.get_slide_id())
                q_concept_id = ';'.join(nn_tags)
                q_pars = (self.options["filename"], self.get_slide_id(), self.cur_header, len(self.questions), q_concept_id)
                Global.questions[q_id] = q_pars
                Global.concept_questions[q_concept_id].append( q_pars )
                for tag in nn_tags:
                    if tag not in Global.first_tags and tag not in Global.sec_tags:
                        self.concept_warnings.append("CONCEPT-WARNING: %s: '%s' not covered before '%s'" % (self.options["filename"], tag, self.cur_header))
                        print("        "+self.concept_warnings[-1], file=sys.stderr)

                add_to_index(Global.first_qtags, Global.sec_qtags, tags, self.options["filename"], self.get_slide_id(), self.cur_header)
                if tags[0] != 'null':
                    self.qconcepts[0].add(tags[0])
                if tags[1:]:
                    self.qconcepts[1].update(set(tags[1:]))
            else:
                # Not question
                add_to_index(Global.first_tags, Global.sec_tags, tags, self.options["filename"], self.get_slide_id(), self.cur_header)

        if 'concepts' in self.options['config'].strip:
            # Strip concepts
            return ''

        id_str = self.get_slide_id()+'-concepts'
        display_style = 'inline' if self.options['config'].printable else 'none'
        tag_html = '''<div class="slidoc-concepts-container slidoc-noslide"><span class="slidoc-clickable" onclick="Slidoc.toggleInlineId('%s')">%s:</span> <span id="%s" style="display: %s;">''' % (id_str, name.capitalize(), id_str, display_style)

        if self.options['config'].index:
            first = True
            for tag in tags:
                if not first:
                    tag_html += '; '
                first = False
                tag_hash = '#%s-concept-%s' % (self.index_id, md2md.make_id_from_text(tag))
                tag_html += nav_link(tag, self.options['config'].site_url, self.options['config'].index,
                                     hash=tag_hash, separate=self.options['config'].separate, target='_blank',
                                     keep_hash=True, printable=self.options['config'].printable)
        else:
            tag_html += text

        tag_html += '</span></div>'

        return tag_html+'\n'

    
    def slidoc_notes(self, name, text):
        if self.notes_end is not None:
            # Additional notes prefix in slide; strip it
            return ''
        id_str = self.get_slide_id() + '-notes'
        disp_block = 'none' if self.cur_answer else 'block'
        prefix, suffix, end_str = self.start_block('notes', id_str, display=disp_block)
        self.notes_end = end_str
        classes = 'slidoc-clickable'
        if self.qtypes[-1]:
            classes += ' slidoc-question-notes'
        return prefix + ('''<br><span id="%s" class="%s" onclick="Slidoc.classDisplay('%s')" style="display: inline;">Notes:</span>\n''' % (id_str, classes, id_str)) + suffix


    def table_of_contents(self, filepath='', filenumber=1):
        if len(self.header_list) < 1:
            return ''

        toc = [('\n<ol class="slidoc-section-toc">' if 'sections' in self.options['config'].strip
                 else '\n<ul class="slidoc-section-toc" style="list-style-type: none;">') ]

        for id_str, header in self.header_list:  # Skip first header
            if filepath or self.options['config'].printable:
                elem = ElementTree.Element("a", {"class" : "header-link", "href" : filepath+"#"+id_str})
            else:
                elem = ElementTree.Element("span", {"class" : "slidoc-clickable", "onclick" : "Slidoc.go('#%s');" % id_str})
            elem.text = header
            toc.append('<li>'+ElementTree.tostring(elem)+'</li>')

        toc.append('</ol>\n' if 'sections' in self.options['config'].strip else '</ul>\n')
        return '\n'.join(toc)

def click_span(text, onclick, id='', classes=['slidoc-clickable'], href=''):
    id_str = ' id="%s"' % id if id else ''
    if href:
        return '''<a %s href="%s" class="%s" onclick="%s">%s</a>''' % (id_str, href, ' '.join(classes), onclick, text)
    else:
        return '''<span %s class="%s" onclick="%s">%s</span>''' % (id_str, ' '.join(classes), onclick, text)

def nav_link(text, site_url, href, hash='', separate=False, keep_hash=False, printable=False, target='', classes=[]):
    extras = ' target="%s"' % target if target else ''
    class_list = classes[:]
    if text.startswith('&'):
        class_list.append("slidoc-clickable-sym")
        if not href:
            extras += ' style="visibility: hidden;"'
    else:
        class_list.append("slidoc-clickable")
        extras += ' class="slidoc-clickable slidoc-noall"'
    class_str = ' '.join(class_list)
    if printable:
        return '''<a class="%s" href="%s%s" onclick="Slidoc.go('%s');" %s>%s</a>'''  % (class_str, site_url, hash or href, hash or href, extras, text)
    elif not separate:
        return '''<span class="%s" onclick="Slidoc.go('%s');" %s>%s</span>'''  % (class_str, hash or href, extras, text)
    elif href or text.startswith('&'):
        return '''<a class="%s" href="%s%s" %s>%s</a>'''  % (class_str, site_url, href+hash if hash and keep_hash else href, extras, text)
    else:
        return '<span class="%s">%s</span>' % (class_str, text)

Missing_ref_num_re = re.compile(r'_MISSING_SLIDOC_REF_NUM\(#([-.\w]+)\)')
def Missing_ref_num(match):
    ref_id = match.group(1)
    if ref_id in Global.ref_tracker:
        return Global.ref_tracker[ref_id][0]
    else:
        return '(%s)??' % ref_id

def md2html(source, filename, config, filenumber=1, prev_file='', next_file='', index_id='', qindex_id=''):
    """Convert a markdown string to HTML using mistune, returning (first_header, file_toc, renderer, html)"""
    Global.chapter_ref_counter = defaultdict(int)

    renderer = SlidocRenderer(escape=False, filename=filename, config=config, filenumber=filenumber)

    content_html = MarkdownWithSlidoc(renderer=renderer).render(source, index_id=index_id, qindex_id=qindex_id)

    content_html = Missing_ref_num_re.sub(Missing_ref_num, content_html)

    pre_header_html = ''
    tail_html = ''
    post_header_html = ''
    if 'navigate' not in config.strip:
        nav_html = ''
        if config.toc:
            nav_html += nav_link(SYMS['return'], config.site_url, config.toc, hash='#'+make_chapter_id(0), separate=config.separate, classes=['slidoc-nosidebar', 'slidoc-noprint'], printable=config.printable) + SPACER6
            nav_html += nav_link(SYMS['prev'], config.site_url, prev_file, separate=config.separate, classes=['slidoc-noall'], printable=config.printable) + SPACER6
            nav_html += nav_link(SYMS['next'], config.site_url, next_file, separate=config.separate, classes=['slidoc-noall'], printable=config.printable) + SPACER6

        pre_header_html += '<div class="slidoc-noslide slidoc-noprint slidoc-noall">'+nav_html+click_span(SYMS['square'], "Slidoc.slideViewStart();", classes=["slidoc-clickable-sym", 'slidoc-nosidebar'])+'</div>\n'

        tail_html = '<div class="slidoc-noslide slidoc-nosidebar slidoc-noprint">' + nav_html + '<a href="#%s" class="slidoc-clickable-sym">%s</a>%s' % (renderer.first_id, SYMS['up'], SPACER6) + '</div>\n'

    if 'contents' not in config.strip:
        chapter_id = make_chapter_id(filenumber)
        header_toc = renderer.table_of_contents(filenumber=filenumber)
        if header_toc:
            post_header_html += ('<div class="slidoc-chapter-toc %s-chapter-toc slidoc-nopaced slidoc-nosidebar">' % chapter_id)+header_toc+'</div>\n'
            post_header_html += click_span('&#8722;Contents', "Slidoc.hide(this, '%s');" % (chapter_id+'-chapter-toc'),
                                            id=chapter_id+'-chapter-toc-hide', classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-chapter-toc-hide', 'slidoc-nopaced', 'slidoc-noprint', 'slidoc-nosidebar'])

    if 'contents' not in config.strip and 'slidoc-notes' in content_html:
        post_header_html += '&nbsp;&nbsp;' + click_span('&#8722;All Notes',
                                             "Slidoc.hide(this,'slidoc-notes');",id=renderer.first_id+'-hidenotes',
                                              classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-nopaced', 'slidoc-noprint'])

    if 'slidoc-answer-type' in content_html and 'slidoc-concepts-container' in content_html:
        post_header_html += '&nbsp;&nbsp;' + click_span('Missed question concepts', "Slidoc.showConcepts();", classes=['slidoc-clickable', 'slidoc-noprint'])

    content_html = content_html.replace('__PRE_HEADER__', pre_header_html)
    content_html = content_html.replace('__POST_HEADER__', post_header_html)
    content_html += tail_html

    if 'hidden' in config.strip:
        # Strip out hidden answer slides
        content_html = re.sub(r"<!--slidoc-hidden-block-begin\[([-\w]+)\](.*?)<!--slidoc-hidden-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    if 'notes' in config.strip:
        # Strip out notes
        content_html = re.sub(r"<!--slidoc-notes-block-begin\[([-\w]+)\](.*?)<!--slidoc-notes-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    file_toc = renderer.table_of_contents('' if not config.separate else config.site_url+filename+'.html', filenumber=filenumber)

    return (renderer.file_header or filename, file_toc, renderer, content_html)


def process_input(input_files, config_dict):
    tem_dict = config_dict.copy()
    tem_dict.update(separate=False, toc='toc.html', index='ind.html', qindex='qind.html')

    config = argparse.Namespace(**tem_dict)

    out_name = os.path.splitext(os.path.basename(config.outfile or input_files[0].name))[0]
    combined_file = out_name+'.html'

    js_params = {'filename': '', 'sessionVersion': '1.0', 'sessionRevision': '', 'sessionPrereqs': '',
                 'paceStrict': None, 'paceDelay': 0, 'tryCount': 0, 'tryDelay': 0,
                 'gd_client_id': None, 'gd_api_key': None, 'gd_sheet_url': None,
                 'features': {}}

    if config.index_files:
        # Separate files
        config.separate = True
        combined_file = ''
        comps = config.index_files.split(',')
        config.toc = comps[0]+'.html' if comps[0] else ''
        config.index = comps[1]+'.html' if len(comps) > 1 and comps[1] else ''
        config.qindex = comps[2]+'.html' if len(comps) > 2 and comps[2] else ''
    else:
        # Combined file (cannot be paced)
        js_params['filename'] = out_name

    hide_chapters = False
    if config.pace:
        if config.printable:
            sys.exit('slidoc: Error: --pace and --printable options do not work well together')
        hide_chapters = True
        # Pace implies separate files
        config.separate = True
        combined_file = ''
        if len(input_files) == 1 and not config.index_files:
            # Single input file; no table of contents, by default
            config.toc = ''
        # Index not compatible with paced
        config.index = ''
        config.qindex = ''
        comps = config.pace.split(',')
        if comps[0]:
            js_params['paceStrict'] = int(comps[0])
        if len(comps) > 1 and comps[1].isdigit():
            js_params['paceDelay'] = int(comps[1])
        if len(comps) > 2 and comps[2].isdigit():
            js_params['tryCount'] = int(comps[2])
        if len(comps) > 3 and comps[3].isdigit():
            js_params['tryDelay'] = int(comps[3])
        if len(comps) > 4:
            js_params['sessionRevision'] = comps[4]
        if len(comps) > 5:
            js_params['sessionPrereqs'] = comps[5]

    gd_hmac_key = ''
    if config.google_docs:
        if not config.pace:
            sys.exit('slidoc: Error: Must use --google_docs with --pace')
        comps = config.google_docs.split(',')
        js_params['gd_sheet_url'] = comps[0]
        if len(comps) > 1:
            js_params['gd_client_id'], js_params['gd_api_key'] = comps[1:3]
        if len(comps) > 3:
            gd_hmac_key = comps[3]
    
    nb_site_url = config.site_url
    if combined_file:
        config.site_url = ''
    if config.site_url and not config.site_url.endswith('/'):
        config.site_url += '/'
    if config.image_url and not config.image_url.endswith('/'):
        config.image_url += '/'

    config.images = set(config.images.split(',')) if config.images else set()

    config.features = md2md.make_arg_set(config.features, features_all)
    js_params['features'] = dict([(x, 1) for x in config.features])

    config.strip = md2md.make_arg_set(config.strip, strip_all)
    if len(input_files) == 1:
        config.strip.add('chapters')

    if config.dest_dir and not os.path.isdir(config.dest_dir):
        sys.exit("Destination directory %s does not exist" % config.dest_dir)
    dest_dir = config.dest_dir+"/" if config.dest_dir else ''
    scriptdir = os.path.dirname(os.path.realpath(__file__))
    templates = {}
    for tname in ('doc_custom.css', 'doc_include.css', 'doc_include.js', 'doc_google.js',
                  'doc_include.html', 'doc_template.html', 'reveal_template.html'):
        templates[tname] = md2md.read_file(scriptdir+'/templates/'+tname)

    inc_css = templates['doc_include.css'] + HtmlFormatter().get_style_defs('.highlight')
    if config.css.startswith('http:') or config.css.startswith('https:'):
        link_css = '<link rel="stylesheet" type="text/css" href="%s">\n' % config.css
        css_html = '%s<style>%s</style>\n' % (link_css, inc_css)
    else:
        custom_css = md2md.read_file(config.css) if config.css else templates['doc_custom.css']
        css_html = '<style>\n%s\n%s</style>\n' % (custom_css, inc_css)
    gd_html = ''
    if config.google_docs:
        gd_html += (Google_docs_js % js_params) + ('\n<script>\n%s</script>\n' % templates['doc_google.js'])
        if js_params['gd_client_id']:
            gd_html += '<script src="https://apis.google.com/js/client.js?onload=onGoogleAPILoad"></script>\n'
        if gd_hmac_key:
            gd_html += '<script src="https://cdnjs.cloudflare.com/ajax/libs/blueimp-md5/2.3.0/js/md5.min.js"></script>\n'

    head_html = css_html + ('\n<script>\n%s</script>\n' % templates['doc_include.js'].replace('JS_PARAMS_OBJ', json.dumps(js_params)) ) + gd_html
    body_prefix = templates['doc_include.html']
    mid_template = templates['doc_template.html']

    math_inc = Mathjax_js % ( ', TeX: { equationNumbers: { autoNumber: "AMS" } }' if 'equation_number' in config.features else '')
    
    fnames = []
    for f in input_files:
        fcomp = os.path.splitext(os.path.basename(f.name))
        fnames.append(fcomp[0])
        if fcomp[1] != '.md':
            sys.exit('Invalid file extension for '+f.name)

        if config.notebook and os.path.exists(fcomp[0]+'.ipynb') and not config.overwrite and not config.dry_run:
            sys.exit("File %s.ipynb already exists. Delete it or specify --overwrite" % fcomp[0])

    if config.slides:
        reveal_themes = config.slides.split(',')
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

    slidoc_opts = set(['embed', '_slidoc'])
    if combined_file:
        slidoc_opts.add('_slidoc_combine')

    base_mods_args = md2md.Args_obj.create_args(None, dest_dir=config.dest_dir,
                                                      image_dir=config.image_dir,
                                                      image_url=config.image_url,
                                                      images=config.images | slidoc_opts)
    slide_mods_dict = {'strip': 'concepts,extensions'}
    if 'answers' in config.strip:
        slide_mods_dict['strip'] += ',answers'
    if 'notes' in config.strip:
        slide_mods_dict['strip'] += ',notes'
    slide_mods_args = md2md.Args_obj.create_args(base_mods_args, **slide_mods_dict)

    nb_mods_dict = {'strip': 'concepts,extensions', 'site_url': config.site_url}
    if 'rule' in config.strip:
        nb_mods_dict['strip'] += ',rule'
    nb_converter_args = md2nb.Args_obj.create_args(None, **nb_mods_dict)
    index_id = make_chapter_id(len(input_files)+1)
    qindex_id = make_chapter_id(len(input_files)+2)
    back_to_contents = nav_link('BACK TO CONTENTS', config.site_url, config.toc, hash='#'+make_chapter_id(0),
                                separate=config.separate, classes=['slidoc-nosidebar'], printable=config.printable)+'<p></p>\n'

    flist = []
    all_concept_warnings = []
    outfile_buffer = []
    combined_html = []
    if combined_file:
        combined_html.append( '<div id="slidoc-sidebar-right-container" class="slidoc-sidebar-right-container">\n' )
        combined_html.append( '<div id="slidoc-sidebar-right-wrapper" class="slidoc-sidebar-right-wrapper">\n' )
    fprefix = None
    math_found = False
    skulpt_load = False
    for j, f in enumerate(input_files):
        fname = fnames[j]
        filepath = f.name
        md_text = f.read()
        f.close()
        if config.separate:
            js_params['filename'] = fname

        file_head_html = css_html + ('\n<script>\n%s</script>\n' % templates['doc_include.js'].replace('JS_PARAMS_OBJ', json.dumps(js_params)) ) + gd_html


        base_parser = md2md.Parser(base_mods_args)
        slide_parser = md2md.Parser(slide_mods_args)
        md_text_modified = slide_parser.parse(md_text, filepath)
        md_text = base_parser.parse(md_text, filepath)

        if config.hide and 'hidden' in config.strip:
            md_text_modified = re.sub(r'(^|\n *\n--- *\n( *\n)+) {0,3}#{2,3}[^#][^\n]*'+config.hide+r'.*?(\n *\n--- *\n|$)', r'\1', md_text_modified, flags=re.DOTALL)

        prev_file = '' if j == 0                    else ('#'+make_chapter_id(j) if combined_file else fnames[j-1]+".html")
        next_file = '' if j >= len(input_files)-1 else ('#'+make_chapter_id(j+2) if combined_file else fnames[j+1]+".html")

        if fprefix == None:
            fprefix = fname
        else:
            # Find common filename prefix
            while fprefix:
                if fname[:len(fprefix)] == fprefix:
                    break
                fprefix = fprefix[:-1]

        filenumber = j+1

        # Strip annotations
        md_text = re.sub(r"(^|\n) {0,3}[Aa]nnotation:(.*?)(\n|$)", '', md_text)

        fheader, file_toc, renderer, md_html = md2html(md_text, filename=fname, config=config, filenumber=filenumber,
                                                        prev_file=prev_file, next_file=next_file,
                                                        index_id=index_id, qindex_id=qindex_id)

        all_concept_warnings += renderer.concept_warnings
        outname = fname+".html"
        flist.append( (fname, outname, fheader, file_toc) )

        math_in_file = '$$' in md_text or ('`$' in md_text and '$`' in md_text)
        if math_in_file:
            math_found = True
        if renderer.load_python:
            skulpt_load = True
        
        mid_params = {'math_js': math_inc if math_in_file else '',
                      'skulpt_js': Skulpt_js if renderer.load_python else ''}
        mid_params.update(SYMS)
        if config.dry_run:
            print("Indexed ", outname+":", fheader, file=sys.stderr)
        else:
            md_prefix = chapter_prefix(j+1, 'slidoc-reg-chapter', hide=hide_chapters)
            md_suffix = '</article> <!--chapter end-->\n'
            if combined_file:
                combined_html.append(md_prefix)
                combined_html.append(md_html)
                combined_html.append(md_suffix)
            else:
                head = file_head_html + (mid_template % mid_params) + body_prefix
                tail = md_prefix + md_html + md_suffix
                if Missing_ref_num_re.search(md_html):
                    # Still some missing reference numbers; output file later
                    outfile_buffer.append([outname, dest_dir+outname, head, tail])
                else:
                    outfile_buffer.append([outname, dest_dir+outname, '', ''])
                    write_doc(dest_dir+outname, head, tail)

            if config.slides:
                reveal_pars['reveal_title'] = fname
                reveal_pars['reveal_md'] = re.sub(r'(^|\n)\$\$(.+?)\$\$', r'`\1$$\2$$`', md_text_modified, flags=re.DOTALL)
                md2md.write_file(dest_dir+fname+"-slides.html", templates['reveal_template.html'] % reveal_pars)

            if config.notebook:
                md_parser = md2nb.MDParser(nb_converter_args)
                md2md.write_file(dest_dir+fname+".ipynb", md_parser.parse_cells(md_text_modified))

            if gd_hmac_key:
                user = 'admin'
                user_token = base64.b64encode(hmac.new(gd_hmac_key, user, hashlib.md5).digest())
                sheet_headers = ['name', 'id', 'Timestamp', 'revision',
                                 'questions', 'answers', 'primary_qconcepts', 'secondary_qconcepts']
                row_values = [fname, fname, None, js_params['sessionRevision'],
                                ','.join([x['qtype'] for x in renderer.questions]),
                                '|'.join([(x['correct'] or '').replace('|','/') for x in renderer.questions]),
                                '; '.join(sort_caseless(list(renderer.qconcepts[0]))),
                                '; '.join(sort_caseless(list(renderer.qconcepts[1])))
                                ]
                post_params = {'sheet': 'sessions', 'user': user, 'token': user_token,
                               'headers': json.dumps(sheet_headers), 'row': json.dumps(row_values)
                               }
                print('slidoc: Updated remote spreadsheet:', http_post(js_params['gd_sheet_url'], post_params))
    
    if not config.dry_run:
        if not combined_file:
            for outname, outpath, head, tail in outfile_buffer:
                if tail:
                    # Update "missing" reference numbers and write output file
                    tail = Missing_ref_num_re.sub(Missing_ref_num, tail)
                    write_doc(outpath, head, tail)
            print('Created output files:', ', '.join(x[0] for x in outfile_buffer), file=sys.stderr)
        if config.slides:
            print('Created *-slides.html files', file=sys.stderr)
        if config.notebook:
            print('Created *.ipynb files', file=sys.stderr)

    if config.toc:
        if config.toc_header:
            header_insert = md2md.read_file(config.toc_header)
            if config.toc_header.endswith('.md'):
                header_insert = MarkdownWithMath(renderer=MathRenderer(escape=False)).render(header_insert)
        else:
            header_insert = ''

        toc_html = []
        if config.index and (Global.first_tags or Global.first_qtags):
            toc_html.append(' '+nav_link('INDEX', config.site_url, config.index, hash='#'+index_id,
                                     separate=config.separate, printable=config.printable))
        toc_html.append('\n<ol class="slidoc-toc-list">\n' if 'sections' in config.strip else '\n<ul class="slidoc-toc-list" style="list-style-type: none;">\n')
        ifile = 0
        for fname, outname, fheader, file_toc in flist:
            ifile += 1
            chapter_id = make_chapter_id(ifile)
            slide_link = ''
            if not config.pace and config.slides:
                slide_link = ',&nbsp; <a href="%s%s" class="slidoc-clickable" target="_blank">%s</a>' % (config.site_url, fname+"-slides.html", 'slides')
            nb_link = ''
            if not config.pace and config.notebook and nb_site_url:
                nb_link = ',&nbsp; <a href="%s%s%s.ipynb" class="slidoc-clickable">%s</a>' % (md2nb.Nb_convert_url_prefix, nb_site_url[len('http://'):], fname, 'notebook')
            doc_link = nav_link('document', config.site_url, outname, hash='#'+chapter_id,
                                 separate=config.separate, printable=config.printable)

            if not config.pace:
                doc_link = nav_link('document', config.site_url, outname, hash='#'+chapter_id,
                                    separate=config.separate, printable=config.printable)
                toggle_link = '''<span class="slidoc-clickable slidoc-toc-chapters" onclick="Slidoc.idDisplay('%s-toc-sections');">%s</span>''' % (chapter_id, fheader)
            else:
                doc_link = nav_link('paced', config.site_url, outname, target='_blank', separate=True)
                toggle_link = '<span class="slidoc-toc-chapters">%s</span>' % (fheader,)
            toc_html.append('<li>%s%s<span class="slidoc-nosidebar">(<em>%s%s%s</em>)</span></li>\n' % (toggle_link, SPACER6, doc_link, slide_link, nb_link))

            if not config.pace:
                f_toc_html = ('\n<div id="%s-toc-sections" class="slidoc-toc-sections" style="display: none;">' % chapter_id)+file_toc+'\n<p></p></div>'
                toc_html.append(f_toc_html)

        toc_html.append('</ol>\n' if 'sections' in config.strip else '</ul>\n')

        if config.slides:
            toc_html.append('<em>Note</em>: When viewing slides, type ? for help or click <a class="slidoc-clickable" target="_blank" href="https://github.com/hakimel/reveal.js/wiki/Keyboard-Shortcuts">here</a>.\nSome slides can be navigated vertically.')

        toc_html.append('<p></p><em>Document formatted by <a href="https://github.com/mitotic/slidoc" class="slidoc-clickable">slidoc</a>.</em><p></p>')

        if not config.dry_run:
            toc_insert = ''
            if not config.pace:
                toc_insert += click_span('+Contents', "Slidoc.hide(this,'slidoc-toc-sections');",
                                        classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-noprint'])
            if combined_file:
                toc_insert = click_span(SYMS['rightpair'], "Slidoc.sidebarDisplay();",
                                    classes=['slidoc-clickable-sym', 'slidoc-nosidebar', 'slidoc-noprint']) + SPACER2 + toc_insert
                toc_insert = click_span(SYMS['leftpair'], "Slidoc.sidebarDisplay();",
                                    classes=['slidoc-clickable-sym', 'slidoc-sidebaronly', 'slidoc-noprint']) + toc_insert
                toc_insert += SPACER3 + click_span('+All Chapters', "Slidoc.allDisplay(this);",
                                                  classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-noprint'])
            toc_output = chapter_prefix(0, 'slidoc-toc-container slidoc-noslide', hide=hide_chapters)+header_insert+Toc_header+toc_insert+'<br>'+''.join(toc_html)+'</article>\n'
            if combined_file:
                all_container_prefix  = '<div id="slidoc-all-container" class="slidoc-all-container">\n'
                left_container_prefix = '<div id="slidoc-left-container" class="slidoc-left-container">\n'
                left_container_suffix = '</div> <!--slidoc-left-container-->\n'
                combined_html = [all_container_prefix, left_container_prefix, toc_output, left_container_suffix] + combined_html
            else:
                md2md.write_file(dest_dir+config.toc, Html_header, head_html,
                                  mid_template % mid_params, body_prefix, toc_output, Html_footer)
                print("Created ToC in", config.toc, file=sys.stderr)

    xref_list = []
    if config.index and (Global.first_tags or Global.first_qtags):
        first_references, covered_first, index_html = make_index(Global.first_tags, Global.sec_tags, config.site_url, fprefix=fprefix, index_id=index_id, index_file='' if combined_file else config.index)
        if not config.dry_run:
            index_html= ' <b>CONCEPT</b>\n' + index_html
            if config.qindex:
                index_html = nav_link('QUESTION INDEX', config.site_url, config.qindex, hash='#'+qindex_id,
                                      separate=config.separate, printable=config.printable) + '<p></p>\n' + index_html
            if config.crossref:
                index_html = ('<a href="%s%s" class="slidoc-clickable">%s</a><p></p>\n' % (config.site_url, config.crossref, 'CROSS-REFERENCING')) + index_html

            index_output = chapter_prefix(len(input_files)+1, 'slidoc-index-container slidoc-noslide', hide=hide_chapters) + back_to_contents +'<p></p>' + index_html + '</article>\n'
            if combined_file:
                combined_html.append('<div class="slidoc-noslide">'+index_output+'</div>\n')
            else:
                md2md.write_file(dest_dir+config.index, index_output)
                print("Created index in", config.index, file=sys.stderr)

        if config.crossref:
            if config.toc:
                xref_list.append('<a href="%s%s" class="slidoc-clickable">%s</a><p></p>\n' % (config.site_url, combined_file or config.toc, 'BACK TO CONTENTS'))
            xref_list.append("<h3>Concepts cross-reference (file prefix: "+fprefix+")</h3><p></p>")
            xref_list.append("\n<b>Concepts -> files mapping:</b><br>")
            for tag in first_references:
                links = ['<a href="%s%s.html#%s" class="slidoc-clickable" target="_blank">%s</a>' % (config.site_url, slide_file, slide_id, slide_file[len(fprefix):] or slide_file) for slide_file, slide_id, slide_header in first_references[tag]]
                xref_list.append(("%-32s:" % tag)+', '.join(links)+'<br>')

            xref_list.append("<p></p><b>Primary concepts covered in each file:</b><br>")
            for fname, outname, fheader, file_toc in flist:
                clist = covered_first[fname].keys()
                clist.sort()
                tlist = []
                for ctag in clist:
                    slide_id, slide_header = covered_first[fname][ctag]
                    tlist.append( '<a href="%s%s.html#%s" class="slidoc-clickable" target="_blank">%s</a>' % (config.site_url, fname, slide_id, ctag) )
                xref_list.append(('%-24s:' % fname[len(fprefix):])+'; '.join(tlist)+'<br>')
            if all_concept_warnings:
                xref_list.append('<pre>\n'+'\n'.join(all_concept_warnings)+'\n</pre>')

    if config.qindex and Global.first_qtags:
        import itertools
        qout_list = []
        qout_list.append('<b>QUESTION CONCEPT</b>\n')
        first_references, covered_first, qindex_html = make_index(Global.first_qtags, Global.sec_qtags, config.site_url, question=True, fprefix=fprefix, index_id=qindex_id, index_file='' if combined_file else config.qindex)
        qout_list.append(qindex_html)

        qindex_output = chapter_prefix(len(input_files)+2, 'slidoc-qindex-container slidoc-noslide', hide=hide_chapters) + back_to_contents +'<p></p>' + ''.join(qout_list) + '</article>\n'
        if not config.dry_run:
            if combined_file:
                combined_html.append('<div class="slidoc-noslide">'+qindex_output+'</div>\n')
            else:
                md2md.write_file(dest_dir+config.qindex, qindex_output)
                print("Created qindex in", config.qindex, file=sys.stderr)

        if config.crossref:
            xref_list.append('\n\n<p><b>CONCEPT SUB-QUESTIONS</b><br>Sub-questions are questions that address combinatorial (improper) concept subsets of the original question concept set. (*) indicates a variant question that explores all the same concepts as the original question. Numeric superscript indicates the number of concepts in the sub-question shared with the original question.</p>\n')
            xref_list.append('<ul style="list-style-type: none;">\n')
            xref_list.append('<li><em><b>Original question:</b> Sub-question1, Sub-question2, ...</em></li>')
            for fname, slide_id, header, qnumber, concept_id in Global.questions.values():
                q_id = make_file_id(fname, slide_id)
                xref_list.append('<li><b>'+nav_link(make_q_label(fname, qnumber, fprefix)+': '+header,
                                               config.site_url, fname+'.html', hash='#'+slide_id,
                                               separate=config.separate, keep_hash=True, printable=config.printable)+'</b>: ')
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
                                xref_list.append(nav_link(make_q_label(sub_fname, sub_qnumber, fprefix)+': '+header,
                                                        config.site_url, sub_fname+'.html', hash='#'+sub_slide_id,
                                                        separate=config.separate, keep_hash=True, printable=config.printable)
                                                        + ('<sup>%s</sup>, ' % sub_num) )

                xref_list.append('</li>\n')
            xref_list.append('</ul>\n')

    if config.crossref:
        md2md.write_file(dest_dir+config.crossref, ''.join(xref_list))
        print("Created crossref in", config.crossref, file=sys.stderr)

    if combined_file:
        combined_html.append( '</div><!--slidoc-sidebar-right-wrapper-->\n' )
        combined_html.append( '</div><!--slidoc-sidebar-right-container-->\n' )
        if config.toc:
            combined_html.append( '</div><!--slidoc-sidebar-all-container-->\n' )

        comb_params = {'math_js': math_inc if math_found else '',
                       'skulpt_js': Skulpt_js if skulpt_load else ''}
        comb_params.update(SYMS)
        md2md.write_file(dest_dir+combined_file, Html_header, head_html,
                          mid_template % comb_params, body_prefix,
                         '\n'.join(combined_html), Html_footer)
        print('Created combined HTML file in '+combined_file, file=sys.stderr)


def sort_caseless(list):
    new_list = list[:]
    sorted(new_list, key=lambda s: s.lower())
    return new_list

def http_post(url, params_dict):
    data = urllib.urlencode(params_dict)
    req = urllib2.Request(url, data)
    response = urllib2.urlopen(req) 
    result = response.read()
    try:
        result = json.loads(result)
    except Exception, excp:
        pass
    return result


Html_header = '''<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML//EN">
<html><head>
'''

Html_footer = '''
</body></html>
'''

Toc_header = '''
<h3>Table of Contents</h3>

'''

Mathjax_js = '''<script type="text/x-mathjax-config">
  MathJax.Hub.Config({
    tex2jax: {
      inlineMath: [ ['`$','$`'], ["$$$","$$$"] ],
      processEscapes: false
    }%s
  });
</script>
<script src='https://cdn.mathjax.org/mathjax/latest/MathJax.js?config=TeX-AMS-MML_HTMLorMML'></script>
'''

Skulpt_js = '''
<script src="http://ajax.googleapis.com/ajax/libs/jquery/1.9.0/jquery.min.js" type="text/javascript"></script> 
<script src="http://www.skulpt.org/static/skulpt.min.js" type="text/javascript"></script> 
<script src="http://www.skulpt.org/static/skulpt-stdlib.js" type="text/javascript"></script> 
'''


Google_docs_js = '''
<script>
var CLIENT_ID = '%(gd_client_id)s';
var API_KEY = '%(gd_api_key)s';
var LOGIN_BUTTON_ID = 'slidoc-google-login-button';
var AUTH_CALLBACK = Slidoc.slidocReady;

function onGoogleAPILoad() {
    console.log('onGoogleAPILoad:',GService);
    GService.onGoogleAPILoad();
}
</script>
'''

def write_doc(path, head, tail):
    md2md.write_file(path, Html_header, head, tail, Html_footer)

if __name__ == '__main__':
    import md2nb

    strip_all = ['answers', 'chapters', 'concepts', 'contents', 'hidden', 'inline_js', 'navigate', 'notes', 'rule', 'sections']
    features_all = ['equation_number', 'incremental', 'progress_bar', 'untitled_number']

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--crossref', metavar='FILE', help='Cross reference HTML file')
    parser.add_argument('--css', metavar='FILE_OR_URL', help='Custom CSS filepath or URL (derived from doc_custom.css)')
    parser.add_argument('--dest_dir', metavar='DIR', help='Destination directory for creating files')
    parser.add_argument('--features', metavar='OPT1,OPT2,...', help='Enable feature %s|all|all,but,...' % ','.join(features_all))
    parser.add_argument('--google_docs', help='spreadsheet_url[,client_id,api_key] (export sessions to Google Docs spreadsheet)')
    parser.add_argument('--hide', metavar='REGEX', help='Hide sections matching header regex (e.g., "[Aa]nswer")')
    parser.add_argument('--image_dir', metavar='DIR', help='image subdirectory (default: images)')
    parser.add_argument('--image_url', metavar='URL', help='URL prefix for images, including image_dir')
    parser.add_argument('--images', help='images=(check|copy|export|import)[_all] to process images')
    parser.add_argument('--index_files', metavar='TOC,INDEX,QINDEX', help='Table_of_contents,concep_index,question_index base filenames, e.g., "toc,ind,qind" (if omitted, all input files are combined, unless pacing)')
    parser.add_argument('--notebook', help='Create notebook files', action="store_true", default=None)
    parser.add_argument('--outfile', metavar='NAME', help='Base name of HTML output file')
    parser.add_argument('--pace', metavar='PACE_STRICT,DELAY_SEC,TRY_COUNT,TRY_DELAY,REVISION,PREREQS', help='Options for paced session using combined file, e.g., 1,0,1 to force answering questions')
    parser.add_argument('--printable', help='Printer-friendly output', action="store_true", default=None)
    parser.add_argument('--site_url', metavar='URL', help='URL prefix to link local HTML files (default: "")')
    parser.add_argument('--slides', metavar='THEME,CODE_THEME,FSIZE,NOTES_PLUGIN', help='Create slides with reveal.js theme(s) (e.g., ",zenburn,190%%")')
    parser.add_argument('--strip', metavar='OPT1,OPT2,...', help='Strip %s|all|all,but,...' % ','.join(strip_all))
    parser.add_argument('--toc_header', metavar='FILE', help='.html or .md header file for ToC')

    cmd_parser = argparse.ArgumentParser(parents=[parser],description='Convert from Markdown to HTML')
    cmd_parser.add_argument('--dry_run', help='Do not create any HTML files (index only)', action="store_true", default=None)
    cmd_parser.add_argument('--overwrite', help='Overwrite files', action="store_true", default=None)
    cmd_parser.add_argument('-v', '--verbose', help='Verbose output', action="store_true", default=None)
    cmd_parser.add_argument('file', help='Markdown filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)

    cmd_args = cmd_parser.parse_args()
    first_name = os.path.splitext(os.path.basename(cmd_args.file[0].name))[0]

    # Read first line of first file and rewind it
    first_line = cmd_args.file[0].readline()
    cmd_args.file[0].seek(0)
    match = re.match(r'^ {0,3}<!--slidoc-defaults\s+(.*?)-->\s*?\n', first_line)
    if match:
        try:
            line_args_list = shlex.split(match.group(1).strip())
            if cmd_args.verbose:
                print('First line arguments from file', first_name, file=sys.stderr)
                print('    ', line_args_list, file=sys.stderr)
            line_args_dict = vars(parser.parse_args(line_args_list))
        except Exception, excp:
            sys.exit('slidoc: ERROR in parsing command options in first line of %s: %s' % (cmd_args.file[0].name, excp))

        cmd_args_dict = vars(cmd_args)
        for arg_name in cmd_args_dict:
            if arg_name not in line_args_dict:
                # Argument not specified in file line (copy from command line)
                line_args_dict[arg_name] = cmd_args_dict[arg_name]
            elif cmd_args_dict[arg_name] != None:
                # Argument also specified in command line (override)
                line_args_dict[arg_name] = cmd_args_dict[arg_name]
        cmd_args = argparse.Namespace(**line_args_dict)

    # Some arguments need to be set explicitly to '' by default, rather than staying as None
    cmd_defaults = {'css': '', 'dest_dir': '', 'hide': '', 'image_dir': 'images', 'image_url': '',
                     'site_url': ''}
    
    # Assign default (non-None) values to arguments not specified anywhere
    for arg_name in cmd_defaults:
        if getattr(cmd_args, arg_name) == None:
            setattr(cmd_args, arg_name, cmd_defaults[arg_name]) 

    config_dict = vars(cmd_args)
    input_files = config_dict.pop('file')

    if cmd_args.verbose:
        print('Effective argument list', file=sys.stderr)
        print('    ', argparse.Namespace(**config_dict), file=sys.stderr)

    process_input(input_files, config_dict)
