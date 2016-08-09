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
import base64
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
import md2nb
import sliauth

from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound

from xml.etree import ElementTree

INDEX_SHEET = 'sessions_slidoc'
SCORE_SHEET = 'scores_slidoc'
LOG_SHEET = 'slidoc_log'
MAX_QUERY = 500   # Maximum length of query string for concept chains
SPACER6 = '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
SPACER2 = '&nbsp;&nbsp;'
SPACER3 = '&nbsp;&nbsp;&nbsp;'

SYMS = {'prev': '&#9668;', 'next': '&#9658;', 'return': '&#8617;', 'up': '&#9650;', 'down': '&#9660;',
        'pencil': '&#9998;', 'house': '&#8962;', 'circle': '&#9673;', 'square': '&#9635;',
        'leftpair': '&#8647;', 'rightpair': '&#8649;'}

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

def add_to_index(primary_tags, sec_tags, tags, filename, slide_id, header='', qconcepts=None):
    if not tags:
        return

    # Save tags in proper case and then lowercase tags
    for tag in tags:
        if tag and tag not in Global.all_tags:
            Global.all_tags[tag.lower()] = tag
        
    tags = [x.lower() for x in tags]

    # By default assume only first tag is primary
    primary_tags_offset = 1
    sec_tags_offset = 1
    for j, tag in enumerate(tags):
        if not tag:
            # Null tag (if present) demarcates primary and secondary tags
            primary_tags_offset = j
            sec_tags_offset = j+1
            break

    p_tags = [x for x in tags[:primary_tags_offset] if x]
    s_tags = [x for x in tags[sec_tags_offset:] if x]
        
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
    plugin_begin  =   re.compile(r'^PluginBegin:\s*(\w+).init\s*\(([^\n]*)\)\s*\n(.*\n)*PluginEnd:\s*\1\s*(\n|$)',
                                                re.DOTALL)
    plugin_init   =   re.compile(r'^=(\w+).init\s*\(([^\n]*)\)\s*(\n\s*\n|\n$|$)')
    slidoc_header =   re.compile(r'^ {0,3}<!--(meldr|slidoc)-(\w+)\s+(.*?)-->\s*?\n')
    slidoc_answer =   re.compile(r'^ {0,3}(Answer|Ans):(.*?)(\n|$)')
    slidoc_concepts = re.compile(r'^ {0,3}(Concepts):(.*?)\n\s*(\n|$)', re.DOTALL)
    slidoc_notes =    re.compile(r'^ {0,3}(Notes):\s*?((?=\S)|\n)')
    slidoc_weight =   re.compile(r'^ {0,3}(Weight):(.*?)(\n|$)')
    minirule =        re.compile(r'^(--) *(?:\n+|$)')
    pause =           re.compile(r'^(\.\.\.) *(?:\n+|$)')

class MathBlockLexer(mistune.BlockLexer):
    def __init__(self, rules=None, **kwargs):
        if rules is None:
            rules = MathBlockGrammar()
        config = kwargs.get('config')
        slidoc_rules = ['block_math', 'latex_environment', 'plugin_definition', 'plugin_begin',  'plugin_init', 'slidoc_header', 'slidoc_answer', 'slidoc_concepts', 'slidoc_notes', 'slidoc_weight', 'minirule']
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

    def parse_plugin_begin(self, m):
         self.tokens.append({
            'type': 'slidoc_plugin',
            'name': m.group(1),
            'text': m.group(2)+'\n'+(m.group(3) or '')
        })

    def parse_plugin_init(self, m):
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

    def parse_slidoc_notes(self, m):
         self.tokens.append({
            'type': 'slidoc_notes',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_weight(self, m):
         self.tokens.append({
            'type': 'slidoc_weight',
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
    slidoc_choice = re.compile(r"^ {0,3}([a-pA-P])(\*)?\.\. +")
    block_math =    re.compile(r"^\\\[(.+?)\\\]", re.DOTALL)
    inline_math =   re.compile(r"^\\\((.+?)\\\)")
    tex_inline_math=re.compile(r"\$(?!\$)(.*?)([^\\\n\$])\$(?!\$)")
    inline_js =     re.compile(r"^`=(\w+)\.(\w+)\(\s*(\d*)\s*\)(;([^`\n]+))?`")
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

    def output_slidoc_notes(self):
        return self.renderer.slidoc_notes(self.token['name'], self.token['text'])

    def output_slidoc_weight(self):
        return self.renderer.slidoc_weight(self.token['name'], self.token['text'])

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

        return self.renderer.slide_prefix(self.renderer.first_id)+first_slide_pre+concept_chain(self.renderer.first_id, self.renderer.options['config'].site_url)+html+self.renderer.end_slide(last_slide=True)

    
class MathRenderer(mistune.Renderer):
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
    ansprefix_template = '''<span id="%(sid)s-answer-prefix" data-qnumber="%(qno)d">Answer:</span>'''
    answer_template = '''
  <span id="%(sid)s-answer-prefix" class="slidoc-answeredonly" data-qnumber="%(qno)d">Answer:</span>
  <button id="%(sid)s-answer-click" class="slidoc-clickable slidoc-answer-button slidoc-noadmin slidoc-noanswered" onclick="Slidoc.answerClick(this, '%(sid)s');">Answer</button>
  <input id="%(sid)s-answer-input" type="%(inp_type)s" class="slidoc-answer-input slidoc-answer-box slidoc-noadmin slidoc-noanswered slidoc-noplugin" onkeydown="Slidoc.inputKeyDown(event);"></input>

  <span class="slidoc-answer-span slidoc-answeredonly">
    <span id="%(sid)s-response-span"></span>
    <span id="%(sid)s-correct-mark" class="slidoc-correct-answer"></span>
    <span id="%(sid)s-partcorrect-mark" class="slidoc-partcorrect-answer"></span>
    <span id="%(sid)s-wrong-mark" class="slidoc-wrong-answer"></span>
    <span id="%(sid)s-any-mark" class="slidoc-any-answer"></span>
    <span id="%(sid)s-answer-correct" class="slidoc-answer-correct slidoc-correct-answer"></span>
  </span>
  %(explain)s
  <textarea id="%(sid)s-answer-textarea" name="textarea" class="slidoc-answer-textarea slidoc-answer-box slidoc-noadmin slidoc-noanswered slidoc-noplugin" cols="60" rows="5"></textarea>
'''                

    grading_template = '''
  <div class="slidoc-grade-element slidoc-answeredonly">
    <button id="%(sid)s-gstart-click" class="slidoc-clickable slidoc-gstart-click slidoc-grade-button slidoc-adminonly slidoc-nograding" onclick="Slidoc.gradeClick(this, '%(sid)s');">Start</button>
    <button id="%(sid)s-grade-click" class="slidoc-clickable slidoc-grade-click slidoc-grade-button slidoc-adminonly slidoc-gradingonly" onclick="Slidoc.gradeClick(this,'%(sid)s');">Save</button>
    <span id="%(sid)s-gradeprefix" class="slidoc-grade slidoc-gradeprefix slidoc-admin-graded"><em>Grade:</em></span>
    <input id="%(sid)s-grade-input" type="number" class="slidoc-grade-input slidoc-adminonly slidoc-gradingonly" onkeydown="Slidoc.inputKeyDown(event);"></input>
    <span id="%(sid)s-grade-content" class="slidoc-grade slidoc-grade-content slidoc-nograding"></span>
    <span id="%(sid)s-gradesuffix" class="slidoc-grade slidoc-gradesuffix slidoc-admin-graded"></span>
  </div>
'''
    comments_template_a = '''
  <textarea id="%(sid)s-comments-textarea" name="textarea" class="slidoc-comments-textarea slidoc-gradingonly" cols="60" rows="5" >  </textarea>
'''
    render_template = '''
  <button id="%(sid)s-render-button" class="slidoc-clickable slidoc-render-button" onclick="Slidoc.renderText(this,'%(sid)s');">Render</button>
'''
    quote_template = '''
  <button id="%(sid)s-quote-button" class="slidoc-clickable slidoc-quote-button slidoc-gradingonly" onclick="Slidoc.quoteText(this,'%(sid)s');">Quote</button>
'''
    comments_template_b = '''              
<div id="%(sid)s-comments" class="slidoc-comments slidoc-comments-element slidoc-answeredonly slidoc-admin-graded"><em>Comments:</em>
  <span id="%(sid)s-comments-content" class="slidoc-comments-content"></span>
</div>
'''
    response_div_template = '''  <div id="%(sid)s-response-div" class="slidoc-response-div slidoc-noplugin"></div>\n'''
    response_pre_template = '''  <pre id="%(sid)s-response-div" class="slidoc-response-div slidoc-noplugin"></pre>\n'''

    # Suffixes of input/textarea elements that need to be cleaned up
    input_suffixes = ['-answer-input', '-answer-textarea', '-grade-input', '-comments-textarea']

    # Suffixes of span/div/pre elements that need to be cleaned up
    content_suffixes = ['-response-span', '-correct-mark', '-partcorrect-mark', '-wrong-mark', '-any-mark', '-answer-correct',
                        '-grade-content','-comments-content', '-response-div'] 
    
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
        self.cum_weights = []
        self.cum_gweights = []
        self.grade_fields = []
        self.max_fields = []
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
        self.render_markdown = False
        self.plugin_number = 0
        self.plugin_defs = {}
        self.plugin_loads = set()
        self.load_python = False

    def _new_slide(self):
        self.slide_number += 1
        self.qtypes.append('')
        self.choices = None
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
        if action in ('create', 'globalInit', 'init', 'disable', 'display', 'expect', 'response'):
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

    def end_notes(self):
        s = self.notes_end or ''
        self.notes_end = None
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

    def end_slide(self, suffix_html='', last_slide=False):
        if not self.slide_plugin_refs.issubset(self.slide_plugin_embeds):
            message("    ****PLUGIN-ERROR: %s: Missing plugins %s in slide %s." % (self.options["filename"], list(self.slide_plugin_refs.difference(self.slide_plugin_embeds)), self.slide_number))
        if self.qtypes[-1]:
            # Question slide
            if self.options['config'].pace and last_slide:
                abort('***ERROR*** Last slide cannot be a question slide for paced mode in session '+self.options["filename"])
            if len(self.questions) == 1:
                self.cum_weights.append(self.questions[-1]['weight'])
                self.cum_gweights.append(self.questions[-1]['gweight'])
            else:
                self.cum_weights.append(self.questions[-1]['weight'] + self.cum_weights[-1])
                self.cum_gweights.append(self.questions[-1]['gweight']+ self.cum_gweights[-1])

            if 'grade_response' in self.options['config'].features:
                qno = 'q%d' % len(self.questions)
                fields = []
                if self.qtypes[-1].startswith('text/'):
                    fields = [qno+'_response']
                elif self.questions[-1].get('explain'):
                    fields = [qno+'_response', qno+'_explain']
                if fields:
                    self.grade_fields += fields
                    self.max_fields += ['' for field in fields]
                    if self.questions[-1]['gweight']:
                        self.grade_fields += [qno+'_grade']
                        self.max_fields += [self.questions[-1]['gweight']]
                    self.grade_fields += [qno+'_comments']
                    self.max_fields += ['']

            if self.options['config'].pace and self.slide_forward_links:
                # Handle forward link in current question
                self.qforward[self.slide_forward_links[0]].append(len(self.questions))
                if len(self.slide_forward_links) > 1:
                    message("    ****ANSWER-ERROR: %s: Multiple forward links in slide %s. Only first link (%s) recognized." % (self.options["filename"], self.slide_number, self.slide_forward_links[0]))

        ###if self.cur_qtype and not self.qtypes[-1]:
        ###    message("    ****ANSWER-ERROR: %s: 'Answer:' missing for %s question in slide %s" % (self.options["filename"], self.cur_qtype, self.slide_number))

        return self.end_notes()+self.end_hide()+suffix_html+('</section><!--%s-->\n' % ('last slide end' if last_slide else 'slide end'))

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

    def slidoc_choice(self, name, star):
        value = name if star else ''
        if not self.choices:
            if name != 'A':
                return name+'..'
            self.choices = [value]
        else:
            if ord(name) != ord('A')+len(self.choices):
                # Out of sequence choice; ignore
                return name+'..'
            self.choices.append(value)

        prefix = ''
        if len(self.choices) == 1:
            prefix = '</p><blockquote><p>\n'
            self.choice_end = '</blockquote>\n'

        self.cur_choice = name

        params = {'id': self.get_slide_id(), 'opt': name}
        if self.options['config'].hide or self.options['config'].pace:
            return prefix+'''<span id="%(id)s-choice-%(opt)s" data-choice="%(opt)s" class="slidoc-clickable %(id)s-choice slidoc-choice" onclick="Slidoc.choiceClick(this, '%(id)s', '%(opt)s');"+'">%(opt)s</span>. ''' % params
        else:
            return prefix+'''<span id="%(id)s-choice-%(opt)s" class="%(id)s-choice slidoc-choice">%(opt)s</span>. ''' % params

    
    def plugin_definition(self, name, text):
        _, self.plugin_defs[name] = parse_plugin(name+' = {'+text)
        return ''

    def embed_plugin_body(self, plugin_name, slide_id, args='', content=''):
        if plugin_name in self.slide_plugin_embeds:
            abort('ERROR Multiple instances of plugin '+plugin_name+' in slide '+self.slide_number)
        self.slide_plugin_embeds.add(plugin_name)
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

        plugin_params = {'pluginSlideId': slide_id,
                         'pluginName': plugin_name,
                         'pluginLabel': 'slidoc-plugin-'+plugin_name,
                         'pluginId': slide_id+'-plugin-'+plugin_name,
                         'pluginInitArgs': urllib.quote(args),
                         'pluginNumber': self.plugin_number,
                         'pluginButton': urllib.quote(plugin_def.get('Button', ''))}
        tem_params = plugin_params.copy()
        try:
            tem_params['pluginBodyDef'] = plugin_def.get('Body', '') % plugin_params
        except Exception, err:
            abort('ERROR Template formatting error in Body for plugin %s in slide %s: %s' % (plugin_name, self.slide_number, err))
        body_div = self.plugin_body_template % tem_params
        if '%(pluginBody)s' not in content:
            # By default, insert plugin body after any content
            content += '%(pluginBody)s'
        try:
            plugin_params['pluginContent'] = content.replace('%(pluginBody)s', body_div, 1) % plugin_params
        except Exception, err:
            abort('ERROR Template formatting error for plugin %s in slide %s: %s' % (plugin_name, self.slide_number, err))
        return self.plugin_content_template % plugin_params

    def slidoc_plugin(self, name, text):
        args, sep, content = text.partition('\n')
        self.plugin_loads.add(name)
        return self.embed_plugin_body(name, self.get_slide_id(), args=args.strip(), content=content)

    def slidoc_answer(self, name, text):
        if self.cur_answer:
            # Ignore multiple answers
            return ''
        self.cur_answer = True

        html_prefix = ''
        if self.choice_end:
            html_prefix = self.choice_end
            self.choice_end = ''

        explain_answer = ''
        explain_match = re.match(r'(^|.*\s)(explain(=(\w+))?)\s*$', text)
        if explain_match:
            text = text[:-len(explain_match.group(0))].strip()
            explain_answer = explain_match.group(4) or 'text'

        slide_id = self.get_slide_id()
        plugin_name = ''
        plugin_action = ''
        plugin_match = re.match(r'^(\w+)\.(expect|response)\(\)(;(.+))?$', text)
        if text.lower() in ('text/x-python', 'text/x-javascript', 'text/x-test'):
            plugin_name = 'code'
            plugin_action = 'response'
        elif plugin_match:
            plugin_name = plugin_match.group(1)
            plugin_action = plugin_match.group(2)
            text = plugin_match.group(4) or ''

        if plugin_name:
            if 'inline_js' in self.options['config'].strip and plugin_action == 'expect':
                plugin_name = ''
                plugin_action = ''
            elif plugin_name not in self.slide_plugin_embeds:
                html_prefix += self.embed_plugin_body(plugin_name, slide_id)
            
        if plugin_name:
            self.plugin_loads.add(plugin_name)

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
                message("    ****ANSWER-ERROR: %s: 'Answer: %s' is not a valid numeric answer; expect 'ans +/- err' in slide %s" % (self.options["filename"], text, self.slide_number))

        elif text.lower() in ('choice', 'multichoice', 'number', 'text', 'text/x-code', 'text/x-python', 'text/x-javascript', 'text/x-test', 'text/markdown', 'text/multiline', 'point', 'line'):
            # Unspecified answer
            qtype = text.lower()
            text = ''

        if self.choices:
            if not qtype or qtype in ('choice', 'multichoice'):
                # Correct choice(s)
                choices_str = ''.join(self.choices)
                if choices_str:
                    text = choices_str
                else:
                    text = ''.join(x for x in text if ord(x) >= ord('A') and ord(x)-ord('A') < len(self.choices))

                if qtype == 'choice':
                    if len(text) > 1:
                        message("    ****ANSWER-ERROR: %s: 'Answer: %s' expect single choice in slide %s" % (self.options["filename"], text, self.slide_number))
                    text = text[0] if text else ''
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

        if self.cur_qtype == 'text/x-python':
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

        grade_response = 'grade_response' in self.options['config'].features

        multiline_answer = self.cur_qtype.startswith('text/')
        if multiline_answer:
            explain_answer = ''      # Explain not compatible with textarea input

        self.qtypes[-1] = self.cur_qtype
        self.questions.append({})
        if plugin_name:
            correct_val = plugin_name + '.' + plugin_action + '()'
            if correct_text:
                correct_val = correct_val + ';' + correct_text
        else:
            correct_val = correct_text
        self.questions[-1].update(qnumber=len(self.questions), qtype=self.cur_qtype, slide=self.slide_number, correct=correct_val,
                                  explain=explain_answer, weight=1, gweight=0)
        if correct_html and correct_html != correct_text:
            self.questions[-1].update(html=correct_html)
        if self.block_input_counter:
            self.questions[-1].update(input=self.block_input_counter)
        if self.slide_block_test:
            self.questions[-1].update(test=self.slide_block_test)
        if self.slide_block_output:
            self.questions[-1].update(output=self.slide_block_output)

        id_str = self.get_slide_id()
        ans_params = { 'sid': id_str, 'qno': len(self.questions)}
        if not self.options['config'].pace and ('answers' in self.options['config'].strip or not correct_val):
            # Strip any correct answers
            return html_prefix+(self.ansprefix_template % ans_params)+'<p></p>\n'

        hide_answer = self.options['config'].hide or self.options['config'].pace
        if len(self.slide_block_test) != len(self.slide_block_output):
            hide_answer = False
            message("    ****ANSWER-ERROR: %s: Test block count %d != output block_count %d in slide %s" % (self.options["filename"], len(self.slide_block_test), len(self.slide_block_output), self.slide_number))

        if not hide_answer:
            # No hiding of correct answers
            return html_prefix+(self.ansprefix_template % ans_params)+' '+correct_html+'<p></p>\n'

        slide_markdown = (self.cur_qtype == 'text/markdown' or explain_answer == 'markdown')

        ans_classes = ''
        if multiline_answer:
            ans_classes += ' slidoc-multiline-answer'
        if explain_answer:
            ans_classes += ' slidoc-explain-answer'
        if self.cur_qtype in ('choice', 'multichoice'):
            ans_classes += ' slidoc-choice-answer'
        if plugin_name and plugin_action != 'expect':
            ans_classes += ' slidoc-answer-plugin'

        ans_params.update(ans_classes=ans_classes,
                        inp_type='number' if self.cur_qtype == 'number' else 'text',
                        explain=('<br><span id="%s-explainprefix" class="slidoc-explainprefix"><em>Explain:</em></span>' % id_str) if explain_answer else '')

        html_template = '''\n<div id="%(sid)s-answer-container" class="slidoc-answer-container %(ans_classes)s">\n'''+self.answer_template

        if grade_response:
            html_template += self.grading_template     # Hidden later by doc_include.js, if zero gweight
            html_template += self.comments_template_a

        if slide_markdown:
            self.render_markdown = True
            html_template += self.render_template

        if multiline_answer or explain_answer:
            html_template += self.quote_template

        if grade_response:
            html_template += self.comments_template_b

        if self.cur_qtype == 'text/x-code':
            html_template += self.response_pre_template
        else:
            html_template += self.response_div_template

        html_template +='''</div>\n'''

        ans_html = html_template % ans_params
            
        return html_prefix+ans_html+'\n'


    def slidoc_weight(self, name, text):
        if not text:
            return ''

        if not self.qtypes[-1]:
            message("    ****WEIGHT-ERROR: %s: Unexpected 'Weight: %s' line in non-question slide %s" % (self.options["filename"], text, self.slide_number))
            return ''
        weight, gweight = None, None
        match = re.match(r'^([0-9\.]+)(\s*,\s*([0-9\.]+))?$', text)
        if match:
            weight = parse_number(match.group(1))
            gweight = parse_number(match.group(3)) if match.group(3) is not None else 0

        if weight is None or (match.group(3) is not None and gweight is None):
            message("    ****WEIGHT-ERROR: %s: Error in parsing 'Weight: %s' line ignored; expected 'Weight: number[,number]' in slide %s" % (self.options["filename"], text, self.slide_number))
            return ''

        gweight = gweight or 0

        if gweight and not self.qtypes[-1].startswith('text/') and not self.questions[-1].get('explain'):
            message("    ****WEIGHT-ERROR: %s: Unexpected grade weight %d line in non-graded/explained slide %s" % (self.options["filename"], gweight, self.slide_number))

        self.questions[-1].update(weight=weight, gweight=gweight)

        return '<em>Weight: %s%s<em>' % (weight, ', '+str(gweight) if gweight else '')

    def slidoc_concepts(self, name, text):
        if not text:
            return ''

        ###if self.notes_end is not None:
        ###    message("    ****CONCEPT-ERROR: %s: 'Concepts: %s' line after Notes: ignored in '%s'" % (self.options["filename"], text, self.cur_header))
        ###    return ''

        if self.slide_concepts:
            message("    ****CONCEPT-ERROR: %s: Extra 'Concepts: %s' line ignored in '%s'" % (self.options["filename"], text, self.cur_header or ('slide%02d' % self.slide_number)))
            return ''

        self.slide_concepts = text

        tags = [x.strip() for x in text.split(";")]
        nn_tags = [x for x in tags if x]   # Non-null tags

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
                    # If assessment document, do not warn about lack of concept coverage
                    if tag not in Global.primary_tags and tag not in Global.sec_tags and 'assessment' not in self.options['config'].features:
                        self.concept_warnings.append("CONCEPT-WARNING: %s: '%s' not covered before '%s'" % (self.options["filename"], tag, self.cur_header or ('slide%02d' % self.slide_number)) )
                        message("        "+self.concept_warnings[-1])

                add_to_index(Global.primary_qtags, Global.sec_qtags, tags, self.options["filename"], self.get_slide_id(), self.cur_header, qconcepts=self.qconcepts)
            else:
                # Not question
                add_to_index(Global.primary_tags, Global.sec_tags, tags, self.options["filename"], self.get_slide_id(), self.cur_header)

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

def md2html(source, filename, config, filenumber=1, plugin_defs={}, prev_file='', next_file='', index_id='', qindex_id=''):
    """Convert a markdown string to HTML using mistune, returning (first_header, file_toc, renderer, html)"""
    Global.chapter_ref_counter = defaultdict(int)

    renderer = SlidocRenderer(escape=False, filename=filename, config=config, filenumber=filenumber, plugin_defs=plugin_defs)

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

        sidebar_html = click_span(SYMS['rightpair'], "Slidoc.sidebarDisplay();", classes=["slidoc-clickable-sym", 'slidoc-nosidebar']) if config.toc and not config.separate else ''
        pre_header_html += '<div class="slidoc-noslide slidoc-noprint slidoc-noall">'+nav_html+sidebar_html+SPACER3+click_span(SYMS['square'], "Slidoc.slideViewStart();", classes=["slidoc-clickable-sym", 'slidoc-nosidebar'])+'</div>\n'

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

    if 'hidden' in config.strip:
        # Strip out hidden answer slides
        content_html = re.sub(r"<!--slidoc-hidden-block-begin\[([-\w]+)\](.*?)<!--slidoc-hidden-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    if 'notes' in config.strip:
        # Strip out notes
        content_html = re.sub(r"<!--slidoc-notes-block-begin\[([-\w]+)\](.*?)<!--slidoc-notes-block-end\[\1\]-->", '', content_html, flags=re.DOTALL)

    file_toc = renderer.table_of_contents('' if not config.separate else config.site_url+filename+'.html', filenumber=filenumber)

    return (renderer.file_header or filename, file_toc, renderer, content_html)

# 'name' and 'id' are required field; entries are sorted by name but uniquely identified by id
Manage_fields =  ['name', 'id', 'email', 'altid', 'Timestamp', 'initTimestamp', 'submitTimestamp']
Session_fields = ['lateToken', 'lastSlide', 'questionsCount', 'questionsCorrect', 'weightedCorrect',
                  'session_hidden']
Index_fields = ['name', 'id', 'revision', 'Timestamp', 'dueDate', 'gradeDate', 'sessionWeight',
                'scoreWeight', 'gradeWeight', 'questionsMax', 'fieldsMin', 'questions', 'answers',
                'primary_qconcepts', 'secondary_qconcepts']
Log_fields = ['name', 'id', 'email', 'altid', 'Timestamp', 'browser', 'file', 'function', 'type', 'message', 'trace']

def update_session_index(sheet_url, hmac_key, session_name, revision, due_date, questions, score_weights, grade_weights,
                         p_concepts, s_concepts):
    user = 'admin'
    user_token = sliauth.gen_admin_token(hmac_key, user)

    get_params = {'sheet': INDEX_SHEET, 'id': session_name, 'admin': user, 'token': user_token,
                  'get': '1', 'headers': json.dumps(Index_fields)}
    retval = http_post(sheet_url, get_params)
    if retval['result'] != 'success':
        if not retval['error'].startswith('Error:NOSHEET:'):
            abort("Error in accessing index entry for session '%s': %s" % (session_name, retval['error']))
    prev_row = retval.get('value')
    if prev_row:
        revision_col = Index_fields.index('revision')
        if prev_row[revision_col] != revision:
            message('    ****WARNING: Session %s has changed from revision %s to %s' % (session_name, prev_row[revision_col], revision))

    row_values = [session_name, session_name, revision, None, due_date, None, None,
                score_weights, grade_weights, len(questions), len(Manage_fields)+len(Session_fields),
                ','.join([x['qtype'] for x in questions]),
                '|'.join([(x['correct'] or '').replace('|','/') for x in questions]),
                '; '.join(sort_caseless(list(p_concepts))),
                '; '.join(sort_caseless(list(s_concepts)))
                                ]
    post_params = {'sheet': INDEX_SHEET, 'admin': user, 'token': user_token,
                   'headers': json.dumps(Index_fields), 'row': json.dumps(row_values)
                  }
    retval = http_post(sheet_url, post_params)
    if retval['result'] != 'success':
        abort("Error in updating index entry for session '%s': %s" % (session_name, retval['error']))
    message('slidoc: Updated remote index sheet %s for session %s' % (INDEX_SHEET, session_name))

                
def create_gdoc_sheet(sheet_url, hmac_key, sheet_name, headers, row=None):
    user = 'admin'
    user_token = sliauth.gen_admin_token(hmac_key, user) if hmac_key else ''
    post_params = {'admin': user, 'token': user_token, 'sheet': sheet_name,
                   'headers': json.dumps(headers)}
    if row:
        post_params['row'] = json.dumps(row)
    retval = http_post(sheet_url, post_params)
    if retval['result'] != 'success':
        abort("Error in creating sheet '%s': %s" % (sheet_name, retval['error']))
    message('slidoc: Created remote spreadsheet:', sheet_name)

def parse_plugin(text, name=None):
    nmatch = re.match(r'^\s*([a-z]\w*)\s*=\s*{', text)
    if not nmatch:
        abort("Plugin definition must start with plugin_name={'")
    plugin_name = nmatch.group(1)
    if name and name != plugin_name:
        abort("Plugin definition must start with '"+name+" = {'")
    plugin_def = {}
    match = re.match(r'^(.*)\n(\s*/\*\s*)?PluginHead:(.*)$', text, flags=re.DOTALL)
    if match:
        text = match.group(1)+'\n'
        comment = match.group(2)
        tail = match.group(3).strip()
        if comment and tail.endswith('*/'):    # Strip comment delimiter
            tail = tail[:-2].strip()
        tail = re.sub(r'%(?!\(plugin_)', '%%', tail)  # Escape % signs in Head/Body template
        comps = re.split(r'(^|\n)\s*Plugin(Button|Body):' if comment else r'(^|\n)Plugin(Button|Body):', tail)
        plugin_def['Head'] = comps[0]+'\n' if comps[0] else ''
        comps = comps[1:]
        while comps:
            if comps[1] == 'Button':
                plugin_def['Button'] = comps[2]
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

    if config.pace and config.all is not None :
        abort('slidoc: Error: --pace option incompatible with --all')

    js_params = {'fileName': '', 'sessionVersion': '1.0', 'sessionRevision': '', 'sessionPrereqs': '',
                 'questionsMax': 0, 'pacedSlides': 0, 'scoreWeight': 0, 'gradeWeight': 0,
                 'paceLevel': 0, 'paceDelay': 0, 'tryCount': 0, 'tryDelay': 0,
                 'gd_client_id': None, 'gd_api_key': None, 'gd_sheet_url': None,
                 'score_sheet': SCORE_SHEET, 'index_sheet': INDEX_SHEET, 'indexFields': Index_fields,
                 'log_sheet': LOG_SHEET, 'logFields': Log_fields,
                 'sessionFields':Manage_fields+Session_fields, 'gradeFields': [], 
                 'features': {} }

    js_params['conceptIndexFile'] = 'index.html'  # Need command line option to modify this
    js_params['remoteLogLevel'] = config.remote_logging

    out_name = os.path.splitext(os.path.basename(config.all or input_paths[0]))[0]
    combined_file = '' if config.separate else out_name+'.html'

    # Reset config properties that will be overridden for separate files
    cmd_features_set = None if config.features is None else md2md.make_arg_set(config.features, features_all)

    cmd_pace_args = config.pace    # If None, will be initialized to file-specific values

    gd_sheet_url = ''
    if not config.separate:
        # Combined file  (these will be set later for separate files)
        config.features = cmd_features_set or set()
        js_params['features'] = dict([(x, 1) for x in config.features])
        gd_sheet_url = config.gsheet_url or ''
        js_params['gd_sheet_url'] = config.proxy_url if config.proxy_url and gd_sheet_url else gd_sheet_url
        js_params['fileName'] = out_name
    else:
        # Will be initialized to file-specific values (use '' to override)
        config.pace = None
        config.features = None


    gd_hmac_key = None             # Specify --gsheet_login='' to use Google Sheets without authentication
    if config.gsheet_login is not None:
        comps = config.gsheet_login.split(',')
        gd_hmac_key = comps[0]
        if len(comps) > 1:
            js_params['gd_client_id'], js_params['gd_api_key'] = comps[1:3]
    
    nb_site_url = config.site_url
    if combined_file:
        config.site_url = ''
    if config.site_url and not config.site_url.endswith('/'):
        config.site_url += '/'
    if config.image_url and not config.image_url.endswith('/'):
        config.image_url += '/'

    config.images = set(config.images.split(',')) if config.images else set()

    config.strip = md2md.make_arg_set(config.strip, strip_all)
    if len(input_files) == 1:
        config.strip.add('chapters')

    if config.dest_dir and not os.path.isdir(config.dest_dir):
        abort("Destination directory %s does not exist" % config.dest_dir)
    dest_dir = config.dest_dir+"/" if config.dest_dir else ''
    templates = {}
    for tname in ('doc_custom.css', 'doc_include.css', 'doc_include.js', 'doc_google.js', 'doc_test.js',
                  'doc_include.html', 'doc_template.html', 'reveal_template.html'):
        templates[tname] = md2md.read_file(scriptdir+'/templates/'+tname)

    inc_css = templates['doc_include.css'] + HtmlFormatter().get_style_defs('.highlight')
    if config.css.startswith('http:') or config.css.startswith('https:'):
        link_css = '<link rel="stylesheet" type="text/css" href="%s">\n' % config.css
        css_html = '%s<style>%s</style>\n' % (link_css, inc_css)
    else:
        custom_css = md2md.read_file(config.css) if config.css else templates['doc_custom.css']
        css_html = '<style>\n%s\n%s</style>\n' % (custom_css, inc_css)

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
                    proxy_query = '?username=%s&token=%s' % (user_id, gd_hmac_key if user_id == 'admin' else sliauth.gen_user_token(gd_hmac_key, user_id))
                else:
                    label = script
                test_params.append([label, query, proxy_query])

    if gd_hmac_key is not None:
        add_scripts += (Google_docs_js % js_params) + ('\n<script>\n%s</script>\n' % templates['doc_google.js'])
        if js_params['gd_client_id']:
            add_scripts += '<script src="https://apis.google.com/js/client.js?onload=onGoogleAPILoad"></script>\n'
        if gd_hmac_key:
            add_scripts += '<script src="https://cdnjs.cloudflare.com/ajax/libs/blueimp-md5/2.3.0/js/md5.js"></script>\n'
    answer_elements = {}
    for suffix in SlidocRenderer.content_suffixes:
        answer_elements[suffix] = 0;
    for suffix in SlidocRenderer.input_suffixes:
        answer_elements[suffix] = 1;
    js_params['answer_elements'] = answer_elements

    head_html = css_html + ('\n<script>\n%s</script>\n' % templates['doc_include.js'].replace('JS_PARAMS_OBJ', json.dumps(js_params)) )
    if combined_file:
        head_html += add_scripts
    body_prefix = templates['doc_include.html']
    mid_template = templates['doc_template.html']

    base_plugin_list = ['code', 'slider']
    base_plugin_defs = {}
    for plugin_name in base_plugin_list:
        _, base_plugin_defs[plugin_name] = parse_plugin(md2md.read_file(scriptdir+'/plugins/'+plugin_name+'.js'), name= plugin_name)
    if config.plugins:
        for plugin_path in config.plugins.split(','):
            plugin_name, base_plugin_defs[plugin_name] = parse_plugin( md2md.read_file(plugin_path.strip()) )

    comb_plugin_defs = {}
    comb_plugin_loads = set()
    fnames = []
    for j, f in enumerate(input_files):
        fcomp = os.path.splitext(os.path.basename(input_paths[j]))
        fnames.append(fcomp[0])
        if fcomp[1] != '.md':
            abort('Invalid file extension for '+input_paths[j])

        if config.notebook and os.path.exists(fcomp[0]+'.ipynb') and not config.overwrite and not config.dry_run:
            abort("File %s.ipynb already exists. Delete it or specify --overwrite" % fcomp[0])

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
    index_chapter_id = make_chapter_id(len(input_files)+1)
    qindex_chapter_id = make_chapter_id(len(input_files)+2)
    back_to_contents = nav_link('BACK TO CONTENTS', config.site_url, config.toc, hash='#'+make_chapter_id(0),
                                separate=config.separate, classes=['slidoc-nosidebar'], printable=config.printable)+'<p></p>\n'

    all_concept_warnings = []
    outfile_buffer = []
    combined_html = []
    if combined_file:
        combined_html.append( '<div id="slidoc-sidebar-right-container" class="slidoc-sidebar-right-container">\n' )
        combined_html.append( '<div id="slidoc-sidebar-right-wrapper" class="slidoc-sidebar-right-wrapper">\n' )
    fprefix = None
    math_found = False
    pagedown_load = False
    skulpt_load = False
    flist = []
    paced_files = {}
    for j, f in enumerate(input_files):
        fname = fnames[j]
        due_date = None
        if config.separate:
            # Separate files (may also be paced)
            file_config = parse_first_line(f, fname, parser, {}, include_args=Select_file_args,
                                           verbose=config.verbose)
            config.pace = file_config.pace if cmd_pace_args is None else cmd_pace_args
            if config.pace == '0':
                config.pace = None

            js_params['paceLevel'] = 0
            js_params['paceDelay'] = 0
            js_params['tryCount'] = 0
            js_params['tryDelay'] = 0
            if config.pace:
                # Note: pace does not work with combined files
                if config.printable:
                    abort('slidoc: Error: --pace and --printable options do not work well together')
                comps = config.pace.split(',')
                if comps[0]:
                    js_params['paceLevel'] = int(comps[0])
                if not js_params['paceLevel']:
                    abort('slidoc: Error: --pace=0 argument should be omitted')

                if len(comps) > 1 and comps[1]:
                    js_params['paceDelay'] = int(comps[1])
                if len(comps) > 2 and comps[2]:
                    js_params['tryCount'] = int(comps[2])
                if len(comps) > 3 and comps[3]:
                    js_params['tryDelay'] = int(comps[3])

                if config.due_date is not None:
                    if config.due_date:
                        due_date = sliauth.get_utc_date(config.due_date)
                elif file_config.due_date:
                    due_date = sliauth.get_utc_date(file_config.due_date)

            config.features = cmd_features_set or set()
            if file_config.features and (cmd_features_set is None or 'override' not in cmd_features_set):
                # Merge features from each file (unless 'override' feature is present, for command line to override)
                file_features_set = set(file_config.features.split(','))
                if 'grade_response' in file_features_set and gd_hmac_key is None:
                    file_features_set.remove('grade_response')
                config.features = config.features.union(file_features_set)

            js_params['features'] = dict([(x, 1) for x in config.features])
            js_params['sessionPrereqs'] =  (file_config.prereqs or '') if config.prereqs is None else config.prereqs
            js_params['sessionRevision'] = (file_config.revision or '') if config.revision is None else config.revision
                
            gd_sheet_url = (file_config.gsheet_url or '') if config.gsheet_url is None else config.gsheet_url
            js_params['gd_sheet_url'] = config.proxy_url if config.proxy_url and gd_sheet_url else gd_sheet_url
            js_params['fileName'] = fname

        if not j or config.separate:
            # First file or separate files
            mathjax_config = []
            if 'equation_number' in config.features:
                mathjax_config.append( r"TeX: { equationNumbers: { autoNumber: 'AMS' } }" )
            if 'tex_math' in config.features:
                mathjax_config.append( r"tex2jax: { inlineMath: [ ['$','$'], ['\\(','\\)'] ], processEscapes: true }" )
            math_inc = Mathjax_js % ','.join(mathjax_config)

        if not config.features.issubset(set(features_all)):
            abort('Error: Unknown feature(s): '+','.join(list(config.features.difference(set(features_all)))) )
            
        filepath = input_paths[j]
        md_text = f.read()
        f.close()

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
                                                        plugin_defs=base_plugin_defs, prev_file=prev_file, next_file=next_file,
                                                        index_id=index_id, qindex_id=qindex_id)

        max_params = {}
        max_params['id'] = '_max_score'
        max_params['initTimestamp'] = None
        max_params['questionsCount'] = len(renderer.questions)
        max_params['questionsCorrect'] = len(renderer.questions)
        max_params['weightedCorrect'] = renderer.cum_weights[-1] if renderer.cum_weights else 0
        max_params['q_grades'] = renderer.cum_gweights[-1] if renderer.cum_gweights else 0
        max_score_fields = [max_params.get(x,'') for x in Manage_fields+Session_fields]
        if max_params['q_grades'] and renderer.max_fields:
            # Include column for total grades
            max_score_fields += [max_params['q_grades']]
        max_score_fields += renderer.max_fields if renderer.max_fields else []
        if config.pace:
            # File-specific js_params
            js_params['pacedSlides'] = renderer.slide_number
            js_params['questionsMax'] = max_params['questionsCount']
            js_params['scoreWeight'] = max_params['weightedCorrect']
            js_params['gradeWeight'] = max_params['q_grades']
            js_params['gradeFields'] = renderer.grade_fields[:] if renderer.grade_fields else []
            if js_params['gradeWeight'] and js_params['gradeFields']:
                # Include column for total grades
                js_params['gradeFields'] = ['q_grades'] + js_params['gradeFields']

            paced_files[fname] = {'due_date': due_date} 
            if gd_sheet_url:
                if js_params['gradeWeight']:
                    paced_files[fname]['type'] = 'graded'
                else:
                    paced_files[fname]['type'] = 'scored'
            else:
                paced_files[fname]['type'] = 'paced'

        all_concept_warnings += renderer.concept_warnings
        outname = fname+".html"
        flist.append( (fname, outname, fheader, file_toc) )
        
        comb_plugin_defs.update(renderer.plugin_defs)
        comb_plugin_loads.update(renderer.plugin_loads)
        math_in_file = renderer.render_markdown or (r'\[' in md_text and r'\]' in md_text) or (r'\(' in md_text and r'\)' in md_text)
        if math_in_file:
            math_found = True
        if renderer.render_markdown:
            pagedown_load = True
        if renderer.load_python:
            skulpt_load = True
        
        mid_params = {'session_name': fname,
                      'math_js': math_inc if math_in_file else '',
                      'pagedown_js': Pagedown_js if renderer.render_markdown else '',
                      'skulpt_js': Skulpt_js if renderer.load_python else ''}
        mid_params.update(SYMS)

        if config.dry_run:
            message("Indexed ", outname+":", fheader)
        else:
            md_prefix = chapter_prefix(filenumber, 'slidoc-reg-chapter', hide=config.pace)
            md_suffix = '</article> <!--chapter end-->\n'
            if combined_file:
                combined_html.append(md_prefix)
                combined_html.append(md_html)
                combined_html.append(md_suffix)
            else:
                file_plugin_defs = base_plugin_defs.copy()
                file_plugin_defs.update(renderer.plugin_defs)
                file_head_html = css_html + ('\n<script>\n%s</script>\n' % templates['doc_include.js'].replace('JS_PARAMS_OBJ', json.dumps(js_params)) ) + add_scripts

                head = file_head_html + plugin_heads(file_plugin_defs, renderer.plugin_loads) + (mid_template % mid_params) + body_prefix
                tail = md_prefix + md_html + md_suffix
                if Missing_ref_num_re.search(md_html) or return_html:
                    # Still some missing reference numbers; output file later
                    outfile_buffer.append([outname, dest_dir+outname, head, tail])
                else:
                    outfile_buffer.append([outname, dest_dir+outname, '', ''])
                    write_doc(dest_dir+outname, head, tail)

            if config.slides and not return_html:
                reveal_pars['reveal_title'] = fname
                # Wrap inline math in backticks to protect from backslashes being removed
                md_text_reveal = re.sub(r'\\\((.+?)\\\)', r'`\(\1\)`', md_text_modified)
                md_text_reveal = re.sub(r'(^|\n)\\\[(.+?)\\\]', r'\1`\[\2\]`', md_text_reveal, flags=re.DOTALL)
                if 'tex_math' in config.features:
                    md_text_reveal = re.sub(r'(^|[^\\\$])\$(?!\$)(.*?)([^\\\n\$])\$(?!\$)', r'\1`$\2\3$`', md_text_reveal)
                    md_text_reveal = re.sub(r'(^|\n)\$\$(.*?)\$\$', r'\1`$$\2\3$$`', md_text_reveal, flags=re.DOTALL)
                reveal_pars['reveal_md'] = md_text_reveal
                md2md.write_file(dest_dir+fname+"-slides.html", templates['reveal_template.html'] % reveal_pars)

            if config.notebook and not return_html:
                md_parser = md2nb.MDParser(nb_converter_args)
                md2md.write_file(dest_dir+fname+".ipynb", md_parser.parse_cells(md_text_modified))

            if gd_hmac_key:
                update_session_index(gd_sheet_url, gd_hmac_key, fname, js_params['sessionRevision'],
                                      due_date, renderer.questions, js_params['scoreWeight'], js_params['gradeWeight'],
                                      renderer.qconcepts[0], renderer.qconcepts[1])

            if gd_sheet_url and (gd_hmac_key or not return_html):
                create_gdoc_sheet(gd_sheet_url, gd_hmac_key, js_params['fileName'],
                                  Manage_fields+Session_fields+js_params['gradeFields'], row=max_score_fields)
                create_gdoc_sheet(gd_sheet_url, gd_hmac_key, LOG_SHEET, Log_fields)

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

    if config.toc:
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
        ifile = 0
        for fname, outname, fheader, file_toc in flist:
            ifile += 1
            chapter_id = make_chapter_id(ifile)
            slide_link = ''
            if fname not in paced_files and config.slides:
                slide_link = ' (<a href="%s%s" class="slidoc-clickable" target="_blank">%s</a>)' % (config.site_url, fname+"-slides.html", 'slides')
            nb_link = ''
            if fname not in paced_files and config.notebook and nb_site_url:
                nb_link = ' (<a href="%s%s%s.ipynb" class="slidoc-clickable">%s</a>)' % (md2nb.Nb_convert_url_prefix, nb_site_url[len('http://'):], fname, 'notebook')

            if fname in paced_files:
                doc_str = paced_files[fname]['type'] + ' exercise'
                due_date = paced_files[fname]['due_date']
                if due_date:
                    doc_str += ', due '+(due_date[:-8]+'Z' if due_date.endswith(':00.000Z') else due_date)
                doc_link = nav_link(doc_str, config.site_url, outname, target='_blank', separate=True)
                toggle_link = '<span id="slidoc-toc-chapters-toggle" class="slidoc-toc-chapters">%s</span>' % (fheader,)
                if test_params:
                    for label, query, proxy_query in test_params:
                        if config.proxy_url:
                            doc_link += ', <a href="/_auth/login/%s&next=%s" target="_blank">%s</a>' % (proxy_query, urllib.quote('/'+outname+query), label)
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

        if config.slides:
            toc_html.append('<em>Note</em>: When viewing slides, type ? for help or click <a class="slidoc-clickable" target="_blank" href="https://github.com/hakimel/reveal.js/wiki/Keyboard-Shortcuts">here</a>.\nSome slides can be navigated vertically.')

        toc_html.append('<p></p><em>Document formatted by <a href="https://github.com/mitotic/slidoc" class="slidoc-clickable">slidoc</a>.</em><p></p>')

        if not config.dry_run:
            toc_insert = ''
            if fname not in paced_files:
                toc_insert += click_span('+Contents', "Slidoc.hide(this,'slidoc-toc-sections');",
                                        classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-noprint'])
            if combined_file:
                toc_insert = click_span(SYMS['rightpair'], "Slidoc.sidebarDisplay();",
                                    classes=['slidoc-clickable-sym', 'slidoc-nosidebar', 'slidoc-noprint']) + SPACER2 + toc_insert
                toc_insert = click_span(SYMS['leftpair'], "Slidoc.sidebarDisplay();",
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
                md2md.write_file(dest_dir+config.toc, Html_header, head_html,
                                  mid_template % mid_params, body_prefix, toc_output, Html_footer)
                message("Created ToC in", config.toc)

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

            index_output = chapter_prefix(len(input_files)+1, 'slidoc-index-container slidoc-noslide', hide=False) + back_to_contents +'<p></p>' + index_html + '</article>\n'
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

    if config.qindex and Global.primary_qtags:
        import itertools
        qout_list = []
        qout_list.append('<b>QUESTION CONCEPT</b>\n')
        first_references, covered_first, qindex_html = make_index(Global.primary_qtags, Global.sec_qtags, config.site_url, question=True, fprefix=fprefix, index_id=qindex_id, index_file='' if combined_file else config.qindex)
        qout_list.append(qindex_html)

        qindex_output = chapter_prefix(len(input_files)+2, 'slidoc-qindex-container slidoc-noslide', hide=False) + back_to_contents +'<p></p>' + ''.join(qout_list) + '</article>\n'
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

        comb_params = {'session_name': out_name,
                       'math_js': math_inc if math_found else '',
                       'pagedown_js': Pagedown_js if pagedown_load else '',
                       'skulpt_js': Skulpt_js if skulpt_load else ''}
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

def http_post(url, params_dict):
    data = urllib.urlencode(params_dict)
    req = urllib2.Request(url, data)
    try:
        response = urllib2.urlopen(req)
    except Exception, excp:
        abort('ERROR in accessing URL %s: %s' % (url, excp))
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

# Need latest version of Markdown for hooks
Pagedown_js = r'''
<script src='https://dl.dropboxusercontent.com/u/72208800/Pagedown/Markdown.Converter.js'></script>
<script src='https://dl.dropboxusercontent.com/u/72208800/Pagedown/Markdown.Sanitizer.js'></script>
<script src='https://dl.dropboxusercontent.com/u/72208800/Pagedown/Markdown.Extra.js'></script>
'''

Mathjax_js = r'''<script type="text/x-mathjax-config">
  MathJax.Hub.Config({
    %s
  });
</script>
<script src='https://cdn.mathjax.org/mathjax/latest/MathJax.js?config=TeX-AMS-MML_HTMLorMML'></script>
'''

Skulpt_js = r'''
<script src="http://ajax.googleapis.com/ajax/libs/jquery/1.9.0/jquery.min.js" type="text/javascript"></script> 
<script src="http://www.skulpt.org/static/skulpt.min.js" type="text/javascript"></script> 
<script src="http://www.skulpt.org/static/skulpt-stdlib.js" type="text/javascript"></script> 
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

Select_file_args = set(['due_date', 'features', 'gsheet_url', 'pace', 'prereqs', 'revision'])
    
def parse_first_line(file, fname, parser, cmd_args_dict, exclude_args=set(), include_args=set(), verbose=False):
    # Read first line of first file and rewind it
    first_line = file.readline()
    file.seek(0)
    match = re.match(r'^ {0,3}<!--slidoc-defaults\s+(.*?)-->\s*?\n', first_line)
    try:
        if match:
            line_args_list = shlex.split(match.group(1).strip())
            line_args_dict = vars(parser.parse_args(line_args_list))
        else:
            line_args_dict = dict([(arg_name, None) for arg_name in include_args]) if include_args else {}
        for arg_name in line_args_dict.keys():
            if include_args and arg_name not in include_args:
                del line_args_dict[arg_name]
            elif exclude_args and arg_name in exclude_args:
                del line_args_dict[arg_name]
        if verbose:
            message('Selected first line arguments from file', fname, argparse.Namespace(**line_args_dict))
    except Exception, excp:
        abort('slidoc: ERROR in parsing command options in first line of %s: %s' % (file.name, excp))

    for arg_name in cmd_args_dict:
        if arg_name not in line_args_dict:
            # Argument not specified in file line (copy from command line)
            line_args_dict[arg_name] = cmd_args_dict[arg_name]
        elif cmd_args_dict[arg_name] != None:
            # Argument also specified in command line (override)
            line_args_dict[arg_name] = cmd_args_dict[arg_name]

    return argparse.Namespace(**line_args_dict)

def abort(msg):
    if __name__ == '__main__':
        sys.exit(msg)
    else:
        raise Exception(msg)

strip_all = ['answers', 'chapters', 'concepts', 'contents', 'hidden', 'inline_js', 'navigate', 'notes', 'rule', 'sections']
features_all = ['assessment', 'equation_number', 'grade_response', 'incremental_slides', 'override', 'progress_bar', 'quote_response', 'tex_math', 'untitled_number']

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--all', metavar='FILENAME', help='Base name of combined HTML output file')
parser.add_argument('--crossref', metavar='FILE', help='Cross reference HTML file')
parser.add_argument('--css', metavar='FILE_OR_URL', help='Custom CSS filepath or URL (derived from doc_custom.css)')
parser.add_argument('--dest_dir', metavar='DIR', help='Destination directory for creating files')
parser.add_argument('--due_date', metavar='DATE_TIME', help="Due local date yyyy-mm-ddThh:mm (append 'Z' for UTC)")
parser.add_argument('--features', metavar='OPT1,OPT2,...', help='Enable feature %s|all|all,but,...' % ','.join(features_all))
parser.add_argument('--gsheet_login', metavar='HMAC_KEY,CLIENT_ID,API_KEY', help='hmac_key[,client_id,api_key] (authenticate via Google Docs)')
parser.add_argument('--gsheet_url', metavar='URL', help='Google spreadsheet_url (export sessions to Google Docs spreadsheet)')
parser.add_argument('--proxy_url', metavar='URL', help='Proxy spreadsheet_url')
parser.add_argument('--hide', metavar='REGEX', help='Hide sections matching header regex (e.g., "[Aa]nswer")')
parser.add_argument('--image_dir', metavar='DIR', help='image subdirectory (default: images)')
parser.add_argument('--image_url', metavar='URL', help='URL prefix for images, including image_dir')
parser.add_argument('--images', help='images=(check|copy|export|import)[_all] to process images')
parser.add_argument('--indexed', metavar='TOC,INDEX,QINDEX', help='Table_of_contents,concep_index,question_index base filenames, e.g., "toc,ind,qind" (if omitted, all input files are combined, unless pacing)')
parser.add_argument('--notebook', help='Create notebook files', action="store_true", default=None)
parser.add_argument('--pace', metavar='PACE_LEVEL,DELAY_SEC,TRY_COUNT,TRY_DELAY', help='Options for paced session using combined file, e.g., 1,0,1 to force answering questions')
parser.add_argument('--plugins', metavar='FILE1,FILE2,...', help='Additional plugin file paths')
parser.add_argument('--prereqs', metavar='PREREQ_SESSION1,PREREQ_SESSION2,...', help='Session prerequisites')
parser.add_argument('--printable', help='Printer-friendly output', action="store_true", default=None)
parser.add_argument('--remote_logging', type=int, default=0, help='Remote logging level (0/1/2)')
parser.add_argument('--revision', metavar='REVISION', help='File revision')
parser.add_argument('--site_url', metavar='URL', help='URL prefix to link local HTML files (default: "")')
parser.add_argument('--slides', metavar='THEME,CODE_THEME,FSIZE,NOTES_PLUGIN', help='Create slides with reveal.js theme(s) (e.g., ",zenburn,190%%")')
parser.add_argument('--strip', metavar='OPT1,OPT2,...', help='Strip %s|all|all,but,...' % ','.join(strip_all))
parser.add_argument('--test_script', help='Enable scripted testing(=1 OR SCRIPT1[/USER],SCRIPT2/USER2,...)')
parser.add_argument('--toc_header', metavar='FILE', help='.html or .md header file for ToC')

alt_parser = argparse.ArgumentParser(parents=[parser], add_help=False)
alt_parser.add_argument('--dry_run', help='Do not create any HTML files (index only)', action="store_true", default=None)
alt_parser.add_argument('--overwrite', help='Overwrite files', action="store_true", default=None)
alt_parser.add_argument('-v', '--verbose', help='Verbose output', action="store_true", default=None)

cmd_parser = argparse.ArgumentParser(parents=[alt_parser], description='Convert from Markdown to HTML')
cmd_parser.add_argument('file', help='Markdown filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)

def cmd_args2dict(cmd_args):
    # Some arguments need to be set explicitly to '' by default, rather than staying as None
    cmd_defaults = {'css': '', 'dest_dir': '', 'hide': '', 'image_dir': 'images', 'image_url': '',
                    'site_url': ''}
    
    # Assign default (non-None) values to arguments not specified anywhere
    for arg_name in cmd_defaults:
        if getattr(cmd_args, arg_name) == None:
            setattr(cmd_args, arg_name, cmd_defaults[arg_name]) 

    return vars(cmd_args)

if __name__ == '__main__':
    cmd_args_orig = cmd_parser.parse_args()
    first_name = os.path.splitext(os.path.basename(cmd_args_orig.file[0].name))[0]

    # Do not exclude args if combined file
    exclude_args = Select_file_args if cmd_args_orig.all is None else None
    cmd_args = parse_first_line(cmd_args_orig.file[0], first_name, parser, vars(cmd_args_orig),
                                exclude_args=exclude_args, verbose=cmd_args_orig.verbose)

    config_dict = cmd_args2dict(cmd_args)

    input_files = config_dict.pop('file')

    if cmd_args.verbose:
        print('Effective argument list', file=sys.stderr)
        print('    ', argparse.Namespace(**config_dict), file=sys.stderr)

    process_input(input_files, [f.name for f in input_files], config_dict)
