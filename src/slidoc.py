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
# Copyright (c) IPython Development Team.
# Modified by R. Saravanan
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

SYMS = {'prev': '&#9668;', 'next': '&#9658;', 'return': '&#8617;', 'up': '&#9650;',
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
    return '\n<div id="%s" class="slidoc-container %s" %s> <!--chapter start-->\n' % (make_chapter_id(num), classes, attrs)

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


def make_index(first_tags, sec_tags, site_url, fprefix='', index_id='', index_file=''):
    # index_file would be null string for combined file
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
            out_list.append('<b id="slidoc-index-%s">%s</b>\n<ul style="list-style-type: none;">\n' % (first_letter.upper(), first_letter.upper()) )
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
        
    out_list = ['<b>INDEX</b><blockquote>\n'] + ["&nbsp;&nbsp;".join(['<a href="#slidoc-index-%s" class="slidoc-clickable">%s</a>' % (x.upper(), x.upper()) for x in first_letters])] + ['</blockquote>'] + out_list
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

class MathBlockLexer(mistune.BlockLexer):
    default_rules = ['block_math', 'latex_environment', 'slidoc_header', 'slidoc_answer', 'slidoc_concepts', 'slidoc_notes', 'minirule'] + mistune.BlockLexer.default_rules

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

    
class MathInlineGrammar(mistune.InlineGrammar):
    slidoc_choice = re.compile(r"^ {0,3}([a-pA-P])\.\. +")
    math =          re.compile(r"^`\$(.+?)\$`")
    block_math =    re.compile(r"^\$\$(.+?)\$\$", re.DOTALL)
    text =          re.compile(r'^[\s\S]+?(?=[\\<!\[_*`~$]|https?://| {2,}\n|$)')
    internal_ref =  re.compile(
        r'^\[('
        r'(?:\[[^^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*'
        r')\]\s*\{\s*#([^^\}]*)\}'
    )

class MathInlineLexer(mistune.InlineLexer):
    default_rules = ['slidoc_choice', 'block_math', 'math', 'internal_ref'] + mistune.InlineLexer.default_rules

    def __init__(self, renderer, rules=None, **kwargs):
        if rules is None:
            rules = MathInlineGrammar()
        super(MathInlineLexer, self).__init__(renderer, rules, **kwargs)

    def output_slidoc_choice(self, m):
        return self.renderer.slidoc_choice(m.group(1).upper())

    def output_math(self, m):
        return self.renderer.inline_math(m.group(1))

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
                    tag_html = nav_link(text, self.renderer.options['cmd_args'].site_url, self.renderer.options['cmd_args'].index,
                                        hash=tag_hash, combine=self.renderer.options['cmd_args'].combine, target='_blank',
                                        keep_hash=True, printable=self.renderer.options['cmd_args'].printable)
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
                    classes.append('slidoc-forward-link')
                if link.startswith('#:'):
                    # Numbered reference
                    if ref_id in Global.ref_tracker:
                        num_label, _, ref_class = Global.ref_tracker[ref_id]
                        classes.append(ref_class)
                    else:
                        num_label = '_MISSING_SLIDOC_REF_NUM(#%s)' % ref_id
                    text += num_label
                return click_span(text, "Slidoc.go('#%s');" % ref_id, classes=classes,
                                  href='#'+ref_id if self.renderer.options['cmd_args'].printable else '')

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
                if key.startswith('::') and 'chapters' not in self.options['cmd_args'].strip:
                    Global.chapter_ref_counter[text_key] += 1
                    num_label = "%d.%d" % (self.renderer.options['filenumber'], Global.chapter_ref_counter[text_key])
                else:
                    Global.ref_counter[text_key] += 1
                    num_label = "%d" % Global.ref_counter[text_key]
                text += num_label
            Global.ref_tracker[ref_id] = (num_label, key, ref_class)
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

    def render(self, text, index_id='', qindex_id=''):
        self.renderer.index_id = index_id
        self.renderer.qindex_id = qindex_id
        html = super(MarkdownWithMath, self).render(text)

        first_slide_prefix = '<span id="%s-attrs" class="slidoc-attrs" style="display: none;">%s</span>\n' % (self.renderer.first_id, base64.b64encode(json.dumps(self.renderer.questions)))

        if self.renderer.qconcepts[0] or self.renderer.qconcepts[1]:
            # Include sorted list of concepts related to questions
            q_list = [sort_caseless(list(self.renderer.qconcepts[j])) for j in (0, 1)]
            first_slide_prefix += '<span id="%s-qconcepts" class="slidoc-qconcepts" style="display: none;">%s</span>\n' % (self.renderer.first_id, base64.b64encode(json.dumps(q_list)))

        
        return self.renderer.slide_prefix(self.renderer.first_id)+first_slide_prefix+concept_chain(self.renderer.first_id, self.renderer.options["cmd_args"].site_url)+html+self.renderer.end_notes()+self.renderer.end_hide()+'</div>\n<!--last slide end-->\n'

    
class IPythonRenderer(mistune.Renderer):
    header_attr_re = re.compile(r'^.*?(\s*\{\s*#(\S+)(\s+[^\}]*)?\s*\})\s*$')

    def __init__(self, **kwargs):
        super(IPythonRenderer, self).__init__(**kwargs)
        self.file_header = ''
        self.header_list = []
        self.concept_warnings = []
        self.hide_end = None
        self.notes_end = None
        self.section_number = 0
        self.untitled_number = 0
        self.questions = []
        self.qconcepts = [set(),set()]
        self.slide_number = 0
        self._new_slide()
        self.first_id = self.get_slide_id()
        self.index_id = ''                     # Set by render()
        self.qindex_id = ''                    # Set by render

    def _new_slide(self):
        self.slide_number += 1
        self.choice_end = None
        self.cur_choice = ''
        self.cur_qtype = ''
        self.cur_header = ''
        self.cur_answer = False
        self.slide_concepts = ''
        self.first_para = True

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

    def slide_prefix(self, slide_id, classes=''):
        chapter_id, sep, _ = slide_id.partition('-')
        return '\n<div id="%s" class="slidoc-slide %s-slide %s"> <!--slide start-->\n' % (slide_id, chapter_id, classes)

    def hrule(self, implicit=False):
        """Rendering method for ``<hr>`` tag."""
        if self.choice_end:
            prefix = self.choice_end

        self._new_slide()

        hide_prefix = self.end_hide()
        new_slide_id = self.get_slide_id()

        if implicit or 'rule' in self.options["cmd_args"].strip or (hide_prefix and 'hidden' in self.options["cmd_args"].strip):
            html = ''
        elif self.options.get('use_xhtml'):
            html = '<hr class="slidoc-noslide slidoc-noprint"/>\n'
        else:
            html = '<hr class="slidoc-noslide slidoc-noprint">\n'

        html += '</div><!--slide end-->\n' + self.slide_prefix(new_slide_id) + concept_chain(new_slide_id, self.options["cmd_args"].site_url)
        return self.end_notes()+hide_prefix+html
    
    def paragraph(self, text):
        """Rendering paragraph tags. Like ``<p>``."""
        if not self.cur_header and self.first_para:
            self.untitled_number += 1
            if 'untitled_number' in self.options["cmd_args"].features:
                # Number untitled slides (e.g., as in question numbering) 
                text = ('%d. ' % self.untitled_number) + text
        self.first_para = False
        return super(IPythonRenderer, self).paragraph(text)

    def header(self, text, level, raw=None):
        """Handle markdown headings
        """
        html = super(IPythonRenderer, self).header(text, level, raw=raw)
        try:
            hdr = ElementTree.fromstring(html)
        except Exception:
            # failed to parse, just return it unmodified
            return html

        prev_slide_end = ''
        if self.cur_header and level <= 2:
            # Implicit horizontal rule before Level 1/2 header
            prev_slide_end = self.hrule(implicit=True)
        
        text = html2text(hdr).strip()
        match = self.header_attr_re.match(text)
        header_ref = md2md.ref_key(text)
        if match:
            # Header attributes found
            if not re.match(r'^[-.\w]+$', match.group(2)):
                print('REF-WARNING: Use only alphanumeric chars, hyphens and dots in references: %s' % text, file=sys.stderr)
            header_ref = md2md.ref_key(match.group(2))
            try:
                hdr = ElementTree.fromstring(html.replace(match.group(1),''))
                text = html2text(hdr).strip()
            except Exception:
                pass

        ref_id = 'slidoc-ref-'+md2md.make_id_from_text(header_ref)
        if ref_id in Global.ref_tracker:
            print('REF-ERROR: Duplicate reference #%s (#%s)' % (ref_id, header_ref), file=sys.stderr)
        else:
            Global.ref_tracker[ref_id] = ('??', header_ref, '')

        hdr.set('id', ref_id)
        hdr_class = (hdr.get('class')+' ' if hdr.get('class') else '') + ('slidoc-referable-in-%s' % self.get_slide_id())

        hide_block = self.options["cmd_args"].hide and re.search(self.options["cmd_args"].hide, text)
        if level > 3 or (level == 3 and not (hide_block and self.hide_end is None)):
            # Ignore higher level headers (except for level 3 hide block, if no earlier header in slide)
            return ElementTree.tostring(hdr)

        pre_header = ''
        post_header = ''
        hdr_prefix = ''
        clickable_secnum = False
        if level <= 2 and not self.file_header:
            # First (file) header
            if 'chapters' not in self.options['cmd_args'].strip:
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
                if 'sections' not in self.options['cmd_args'].strip:
                    if 'chapters' not in self.options['cmd_args'].strip:
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


    # Pass math through unaltered - mathjax does the rendering in the browser
    def block_math(self, text):
        return '$$%s$$' % text

    def latex_environment(self, name, text):
        return r'\begin{%s}%s\end{%s}' % (name, text, name)

    def inline_math(self, text):
        return '`$%s$`' % text

    def slidoc_header(self, name, text):
        if name == "type" and text:
            params = text.split()
            type_code = params[0]
            if type_code in ("choice", "multichoice", "number", "text", "point", "line"):
                self.cur_qtype = type_code
                self.questions.append([type_code, None])
             
        return ''

    def slidoc_choice(self, name):
        if not self.cur_qtype:
            self.cur_qtype = 'choice'
            self.questions.append([self.cur_qtype, None])
        elif self.cur_qtype != 'choice':
            print("    ****CHOICE-ERROR: %s: Line '%s.. ' implies multiple choice question in '%s'" % (self.options["filename"], name, self.cur_header), file=sys.stderr)
            return name+'.. '

        prefix = ''
        if not self.cur_choice:
            prefix = '<blockquote>\n'
            self.choice_end = '</blockquote>\n'

        self.cur_choice = name

        params = {'id': self.get_slide_id(), 'opt': name, 'qno': len(self.questions)}
        if self.options['cmd_args'].hide or self.options['cmd_args'].pace:
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

        if text.lower() in ('choice', 'multichoice', 'number', 'text', 'point', 'line'):
            # Unspecified answer
            if not self.cur_qtype:
                self.cur_qtype = text.lower()
                self.questions.append([self.cur_qtype, None])
            elif self.cur_qtype != text.lower():
                print("    ****ANSWER-ERROR: %s: 'Answer: %s' line ignored; expected 'Answer: %s'" % (self.options["filename"], text, self.cur_qtype), file=sys.stderr)

            text = ''

        if not self.cur_qtype:
            # Determine question type from answer
            if len(text) == 1 and text.isalpha():
                self.cur_qtype = 'choice'
            elif text and text[0].isdigit():
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
                    self.cur_qtype = 'number'
                    text = ans + (' +/- '+error if error else '')
                else:
                    print("    ****ANSWER-ERROR: %s: 'Answer: %s' is not a valid numeric answer; expect 'ans +/- err'" % (self.options["filename"], text), file=sys.stderr)
                    self.cur_qtype = 'text'
            else:
                self.cur_qtype = 'text'    # Default answer type
            self.questions.append([self.cur_qtype, None])

        if not self.options['cmd_args'].pace and (not text or 'answers' in self.options['cmd_args'].strip):
            # Strip correct answers
            return choice_prefix+name.capitalize()+':'+'<p></p>\n'

        if self.options['cmd_args'].hide or self.options['cmd_args'].pace:
            self.questions[-1][1] = text.upper() if len(text) == 1 else text
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

            ans_html = '''<div id="%(sid)s-answer" class="slidoc-answer-container" %(ans_extras)s>
<span id="%(sid)s-ansprefix" style="display: none;">%(ans_text)s:</span>
<span id="%(sid)s-anstype" class="slidoc-answer-type" style="display: none;">%(ans_type)s</span>
<input id="%(sid)s-ansinput" type="%(inp_type)s" class="slidoc-answer-input" %(inp_extras)s onkeydown="Slidoc.inputKeyDown(event);"></input>
<button id="%(sid)s-ansclick" class="slidoc-clickable" %(click_extras)s>Answer</button>
<span id="%(sid)s-correct-mark" class="slidoc-correct-answer"></span>
<span id="%(sid)s-wrong-mark" class="slidoc-wrong-answer"></span>
<span id="%(sid)s-correct" class="slidoc-correct-answer" style="display: none;"></span>
</div>
''' % ans_params

            return choice_prefix+ans_html+'\n'
        else:
            return choice_prefix+name.capitalize()+': '+text+'<p></p>\n'


    def slidoc_concepts(self, name, text):
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

        if 'concepts' in self.options['cmd_args'].strip:
            # Strip concepts
            return ''

        id_str = self.get_slide_id()+'-concepts'
        display_style = 'inline' if self.options['cmd_args'].printable else 'none'
        tag_html = '''<div class="slidoc-concepts-container"><span class="slidoc-clickable slidoc-noslide" onclick="Slidoc.toggleInlineId('%s')">%s:</span> <span id="%s" style="display: %s;">''' % (id_str, name.capitalize(), id_str, display_style)

        if self.options["cmd_args"].index:
            first = True
            for tag in tags:
                if not first:
                    tag_html += '; '
                first = False
                tag_hash = '#%s-concept-%s' % (self.index_id, md2md.make_id_from_text(tag))
                tag_html += nav_link(tag, self.options['cmd_args'].site_url, self.options['cmd_args'].index,
                                     hash=tag_hash, combine=self.options['cmd_args'].combine, target='_blank',
                                     keep_hash=True, printable=self.options['cmd_args'].printable)
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
        if self.cur_qtype:
            classes += ' slidoc-question-notes'
        return prefix + ('''<br><span id="%s" class="%s" onclick="Slidoc.classDisplay('%s')" style="display: inline;">Notes:</span>\n''' % (id_str, classes, id_str)) + suffix


    def table_of_contents(self, filepath='', filenumber=1):
        if len(self.header_list) < 1:
            return ''

        toc = [('\n<ol class="slidoc-section-toc">' if 'sections' in self.options['cmd_args'].strip
                 else '\n<ul class="slidoc-section-toc" style="list-style-type: none;">') ]

        for id_str, header in self.header_list:  # Skip first header
            if filepath or self.options['cmd_args'].printable:
                elem = ElementTree.Element("a", {"class" : "header-link", "href" : filepath+"#"+id_str})
            else:
                elem = ElementTree.Element("span", {"class" : "slidoc-clickable", "onclick" : "Slidoc.go('#%s');" % id_str})
            elem.text = header
            toc.append('<li>'+ElementTree.tostring(elem)+'</li>')

        toc.append('</ol>\n' if 'sections' in self.options['cmd_args'].strip else '</ul>\n')
        return '\n'.join(toc)

    def block_code(self, code, lang=None):
        """Rendering block level code. ``pre > code``.
        """
        lexer = None
        if code.endswith('\n\n'):
            code = code[:-1]
        if lang and not lang.startswith('nb_'):
            try:
                lexer = get_lexer_by_name(lang, stripall=True)
            except ClassNotFound:
                code = lang + '\n' + code

        if not lexer:
            return '\n<pre><code>%s</code></pre>\n' % \
                mistune.escape(code)

        formatter = HtmlFormatter()
        return highlight(code, lexer, formatter)

def click_span(text, onclick, id='', classes=['slidoc-clickable'], href=''):
    id_str = ' id="%s"' % id if id else ''
    if href:
        return '''<a %s href="%s" class="%s" onclick="%s">%s</a>''' % (id_str, href, ' '.join(classes), onclick, text)
    else:
        return '''<span %s class="%s" onclick="%s">%s</span>''' % (id_str, ' '.join(classes), onclick, text)

def nav_link(text, site_url, href, hash='', combine=False, keep_hash=False, printable=False, target='', classes=[]):
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
    elif combine:
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

def md2html(source, filename, cmd_args, filenumber=1, prev_file='', next_file='', index_id='', qindex_id=''):
    """Convert a markdown string to HTML using mistune, returning (first_header, html)"""
    Global.chapter_ref_counter = defaultdict(int)

    renderer = IPythonRenderer(escape=False, filename=filename, cmd_args=cmd_args, filenumber=filenumber)

    content_html = MarkdownWithMath(renderer=renderer).render(source, index_id=index_id, qindex_id=qindex_id)

    content_html = Missing_ref_num_re.sub(Missing_ref_num, content_html)

    pre_header_html = ''
    tail_html = ''
    post_header_html = ''
    if 'navigate' not in cmd_args.strip:
        nav_html = ''
        if cmd_args.toc:
            nav_html += nav_link(SYMS['return'], cmd_args.site_url, cmd_args.toc, hash='#'+make_chapter_id(0), combine=cmd_args.combine, classes=['slidoc-nosidebar'], printable=cmd_args.printable) + SPACER6
            nav_html += nav_link(SYMS['prev'], cmd_args.site_url, prev_file, combine=cmd_args.combine, classes=['slidoc-noall'], printable=cmd_args.printable) + SPACER6
            nav_html += nav_link(SYMS['next'], cmd_args.site_url, next_file, combine=cmd_args.combine, classes=['slidoc-noall'], printable=cmd_args.printable) + SPACER6

        pre_header_html += '<div class="slidoc-noslide slidoc-noprint slidoc-noall">'+nav_html+click_span(SYMS['square'], "Slidoc.slideViewStart();", classes=["slidoc-clickable-sym", 'slidoc-nosidebar'])+'</div>\n'

        tail_html = '<div class="slidoc-noslide slidoc-nosidebar">' + nav_html + '<a href="#%s" class="slidoc-clickable-sym">%s</a>%s' % (renderer.first_id, SYMS['up'], SPACER6) + '</div>\n'

    if 'contents' not in cmd_args.strip:
        chapter_id = make_chapter_id(filenumber)
        post_header_html += ('<div class="slidoc-chapter-toc %s-chapter-toc slidoc-nosidebar">' % chapter_id)+renderer.table_of_contents(filenumber=filenumber)+'</div>\n'
        if post_header_html:
            post_header_html = '<div class="slidoc-nopaced">'+ post_header_html + '</div>\n'
            post_header_html += click_span('&#8722;Contents', "Slidoc.hide(this, '%s');" % (chapter_id+'-chapter-toc'),
                                            id=chapter_id+'-chapter-toc-hide', classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-chapter-toc-hide', 'slidoc-nopaced', 'slidoc-noprint', 'slidoc-nosidebar'])

    if 'contents' not in cmd_args.strip and 'slidoc-notes' in content_html:
        post_header_html += '&nbsp;&nbsp;' + click_span('&#8722;All Notes',
                                             "Slidoc.hide(this,'slidoc-notes');",id=renderer.first_id+'-hidenotes',
                                              classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-nopaced', 'slidoc-noprint'])

    if 'slidoc-answer-type' in content_html and 'slidoc-concepts-container' in content_html:
        post_header_html += '&nbsp;&nbsp;' + click_span('Missed question concepts', "Slidoc.showConcepts();")

    content_html = content_html.replace('__PRE_HEADER__', pre_header_html)
    content_html = content_html.replace('__POST_HEADER__', post_header_html)
    content_html += tail_html

    if 'hidden' in cmd_args.strip:
        # Strip out hidden answer slides
        content_html = re.sub(r"<!--slidoc-hidden-block-begin\[([-\w]+)\](.*?)<!--slidoc-hidden-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    if 'notes' in cmd_args.strip:
        # Strip out notes
        content_html = re.sub(r"<!--slidoc-notes-block-begin\[([-\w]+)\](.*?)<!--slidoc-notes-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    file_toc = renderer.table_of_contents('' if cmd_args.combine else cmd_args.site_url+filename+'.html', filenumber=filenumber)

    return (renderer.file_header or filename, file_toc, renderer, content_html)

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

    strip_all = ['answers', 'chapters', 'concepts', 'contents', 'hidden', 'navigate', 'notes', 'rule', 'sections']
    features_all = ['equation_number', 'untitled_number']

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--combine', metavar='FILE', help='Combine all files into a single HTML file')
    parser.add_argument('--crossref', metavar='FILE', help='Cross reference HTML file')
    parser.add_argument('--css', metavar='FILE', help='Custom CSS file (derived from doc_custom.css)')
    parser.add_argument('--dest_dir', metavar='DIR', help='Destination directory for creating files')
    parser.add_argument('--features', metavar='OPT1,OPT2,...', help='Enable feature %s|all|all,but,...' % ','.join(features_all))
    parser.add_argument('--google_docs', help='spreadsheet_url[,client_id,api_key] (export sessions to Google Docs spreadsheet)')
    parser.add_argument('--hide', metavar='REGEX', help='Hide sections matching header regex (e.g., "[Aa]nswer")')
    parser.add_argument('--image_dir', metavar='DIR', help='image subdirectory (default: images)')
    parser.add_argument('--image_url', metavar='URL', help='URL prefix for images, including image_dir')
    parser.add_argument('--images', help='images=(check|copy|export|import)[_all] to process images')
    parser.add_argument('--index', metavar='FILE', help='index HTML file (default: ind.html)')
    parser.add_argument('--notebook', help='Create notebook files', action="store_true", default=None)
    parser.add_argument('--pace', metavar='PACE_END,DELAY_SEC,TRY_COUNT,TRY_DELAY,REVISION', help='Options for paced session using combined file, e.g., 0,0,1 to force answering questions')
    parser.add_argument('--printable', help='Printer-friendly output', action="store_true", default=None)
    parser.add_argument('--qindex', metavar='FILE', help='Question index HTML file (default: "")')
    parser.add_argument('--site_url', metavar='URL', help='URL prefix to link local HTML files (default: "")')
    parser.add_argument('--slides', metavar='THEME,CODE_THEME,FSIZE,NOTES_PLUGIN', help='Create slides with reveal.js theme(s) (e.g., ",zenburn,190%%")')
    parser.add_argument('--strip', metavar='OPT1,OPT2,...', help='Strip %s|all|all,but,...' % ','.join(strip_all))
    parser.add_argument('--toc', metavar='FILE', help='Table of contents file (default: toc.html)')
    parser.add_argument('--toc_header', metavar='FILE', help='HTML header file for ToC')

    cmd_parser = argparse.ArgumentParser(parents=[parser],description='Convert from Markdown to HTML')
    cmd_parser.add_argument('--dry_run', help='Do not create any HTML files (index only)', action="store_true", default=None)
    cmd_parser.add_argument('--overwrite', help='Overwrite files', action="store_true", default=None)
    cmd_parser.add_argument('file', help='Markdown filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)

    # Some arguments need to be set explicitly to '' by default, rather than staying as None
    cmd_defaults = {'dest_dir': '', 'hide': '', 'image_dir': 'images', 'image_url': '', 'index': 'ind.html',
                     'toc': 'toc.html', 'site_url': ''}
    
    cmd_args = cmd_parser.parse_args()
    # Read first line of first file and rewind it
    first_line = cmd_args.file[0].readline()
    cmd_args.file[0].seek(0)
    match = re.match(r'^ {0,3}<!--slidoc-defaults\s+(.*?)-->\s*?\n', first_line)
    if match:
        try:
            line_args_list = shlex.split(match.group(1).strip())
            print('slidoc: First line arguments from file', cmd_args.file[0].name, line_args_list)
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

    # Assign default (non-None) values to arguments not specified anywhere
    for arg_name in cmd_defaults:
        if getattr(cmd_args, arg_name) == None:
            setattr(cmd_args, arg_name, cmd_defaults[arg_name]) 
    effective_args = vars(cmd_args).copy()
    del effective_args['file']
    print('slidoc: Effective argument list', argparse.Namespace(**effective_args))

    js_params = {'filename': '', 'sessionVersion': '1.0', 'sessionRevision': '',
                 'paceEnd': None, 'paceDelay': 0, 'tryCount': 0, 'tryDelay': 0,
                 'gd_client_id': None, 'gd_api_key': None, 'gd_sheet_url': None}
    if cmd_args.combine:
        js_params['filename'] = os.path.splitext(os.path.basename(cmd_args.combine))[0]
        print('Filename: ', js_params['filename'], file=sys.stderr)

    hide_chapters = False
    if cmd_args.pace:
        if cmd_args.combine:
            sys.exit('slidoc: Error: --pace and --combine options do not work well together')
        if cmd_args.printable:
            sys.exit('slidoc: Error: --pace and --printable options do not work well together')
        hide_chapters = True
        # Index not compatible with paced
        cmd_args.index = ''
        cmd_args.qindex = ''
        comps = cmd_args.pace.split(',')
        if comps[0]:
            js_params['paceEnd'] = int(comps[0])
        if len(comps) > 1 and comps[1].isdigit():
            js_params['paceDelay'] = int(comps[1])
        if len(comps) > 2 and comps[2].isdigit():
            js_params['tryCount'] = int(comps[2])
        if len(comps) > 3 and comps[3].isdigit():
            js_params['tryDelay'] = int(comps[3])
        if len(comps) > 4:
            js_params['sessionRevision'] = comps[4]

    gd_hmac_key = ''
    if cmd_args.google_docs:
        if not cmd_args.pace:
            sys.exit('slidoc: Error: Must use --google_docs with --pace')
        comps = cmd_args.google_docs.split(',')
        js_params['gd_sheet_url'] = comps[0]
        if len(comps) > 1:
            js_params['gd_client_id'], js_params['gd_api_key'] = comps[1:3]
        if len(comps) > 3:
            gd_hmac_key = comps[3]
    
    nb_site_url = cmd_args.site_url
    if cmd_args.combine:
        cmd_args.site_url = ''
    if cmd_args.site_url and not cmd_args.site_url.endswith('/'):
        cmd_args.site_url += '/'
    if cmd_args.image_url and not cmd_args.image_url.endswith('/'):
        cmd_args.image_url += '/'

    cmd_args.images = set(cmd_args.images.split(',')) if cmd_args.images else set()

    cmd_args.features = md2md.make_arg_set(cmd_args.features, features_all)

    cmd_args.strip = md2md.make_arg_set(cmd_args.strip, strip_all)
    if len(cmd_args.file) == 1:
        cmd_args.strip.add('chapters')

    if cmd_args.dest_dir and not os.path.isdir(cmd_args.dest_dir):
        sys.exit("Destination directory %s does not exist" % cmd_args.dest_dir)
    dest_dir = cmd_args.dest_dir+"/" if cmd_args.dest_dir else ''
    scriptdir = os.path.dirname(os.path.realpath(__file__))
    templates = {}
    for tname in ('doc_custom.css', 'doc_include.css', 'doc_include.js', 'doc_google.js',
                  'doc_include.html', 'doc_template.html', 'reveal_template.html'):
        templates[tname] = md2md.read_file(scriptdir+'/templates/'+tname)

    custom_css = md2md.read_file(cmd_args.css) if cmd_args.css else templates['doc_custom.css']
    css_html = '<style>\n%s\n%s</style>\n' % (custom_css, templates['doc_include.css'])
    gd_html = ''
    if cmd_args.google_docs:
        gd_html += (Google_docs_js % js_params) + ('\n<script>\n%s</script>\n' % templates['doc_google.js'])
        if js_params['gd_client_id']:
            gd_html += '<script src="https://apis.google.com/js/client.js?onload=onGoogleAPILoad"></script>\n'
        if gd_hmac_key:
            gd_html += '<script src="https://cdnjs.cloudflare.com/ajax/libs/blueimp-md5/2.3.0/js/md5.min.js"></script>\n'

    head_html = css_html + ('\n<script>\n%s</script>\n' % templates['doc_include.js'].replace('JS_PARAMS_OBJ', json.dumps(js_params)) ) + gd_html
    body_prefix = templates['doc_include.html']
    mid_template = templates['doc_template.html']

    math_inc = Mathjax_js % ( ', TeX: { equationNumbers: { autoNumber: "AMS" } }' if 'equation_number' in cmd_args.features else '')
    
    fnames = []
    for f in cmd_args.file:
        fcomp = os.path.splitext(os.path.basename(f.name))
        fnames.append(fcomp[0])
        if fcomp[1] != '.md':
            sys.exit('Invalid file extension for '+f.name)

        if cmd_args.notebook and os.path.exists(fcomp[0]+'.ipynb') and not cmd_args.overwrite and not cmd_args.dry_run:
            sys.exit("File %s.ipynb already exists. Delete it or specify --overwrite" % fcomp[0])

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

    slidoc_opts = set(['embed', '_slidoc'])
    if cmd_args.combine:
        slidoc_opts.add('_slidoc_combine')

    base_mods_args = md2md.Args_obj.create_args(None, dest_dir=cmd_args.dest_dir,
                                                      image_dir=cmd_args.image_dir,
                                                      image_url=cmd_args.image_url,
                                                      images=cmd_args.images | slidoc_opts)
    slide_mods_dict = {'strip': 'concepts,extensions'}
    if 'answers' in cmd_args.strip:
        slide_mods_dict['strip'] += ',answers'
    if 'notes' in cmd_args.strip:
        slide_mods_dict['strip'] += ',notes'
    slide_mods_args = md2md.Args_obj.create_args(base_mods_args, **slide_mods_dict)

    nb_mods_dict = {'strip': 'concepts,extensions', 'site_url': cmd_args.site_url}
    if 'rule' in cmd_args.strip:
        nb_mods_dict['strip'] += ',rule'
    nb_converter_args = md2nb.Args_obj.create_args(None, **nb_mods_dict)
    index_id = make_chapter_id(len(cmd_args.file)+1)
    qindex_id = make_chapter_id(len(cmd_args.file)+2)
    back_to_contents = nav_link('BACK TO CONTENTS', cmd_args.site_url, cmd_args.toc, hash='#'+make_chapter_id(0),
                                combine=cmd_args.combine, classes=['slidoc-nosidebar'], printable=cmd_args.printable)+'<p></p>\n'

    flist = []
    all_concept_warnings = []
    outfile_buffer = []
    combined_html = []
    if cmd_args.combine:
        combined_html.append( '<div id="slidoc-sidebar-right-container" class="slidoc-sidebar-right-container">\n' )
        combined_html.append( '<div id="slidoc-sidebar-right-wrapper" class="slidoc-sidebar-right-wrapper">\n' )
    fprefix = None
    math_found = False
    for j, f in enumerate(cmd_args.file):
        fname = fnames[j]
        filepath = f.name
        md_text = f.read()
        f.close()
        if not cmd_args.combine:
            js_params['filename'] = fname

        file_head_html = css_html + ('\n<script>\n%s</script>\n' % templates['doc_include.js'].replace('JS_PARAMS_OBJ', json.dumps(js_params)) ) + gd_html


        base_parser = md2md.Parser(base_mods_args)
        slide_parser = md2md.Parser(slide_mods_args)
        md_text_modified = slide_parser.parse(md_text, filepath)
        md_text = base_parser.parse(md_text, filepath)

        if cmd_args.hide and 'hidden' in cmd_args.strip:
            md_text_modified = re.sub(r'(^|\n *\n--- *\n( *\n)+) {0,3}#{2,3}[^#][^\n]*'+cmd_args.hide+r'.*?(\n *\n--- *\n|$)', r'\1', md_text_modified, flags=re.DOTALL)

        prev_file = '' if j == 0                    else ('#'+make_chapter_id(j) if cmd_args.combine else fnames[j-1]+".html")
        next_file = '' if j >= len(cmd_args.file)-1 else ('#'+make_chapter_id(j+2) if cmd_args.combine else fnames[j+1]+".html")

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

        fheader, file_toc, renderer, md_html = md2html(md_text, filename=fname, cmd_args=cmd_args,
                                                               filenumber=filenumber, prev_file=prev_file,
                                                               next_file=next_file,
                                                               index_id=index_id, qindex_id=qindex_id)

        all_concept_warnings += renderer.concept_warnings
        outname = fname+".html"
        flist.append( (fname, outname, fheader, file_toc) )

        math_in_file = '$$' in md_text or ('`$' in md_text and '$`' in md_text)
        if math_in_file:
            math_found = True
        
        mid_params = {'math_js': math_inc if math_in_file else ''}
        mid_params.update(SYMS)
        if cmd_args.dry_run:
            print("Indexed ", outname+":", fheader, file=sys.stderr)
        else:
            md_prefix = chapter_prefix(j+1, 'slidoc-reg-chapter', hide=hide_chapters)
            md_suffix = '</div>\n'
            if cmd_args.combine:
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

            if cmd_args.slides:
                reveal_pars['reveal_title'] = fname
                reveal_pars['reveal_md'] = re.sub(r'(^|\n)\$\$(.+?)\$\$', r'`\1$$\2$$`', md_text_modified, flags=re.DOTALL)
                md2md.write_file(dest_dir+fname+"-slides.html", templates['reveal_template.html'] % reveal_pars)

            if cmd_args.notebook:
                md_parser = md2nb.MDParser(nb_converter_args)
                md2md.write_file(dest_dir+fname+".ipynb", md_parser.parse_cells(md_text_modified))

            if gd_hmac_key:
                user = 'admin'
                user_token = base64.b64encode(hmac.new(gd_hmac_key, user, hashlib.md5).digest())
                sheet_headers = ['name', 'id', 'Timestamp', 'revision',
                                 'questions', 'answers', 'primary_qconcepts', 'secondary_qconcepts']
                row_values = [fname, fname, None, js_params['sessionRevision'],
                                ','.join([x[0] for x in renderer.questions]),
                                '|'.join([(x[1] or '').replace('|','/') for x in renderer.questions]),
                                '; '.join(sort_caseless(list(renderer.qconcepts[0]))),
                                '; '.join(sort_caseless(list(renderer.qconcepts[1])))
                                ]
                post_params = {'sheet': 'sessions', 'user': user, 'token': user_token,
                               'headers': json.dumps(sheet_headers), 'row': json.dumps(row_values)
                               }
                print('slidoc: Updated remote spreadsheet:', http_post(js_params['gd_sheet_url'], post_params))
    
    if not cmd_args.dry_run:
        if not cmd_args.combine:
            for outname, outpath, head, tail in outfile_buffer:
                if tail:
                    # Update "missing" reference numbers and write output file
                    tail = Missing_ref_num_re.sub(Missing_ref_num, tail)
                    write_doc(outpath, head, tail)
            print('Created output files:', ', '.join(x[0] for x in outfile_buffer), file=sys.stderr)
        if cmd_args.slides:
            print('Created *-slides.html files', file=sys.stderr)
        if cmd_args.notebook:
            print('Created *.ipynb files', file=sys.stderr)

    if cmd_args.toc:
        if cmd_args.toc_header:
            header_insert = md2md.read_file(cmd_args.toc_header)
        else:
            header_insert = ''

        toc_html = []
        if cmd_args.index and (Global.first_tags or Global.first_qtags):
            toc_html.append(' '+nav_link('INDEX', cmd_args.site_url, cmd_args.index, hash='#'+index_id,
                                     combine=cmd_args.combine, printable=cmd_args.printable))
        toc_html.append('\n<ol class="slidoc-toc-list">\n' if 'sections' in cmd_args.strip else '\n<ul class="slidoc-toc-list" style="list-style-type: none;">\n')
        ifile = 0
        for fname, outname, fheader, file_toc in flist:
            ifile += 1
            chapter_id = make_chapter_id(ifile)
            slide_link = ''
            if not cmd_args.pace and cmd_args.slides:
                slide_link = ',&nbsp; <a href="%s%s" class="slidoc-clickable" target="_blank">%s</a>' % (cmd_args.site_url, fname+"-slides.html", 'slides')
            nb_link = ''
            if not cmd_args.pace and cmd_args.notebook and nb_site_url:
                nb_link = ',&nbsp; <a href="%s%s%s.ipynb" class="slidoc-clickable">%s</a>' % (md2nb.Nb_convert_url_prefix, nb_site_url[len('http://'):], fname, 'notebook')
            doc_link = nav_link('document', cmd_args.site_url, outname, hash='#'+chapter_id,
                                 combine=cmd_args.combine, printable=cmd_args.printable)

            if not cmd_args.pace:
                doc_link = nav_link('document', cmd_args.site_url, outname, hash='#'+chapter_id,
                                    combine=cmd_args.combine, printable=cmd_args.printable)
                toggle_link = '''<span class="slidoc-clickable slidoc-toc-chapters" onclick="Slidoc.idDisplay('%s-toc-sections');">%s</span>''' % (chapter_id, fheader)
            else:
                doc_link = nav_link('paced', cmd_args.site_url, outname, target='_blank')
                toggle_link = '<span class="slidoc-toc-chapters">%s</span>' % (fheader,)
            toc_html.append('<li>%s%s<span class="slidoc-nosidebar">(<em>%s%s%s</em>)</span></li>\n' % (toggle_link, SPACER6, doc_link, slide_link, nb_link))

            if not cmd_args.pace:
                f_toc_html = ('\n<div id="%s-toc-sections" class="slidoc-toc-sections" style="display: none;">' % chapter_id)+file_toc+'\n<p></p></div>'
                toc_html.append(f_toc_html)

        toc_html.append('</ol>\n' if 'sections' in cmd_args.strip else '</ul>\n')

        if cmd_args.slides:
            toc_html.append('<em>Note</em>: When viewing slides, type ? for help or click <a class="slidoc-clickable" target="_blank" href="https://github.com/hakimel/reveal.js/wiki/Keyboard-Shortcuts">here</a>.\nSome slides can be navigated vertically.')

        toc_html.append('<p></p><em>Document formatted by <a href="https://github.com/mitotic/slidoc" class="slidoc-clickable">slidoc</a>.</em><p></p>')

        if not cmd_args.dry_run:
            toc_insert = ''
            if not cmd_args.pace:
                toc_insert += click_span('+Contents', "Slidoc.hide(this,'slidoc-toc-sections');",
                                        classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-noprint'])
            if cmd_args.combine:
                toc_insert = click_span(SYMS['leftpair'], "Slidoc.sidebarDisplay();",
                                    classes=['slidoc-clickable-sym', 'slidoc-nosidebar', 'slidoc-noprint']) + SPACER2 + toc_insert
                toc_insert = click_span(SYMS['rightpair'], "Slidoc.sidebarDisplay();",
                                    classes=['slidoc-clickable-sym', 'slidoc-sidebaronly', 'slidoc-noprint']) + toc_insert
                toc_insert += SPACER3 + click_span('+All Chapters', "Slidoc.allDisplay(this);",
                                                  classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-noprint'])
            toc_output = chapter_prefix(0, 'slidoc-toc-container slidoc-noslide', hide=hide_chapters)+header_insert+Toc_header+toc_insert+'<br>'+''.join(toc_html)+'</div>\n'
            if cmd_args.combine:
                all_container_prefix  = '<div id="slidoc-all-container" class="slidoc-all-container">\n'
                left_container_prefix = '<div id="slidoc-left-container" class="slidoc-left-container">\n'
                left_container_suffix = '</div> <!--slidoc-left-container-->\n'
                combined_html = [all_container_prefix, left_container_prefix, toc_output, left_container_suffix] + combined_html
            else:
                md2md.write_file(dest_dir+cmd_args.toc, Html_header, head_html,
                                  mid_template % mid_params, body_prefix, toc_output, Html_footer)
                print("Created ToC in", cmd_args.toc, file=sys.stderr)

    xref_list = []
    if cmd_args.index and (Global.first_tags or Global.first_qtags):
        first_references, covered_first, index_html = make_index(Global.first_tags, Global.sec_tags, cmd_args.site_url, fprefix=fprefix, index_id=index_id, index_file='' if cmd_args.combine else cmd_args.index)
        if not cmd_args.dry_run:
            index_html= ' <b>CONCEPT</b>\n' + index_html
            if cmd_args.qindex:
                index_html = nav_link('QUESTION INDEX', cmd_args.site_url, cmd_args.qindex, hash='#'+qindex_id,
                                      combine=cmd_args.combine, printable=cmd_args.printable) + '<p></p>\n' + index_html
            if cmd_args.crossref:
                index_html = ('<a href="%s%s" class="slidoc-clickable">%s</a><p></p>\n' % (cmd_args.site_url, cmd_args.crossref, 'CROSS-REFERENCING')) + index_html

            index_output = chapter_prefix(len(cmd_args.file)+1, 'slidoc-index-container slidoc-noslide', hide=hide_chapters) + back_to_contents +'<p></p>' + index_html + '</div>\n'
            if cmd_args.combine:
                combined_html.append('<div class="slidoc-noslide">'+index_output+'</div>\n')
            else:
                md2md.write_file(dest_dir+cmd_args.index, index_output)
                print("Created index in", cmd_args.index, file=sys.stderr)

        if cmd_args.crossref:
            if cmd_args.toc:
                xref_list.append('<a href="%s%s" class="slidoc-clickable">%s</a><p></p>\n' % (cmd_args.site_url, cmd_args.combine or cmd_args.toc, 'BACK TO CONTENTS'))
            xref_list.append("<h3>Concepts cross-reference (file prefix: "+fprefix+")</h3><p></p>")
            xref_list.append("\n<b>Concepts -> files mapping:</b><br>")
            for tag in first_references:
                links = ['<a href="%s%s.html#%s" class="slidoc-clickable" target="_blank">%s</a>' % (cmd_args.site_url, slide_file, slide_id, slide_file[len(fprefix):] or slide_file) for slide_file, slide_id, slide_header in first_references[tag]]
                xref_list.append(("%-32s:" % tag)+', '.join(links)+'<br>')

            xref_list.append("<p></p><b>Primary concepts covered in each file:</b><br>")
            for fname, outname, fheader, file_toc in flist:
                clist = covered_first[fname].keys()
                clist.sort()
                tlist = []
                for ctag in clist:
                    slide_id, slide_header = covered_first[fname][ctag]
                    tlist.append( '<a href="%s%s.html#%s" class="slidoc-clickable" target="_blank">%s</a>' % (cmd_args.site_url, fname, slide_id, ctag) )
                xref_list.append(('%-24s:' % fname[len(fprefix):])+'; '.join(tlist)+'<br>')
            if all_concept_warnings:
                xref_list.append('<pre>\n'+'\n'.join(all_concept_warnings)+'\n</pre>')

    if cmd_args.qindex and Global.first_qtags:
        import itertools
        qout_list = []
        qout_list.append('<b>QUESTION CONCEPT</b>\n')
        first_references, covered_first, qindex_html = make_index(Global.first_qtags, Global.sec_qtags, cmd_args.site_url, fprefix=fprefix, index_id=qindex_id, index_file='' if cmd_args.combine else cmd_args.qindex)
        qout_list.append(qindex_html)

        qindex_output = chapter_prefix(len(cmd_args.file)+2, 'slidoc-qindex-container slidoc-noslide', hide=hide_chapters) + back_to_contents +'<p></p>' + ''.join(qout_list) + '</div>\n'
        if not cmd_args.dry_run:
            if cmd_args.combine:
                combined_html.append('<div class="slidoc-noslide">'+qindex_output+'</div>\n')
            else:
                md2md.write_file(dest_dir+cmd_args.qindex, qindex_output)
                print("Created qindex in", cmd_args.qindex, file=sys.stderr)

        if cmd_args.crossref:
            xref_list.append('\n\n<p><b>CONCEPT SUB-QUESTIONS</b><br>Sub-questions are questions that address combinatorial (improper) concept subsets of the original question concept set. (*) indicates a variant question that explores all the same concepts as the original question. Numeric superscript indicates the number of concepts in the sub-question shared with the original question.</p>\n')
            xref_list.append('<ul style="list-style-type: none;">\n')
            xref_list.append('<li><em><b>Original question:</b> Sub-question1, Sub-question2, ...</em></li>')
            for fname, slide_id, header, qnumber, concept_id in Global.questions.values():
                q_id = make_file_id(fname, slide_id)
                xref_list.append('<li><b>'+nav_link(make_q_label(fname, qnumber, fprefix)+': '+header,
                                               cmd_args.site_url, fname+'.html', hash='#'+slide_id,
                                               combine=cmd_args.combine, keep_hash=True, printable=cmd_args.printable)+'</b>: ')
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
                                                        cmd_args.site_url, sub_fname+'.html', hash='#'+sub_slide_id,
                                                        combine=cmd_args.combine, keep_hash=True, printable=cmd_args.printable)
                                                        + ('<sup>%s</sup>, ' % sub_num) )

                xref_list.append('</li>\n')
            xref_list.append('</ul>\n')

    if cmd_args.crossref:
        md2md.write_file(dest_dir+cmd_args.crossref, ''.join(xref_list))
        print("Created crossref in", cmd_args.crossref, file=sys.stderr)

    if cmd_args.combine:
        combined_html.append( '</div><!--slidoc-sidebar-right-wrapper-->\n' )
        combined_html.append( '</div><!--slidoc-sidebar-right-container-->\n' )
        if cmd_args.toc:
            combined_html.append( '</div><!--slidoc-sidebar-all-container-->\n' )

        comb_params = {'math_js': math_inc if math_found else ''}
        comb_params.update(SYMS)
        md2md.write_file(dest_dir+cmd_args.combine, Html_header, head_html,
                          mid_template % comb_params, body_prefix,
                         '\n'.join(combined_html), Html_footer)
        print('Created combined HTML file in '+cmd_args.combine, file=sys.stderr)
