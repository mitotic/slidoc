#!/usr/bin/env python

"""Slidoc is a Markdown based lecture management system.
Markdown filters with mistune, with support for MathJax, keyword indexing etc.
Use \[ ... \] for LaTeX-style block math
Use \( ... \) for LaTeX-style inline math
Used from markdown.py

See slidoc.md for examples and test cases in Markdown.

Usage examples:
./slidoc.py --hide='[Aa]nswer' --slides=black,zenburn,200% ../Lectures/course-lecture??.md

"""
# Copyright (c) R. Saravanan, IPython Development Team (for MarkdownWithMath)
# Distributed under the terms of the Modified BSD License.

from __future__ import print_function

import argparse
import BaseHTTPServer
import base64
import cStringIO
import os
import re
import shlex
import subprocess
import sys
import urllib
import urllib2

from collections import defaultdict, OrderedDict

import json
import mistune
import md2md
import md2nb
import pptx2md
import sliauth

try:
    import pygments
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name
    from pygments.formatters import HtmlFormatter
    from pygments.util import ClassNotFound
except ImportError:
    pass


from xml.etree import ElementTree

ADMINUSER_ID = 'admin'
TESTUSER_ID = '_test_user'

SETTINGS_SHEET = 'settings_slidoc'
INDEX_SHEET = 'sessions_slidoc'
ROSTER_SHEET = 'roster_slidoc'
SCORE_SHEET = 'scores_slidoc'
LOG_SHEET = 'slidoc_log'
MAX_QUERY = 500   # Maximum length of query string for concept chains
SPACER6 = '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
SPACER2 = '&nbsp;&nbsp;'
SPACER3 = '&nbsp;&nbsp;&nbsp;'

BASIC_PACE    = 1
QUESTION_PACE = 2
ADMIN_PACE    = 3

FUTURE_DATE = 'future'

SYMS = {'prev': '&#9668;', 'next': '&#9658;', 'return': '&#8617;', 'up': '&#9650;', 'down': '&#9660;', 'play': '&#9658;', 'stop': '&#9724;',
        'gear': '&#9881;', 'letters': '&#x1f520;', 'folder': '&#x1f4c1;', 'lightning': '&#9889;', 'pencil': '&#9998;', 'phone': '&#128241;', 'house': '&#8962;', 'circle': '&#9673;', 'square': '&#9635;',
        'threebars': '&#9776;', 'trigram': '&#9783;', 'leftpair': '&#8647;', 'rightpair': '&#8649;'}

def parse_number(s):
    if s.isdigit() or (s and s[0] in '+-' and s[1:].isdigit()):
        return int(s)
    try:
        return float(s)
    except Exception:
        return None
    
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

def add_to_index(primary_tags, sec_tags, p_tags, s_tags, filename, slide_id, header='', qconcepts=None):
    all_tags = p_tags + s_tags
    if not all_tags:
        return

    # Save tags in proper case (for index display)
    for tag in all_tags:
        if tag and tag not in Global.all_tags:
            Global.all_tags[tag.lower()] = tag

    # Convert all tags to lower case
    p_tags = [x.lower() for x in p_tags]
    s_tags = [x.lower() for x in s_tags]

    for tag in p_tags:
        # Primary tags
        if qconcepts:
            qconcepts[0].add(tag)

        if filename not in primary_tags[tag]:
            primary_tags[tag][filename] = []

        primary_tags[tag][filename].append( (slide_id, header) )

    for tag in s_tags:
        # Secondary tags
        if qconcepts:
            qconcepts[1].add(tag)

        if filename not in sec_tags[tag]:
            sec_tags[tag][filename] = []

        sec_tags[tag][filename].append( (slide_id, header) )


def make_index(primary_tags, sec_tags, site_url, question=False, fprefix='', index_id='', index_file=''):
    # index_file would be null string for combined file
    id_prefix = 'slidoc-qindex-' if question else 'slidoc-index-'
    covered_first = defaultdict(dict)
    first_references = OrderedDict()
    tag_list = list(set(primary_tags.keys()+sec_tags.keys()))
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
        
        for fname, ref_list in primary_tags[tag].items():
            # File includes this tag as primary tag
            if tag not in covered_first[fname]:
                covered_first[fname][tag] = ref_list[0]

        # Get sorted list of files with at least one reference (primary or secondary) to tag
        files = list(set(primary_tags[tag].keys()+sec_tags[tag].keys()))
        files.sort()

        first_ref_list = []
        tag_id = '%s-concept-%s' % (index_id, md2md.make_id_from_text(tag))
        if files:
            out_list.append('<li id="%s"><b>%s</b>:\n' % (tag_id, tag_str))

        tag_index = []
        for fname in files:
            f_index  = [(fname, slide_id, header, 1) for slide_id, header in primary_tags[tag].get(fname,[])]
            f_index += [(fname, slide_id, header, 2) for slide_id, header in sec_tags[tag].get(fname,[])]
            tag_index += f_index
            assert f_index, 'Expect at least one reference to tag in '+fname
            first_ref_list.append( f_index[0][:3] )

        tagid_list = [(fname[len(fprefix):] if index_file else '')+'#'+slide_id for fname, slide_id, header, reftype in tag_index]
        tagids_quoted = sliauth.safe_quote(';'.join(tagid_list))

        started = False
        j = 0
        for fname, slide_id, header, reftype in tag_index:
            j += 1
            if j > 1:
                out_list.append(', ')

            started = True
            query_str = '?tagindex=%d&tagconcept=%s&tagconceptref=%s&taglist=%s' % (j, sliauth.safe_quote(tag),
                                                sliauth.safe_quote(index_file+'#'+tag_id), tagids_quoted )
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
        
    out_list = ['<b id="%s">INDEX</b><blockquote>\n' % index_id] + ["&nbsp;&nbsp;".join(['<a href="#%s" class="slidoc-clickable">%s</a>' % (id_prefix+x.upper(), x.upper()) for x in first_letters])] + ['</blockquote>'] + out_list
    return first_references, covered_first, ''.join(out_list)


class Dummy(object):
    pass

Global = Dummy()

Global.primary_tags = defaultdict(OrderedDict)
Global.sec_tags = defaultdict(OrderedDict)
Global.primary_qtags = defaultdict(OrderedDict)
Global.sec_qtags = defaultdict(OrderedDict)

Global.all_tags = {}

Global.questions = OrderedDict()
Global.concept_questions = defaultdict(list)

Global.ref_tracker = dict()
Global.ref_counter = defaultdict(int)
Global.chapter_ref_counter = defaultdict(int)

Global.dup_ref_tracker = set()

class MathBlockGrammar(mistune.BlockGrammar):
    def_links = re.compile(  # RE-DEFINE TO INCLUDE SINGLE QUOTES
        r'^ *\[([^^\]]+)\]: *'  # [key]:
        r'<?([^\s>]+)>?'  # <link> or link
        r'''(?: +['"(]([^\n]+)['")])? *(?:\n+|$)'''
    )

    block_math =      re.compile(r'^\\\[(.*?)\\\]', re.DOTALL)
    latex_environment = re.compile(r'^\\begin\{([a-z]*\*?)\}(.*?)\\end\{\1\}',
                                                re.DOTALL)
    plugin_definition = re.compile(r'^PluginDef:\s*(\w+)\s*=\s*\{(.*?)\nPluginEndDef:\s*\1\s*(\n|$)',
                                                re.DOTALL)
    plugin_embed  =   re.compile(r'^PluginEmbed:\s*(\w+)\(([^\n]*)\)\s*\n(.*\n)*PluginEnd:\s*\1\s*(\n|$)',
                                                re.DOTALL)
    plugin_insert =   re.compile(r'^=(\w+)\(([^\n]*)\)\s*(\n\s*\n|\n$|$)')
    slidoc_header =   re.compile(r'^ {0,3}<!--(meldr|slidoc)-(\w[-\w]*)\s(.*?)-->\s*?(\n|$)')
    slidoc_answer =   re.compile(r'^ {0,3}(Answer):(.*?)(\n|$)')
    slidoc_concepts = re.compile(r'^ {0,3}(Concepts):(.*?)\n\s*(\n|$)', re.DOTALL)
    slidoc_hint   =   re.compile(r'^ {0,3}(Hint):\s*(-?\d+(\.\d*)?)\s*%\s+')
    slidoc_notes  =   re.compile(r'^ {0,3}(Notes):\s*?((?=\S)|\n)')
    slidoc_extra  =   re.compile(r'^ {0,3}(Extra):\s*?((?=\S)|\n)')
    minirule =        re.compile(r'^(--) *(?:\n+|$)')
    pause =           re.compile(r'^(\.\.\.) *(?:\n+|$)')

class MathBlockLexer(mistune.BlockLexer):
    def __init__(self, rules=None, **kwargs):
        if rules is None:
            rules = MathBlockGrammar()
        config = kwargs.get('config')
        slidoc_rules = ['block_math', 'latex_environment', 'plugin_definition', 'plugin_embed',  'plugin_insert', 'slidoc_header', 'slidoc_answer', 'slidoc_concepts', 'slidoc_hint', 'slidoc_notes', 'slidoc_extra', 'minirule']
        if config and 'incremental_slides' in config.features:
            slidoc_rules += ['pause']
        self.default_rules = slidoc_rules + mistune.BlockLexer.default_rules
        super(MathBlockLexer, self).__init__(rules, **kwargs)

    def parse_block_math(self, m):
        """Parse a \[math\] block"""
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

    def parse_plugin_definition(self, m):
        self.tokens.append({
            'type': 'plugin_definition',
            'name': m.group(1),
            'text': m.group(2)
        })

    def parse_plugin_embed(self, m):
         self.tokens.append({
            'type': 'slidoc_plugin',
            'name': m.group(1),
            'text': m.group(2)+'\n'+(m.group(3) or '')
        })

    def parse_plugin_insert(self, m):
         self.tokens.append({
            'type': 'slidoc_plugin',
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

    def parse_slidoc_hint(self, m):
         self.tokens.append({
            'type': 'slidoc_hint',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_notes(self, m):
         self.tokens.append({
            'type': 'slidoc_notes',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_extra(self, m):
         self.tokens.append({
            'type': 'slidoc_extra',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_hrule(self, m):
        self.tokens.append({'type': 'hrule', 'text': m.group(0).strip()})

    def parse_minirule(self, m):
        self.tokens.append({'type': 'minirule'})

    def parse_pause(self, m):
         self.tokens.append({
            'type': 'pause',
            'text': m.group(0)
        })

    
class MathInlineGrammar(mistune.InlineGrammar):
    slidoc_choice = re.compile(r"^ {0,3}([a-qA-Q])(\*)?\.\. +")
    block_math =    re.compile(r"^\\\[(.+?)\\\]", re.DOTALL)
    inline_math =   re.compile(r"^\\\((.+?)\\\)")
    tex_inline_math=re.compile(r"\$(?!\$)(.*?)([^\\\n\$])\$(?!\$)")
    inline_js =     re.compile(r"^`=(\w+)\.(\w+)\(\s*(\d*)\s*\)(;([^`\n]*))?`")
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
        slidoc_rules = ['slidoc_choice', 'block_math', 'inline_math', 'inline_js', 'internal_ref']
        if 'config' in renderer.options and 'tex_math' in renderer.options['config'].features:
            slidoc_rules += ['tex_inline_math']
        self.default_rules = slidoc_rules + mistune.InlineLexer.default_rules
        super(MathInlineLexer, self).__init__(renderer, rules, **kwargs)

    def output_slidoc_choice(self, m):
        return self.renderer.slidoc_choice(m.group(1).upper(), m.group(2) or '')

    def output_inline_math(self, m):
        return self.renderer.inline_math(m.group(1))

    def output_tex_inline_math(self, m):
        return self.renderer.inline_math(m.group(1)+m.group(2))

    def output_inline_js(self, m):
        return self.renderer.inline_js(m.group(1), m.group(2), m.group(3), m.group(5))

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
                    message('LINK-ERROR: Null link')
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
            message('REF-ERROR: Null reference')
            return None

        # Slidoc-specific hash reference handling
        ref_id = 'slidoc-ref-'+md2md.make_id_from_text(header_ref)
        ref_class = ''
        if ref_id in Global.ref_tracker:
            message('    ****REF-ERROR: Duplicate reference #%s (#%s)' % (ref_id, key))
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

    def output_plugin_definition(self):
        return self.renderer.plugin_definition(self.token['name'], self.token['text'])

    def output_slidoc_plugin(self):
        return self.renderer.slidoc_plugin(self.token['name'], self.token['text'])

    def output_slidoc_header(self):
        return self.renderer.slidoc_header(self.token['name'], self.token['text'])

    def output_slidoc_answer(self):
        return self.renderer.slidoc_answer(self.token['name'], self.token['text'])

    def output_slidoc_concepts(self):
        return self.renderer.slidoc_concepts(self.token['name'], self.token['text'])

    def output_slidoc_hint(self):
        return self.renderer.slidoc_hint(self.token['name'], self.token['text'])

    def output_slidoc_notes(self):
        return self.renderer.slidoc_notes(self.token['name'], self.token['text'])

    def output_slidoc_extra(self):
        return self.renderer.slidoc_extra(self.token['name'], self.token['text'])

    def output_hrule(self):
        return self.renderer.hrule(self.token['text'])

    def output_minirule(self):
        return self.renderer.minirule()

    def output_pause(self):
        return self.renderer.pause(self.token['text'])

class MarkdownWithSlidoc(MarkdownWithMath):
    def __init__(self, renderer, **kwargs):
        super(MarkdownWithSlidoc, self).__init__(renderer, **kwargs)
        self.incremental = 'incremental_slides' in self.renderer.options['config'].features

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

        classes =  'slidoc-single-column' if 'two_column' in self.renderer.options['config'].features else ''
        return self.renderer.slide_prefix(self.renderer.first_id, classes)+first_slide_pre+concept_chain(self.renderer.first_id, self.renderer.options['config'].site_url)+html+self.renderer.end_slide(last_slide=True)

    
class MathRenderer(mistune.Renderer):
    def hrule(self, text='---', implicit=False):
        return super(MathRenderer, self).hrule()

    def forward_link(self, ref_id):
        pass

    def add_ref_link(self, ref_id, num_label, key, ref_class):
        pass
    
    def block_math(self, text):
        return r'\[%s\]' % text

    def latex_environment(self, name, text):
        return r'\begin{%s}%s\end{%s}' % (name, text, name)

    def inline_math(self, text):
        return r'\(%s\)' % text

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

    plugin_content_template = '''<div id="%(pluginId)s-content" class="%(pluginLabel)s-content slidoc-plugin-content slidoc-pluginonly" data-plugin="%(pluginName)s" data-number="%(pluginNumber)s" data-args="%(pluginInitArgs)s" data-button="%(pluginButton)s" data-slide-id="%(pluginSlideId)s">%(pluginContent)s</div><!--%(pluginId)s-content-->'''

    plugin_body_template = '''<div id="%(pluginId)s-body" class="%(pluginLabel)s-body slidoc-plugin-body slidoc-pluginonly">%(pluginBodyDef)s</div><!--%(pluginId)s-body-->'''

    # Templates: {'sid': slide_id, 'qno': question_number, 'inp_type': 'text'/'number', 'ansinput_style': , 'ansarea_style': }
    ansprefix_template = '''<span id="%(sid)s-answer-prefix" class="%(disabled)s" data-qnumber="%(qno)d">Answer:</span>'''
    answer_template = '''
  <span id="%(sid)s-answer-prefix" class="slidoc-answeredonly %(disabled)s" data-qnumber="%(qno)d">Answer:</span>
  <button id="%(sid)s-answer-click" class="slidoc-clickable slidoc-button slidoc-answer-button slidoc-noadmin slidoc-noanswered slidoc-noprint %(disabled)s" onclick="Slidoc.answerClick(this, '%(sid)s');">Answer</button>
  <input id="%(sid)s-answer-input" type="%(inp_type)s" class="slidoc-answer-input slidoc-answer-box slidoc-noadmin slidoc-noanswered slidoc-noprint slidoc-noplugin %(disabled)s" onkeydown="Slidoc.inputKeyDown(event);"></input>

  <span class="slidoc-answer-span slidoc-answeredonly">
    <span id="%(sid)s-response-span"></span>
    <span id="%(sid)s-correct-mark" class="slidoc-correct-answer"></span>
    <span id="%(sid)s-partcorrect-mark" class="slidoc-partcorrect-answer"></span>
    <span id="%(sid)s-wrong-mark" class="slidoc-wrong-answer"></span>
    <span id="%(sid)s-any-mark" class="slidoc-any-answer"></span>
    <span id="%(sid)s-answer-correct" class="slidoc-answer-correct slidoc-correct-answer"></span>
  </span>
  %(explain)s
  <textarea id="%(sid)s-answer-textarea" name="textarea" class="slidoc-answer-textarea slidoc-answer-box slidoc-noadmin slidoc-noanswered slidoc-noprint slidoc-noplugin %(disabled)s" cols="60" rows="5"></textarea>
'''                

    grading_template = '''
  <div id="%(sid)s-grade-element" class="slidoc-grade-element slidoc-answeredonly %(zero_gwt)s">
    <button id="%(sid)s-gstart-click" class="slidoc-clickable slidoc-button slidoc-gstart-click slidoc-grade-button slidoc-adminonly slidoc-nograding" onclick="Slidoc.gradeClick(this, '%(sid)s');">Start</button>
    <button id="%(sid)s-grade-click" class="slidoc-clickable slidoc-button slidoc-grade-click slidoc-grade-button slidoc-adminonly slidoc-gradingonly" onclick="Slidoc.gradeClick(this,'%(sid)s');">Save</button>
    <span id="%(sid)s-gradeprefix" class="slidoc-grade slidoc-gradeprefix slidoc-admin-graded"><em>Grade:</em></span>
    <input id="%(sid)s-grade-input" type="number" class="slidoc-grade-input slidoc-adminonly slidoc-gradingonly" onkeydown="Slidoc.inputKeyDown(event);"></input>
    <span id="%(sid)s-grade-content" class="slidoc-grade slidoc-grade-content slidoc-nograding"></span>
    <span id="%(sid)s-gradesuffix" class="slidoc-grade slidoc-gradesuffix slidoc-admin-graded">%(gweight)s</span>
    <button id="%(sid)s-grademax" class="slidoc-clickable slidoc-button slidoc-grademax slidoc-gradingonly" onclick="Slidoc.gradeMax(this,'%(sid)s','%(gweight)s');">&#x2714;</button>
  </div>
'''
    comments_template_a = '''
  <textarea id="%(sid)s-comments-textarea" name="textarea" class="slidoc-comments-textarea slidoc-gradingonly" cols="60" rows="7" ></textarea>
  <div id="%(sid)s-comments-suggestions" class="slidoc-comments-suggestions" style="display: none;"></div>
'''
    render_template = '''
  <button id="%(sid)s-render-button" class="slidoc-clickable slidoc-button slidoc-render-button" onclick="Slidoc.renderText(this,'%(sid)s');">Render</button>
'''
    quote_template = '''
  <button id="%(sid)s-quote-button" class="slidoc-clickable slidoc-button slidoc-quote-button slidoc-gradingonly" onclick="Slidoc.quoteText(this,'%(sid)s');">Quote</button>
'''
    comments_template_b = '''              
<div id="%(sid)s-comments" class="slidoc-comments slidoc-comments-element slidoc-answeredonly slidoc-admin-graded"><em>Comments:</em>
  <div id="%(sid)s-comments-content" class="slidoc-comments-content"></div>
</div>
'''
    response_div_template = '''  <div id="%(sid)s-response-div" class="slidoc-response-div slidoc-noplugin"></div>\n'''
    response_pre_template = '''  <pre id="%(sid)s-response-div" class="slidoc-response-div slidoc-noplugin"></pre>\n'''

    # Suffixes of input/textarea elements that need to be cleaned up
    input_suffixes = ['-answer-input', '-answer-textarea', '-grade-input', '-comments-textarea']

    # Suffixes of span/div/pre elements that need to be cleaned up
    content_suffixes = ['-response-span', '-correct-mark', '-partcorrect-mark', '-wrong-mark', '-any-mark', '-answer-correct',
                        '-grade-content','-comments-content', '-response-div', '-choice-shuffle'] 
    
    def __init__(self, **kwargs):
        super(SlidocRenderer, self).__init__(**kwargs)
        self.file_header = ''
        self.header_list = []
        self.concept_warnings = []
        self.hide_end = None
        self.hint_end = None
        self.notes_end = None
        self.extra_end = None
        self.section_number = 0
        self.untitled_number = 0
        self.qtypes = []
        self.questions = []
        self.question_concepts = []
        self.cum_weights = []
        self.cum_gweights = []
        self.grade_fields = []
        self.max_fields = []
        self.qforward = defaultdict(list)
        self.qconcepts = [set(),set()]
        self.sheet_attributes = {'shareAnswers': {}, 'hints': defaultdict(list)}
        self.slide_number = 0

        self._new_slide()
        self.first_id = self.get_slide_id()
        self.index_id = ''                     # Set by render()
        self.qindex_id = ''                    # Set by render
        self.block_input_counter = 0
        self.block_test_counter = 0
        self.block_output_counter = 0
        self.render_markdown = False
        self.plugin_number = 0
        self.plugin_defs = {}
        self.plugin_tops = []
        self.plugin_loads = set()
        self.plugin_embeds = set()
        self.load_python = False

    def _new_slide(self):
        self.slide_number += 1
        self.qtypes.append('')
        self.choices = None
        self.choice_end = None
        self.choice_questions = 0
        self.cur_qtype = ''
        self.cur_header = ''
        self.untitled_header = ''
        self.slide_concepts = []
        self.first_para = True
        self.incremental_level = 0
        self.incremental_list = False
        self.incremental_pause = False
        self.slide_block_test = []
        self.slide_block_output = []
        self.slide_forward_links = []
        self.slide_plugin_refs = set()
        self.slide_plugin_embeds = set()

    def list_incremental(self, activate):
        self.incremental_list = activate
    
    def forward_link(self, ref_id):
        self.slide_forward_links.append(ref_id)

    def add_ref_link(self, ref_id, num_label, key, ref_class):
        Global.ref_tracker[ref_id] = (num_label, key, ref_class)
        if ref_id in self.qforward:
            last_qno = len(self.cum_weights)  # cum_weights are only appended at end of slide
            for qno in self.qforward.pop(ref_id):
                skipped = last_qno - qno
                skip_weight = self.cum_weights[-1] - self.cum_weights[qno-1]
                skip_gweight = self.cum_gweights[-1] - self.cum_gweights[qno-1]
                if not skip_gweight:
                    # (slide_number, number of questions skipped, weight of questions skipped, class for forward link)
                    self.questions[qno-1]['skip'] = (self.slide_number, skipped, skip_weight, ref_id+'-forward-link')
                else:
                    message("    ****LINK-ERROR: %s: Forward link %s to slide %s skips graded questions; ignored." % (self.options["filename"], ref_id, self.slide_number))

    def inline_js(self, plugin_name, action, arg, text):
        js_func = plugin_name + '.' + action
        if action in ('answerSave', 'buttonClick', 'disable', 'display', 'enterSlide', 'expect', 'incrementSlide', 'init', 'initGlobal', 'initSetup', 'leaveSlide', 'response'):
            message("    ****PLUGIN-ERROR: %s: Disallowed inline plugin action `=%s()` in slide %s" % (self.options["filename"], js_func, self.slide_number))
            
        if 'inline_js' in self.options['config'].strip:
            return '<code>%s</code>' % (mistune.escape('='+js_func+'()' if text is None else text))

        self.plugin_loads.add(plugin_name)
        self.slide_plugin_refs.add(plugin_name)

        slide_id = self.get_slide_id()
        classes = 'slidoc-inline-js'
        if slide_id:
            classes += ' slidoc-inline-js-in-'+slide_id
        return '<code class="%s" data-slidoc-js-function="%s" data-slidoc-js-argument="%s">%s</code>' % (classes, js_func, arg or '', mistune.escape('='+js_func+'()' if text is None else text))

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

    def end_hint(self):
        s = self.hint_end or ''
        self.hint_end = None
        return s

    def end_notes(self):
        s = self.notes_end or ''
        self.notes_end = None
        return s

    def end_extra(self):
        s = self.extra_end or ''
        self.extra_end = None
        return s

    def minirule(self):
        """Treat minirule as a linebreak"""
        return '<br>\n'

    def pause(self, text):
        """Pause in display"""
        if 'incremental_slides' in self.options['config'].features:
            self.incremental_pause = True
            self.incremental_level += 1
            return ''
        else:
            return text

    def slide_prefix(self, slide_id, classes=''):
        chapter_id, sep, _ = slide_id.partition('-')
        # Slides need to be unhidden in Javascript
        return '\n<section id="%s" class="slidoc-slide %s-slide %s" style="display: none;"> <!--slide start-->\n' % (slide_id, chapter_id, classes)

    def hrule(self, text='---', implicit=False):
        """Rendering method for ``<hr>`` tag."""
        if self.choice_end:
            prefix = self.choice_end

        if implicit or 'rule' in self.options['config'].strip or (self.hide_end and 'hidden' in self.options['config'].strip):
            rule_html = ''
        elif self.options.get('use_xhtml'):
            rule_html = '<hr class="slidoc-hrule slidoc-noslide slidoc-noprint slidoc-single-columnonly"/>\n'
        else:
            rule_html = '<hr class="slidoc-hrule slidoc-noslide slidoc-noprint slidoc-single-columnonly">\n'

        end_html = self.end_slide(rule_html)
        self._new_slide()
        new_slide_id = self.get_slide_id()

        classes = []
        if text.startswith('----'):
            if 'slide_break_page' not in self.options['config'].features:
                classes.append('slidoc-page-break-before')
            if 'two_column' in self.options['config'].features:
                classes.append('slidoc-single-column')

        return end_html + self.slide_prefix(new_slide_id, ' '.join(classes)) + concept_chain(new_slide_id, self.options['config'].site_url)

    def end_slide(self, suffix_html='', last_slide=False):
        if not self.slide_plugin_refs.issubset(self.slide_plugin_embeds):
            message("    ****PLUGIN-ERROR: %s: Missing plugins %s in slide %s." % (self.options["filename"], list(self.slide_plugin_refs.difference(self.slide_plugin_embeds)), self.slide_number))

        prefix_html = self.end_extra()+self.end_hint()  # Hints/Notes will be ignored after Extra:
        if self.qtypes[-1]:
            # Question slide
            self.question_concepts.append(self.slide_concepts)

            if self.options['config'].pace and self.slide_forward_links:
                # Handle forward link in current question
                self.qforward[self.slide_forward_links[0]].append(len(self.questions))
                if len(self.slide_forward_links) > 1:
                    message("    ****ANSWER-ERROR: %s: Multiple forward links in slide %s. Only first link (%s) recognized." % (self.options["filename"], self.slide_number, self.slide_forward_links[0]))

        if last_slide and self.options['config'].pace:
            # Last paced slide
            if self.qtypes[-1]:
                abort('***ERROR*** Last slide cannot be a question slide for paced mode in session '+self.options["filename"])

            if self.options['config'].pace == BASIC_PACE and 'Submit' not in self.plugin_loads:
                # Submit button not previously included in this slide or earlier slides
                prefix_html += self.embed_plugin_body('Submit', self.get_slide_id())

        ###if self.cur_qtype and not self.qtypes[-1]:
        ###    message("    ****ANSWER-ERROR: %s: 'Answer:' missing for %s question in slide %s" % (self.options["filename"], self.cur_qtype, self.slide_number))

        return prefix_html+self.end_notes()+self.end_hide()+suffix_html+('</section><!--%s-->\n' % ('last slide end' if last_slide else 'slide end'))

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
                self.untitled_header = '%d. ' % self.untitled_number
                text = self.untitled_header + text
                if self.questions and len(self.questions)+1 != self.untitled_number:
                    abort("    ****QUESTION-ERROR: %s: Untitled number %d out of sync with question number %d in slide %s. Add explicit headers to non-question slides to avoid numbering" % (self.options["filename"], self.untitled_number, len(self.questions)+1, self.slide_number))
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

    def get_header_prefix(self):
        if 'untitled_number' in self.options['config'].features:
            return self.untitled_header

        if 'sections' in self.options['config'].strip:
            return ''

        if 'chapters' in self.options['config'].strip:
            return '%d ' % self.section_number
        else:
            return  '%d.%d ' % (self.options['filenumber'], self.section_number)
                    
    def header(self, text, level, raw=None):
        """Handle markdown headings
        """
        if self.notes_end is None:
            html = super(SlidocRenderer, self).header(text.strip('#'), level, raw=raw)
            try:
                hdr = ElementTree.fromstring(html)
            except Exception:
                # failed to parse, just return it unmodified
                return html
        else:
            # Header in Notes
            hdr = ElementTree.Element('p', {})
            hdr.text = text.strip('#')

        prev_slide_end = ''
        if self.cur_header and level <= 2:
            # Implicit horizontal rule before Level 1/2 header
            prev_slide_end = self.hrule(implicit=True)
        
        hdr_class = (hdr.get('class')+' ' if hdr.get('class') else '') + ('slidoc-referable-in-%s' % self.get_slide_id()) + (' slidoc-header %s-header' % self.get_slide_id())
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
                    message('REF-WARNING: Use only alphanumeric chars, hyphens and dots in references: %s' % text)
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
            if ref_id not in Global.dup_ref_tracker:
                Global.dup_ref_tracker.add(ref_id)
                message('    ****REF-ERROR: %s: Duplicate reference #%s in slide %s' % (self.options["filename"], header_ref, self.slide_number))
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
        if self.slide_number == 1 and level <= 2 and not self.file_header:
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
                hdr_prefix = self.get_header_prefix()
                self.cur_header = (hdr_prefix + text.strip('#')).strip()
                if self.cur_header:
                    self.header_list.append( (self.get_slide_id(), self.cur_header) )
                if 'sections' not in self.options['config'].strip:
                    clickable_secnum = True

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

    def slidoc_choice(self, name, star):
        value = name if star else ''
        if self.notes_end:
            # Choice notes
            return '''</p><p class="slidoc-choice-notes %s-choice-notes-%s" style="display: none;">''' % (self.get_slide_id(), name.upper())

        alt_choice = False
        if name == 'Q':
            if self.choice_questions == 0:
                self.choice_questions = 1
            elif self.choice_questions == 1:
                self.choice_questions = 2
                alt_choice = True
            else:
                return name+'..'
        elif not self.choices:
            if name != 'A':
                return name+'..'
            self.choices = [ [value, alt_choice] ]
        else:
            if ord(name) == ord('A')+len(self.choices):
                self.choices.append([value, alt_choice])
            elif ord(name) == ord('A')+len(self.choices)-1 and not self.choices[-1][1]:
                # Alternative choice
                alt_choice = True
                self.choices[-1][0] = self.choices[-1][0] or value
                self.choices[-1][1] = alt_choice
            else:
                abort("    ****CHOICE-ERROR: %s: Out of sequence choice %s in slide %s" % (self.options["filename"], name, self.slide_number))
                return name+'..'

        randomizing = 'randomize_choice' in self.options['config'].features
        if alt_choice and not randomizing:
            message("    ****CHOICE-WARNING: %s: Specify --features=randomize_choice to handle alternative choices in slide %s" % (self.options["filename"], self.slide_number))

        params = {'id': self.get_slide_id(), 'opt': name, 'alt': '-alt' if alt_choice else ''}
            
        prefix = ''
        if not self.choice_end:
            prefix += '</p><blockquote id="%(id)s-choice-block" data-shuffle=""><div id="%(id)s-chart-header" class="slidoc-chart-header" style="display: none;"></div><p>\n'
            self.choice_end = '</blockquote><div id="%s-choice-shuffle"></div>\n' % self.get_slide_id()

        hide_answer = self.options['config'].pace or 'show_correct' not in self.options['config'].features
        if name != 'Q' and hide_answer:
            prefix += '''<span class="slidoc-chart-box %(id)s-chart-box" style="display: none;"><span id="%(id)s-chartbar-%(opt)s" class="slidoc-chart-bar" onclick="Slidoc.PluginMethod('Share', '%(id)s', 'shareExplain', '%(opt)s');" style="width: 0%%;"></span></span>\n'''

        if name == 'Q':
            return (prefix+'''<span id="%(id)s-choice-question%(alt)s" class="slidoc-choice-question%(alt)s" ></span>''') % params
        elif hide_answer:
            return (prefix+'''<span id="%(id)s-choice-%(opt)s%(alt)s" data-choice="%(opt)s" class="slidoc-clickable %(id)s-choice %(id)s-choice-elem%(alt)s slidoc-choice slidoc-choice-elem%(alt)s" onclick="Slidoc.choiceClick(this, '%(id)s');"+'">%(opt)s</span>. ''') % params
        else:
            return (prefix+'''<span id="%(id)s-choice-%(opt)s" class="%(id)s-choice slidoc-choice">%(opt)s</span>. ''') % params

    
    def plugin_definition(self, name, text):
        _, self.plugin_defs[name] = parse_plugin(name+' = {'+text)
        return ''

    def embed_plugin_body(self, plugin_name, slide_id, args='', content=''):
        if plugin_name in self.slide_plugin_embeds:
            abort('ERROR Multiple instances of plugin '+plugin_name+' in slide '+str(self.slide_number))
        self.slide_plugin_embeds.add(plugin_name)
        self.plugin_embeds.add(plugin_name)

        self.plugin_number += 1

        plugin_def_name = plugin_name
        if plugin_def_name not in self.plugin_defs and plugin_def_name not in self.options['plugin_defs']:
            # Look for plugin definition with trailing digit stripped out from name
            if plugin_name[-1].isdigit():
                plugin_def_name = plugin_name[:-1]
            if plugin_def_name not in self.plugin_defs and plugin_def_name not in self.options['plugin_defs']:
                abort('ERROR Plugin '+plugin_name+' not defined!')
                return ''

        plugin_def = self.plugin_defs.get(plugin_def_name) or self.options['plugin_defs'][plugin_def_name]

        plugin_params = {'pluginName': plugin_name,
                         'pluginLabel': 'slidoc-plugin-'+plugin_name,
                         'pluginId': slide_id+'-plugin-'+plugin_name,
                         'pluginInitArgs': sliauth.safe_quote(args),
                         'pluginNumber': self.plugin_number,
                         'pluginButton': sliauth.safe_quote(plugin_def.get('Button', ''))}

        if plugin_def_name not in self.plugin_loads:
            self.plugin_loads.add(plugin_def_name)
            plugin_top = plugin_def.get('Top', '').strip()
            if plugin_top:
                self.plugin_tops.append( (plugin_top % {}) % plugin_params ) # Unescape the %% before substituting

        # Add slide-specific plugin params
        plugin_params['pluginSlideId'] = slide_id
        tem_params = plugin_params.copy()
        try:
            tem_params['pluginBodyDef'] = plugin_def.get('Body', '') % plugin_params
        except Exception, err:
            abort('ERROR Template formatting error in Body for plugin %s in slide %s: %s' % (plugin_name, self.slide_number, err))
        body_div = self.plugin_body_template % tem_params
        if '%(pluginBody)s' in content:
            # Insert plugin body at the right place within the HTML content
            try:
                plugin_params['pluginContent'] = content.replace('%(pluginBody)s', body_div, 1) % plugin_params
            except Exception, err:
                abort('ERROR Template formatting error for plugin %s in slide %s: %s' % (plugin_name, self.slide_number, err))
        else:
            # Save content as raw (pre) text (for plugin processing); insert plugin body after raw content
            if content:
                content = ('<pre id="%(pluginId)s-raw-content">' % plugin_params) + mistune.escape(content) + '</pre>'
            plugin_params['pluginContent'] = content + (body_div % plugin_params)
        return self.plugin_content_template % plugin_params

    def slidoc_plugin(self, name, text):
        args, sep, content = text.partition('\n')
        return self.embed_plugin_body(name, self.get_slide_id(), args=args.strip(), content=content)

    def slidoc_answer(self, name, text):
        if self.qtypes[-1]:
            # Ignore multiple answers
            return ''

        html_prefix = ''
        if self.choice_end:
            html_prefix = self.choice_end
            self.choice_end = ''

        all_options = ('explain', 'retry', 'share', 'team', 'vote', 'weight')

        opt_comps = [x.strip() for x in text.split(';')]
        text = opt_comps[0]
        if text and (text.split('=')[0].strip() in all_options):
             abort("    ****ANSWER-ERROR: %s: 'Answer: %s ...' is not a valid answer type. Insert semicolon before answer option in slide %s" % (self.options["filename"], text, self.slide_number))
             return

        weight_answer = ''
        noshuffle = 0          # If n > 0, do not randomlly shuffle last n choices
        retry_counts = [0, 0]  # Retry count, retry delay
        opt_values = { 'disabled': ('yes',),               # Disable answering for this question
                       'explain': ('text', 'markdown'),    # Require text/markdown explanation
                       'share': ('after_due_date', 'after_answering', 'after_grading'),
                       'team': ('response', 'setup'),
                       'vote': ('show_completed', 'show_live') }
        if self.options['config'].pace == ADMIN_PACE:
            # Change default share value for admin pace
            opt_values['share'] = ('after_answering', 'after_due_date', 'after_grading')
        answer_opts = { 'disabled': '', 'explain': '', 'participation': '', 'share': '', 'team': '', 'vote': ''}
        for opt in opt_comps[1:]:
            num_match = re.match(r'^(noshuffle|participation|retry|weight)\s*=\s*((\d+(.\d+)?)(\s*,\s*\d+(.\d+)?)*)\s*$', opt)
            if num_match:
                try:
                    if num_match.group(1) == 'weight':
                        weight_answer = num_match.group(2).strip()
                    elif num_match.group(1) == 'noshuffle':
                        noshuffle = abs(int(num_match.group(2).strip()))
                    elif num_match.group(1) == 'retry':
                        num_comps = [int(x.strip() or '0') for x in num_match.group(2).strip().split(',')]
                        retry_counts = [num_comps[0], 0]
                        if len(num_comps) > 1 and num_comps[0]:
                            retry_counts[1] = num_comps[1]
                    else:
                        answer_opts['participation'] = float(num_match.group(2).strip())
                except Exception, excp:
                    abort("    ****ANSWER-ERROR: %s: 'Answer: ... %s=%s' is not a valid option; expecting numeric value for slide %s" % (self.options["filename"], num_match.group(1), num_match.group(2), self.slide_number))
            elif opt == 'retry':
                retry_counts = [1, 0]
            else:
                option_match = re.match(r'^(disabled|explain|share|team|vote)(=(\w+))?$', opt)
                if option_match:
                    opt_name = option_match.group(1)
                    if option_match.group(3) and option_match.group(3) not in opt_values[opt_name]:
                        abort("    ****ANSWER-ERROR: %s: 'Answer: ... %s=%s' is not a valid option; expecting %s for slide %s" % (self.options["filename"], opt_name, option_match.group(3), '/'.join(opt_values[opt_name]), self.slide_number))
                        return ''

                    answer_opts[opt_name] = option_match.group(3) or opt_values[opt_name][0]
                else:
                    abort("    ****ANSWER-ERROR: %s: 'Answer: ... %s' is not a valid answer option for slide %s" % (self.options["filename"], opt, self.slide_number))

        if not answer_opts['share']:
            if (answer_opts['vote'] or 'share_all' in self.options['config'].features):
                answer_opts['share'] = opt_values['share'][0]
            elif 'share_answers' in self.options['config'].features:
                answer_opts['share'] = opt_values['share'][-1]

        if answer_opts['share'] and 'delay_answers' in self.options['config'].features:
            answer_opts['share'] = opt_values['share'][2]

        if not answer_opts['disabled'] and 'disable_answering' in self.options['config'].features:
            answer_opts['disabled'] = opt_values['disabled'][0]
            
        slide_id = self.get_slide_id()
        plugin_name = ''
        plugin_action = ''
        plugin_arg = ''
        plugin_match = re.match(r'^(.*)=\s*(\w+)\.(expect|response)\(\s*(\d*)\s*\)$', text)
        if plugin_match:
            text = plugin_match.group(1).strip()
            plugin_name = plugin_match.group(2)
            plugin_action = plugin_match.group(3)
            plugin_arg = plugin_match.group(4) or ''

        qtype = ''
        num_match = re.match(r'^([-+/\d\.eE\s%]+)$', text)
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
            if isfloat(ans) and (not error or isfloat(error[:-1] if error.endswith('%') else error)):
                qtype = 'number'
                text = ans + (' +/- '+error if error else '')
            else:
                message("    ****ANSWER-ERROR: %s: 'Answer: %s' is not a valid numeric answer; expect 'ans +/- err' in slide %s" % (self.options["filename"], text, self.slide_number))

        elif text.lower() in ('choice', 'multichoice', 'number', 'text', 'text/x-code', 'text/markdown', 'text/multiline', 'point', 'line'):
            # Unspecified answer
            qtype = text.lower()
            text = ''
        elif not plugin_name:
            tem_name, _, tem_args = text.partition('/')
            tem_name = tem_name.strip()
            tem_args = tem_args.strip()

            arg_pattern = None
            if tem_name in self.plugin_defs:
                arg_pattern = self.plugin_defs[tem_name].get('ArgPattern', '')
            elif tem_name in self.options['plugin_defs']:
                arg_pattern = self.options['plugin_defs'][tem_name].get('ArgPattern', '')

            if arg_pattern is not None:
                plugin_name = tem_name
                plugin_action = 'response'
                if not arg_pattern:
                    # Ignore argument
                    qtype = plugin_name
                    text = ''
                elif re.match(arg_pattern, tem_args):
                    qtype = plugin_name + '/' + tem_args
                    text = ''
                else:
                    abort("    ****ANSWER-ERROR: %s: 'Answer: %s' invalid arguments for plugin %s, expecting %s; in slide %s" % (self.options["filename"], text, plugin_name, arg_pattern, self.slide_number))


        if plugin_name:
            if 'inline_js' in self.options['config'].strip and plugin_action == 'expect':
                plugin_name = ''
                plugin_action = ''
            elif plugin_name not in self.slide_plugin_embeds:
                html_prefix += self.embed_plugin_body(plugin_name, slide_id)

        html_suffix = ''
        if answer_opts['share']:
            if 'Share' not in self.slide_plugin_embeds:
                html_suffix += self.embed_plugin_body('Share', slide_id)

            if self.options['config'].pace == ADMIN_PACE and 'Timer' not in self.slide_plugin_embeds:
                html_suffix += self.embed_plugin_body('Timer', slide_id)
                
        if self.choices:
            if not qtype or qtype in ('choice', 'multichoice'):
                # Correct choice(s)
                choices_str = ''.join(x[0] for x in self.choices)
                if choices_str:
                    text = choices_str
                else:
                    text = ''.join(x for x in text if ord(x) >= ord('A') and ord(x)-ord('A') < len(self.choices))

                if qtype == 'choice':
                    # Multiple answers for choice are allowed with a warning (to fix grading problems)
                    if len(text) > 1:
                        message("    ****ANSWER-WARNING: %s: 'Answer: %s' expect single choice in slide %s" % (self.options["filename"], text, self.slide_number))
                elif not qtype:
                    qtype = 'multichoice' if len(text) > 1 else 'choice'
            else:
                # Ignore choice options
                self.choices = None
                
        if not self.cur_qtype:
            # Default answer type is 'text'
            self.cur_qtype = qtype or 'text'

        elif qtype and qtype != self.cur_qtype:
            message("    ****ANSWER-ERROR: %s: 'Answer: %s' line ignored; expected 'Answer: %s' in slide %s" % (self.options["filename"], qtype, self.cur_qtype, self.slide_number))

        if self.cur_qtype == 'Code/python':
            self.load_python = True

        # Handle correct answer
        if self.cur_qtype in ('choice', 'multichoice'):
            correct_text = text.upper()
            correct_html = correct_text
        else:
            correct_text = text
            correct_html = ''
            if text and not plugin_name:
                try:
                    # Render any Markdown in correct answer
                    correct_html = MarkdownWithMath(renderer=MathRenderer(escape=False)).render(text) if text else ''
                    corr_elem = ElementTree.fromstring(correct_html)
                    correct_text = html2text(corr_elem).strip()
                    correct_html = correct_html[3:-5]
                except Exception, excp:
                    import traceback
                    traceback.print_exc()
                    message("    ****ANSWER-ERROR: %s: 'Answer: %s' in slide %s does not parse properly as html: %s'" % (self.options["filename"], text, self.slide_number, excp))

        multiline_answer = self.cur_qtype.startswith('text/')
        if multiline_answer:
            answer_opts['explain'] = ''      # Explain not compatible with textarea input

        self.qtypes[-1] = self.cur_qtype
        self.questions.append({})
        qnumber = len(self.questions)
        if plugin_name:
            correct_val = '=' + plugin_name + '.' + plugin_action + '(' + plugin_arg + ')'
            if correct_text:
                correct_val = correct_text + correct_val
        else:
            correct_val = correct_text

        self.questions[-1].update(qnumber=qnumber, qtype=self.cur_qtype, slide=self.slide_number, correct=correct_val,
                                  weight=1)

        if answer_opts['disabled']:
            self.questions[-1].update(disabled=answer_opts['disabled'])
        if answer_opts['explain']:
            self.questions[-1].update(explain=answer_opts['explain'])
        if answer_opts['participation']:
            self.questions[-1].update(participation=answer_opts['participation'])
        if answer_opts['share']:
            self.questions[-1].update(share=answer_opts['share'])
        if answer_opts['team']:
            self.questions[-1].update(team=answer_opts['team'])
        if answer_opts['vote']:
            self.questions[-1].update(vote=answer_opts['vote'])

        if self.cur_qtype in ('choice', 'multichoice'):
            self.questions[-1].update(choices=len(self.choices))
        if noshuffle:
            self.questions[-1].update(noshuffle=noshuffle)
        if retry_counts[0]:
            self.questions[-1].update(retry=retry_counts)
        if correct_html and correct_html != correct_text:
            self.questions[-1].update(html=correct_html)
        if self.block_input_counter:
            self.questions[-1].update(input=self.block_input_counter)
        if self.slide_block_test:
            self.questions[-1].update(test=self.slide_block_test)
        if self.slide_block_output:
            self.questions[-1].update(output=self.slide_block_output)

        if answer_opts['share']:
            self.sheet_attributes['shareAnswers']['q'+str(qnumber)] = {'share': answer_opts['share'], 'vote': answer_opts['vote'], 'voteWeight': 0}

        if answer_opts['team']:
            if answer_opts['team'] == 'setup':
                if self.sheet_attributes.get('sessionTeam'):
                    abort("    ****ANSWER-ERROR: %s: 'Answer: ... team=setup' must occur as first team option in slide %s" % (self.options["filename"], self.slide_number))
                if self.cur_qtype != 'choice' and self.cur_qtype != 'text':
                    abort("    ****ANSWER-ERROR: %s: 'Answer: ... team=setup' must have answer type as 'choice' or 'text' in slide %s" % (self.options["filename"], self.slide_number))
                self.sheet_attributes['sessionTeam'] = 'setup'
            elif not self.sheet_attributes.get('sessionTeam'):
                self.sheet_attributes['sessionTeam'] = 'roster'

        ans_grade_fields = self.process_weights(weight_answer)

        id_str = self.get_slide_id()
        ans_params = { 'sid': id_str, 'qno': len(self.questions), 'disabled': ''}
        if answer_opts['disabled']:
            ans_params['disabled'] = 'slidoc-answer-disabled'
            if self.options['config'].pace > BASIC_PACE:
                abort("    ****ANSWER-ERROR: %s: 'Answer disabling incompatible with pace value: slide %s" % (self.options["filename"], self.slide_number))

        if not self.options['config'].pace and ('answers' in self.options['config'].strip or not correct_val):
            # Strip any correct answers
            return html_prefix+(self.ansprefix_template % ans_params)+'<p></p>\n'

        hide_answer = self.options['config'].pace or 'show_correct' not in self.options['config'].features 
        if len(self.slide_block_test) != len(self.slide_block_output):
            hide_answer = False
            message("    ****ANSWER-ERROR: %s: Test block count %d != output block_count %d in slide %s" % (self.options["filename"], len(self.slide_block_test), len(self.slide_block_output), self.slide_number))

        if not hide_answer:
            # No hiding of correct answers
            return html_prefix+(self.ansprefix_template % ans_params)+' '+correct_html+'<p></p>\n'

        slide_markdown = (self.cur_qtype == 'text/markdown' or answer_opts['explain'] == 'markdown')

        ans_classes = ''
        if multiline_answer:
            ans_classes += ' slidoc-multiline-answer'
        if answer_opts['explain']:
            ans_classes += ' slidoc-explain-answer'
        if self.cur_qtype in ('choice', 'multichoice'):
            ans_classes += ' slidoc-choice-answer'
        if plugin_name and plugin_action != 'expect':
            ans_classes += ' slidoc-answer-plugin'

        if self.questions[-1].get('gweight'):
            gweight_str = '/'+str(self.questions[-1]['gweight'])
            zero_gwt = ''
        else:
            gweight_str = ''
            zero_gwt = ' slidoc-zero-gradeweight'

        ans_params.update(ans_classes=ans_classes,
                        inp_type='number' if self.cur_qtype == 'number' else 'text',
                        gweight=gweight_str,
                        zero_gwt=zero_gwt,
                        explain=('<br><span id="%s-explainprefix" class="slidoc-explainprefix"><em>Explain:</em></span>' % id_str) if answer_opts['explain'] else '')

        html_template = '''\n<div id="%(sid)s-answer-container" class="slidoc-answer-container %(ans_classes)s">\n'''+self.answer_template

        if ans_grade_fields:
            html_template += self.grading_template
            html_template += self.comments_template_a

        if slide_markdown:
            self.render_markdown = True
            html_template += self.render_template

        if multiline_answer or answer_opts['explain']:
            html_template += self.quote_template

        if ans_grade_fields:
            html_template += self.comments_template_b

        if self.cur_qtype == 'text/x-code':
            html_template += self.response_pre_template
        else:
            html_template += self.response_div_template

        html_template +='''</div>\n'''

        ans_html = html_template % ans_params
            
        return html_prefix+ans_html+html_suffix+'\n'


    def process_weights(self, text):
        # Note: gweight=0 is treated differently from omitted gweight;
        # grade column is created for gweight=0 to allow later changes in grade weights
        sweight, gweight, vweight = 1, None, 0
        comps = [x.strip() for x in text.split(',') if x.strip()]
        if len(comps) > 0:
            sweight = parse_number(comps[0])
        if len(comps) > 1:
            gweight = parse_number(comps[1])
        if len(comps) > 2:
            vweight = parse_number(comps[2])

        if sweight is None or vweight is None:
            abort("    ****WEIGHT-ERROR: %s: Error in parsing 'weight=%s' answer option; expected ';weight=number[,number[,number]]' in slide %s" % (self.options["filename"], text, self.slide_number))
            return []

        if 'grade_response' not in self.options['config'].features:
            if gweight is not None:
                message("    ****WEIGHT-WARNING: %s: Not grading question with weight %d line in slide %s" % (self.options["filename"], gweight, self.slide_number))

            gweight = None

        if gweight is not None and '/' not in self.qtypes[-1] and not self.questions[-1].get('explain') and '()' not in self.questions[-1].get('correct','') < 0:
            message("    ****WEIGHT-WARNING: %s: Ignoring unexpected grade weight %d in non-multiline/non-explained slide %s" % (self.options["filename"], gweight, self.slide_number))
            gweight = None

        if vweight and not self.questions[-1].get('vote'):
            message("    ****WEIGHT-WARNING: %s: Ignoring unexpected vote weight %d line without vote option in slide %s" % (self.options["filename"], vweight, self.slide_number))
            vweight = 0

        if vweight:
            self.sheet_attributes['shareAnswers']['q'+str(self.questions[-1]['qnumber'])]['voteWeight'] = vweight

        self.questions[-1].update(weight=sweight)
        if gweight is not None:
            self.questions[-1].update(gweight=gweight)
        if vweight:
            self.questions[-1].update(vweight=vweight)

        if len(self.questions) == 1:
            self.cum_weights.append(sweight)
            self.cum_gweights.append(gweight or 0)
        else:
            self.cum_weights.append(self.cum_weights[-1] + sweight)
            self.cum_gweights.append(self.cum_gweights[-1] + (gweight or 0))

        ans_grade_fields = []
        if 'grade_response' in self.options['config'].features or 'share_all' in self.options['config'].features or self.questions[-1].get('vote') or self.questions[-1].get('team'):
            qno = 'q%d' % len(self.questions)
            if '/' in self.qtypes[-1] and self.qtypes[-1].split('/')[0] in ('text', 'Code', 'Upload'):
                ans_grade_fields += [qno+'_response']
            elif self.questions[-1].get('explain'):
                ans_grade_fields += [qno+'_response', qno+'_explain']
            elif self.questions[-1].get('vote') or self.questions[-1].get('disabled') or self.questions[-1].get('team') or 'share_all' in self.options['config'].features:
                ans_grade_fields += [qno+'_response']

            if self.questions[-1].get('team') and re.match(r'^(.*)=\s*(\w+)\.response\(\s*\)$', self.questions[-1].get('correct', '')):
                ans_grade_fields += [qno+'_plugin']

            if ans_grade_fields:
                if self.questions[-1].get('vote'):
                    ans_grade_fields += [qno+'_share', qno+'_vote']
                self.grade_fields += ans_grade_fields
                self.max_fields += ['' for field in ans_grade_fields]
                if gweight is not None:
                    self.grade_fields += [qno+'_grade', qno+'_comments']
                    self.max_fields += [gweight, '']

        return ans_grade_fields

    def slidoc_concepts(self, name, text):
        if not text:
            return ''

        ###if self.notes_end is not None:
        ###    message("    ****CONCEPT-ERROR: %s: 'Concepts: %s' line after Notes: ignored in '%s'" % (self.options["filename"], text, self.cur_header))
        ###    return ''

        if self.slide_concepts:
            message("    ****CONCEPT-ERROR: %s: Extra 'Concepts: %s' line ignored in '%s'" % (self.options["filename"], text, self.cur_header or ('slide%02d' % self.slide_number)))
            return ''

        primary, _, secondary = text.partition(':')
        primary = primary.strip()
        secondary = secondary.strip()
        p_tags = [x.strip() for x in primary.split(";") if x.strip()]
        s_tags = [x.strip() for x in secondary.split(";") if x.strip()]
        all_tags = p_tags + s_tags # Preserve case for now

        self.slide_concepts = [[x.lower() for x in p_tags], [x.lower() for x in s_tags]] # Lowercase the tags

        if all_tags and (self.options['config'].index or self.options['config'].qindex or self.options['config'].pace):
            # Track/check tags
            if self.qtypes[-1] in ("choice", "multichoice", "number", "text", "point", "line"):
                # Question
                qtags = [x.lower() for x in all_tags] # Lowercase the tags
                qtags.sort()
                q_id = make_file_id(self.options["filename"], self.get_slide_id())
                q_concept_id = ';'.join(qtags)
                q_pars = (self.options["filename"], self.get_slide_id(), self.cur_header, len(self.questions), q_concept_id)
                Global.questions[q_id] = q_pars
                Global.concept_questions[q_concept_id].append( q_pars )
                for tag in qtags:
                    # If assessment document, do not warn about lack of concept coverage
                    if tag not in Global.primary_tags and tag not in Global.sec_tags and 'assessment' not in self.options['config'].features:
                        self.concept_warnings.append("CONCEPT-WARNING: %s: '%s' not covered before '%s'" % (self.options["filename"], tag, self.cur_header or ('slide%02d' % self.slide_number)) )
                        message("        "+self.concept_warnings[-1])

                add_to_index(Global.primary_qtags, Global.sec_qtags, p_tags, s_tags, self.options["filename"], self.get_slide_id(), self.cur_header, qconcepts=self.qconcepts)
            else:
                # Not question
                add_to_index(Global.primary_tags, Global.sec_tags, p_tags, s_tags, self.options["filename"], self.get_slide_id(), self.cur_header)

        if 'concepts' in self.options['config'].strip:
            # Strip concepts
            return ''

        id_str = self.get_slide_id()+'-concepts'
        display_style = 'inline' if self.options['config'].printable else 'none'
        tag_html = '''<div class="slidoc-concepts-container slidoc-noslide slidoc-nopaced"><span class="slidoc-clickable" onclick="Slidoc.toggleInlineId('%s')">%s:</span> <span id="%s" style="display: %s;">''' % (id_str, name.capitalize(), id_str, display_style)

        if self.options['config'].index:
            for j, tag in enumerate(all_tags):
                if j == len(p_tags):
                    tag_html += ': '
                elif j:
                    tag_html += '; '
                tag_hash = '#%s-concept-%s' % (self.index_id, md2md.make_id_from_text(tag))
                tag_html += nav_link(tag, self.options['config'].site_url, self.options['config'].index,
                                     hash=tag_hash, separate=self.options['config'].separate, target='_blank',
                                     keep_hash=True, printable=self.options['config'].printable)
        else:
            tag_html += text

        tag_html += '</span></div>'

        return tag_html+'\n'

    
    def slidoc_hint(self, name, text):
        if self.extra_end is not None:
            return ''
        if not self.qtypes[-1]:
            abort("    ****HINT-ERROR: %s: Hint must appear after Answer:... in slide %s" % (self.options["filename"], self.slide_number))

        if self.notes_end is not None:
            abort("    ****HINT-ERROR: %s: Hint may not appear within Notes section of slide %s" % (self.options["filename"], self.slide_number))
        if not isfloat(text) or abs(float(text)) >= 100.0:
            abort("    ****HINT-ERROR: %s: Invalid penalty %s following Hint. Expecting a negative percentage in slide %s" % (self.options["filename"], text, self.slide_number))

        if self.options['config'].pace > QUESTION_PACE:
            message("    ****HINT-WARNING: %s: Hint displayed for non-question-paced session in slide %s" % (self.options["filename"], self.slide_number))

        hint_penalty = abs(float(text)) / 100.0
            
        qno = 'q'+str(self.questions[-1]['qnumber'])

        qhints = self.sheet_attributes['hints'][qno]
        qhints.append(hint_penalty)
        hint_number = len(qhints)

        if qhints:
            self.questions[-1]['hints'] = qhints[:]

        prefix = self.end_hint()

        id_str = self.get_slide_id() + '-hint-' + str(hint_number)
        start_str, suffix, end_str = self.start_block('hint', id_str, display='none')
        prefix += start_str
        self.hint_end = end_str
        classes = 'slidoc-clickable slidoc-question-hint'
        return prefix + ('''<br><span id="%s" class="%s" onclick="Slidoc.hintDisplay(this, '%s', %s, %s)" style="display: inline;">Hint %s:</span>\n''' % (id_str, classes, self.get_slide_id() , self.questions[-1]['qnumber'], hint_number, hint_number)) + ' ' + text + '% ' + suffix


    def slidoc_notes(self, name, text):
        if self.extra_end is not None:
            return ''
        if self.notes_end is not None:
            # Additional notes prefix in slide; strip it
            return ''
        prefix = self.end_hint()

        id_str = self.get_slide_id() + '-notes'
        disp_block = 'none' if self.qtypes[-1] else 'block'
        start_str, suffix, end_str = self.start_block('notes', id_str, display=disp_block)
        prefix += start_str
        self.notes_end = end_str
        classes = 'slidoc-clickable'
        if self.qtypes[-1]:
            classes += ' slidoc-question-notes'
        return prefix + ('''<br><span id="%s" class="%s" onclick="Slidoc.classDisplay('%s')" style="display: inline;">Notes:</span>\n''' % (id_str, classes, id_str)) + suffix


    def slidoc_extra(self, name, text):
        prefix = self.end_hint() + self.end_notes()
        id_str = self.get_slide_id() + '-extra'
        disp_block = 'block' if 'keep_extras' in self.options['config'].features else 'none'
        start_str, suffix, end_str = self.start_block('extra', id_str, display=disp_block)
        prefix += start_str
        self.extra_end = end_str
        return prefix + suffix + '\n<b>Extra</b>:<br>\n'


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

SLIDE_BREAK_RE =  re.compile(r'^ {0,3}(----* *|##[^#].*)\n?$')
HRULE_BREAK_RE =  re.compile(r'(\S\s*\n)( {0,3}----* *(\n|$))')
    
def md2html(source, filename, config, filenumber=1, plugin_defs={}, prev_file='', next_file='', index_id='', qindex_id=''):
    """Convert a markdown string to HTML using mistune, returning (first_header, file_toc, renderer, html)"""
    Global.chapter_ref_counter = defaultdict(int)

    renderer = SlidocRenderer(escape=False, filename=filename, config=config, filenumber=filenumber, plugin_defs=plugin_defs)
    content_html = MarkdownWithSlidoc(renderer=renderer).render(source, index_id=index_id, qindex_id=qindex_id)

    content_html = Missing_ref_num_re.sub(Missing_ref_num, content_html)

    if renderer.questions:
        # Compute question hash digest to track questions
        sbuf = cStringIO.StringIO(source)
        slide_hash = []
        slide_lines = []
        first_slide = True
        prev_hrule = True
        prev_blank = True
        slide_header = ''
        while True:
            line = sbuf.readline()
            if not line:
                slide_hash.append( sliauth.digest_hex((''.join(slide_lines)).strip()) )
                break

            if not line.strip() or MathBlockGrammar.slidoc_header.match(line):
                # Blank line (treat slidoc comment line as blank)
                if prev_blank:
                    # Skip multiple blank lines (for digest computation)
                    continue
                prev_blank = True
            else:
                prev_blank = False

            new_slide = False
            lmatch = SLIDE_BREAK_RE.match(line)
            if lmatch:
                if lmatch.group(1).startswith('---'):
                    prev_hrule = True
                    new_slide = True
                    slide_header = ''
                else:
                    if not prev_hrule:
                        new_slide = True
                    slide_header = line
                    prev_hrule = False
            elif not prev_blank:
                prev_hrule = False

            if new_slide:
                slide_hash.append( sliauth.digest_hex((''.join(slide_lines)).strip()) )
                slide_lines = []
                if slide_header:
                    slide_lines.append(slide_header)
                prev_blank = True
                first_slide = False
            else:
                slide_lines.append(line)

        if renderer.slide_number == len(slide_hash):
            # Save question digests (for future use)
            for question in renderer.questions:
                question['digest'] = slide_hash[question['slide']-1]
        else:
            message('Mismatch in slide count for hashing: expected %d but found %d' % (renderer.slide_number, len(slide_hash)))

    pre_header_html = ''
    tail_html = ''
    post_header_html = ''
    if 'navigate' not in config.strip:
        nav_html = ''
        if config.toc:
            nav_html += nav_link(SYMS['return'], config.site_url, config.toc, hash='#'+make_chapter_id(0), separate=config.separate, classes=['slidoc-noprint'], printable=config.printable) + SPACER6
            nav_html += nav_link(SYMS['prev'], config.site_url, prev_file, separate=config.separate, classes=['slidoc-noall'], printable=config.printable) + SPACER6
            nav_html += nav_link(SYMS['next'], config.site_url, next_file, separate=config.separate, classes=['slidoc-noall'], printable=config.printable) + SPACER6

        ###sidebar_html = click_span(SYMS['trigram'], "Slidoc.sidebarDisplay();", classes=["slidoc-clickable-sym", 'slidoc-nosidebar']) if config.toc and not config.separate else ''
        ###slide_html = SPACER3+click_span(SYMS['square'], "Slidoc.slideViewStart();", classes=["slidoc-clickable-sym", 'slidoc-nosidebar'])
        sidebar_html = ''
        slide_html = ''
        pre_header_html += '<div class="slidoc-noslide slidoc-noprint slidoc-noall">'+nav_html+sidebar_html+slide_html+'</div>\n'

        tail_html = '<div class="slidoc-noslide slidoc-noprint">' + nav_html + ('<a href="#%s" class="slidoc-clickable-sym">%s</a>%s' % (renderer.first_id, SYMS['up'], SPACER6) if renderer.slide_number > 1 else '') + '</div>\n'

    if 'contents' not in config.strip:
        chapter_id = make_chapter_id(filenumber)
        header_toc = renderer.table_of_contents(filenumber=filenumber)
        if header_toc:
            post_header_html += ('<div class="slidoc-chapter-toc %s-chapter-toc slidoc-nopaced slidoc-nosidebar">' % chapter_id)+header_toc+'</div>\n'
            post_header_html += click_span('&#8722;Contents', "Slidoc.hide(this, '%s');" % (chapter_id+'-chapter-toc'),
                                            id=chapter_id+'-chapter-toc-hide', classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-chapter-toc-hide', 'slidoc-nopaced', 'slidoc-noslide', 'slidoc-noprint', 'slidoc-nosidebar'])

    if 'contents' not in config.strip and 'slidoc-notes' in content_html:
        post_header_html += '&nbsp;&nbsp;' + click_span('&#8722;All Notes',
                                             "Slidoc.hide(this,'slidoc-notes');",id=renderer.first_id+'-hidenotes',
                                              classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-nopaced', 'slidoc-noprint'])

    if 'slidoc-answer-type' in content_html and 'slidoc-concepts-container' in content_html:
        post_header_html += '&nbsp;&nbsp;' + click_span('Missed question concepts', "Slidoc.showConcepts();", classes=['slidoc-clickable', 'slidoc-noprint'])

    content_html = content_html.replace('__PRE_HEADER__', pre_header_html)
    content_html = content_html.replace('__POST_HEADER__', post_header_html)
    content_html += tail_html

    if 'keep_extras' not in config.features:
        # Strip out extra text
        content_html = re.sub(r"<!--slidoc-extra-block-begin\[([-\w]+)\](.*?)<!--slidoc-extra-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    if 'hidden' in config.strip:
        # Strip out hidden answer slides
        content_html = re.sub(r"<!--slidoc-hidden-block-begin\[([-\w]+)\](.*?)<!--slidoc-hidden-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    if 'notes' in config.strip:
        # Strip out notes
        content_html = re.sub(r"<!--slidoc-notes-block-begin\[([-\w]+)\](.*?)<!--slidoc-notes-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    file_toc = renderer.table_of_contents('' if not config.separate else config.site_url+filename+'.html', filenumber=filenumber)

    return (renderer.file_header or filename, file_toc, renderer, content_html)

# 'name' and 'id' are required field; entries are sorted by name but uniquely identified by id
Manage_fields  = ['name', 'id', 'email', 'altid', 'source', 'accessCount', 'Timestamp', 'initTimestamp', 'submitTimestamp']
Session_fields = ['team', 'lateToken', 'lastSlide', 'retakes', 'session_hidden']
Score_fields   = ['q_total', 'q_scores', 'q_other', 'q_comments']
Index_fields   = ['name', 'id', 'revision', 'Timestamp', 'sessionWeight', 'sessionRescale', 'releaseDate', 'dueDate', 'gradeDate',
                  'mediaURL', 'paceLevel', 'adminPaced', 'scoreWeight', 'gradeWeight', 'otherWeight',
                  'questionsMax', 'fieldsMin', 'attributes', 'questions',
                  'questionConcepts', 'primary_qconcepts', 'secondary_qconcepts']
Log_fields =     ['name', 'id', 'email', 'altid', 'Timestamp', 'browser', 'file', 'function', 'type', 'message', 'trace']


def update_session_index(sheet_url, hmac_key, session_name, revision, session_weight, session_rescale, release_date_str, due_date_str, media_url, pace_level,
                         score_weights, grade_weights, other_weights, sheet_attributes,
                         questions, question_concepts, p_concepts, s_concepts, max_last_slide=None, debug=False,
                         row_count=None, modify_session=False):
    modify_questions = False
    user = ADMINUSER_ID
    user_token = sliauth.gen_admin_token(hmac_key, user)
    admin_paced = 1 if pace_level >= ADMIN_PACE else None

    post_params = {'sheet': INDEX_SHEET, 'id': session_name, ADMINUSER_ID: user, 'token': user_token,
                  'get': '1', 'headers': json.dumps(Index_fields), 'getheaders': '1'}
    retval = sliauth.http_post(sheet_url, post_params)
    if retval['result'] != 'success':
        if not retval['error'].startswith('Error:NOSHEET:'):
            abort("Error in accessing index entry for session '%s': %s" % (session_name, retval['error']))

    ##if debug:
    ##    print('slidoc.update_session_index: slidoc_sheets VERSION =', retval.get('info',{}).get('version'), file=sys.stderr)
    prev_headers = retval.get('headers')
    prev_row = retval.get('value')
    prev_questions = None
    if prev_row:
        revision_col = Index_fields.index('revision')
        admin_paced_col = Index_fields.index('adminPaced')
        due_date_col = Index_fields.index('dueDate')
        if prev_row[revision_col] != revision:
            message('    ****WARNING: Session %s has changed from revision %s to %s' % (session_name, prev_row[revision_col], revision))

        prev_questions = json.loads(prev_row[prev_headers.index('questions')])

        min_count =  min(len(prev_questions), len(questions))
        mod_question = 0
        for j in range(min_count):
            if prev_questions[j]['qtype'] != questions[j]['qtype']:
                mod_question = j+1
                break

        if mod_question or len(prev_questions) != len(questions):
            ###if modify_session or not row_count:
            if modify_session:
                modify_questions = True
                if len(prev_questions) > len(questions):
                    # Truncating
                    if max_last_slide is not None:
                        for j in range(len(questions), len(prev_questions)):
                            if prev_questions[j]['slide'] <= max_last_slide:
                                abort('ERROR: Cannot truncate previously viewed question %d for session %s (max_last_slide=%d,question_%d_slide=%d); change lastSlide in session sheet' % (j+1, session_name, max_last_slide, j+1, prev_questions[j]['slide']))
                elif len(prev_questions) < len(questions):
                    # Extending
                    pass
            elif row_count == 1:
                abort('ERROR: Delete test user entry to modify questions in session '+session_name)
            elif mod_question:
                abort('ERROR: Mismatch in question %d type for session %s: previously \n%s \nbut now \n%s. Specify --modify_sessions=%s' % (mod_question, session_name, prev_questions[mod_question-1]['qtype'], questions[mod_question-1]['qtype'], session_name))
            else:
                abort('ERROR: Mismatch in question numbers for session %s: previously %d but now %d. Specify --modify_sessions=%s' % (session_name, len(prev_questions), len(questions), session_name))

        if prev_row[admin_paced_col]:
            # Do not overwrite previous value of adminPaced
            admin_paced = prev_row[admin_paced_col]
            # Do not overwrite due date, unless it is actually specified
            if not due_date_str:
                due_date_str = prev_row[due_date_col]

    row_values = [session_name, session_name, revision, None, session_weight, session_rescale, release_date_str, due_date_str, None, media_url, pace_level, admin_paced,
                score_weights, grade_weights, other_weights, len(questions), len(Manage_fields)+len(Session_fields),
                json.dumps(sheet_attributes), json.dumps(questions), json.dumps(question_concepts),
                '; '.join(sort_caseless(list(p_concepts))),
                '; '.join(sort_caseless(list(s_concepts)))
                 ]

    if len(Index_fields) != len(row_values):
        abort('Error in updating index entry for session %s: number of headers != row length' % (session_name,))

    post_params = {'sheet': INDEX_SHEET, ADMINUSER_ID: user, 'token': user_token,
                   'headers': json.dumps(Index_fields), 'row': json.dumps(row_values)
                  }
    retval = sliauth.http_post(sheet_url, post_params)
    if retval['result'] != 'success':
        abort("Error in updating index entry for session '%s': %s" % (session_name, retval['error']))
    message('slidoc: Updated remote index sheet %s for session %s' % (INDEX_SHEET, session_name))

    # Return possibly modified due date
    return (due_date_str, modify_questions)


def check_gdoc_sheet(sheet_url, hmac_key, sheet_name, headers, modify_session=None):
    modify_col = 0
    user = TESTUSER_ID
    user_token = sliauth.gen_user_token(hmac_key, user) if hmac_key else ''
    post_params = {'id': user, 'token': user_token, 'sheet': sheet_name,
                   'get': 1, 'getheaders': '1'}
    retval = sliauth.http_post(sheet_url, post_params)
    if retval['result'] != 'success':
        if retval['error'].startswith('Error:NOSHEET:'):
            return (None, modify_col, 0)
        else:
            abort("Error in accessing sheet '%s': %s\n%s" % (sheet_name, retval['error'], retval.get('messages')))
    prev_headers = retval['headers']
    prev_row = retval['value']
    maxLastSlide = retval['info']['maxLastSlide']
    maxRows = retval['info']['maxRows']
    if maxRows == 2:
        # No data rows; all modifications OK
        row_count = 0
    elif maxRows == 3 and prev_row:
        # Test user row only
        row_count = 1
    else:
        # One or more regular user rows
        row_count = 2

    min_count = min(len(prev_headers), len(headers))
    for j in range(min_count):
        if prev_headers[j] != headers[j]:
            modify_col = j+1
            break

    if not modify_col:
        if len(headers) != len(prev_headers):
            modify_col = min_count + 1
        
    if modify_col:
        if row_count == 1:
            abort('ERROR: Mismatched header %d for session %s. Delete test user row to modify')
        ###elif not modify_session and row_count:
        elif not modify_session:
            abort('ERROR: Mismatched header %d for session %s. Specify --modify_sessions=%s to truncate/extend.\n Previously \n%s\n but now\n %s' % (modify_col, sheet_name, sheet_name, prev_headers, headers))

    return (maxLastSlide, modify_col, row_count)
                
def update_gdoc_sheet(sheet_url, hmac_key, sheet_name, headers, row=None, modify=None):
    user = ADMINUSER_ID
    user_token = sliauth.gen_admin_token(hmac_key, user) if hmac_key else ''
    post_params = {ADMINUSER_ID: user, 'token': user_token, 'sheet': sheet_name,
                   'headers': json.dumps(headers)}
    if row:
        post_params['row'] = json.dumps(row)
    if modify:
        post_params['modify'] = modify
    retval = sliauth.http_post(sheet_url, post_params)

    if retval['result'] != 'success':
        abort("Error in creating sheet '%s': %s\n headers=%s\n%s" % (sheet_name, retval['error'], headers, retval.get('messages')))
    if sheet_name != LOG_SHEET:
        message('slidoc: Created remote spreadsheet:', sheet_name)

def parse_plugin(text, name=None):
    nmatch = re.match(r'^\s*([a-zA-Z]\w*)\s*=\s*{', text)
    if not nmatch:
        abort("Plugin definition must start with plugin_name={'")
    plugin_name = nmatch.group(1)
    if name and name != plugin_name:
        abort("Plugin definition must start with '"+name+" = {'")
    plugin_def = {}
    match = re.match(r'^(.*)\n(\s*/\*\s*)?PluginHead:([^\n]*)\n(.*)$', text, flags=re.DOTALL)
    if match:
        text = match.group(1)+'\n'
        comment = match.group(2)
        plugin_def['ArgPattern'] = match.group(3).strip()
        tail = match.group(4).strip()
        if comment and tail.endswith('*/'):    # Strip comment delimiter
            tail = tail[:-2].strip()
        tail = re.sub(r'%(?!\(plugin_)', '%%', tail)  # Escape % signs in Head/Body template
        comps = re.split(r'(^|\n)\s*Plugin(Button|Top|Body):' if comment else r'(^|\n)Plugin(Button|Body):', tail)
        plugin_def['Head'] = comps[0]+'\n' if comps[0] else ''
        comps = comps[1:]
        while comps:
            if comps[1] == 'Button':
                plugin_def['Button'] = comps[2]
            elif comps[1] == 'Top':
                plugin_def['Top'] = comps[2]
            elif comps[1] == 'Body':
                plugin_def['Body'] = comps[2]+'\n'
            comps = comps[3:]

    plugin_def['JS'] = 'Slidoc.PluginDefs.'+text.lstrip()
    return plugin_name, plugin_def

def plugin_heads(plugin_defs, plugin_loads):
    if not plugin_defs:
        return ''
    plugin_list = plugin_defs.keys()
    plugin_list.sort()
    plugin_code = []
    for plugin_name in plugin_list:
        if plugin_name not in plugin_loads:
            continue
        plugin_code.append('\n')
        plugin_head = plugin_defs[plugin_name].get('Head', '') 
        if plugin_head:
            plugin_params = {'pluginName': plugin_name,
                             'pluginLabel': 'slidoc-plugin-'+plugin_name}
            try:
                tem_head = plugin_head % plugin_params
            except Exception, err:
                tem_head = ''
                abort('ERROR Template formatting error in Head for plugin %s: %s' % (plugin_name, err))
            plugin_code.append(tem_head+'\n')
        plugin_code.append('<script>(function() {\n'+plugin_defs[plugin_name]['JS'].strip()+'\n})();</script>\n')
    return ''.join(plugin_code)

def strip_name(filepath, split_char=''):
    # Strips dir/extension from filepath, and returns last subname assuming split_char to split subnames
    name = os.path.splitext(os.path.basename(filepath))[0]
    return name.split(split_char)[-1] if split_char else name

N_INDEX_ENTRIES = 5
def read_index(filepath):
    # Read one or more index entries from comment in the header portion of HTML file
    index_entries = []
    if not os.path.exists(filepath):
        return index_entries

    with open(filepath) as f:
        found_entries = False
        while 1:
            line = f.readline()
            if not line:
                break
            if line.strip() == Index_prefix.strip():
                found_entries = True
                break

        tem_list = []
        while found_entries:
            line = f.readline()
            if not line or line.strip().startswith(Index_suffix.strip()):
                break
            tem_list.append(line.strip())
            if len(tem_list) == N_INDEX_ENTRIES:
                index_entries.append(tem_list)
                tem_list = []

    return index_entries

def get_topnav(opts, fnames=[], site_name='', separate=False, cur_dir='', split_char=''):
    site_prefix = '/'
    if site_name:
        site_prefix += site_name + '/'
    if opts == 'args':
        # Generate top navigation menu from argument filenames
        label_list = [ (site_name or 'Home', site_prefix) ] + [ (strip_name(x, split_char), site_prefix+x+'.html') for x in fnames if x != 'index' ]

    elif opts in ('dirs', 'files'):
        # Generate top navigation menu from list of subdirectories, or list of HTML files
        _, subdirs, subfiles = next(os.walk(cur_dir or '.'))
        if opts == 'dirs':
            label_list = [(strip_name(x, split_char), site_prefix+x+'/index.html') for x in subdirs if x[0] not in '._']
        else:
            label_list = [(strip_name(x, split_char), site_prefix+x.replace('.md','.html')) for x in subfiles if x[0] not in '._' and not x.startswith('index.') and x.endswith('.md')]
        label_list.sort()
        label_list = [ (site_name or 'Home', site_prefix) ] + label_list

    else:
        # Generate menu using basenames of provided paths
        label_list = []
        for opt in opts.split(','):
            base = os.path.basename(opt)
            if opt == '/' or opt == 'index.html':
                label_list.append( (site_name or 'Home', site_prefix) )
            elif '.' not in base:
                # No extension in basename; assume directory
                label_list.append( (strip_name(opt, split_char), site_prefix+opt+'/index.html') )
            elif opt.endswith('/index.html'):
                label_list.append( (strip_name(opt[:-len('/index.html')], split_char), site_prefix+opt) )
            else:
                label_list.append( (strip_name(opt, split_char), site_prefix+opt) )

    if site_name:
        label_list = [ (SYMS['house'], '/') ] + label_list

    topnav_list = []
    for j, names in enumerate(label_list):
        basename, href = names
        linkid = re.sub(r'\W', '', basename)
        if j and opts == 'args' and not separate:
            link = '#'+make_chapter_id(j+1)
        else:
            link = href
        topnav_list.append([link, basename, linkid])
    return topnav_list

def render_topnav(topnav_list, filepath='', site_name=''):
    fname = ''
    if filepath:
        fname = strip_name(filepath)
        if fname == 'index':
           fname = strip_name(os.path.dirname(filepath))
    elems = []
    for link, basename, linkid in topnav_list:
        classes = ''
        if basename.lower() == fname.lower() or (basename == site_name and fname.lower() == 'home'):
            classes = ' class="slidoc-topnav-selected"'
        if link.startswith('#'):
            elem = '''<span onclick="Slidoc.go('%s');" %s>%s</span>'''  % (link, classes, basename)
        else:
            elem = '<a href="%s" %s>%s</a>' % (link, classes, basename)

        elems.append('<li>'+elem+'</li>')

    topnav_html = '<ul class="slidoc-topnav" id="slidoc-topnav">\n'+'\n'.join(elems)+'\n'
    topnav_html += '<li id="dashlink" style="display: none;"><a href="/_dash" target="_blank">dashboard</a></li>'
    topnav_html += '<li class="slidoc-nav-icon"><a href="javascript:void(0);" onclick="Slidoc.switchNav()">%s</a></li>' % SYMS['threebars']
    topnav_html += '</ul>\n'
    return topnav_html


scriptdir = os.path.dirname(os.path.realpath(__file__))

def message(*args):
    print(*args, file=sys.stderr)

def process_input(input_files, input_paths, config_dict, return_html=False):
    global message
    messages = []
    if return_html:
        def append_message(*args):
            messages.append(''.join(str(x) for x in args))
        message = append_message

    if config_dict['indexed']:
        comps = config_dict['indexed'].split(',')
        ftoc = comps[0]+'.html' if comps[0] else ''
        findex = comps[1]+'.html' if len(comps) > 1 and comps[1] else ''
        fqindex = comps[2]+'.html' if len(comps) > 2 and comps[2] else ''
    elif config_dict['all'] is not None:
        # All indexes for combined file by default
        ftoc, findex, fqindex = 'toc.html', 'ind.html', 'qind.html'
    else:
        # No default indexes for separate file
        ftoc, findex, fqindex = '', '', ''

    separate_files = config_dict['all'] is None  # Specify --all='' to use first file name

    tem_dict = config_dict.copy()
    tem_dict.update(separate=separate_files, toc=ftoc, index=findex, qindex=fqindex)

    # Create config object
    config = argparse.Namespace(**tem_dict)

    config.modify_sessions = set(config.modify_sessions.split(',')) if config.modify_sessions else set()

    if config.make:
        # Process only modified input files
        if config.toc or config.index or config.qindex or config.all:
            abort('ERROR --make option incompatible with indexing or "all" options')
        
    dest_dir = ''
    backup_dir = ''
    if config.dest_dir:
        if not os.path.isdir(config.dest_dir):
            os.makedirs(config.dest_dir)
        dest_dir = config.dest_dir+'/'
        if config.backup_dir:
            if not os.path.isdir(config.backup_dir):
                os.makedirs(config.backup_dir)
            backup_dir = config.backup_dir + '/'

    orig_fnames = []
    orig_outpaths = []
    orig_flinks = []

    fnumbers = []
    fprefix = None
    nfiles = len(input_files)
    for j, inpath in enumerate(input_paths):
        fext = os.path.splitext(os.path.basename(inpath))[1]
        if fext != '.md':
            abort('Invalid file extension for '+inpath)

        fnumber = j+1
        fname = strip_name(inpath, config.split_name)
        outpath = dest_dir + fname + '.html'
        flink = fname+'.html' if config.separate else '#'+make_chapter_id(fnumber)

        orig_fnames.append(fname)
        orig_outpaths.append(outpath)
        orig_flinks.append(flink)

        if not config.make:
            fnumbers.append(fnumber)
        elif not os.path.exists(outpath) or os.path.getmtime(outpath) <= os.path.getmtime(inpath):
            # Process only modified input files
            fnumbers.append(fnumber)

        if config.notebook and os.path.exists(dest_dir+fname+'.ipynb') and not config.overwrite and not config.dry_run:
            abort("File %s.ipynb already exists. Delete it or specify --overwrite" % fname)

        if fprefix == None:
            fprefix = fname
        else:
            # Find common filename prefix
            while fprefix:
                if fname[:len(fprefix)] == fprefix:
                    break
                fprefix = fprefix[:-1]

    if not fnumbers:
        message('All output files are newer than corresponding input files')
        if not config.make_toc:
            return

    if config.pace and config.all is not None :
        abort('slidoc: Error: --pace option incompatible with --all')

    js_params = {'siteName': '', 'fileName': '', 'sessionVersion': '1.0', 'sessionRevision': '', 'sessionPrereqs': '',
                 'pacedSlides': 0, 'questionsMax': 0, 'scoreWeight': 0, 'otherWeight': 0, 'gradeWeight': 0,
                 'gradeFields': [], 'topnavList': [], 'tocFile': '',
                 'slideDelay': 0, 'lateCredit': None, 'participationCredit': None, 'maxRetakes': 0,
                 'plugins': [], 'plugin_share_voteDate': '',
                 'releaseDate': '', 'dueDate': '',
                 'gd_client_id': None, 'gd_api_key': None, 'gd_sheet_url': '',
                 'roster_sheet': ROSTER_SHEET, 'score_sheet': SCORE_SHEET,
                 'index_sheet': INDEX_SHEET, 'indexFields': Index_fields,
                 'log_sheet': LOG_SHEET, 'logFields': Log_fields,
                 'sessionFields':Manage_fields+Session_fields, 'gradeFields': [], 
                 'testUserId': TESTUSER_ID, 'authType': '', 'features': {} }

    js_params['siteName'] = config.site_name
    js_params['paceLevel'] = config.pace or 0  # May be overridden by file-specific values

    js_params['conceptIndexFile'] = 'index.html'  # Need command line option to modify this
    js_params['printable'] = config.printable
    js_params['debug'] = config.debug
    js_params['remoteLogLevel'] = config.remote_logging

    combined_name = config.all or orig_fnames[0]
    combined_file = '' if config.separate else combined_name+'.html'

    # Reset config properties that will be overridden for separate files
    if config.features is not None and not isinstance(config.features, set):
        config.features = md2md.make_arg_set(config.features, Features_all)

    topnav_opts = ''
    gd_sheet_url = ''
    if not config.separate:
        # Combined file  (these will be set later for separate files)
        if config.gsheet_url:
            sys.exit('Combined files do not use --gsheet_url');
        config.features = config.features or set()
        js_params['features'] = dict([(x, 1) for x in config.features])
        js_params['fileName'] = combined_name

    gd_hmac_key = config.auth_key     # Specify --auth_key='' to use Google Sheets without authentication
                
    if config.google_login is not None:
        js_params['gd_client_id'], js_params['gd_api_key'] = config.google_login.split(',')
    
    if gd_hmac_key and not config.anonymous:
        js_params['authType'] = 'digest'

    nb_site_url = config.site_url
    if combined_file:
        config.site_url = ''
    if config.site_url and not config.site_url.endswith('/'):
        config.site_url += '/'
    if config.image_url and not config.image_url.endswith('/'):
        config.image_url += '/'

    config.images = set(config.images.split(',')) if config.images else set()

    config.strip = md2md.make_arg_set(config.strip, Strip_all)
    if nfiles == 1:
        config.strip.add('chapters')

    templates = {}
    for tname in ('doc_include.css', 'wcloud.css', 'doc_custom.css',
                  'doc_include.js', 'wcloud.js', 'doc_google.js', 'doc_test.js',
                  'doc_include.html', 'doc_template.html', 'reveal_template.html'):
        templates[tname] = md2md.read_file(scriptdir+'/templates/'+tname)

    if config.css.startswith('http:') or config.css.startswith('https:'):
        css_html = '<link rel="stylesheet" type="text/css" href="%s">\n' % config.css
    elif config.css:
        css_html = '<style>\n' + md2md.read_file(config.css) + '</style>\n'
    else:
        tem_css = templates['doc_custom.css']
        if config.fontsize:
            comps = config.fontsize.split(',')
            if len(comps) == 1:
                tem_css = tem_css.replace('/*SUBSTITUTE_FONTSIZE*/', 'font-size: %s;' % config.fontsize)
            else:
                for fsize in comps:
                    tem_css = tem_css.replace('/*SUBSTITUTE_FONTSIZE*/', 'font-size: %s;' % fsize, 1)
        css_html = '<style>\n'+tem_css+'</style>\n'

    # External CSS replaces doc_custom.css, but not doc_include.css
    css_html += '<style>\n' + (templates['doc_include.css']+HtmlFormatter().get_style_defs('.highlight')) + '</style>\n'
    css_html += '<style>\n' + templates['wcloud.css'] + '</style>\n'

    test_params = []
    add_scripts = ''
    if config.test_script:
        add_scripts += '\n<script>\n%s</script>\n' % templates['doc_test.js']
        if not config.test_script.isdigit():
            for comp in config.test_script.split(','):
                script, _, user_id = comp.partition('/')
                if user_id and not gd_hmac_key:
                    continue
                query = '?testscript=' + script
                proxy_query = ''
                if user_id:
                    label = '%s/%s' % (script, user_id)
                    query += '&testuser=%s&testkey=%s' % (user_id, gd_hmac_key)
                    proxy_query = '?username=%s&token=%s' % (user_id, gd_hmac_key if user_id == ADMINUSER_ID else sliauth.gen_user_token(gd_hmac_key, user_id))
                else:
                    label = script
                test_params.append([label, query, proxy_query])

    if gd_hmac_key is not None:
        add_scripts += (Google_docs_js % js_params) + ('\n<script>\n%s</script>\n' % templates['doc_google.js'])
        if config.google_login:
            add_scripts += '<script src="https://apis.google.com/js/client.js?onload=onGoogleAPILoad"></script>\n'
        if gd_hmac_key:
            add_scripts += '<script src="https://cdnjs.cloudflare.com/ajax/libs/blueimp-md5/2.3.0/js/md5.js"></script>\n'
    answer_elements = {}
    for suffix in SlidocRenderer.content_suffixes:
        answer_elements[suffix] = 0;
    for suffix in SlidocRenderer.input_suffixes:
        answer_elements[suffix] = 1;
    js_params['answer_elements'] = answer_elements

    toc_file = ''
    if config.make_toc or config.toc:
        toc_file = 'index.html' if config.make_toc else config.toc
        js_params['tocFile'] = toc_file

    topnav_list = []
    if config.topnav:
        topnav_list = get_topnav(config.topnav, fnames=orig_fnames, site_name=config.site_name, separate=config.separate)
    js_params['topnavList'] = topnav_list

    head_html = css_html + ('\n<script>\n%s</script>\n' % templates['doc_include.js'].replace('JS_PARAMS_OBJ', json.dumps(js_params)) ) + ('\n<script>\n%s</script>\n' % templates['wcloud.js'])
    if combined_file:
        head_html += add_scripts
    body_prefix = templates['doc_include.html']
    mid_template = templates['doc_template.html']

    plugins_dir = scriptdir + '/plugins'
    plugin_paths = [plugins_dir+'/'+fname for fname in os.listdir(plugins_dir) if not fname.startswith('.') and fname.endswith('.js')]
    if config.plugins:
        # Plugins with same name will override earlier plugins
        plugin_paths += config.plugins.split(',')

    base_plugin_defs = {}
    for plugin_path in plugin_paths:
        plugin_name, base_plugin_defs[plugin_name] = parse_plugin( md2md.read_file(plugin_path.strip()) )

    comb_plugin_defs = {}
    comb_plugin_loads = set()

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
    index_id = 'slidoc-index'
    qindex_id = 'slidoc-qindex'
    index_chapter_id = make_chapter_id(nfiles+1)
    qindex_chapter_id = make_chapter_id(nfiles+2)
    back_to_contents = nav_link('BACK TO CONTENTS', config.site_url, config.toc, hash='#'+make_chapter_id(0),
                                separate=config.separate, classes=['slidoc-nosidebar'], printable=config.printable)+'<p></p>\n'

    all_concept_warnings = []
    outfile_buffer = []
    combined_html = []
    if combined_file:
        combined_html.append( '<div id="slidoc-sidebar-right-container" class="slidoc-sidebar-right-container">\n' )
        combined_html.append( '<div id="slidoc-sidebar-right-wrapper" class="slidoc-sidebar-right-wrapper">\n' )

    math_found = False
    pagedown_load = False
    skulpt_load = False
    flist = []
    paced_files = {}
    admin_due_date = {}
    for j, fnumber in enumerate(fnumbers):
        fhandle = input_files[fnumber-1]
        fname = orig_fnames[fnumber-1]
        release_date_str = ''
        due_date_str = ''
        vote_date_str = ''
        if not config.separate:
            file_config = config
        else:
            # Separate files (may also be paced)

            # Merge file config with command line
            file_config = parse_merge_args(read_first_line(fhandle), fname, Conf_parser, vars(config), include_args=Select_file_args,
                                           first_line=True, verbose=config.verbose)

            if config.preview:
                if file_config.pace:
                    file_config.pace = BASIC_PACE
                if file_config.gsheet_url:
                    file_config.gsheet_url = ''
                if file_config.images:
                    file_config.images = ''

            file_config.features = file_config.features or set()
            if 'grade_response' in file_config.features and gd_hmac_key is None:
                # No grading without google sheet
                file_config.features.remove('grade_response')

            if 'slides_only' in file_config.features and config.printable:
                file_config.features.remove('slides_only')
                message('slides_only feature suppressed by --printable option')

            if 'keep_extras' in file_config.features and config.gsheet_url:
                abort('PACE-ERROR: --features=keep_extras incompatible with -gsheet_url')

            file_config_vars = vars(file_config)
            settings_list = []
            exclude = set(['anonymous', 'auth_key', 'backup_dir', 'config', 'copy_source', 'dest_dir', 'dry_run', 'google_login', 'gsheet_url', 'make', 'make_toc', 'modify_sessions', 'notebook', 'overwrite', 'preview', 'proxy_url', 'site_url', 'split_name', 'test_script', 'toc_header', 'topnav', 'verbose', 'file', 'separate', 'toc', 'index', 'qindex'])
            arg_names = file_config_vars.keys()
            arg_names.sort()
            for name in arg_names:
                value = file_config_vars[name]
                if name in exclude:
                    continue
                if name in Cmd_defaults:
                    if value == Cmd_defaults[name]:
                        continue
                elif value == Conf_parser.get_default(name):
                    continue
                # Non-default conf setting
                if isinstance(value, set):
                    if value:
                        temvals = list(value)
                        temvals.sort()
                        settings_list.append('--'+name+'='+','.join(temvals))
                elif isinstance(value, bool):
                    if value:
                        settings_list.append('--'+name)
                else:
                    settings_list.append('--'+name+'='+str(value))
            message(fname+' settings: '+' '.join(settings_list))
                    
            js_params['features'] = dict([(x, 1) for x in file_config.features])
            js_params['paceLevel'] = file_config.pace or 0
            if js_params['paceLevel']:
                # Note: pace does not work with combined files
                if file_config.release_date:
                    release_date_str = file_config.release_date if file_config.release_date == FUTURE_DATE else sliauth.get_utc_date(file_config.release_date)
                if file_config.due_date:
                    due_date_str = sliauth.get_utc_date(file_config.due_date)

                if file_config.vote_date:
                    vote_date_str = sliauth.get_utc_date(file_config.vote_date)

            js_params['sessionPrereqs'] =  file_config.prereqs or ''
            js_params['sessionRevision'] = file_config.revision or ''
            js_params['slideDelay'] = file_config.slide_delay or 0

            js_params['lateCredit'] = file_config.late_credit or 0
            js_params['participationCredit'] = file_config.participation_credit or 0
            js_params['maxRetakes'] = file_config.retakes or 0
                
            topnav_opts = file_config.topnav or ''
            gd_sheet_url = file_config.gsheet_url or ''
            js_params['gd_sheet_url'] = config.proxy_url if config.proxy_url and gd_sheet_url else gd_sheet_url
            js_params['plugin_share_voteDate'] = vote_date_str
            js_params['releaseDate'] = release_date_str
            js_params['dueDate'] = due_date_str
            js_params['fileName'] = fname

            if js_params['paceLevel'] >= ADMIN_PACE and not gd_sheet_url:
                abort('PACE-ERROR: Must specify -gsheet_url for --pace='+str(js_params['paceLevel']))

            if js_params['paceLevel'] >= ADMIN_PACE and 'randomize_choice' in file_config.features:
                abort('PACE-ERROR: randomize_choice feature not compatible with --pace='+str(js_params['paceLevel']))

        if not j or config.separate:
            # First file or separate files
            mathjax_config = ''
            if 'equation_number' in file_config.features:
                mathjax_config += r", TeX: { equationNumbers: { autoNumber: 'AMS' } }"
            if 'tex_math' in file_config.features:
                mathjax_config += r", tex2jax: { inlineMath: [ ['$','$'], ['\\(','\\)'] ], processEscapes: true }"
            math_inc = Mathjax_js % mathjax_config

        if not file_config.features.issubset(set(Features_all)):
            abort('Error: Unknown feature(s): '+','.join(list(file_config.features.difference(set(Features_all)))) )
            
        filepath = input_paths[fnumber-1]
        md_text = fhandle.read()
        fhandle.close()

        base_parser = md2md.Parser(base_mods_args)
        slide_parser = md2md.Parser(slide_mods_args)
        md_text_modified = slide_parser.parse(md_text, filepath)
        md_text = base_parser.parse(md_text, filepath)

        if file_config.hide and 'hidden' in file_config.strip:
            md_text_modified = re.sub(r'(^|\n *\n--- *\n( *\n)+) {0,3}#{2,3}[^#][^\n]*'+file_config.hide+r'.*?(\n *\n--- *\n|$)', r'\1', md_text_modified, flags=re.DOTALL)

        # Strip annotations
        md_text = re.sub(r"(^|\n) {0,3}[Aa]nnotation:(.*?)(\n|$)", '', md_text)

        if 'underline_headers' not in file_config.features:
            # Insert a blank line between hrule and any immediately preceding non-blank line (to avoid it being treated as a Markdown Setext-style header)
            md_text = HRULE_BREAK_RE.sub(r'\1\n\2', md_text)

        prev_file = '' if fnumber == 1      else orig_flinks[fnumber-2]
        next_file = '' if fnumber == nfiles else orig_flinks[fnumber]

        fheader, file_toc, renderer, md_html = md2html(md_text, filename=fname, config=file_config, filenumber=fnumber,
                                                        plugin_defs=base_plugin_defs, prev_file=prev_file, next_file=next_file,
                                                        index_id=index_id, qindex_id=qindex_id)
        plugin_list = list(renderer.plugin_embeds)
        plugin_list.sort()
        js_params['plugins'] = plugin_list
        if js_params['paceLevel']:
            # File-specific js_params
            js_params['pacedSlides'] = renderer.slide_number
            js_params['questionsMax'] = len(renderer.questions)
            js_params['scoreWeight'] = renderer.cum_weights[-1] if renderer.cum_weights else 0
            js_params['otherWeight'] = sum(q.get('vweight',0) for q in renderer.questions) if renderer.questions else 0
            js_params['gradeWeight'] = renderer.cum_gweights[-1] if renderer.cum_gweights else 0
            js_params['gradeFields'] = Score_fields[:] + (renderer.grade_fields[:] if renderer.grade_fields else [])
        else:
            js_params['pacedSlides'] = 0
            js_params['questionsMax'] = 0
            js_params['scoreWeight'] = 0
            js_params['otherWeight'] = 0
            js_params['gradeWeight'] = 0
            js_params['gradeFields'] = []

        js_params['totalWeight'] = js_params['scoreWeight'] + js_params['gradeWeight'] + js_params['otherWeight']
            
        max_params = {}
        max_params['id'] = '_max_score'
        max_params['source'] = 'slidoc'
        max_params['initTimestamp'] = None
        max_score_fields = [max_params.get(x,'') for x in Manage_fields+Session_fields]
        if js_params['paceLevel']:
            max_score_fields += ['', js_params['scoreWeight'], js_params['otherWeight'], '']
            max_score_fields += renderer.max_fields if renderer.max_fields else []

        all_concept_warnings += renderer.concept_warnings
        outname = fname+".html"
        flist.append( (fname, outname, release_date_str, fheader, file_toc) )
        
        comb_plugin_defs.update(renderer.plugin_defs)
        comb_plugin_loads.update(renderer.plugin_loads)
        math_in_file = renderer.render_markdown or (r'\[' in md_text and r'\]' in md_text) or (r'\(' in md_text and r'\)' in md_text)
        if math_in_file:
            math_found = True
        if renderer.render_markdown:
            pagedown_load = True
        if renderer.load_python:
            skulpt_load = True

        js_params['topnavList'] = []
        topnav_html = ''
        sessions_due_html = ''
        if topnav_opts:
            top_fname = 'home' if fname == 'index' else fname
            js_params['topnavList'] = get_topnav(topnav_opts, fnames=orig_fnames, site_name=config.site_name, separate=config.separate)
            topnav_html = '' if config.make_toc or config.toc else render_topnav(js_params['topnavList'], top_fname, site_name=config.site_name)
            sessions_due = []
            for opt in topnav_opts.split(','):
                if opt != '/index.html' and opt.endswith('/index.html'):
                    index_entries = read_index(dest_dir+opt)
                    for ind_fname, ind_fheader, doc_str, iso_due_str, iso_release_str in index_entries:
                        if iso_due_str and iso_due_str != '-':
                            sessions_due.append([os.path.dirname(opt)+'/'+ind_fname, ind_fname, doc_str, iso_due_str, iso_release_str])
            if sessions_due:
                sessions_due.sort(reverse=True)
                due_html = []
                for ind_fpath, ind_fname, doc_str, iso_due_str, iso_release_str in sessions_due:
                    if iso_release_str == FUTURE_DATE:
                        continue
                    release_epoch = 0
                    due_epoch = 0
                    if iso_release_str and iso_release_str != '-':
                        release_epoch = int(sliauth.epoch_ms(sliauth.parse_date(iso_release_str))/1000.0)
                    if iso_due_str and iso_due_str != '-':
                        due_epoch = int(sliauth.epoch_ms(sliauth.parse_date(iso_due_str))/1000.0)
                    doc_link = '''(<a class="slidoc-clickable" href="%s.html"  target="_blank">%s</a>)''' % (ind_fpath, doc_str)
                    due_html.append('<li class="slidoc-index-entry" data-release="%d" data-due="%d">%s: <span id="slidoc-toc-chapters-toggle" class="slidoc-toc-chapters">%s</span>%s<span class="slidoc-nosidebar"> %s</span></li>\n' % (release_epoch, due_epoch, iso_due_str[:10], ind_fname, SPACER6, doc_link))
                sessions_due_html = '<ul class="slidoc-toc-list" style="list-style-type: none;">\n' + '\n'.join(due_html) + '\n</ul>\n'
        md_html = md_html.replace('<p>SessionsDue:</p>', sessions_due_html)

        mid_params = {'session_name': fname,
                      'math_js': math_inc if math_in_file else '',
                      'pagedown_js': Pagedown_js if renderer.render_markdown else '',
                      'skulpt_js': Skulpt_js if renderer.load_python else '',
                      'body_class': 'slidoc-plain-page' if topnav_html else '',
                      'top_nav':  topnav_html,
                      'top_nav_hide': ' slidoc-topnav-hide' if topnav_html else ''}
        mid_params.update(SYMS)
        mid_params['plugin_tops'] = ''.join(renderer.plugin_tops)

        if not config.dry_run and gd_sheet_url:
            tem_attributes = renderer.sheet_attributes.copy()
            tem_attributes.update(params=js_params)
            tem_fields = Manage_fields+Session_fields+js_params['gradeFields']
            modify_session = (fname in config.modify_sessions)
            max_last_slide, modify_col, row_count = check_gdoc_sheet(gd_sheet_url, gd_hmac_key, js_params['fileName'], tem_fields,
                                                                     modify_session=modify_session)
            mod_due_date, modify_questions = update_session_index(gd_sheet_url, gd_hmac_key, fname, js_params['sessionRevision'],
                                 file_config.session_weight, file_config.session_rescale, release_date_str, due_date_str, file_config.media_url, js_params['paceLevel'],
                                 js_params['scoreWeight'], js_params['gradeWeight'], js_params['otherWeight'], tem_attributes,
                                 renderer.questions, renderer.question_concepts, renderer.qconcepts[0], renderer.qconcepts[1],
                                 max_last_slide=max_last_slide, debug=config.debug,
                                 row_count=row_count, modify_session=modify_session)

            admin_due_date[fname] = mod_due_date if js_params['paceLevel'] == ADMIN_PACE else ''

            if not modify_col and modify_questions:
                # Dummy modify col to force passthru
                modify_col = len(tem_fields) + 1
            update_gdoc_sheet(gd_sheet_url, gd_hmac_key, js_params['fileName'], tem_fields, row=max_score_fields, modify=modify_col)
            update_gdoc_sheet(gd_sheet_url, gd_hmac_key, LOG_SHEET, Log_fields)

        if js_params['paceLevel']:
            # Additional info for paced files
            if gd_sheet_url:
                if js_params['gradeWeight']:
                    file_type = 'graded'
                else:
                    file_type = 'scored'
            else:
                file_type = 'paced'

            doc_str = file_type + ' exercise'
            iso_release_str = '-'

            if release_date_str == FUTURE_DATE:
                doc_str += ', not available'
                iso_release_str = release_date_str
            elif release_date_str:
                release_date = sliauth.parse_date(release_date_str)
                iso_release_str = sliauth.iso_date(release_date)
                if sliauth.epoch_ms(release_date) > sliauth.epoch_ms():
                    # Session not yet released
                    rel_local_time = release_date.ctime()
                    if rel_local_time.endswith(':00.000Z'):
                        rel_local_time = rel_local_time[:-8]+'Z'
                    doc_str += ', available ' + rel_local_time

            admin_ended = bool(admin_due_date.get(fname))
            doc_date_str = admin_due_date[fname] if admin_ended else due_date_str
            iso_due_str = '-'
            if doc_date_str:
                date_time = sliauth.parse_date(doc_date_str)
                local_time_str = date_time.ctime()
                if admin_ended:
                    doc_str += ', ended '
                else:
                    doc_str += ', due '
                    iso_due_str = sliauth.iso_date(date_time)

                doc_str += (local_time_str[:-8]+'Z' if local_time_str.endswith(':00.000Z') else local_time_str)
            paced_files[fname] = {'type': file_type, 'release_date': iso_release_str, 'due_date': iso_due_str, 'doc_str': doc_str}

        if config.dry_run:
            message("Indexed ", outname+":", fheader)
        else:
            chapter_classes = 'slidoc-reg-chapter'
            if 'two_column' in file_config.features:
                chapter_classes += ' slidoc-two-column'

            if 'slide_break_avoid' in file_config.features:
                chapter_classes += ' slidoc-page-break-avoid'
            elif 'slide_break_page' in file_config.features:
                chapter_classes += ' slidoc-page-break-always'

            md_prefix = chapter_prefix(fnumber, chapter_classes, hide=js_params['paceLevel'] and not config.printable)
            md_suffix = '</article> <!--chapter end-->\n'
            if combined_file:
                combined_html.append(md_prefix)
                combined_html.append(md_html)
                combined_html.append(md_suffix)
            else:
                file_plugin_defs = base_plugin_defs.copy()
                file_plugin_defs.update(renderer.plugin_defs)
                file_head_html = css_html + ('\n<script>\n%s</script>\n' % templates['doc_include.js'].replace('JS_PARAMS_OBJ', json.dumps(js_params)) ) + ('\n<script>\n%s</script>\n' % templates['wcloud.js']) + add_scripts

                head = file_head_html + plugin_heads(file_plugin_defs, renderer.plugin_loads) + (mid_template % mid_params) + body_prefix
                if release_date_str != FUTURE_DATE:
                    # Prefix index entry as comment
                    if js_params['paceLevel']:
                        index_entries = [fname, fheader, paced_files[fname]['doc_str'], paced_files[fname]['due_date'], paced_files[fname]['release_date']]
                    else:
                        index_entries = [fname, fheader, 'view', '-', '-']
                    head = '\n'.join([Index_prefix] + index_entries + [Index_suffix, head])

                tail = md_prefix + md_html + md_suffix
                if Missing_ref_num_re.search(md_html) or return_html:
                    # Still some missing reference numbers; output file later
                    outfile_buffer.append([outname, dest_dir+outname, head, tail])
                else:
                    outfile_buffer.append([outname, dest_dir+outname, '', ''])
                    write_doc(dest_dir+outname, head, tail)

            if backup_dir:
                bakname = backup_dir+os.path.basename(input_paths[fnumber-1])[:-3]+'-bak.md'
                md2md.write_file(bakname)
                message('Backup copy of file written to '+bakname)

            if config.slides and not return_html:
                reveal_pars['reveal_title'] = fname
                # Wrap inline math in backticks to protect from backslashes being removed
                md_text_reveal = re.sub(r'\\\((.+?)\\\)', r'`\(\1\)`', md_text_modified)
                md_text_reveal = re.sub(r'(^|\n)\\\[(.+?)\\\]', r'\1`\[\2\]`', md_text_reveal, flags=re.DOTALL)
                if 'tex_math' in file_config.features:
                    md_text_reveal = re.sub(r'(^|[^\\\$])\$(?!\$)(.*?)([^\\\n\$])\$(?!\$)', r'\1`$\2\3$`', md_text_reveal)
                    md_text_reveal = re.sub(r'(^|\n)\$\$(.*?)\$\$', r'\1`$$\2\3$$`', md_text_reveal, flags=re.DOTALL)
                reveal_pars['reveal_md'] = md_text_reveal
                md2md.write_file(dest_dir+fname+"-slides.html", templates['reveal_template.html'] % reveal_pars)

            if config.notebook and not return_html:
                md_parser = md2nb.MDParser(nb_converter_args)
                md2md.write_file(dest_dir+fname+".ipynb", md_parser.parse_cells(md_text_modified))

    if not config.dry_run:
        if not combined_file:
            message('Created output files:', ', '.join(x[0] for x in outfile_buffer))
            for outname, outpath, head, tail in outfile_buffer:
                if tail:
                    # Update "missing" reference numbers and write output file
                    tail = Missing_ref_num_re.sub(Missing_ref_num, tail)
                    if return_html:
                        return outpath, Html_header+head+tail+Html_footer, messages
                    else:
                        write_doc(outpath, head, tail)
        if config.slides:
            message('Created *-slides.html files')
        if config.notebook:
            message('Created *.ipynb files')

    if toc_file:
        toc_path = dest_dir + toc_file
        toc_mid_params = {'session_name': '',
                          'math_js': '',
                          'pagedown_js': '',
                          'skulpt_js': '',
                          'plugin_tops': '',
                          'body_class': 'slidoc-plain-page',
                          'top_nav': render_topnav(topnav_list, toc_path, site_name=config.site_name) if topnav_list else '',
                          'top_nav_hide': ' slidoc-topnav-hide' if topnav_list else ''}
        toc_mid_params.update(SYMS)
        if config.toc_header:
            header_insert = md2md.read_file(config.toc_header)
            if config.toc_header.endswith('.md'):
                header_insert = MarkdownWithMath(renderer=MathRenderer(escape=False)).render(header_insert)
        else:
            header_insert = ''

        toc_html = []
        if config.index and (Global.primary_tags or Global.primary_qtags):
            toc_html.append(' '+nav_link('INDEX', config.site_url, config.index, hash='#'+index_chapter_id,
                                     separate=config.separate, printable=config.printable))

        toc_html.append('\n<ol class="slidoc-toc-list">\n' if 'sections' in config.strip else '\n<ul class="slidoc-toc-list" style="list-style-type: none;">\n')

        toc_list = []
        if config.make_toc:
            # Create ToC using header info from .html files
            for j, outpath in enumerate(orig_outpaths):
                if not os.path.exists(outpath):
                    abort('Output file '+outpath+' not readable for indexing')
                index_entries = read_index(outpath)
                if not index_entries:
                    message('Index header not found in '+outpath)
                    continue
                _, fheader, doc_str, iso_due_str, iso_release_str = index_entries[0]
                doc_link = ''
                if doc_str:
                    doc_link = '''(<a class="slidoc-clickable" href="%s.html"  target="_blank">%s</a>)''' % (orig_fnames[j], doc_str)
                toc_html.append('<li><span id="slidoc-toc-chapters-toggle" class="slidoc-toc-chapters">%s</span>%s<span class="slidoc-nosidebar"> %s</span></li>\n' % (fheader, SPACER6, doc_link))
                toc_list.append(orig_fnames[j])
                toc_list.append(fheader)
                toc_list.append(doc_str)
                toc_list.append(iso_due_str)
                toc_list.append(iso_release_str)
        else:
            # Create ToC using info from rendering
            for ifile, felem in enumerate(flist):
                fname, outname, release_date_str, fheader, file_toc = felem
                if release_date_str == FUTURE_DATE:
                    # Future release files not accessible from ToC
                    continue
                chapter_id = make_chapter_id(ifile+1)
                slide_link = ''
                if fname not in paced_files and config.slides:
                    slide_link = ' (<a href="%s%s" class="slidoc-clickable" target="_blank">%s</a>)' % (config.site_url, fname+"-slides.html", 'slides')
                nb_link = ''
                if fname not in paced_files and config.notebook and nb_site_url:
                    nb_link = ' (<a href="%s%s%s.ipynb" class="slidoc-clickable">%s</a>)' % (md2nb.Nb_convert_url_prefix, nb_site_url[len('http://'):], fname, 'notebook')

                if fname in paced_files:
                    doc_link = nav_link(paced_files[fname]['doc_str'], config.site_url, outname, target='_blank', separate=True)
                    toggle_link = '<span id="slidoc-toc-chapters-toggle" class="slidoc-toc-chapters">%s</span>' % (fheader,)
                    if test_params:
                        for label, query, proxy_query in test_params:
                            if config.proxy_url:
                                doc_link += ', <a href="/_auth/login/%s&next=%s" target="_blank">%s</a>' % (proxy_query, sliauth.safe_quote('/'+outname+query), label)
                            else:
                                doc_link += ', <a href="%s%s" target="_blank">%s</a>' % (outname, query, label)
                else:
                    doc_link = nav_link('view', config.site_url, outname, hash='#'+chapter_id,
                                        separate=config.separate, printable=config.printable)
                    toggle_link = '''<span id="slidoc-toc-chapters-toggle" class="slidoc-clickable slidoc-toc-chapters" onclick="Slidoc.idDisplay('%s-toc-sections');">%s</span>''' % (chapter_id, fheader)

                toc_html.append('<li>%s%s<span class="slidoc-nosidebar"> (%s)%s%s</span></li>\n' % (toggle_link, SPACER6, doc_link, slide_link, nb_link))

                if fname not in paced_files:
                    f_toc_html = ('\n<div id="%s-toc-sections" class="slidoc-toc-sections" style="display: none;">' % chapter_id)+file_toc+'\n<p></p></div>'
                    toc_html.append(f_toc_html)

        toc_html.append('</ol>\n' if 'sections' in config.strip else '</ul>\n')

        if config.toc and config.slides:
            toc_html.append('<em>Note</em>: When viewing slides, type ? for help or click <a class="slidoc-clickable" target="_blank" href="https://github.com/hakimel/reveal.js/wiki/Keyboard-Shortcuts">here</a>.\nSome slides can be navigated vertically.')

        toc_html.append('<p></p><em>'+Formatted_by+'</em><p></p>')

        if not config.dry_run:
            toc_insert = ''
            if config.toc and fname not in paced_files:
                toc_insert += click_span('+Contents', "Slidoc.hide(this,'slidoc-toc-sections');",
                                        classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-noprint'])
            if combined_file:
                toc_insert = click_span(SYMS['trigram'], "Slidoc.sidebarDisplay();",
                                    classes=['slidoc-clickable-sym', 'slidoc-nosidebar', 'slidoc-noprint']) + SPACER2 + toc_insert
                toc_insert = click_span(SYMS['trigram'], "Slidoc.sidebarDisplay();",
                                    classes=['slidoc-clickable-sym', 'slidoc-sidebaronly', 'slidoc-noprint']) + toc_insert
                toc_insert += SPACER3 + click_span('+All Chapters', "Slidoc.allDisplay(this);",
                                                  classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-noprint'])

            if toc_insert:
                toc_insert += '<br>'
            toc_output = chapter_prefix(0, 'slidoc-toc-container slidoc-noslide', hide=False)+header_insert+Toc_header+toc_insert+''.join(toc_html)+'</article>\n'
            if combined_file:
                all_container_prefix  = '<div id="slidoc-all-container" class="slidoc-all-container">\n'
                left_container_prefix = '<div id="slidoc-left-container" class="slidoc-left-container">\n'
                left_container_suffix = '</div> <!--slidoc-left-container-->\n'
                combined_html = [all_container_prefix, left_container_prefix, toc_output, left_container_suffix] + combined_html
            elif not return_html:
                if toc_list:
                    # Include file header info as HTML comment
                    toc_head_html = '\n'.join([Index_prefix]+toc_list+[Index_suffix]) + head_html
                else:
                    toc_head_html = head_html
                md2md.write_file(toc_path, Html_header, toc_head_html,
                                  mid_template % toc_mid_params, body_prefix, toc_output, Html_footer)
                message("Created ToC file:", toc_path)

    xref_list = []
    if config.index and (Global.primary_tags or Global.primary_qtags):
        first_references, covered_first, index_html = make_index(Global.primary_tags, Global.sec_tags, config.site_url, fprefix=fprefix, index_id=index_id, index_file='' if combined_file else config.index)
        if not config.dry_run:
            index_html= ' <b>CONCEPT</b>\n' + index_html
            if config.qindex:
                index_html = nav_link('QUESTION INDEX', config.site_url, config.qindex, hash='#'+qindex_chapter_id,
                                      separate=config.separate, printable=config.printable) + '<p></p>\n' + index_html
            if config.crossref:
                index_html = ('<a href="%s%s" class="slidoc-clickable">%s</a><p></p>\n' % (config.site_url, config.crossref, 'CROSS-REFERENCING')) + index_html

            index_output = chapter_prefix(nfiles+1, 'slidoc-index-container slidoc-noslide', hide=False) + back_to_contents +'<p></p>' + index_html + '</article>\n'
            if combined_file:
                combined_html.append('<div class="slidoc-noslide">'+index_output+'</div>\n')
            elif not return_html:
                md2md.write_file(dest_dir+config.index, index_output)
                message("Created index in", config.index)

        if config.crossref:
            if config.toc:
                xref_list.append('<a href="%s%s" class="slidoc-clickable">%s</a><p></p>\n' % (config.site_url, combined_file or config.toc, 'BACK TO CONTENTS'))
            xref_list.append("<h3>Concepts cross-reference (file prefix: "+fprefix+")</h3><p></p>")
            xref_list.append("\n<b>Concepts -> files mapping:</b><br>")
            for tag in first_references:
                links = ['<a href="%s%s.html#%s" class="slidoc-clickable" target="_blank">%s</a>' % (config.site_url, slide_file, slide_id, slide_file[len(fprefix):] or slide_file) for slide_file, slide_id, slide_header in first_references[tag]]
                xref_list.append(("%-32s:" % tag)+', '.join(links)+'<br>')

            xref_list.append("<p></p><b>Primary concepts covered in each file:</b><br>")
            for ifile, felem in enumerate(flist):
                fname, outname, release_date_str, fheader, file_toc = felem
                clist = covered_first[fname].keys()
                clist.sort()
                tlist = []
                for ctag in clist:
                    slide_id, slide_header = covered_first[fname][ctag]
                    tlist.append( '<a href="%s%s.html#%s" class="slidoc-clickable" target="_blank">%s</a>' % (config.site_url, fname, slide_id, ctag) )
                xref_list.append(('%-24s:' % fname[len(fprefix):])+'; '.join(tlist)+'<br>')
            if all_concept_warnings:
                xref_list.append('<pre>\n'+'\n'.join(all_concept_warnings)+'\n</pre>')

    if config.qindex and Global.primary_qtags:
        import itertools
        qout_list = []
        qout_list.append('<b>QUESTION CONCEPT</b>\n')
        first_references, covered_first, qindex_html = make_index(Global.primary_qtags, Global.sec_qtags, config.site_url, question=True, fprefix=fprefix, index_id=qindex_id, index_file='' if combined_file else config.qindex)
        qout_list.append(qindex_html)

        qindex_output = chapter_prefix(nfiles+2, 'slidoc-qindex-container slidoc-noslide', hide=False) + back_to_contents +'<p></p>' + ''.join(qout_list) + '</article>\n'
        if not config.dry_run:
            if combined_file:
                combined_html.append('<div class="slidoc-noslide">'+qindex_output+'</div>\n')
            elif not return_html:
                md2md.write_file(dest_dir+config.qindex, qindex_output)
                message("Created qindex in", config.qindex)

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

    if config.crossref and not return_html:
        md2md.write_file(dest_dir+config.crossref, ''.join(xref_list))
        message("Created crossref in", config.crossref)

    if combined_file:
        combined_html.append( '</div><!--slidoc-sidebar-right-wrapper-->\n' )
        combined_html.append( '</div><!--slidoc-sidebar-right-container-->\n' )
        if config.toc:
            combined_html.append( '</div><!--slidoc-sidebar-all-container-->\n' )

        comb_params = {'session_name': combined_name,
                       'math_js': math_inc if math_found else '',
                       'pagedown_js': Pagedown_js if pagedown_load else '',
                       'skulpt_js': Skulpt_js if skulpt_load else '',
                       'plugin_tops': '',
                       'body_class': '',
                       'top_nav': '',
                       'top_nav_hide': ''}
        comb_params.update(SYMS)
        all_plugin_defs = base_plugin_defs.copy()
        all_plugin_defs.update(comb_plugin_defs)
        output_data = [Html_header, head_html+plugin_heads(all_plugin_defs, comb_plugin_loads),
                       mid_template % comb_params, body_prefix,
                       '\n'.join(combined_html), Html_footer]
        message('Created combined HTML file in '+combined_file)
        if return_html:
            return dest_dir+combined_file, ''.join(output_data), messages
        md2md.write_file(dest_dir+combined_file, *output_data)


def sort_caseless(list):
    new_list = list[:]
    sorted(new_list, key=lambda s: s.lower())
    return new_list


Html_header = '''<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML//EN">
<html><head>
'''

Html_footer = '''
</body></html>
'''

Formatted_by = 'Document formatted by <a href="https://github.com/mitotic/slidoc" class="slidoc-clickable">slidoc</a>.'

Index_prefix = '\n<!--SlidocIndex'
Index_suffix = 'SlidocIndex-->\n'

Toc_header = '''
<h3>Table of Contents</h3>

'''

# Need latest version of Markdown for hooks
Pagedown_js = r'''
<script src='https://dl.dropboxusercontent.com/u/72208800/Pagedown/Markdown.Converter.js'></script>
<script src='https://dl.dropboxusercontent.com/u/72208800/Pagedown/Markdown.Sanitizer.js'></script>
<script src='https://dl.dropboxusercontent.com/u/72208800/Pagedown/Markdown.Extra.js'></script>
'''

Mathjax_js = r'''<script type="text/x-mathjax-config">
  MathJax.Hub.Config({
    skipStartupTypeset: true
    %s
  });
</script>
<script src='https://cdn.mathjax.org/mathjax/latest/MathJax.js?config=TeX-AMS-MML_HTMLorMML'></script>
'''

Skulpt_js_non_https = r'''
<script src="http://ajax.googleapis.com/ajax/libs/jquery/1.9.0/jquery.min.js" type="text/javascript"></script> 
<script src="http://www.skulpt.org/static/skulpt.min.js" type="text/javascript"></script> 
<script src="http://www.skulpt.org/static/skulpt-stdlib.js" type="text/javascript"></script> 
'''

Skulpt_js = r'''
<script src="https://dl.dropboxusercontent.com/u/72208800/Skulpt/jquery.min.js" type="text/javascript"></script> 
<script src="https://dl.dropboxusercontent.com/u/72208800/Skulpt/skulpt.min.js" type="text/javascript"></script> 
<script src="https://dl.dropboxusercontent.com/u/72208800/Skulpt/skulpt-stdlib.js" type="text/javascript"></script> 
'''


Google_docs_js = r'''
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

Select_file_args = set(['due_date', 'features', 'gsheet_url', 'late_credit', 'media_url', 'pace', 'participation_credit', 'prereqs', 'release_date', 'retakes', 'revision', 'session_rescale', 'session_weight', 'slide_delay', 'topnav', 'vote_date'])
    
def read_first_line(file):
    # Read first line of file and rewind it
    first_line = file.readline()
    file.seek(0)
    return first_line

def parse_merge_args(args_text, fname, parser, cmd_args_dict, exclude_args=set(), include_args=set(), first_line=False, verbose=False):
    # Read file args and merge with command line args, with command line args being final
    if first_line:
        match = re.match(r'^ {0,3}<!--slidoc-defaults\s+(.*?)-->\s*?\n', args_text)
        if match:
            args_text = match.group(1).strip()
        else:
            args_text = ''
    else:
        args_text = args_text.strip().replace('\n', ' ')

    try:
        if args_text:
            line_args_list = shlex.split(args_text)
            line_args_dict = vars(parser.parse_args(line_args_list))
        else:
            line_args_dict = dict([(arg_name, None) for arg_name in include_args]) if include_args else {}

        for arg_name in line_args_dict.keys():
            if include_args and arg_name not in include_args:
                del line_args_dict[arg_name]
            elif exclude_args and arg_name in exclude_args:
                del line_args_dict[arg_name]
            elif arg_name == 'features':
                # Convert feature string to set
                line_args_dict[arg_name] = md2md.make_arg_set(line_args_dict[arg_name], Features_all)
        if verbose:
            message('Read command line arguments from file', fname, argparse.Namespace(**line_args_dict))
    except Exception, excp:
        abort('slidoc: ERROR in parsing command options in first line of %s: %s' % (fname, excp))

    for arg_name in cmd_args_dict:
        if arg_name not in line_args_dict:
            # Argument not specified in file line (copy from command line)
            line_args_dict[arg_name] = cmd_args_dict[arg_name]

        elif cmd_args_dict[arg_name] is not None:
            # Argument also specified in command line
            if arg_name == 'features' and line_args_dict[arg_name] and 'override' not in cmd_args_dict[arg_name]:
                # Merge features from file with command line (unless 'override' feature is present in command line)
                line_args_dict[arg_name] = cmd_args_dict[arg_name].union(line_args_dict[arg_name])
            else:
                # Command line overrides file line
                line_args_dict[arg_name] = cmd_args_dict[arg_name]

    return argparse.Namespace(**line_args_dict)

def abort(msg):
    if __name__ == '__main__':
        sys.exit(msg)
    else:
        raise Exception(msg)

class RequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    output_html = 'NO DATA'
    mime_types = {'.gif': 'image/gif', '.jpg': 'image/jpg', '.jpeg': 'image/jpg', '.png': 'image/png'}
    def do_GET(self):
        if self.path == '/' or self.path.startswith('/?'):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(self.output_html)
        elif '..' not in self.path and os.path.exists(self.path[1:]):
            fext = os.path.splitext(os.path.basename(self.path[1:]))[1]
            mime_type = self.mime_types.get(fext.lower())
            if mime_type:
                self.send_response(200)
                self.send_header("Content-type", mime_type)
                self.end_headers()
                with open(self.path[1:]) as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
        else:
            self.send_response(404)
    
# Strip options
# For pure web pages, --strip=chapters,contents,navigate,sections
Strip_all = ['answers', 'chapters', 'concepts', 'contents', 'hidden', 'inline_js', 'navigate', 'notes', 'rule', 'sections']

# Features
#   adaptive_rubric: Track comment lines and display suggestions. Start comment lines with '(+/-n)...' to add/subtract points
#   assessment: Do not warn about concept coverage for assessment documents
#   disable_answering: Hide all answer buttons/input boxes (to generate closed book question sheets that are manually graded)
#   delay_answers: Correct answers and score are hidden from users until session is graded
#   equation_number: Number equations sequentially
#   grade_response: Grade text responses and explanations; provide comments
#   incremental_slides: Display portions of slides incrementally (only for the current last slide)
#   keep_extras: Keep Extra: portion of slides (incompatible with remote sheet)
#   override: Force command line feature set to override file-specific settings (by default, the features are merged)
#   progress_bar: Display progress bar during pace delays
#   quote_response: Display user response as quote (for grading)
#   randomize_choice: Choices are shuffled randomly. If there are alternative choices, they are picked together (randomly)
#   share_all: share responses for all questions
#   share_answers: share answers for all questions after completion (e.g., an exam)
#   show_correct: show correct answers for non-paced sessions
#   skip_ahead: Allow questions to be skipped if the previous sequnce of questions were all answered correctly
#   slide_break_avoid: Avoid page breaks within slide
#   slide_break_page: Force page breaks after each slide
#   slides_only: Only slide view is permitted; no scrolling document display
#   tex_math: Allow use of TeX-style dollar-sign delimiters for math
#   two_column: Two column output
#   underline_headers: Allow Setext-style underlined Level 2 headers permitted by standard Markdown
#   untitled_number: Untitled slides are automatically numbered (as in a sheet of questions)

Features_all = ['adaptive_rubric', 'assessment', 'delay_answers', 'dest_dir', 'disable_answering', 'equation_number', 'grade_response', 'incremental_slides', 'keep_extras', 'override', 'progress_bar', 'quote_response', 'randomize_choice', 'share_all', 'share_answers', 'show_correct', 'skip_ahead', 'slide_break_avoid', 'slide_break_page', 'slides_only', 'tex_math', 'two_column', 'underline_headers', 'untitled_number']

Conf_parser = argparse.ArgumentParser(add_help=False)
Conf_parser.add_argument('--all', metavar='FILENAME', help='Base name of combined HTML output file')
Conf_parser.add_argument('--crossref', metavar='FILE', help='Cross reference HTML file')
Conf_parser.add_argument('--css', metavar='FILE_OR_URL', help='Custom CSS filepath or URL (derived from doc_custom.css)')
Conf_parser.add_argument('--debug', help='Enable debugging', action="store_true", default=None)
Conf_parser.add_argument('--due_date', metavar='DATE_TIME', help="Due local date yyyy-mm-ddThh:mm (append 'Z' for UTC)")
Conf_parser.add_argument('--features', metavar='OPT1,OPT2,...', help='Enable feature %s|all|all,but,...' % ','.join(Features_all))
Conf_parser.add_argument('--fontsize', metavar='FONTSIZE[,PRINT_FONTSIZE]', help='Font size, e.g., 9pt')
Conf_parser.add_argument('--hide', metavar='REGEX', help='Hide sections with headers matching regex (e.g., "[Aa]nswer")')
Conf_parser.add_argument('--image_dir', metavar='DIR', help='image subdirectory (default: _images)')
Conf_parser.add_argument('--image_url', metavar='URL', help='URL prefix for images, including image_dir')
Conf_parser.add_argument('--images', help='images=(check|copy|export|import)[_all] to process images')
Conf_parser.add_argument('--indexed', metavar='TOC,INDEX,QINDEX', help='Table_of_contents,concep_index,question_index base filenames, e.g., "toc,ind,qind" (if omitted, all input files are combined, unless pacing)')
Conf_parser.add_argument('--late_credit', type=float, default=None, metavar='FRACTION', help='Fractional credit for late submissions, e.g., 0.25')
Conf_parser.add_argument('--media_url', metavar='URL', help='URL for media')
Conf_parser.add_argument('--pace', type=int, metavar='PACE_LEVEL', help='Pace level: 0 (none), 1 (basic-paced), 2 (question-paced), 3 (instructor-paced)')
Conf_parser.add_argument('--participation_credit', type=int, metavar='INTEGER', help='Participation credit: 0 (none), 1 (per question), 2 (for whole session)')
Conf_parser.add_argument('--plugins', metavar='FILE1,FILE2,...', help='Additional plugin file paths')
Conf_parser.add_argument('--prereqs', metavar='PREREQ_SESSION1,PREREQ_SESSION2,...', help='Session prerequisites')
Conf_parser.add_argument('--printable', help='Printer-friendly output', action="store_true", default=None)
Conf_parser.add_argument('--publish', help='Only process files with --public in first line', action="store_true", default=None)
Conf_parser.add_argument('--release_date', metavar='DATE_TIME', help="Release session on yyyy-mm-ddThh:mm (append 'Z' for UTC) or 'future' (test user always has access)")
Conf_parser.add_argument('--remote_logging', type=int, default=0, help='Remote logging level (0/1/2)')
Conf_parser.add_argument('--retakes', type=int, default=0, help='Max. number of retakes allowed (default: 0)')
Conf_parser.add_argument('--revision', metavar='REVISION', help='File revision')
Conf_parser.add_argument('--session_rescale', help='Session rescale (curve) parameters, e.g., *2,^0.5')
Conf_parser.add_argument('--session_weight', type=float, default=None, metavar='WEIGHT', help='Session weight')
Conf_parser.add_argument('--slide_delay', metavar='SEC', type=int, help='Delay between slides for paced sessions')
Conf_parser.add_argument('--strip', metavar='OPT1,OPT2,...', help='Strip %s|all|all,but,...' % ','.join(Strip_all))
Conf_parser.add_argument('--vote_date', metavar='VOTE_DATE_TIME]', help="Votes due local date yyyy-mm-ddThh:mm (append 'Z' for UTC)")

alt_parser = argparse.ArgumentParser(parents=[Conf_parser], add_help=False)
alt_parser.add_argument('--anonymous', help='Allow anonymous access (also unset REQUIRE_LOGIN_TOKEN)', action="store_true", default=None)
alt_parser.add_argument('--auth_key', metavar='DIGEST_AUTH_KEY', help='digest_auth_key (authenticate users with HMAC)')
alt_parser.add_argument('--backup_dir', default='_backup', help='Directory to create backup files for last valid version in when dest_dir is specified')
alt_parser.add_argument('--config', metavar='CONFIG_FILENAME', help='File containing default command line')
alt_parser.add_argument('--copy_source', help='Create a modified copy (only if dest_dir is specified)', action="store_true", default=None)
alt_parser.add_argument('--dest_dir', metavar='DIR', help='Destination directory for creating files')
alt_parser.add_argument('--dry_run', help='Do not create any HTML files (index only)', action="store_true", default=None)
alt_parser.add_argument('--google_login', metavar='CLIENT_ID,API_KEY', help='client_id,api_key (authenticate via Google; not used)')
alt_parser.add_argument('--gsheet_url', metavar='URL', help='Google spreadsheet_url (export sessions to Google Docs spreadsheet)')
alt_parser.add_argument('--make', help='Make mode: only process .md files that are newer than corresponding .html files', action="store_true", default=None)
alt_parser.add_argument('--make_toc', help='Create Table of Contents in index.html using *.html output', action="store_true", default=None)
alt_parser.add_argument('--modify_sessions', metavar='SESSION1,SESSION2,...', help='Sessions with questions to be modified')
alt_parser.add_argument('--notebook', help='Create notebook files', action="store_true", default=None)
alt_parser.add_argument('--overwrite', help='Overwrite files', action="store_true", default=None)
alt_parser.add_argument('--preview', type=int, default=0, metavar='PORT', help='Preview document in browser using specified localhost port')
alt_parser.add_argument('--pptx_options', metavar='PPTX_OPTS', default='', help='Powerpoint conversion options (comma-separated)')
alt_parser.add_argument('--proxy_url', metavar='URL', help='Proxy spreadsheet_url')
alt_parser.add_argument('--site_name', metavar='SITE', help='Site name (default: "")')
alt_parser.add_argument('--site_url', metavar='URL', help='URL prefix to link local HTML files (default: "")')
alt_parser.add_argument('--slides', metavar='THEME,CODE_THEME,FSIZE,NOTES_PLUGIN', help='Create slides with reveal.js theme(s) (e.g., ",zenburn,190%%")')
alt_parser.add_argument('--split_name', default='', metavar='CHAR', help='Character to split filenames with and retain last non-extension component, e.g., --split_name=-')
alt_parser.add_argument('--test_script', help='Enable scripted testing(=1 OR SCRIPT1[/USER],SCRIPT2/USER2,...)')
alt_parser.add_argument('--toc_header', metavar='FILE', help='.html or .md header file for ToC')
alt_parser.add_argument('--topnav', metavar='PATH,PATH2,...', help='=dirs/files/args/path1,path2,... Create top navigation bar (from subdirectory names, HTML filenames, argument filenames, or pathnames)')
alt_parser.add_argument('-v', '--verbose', help='Verbose output', action="store_true", default=None)

cmd_parser = argparse.ArgumentParser(parents=[alt_parser], description='Convert from Markdown to HTML')
cmd_parser.add_argument('file', help='Markdown/pptx filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)

# Some arguments need to be set explicitly to '' by default, rather than staying as None
Cmd_defaults = {'css': '', 'dest_dir': '', 'hide': '', 'image_dir': '_images', 'image_url': '',
                'site_name': '', 'site_url': ''}
    
def cmd_args2dict(cmd_args):
    # Assign default (non-None) values to arguments not specified anywhere
    for arg_name in Cmd_defaults:
        if getattr(cmd_args, arg_name) == None:
            setattr(cmd_args, arg_name, Cmd_defaults[arg_name]) 

    return vars(cmd_args)

if __name__ == '__main__':
    cmd_args_orig = cmd_parser.parse_args()
    if cmd_args_orig.config:
        cmd_args = parse_merge_args(md2md.read_file(cmd_args_orig.config), cmd_args_orig.config, Conf_parser, vars(cmd_args_orig),
                                    verbose=cmd_args_orig.verbose)
    else:
        # Read default args from first line of first file
        # Do not exclude args if combined file
        exclude_args = Select_file_args if cmd_args_orig.all is None else None
        cmd_args = parse_merge_args(read_first_line(cmd_args_orig.file[0]), cmd_args_orig.file[0].name, Conf_parser, vars(cmd_args_orig),
                                    exclude_args=exclude_args, first_line=True, verbose=cmd_args_orig.verbose)

    config_dict = cmd_args2dict(cmd_args)

    settings = {}
    if cmd_args.gsheet_url:
        try:
            settings = sliauth.read_settings(cmd_args.gsheet_url, cmd_args.auth_key, SETTINGS_SHEET)
        except Exception, excp:
            print('Error in reading settings: %s', str(excp), file=sys.stderr)

    fhandles = config_dict.pop('file')
    input_files = []
    skipped = []
    for fhandle in fhandles:
        first_line = read_first_line(fhandle)
        if cmd_args_orig.publish and (not first_line.strip().startswith('<!--slidoc-defaults') or '--publish' not in first_line):
            # Skip files without --publish option in the first line
            skipped.append(fhandle.name)
            continue
        input_files.append(fhandle)

    if not input_files:
        sys.exit('No --publish files to process!')

    if skipped:
        print('\n******Skipped non-publish files: %s\n' % ', '.join(skipped), file=sys.stderr)

    if cmd_args.verbose:
        print('Effective argument list', file=sys.stderr)
        print('    ', argparse.Namespace(**config_dict), file=sys.stderr)

    pptx_opts = {}
    if cmd_args.pptx_options:
        for opt in cmd_args.pptx_options.split(','):
            pptx_opts[opt] = True

    input_paths = [f.name for f in input_files]
    for j, inpath in enumerate(input_paths):
        fext = os.path.splitext(os.path.basename(inpath))[1]
        if fext == '.pptx':
            # Convert .pptx to .md
            ppt_parser = pptx2md.PPTXParser(pptx_opts)
            md_text = ppt_parser.parse_pptx(input_files[j], input_files[j].name)
            input_files[j].close()
            input_files[j] = cStringIO.StringIO(md_text.encode('utf8'))
            input_paths[j] = input_paths[j][:-len('.pptx')]+'.md'

    if cmd_args_orig.preview:
        if len(input_files) != 1:
            raise Exception('ERROR: --preview only works for a singe file')
        outname, RequestHandler.output_html, messages = process_input(input_files, input_paths, config_dict, return_html=True)
        for msg in messages:
            print(msg, file=sys.stderr)
        httpd = BaseHTTPServer.HTTPServer(('localhost', cmd_args_orig.preview), RequestHandler)
        command = "sleep 1 && open -a 'Google Chrome' http://localhost:%d" % cmd_args_orig.preview
        print('Preview at http://localhost:'+str(cmd_args_orig.preview), file=sys.stderr)
        print(command, file=sys.stderr)
        subp = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True, stderr=subprocess.STDOUT)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        httpd.server_close()
    else:
        process_input(input_files, input_paths, config_dict)

        if cmd_args.printable:
            if cmd_args.gsheet_url:
                print("To convert .html to .pdf, use proxy to allow XMLHTTPRequest:\n  wkhtmltopdf -s Letter --print-media-type --cookie slidoc_server 'username::token:' --javascript-delay 5000 http://localhost/file.html file.pdf", file=sys.stderr)
            else:
                print("To convert .html to .pdf, use:\n  wkhtmltopdf -s Letter --print-media-type --javascript-delay 5000 file.html file.pdf", file=sys.stderr)
            print("Additional options that may be useful are:\n  --debug-javascript --load-error-handling ignore --enable-local-file-access --header-right 'Page [page] of [toPage]'", file=sys.stderr)
