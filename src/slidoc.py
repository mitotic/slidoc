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
import datetime
import io
import os
import random
import re
import shlex
import subprocess
import sys
import time
import urllib
import urllib2
import urlparse
import zipfile

from collections import defaultdict, OrderedDict

import json
import mistune
import md2md
import md2nb
import sliauth

try:
    import pygments
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name
    from pygments.formatters import HtmlFormatter
    from pygments.util import ClassNotFound
except ImportError:
    HtmlFormatter = None


from xml.etree import ElementTree

LIBRARIES_URL = 'https://mitotic.github.io/slidoc/_libraries'
RESOURCE_PATH = '_resource'

ADMIN_ROLE = 'admin'
GRADER_ROLE = 'grader'

ADMINUSER_ID = 'admin'
TESTUSER_ID = '_test_user'

SETTINGS_SHEET = 'settings_slidoc'
INDEX_SHEET = 'sessions_slidoc'
ROSTER_SHEET = 'roster_slidoc'
GRADES_SHEET = 'grades_slidoc'
LOG_SHEET = 'slidoc_log'
MAX_QUERY = 500   # Maximum length of query string for concept chains
SPACER6 = '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
SPACER2 = '&nbsp;&nbsp;'
SPACER3 = '&nbsp;&nbsp;&nbsp;'

SINGLETON_PLUGINS = ['Code', 'Params', 'Share', 'Timer', 'Upload']
FORMULA_NAMESPACE = ['Math']

ANGLE_TEXT_RE = re.compile(r'^\s*<(center|code|strong)>(.*)</\1>\s*$')

ANSWER_TYPE_RE = re.compile(r'^([a-zA-Z\w]+)\s*=(.*)$')
ANSWER_CONTENT_RE = re.compile(r'^([a-zA-Z]\w*)/(.*)$')

# Backticks are optional for backwards compatibility in plugin syntax
ANSWER_EXPECT_RE  = re.compile(r'^`?=?(\w+)\.(expect)\(\s*(\d*)\s*\)\s*(;;\s*([()eE0-9.*+/-]+%?))?\s*`?$')
ANSWER_FORMULA_RE = re.compile(r'^`=([^`;\n]+)(;;\s*([()eE0-9.*+/-]+%?))?\s*`$')
INLINE_METHOD_RE  = re.compile(r'^(\w+)\.(\w+)\(\s*(\d*)\s*\)')
INLINE_PLUGIN_RE  = re.compile(r'(^|\b)(\$+)\.([a-zA-Z]\w*)(\[\d+\])?\.')    # Syntax: $.Plugin.method(1) OR $.Plugin[1].method(100) OR $$.Plugin.method()

DEFINE_PARAM_RE   = re.compile(r'^([_a-zA-Z]\w*)=([0-9.:eE+-]+)$')
DEFINE_FUNCTION_RE = re.compile(r'^\s*function\s+([a-zA-Z]\w*)\s*(\([\w\s,]*\)\s*\{.*\})\s*$')

BASIC_PACE    = 1
QUESTION_PACE = 2
ADMIN_PACE    = 3


SYMS = {'prev': '&#9668;', 'next': '&#9658;', 'return': '&#8617;', 'up': '&#9650;', 'down': '&#9660;', 'play': '&#9658;', 'stop': '&#9724;',
        'gear': '&#9881;', 'bubble': '&#x1F4AC;', 'letters': '&#x1f520;', 'printer': '&#x1f5b6;', 'folder': '&#x1f4c1;', 'openfolder': '&#x1f4c2;', 'lightning': '&#9889;', 'pencil': '&#9998;',
        'phone': '&#x1f4f1;', 'phonearrow': '&#x1f4f2;', 'ballot': '&#x2611;', 'house': '&#8962;', 'circle': '&#9673;', 'square': '&#9635;',
        'threebars': '&#9776;', 'bigram': '&#9782;', 'trigram': '&#9783;', 'rightarrow': '&#x27A4;', 'leftrightarrow':'&#x2194;', 'leftpair': '&#8647;', 'rightpair': '&#8649;', 'bust': '&#x1f464;', 'eye': '&#x1f441;', 'lock': '&#x1f512;', 'printer': '&#9113;'}

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

def concept_chain(slide_id, server_url):
    params = {'sid': slide_id, 'ixfilepfx': server_url+'/'}
    params.update(SYMS)
    return '\n<div id="%(sid)s-ichain" style="display: none;">CONCEPT CHAIN: <a id="%(sid)s-ichain-prev" class="slidoc-clickable-sym">%(prev)s</a>&nbsp;&nbsp;&nbsp;<b><a id="%(sid)s-ichain-concept" class="slidoc-clickable"></a></b>&nbsp;&nbsp;&nbsp;<a id="%(sid)s-ichain-next" class="slidoc-clickable-sym">%(next)s</a></div><p></p>\n\n' % params


def isfloat(value):
  try:
    float(value)
    return True
  except ValueError:
    return False

def font_css(fontsize):
    if not fontsize:
        return ''
    comps = fontsize.split(',')
    if comps[0]:
        if comps[0].isdigit():
            comps[0] += 'px'
        tem_css = '@media not print { body { font-size: %s; }  }\n' % comps[0]
    else:
        tem_css = ''

    if len(comps) > 1 and comps[1]:
        if comps[1].isdigit():
            comps[1] += 'px'
        tem_css += '@media print { body { font-size: %s; }  }\n' % comps[1]

    return '<style>\n'+tem_css+'</style>\n' if tem_css else ''

def exponentiate(format, times=False):
    if times and '*10**' in format:
        return format.replace('*10**','&times;10<sup>').replace('(','').replace(')','')+'</sup>'
    else:
        return format.replace('*10**','e').replace('(','').replace(')','')

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


def make_index(primary_tags, sec_tags, server_url, question=False, fprefix='', index_id='', index_file=''):
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
                out_list.append('<a href="%s#%s" class="slidoc-clickable" target="_blank">%s</a>' % (server_url+fname+'.html'+query_str, slide_id, header_html))            
            else:
                out_list.append('''<a href="#%s" class="slidoc-clickable" onclick="Slidoc.chainStart('%s', '#%s');">%s</a>''' % (slide_id, query_str, slide_id, header_html))            

        if files:
            out_list.append('</li>\n')

        first_references[tag] = first_ref_list
        prev_tag_comps = tag_comps

    out_list.append(close_ul)
        
    out_list = ['<b id="%s">INDEX</b><blockquote>\n' % index_id] + ["&nbsp;&nbsp;".join(['<a href="#%s" class="slidoc-clickable">%s</a>' % (id_prefix+x.upper(), x.upper()) for x in first_letters])] + ['</blockquote>'] + out_list
    return first_references, covered_first, ''.join(out_list)


class MathBlockGrammar(mistune.BlockGrammar):
    def_links = re.compile(  # RE-DEFINE TO INCLUDE SINGLE QUOTES
        r'^ *\[([^^\]]+)\]: *'  # [key]:
        r'<?([^\s>]+)>?'  # <link> or link
        r'''(?: +['"(]([^\n]+)['")])? *(?:\n+|$)'''
    )

    lheading =          re.compile(r'^([^\n]+)\n *(=|-){5,} *(?:\n+|$)')  # Require at least 5 equals/dashes for level 3/4 setext-style header

    block_math =        re.compile(r'^\\\[(.*?)\\\]', re.DOTALL)
    latex_environment = re.compile(r'^\\begin\{([a-z]*\*?)\}(.*?)\\end\{\1\}',
                                                re.DOTALL)
    plugin_definition = re.compile(r'^ {0,3}<script +type="x-slidoc-plugin" *>\s*(\w+)\s*=\s*\{(.*?)\n *(// *\1)? *</script> *(\n|$)',
                                                re.DOTALL)
    plugin_embed      = re.compile(r'^ {0,3}<script +type="x-slidoc-embed" *>\s*(\w+)\(([^\n]*)\)\s*\n(.*?)\n *</script> *(\n|$)',
                                                re.DOTALL)
    plugin_insert =   re.compile(r'^=(\w+)\(([^\n]*)\)\s*(\n\s*\n|\n$|$)')
    slidoc_header =   re.compile(r'^ {0,3}<!--\s*(meldr-\w[-\w]*\s|slidoc-\w[-\w]*\s|Slidoc:)(.*?)(-->|\n)\s*?(\n|$)', re.DOTALL)
    slidoc_options=   re.compile(r'^ {0,3}(Slidoc):(.*?)(\n|$)')
    slidoc_slideopts= re.compile(r'^ {0,3}(Slide):(.*?)(\n|$)')
    slidoc_banner =   re.compile(r'^ {0,3}(Banner):(.*?)(\n|$)')
    slidoc_define =   re.compile(r'^ {0,3}(Define):(.*?)(\n|$)')
    slidoc_answer =   re.compile(r'^ {0,3}(Answer):(.*?)(\n|$)')
    slidoc_tags   =   re.compile(r'^ {0,3}(Tags):(.*?)(\n\s*(\n|$)|$)', re.DOTALL)
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
        slidoc_rules = ['block_math', 'latex_environment', 'plugin_definition', 'plugin_embed', 'plugin_insert', 'slidoc_header', 'slidoc_options', 'slidoc_slideopts', 'slidoc_banner', 'slidoc_define', 'slidoc_answer', 'slidoc_tags', 'slidoc_hint', 'slidoc_notes', 'slidoc_extra', 'minirule']
        if config and 'incremental_slides' in config.features:
            slidoc_rules += ['pause']
        self.default_rules = slidoc_rules + mistune.BlockLexer.default_rules
        self.slidoc_slide_text = []
        self.slidoc_blocks = []
        self.slidoc_recursion = 0
        self.slidoc_slide_header = None
        super(MathBlockLexer, self).__init__(rules, **kwargs)

    def get_slide_text(self):
        return self.slidoc_slide_text

    def slidoc_slide_end(self):
        self.slidoc_slide_text.append(''.join(self.slidoc_blocks))
        self.slidoc_blocks = []

    def parse(self, text, rules=None):
        self.slidoc_recursion += 1
        text = text.rstrip('\n')
        if not rules:
            rules = self.default_rules

        def manipulate(text):
            for key in rules:
                rule = getattr(self.rules, key)
                m = rule.match(text)
                if not m:
                    continue
                getattr(self, 'parse_%s' % key)(m)
                if self.slidoc_recursion == 1:
                    if key == 'slidoc_slideopts':
                        # Slide: => slide break if not right after hrule
                        if self.slidoc_slide_header is not None:
                            self.slidoc_slide_end()
                        self.slidoc_slide_header = ''
                    elif key == 'heading':
                        if len(m.group(1)) <= 2 and m.group(2).strip('#').strip():
                            # Level 1 or 2 header
                            if self.slidoc_slide_header:
                                # Not right after hrule or after Slide: => implicit slide break
                                self.slidoc_slide_end()
                        # Non-blank text content
                        self.slidoc_slide_header = m.group(2).strip('#').strip() 

                    self.slidoc_blocks.append(m.group(0))

                    if key == 'paragraph':
                        if not self.slidoc_slide_header:
                            # Non-blank text content
                            self.slidoc_slide_header = m.group(1).strip()
                    elif key == 'hrule':
                        # Explicit slide break
                        self.slidoc_slide_end()
                        self.slidoc_slide_header = None
                return m
            return False  # pragma: no cover

        while text:
            m = manipulate(text)
            if m is not False:
                text = text[len(m.group(0)):]
                continue
            if text:  # pragma: no cover
                raise RuntimeError('Infinite loop at: %s' % text)
        if self.slidoc_recursion == 1:
            self.slidoc_slide_end()
        self.slidoc_recursion -= 1
        return self.tokens

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
            'name': m.group(1).strip().lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_options(self, m):
         self.tokens.append({
            'type': 'slidoc_options',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_slideopts(self, m):
         self.tokens.append({
            'type': 'slidoc_slideopts',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_banner(self, m):
         self.tokens.append({
            'type': 'slidoc_banner',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_define(self, m):
         self.tokens.append({
            'type': 'slidoc_define',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_answer(self, m):
         self.tokens.append({
            'type': 'slidoc_answer',
            'name': m.group(1).lower(),
            'text': m.group(2).strip()
        })

    def parse_slidoc_tags(self, m):
         self.tokens.append({
            'type': 'slidoc_tags',
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

    def parse_lheading(self, m):
        """Parse setext heading (force level 3/4 to avoid slide break)"""
        self.tokens.append({
            'type': 'heading',
            'level': 3 if m.group(2).startswith('=') else 4,
            'text': m.group(1),
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
    tex_inline_math=re.compile(r"^\$(?!\$)(.*?)([^\\\n\$])\$(?!\$)")
    inline_formula =re.compile(r"^`=([^`;\n]+)(;;\s*([()eE0-9.*+-]*))?\s*`")
    text =          re.compile(r'^[\s\S]+?(?=[\\<!\[_*`~$]|https?://| {2,}\n|$)')
    internal_ref =  re.compile(
        r'^\[('
        r'(?:\[[^^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*'
        r')\]\s*\{\s*#([^^\}]*)\}'
    )
    any_block_math =  re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
    any_inline_math = re.compile(r"(\$|\\\()(.+?)(\\\)|\$)")

class MathInlineLexer(mistune.InlineLexer):
    def __init__(self, renderer, rules=None, **kwargs):
        if rules is None:
            rules = MathInlineGrammar()
        config = kwargs.get('config')
        slidoc_rules = ['slidoc_choice', 'block_math', 'inline_math', 'inline_formula', 'internal_ref']
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

    def output_inline_formula(self, m):
        return self.renderer.inline_formula(m.group(1), m.group(3))

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
                    tag_html = nav_link(text, self.renderer.options['config'].server_url, self.renderer.options['config'].index,
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
                        num_label, _, ref_class, _ = Global.ref_tracker[ref_id]
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
            message('REF-WARNING: Null reference')
            return None

        # Slidoc-specific hash reference handling
        ref_id = 'slidoc-ref-'+md2md.make_id_from_text(header_ref)
        ref_class = ''
        if ref_id in Global.ref_tracker:
            message('    ****REF-WARNING: Duplicate reference #%s (#%s)' % (ref_id, key))
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
        return '''<span id="%s" class="slidoc-referable %s" data-slide-id="%s">%s</span>'''  % (ref_id, ref_class, self.renderer.get_slide_id(), text)

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

    def output_slidoc_options(self):
        return self.renderer.slidoc_options(self.token['name'], self.token['text'])

    def output_slidoc_slideopts(self):
        return self.renderer.slidoc_slideopts(self.token['name'], self.token['text'])

    def output_slidoc_banner(self):
        return self.renderer.slidoc_banner(self.token['name'], self.token['text'])

    def output_slidoc_define(self):
        return self.renderer.slidoc_define(self.token['name'], self.token['text'])

    def output_slidoc_answer(self):
        return self.renderer.slidoc_answer(self.token['name'], self.token['text'])

    def output_slidoc_tags(self):
        return self.renderer.slidoc_tags(self.token['name'], self.token['text'])

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
        self.renderer.close_zip(text)

        if not self.renderer.global_plugin_refs.issubset(self.renderer.plugin_embeds):
            abort("    ****PLUGIN-ERROR: %s: Missing global plugins %s ." % (self.options["filename"], list(self.renderer.global_plugin_refs.difference(self.renderer.plugin_embeds))))

        first_slide_pre = '<span id="%s-attrs" class="slidoc-attrs" style="display: none;">%s</span>\n' % (self.renderer.first_id, base64.b64encode(json.dumps(self.renderer.questions)))

        if self.renderer.options['config'].pace:
            first_slide_pre += SlidocRenderer.remarks_template

        if self.renderer.qconcepts[0] or self.renderer.qconcepts[1]:
            # Include sorted list of concepts related to questions
            q_list = [sort_caseless(list(self.renderer.qconcepts[j])) for j in (0, 1)]
            first_slide_pre += '<span id="%s-qconcepts" class="slidoc-qconcepts" style="display: none;">%s</span>\n' % (self.renderer.first_id, base64.b64encode(json.dumps(q_list)))

        classes =  ['slidoc-first-slide', 'slidoc-single-column' if 'two_column' in self.renderer.options['config'].features else '']
        return SlidocRenderer.image_drop_template+self.renderer.slide_prefix(self.renderer.first_id, ' '.join(classes))+first_slide_pre+concept_chain(self.renderer.first_id, self.renderer.options['config'].server_url)+html+self.renderer.end_slide(last_slide=True)

    
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
        if HtmlFormatter and lang:
            try:
                lexer = get_lexer_by_name(lang, stripall=True)
            except ClassNotFound:
                code = lang + '\n' + code

        if not lexer or not HtmlFormatter:
            return '\n<pre><code>%s</code></pre>\n' % mistune.escape(code)

        formatter = HtmlFormatter()
        return highlight(code, lexer, formatter)

    
class SlidocRenderer(MathRenderer):
    header_attr_re = re.compile(r'^.*?(\s*\{\s*(#\S+)?([^#\}]*)?\s*\})\s*$')

    plugin_content_template = '''<div id="%(pluginId)s-content" class="%(pluginLabel)s-content slidoc-plugin-content slidoc-pluginonly" data-plugin="%(pluginName)s" data-number="%(pluginNumber)s" data-args="%(pluginInitArgs)s" data-button="%(pluginButton)s" data-slide-id="%(pluginSlideId)s">%(pluginContent)s</div><!--%(pluginId)s-content-->'''

    plugin_body_template = '''<div id="%(pluginId)s-body" class="%(pluginLabel)s-body slidoc-plugin-body slidoc-pluginonly">%(pluginBodyDef)s</div><!--%(pluginId)s-body-->'''

    image_drop_template = '''<div id="slidoc-imgupload-container" class="slidoc-previewonly slidoc-updateonly"><label>Autonumber images:</label><input id="slidoc-upload-img-autonumber" type="checkbox" class="slidoc-upload-img-autonumber" value="autonumber"></input></label><div class="slidoc-img-droparea slidoc-droppable slidoc-img-drop">Drop image here<br></div></div>'''

    remarks_template = '''
  <button id="slidoc-remarks-start-click" class="slidoc-clickable slidoc-button slidoc-gstart-click slidoc-grade-button slidoc-gradableonly slidoc-noprint" onclick="Slidoc.remarksClick(this);">Edit remarks</button>
  <div id="slidoc-remarks-edit" class="slidoc-grade-element slidoc-gradableonly" style="display: none;">
    <button id="slidoc-remarks-save-click" class="slidoc-clickable slidoc-button slidoc-grade-click slidoc-grade-button" onclick="Slidoc.remarksClick(this);">Save remarks</button>
    <span id="slidoc-remarksprefix" class="slidoc-grade slidoc-gradeprefix"><em>Extra points:</em></span>
    <input id="slidoc-remarks-input" type="number" step="any" class="slidoc-grade-input"></input>
    <textarea id="slidoc-remarks-comments-textarea" name="textarea" class="slidoc-comments-textarea" cols="60" rows="7" ></textarea>
    <button id="slidoc-remarks-render-button" class="slidoc-clickable slidoc-button" onclick="Slidoc.renderText(this);">Render</button>
  </div>
  <div id="slidoc-remarks-comments-content" class="slidoc-comments slidoc-comments-content" style="display: none;"></div>
  <span id="slidoc-remarks-content" class="slidoc-grade slidoc-grade-content" style="display: none;"></span>
'''

    # Templates: {'sid': slide_id, 'qno': question_number, 'inp_type': 'text'/'number', 'ansinput_style': , 'ansarea_style': }
    ansprefix_template = '''<span id="%(sid)s-answer-prefix" class="slidoc-answer-prefix %(ansdisp)s" data-qnumber="%(qno)d">Answer:</span>'''
    answer_template = '''
  <span id="%(sid)s-answer-prefix" class="slidoc-answer-prefix" data-qnumber="%(qno)d">Answer:</span>
  <button id="%(sid)s-answer-click" class="slidoc-clickable slidoc-button slidoc-answer-button slidoc-nogradable slidoc-nosubmitted slidoc-noprint %(ansdisp)s" onclick="Slidoc.answerClick(this, '%(sid)s');">Answer</button>
  <input id="%(sid)s-answer-input" type="%(inp_type)s" %(inp_step)s class="slidoc-answer-input slidoc-answer-box slidoc-nogradable slidoc-noansweredresubmit slidoc-nosubmitted slidoc-noprint slidoc-noplugin %(ansdisp)s" onkeydown="Slidoc.inputKeyDown(event);"></input>

  <span class="slidoc-answer-span slidoc-answeredonly">
    <span id="%(sid)s-response-span"></span>
    <span id="%(sid)s-correct-mark" class="slidoc-correct-answer"></span>
    <span id="%(sid)s-partcorrect-mark" class="slidoc-partcorrect-answer"></span>
    <span id="%(sid)s-wrong-mark" class="slidoc-wrong-answer"></span>
    <span id="%(sid)s-any-mark" class="slidoc-any-answer"></span>
    <span id="%(sid)s-answer-correct" class="slidoc-answer-correct slidoc-correct-answer %(ansdisp)s"></span>
  </span>
  %(explain)s %(boxlabel)s
  <textarea id="%(sid)s-answer-textarea" name="textarea" class="slidoc-answer-textarea slidoc-answer-box slidoc-nogradable slidoc-noansweredresubmit slidoc-noprint slidoc-noplugin %(ansdisp)s" %(boxsize)s ></textarea>
'''                

    grading_template = '''
  <div id="%(sid)s-grade-element" class="slidoc-grade-element slidoc-answeredonly %(zero_gwt)s">
    <button id="%(sid)s-gstart-click" class="slidoc-clickable slidoc-button slidoc-gstart-click slidoc-grade-button slidoc-gradableonly slidoc-nograding" onclick="Slidoc.gradeClick(this, '%(sid)s');">Start</button>
    <button id="%(sid)s-grade-click" class="slidoc-clickable slidoc-button slidoc-grade-click slidoc-grade-button slidoc-gradableonly slidoc-gradingonly" onclick="Slidoc.gradeClick(this,'%(sid)s');">Save</button>
    <span id="%(sid)s-gradeprefix" class="slidoc-grade slidoc-gradeprefix slidoc-gradable-graded"><em>Grade:</em></span>
    <input id="%(sid)s-grade-input" type="number" step="any" class="slidoc-grade-input slidoc-gradableonly slidoc-gradingonly" onkeydown="Slidoc.inputKeyDown(event);"></input>
    <span id="%(sid)s-grade-content" class="slidoc-grade slidoc-grade-content slidoc-nograding"></span>
    <span id="%(sid)s-gradesuffix" class="slidoc-grade slidoc-gradesuffix slidoc-gradable-graded">%(gweight)s</span>
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
<div id="%(sid)s-comments" class="slidoc-comments slidoc-comments-element slidoc-answeredonly slidoc-gradable-graded slidoc-graderesponseonly"><em>Comments:</em>
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
        self.sheet_attributes = {'disabledCount': 0, 'discussSlides': [], 'hiddenSlides': [], 'hints': defaultdict(list),
                                 'questionParams':[],  'remoteAnswers': [], 'shareAnswers': {}}

        self.sheet_attributes['resubmitAnswers'] = self.options['config'].pace <= BASIC_PACE and self.options['config'].show_score in ('after_submitting', 'after_grading')
        self.slide_number = 0
        self.slide_images = []

        self._new_slide()
        self.first_id = self.get_slide_id()
        self.index_id = ''                     # Set by render()
        self.qindex_id = ''                    # Set by render
        self.block_input_counter = 0
        self.block_test_counter = 0
        self.block_output_counter = 0
        self.block_solution_counter = 0
        self.toggle_slide_id = ''
        self.render_markdown = 'no_markdown' not in self.options['config'].features
        self.render_mathjax = 'math_input' in self.options['config'].features
        self.plugin_number = 0
        self.plugin_defs = {}
        self.plugin_tops = []
        self.plugin_loads = set()
        self.plugin_embeds = set()
        self.plugin_names = set()
        self.global_plugin_refs = set()
        self.load_python = False
        self.slide_maximage = 0
        self.last_question_props = {}

        self.images_zipfile = None
        self.images_map = {}
        if self.options['images_zipdata']:
            self.images_zipfile = zipfile.ZipFile(io.BytesIO(self.options['images_zipdata']), 'r')
            self.images_map = dict( (os.path.basename(fpath), fpath) for fpath in self.images_zipfile.namelist() if os.path.basename(fpath))

        self.content_zip_bytes = None
        self.content_zip = None
        self.content_image_paths = set()
        self.zipped_content = None
        if self.options['zip_content']:
            self.content_zip_bytes = io.BytesIO()
            self.content_zip = zipfile.ZipFile(self.content_zip_bytes, 'w')

        self.all_functions = []
        self.all_params = []
        self.current_params = []
        self.banner = ''
        self.retry_questions = False

    def _new_slide(self):
        self.slide_number += 1
        self.qtypes.append('')
        self.choice_end = None
        self.choice_questions = 0
        self.choice_notes = set()
        self.count_of_the_above = 0

        self.choice_star = ''
        self.choice_current = ''
        self.choice_expect = 'A'
        self.choice_alternatives = 0
        self.choice_full_alt = 0
        self.choice_opts = []
        self.choice_no_top_q = False
        self.choice_qprefix = ''

        self.cur_qtype = ''
        self.cur_header = ''
        self.untitled_header = ''
        self.slide_concepts = []
        self.alt_header = None
        self.incremental_level = 0
        self.incremental_list = False
        self.incremental_pause = False
        self.slide_block_test = []
        self.slide_block_output = []
        self.slide_block_hidden = 0
        self.slide_block_solution = 0
        self.slide_block_fillable = 0
        self.slide_forward_links = []
        self.slide_plugin_refs = {}
        self.slide_plugin_embeds = {}
        self.slide_images.append([])
        self.slide_img_tag = ''
        self.slide_options = set()
        if 'discuss_all' in self.options['config'].features:
            self.slide_options.add('discuss')
        self.slide_formulas = []
        self.slide_params = {}

    def close_zip(self, md_content=None):
        # Create zipped content (only if there are any images)
        if self.content_zip and self.content_image_paths:
            if md_content is not None:
                self.content_zip.writestr('content.md', md_content)
            self.content_zip.close()
            self.zipped_content = self.content_zip_bytes.getvalue()

    def list_incremental(self, activate):
        self.incremental_list = activate
    
    def forward_link(self, ref_id):
        self.slide_forward_links.append(ref_id)

    def add_ref_link(self, ref_id, num_label, key, ref_class):
        Global.ref_tracker[ref_id] = (num_label, key, ref_class, '%s#%s' % (self.options["filename"],self.slide_number) )
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

    def inline_formula(self, text, alt_text):
        text = text.strip()
        alt_text = alt_text.strip() if alt_text is not None else alt_text
        js_format = alt_text or ''
        slide_id = self.get_slide_id()
        plugin_refs = []
        imatch = INLINE_METHOD_RE.match(text)
        if imatch and imatch.group(1) not in FORMULA_NAMESPACE:
            plugin_def_name = imatch.group(1)
            action = imatch.group(2)
            js_arg = imatch.group(3)
            if action in ('answerSave', 'buttonClick', 'disable', 'display', 'enterSlide', 'expect', 'incrementSlide', 'init', 'initGlobal', 'initSetup', 'leaveSlide', 'response'):
                abort("    ****PLUGIN-ERROR: %s: Disallowed inline plugin action `=%s.%s()` in slide %s" % (self.options["filename"], plugin_def_name, action, self.slide_number))

        else:
            plugin_def_name = 'Params'
            action = 'formula'
            js_arg = text
            for match in INLINE_PLUGIN_RE.findall(text):
                if match[1] == '$':
                    plugin_refs.append( [match[2], int(match[3] or 0)] )
                elif match[1] == '$$':
                    self.global_plugin_refs.add(match[2])
            
        js_func = plugin_def_name + '.' + action
        alt_html = mistune.escape('='+js_func+'()' if alt_text is None else alt_text)
        if 'inline_formula' in self.options['config'].strip:
            return '<code>%s</code>' % exponentiate(alt_html, times=True)

        if plugin_def_name == 'Params' and action == 'formula':
            self.slide_formulas.append(js_arg)

        self.plugin_loads.add(plugin_def_name)

        plugin_refs.append( [plugin_def_name, 0] )
        for name, instance_num in plugin_refs:
             self.add_slide_plugin_ref(name, instance_num)

        return '<code class="slidoc-inline-js" data-slidoc-js-function="%s" data-slidoc-js-argument="%s" data-slidoc-js-format="%s" data-slide-id="%s">%s</code>' % (js_func, mistune.escape(js_arg or ''), mistune.escape(js_format or ''), slide_id or '', alt_html)

    def add_slide_plugin_ref(self, name, instance_num):
        if name not in self.slide_plugin_refs:
            self.slide_plugin_refs[name] = instance_num
        else:
            self.slide_plugin_refs[name] = max(self.slide_plugin_refs[name], instance_num)

    def get_chapter_id(self):
        return make_chapter_id(self.options['filenumber'])

    def get_slide_id(self, slide_number=0):
        return make_slide_id(self.options['filenumber'], slide_number or self.slide_number)

    def start_block(self, block_type, id_str, classes='', display='none'):
        prefix =        '\n<!--slidoc-%s-block-begin[%s]-->\n' % (block_type, id_str)
        end_str = '</div>\n<!--slidoc-%s-block-end[%s]-->\n' % (block_type, id_str)
        suffix =  '<div class="slidoc-%s %s %s" style="display: %s;">\n' % (block_type, id_str, classes, display)
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
        return '<br class="slidoc-full-block">\n'

    def pause(self, text):
        """Pause in display"""
        if 'incremental_slides' in self.options['config'].features:
            self.incremental_pause = True
            self.incremental_level += 1
            return ''
        else:
            return text

    def slide_prefix(self, slide_id, classes=''):
        chapter_id, sep, slideNumStr = slide_id.partition('-')
        slide_number = int(slideNumStr)
        prefix = str(slide_number)+'. ' if 'untitled_number' not in self.options['config'].features else ''
        html = '''<div id="%s-togglebar" class="slidoc-togglebar slidoc-full-block slidoc-droppable slidoc-collapsibleonly slidoc-noprint" data-slide="%d">\n''' % (slide_id, slide_number)
        html += '''  <span id="%s-toptoggle" class="slidoc-toptoggle">\n''' % slide_id
        html += '''    <span class="slidoc-toptoggle-icon slidoc-toggle-visible slidoc-clickable" onclick="Slidoc.accordionToggle('%s',false);">%s</span><span class="slidoc-toptoggle-icon slidoc-toggle-hidden slidoc-clickable" onclick="Slidoc.accordionToggle('%s',true);">%s</span>\n''' % (slide_id, SYMS['down'], slide_id, SYMS['rightarrow'])
        right_list = [ ('edit', SYMS['pencil']), ('drag', '&#8693')]
        for action, icon in right_list:
            toggle_classes = 'slidoc-toptoggle-edit slidoc-edit-icon slidoc-testuseronly slidoc-nolocalpreview slidoc-noupdate slidoc-serveronly'
            attrs = ''
            if action == 'drag':
                attrs += ' draggable="true" data-slide="%d"' % slide_number
                toggle_classes += ' slidoc-toggle-hidden slidoc-toggle-draggable'
            else:
                attrs += '''onclick="Slidoc.slideEdit('%s', '%s');"''' % (action, slide_id)
                toggle_classes += ' slidoc-toggle-visible slidoc-clickable'

            html += '''  <span class="%s" %s >%s</span>''' % (toggle_classes, attrs, icon)
            
        html += '''  <span id="%s-toptoggle-discuss" class="slidoc-toptoggle-edit slidoc-edit-icon slidoc-nolocalpreview slidoc-discussonly slidoc-serveronly slidoc-toggle-hidden" style="display: none;">%s</span>''' % (slide_id, SYMS['bubble'])

        site_name = self.options['config'].site_name
        site_prefix = '/'+site_name if site_name else ''

        html += '''    <span id="%s-toptoggle-header" class="slidoc-toptoggle-header slidoc-toggle-hidden slidoc-toggle-draggable" draggable="true" data-slide="%d">%s</span>''' % (slide_id, slide_number, prefix)
        html += '''  </span>\n'''
        html += '''</div>\n'''
        html += '''<div id="%s-togglebar-edit" class="slidoc-togglebar-edit slidoc-full-block slidoc-droppable slidoc-noupdate slidoc-noprint" data-slide="%s" style="display:none;">\n''' % (slide_id, slide_id)
        html += '''  <pre id="%s-togglebar-edit-status"></pre>\n''' % (slide_id,)
        html += '''  <div>\n'''
        html += '''    <button id="%s-togglebar-edit-save" onclick="Slidoc.slideEdit('save', '%s');">Save edits</button>''' % (slide_id, slide_id)
        html += '''    <button id="%s-togglebar-edit-discard" onclick="Slidoc.slideEdit('discard', '%s');">Discard edits</button>''' % (slide_id, slide_id)
        html += '''    <button id="%s-togglebar-edit-clear" onclick="Slidoc.slideEdit('clear', '%s');">Clear text</button>\n''' % (slide_id, slide_id)
        html += '''  </div><div>\n'''
        html += '''    <button id="%s-togglebar-edit-insert" class="slidoc-edit-update" onclick="Slidoc.slideEdit('insert', '%s');">Insert image</button>\n''' % (slide_id, slide_id)
        html += '''    <button id="%s-togglebar-edit-update" class="slidoc-edit-update slidoc-nomodpreview" onclick="Slidoc.slideEdit('update', '%s');">Update preview</button>\n''' % (slide_id, slide_id)
        html += '''    <button id="%s-togglebar-edit-open" class="slidoc-edit-update slidoc-nomodpreview" onclick="Slidoc.slideEdit('open', '%s');">Open preview</button>\n''' % (slide_id, slide_id)
        html += '''  </div>\n'''
        html += '''  <textarea id="%s-togglebar-edit-area" class="slidoc-togglebar-edit-area"></textarea>\n''' % (slide_id,)
        html += '''  <div id="%s-togglebar-edit-img" class="slidoc-togglebar-edit-img" style="display: none;">''' % (slide_id,)
        html += '''    <label>Autonumber images:</label><input id="%s-upload-img-autonumber" type="checkbox" class="slidoc-upload-img-autonumber" value="autonumber"></input></label>\n''' % (slide_id,)
        html += '''    <div class="slidoc-img-droparea slidoc-droppable slidoc-img-drop" data-slide-id="%s">Drop image here<br></div>\n''' % (slide_id,)
        html += '''  </div>'''
        html += '''</div>\n'''

        # Slides need to be unhidden in Javascript for paced/slides_only sessions
        style = ''
        if self.options['config'].pace or 'slides_only' in self.options['config'].features:
            style += 'display: none;'
        html += '\n<section id="%s" class="slidoc-slide %s-slide slidoc-full-block %s" style="%s"> <!--slide start-->\n' % (slide_id, chapter_id, classes, style)
        return html

    def slide_footer(self):
        slide_id = self.get_slide_id()
        header = self.cur_header or self.slide_img_tag or self.alt_header or ''
        if header and not header.startswith('<img '):
            header = mistune.escape(header)
        if self.cur_header or self.untitled_header or not self.toggle_slide_id:
            self.toggle_slide_id = slide_id
        elif header:
            # Nested header
            header = '&nbsp;&nbsp;&nbsp;' + header

        classes = []
        if 'hide' in self.slide_options and not self.options['config'].unhide_slides:
            if self.slide_number > 1 and not self.qtypes[-1] and self.options['config'].pace != QUESTION_PACE:
                # Explicitly hidden, not first slide, not question slide, and not question paced
                self.sheet_attributes['hiddenSlides'].append(self.slide_number)
                classes.append('slidoc-slide-hidden')
            else:
                message('    ****HIDDEN-WARNING: %s: Slide %s, Hidden: ignored for first slide/question slide/question-paced sessions' % (self.options["filename"], self.slide_number))

        attrs = ''
        if self.all_params:
            attrs += ' data-param-count="%d"' % len(self.all_params)
        if self.all_functions:
            attrs += ' data-function-count="%d"' % len(self.all_functions)
        html = '''<div id="%s-footer-toggle" class="slidoc-footer-toggle %s-footer-toggle slidoc-full-block %s" %s style="display:none;">%s</div>\n''' % (slide_id, self.toggle_slide_id, ' '.join(classes), attrs, header)
        return html

    def image(self, src, title, text):
        basename = os.path.basename(src)
        dirname = os.path.dirname(src)
        self.slide_images[-1].append(basename)
        fname = os.path.splitext(basename)[0]
        if fname.startswith('image'):
            suffix = fname[len('image'):]
            if suffix.isdigit():
                self.slide_maximage = max(self.slide_maximage, int(suffix))

        tem_msg = ''
        img_found = False
        new_src = src
        img_content = None
        copy_image = self.content_zip or self.options['config'].dest_dir
        url_type = md2md.get_url_scheme(src)
        if url_type == 'rel_path':
            # Image link is a relative filepath
            if self.images_zipfile:
                # Check for image in zip archive
                if basename in self.images_map:
                    img_found = True
                    if copy_image:
                        img_content = self.images_zipfile.read(self.images_map[basename])
                else:
                   tem_msg = ' and file %s not found in zip archive' % basename

            if not img_found:
                # Check for local image file
                new_src = md2md.find_image_path(src, filename=self.options['filename'], filedir=self.options['filedir'], image_dir=self.options['config'].image_dir)
                if not new_src:
                    raise Exception('NOIMAGE:Image file %s not found in %s%s' % (src, self.options['filedir'], tem_msg))

                if copy_image:
                    filepath = self.options['filedir']+'/'+new_src if self.options['filedir'] else new_src
                    img_content = md2md.read_file(filepath)

            if self.content_zip:
                # Copy image to zip file
                if self.options['config'].image_dir:
                    zpath = os.path.basename(self.options['config'].image_dir)+'/'+basename
                else:
                    zpath = '_images/'+basename
                new_src = zpath
                self.content_zip.writestr(zpath, img_content)
                self.content_image_paths.add(zpath)

            elif self.options['config'].dest_dir:
                # Copy image to subdirectory of destination directory
                # If image_dir == '_images', destination subdirectory will be sessionname_images
                if self.options['config'].image_dir == '_images':
                    img_dir = self.options['filename']+'_images'
                else:
                    img_dir = self.options['config'].image_dir or dirname or self.options['filename']+'_images'
                new_src = img_dir + '/' + basename
                out_path = self.options['config'].dest_dir + '/' + new_src
                out_dir  = self.options['config'].dest_dir + '/' + img_dir

                if not self.options['config'].preview_mode:
                    if not os.path.exists(out_dir):
                        os.mkdir(out_dir)

                    if os.path.exists(out_path) and img_content == md2md.read_file(out_path):
                        # File already present (with same content)
                        pass
                    else:
                        md2md.write_file(out_path, img_content)

        slide_id = self.get_slide_id()
        img_tag = md2md.new_img_tag(new_src, text, title, classes=['slidoc-img', 'slidoc-img-drop', slide_id+'-img'], image_url=self.options['config'].image_url)
        if not self.slide_img_tag:
            self.slide_img_tag = img_tag
        return img_tag


    def hrule(self, text='---', implicit=False):
        """Rendering method for ``<hr>`` tag."""
        if self.choice_end:
            prefix = self.choice_end

        if implicit or 'rule' in self.options['config'].strip or (self.hide_end and 'hidden' in self.options['config'].strip):
            rule_html = ''
        elif self.options.get('use_xhtml'):
            rule_html = '<hr class="slidoc-hrule slidoc-full-block slidoc-noslide slidoc-noprint slidoc-single-columnonly"/>\n'
        else:
            rule_html = '<hr class="slidoc-hrule slidoc-full-block slidoc-noslide slidoc-noprint slidoc-single-columnonly">\n'

        end_html = self.end_slide(rule_html)
        self._new_slide()
        new_slide_id = self.get_slide_id()

        classes = []
        if text.startswith('----'):
            if 'slide_break_page' not in self.options['config'].features:
                classes.append('slidoc-page-break-before')
            if 'two_column' in self.options['config'].features:
                classes.append('slidoc-single-column')

        return end_html + self.slide_prefix(new_slide_id, ' '.join(classes)) + concept_chain(new_slide_id, self.options['config'].server_url)

    def discuss_footer(self):
        html = ''
        slide_id = self.get_slide_id()
        if 'discuss' in self.slide_options:
            self.sheet_attributes['discussSlides'].append(self.slide_number)
            html += '''<div id="%s-discuss-footer" class="slidoc-discuss-footer slidoc-full-block slidoc-discussonly slidoc-noprint" style="display:none;">\n''' % (slide_id, )
            html += '''  <span id="%s-discuss-show" class="slidoc-discuss-show slidoc-clickable" onclick="Slidoc.slideDiscuss('show','%s');">%s</span>\n''' % (slide_id, slide_id, SYMS['bubble'])
            html += '''  <span id="%s-discuss-count" class="slidoc-discuss-count"></span>\n''' % (slide_id,)
            html += '''  <div id="%s-discuss-container" class="slidoc-discuss-container" style="display: none;">\n''' % (slide_id, )
            html += '''    <div id="%s-discuss-posts" class="slidoc-discuss-posts"></div>\n''' % (slide_id, )
            html += '''    <div><button id="%s-discuss-post" class="slidoc-discuss-post" onclick="Slidoc.slideDiscuss('post','%s');">Post</button></div>\n''' % (slide_id, slide_id, )
            html += '''    <textarea id="%s-discuss-textarea" class="slidoc-discuss-textarea"></textarea>\n''' % (slide_id,)
            html += '''    <div><button id="%s-discuss-preview" class="slidoc-discuss-preview" onclick="Slidoc.slideDiscuss('preview','%s');">Preview</button></div>\n''' % (slide_id, slide_id, )
            html += '''    <br><div id="%s-discuss-render" class="slidoc-discuss-render"></div>\n''' % (slide_id, )
            html += '''  </div>\n'''
            html += '''</div>\n'''
        return html

    def end_slide(self, suffix_html='', last_slide=False):
        prefix_html = self.end_extra()+self.end_hint()  # Hints/Notes will be ignored after Extra:

        if self.slide_params:
            keys = self.slide_params.keys()
            keys.sort()
            param_defs = [key+'='+self.slide_params[key] for key in keys]
            self.current_params.append(' '.join(param_defs))      # Used only for warning about structural changes
            self.all_params.append(';'.join(param_defs))          # Used to define parameter values

        if self.slide_formulas and 'Params' not in self.slide_plugin_embeds:
            prefix_html += self.embed_plugin_body('Params', self.get_slide_id())

        missing = []
        for name in self.slide_plugin_refs:
            if name not in self.slide_plugin_embeds:
                missing.append(name)
            elif self.slide_plugin_embeds[name] < self.slide_plugin_refs[name]:
                missing.append('%s[%s]' % (name, self.slide_plugin_refs[name]))
        if missing:
            abort("    ****PLUGIN-ERROR: %s: Missing plugins %s in slide %s." % (self.options["filename"], ','.join(missing), self.slide_number))
        if self.qtypes[-1]:
            # Question slide
            qnumber = len(self.questions)
            self.question_concepts.append(self.slide_concepts)

            if self.current_params:
                self.sheet_attributes['questionParams'].append(str(qnumber)+';'+';'.join(self.current_params))
                self.current_params = []

            if self.options['config'].pace and self.slide_forward_links:
                # Handle forward link in current question
                self.qforward[self.slide_forward_links[0]].append(qnumber)
                if len(self.slide_forward_links) > 1:
                    message("    ****ANSWER-ERROR: %s: Multiple forward links in slide %s. Only first link (%s) recognized." % (self.options["filename"], self.slide_number, self.slide_forward_links[0]))

        if last_slide and self.options['config'].pace:
            # Last paced slide
            if self.qtypes[-1]:
                pass
                ###abort('***ERROR*** Last slide cannot be a question slide for paced mode in module '+self.options["filename"])

            elif self.options['config'].pace == BASIC_PACE and 'Submit' not in self.plugin_loads:
                # Non-question slide and submit button not previously included in this slide or earlier slides
                prefix_html += self.embed_plugin_body('Submit', self.get_slide_id())

        ###if self.cur_qtype and not self.qtypes[-1]:
        ###    message("    ****ANSWER-ERROR: %s: 'Answer:' missing for %s question in slide %s" % (self.options["filename"], self.cur_qtype, self.slide_number))

        return prefix_html+self.end_notes()+self.end_hide()+self.discuss_footer()+suffix_html+('</section><!--%s-->\n' % ('last slide end' if last_slide else 'slide end')) + self.slide_footer()

    def list_item(self, text):
        """Rendering list item snippet. Like ``<li>``."""
        if not self.incremental_list:
            return super(SlidocRenderer, self).list_item(text)
        self.incremental_level += 1
        return '<li class="slidoc-incremental%d">%s</li>\n' % (self.incremental_level, text)

    def untitled_slide(self, text):
        if not self.cur_header:
            self.untitled_number += 1
            if 'untitled_number' in self.options['config'].features:
                # Number untitled slides (e.g., as in question numbering)
                if self.questions and len(self.questions)+1 != self.untitled_number:
                    abort("    ****QUESTION-ERROR: %s: Untitled number %d out of sync with question number %d in slide %s. Add explicit headers to non-question slides to avoid numbering" % (self.options["filename"], self.untitled_number, len(self.questions)+1, self.slide_number))
                    return ''

                self.untitled_header = '%d. ' % self.untitled_number

        tem_text = text.strip()
        while ANGLE_TEXT_RE.match(tem_text):
            tem_text = ANGLE_TEXT_RE.sub(r'\2', tem_text)
        if not tem_text or tem_text.startswith('<'):
            first_words = '...'
        else:
            comps = tem_text.split()
            first_words = ' '.join(comps[:7])  # First seven words of paragraph
            if len(comps) > 7:
                 first_words += '...'

        self.alt_header = self.untitled_header + first_words
        return self.untitled_header

    def paragraph(self, text):
        """Rendering paragraph tags. Like ``<p>``."""
        if self.alt_header is None:
            text = self.untitled_slide(text) + text

        if self.choice_opts:
            _, _, tem_text = text.rpartition('>')  # Strip any preceding markup
            tem_text = tem_text.strip().strip('.').strip() # Strip leading/trailing periods
            tem_text = md2md.normalize_text(tem_text, lower=True)
            if tem_text in ('all of the above', 'none of the above'):
                self.count_of_the_above += 1

        if not self.incremental_pause:
            return super(SlidocRenderer, self).paragraph(text)
        return '<p class="%s-incremental slidoc-incremental%d">%s</p>\n' % (self.get_slide_id(), self.incremental_level, text.strip(' '))

    def block_math(self, text):
        self.render_mathjax = True
        return super(SlidocRenderer, self).block_math(text)

    def latex_environment(self, name, text):
        self.render_mathjax = True
        return super(SlidocRenderer, self).latex_environment(name, text)

    def inline_math(self, text):
        self.render_mathjax = True
        return super(SlidocRenderer, self).inline_math(text)

    def block_code(self, code, lang=''):
        """Rendering block level code. ``pre > code``.
        python_input, python_solution, python_fillable, python_test, python_test_hidden, javascript..., nb_output, nb_error
        """
        if code.endswith('\n\n'):
            code = code[:-1]

        slide_id = self.get_slide_id()
        classes = 'slidoc-block-code slidoc-block-code-in-%s' % slide_id

        id_str = ''

        comps = (lang or '').split('_')
        lang = comps[0]
        blockType = comps[1] if len(comps) > 1 else ''
        blockOption = comps[2] if len(comps) > 2 else ''

        if lang in ('javascript','python') and blockType in ('input', 'solution', 'fillable'):
            self.block_input_counter += 1
            id_str = 'id="slidoc-block-input-%d"' % self.block_input_counter
            if blockType == 'input':
                classes += ' slidoc-block-input'
            elif blockType in ('solution', 'fillable'):
                if self.slide_block_solution:
                    abort("    ****SOLUTION-ERROR: %s: Multiple '*s' blocks in slide %s" % (self.options["filename"], lang, self.slide_number))
                self.slide_block_solution = self.block_input_counter
                classes += ' slidoc-block-solution'
                if self.options['config'].show_score == 'after_grading':
                    classes += ' slidoc-gradedonly'
                else:
                    classes += ' slidoc-answeredonly'
                if blockType == 'fillable':
                    self.slide_block_fillable = 1

        elif lang in ('javascript','python') and blockType == 'test':
            classes += ' slidoc-block-test'
            self.block_test_counter += 1
            self.slide_block_test.append(self.block_test_counter)
            id_str = 'id="slidoc-block-test-%d"' % self.block_test_counter
            if blockOption == 'hidden' or self.slide_block_hidden:
                # Hide all blocks after first hidden block (viewable only in preview modes)
                if not self.slide_block_hidden:
                    self.slide_block_hidden = len(self.slide_block_test)
                classes += ' slidoc-anypreviewonly'

        elif lang == 'nb' and blockType == 'output':
            lang = 'output'
            classes += ' slidoc-block-output'
            self.block_output_counter += 1
            self.slide_block_output.append(self.block_output_counter)
            id_str = 'id="slidoc-block-output-%d"' % self.block_output_counter
            if self.slide_block_hidden:
                classes += ' slidoc-anypreviewonly'

        elif lang == 'nb' and blockType == 'error':
            lang = 'error'
            classes += ' slidoc-block-error'

        lexer = None
        if HtmlFormatter and lang and lang not in ('output','error'):
            classes += ' slidoc-block-lang-'+lang
            try:
                lexer = get_lexer_by_name(lang, stripall=True)
            except ClassNotFound:
                code = lang + '\n' + code

        if blockType == 'fillable':
            comps = code.strip().split('\n')
            if lang == 'python' and comps[0].startswith('#'):
                # Strip first comment from displayed code
                comps = comps[1:]
            dispCode = '<code>' + '</code>\n<code>'.join(mistune.escape(x) for x in comps) + '</code>'
            dispHtml = re.sub(r'``([^`\n]+)``', r'''<input class="slidoc-fillable-input">''', dispCode)
            solution = re.sub(r'``([^`\n]+)``', r'''<span class="slidoc-fillable-solution">\1</span>''', mistune.escape(code.strip()))
            dispClasses = ' slidoc-block-fillable'
            dispIdStr = 'id=%s-block-fillable' % slide_id
            html = '\n<div %s class="%s"><pre>%s</pre></div>\n' % (dispIdStr, dispClasses, dispHtml)
            html += '\n<p></p>'
            html += '\n<div %s class="%s"><pre><code>%s</code></pre></div>\n' % (id_str, classes, solution)
            return html

        if lexer and HtmlFormatter:
            html = highlight(code, lexer, HtmlFormatter())
        else:
            html = '<pre><code>%s</code></pre>\n' % mistune.escape(code)
        
        return '\n<div %s class="%s">\n%s</div>\n' % (id_str, classes, html)

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
        text = text.strip()
        prev_slide_end = ''
        if (self.cur_header or self.alt_header) and level <= 2 and text:
            # Implicit horizontal rule before Level 1/2 header
            prev_slide_end = self.hrule(implicit=True)

        slide_id = self.get_slide_id()
        hdr_class = ''

        if self.notes_end is None:
            # Render header HTML element
            html = super(SlidocRenderer, self).header(text.strip('#'), level, raw=raw)
            try:
                hdr = ElementTree.fromstring(html)
            except Exception:
                # failed to parse, just return it unmodified
                return html
            hdr_class += ' slidoc-header %s-header' % slide_id
            if 'center_title' in self.options['config'].features:
                hdr_class += ' slidoc-center-text'
        else:
            # Header in Notes; render as plain text
            hdr = ElementTree.Element('p', {})
            hdr.text = text.strip('#')

        if hdr.get('class'):
            hdr_class += ' '+hdr.get('class') 

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
                message('    ****REF-WARNING: %s: Duplicate reference #%s in slide %s (also in %s)' % (self.options["filename"], header_ref, self.slide_number, Global.ref_tracker[ref_id][-1]))
        else:
            self.add_ref_link(ref_id, '??', header_ref, '')

        hdr.set('id', ref_id)
        hdr.set('data-slide-id', slide_id)

        hide_block = self.options['config'].hide and re.search(self.options['config'].hide, text)
        if level > 3 or (level == 3 and not (hide_block and self.hide_end is None)):
            # Ignore higher level headers (except for level 3 hide block, if no earlier header in slide)
            if self.alt_header is None:
                self.alt_header = text
            return ElementTree.tostring(hdr, method='html')

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
                if self.untitled_header:
                    hdr_prefix = self.untitled_header
                else:
                    # New section
                    self.section_number += 1
                    hdr_prefix = self.get_header_prefix()

                self.cur_header = (hdr_prefix + text.strip('#')).strip()
                if self.cur_header:
                    self.header_list.append( (slide_id, self.cur_header) )
                if 'sections' not in self.options['config'].strip:
                    clickable_secnum = True
            elif self.alt_header is None:
                self.alt_header = text.strip('#').strip()

            # Record header occurrence (preventing hiding of any more level 3 headers in the same slide)
            self.hide_end = ''

            if hide_block:
                # New block to hide answer/solution
                id_str = slide_id + '-hide'
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

        ##a = ElementTree.Element("a", {"class" : "anchor-link", "href" : "#" + slide_id})
        ##a.text = u' '
        ##hdr.append(a)

        # Known issue of Python3.x, ElementTree.tostring() returns a byte string
        # instead of a text string.  See issue http://bugs.python.org/issue10942
        # Workaround is to make sure the bytes are casted to a string.
        hdr.set('class', hdr_class)
        return prev_slide_end + pre_header + ElementTree.tostring(hdr, method='html') + '\n' + post_header

    def slidoc_header(self, name, text):
        if name == 'Slidoc:':
            return self.slidoc_options(name, text)

        if name == 'meldr-type' and text:
            params = text.split()
            type_code = params[0]
            if type_code in ('choice', 'multichoice', 'number', 'text', 'point', 'line'):
                self.cur_qtype = type_code
        return ''

    def slidoc_options(self, name, text):
        return ''

    def slidoc_slideopts(self, name, text):
        prev_slide_end = ''
        if self.cur_header or self.alt_header:
            # Implicit horizontal rule
            prev_slide_end = self.hrule(implicit=True)

        opts = text.lower().split()
        ALLOWED_OPTS = ('discuss', 'hide')
        for opt in opts:
            if opt in ALLOWED_OPTS:
                self.slide_options.add(opt)
            elif opt.startswith('no_') and opt[len('no_'):] in ALLOWED_OPTS:
                self.slide_options.discard( opt[len('no_'):] )
            else:
                message('    ****OPTION-WARNING: %s: Slide %s, Ignored invalid option Slide: %s; must be one of %s' % (self.options["filename"], self.slide_number, opt, '/'.join(ALLOWED_OPTS)))

        return prev_slide_end

    def slidoc_banner(self, name, text):
        self.banner = text.strip()
        return ''

    def slidoc_define(self, name, text):
        fmatch = DEFINE_FUNCTION_RE.match(text)
        if fmatch:
            self.all_functions.append( [fmatch.group(1), 'function '+fmatch.group(2).strip()] )
            return ''

        for param_def in text.split():
            match = DEFINE_PARAM_RE.match(param_def)
            if not match:
                abort("    ****DEFINE-ERROR: %s: Invalid Define: specification '%s' in slide %s; expecting name=value1[:value2[:count]] OR name=value1,value2,...  OR function name (arg1,arg2) {...}" % (self.options["filename"], param_def, self.slide_number))
                break
            param_name = match.group(1)
            param_value = match.group(2)
            if param_name in self.slide_params:
                abort("    ****DEFINE-ERROR: %s: Duplicate Define: specification '%s' vs. '%s' in slide %s" % (self.options["filename"], param_def, self.slide_params[param_name], self.slide_number))
            self.slide_params[param_name] = param_value

        return ''

    def slidoc_choice(self, name, star):
        name = name.upper()
        if self.notes_end:
            # Choice notes
            notes_name = name
            j = 1
            while notes_name in self.choice_notes:
                j += 1
                notes_name = name + str(j)
            self.choice_notes.add(notes_name)
            return '''</p><p id="%s-choice-notes-%s" class="slidoc-choice-notes" style="display: none;">''' % (self.get_slide_id(), notes_name)

        if name < 'A' or name > 'Q':
            return name+'..'

        alt_choice = False
        if name == 'Q':
            choiceNum = 0
            alt_choice = True
            if self.choice_full_alt:
                if self.choice_expect: 
                    abort("    ****CHOICE-ERROR: %s: Expected choice %s for alternative question %d in slide %s" % (self.options["filename"], self.choice_expect, self.choice_full_alt, self.slide_number))
                    return ''

            else:
                if self.alt_header is None:
                    self.choice_qprefix = self.untitled_slide('question...')
                if len(self.choice_opts) > 1 and any(self.choice_opts):
                    abort("    ****CHOICE-ERROR: %s: Cannot mix choice alternatives and full question alternatives in slide %s" % (self.options["filename"], self.slide_number))
                    return ''

            self.choice_current = ''

            if not self.choice_opts:
                self.choice_opts = [0]
            else:
                self.choice_opts[0] += 1

            if len(self.choice_opts) > 1:
                if self.choice_no_top_q:
                    abort("    ****CHOICE-ERROR: %s: Must specify top Q.. for full question alternatives in slide %s" % (self.options["filename"], self.slide_number))
                    return ''
                self.choice_full_alt += 1
        else:
            choiceNum = 1 + ord(name) - ord('A')
            if star and name not in self.choice_star:
                if not self.choice_full_alt:
                    self.choice_star += name
                else:
                    abort("    ****CHOICE-ERROR: %s: Correct choice in alternative (%s) does not match main question (%s) in slide %s" % (self.options["filename"], name, self.choice_star, self.slide_number))

            if not self.choice_opts:
                self.choice_no_top_q = True
                self.choice_opts = [0]

            if name == self.choice_current and not self.choice_full_alt:
                alt_choice = True
                self.choice_opts[choiceNum] += 1
            elif name == self.choice_expect:
                if not self.choice_full_alt:
                    self.choice_opts.append( 0 )
                else:
                    self.choice_opts[choiceNum] += 1
            else:
                abort("    ****CHOICE-ERROR: %s: Out of sequence choice %s when expecting %s in slide %s" % (self.options["filename"], name, self.choice_expect, self.slide_number))
                return name+'..'

            self.choice_current = name

        if self.choice_full_alt and choiceNum == len(self.choice_opts)-1:
            self.choice_expect = ''
        else:
            self.choice_expect = chr(choiceNum+ord('A'))

        if alt_choice and 'shuffle_choice' not in self.options['config'].features:
            abort("    ****CHOICE-ERROR: %s: Specify --features=shuffle_choice to handle alternative choices in slide %s" % (self.options["filename"], self.slide_number))
            return ''

        choice_opt = self.choice_opts[choiceNum]
        params = {'id': self.get_slide_id(), 'idtype': self.choice_current or 'question', 'opt': self.choice_current,
                  'alternative': str(choice_opt) if choice_opt else '', 'altid': str(choice_opt+1) if choice_opt else ''}
            
        prefix = ''
        if not self.choice_end:
            prefix += '</p><div id="%(id)s-choice-block" data-shuffle=""><div id="%(id)s-chart-header" class="slidoc-chart-header slidoc-text-orange" style="display: none;"></div>'
            self.choice_end = '</div></div><div id="%s-choice-shuffle"></div>\n' % self.get_slide_id()
            if self.choice_current:
                prefix += '<div class="slidoc-choice-item"><p class="slidoc-choice-option">\n'
            else:
                prefix += '<div class="slidoc-choice-item"><p class="slidoc-choice-question">\n'
        else:
            if self.choice_current:
                prefix += '</p></div><div class="slidoc-choice-item"><p class="slidoc-choice-option">\n'
            else:
                prefix += '</p></div><div class="slidoc-choice-item"><p class="slidoc-choice-question">\n'

        hide_answer = self.options['config'].pace or not self.options['config'].show_score

        if name != 'Q' and hide_answer:
            prefix += '''<span class="slidoc-chart-box %(id)s-chart-box" style="display: none;"><span id="%(id)s-chartbar-%(opt)s" class="%(id)s-chartbar slidoc-chart-bar" onclick="Slidoc.PluginMethod('Share', '%(id)s', 'shareExplain', '%(opt)s');" style="width: 0%%;"></span></span>\n'''

        classes = '%(id)s-choice-inner slidoc-choice-inner'
        attrs = 'data-alternative="%(alternative)s" data-choice="%(opt)s"'

        if name == 'Q':
            suffix = self.choice_qprefix
            classes += ' slidoc-choice-question'
        else:
            suffix = '. '
            classes += ' %(id)s-choice slidoc-choice'
            if hide_answer:
                classes += '  slidoc-clickable'
                attrs += ''' onclick="Slidoc.choiceClick(this, '%(id)s');"'''

        params['classes'] = classes % params
        params['attrs'] = attrs % params
        return (prefix+'''<span id="%(id)s-choice-%(idtype)s%(altid)s" class="%(classes)s" %(attrs)s>%(opt)s</span>'''+suffix) % params

    
    def plugin_definition(self, name, text):
        _, self.plugin_defs[name] = parse_plugin(name+' = {'+text)
        return ''

    def embed_plugin_body(self, plugin_def_name, slide_id, args='', content=''):
        if plugin_def_name in self.slide_plugin_embeds:
            if plugin_def_name in SINGLETON_PLUGINS:
                abort('ERROR Multiple instances of reserved plugin '+plugin_def_name+' in slide '+str(self.slide_number))
            self.slide_plugin_embeds[plugin_def_name] += 1
        else:
            self.slide_plugin_embeds[plugin_def_name] = 0
        self.plugin_embeds.add(plugin_def_name)

        # Load plugin in order of occurrence
        self.plugin_number += 1

        plugin_name = plugin_def_name
        if self.slide_plugin_embeds[plugin_def_name]:
            plugin_name += '-' + str(self.slide_plugin_embeds[plugin_def_name])

        self.plugin_names.add(plugin_name)

        plugin_def = self.plugin_defs.get(plugin_def_name) or self.options['plugin_defs'].get(plugin_def_name)
        if not plugin_def:
            abort('ERROR Plugin '+plugin_def_name+' not defined/closed!')
            return ''

        plugin_params = {'pluginName': plugin_name,
                         'pluginLabel': 'slidoc-plugin-'+plugin_name,
                         'pluginId': slide_id+'-plugin-'+plugin_name,
                         'pluginInitArgs': sliauth.safe_quote(args),
                         'pluginNumber': self.plugin_number,
                         'pluginButton': sliauth.safe_quote(plugin_def.get('BUTTON', ''))}

        if plugin_def_name not in self.plugin_loads:
            self.plugin_loads.add(plugin_def_name)
            plugin_top = plugin_def.get('TOP', '').strip()
            if plugin_top:
                try:
                    self.plugin_tops.append(plugin_top % plugin_params)
                except Exception, err:
                    abort('ERROR Template formatting error in TOP for plugin %s in slide %s: %s' % (plugin_name, self.slide_number, err))

        # Add slide-specific plugin params
        plugin_params['pluginSlideId'] = slide_id
        tem_params = plugin_params.copy()
        try:
            tem_params['pluginBodyDef'] = plugin_def.get('BODY', '') % plugin_params
        except Exception, err:
            abort('ERROR Template formatting error in Body for plugin %s in slide %s: %s' % (plugin_name, self.slide_number, err))
        body_div = self.plugin_body_template % tem_params

        content = unescape_slidoc_script(content)

        if '%(pluginBody)s' in content:
            # Insert plugin body at the right place within the HTML content
            tem_params = plugin_params.copy()
            tem_params['pluginBody'] = body_div
            try:
                plugin_params['pluginContent'] = content % tem_params
            except Exception, err:
                abort('ERROR Template formatting error in content for plugin %s in slide %s: %s' % (plugin_name, self.slide_number, err))
        else:
            # Save content as raw (pre) text (for plugin processing); insert plugin body after raw content
            if content:
                content = ('<pre id="%(pluginId)s-raw-content">' % plugin_params) + mistune.escape(content) + '</pre>'
            plugin_params['pluginContent'] = content + body_div
        return self.plugin_content_template % plugin_params

    def slidoc_plugin(self, name, text):
        if name in SINGLETON_PLUGINS:
            abort("    ****PLUGIN-ERROR: %s: Cannot embed special plugin %s in slide %s" % (self.options["filename"], self.untitled_number, name, self.slide_number))
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

            if not self.choice_full_alt:
                self.choice_alternatives = max(self.choice_opts)
                for j, x in enumerate(self.choice_opts):
                    if x and x != self.choice_alternatives:
                        abort("    ****CHOICE-ERROR: %s: Mismatch in number of alternatives for %s in slide %s: expected %d but got %d" % (self.options["filename"], chr(j-1+ord('A')) if j else 'Q', self.slide_number, self.choice_alternatives, x))
                        return ''

            else:
                self.choice_alternatives = self.choice_full_alt
                if self.choice_expect:
                    abort("    ****CHOICE-ERROR: %s: Expected choice %s for alternative question %d in slide %s" % (self.options["filename"], self.choice_expect, self.choice_full_alt, self.slide_number))
                    return ''

            if self.choice_alternatives > 9:
                abort("    ****CHOICE-ERROR: %s: More than %d alternatives in slide %s" % (self.options["filename"], self.choice_alternatives, self.slide_number))
                return ''

        all_options = ('explain', 'followup', 'maxchars', 'noshuffle', 'participation', 'retry', 'share', 'team', 'vote', 'weight')

        # Syntax
        #   Answer: [(answer_type=answer_value|answer_type|answer_value)] [; option[=value] [option2[=value2]] ...]
        if '`' in text:
            # Look for options after backticks
            text, sep, tail_text = text.rpartition('`')
            tail_text, _, opt_text = tail_text.partition(';')
            text += sep + tail_text
        else:
            text, _, opt_text = text.partition(';')

        if ';' in opt_text:
            # Backwards compatibility (where semicolons are used as separators)
            opt_comps = [x.strip() for x in opt_text.split(';')]
        else:
            opt_comps = shlex.split(opt_text) if opt_text else []

        if text and (text.split('=')[0].strip() in all_options):
             abort("    ****ANSWER-ERROR: %s: Insert semicolon before answer option 'Answer: ;%s' in slide %s" % (self.options["filename"], text, self.slide_number))

        weight_answer = ''
        maxchars = 0           # Max. length (in characters) for textarea
        noshuffle = 0          # If n > 0, do not randomly shuffle last n choices
        retry_counts = [0, 0]  # Retry count, retry delay
        opt_values = { 'disabled': ('all','choice'),  # Disable all answering or correct choice display for this question
                       'explain': ('yes', ),          # Require explanation for answer
                       'share': ('after_due_date', 'after_answering', 'after_grading'),
                       'team': ('response', 'setup'),
                       'vote': ('show_completed', 'show_live') }
        if self.options['config'].pace == ADMIN_PACE:
            # Change default share value for admin pace
            opt_values['share'] = ('after_answering', 'after_due_date', 'after_grading')
        answer_opts = { 'disabled': '', 'explain': '', 'followup': '', 'participation': '', 'share': '', 'team': '', 'vote': ''}
        for opt in opt_comps:
            num_match = re.match(r'^(followup|maxchars|noshuffle|participation|retry|weight)\s*=\s*((\d+(.\d+)?)(\s*,\s*\d+(.\d+)?)*)\s*$', opt)
            if num_match:
                try:
                    match_opt = num_match.group(1)
                    if match_opt == 'followup':
                        answer_opts['followup'] = abs(int(num_match.group(2).strip()))
                    elif match_opt == 'maxchars':
                        maxchars = abs(int(num_match.group(2).strip()))
                    elif match_opt == 'noshuffle':
                        noshuffle = abs(int(num_match.group(2).strip()))
                    elif match_opt == 'participation':
                        answer_opts['participation'] = float(num_match.group(2).strip())
                    elif match_opt == 'retry':
                        num_comps = [int(x.strip() or '0') for x in num_match.group(2).strip().split(',')]
                        retry_counts = [num_comps[0], 0]
                        if len(num_comps) > 1 and num_comps[0]:
                            retry_counts[1] = num_comps[1]
                    elif match_opt == 'weight':
                        weight_answer = num_match.group(2).strip()
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

                    answer_opts[opt_name] = option_match.group(3) or opt_values[opt_name][0]
                else:
                    abort("    ****ANSWER-ERROR: %s: 'Answer: ... %s' is not a valid answer option for slide %s" % (self.options["filename"], opt, self.slide_number))

        if not answer_opts['share']:
            if (answer_opts['vote'] or 'share_all' in self.options['config'].features):
                answer_opts['share'] = opt_values['share'][0]
            elif 'share_answers' in self.options['config'].features:
                answer_opts['share'] = opt_values['share'][-1]

        if answer_opts['share'] and self.options['config'].show_score == 'after_grading':
            answer_opts['share'] = opt_values['share'][2]

        slide_id = self.get_slide_id()
        plugin_name = ''
        plugin_action = ''
        plugin_arg = ''
        plugin_format = ''

        valid_simple_types = ['choice', 'multichoice', 'number', 'text', 'point', 'line']
        valid_all_types = valid_simple_types + ['text/x-code', 'text/markdown', 'text/multiline', 'text/plain'] # markdown, multiline for legacy
        qtype = ''
        type_match = ANSWER_TYPE_RE.match(text)
        if type_match:
            # Check if 'answer_type=correct_answer_or_formula'
            # (Either answer_type or correct_answer_or_formula may be omitted, along with =, if there is no ambiguity)
            qtype = type_match.group(1)
            text = type_match.group(2).strip()
            if qtype not in valid_simple_types:
                abort("    ****ANSWER-ERROR: %s: %s is not a valid answer type; expected %s=answer in slide %s" % (self.options["filename"], qtype, '|'.join(valid_simple_types), self.slide_number))

        embed_defs = []
        expect_match = ANSWER_EXPECT_RE.match(text)
        formula_match = ANSWER_FORMULA_RE.match(text)
        if expect_match:
            # For backwards compatibility only
            # `=Plugin_name.expect([n]);;format`
            # format = number OR 1*10**(-1)+/-range
            plugin_name = expect_match.group(1)
            plugin_action = expect_match.group(2)
            plugin_arg = expect_match.group(3) or ''
            plugin_format = expect_match.group(5) if expect_match.group(5) else ''
            text = exponentiate(plugin_format)
        elif formula_match:
            # `=...;;format`
            plugin_name = 'Params'
            plugin_action = 'formula'
            plugin_arg = formula_match.group(1).strip()
            plugin_format = formula_match.group(3) if formula_match.group(2) else ''
            text = exponentiate(plugin_format)
            self.slide_formulas.append(plugin_arg)
            plugin_refs = []
            for match in INLINE_PLUGIN_RE.findall(plugin_arg):
                if match[1] == '$':
                    self.add_slide_plugin_ref(match[2], int(match[3] or 0))
                    if match[2] not in embed_defs:
                        embed_defs.append(match[2])
                elif match[1] == '$$':
                    self.global_plugin_refs.add(match[2])
        elif text.startswith('`'):
            abort("    ****ANSWER-ERROR: %s: Expecting Answer: ...`=formula`, but found %s in slide %s" % (self.options["filename"], text, self.slide_number))

        num_match = re.match(r'^([-+/\d\.eE\s%]+)$', text)
        if num_match and text.lower() != 'e' and (not qtype or qtype == 'number'):
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
                abort("    ****ANSWER-ERROR: %s: 'Answer: %s' is not a valid numeric answer; expect 'ans +/- err' in slide %s" % (self.options["filename"], text, self.slide_number))

        elif not qtype:
            amatch = ANSWER_CONTENT_RE.match(text)
            if text.lower() in valid_all_types:
                # Unspecified correct answer
                qtype = text.lower()
                text = ''
            elif not plugin_name and amatch:
                # Plugin_name/arg
                plugin_name = amatch.group(1)
                tem_args = amatch.group(2).strip()

                arg_pattern = None
                if plugin_name in self.plugin_defs:
                    arg_pattern = self.plugin_defs[plugin_name].get('ArgPattern', '')
                elif plugin_name in self.options['plugin_defs']:
                    arg_pattern = self.options['plugin_defs'][plugin_name].get('ArgPattern', '')
                else:
                    abort("    ****ANSWER-ERROR: %s: 'Answer: %s' missing definition for response plugin %s in slide %s" % (self.options["filename"], text, plugin_name, self.slide_number))

                if arg_pattern and not re.match(arg_pattern, tem_args):
                    abort("    ****ANSWER-ERROR: %s: 'Answer: %s' invalid arguments for plugin %s, expecting %s; in slide %s" % (self.options["filename"], text, plugin_name, arg_pattern, self.slide_number))

                plugin_action = 'response'
                qtype = plugin_name + '/' + tem_args
                text = ''

        if plugin_name:
            if 'inline_formula' in self.options['config'].strip and plugin_action in ('expect', 'formula'):
                plugin_name = ''
                plugin_action = ''
            else:
                if plugin_name not in embed_defs:
                    embed_defs.append(plugin_name)

        for def_name in embed_defs:
            if def_name not in self.slide_plugin_embeds:
                html_prefix += self.embed_plugin_body(def_name, slide_id)

        html_suffix = ''
        if answer_opts['share']:
            if 'Share' not in self.slide_plugin_embeds:
                html_suffix += self.embed_plugin_body('Share', slide_id)

            if self.options['config'].pace == ADMIN_PACE and 'Timer' not in self.slide_plugin_embeds:
                html_suffix += self.embed_plugin_body('Timer', slide_id)
                
        if self.choice_opts:
            if not qtype or qtype in ('choice', 'multichoice'):
                # Correct choice(s)
                if self.choice_star:
                    text = self.choice_star
                else:
                    text = ''.join(x for x in text if ord(x) >= ord('A') and ord(x)-ord('A') < len(self.choice_opts)-1)

                if qtype == 'choice':
                    # Multiple answers for choice are allowed with a warning (to fix grading problems)
                    if len(text) > 1:
                        message("    ****ANSWER-WARNING: %s: 'Answer: choice=%s' expect single choice in slide %s" % (self.options["filename"], text, self.slide_number))
                elif not qtype:
                    qtype = 'multichoice' if len(text) > 1 else 'choice'

                if not noshuffle and self.count_of_the_above:
                    if 'auto_noshuffle' in self.options['config'].features:
                        noshuffle = self.count_of_the_above
                    else:
                        message("    ****CHOICE-WARNING: Choice question %d may need noshuffle=%d value for '... of the above' option(s)" % (len(self.questions)+1, self.count_of_the_above))
            else:
                # Ignore choice options
                self.choice_opts = []
                
        if qtype in ('text/markdown', 'text/multiline'):  # Legacy support
            qtype = 'text/plain'

        if not self.cur_qtype:
            # Default answer type is 'text'
            self.cur_qtype = qtype or 'text'

        elif qtype and qtype != self.cur_qtype:
            abort("    ****ANSWER-ERROR: %s: 'Answer: %s' line inconsistent; expected 'Answer: %s' in slide %s" % (self.options["filename"], qtype, self.cur_qtype, self.slide_number))

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
                    message("    ****ANSWER-WARNING: %s: 'Answer: %s' in slide %s does not parse properly as html: %s'" % (self.options["filename"], text, self.slide_number, excp))

        multiline_answer = self.cur_qtype.startswith('text/')
        if multiline_answer:
            answer_opts['explain'] = ''      # Explain not compatible with textarea input

        self.qtypes[-1] = self.cur_qtype
        self.questions.append({})
        qnumber = len(self.questions)

        if plugin_name:
            if plugin_name == 'Params' and plugin_action == 'formula':
                correct_val = '=' + plugin_arg
            elif plugin_action != 'response':
                # For backwards compatibility only
                formula = '$.' + plugin_name + '.' + plugin_action +'(' + plugin_arg + ')'
                correct_val = '=' + formula
                plugin_name = 'Params'
                plugin_action = 'formula'
                self.slide_formulas.append(formula)
            else:
                correct_val = ''

            if plugin_format:
                correct_val += ';;' + plugin_format
            elif correct_text:
                correct_val = correct_text + correct_val
        else:
            correct_val = correct_text

        if 'remote_answers' in self.options['config'].features:
            self.sheet_attributes['remoteAnswers'].append(correct_val)
            correct_val = ''

        if answer_opts['followup']:
            if not self.last_question_props:
                abort("    ****FOLLOWUP-ERROR: %s: Answer: followup=%s not allowed for first question in slide %s" % (self.options["filename"], answer_opts['followup'], self.slide_number))

            last_followup = self.last_question_props['followup'] or 0
            if answer_opts['followup'] not in (last_followup, last_followup+1):
                abort("    ****FOLLOWUP-ERROR: %s: Answer: Expecting followup=%s/%s but found followup=%s in slide %s" % (self.options["filename"], last_followup, last_followup+1, answer_opts['followup'], self.slide_number))

            if self.choice_alternatives != self.last_question_props['alternatives']:
                abort("    ****FOLLOWUP-ERROR: %s: Answer: Expecting %s alternatives but found %s for followup=%s question in slide %s" % (self.options["filename"], self.last_question_props['alternatives'], self.choice_alternatives, answer_opts['followup'], self.slide_number))


        self.last_question_props = {'alternatives': self.choice_alternatives, 'followup': answer_opts['followup'] or 0}

        self.questions[-1].update(qnumber=qnumber, qtype=self.cur_qtype, slide=self.slide_number, correct=correct_val,
                                  weight=1)

        if answer_opts['disabled']:
            self.questions[-1].update(disabled=answer_opts['disabled'])
            if answer_opts['disabled'] == 'all':
                self.sheet_attributes['disabledCount'] += 1
        if answer_opts['explain']:
            self.questions[-1].update(explain=answer_opts['explain'])
        if answer_opts['followup']:
            self.questions[-1].update(followup=answer_opts['followup'])
        if answer_opts['participation']:
            self.questions[-1].update(participation=answer_opts['participation'])
        if answer_opts['share']:
            self.questions[-1].update(share=answer_opts['share'])
        if answer_opts['team']:
            self.questions[-1].update(team=answer_opts['team'])
        if answer_opts['vote']:
            self.questions[-1].update(vote=answer_opts['vote'])

        if self.cur_qtype in ('choice', 'multichoice'):
            self.questions[-1].update(choices=len(self.choice_opts)-1)
            if self.choice_alternatives:
                self.questions[-1].update(alternatives=self.choice_alternatives)
        if noshuffle:
            self.questions[-1].update(noshuffle=noshuffle)
        if retry_counts[0]:
            self.retry_questions = True
            self.questions[-1].update(retry=retry_counts)
        if correct_html and correct_html != correct_text:
            self.questions[-1].update(correct_html=correct_html)
        if self.block_input_counter:
            self.questions[-1].update(input=self.block_input_counter)
        if self.slide_block_test:
            self.questions[-1].update(test=self.slide_block_test)
        if self.slide_block_output:
            self.questions[-1].update(output=self.slide_block_output)
        if self.slide_block_solution:
            self.questions[-1].update(solution=self.slide_block_solution)
        if self.slide_block_fillable:
            self.questions[-1].update(fillable=self.slide_block_fillable)
        if self.slide_block_hidden:
            self.questions[-1].update(hiddentest=self.slide_block_hidden)

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

        ans_grade_fields = self.process_weights(weight_answer, plugin_action)

        points_span = ''
        if 'answer_credits' in self.options['config'].features:
            sweight = self.questions[-1].get('weight', 0)
            gweight = self.questions[-1].get('gweight', 0)
            pcredit = self.questions[-1].get('participation', 0)
            points_str = 'Max points: %g' % (sweight+gweight) if gweight else 'Points: %g' % sweight
            if sweight and (pcredit or multiline_answer):
                points_str += ', Points for attempting: %g' % (sweight*(pcredit if pcredit else 1))
            points_span = '<span class="slidoc-ans-points">(%s)</span>' % points_str

        html_prefix += '<div class="slidoc-ans-credit"><span id="%s-ans-attempt-count" class="slidoc-ans-attempt-count slidoc-slideonly"></span>%s</div>' % (slide_id, points_span)

        id_str = self.get_slide_id()
        ans_params = { 'sid': id_str, 'qno': len(self.questions), 'ansdisp': ''}

        if answer_opts['disabled']:
            if self.options['config'].pace > BASIC_PACE:
                abort("    ****ANSWER-ERROR: %s: 'Answer disabling incompatible with pace value: slide %s" % (self.options["filename"], self.slide_number))
            if answer_opts['disabled'] == 'choice':
                ans_params['ansdisp'] = ' slidoc-ansdisp-disabled-choice'
            else:
                ans_params['ansdisp'] = ' slidoc-ansdisp-disabled'
        elif self.cur_qtype == 'choice':
            ans_params['ansdisp'] = 'slidoc-ansdisp-choice'
        elif self.cur_qtype == 'multichoice':
            ans_params['ansdisp'] = 'slidoc-ansdisp-multichoice'

        if not self.options['config'].pace and ('answers' in self.options['config'].strip or not correct_val):
            # For unpaced sessions, if stripping correct answers or no correct answer, do not display answer box
            return html_prefix+(self.ansprefix_template % ans_params)+'<p></p>\n'

        hide_answer = self.options['config'].pace or not self.options['config'].show_score 
        if not self.slide_block_solution and len(self.slide_block_test) != len(self.slide_block_output):
            hide_answer = False
            abort("    ****ANSWER-ERROR: %s: Test block count %d != output block_count %d in slide %s" % (self.options["filename"], len(self.slide_block_test), len(self.slide_block_output), self.slide_number))

        if not hide_answer:
            # No hiding of correct answers
            return html_prefix+(self.ansprefix_template % ans_params)+' '+correct_html+'<p></p>\n'

        ans_classes = ''
        if multiline_answer:
            ans_classes += ' slidoc-multiline-answer'
        if answer_opts['explain']:
            ans_classes += ' slidoc-explain-answer'
        if self.cur_qtype in ('choice', 'multichoice'):
            ans_classes += ' slidoc-choice-answer'

        if plugin_name and plugin_action not in ('expect', 'formula'):
            ans_classes += ' slidoc-answer-plugin'
        if self.slide_block_fillable:
            ans_classes += ' slidoc-answer-fillable'

        if self.questions[-1].get('gweight'):
            gweight_str = '/'+str(self.questions[-1]['gweight'])
            zero_gwt = ''
        else:
            gweight_str = ''
            zero_gwt = ' slidoc-zero-gradeweight'

        inp_type = 'text'
        inp_step = ''
        if self.cur_qtype == 'number':
            inp_type = 'number'
            inp_step = ' step="any" '
        ans_params.update(ans_classes=ans_classes,
                        inp_type=inp_type,
                        inp_step=inp_step,
                        gweight=gweight_str,
                        zero_gwt=zero_gwt,
                        explain=('<br><span id="%s-explainprefix" class="slidoc-explainprefix"><em>Explain:</em></span>' % id_str) if answer_opts['explain'] else '')

        if maxchars:
            ncols = 60
            nrows = 1 + int((maxchars-1) / ncols)
            ans_params['boxsize'] = 'maxlength="%d" cols="%d" rows="%d"' % (maxchars, ncols, nrows)
            ans_params['boxlabel'] = '<em>(%d characters)</em>' % maxchars
        else:
            ans_params['boxsize'] = 'cols="60" rows="5"'
            ans_params['boxlabel'] = ''

        html_template = '''\n<div id="%(sid)s-answer-container" class="slidoc-answer-container %(ans_classes)s">\n'''+self.answer_template

        if ans_grade_fields:
            html_template += self.grading_template
            html_template += self.comments_template_a

        if self.render_markdown and (self.cur_qtype == 'text/plain' or answer_opts['explain']):
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


    def process_weights(self, text, plugin_action=''):
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
                message("    ****WEIGHT-WARNING: %s: Not grading question with weight %d line in slide %s (no sheet URL?)" % (self.options["filename"], gweight, self.slide_number))

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

            if self.questions[-1].get('team') and plugin_action == 'response':
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

    def slidoc_tags(self, name, text):
        if not text:
            return ''

        ###if self.notes_end is not None:
        ###    message("    ****TAGS-ERROR: %s: 'Tags: %s' line after Notes: ignored in '%s'" % (self.options["filename"], text, self.cur_header))
        ###    return ''

        if self.slide_concepts:
            message("    ****TAGS-ERROR: %s: Extra 'Tags: %s' line ignored in '%s'" % (self.options["filename"], text, self.cur_header or ('slide%02d' % self.slide_number)))
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
                        self.concept_warnings.append("TAGS-WARNING: %s: '%s' not covered before '%s'" % (self.options["filename"], tag, self.cur_header or ('slide%02d' % self.slide_number)) )
                        message("        "+self.concept_warnings[-1])

                add_to_index(Global.primary_qtags, Global.sec_qtags, p_tags, s_tags, self.options["filename"], self.get_slide_id(), self.cur_header, qconcepts=self.qconcepts)
            else:
                # Not question
                add_to_index(Global.primary_tags, Global.sec_tags, p_tags, s_tags, self.options["filename"], self.get_slide_id(), self.cur_header)

        if 'tags' in self.options['config'].strip:
            # Strip tags
            return ''

        id_str = self.get_slide_id()+'-concepts'
        display_style = 'inline' if self.options['config'].printable else 'none'
        tag_html = '''<div class="slidoc-concepts-container slidoc-noslide slidoc-nopaced slidoc-noassessment"><span class="slidoc-clickable" onclick="Slidoc.toggleInlineId('%s')">%s:</span> <span id="%s" style="display: %s;">''' % (id_str, name.capitalize(), id_str, display_style)

        if self.options['config'].index:
            for j, tag in enumerate(all_tags):
                if j == len(p_tags):
                    tag_html += ': '
                elif j:
                    tag_html += '; '
                tag_hash = '#%s-concept-%s' % (self.index_id, md2md.make_id_from_text(tag))
                tag_html += nav_link(tag, self.options['config'].server_url, self.options['config'].index,
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
            message("    ****HINT-WARNING: %s: Hint displayed for non-question-paced module in slide %s" % (self.options["filename"], self.slide_number))

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
        classes = '' if self.qtypes[-1] else 'slidoc-plain-notes'
        start_str, suffix, end_str = self.start_block('notes', id_str, display=disp_block, classes=classes)
        prefix += start_str
        self.notes_end = end_str
        classes = 'slidoc-clickable'
        if self.qtypes[-1]:
            classes += ' slidoc-question-notes'
        return prefix + ('''<br class="slidoc-full-block"><span id="%s" class="%s" onclick="Slidoc.classDisplay('%s')" style="display: inline;">Notes:</span>\n''' % (id_str, classes, id_str)) + suffix


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
            toc.append('<li>'+ElementTree.tostring(elem, method='html')+'</li>')

        toc.append('</ol>\n' if 'sections' in self.options['config'].strip else '</ul>\n')
        return '\n'.join(toc)

def click_span(text, onclick, id='', classes=['slidoc-clickable'], href=''):
    id_str = ' id="%s"' % id if id else ''
    if href:
        return '''<a %s href="%s" class="%s" onclick="%s">%s</a>''' % (id_str, href, ' '.join(classes), onclick, text)
    else:
        return '''<span %s class="%s" onclick="%s">%s</span>''' % (id_str, ' '.join(classes), onclick, text)

def nav_link(text, server_url, href, hash='', separate=False, keep_hash=False, printable=False, target='', classes=[]):
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
        return '''<a class="%s" href="%s%s" onclick="Slidoc.go('%s');" %s>%s</a>'''  % (class_str, server_url, hash or href, hash or href, extras, text)
    elif not separate:
        return '''<span class="%s" onclick="Slidoc.go('%s');" %s>%s</span>'''  % (class_str, hash or href, extras, text)
    elif href or text.startswith('&'):
        return '''<a class="%s" href="%s%s" %s>%s</a>'''  % (class_str, server_url, href+hash if hash and keep_hash else href, extras, text)
    else:
        return '<span class="%s">%s</span>' % (class_str, text)

Missing_ref_num_re = re.compile(r'_MISSING_SLIDOC_REF_NUM\(#([-.\w]+)\)')
def Missing_ref_num(match):
    ref_id = match.group(1)
    if ref_id in Global.ref_tracker:
        return Global.ref_tracker[ref_id][0]
    else:
        return '(%s)??' % ref_id

HTML_COMMENT_RE =  re.compile(r'^\s*<!--.*-->\s*\n?$')
SLIDE_BREAK_RE  =  re.compile(r'^ {0,3}(----* *|Slide:|#[^#].*|##[^#].*)\n?$')
HRULE_BREAK_RE  =  re.compile(r'(\S *\n)( {0,3}----* *(\n|$))')
    
def md2html(source, filename, config, filenumber=1, filedir='', plugin_defs={}, prev_file='', next_file='', index_id='', qindex_id='',
            zip_content=False, images_zipdata=None):
    """Convert a markdown string to HTML using mistune, returning (first_header, file_toc, renderer, md_params, html, zipped_content_images)"""
    Global.chapter_ref_counter = defaultdict(int)

    renderer = SlidocRenderer(escape=False, filename=filename, config=config, filenumber=filenumber, filedir=filedir, plugin_defs=plugin_defs,
                              images_zipdata=images_zipdata, zip_content=zip_content)
    md_parser_obj = MarkdownWithSlidoc(renderer=renderer)
    content_html = md_parser_obj.render(source, index_id=index_id, qindex_id=qindex_id)

    if renderer.retry_questions and config.pace < QUESTION_PACE :
        message('RETRY-WARNING: retry=... answer option only works with pace >= %d' % (QUESTION_PACE,))

    md_slides = md_parser_obj.block.get_slide_text()  # Slide markdown list (split only by hrule)
    header_opts, nskip = sliauth.read_header_opts(io.BytesIO(md_slides[0]))
    if nskip:
        md_defaults = md_slides[0][:nskip]
        md_slides[0] = md_slides[0][nskip:]
    else:
        md_defaults = ''
        
    md_source = source.strip()   # Note: source is already preprocessed
    md_digest = sliauth.digest_hex(md_source)
    if len(md_slides) != renderer.slide_number:
        message('SLIDES-WARNING: pre-parsing slide count (%d) does not match post-parsing slide count (%d)' % (len(md_slides), renderer.slide_number))
        md_slides = []
        md_defaults = ''

    elif (md_defaults+''.join(md_slides)).strip() != md_source:
        tem_str = md_defaults+''.join(md_slides).strip()
        for j in range(min(len(tem_str), len(md_source))):
            if tem_str[j] != md_source[j]:
                break
        message('SLIDES-WARNING: combined slide text does not match preprocessed source text: %d, %d, %d; %s, %s' % (len(tem_str), len(md_source), j, repr(tem_str[max(j-10,0):j+20]), repr(md_source[max(j-10,0):j+20])))
        md_slides = []
        md_defaults = ''

    md_breaks = []
    count = 0
    for md_slide in md_slides:
        count += len(md_slide)
        md_breaks.append(count)

    md_params = {'md_digest': md_digest, 'md_defaults': md_defaults, 'md_slides': md_slides, 'md_breaks': md_breaks,
                 'md_images': renderer.slide_images, 'md_header': renderer.file_header, 'new_image_number': renderer.slide_maximage+1}
    content_html = Missing_ref_num_re.sub(Missing_ref_num, content_html)

    if renderer.questions:
        # Compute question hash digest to track questions
        source_text = source.encode('utf-8') if isinstance(source, unicode) else source
        _, skip_bytes = sliauth.read_header_opts(io.BytesIO(source_text))
        sbuf = io.BytesIO(source_text[skip_bytes:])
        slide_hash = []
        slide_lines = []
        first_slide = True
        prev_hrule = True
        prev_slideopt = False
        prev_blank = True
        fenced_code = False
        slide_header = ''
        while True:
            line = sbuf.readline()
            if not line:
                slide_hash.append( sliauth.digest_hex((''.join(slide_lines)).strip()) )
                break

            if not line.strip() or HTML_COMMENT_RE.match(line) or MathBlockGrammar.slidoc_define.match(line) or MathBlockGrammar.slidoc_header.match(line) or MathBlockGrammar.slidoc_options.match(line):
                # Blank line (treat HTML comment or Params or slidoc comment line as blank)
                if prev_blank:
                    # Skip multiple blank lines (for digest computation)
                    continue
                prev_blank = True
            else:
                prev_blank = False

            if line.startswith('```'):
                fenced_code = not fenced_code

            if fenced_code:
                continue

            append_line = line
            new_slide = False
            lmatch = SLIDE_BREAK_RE.match(line)
            if lmatch:
                if lmatch.group(1).startswith('---'):
                    new_slide = True
                    prev_hrule = True
                    prev_slideopt = False
                    append_line = None        # Exclude hrule line from slide hash
                elif lmatch.group(1).startswith('Slide:'):
                    if not prev_hrule:
                        new_slide = True
                    prev_hrule = False
                    prev_slideopt = True
                else:
                    if not prev_hrule and not prev_slideopt:
                        new_slide = True
                    prev_hrule = False
                    prev_slideopt = False
            elif not prev_blank:
                prev_hrule = False
                prev_slideopt = False

            if new_slide:
                slide_hash.append( sliauth.digest_hex((''.join(slide_lines)).strip()) )
                slide_lines = []
                prev_blank = True
                first_slide = False

            if append_line is not None:
                slide_lines.append(append_line)

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
            nav_html += nav_link(SYMS['return'], config.server_url, config.toc, hash='#'+make_chapter_id(0), separate=config.separate, classes=['slidoc-noprint'], printable=config.printable) + SPACER6
            nav_html += nav_link(SYMS['prev'], config.server_url, prev_file, separate=config.separate, classes=['slidoc-noall'], printable=config.printable) + SPACER6
            nav_html += nav_link(SYMS['next'], config.server_url, next_file, separate=config.separate, classes=['slidoc-noall'], printable=config.printable) + SPACER6

        ###sidebar_html = click_span(SYMS['trigram'], "Slidoc.sidebarDisplay();", classes=["slidoc-clickable-sym", 'slidoc-nosidebar']) if config.toc and not config.separate else ''
        ###slide_html = SPACER3+click_span(SYMS['square'], "Slidoc.slideViewStart();", classes=["slidoc-clickable-sym", 'slidoc-nosidebar'])
        sidebar_html = ''
        slide_html = ''
        pre_header_html += '<div class="slidoc-pre-header slidoc-noslide slidoc-noprint slidoc-noall">'+nav_html+sidebar_html+slide_html+'</div>\n'

        tail_html = '<div class="slidoc-noslide slidoc-noprint">' + nav_html + ('<a href="#%s" class="slidoc-clickable-sym">%s</a>%s' % (renderer.first_id, SYMS['up'], SPACER6) if renderer.slide_number > 1 else '') + '</div>\n'

    if 'contents' not in config.strip:
        chapter_id = make_chapter_id(filenumber)
        header_toc = renderer.table_of_contents(filenumber=filenumber)
        if header_toc:
            post_header_html += ('<div class="slidoc-chapter-toc %s-chapter-toc slidoc-nopaced slidoc-nosidebar">' % chapter_id)+header_toc+'</div>\n'
            post_header_html += click_span('&#8722;Contents', "Slidoc.hide(this, '%s');" % (chapter_id+'-chapter-toc'),
                                            id=chapter_id+'-chapter-toc-hide', classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-chapter-toc-hide', 'slidoc-nopaced', 'slidoc-noslide', 'slidoc-noprint', 'slidoc-nosidebar'])

    if 'slidoc-notes' in content_html:
        notes_classes = ['slidoc-clickable', 'slidoc-hide-label', 'slidoc-nopaced', 'slidoc-noprint']
        if 'contents' in config.strip:
            notes_classes += ['slidoc-hidden']
            post_header_html = ''
        else:
            post_header_html = '&nbsp;&nbsp;'

        post_header_html += click_span('&#8722;All Notes',
                                        "Slidoc.hide(this,'slidoc-plain-notes');",id=renderer.first_id+'-hidenotes',
                                         classes=notes_classes)

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

    file_toc = renderer.table_of_contents('' if not config.separate else config.server_url+filename+'.html', filenumber=filenumber)

    return (renderer.file_header or filename, file_toc, renderer, md_params, content_html, renderer.zipped_content)

# 'name' and 'id' are required field; entries are sorted by name but uniquely identified by id
Manage_fields  = ['name', 'id', 'email', 'altid', 'source', 'Timestamp', 'initTimestamp', 'submitTimestamp']
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
                         row_count=None, modify_session=None):
    modify_questions = False
    user = ADMINUSER_ID
    user_token = sliauth.gen_auth_token(hmac_key, user, ADMIN_ROLE, prefixed=True)
    admin_paced = 1 if pace_level >= ADMIN_PACE else None

    post_params = {'sheet': INDEX_SHEET, 'id': session_name, ADMINUSER_ID: user, 'token': user_token,
                  'get': '1', 'headers': json.dumps(Index_fields), 'getheaders': '1'}
    retval = Global.http_post(sheet_url, post_params)
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
            message('    ****WARNING: Module %s has changed from revision %s to %s' % (session_name, prev_row[revision_col], revision))

        prev_questions = json.loads(prev_row[prev_headers.index('questions')])
        prev_attributes = json.loads(prev_row[prev_headers.index('attributes')])
        prev_qparams = prev_attributes.get('questionParams', [])
        cur_qparams = sheet_attributes.get('questionParams', [])
        if row_count and prev_qparams != cur_qparams:
            min_count =  min(len(prev_qparams), len(cur_qparams))
            errq = ''
            for j in range(min_count):
                if prev_qparams[j] != cur_qparams[j]:
                    errq = cur_qparams[j].split(';')[0]
                    break
            abort('ERROR:DEFINE-ERROR: Cannot change Define: values affecting question %s in session %s with %s responders. Reset session?' % (errq, session_name, row_count))

        min_count =  min(len(prev_questions), len(questions))
        mod_question = 0
        for j in range(min_count):
            if prev_questions[j]['qtype'] != questions[j]['qtype']:
                message('    ****WARNING: Module %s: modifying question %d from type %s to %s' % (session_name, j+1, prev_questions[j]['qtype'], questions[j]['qtype']))
                mod_question = j+1
                break
            if row_count:
                for optname in ('alternatives', 'choices', 'explain', 'followup', 'noshuffle'):
                    if prev_questions[j].get(optname) != questions[j].get(optname):
                        abort('ERROR:QUESTION_ERROR: Cannot change %s value for question %d in session %s with %s responders: %s=%s vs. %s. Reset session?' % (optname, j+1, session_name, row_count, optname, prev_questions[j].get(optname), questions[j].get(optname)))

        if mod_question or len(prev_questions) != len(questions):
            if modify_session or not row_count:
                modify_questions = True
                if len(prev_questions) > len(questions):
                    # Truncating
                    if max_last_slide is not None:
                        for j in range(len(questions), len(prev_questions)):
                            if prev_questions[j]['slide'] <= max_last_slide:
                                abort('ERROR:TRUNCATE_SESSION: Cannot truncate previously viewed question %d for module session %s (max_last_slide=%d,question_%d_slide=%d); change lastSlide in session sheet' % (j+1, session_name, max_last_slide, j+1, prev_questions[j]['slide']))
                elif len(prev_questions) < len(questions):
                    # Extending
                    pass
            elif row_count == 1:
                abort('ERROR:MODIFY_SESSION: Delete responder entry, or check modify box, to modify questions in module session '+session_name)
            elif mod_question:
                abort('ERROR:MODIFY_SESSION: Mismatch in question %d type for module %s: previously \n%s \nbut now \n%s. Specify --modify_sessions=%s' % (mod_question, session_name, prev_questions[mod_question-1]['qtype'], questions[mod_question-1]['qtype'], session_name))
            else:
                abort('ERROR:MODIFY_SESSION: Mismatch in question numbers for module %s: previously %d but now %d. Specify --modify_sessions=%s' % (session_name, len(prev_questions), len(questions), session_name))

        if prev_row[admin_paced_col]:
            # Do not overwrite previous value of adminPaced
            admin_paced = prev_row[admin_paced_col]
            # Do not overwrite due date, unless it is actually specified
            if not due_date_str:
                due_date_str = prev_row[due_date_col]

    row_values = [session_name, session_name, revision, None, session_weight, session_rescale, release_date_str, due_date_str, None, media_url, pace_level, admin_paced,
                score_weights, grade_weights, other_weights, len(questions), len(Manage_fields)+len(Session_fields),
                sliauth.ordered_stringify(sheet_attributes), sliauth.ordered_stringify(questions), sliauth.ordered_stringify(question_concepts),
                '; '.join(sort_caseless(list(p_concepts))),
                '; '.join(sort_caseless(list(s_concepts)))
                 ]

    if len(Index_fields) != len(row_values):
        abort('Error:HEADERS:Error in updating index entry for module session %s: number of headers != row length' % (session_name,))

    post_params = {'sheet': INDEX_SHEET, ADMINUSER_ID: user, 'token': user_token,
                   'headers': json.dumps(Index_fields), 'row': json.dumps(row_values, default=sliauth.json_default)
                  }
    retval = Global.http_post(sheet_url, post_params)
    if retval['result'] != 'success':
        abort("Error::Failed to update index entry for module session '%s': %s" % (session_name, retval['error']))
    message('slidoc: Updated remote index sheet %s for module session %s' % (INDEX_SHEET, session_name))

    # Return possibly modified due date
    return (due_date_str, modify_questions)


def check_gdoc_sheet(sheet_url, hmac_key, sheet_name, pace_level, headers, modify_session=None):
    modify_col = 0
    user = TESTUSER_ID
    user_token = sliauth.gen_auth_token(hmac_key, user) if hmac_key else ''
    post_params = {'id': user, 'token': user_token, 'sheet': sheet_name,
                   'get': 1, 'getheaders': '1'}
    retval = Global.http_post(sheet_url, post_params)
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

    if modify_session == 'overwrite':
        # Extend/truncate grade columns
        modify_col = len(Manage_fields)+len(Session_fields)+1
        if pace_level:
            modify_col += len(Score_fields)

    elif modify_session == 'truncate':
        # Truncate columns
        if len(headers) < len(prev_headers):
            modify_col = len(headers) + 1

    else:
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
                abort('ERROR:: Mismatched header %d for module session %s. Delete responder row to modify' % (modify_col, sheet_name))
            ###elif not modify_session and row_count:
            elif not modify_session:
                abort('ERROR:MODIFY_SESSION: Mismatched header %d for module session %s. Specify --modify_sessions=%s to truncate/extend.\n Previously \n%s\n but now\n %s' % (modify_col, sheet_name, sheet_name, prev_headers, headers))

    return (maxLastSlide, modify_col, row_count)
                
def update_gdoc_sheet(sheet_url, hmac_key, sheet_name, headers, row=None, modify=None):
    user = ADMINUSER_ID
    user_token = sliauth.gen_auth_token(hmac_key, user, ADMIN_ROLE, prefixed=True) if hmac_key else ''
    post_params = {ADMINUSER_ID: user, 'token': user_token, 'sheet': sheet_name,
                   'headers': json.dumps(headers)}
    if row:
        post_params['row'] = json.dumps(row)
    if modify:
        post_params['modify'] = modify
    retval = Global.http_post(sheet_url, post_params)

    if retval['result'] != 'success':
        abort("Error in creating sheet '%s': %s\n headers=%s\n%s" % (sheet_name, retval['error'], headers, retval.get('messages')))
    if sheet_name != LOG_SHEET:
        message('slidoc: Created remote spreadsheet:', sheet_name)

def unescape_slidoc_script(content):
    content = re.sub(r'<slidoc-script', '<script', content)
    content = re.sub(r'</slidoc-script>', '</script>', content)
    return content

def parse_plugin(text, name=None):
    nmatch = re.match(r'^\s*([a-zA-Z]\w*)\s*=\s*{', text)
    if not nmatch:
        abort("Plugin definition must start with plugin_name={'")
    plugin_name = nmatch.group(1)
    if name and name != plugin_name:
        abort("Plugin definition must start with '"+name+" = {'")
    plugin_def = {}
    match = re.match(r'^(.*)\n(\s*/\*\s*)?HEAD:([^\n]*)\n(.*)$', text, flags=re.DOTALL)
    if match:
        text = match.group(1)+'\n'
        comment = match.group(2)
        plugin_def['ArgPattern'] = match.group(3).strip()
        tail = match.group(4).strip()
        if comment and tail.endswith('*/'):    # Strip comment delimiter
            tail = tail[:-2].strip()
        # Unescape embedded <script> elements
        tail = unescape_slidoc_script(tail)
        tail = re.sub(r'%(?!\(plugin)', '%%', tail)  # Escape % signs in HEAD/BODY template
        comps = re.split(r'(^|\n)\s*(BUTTON|TOP|BODY):' if comment else r'(^|\n)(BUTTON|BODY):', tail)
        plugin_def['HEAD'] = comps[0]+'\n' if comps[0] else ''
        comps = comps[1:]
        while comps:
            if comps[1] == 'BUTTON':
                plugin_def['BUTTON'] = comps[2]
            elif comps[1] == 'TOP':
                plugin_def['TOP'] = comps[2]
            elif comps[1] == 'BODY':
                plugin_def['BODY'] = comps[2]+'\n'
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
        plugin_head = plugin_defs[plugin_name].get('HEAD', '') 
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

def preprocess(source):
    return mistune.preprocessing(md2md.asciify(source))

def extract_slides(src_path, web_path):
    # Extract text for individual slides from Markdown file
    # Return (md_defaults, md_slides, md_header, new_image_number)
    try:
        with open(src_path) as f:
            source = f.read()
    except Exception, excp:
        raise Exception('Error in reading module source text %s: %s' % (src_path, excp))

    try:
        with open(web_path) as f:
            sessionIndex = read_index(f, path=web_path)
            sessionIndexParams = sessionIndex[0][-1]
    except Exception, excp:
        raise Exception('Error in reading module published HTML %s: %s' % (web_path, excp))

    md_source = preprocess(source).strip()
    if sliauth.digest_hex(md_source) != sessionIndexParams['md_digest']:
        raise Exception('Digest mismatch src=%s vs. web=%s; may need to re-publish HTML file %s by previewing all slides and saving' % (sliauth.digest_hex(md_source), sessionIndexParams['md_digest'], web_path))
    md_slides = []

    base = len(sessionIndexParams['md_defaults'])
    offset = 0
    for count in sessionIndexParams['md_breaks']:
        md_slides.append(md_source[base+offset:base+count])
        offset = count
    return (sessionIndexParams['md_defaults'], md_slides, sessionIndexParams.get('md_header',''), sessionIndexParams['new_image_number'])

def extract_slide_range(src_path, web_path, start_slide=0, end_slide=0, renumber=0, session_name=''):
    # Extract text and images for a range of slides from Markdown file
    # Return (md_defaults, slides_text_md, slides_images_zip or None, md_header, new_image_number)
    md_defaults, md_slides, md_header, new_image_number = extract_slides(src_path, web_path)

    if not start_slide:
        start_slide = 1
    elif start_slide > len(md_slides):
        raise Exception('Invalid slide number %d' % start_slide)

    if not end_slide:
        end_slide = len(md_slides)

    fname = os.path.splitext(os.path.basename(src_path))[0]
    if not session_name:
        session_name = fname
    md_extract = ''.join(md_slides[start_slide-1:end_slide])
    extract_mods_args = md2md.Args_obj.create_args(None,
                                                  image_dir=session_name+'_images',
                                                  images=set(['_slidoc', 'zip', 'md']),
                                                  renumber=renumber)
    extract_parser = md2md.Parser(extract_mods_args)
    extract_text, extract_zipped, tem_image_number = extract_parser.parse(md_extract, src_path)
    
    return (md_defaults, extract_text, extract_zipped, md_header, tem_image_number if renumber else new_image_number)
    

def read_index(fhandle, entry_count=6, path=''):
    # Read one or more index entries from comment in the header portion of HTML file
    index_entries = []
    found_entries = False
    while 1:
        line = fhandle.readline()
        if not line:
            break
        if line.strip() == Index_prefix.strip():
            found_entries = True
            break

    tem_list = []
    while found_entries:
        line = fhandle.readline()
        if not line:
            message('INDEX-WARNING: Index entries not terminated')
            return []
        sline = line.strip()
        if not sline or sline.startswith(Index_suffix.strip()):
            if len(tem_list) >= entry_count:
                index_entries.append(tem_list[:entry_count])
            elif tem_list:
                message('INDEX-WARNING: Insufficient index entries in %s %s %s: %s' % (path, len(index_entries), entry_count, tem_list) )
            if sline.startswith(Index_suffix.strip()):
                break
            tem_list = []
        else:
            if sline[0] in '[{':
                tem_obj = None
                try:
                    tem_obj = json.loads(sline.replace('&lt;', '<').replace('&gt;', '>'))
                except Exception, excp:
                    message('INDEX-WARNING: Error in index params %s: %s' % (sline, excp))
                if isinstance(tem_obj, dict):
                    for key, value in tem_obj.items():
                        if isinstance(value, unicode):
                            tem_obj[key] = value.encode('ascii', 'replace')
                tem_list.append(tem_obj)
            else:
                tem_list.append(sline)

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
            if not opt:
                continue
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
    site_prefix = '/'
    if site_name:
        site_prefix += site_name + '/'
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

    topnav_html = '<ul class="slidoc-topnav slidoc-noprint" id="slidoc-topnav">\n'+'\n'.join(elems)+'\n'
    topnav_html += '<li id="fileslink" class="slidoc-remoteonly" style="display: none;"><a href="%s_user_browse/files" target="_blank">%s</a></li>' % (site_prefix, SYMS['folder'])
    topnav_html += '<li id="gradelink" class="slidoc-remoteonly" style="display: none;"><a href="%s_user_grades" target="_blank">%s</a></li>' % (site_prefix, SYMS['letters'])
    topnav_html += '<li id="helplink" class="" style=""><a href="%ssend">%s</a> <span class="slidoc-clickable slidoc-remoteonly" onclick="Slidoc.userProfile();">%s</span><a href="_docs/index.html" target="_blank">%s</a></li>' % (site_prefix, SYMS['phonearrow'], SYMS['bust'], '<b>?</b>')
    topnav_html += '<li id="dashlink" class="slidoc-restricted-top" style="display: none;"><a href="%s_addtype" target="_blank"><b>+</b></a> <a href="%s_dash" target="_blank">%s</a> <a id="dashlinkedit" class="slidoc-noupdate" href="">%s</a></li>' % (site_prefix, site_prefix, SYMS['gear'], SYMS['pencil'])
    topnav_html += '<li class="slidoc-nav-icon"><a href="javascript:void(0);" onclick="Slidoc.switchNav()">%s</a></li>' % SYMS['threebars']
    topnav_html += '</ul>\n'
    return topnav_html


scriptdir = os.path.dirname(os.path.realpath(__file__))

class GlobalState(object):
    def __init__(self, http_post_func=None, return_html=False, error_exit=False):
        self.http_post = http_post_func or sliauth.http_post
        self.return_html = return_html
        self.error_exit = error_exit
        self.primary_tags = defaultdict(OrderedDict)
        self.sec_tags = defaultdict(OrderedDict)
        self.primary_qtags = defaultdict(OrderedDict)
        self.sec_qtags = defaultdict(OrderedDict)

        self.all_tags = {}

        self.questions = OrderedDict()
        self.concept_questions = defaultdict(list)

        self.ref_tracker = dict()
        self.ref_counter = defaultdict(int)
        self.chapter_ref_counter = defaultdict(int)

        self.dup_ref_tracker = set()

Global = None

def abort(msg):
    if Global and not Global.error_exit:
        message(msg)
        raise Exception(msg)
    else:
        sys.exit(msg)

def message(*args):
    print(*args, file=sys.stderr)


def process_input(*args, **argv):
    try:
        return process_input_aux(*args, **argv)
    except SystemExit, excp:
        import traceback
        traceback.print_exc()
        raise Exception('System exit error in process input: %s' % excp)

def process_input_aux(input_files, input_paths, config_dict, default_args_dict={}, images_zipdict={}, nb_links={},
                      restricted_sessions_re=None, return_html=False, return_messages=False, error_exit=False, http_post_func=None):
    global Global, message
    input_paths = [md2md.stringify(x) for x in input_paths] # unicode -> str

    Global = GlobalState(http_post_func=http_post_func, return_html=return_html, error_exit=error_exit)
    if return_html:
        return_messages = True

    messages = []
    if return_messages:
        def append_message(*args):
            messages.append(''.join(str(x) for x in args))
            if config_dict.get('debug'):
                print(*args, file=sys.stderr)
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

    if config.modify_sessions not in ('overwrite', 'truncate'):
        config.modify_sessions = set(config.modify_sessions.split(',')) if config.modify_sessions else set()

    if config.make:
        # Process only modified input files
        if config.toc or config.index or config.qindex or config.all:
            abort('OPTION-ERROR: --make option incompatible with indexing or "all" options')
        
    site_prefix = '/'+config.site_name if config.site_name else ''
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

    libraries_params = {'libraries_link': (config.libraries_url or LIBRARIES_URL)+''}

    def insert_resource(filename):
        if filename.endswith('.js'):
            return ('<script src="%s/%s"></script>\n' % ('/'+RESOURCE_PATH, filename)) if config.unbundle else ('\n<script>\n%s</script>\n' % templates[filename])

        if filename.endswith('.css'):
            return ('<link rel="stylesheet" type="text/css" href="%s/%s">\n' % ('/'+RESOURCE_PATH, filename)) if config.unbundle else ('\n<style>\n%s</style>\n' % templates[filename])
        raise Exception('Invalid filename for insert_resource: '+filename)

    start_date_obj = None
    if config.start_date:
        start_date_obj = sliauth.parse_date(config.start_date)
        if not start_date_obj:
            abort('DATE-ERROR: Invalid site start date: %s' % config.start_date)

    orig_fnames = []
    orig_outpaths = []
    orig_flinks = []

    fnumbers = []
    fprefix = config.session_type or None
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

        if not input_files[j]:
            continue

        if start_date_obj:
            # Only process files with a release date after the minimum required release date
            tem_config = parse_merge_args(sliauth.read_header_opts(input_files[j])[0], fname, Conf_parser, {})
            tem_release_date_str = getattr(tem_config, 'release_date', None) or config.release_date
            if tem_release_date_str and tem_release_date_str != sliauth.FUTURE_DATE:
                tem_release_date_obj = sliauth.parse_date(tem_release_date_str)
                if not tem_release_date_obj:
                    abort('DATE-ERROR: Module %s has invalid release date %s' % (fname, tem_release_date_str))
                    continue
                if tem_release_date_obj < start_date_obj:
                    abort('RELEASE-ERROR: Module %s has release date %s before start date %s' % (fname, tem_release_date_str, start_date_obj) )
                    continue

        if not config.make or config.make == fname:
            # Not make mode or force single file make; process file
            fnumbers.append(fnumber)
        elif config.make == 'all':
            # Process only accessible and modified input files (if updated using web interface, inpath and outpath may have nearly same mod times)
            # (Always process return_html or index.md file)
            if return_html or fname == 'index' or not (os.path.exists(outpath) and os.path.getmtime(outpath) >= os.path.getmtime(inpath)):
                fnumbers.append(fnumber)



    fprefix = fprefix or ''
    
    if not fnumbers:
        if not return_messages and input_files:
            message('All output files are newer than corresponding input files')
        if not config.create_toc:
            return {'messages':messages}
    elif return_html and len(fnumbers) != 1 and config.separate:
        raise Exception('Cannot return html for multiple input files')

    if config.pace and config.all is not None :
        abort('slidoc: Error: --pace option incompatible with --all')

    js_params = {'siteName': '', 'fileName': '', 'chapterId': '',
                 'sessionType': '', 'sessionVersion': '1.0', 'sessionRevision': '', 'sessionPrereqs': '',
                 'overwrite': '', 'pacedSlides': 0, 'questionsMax': 0, 'scoreWeight': 0, 'otherWeight': 0, 'gradeWeight': 0,
                 'doc_title': '', 'topnavList': [], 'tocFile': '',
                 'slideDelay': 0, 'lateCredit': None, 'participationCredit': None, 'maxRetakes': 0, 'timedSec': 0,
                 'plugins': [], 'plugin_share_voteDate': '',
                 'releaseDate': '', 'dueDate': '', 'discussSlides': [], 'hiddenSlides': [], 'resubmitAnswers': None,
                 'gd_client_id': None, 'gd_api_key': None, 'gd_sheet_url': '',
                 'roster_sheet': ROSTER_SHEET, 'grades_sheet': GRADES_SHEET,
                 'index_sheet': INDEX_SHEET, 'indexFields': Index_fields,
                 'log_sheet': LOG_SHEET, 'logFields': Log_fields,
                 'sessionFields':Manage_fields+Session_fields, 'gradeFields': [], 
                 'adminUserId': ADMINUSER_ID, 'testUserId': TESTUSER_ID,
                 'adminRole': ADMIN_ROLE, 'graderRole': GRADER_ROLE,
                 'authType': '', 'features': {} }

    js_params['version'] = sliauth.get_version()
    js_params['userCookiePrefix'] = sliauth.USER_COOKIE_PREFIX
    js_params['siteCookiePrefix'] = sliauth.SITE_COOKIE_PREFIX
    js_params['siteName'] = config.site_name
    js_params['sessionType'] = config.session_type
    js_params['overwrite'] = 1 if config.overwrite else 0
    js_params['paceLevel'] = config.pace or 0  # May be overridden by file-specific values

    js_params['conceptIndexFile'] = '' if config.create_toc else 'index.html' # Need command line option to modify this
    js_params['printable'] = config.printable
    js_params['debug'] = config.debug
    js_params['remoteLogLevel'] = config.remote_logging or 0

    js_params_fmt = '\n<script>\nvar JS_PARAMS_OBJ=%s;\n</script>\n'
    toc_js_params = js_params_fmt % sliauth.ordered_stringify(js_params)

    combined_name = config.all or (orig_fnames[0] if orig_fnames else 'combined')
    combined_file = '' if config.separate else combined_name+'.html'

    # Reset config properties that will be overridden for separate files
    if config.features is not None and not isinstance(config.features, set):
        config.features = md2md.make_arg_set(config.features, Features_all)
    if 'features' in default_args_dict:
        default_args_dict['features'] = md2md.make_arg_set(default_args_dict['features'], Features_all)

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

    nb_server_url = config.server_url
    if combined_file:
        config.server_url = ''
    if config.server_url and not config.server_url.endswith('/'):
        config.server_url += '/'
    if config.image_url and not config.image_url.endswith('/'):
        config.image_url += '/'

    config.strip = md2md.make_arg_set(config.strip, Strip_all)
    if 'strip' in default_args_dict:
        default_args_dict['strip'] = md2md.make_arg_set(default_args_dict['strip'], Strip_all)

    templates = {}
    for tname in ('doc_include.css', 'wcloud.css', 'doc_custom.css',
                  'doc_include.js', 'wcloud.js', 'doc_google.js', 'md5.js', 'sha256.js', 'doc_test.js',
                  'doc_include.html', 'doc_template.html', 'reveal_template.html'):
        templates[tname] = md2md.read_file(scriptdir+'/templates/'+tname)

    if config.css.startswith('http:') or config.css.startswith('https:'):
        css_html = '<link rel="stylesheet" type="text/css" href="%s">\n' % config.css
    elif config.css:
        css_html = '<style>\n' + md2md.read_file(config.css) + '</style>\n'
    else:
        css_html = insert_resource('doc_custom.css')

    # External CSS replaces doc_custom.css, but not doc_include.css
    css_html += insert_resource('doc_include.css')
    if HtmlFormatter:
        css_html += '\n<style>\n' + HtmlFormatter().get_style_defs('.highlight') + '\n</style>\n'
    css_html += insert_resource('wcloud.css')
    test_params = []
    add_scripts = ''

    if config.test_script:
        add_scripts += insert_resource('doc_test.js')
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
                    userRole = ''
                    if user_id == GRADER_ROLE:
                        userRole = GRADER_ROLE
                        query += '&grading=1'

                    proxy_query = '?username=%s&token=%s' % (user_id, gd_hmac_key if user_id == ADMIN_ROLE else sliauth.gen_auth_token(gd_hmac_key, user_id, role=userRole))
                else:
                    label = script
                test_params.append([label, query, proxy_query])

    if gd_hmac_key is not None:
        add_scripts += (Google_docs_js % js_params) + insert_resource('doc_google.js')
        if config.google_login:
            add_scripts += '<script src="https://apis.google.com/js/client.js?onload=onGoogleAPILoad"></script>\n'
        if gd_hmac_key:
            add_scripts += insert_resource('md5.js')
            add_scripts += insert_resource('sha256.js')
    answer_elements = {}
    for suffix in SlidocRenderer.content_suffixes:
        answer_elements[suffix] = 0;
    for suffix in SlidocRenderer.input_suffixes:
        answer_elements[suffix] = 1;
    js_params['answer_elements'] = answer_elements

    toc_file = ''
    if config.create_toc or config.toc:
        toc_file = 'index.html' if config.create_toc else config.toc
        js_params['tocFile'] = toc_file

    topnav_list = []
    if config.topnav:
        topnav_list = get_topnav(config.topnav, fnames=orig_fnames, site_name=config.site_name, separate=config.separate)
    js_params['topnavList'] = topnav_list

    head_html = font_css(config.fontsize) + css_html + insert_resource('doc_include.js') + insert_resource('wcloud.js')
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
    comb_plugin_embeds = set()

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

    slide_mods_dict = dict(dest_dir=config.dest_dir,
                           image_dir=config.image_dir,
                           image_url=config.image_url,
                           images=set(['_slidoc']),
                           strip='tags,extensions')
    if config.preview_mode:
        slide_mods_dict['images'].add('preview')
    if 'answers' in config.strip:
        slide_mods_dict['strip'] += ',answers'
    if 'notes' in config.strip:
        slide_mods_dict['strip'] += ',notes'
    slide_mods_args = md2md.Args_obj.create_args(None, **slide_mods_dict)

    nb_mods_dict = {'strip': 'tags,extensions', 'server_url': config.server_url}
    if 'rule' in config.strip:
        nb_mods_dict['strip'] += ',rule'
    nb_converter_args = md2nb.Args_obj.create_args(None, **nb_mods_dict)
    index_id = 'slidoc-index'
    qindex_id = 'slidoc-qindex'
    index_chapter_id = make_chapter_id(nfiles+1)
    qindex_chapter_id = make_chapter_id(nfiles+2)
    back_to_contents = nav_link('BACK TO CONTENTS', config.server_url, config.toc, hash='#'+make_chapter_id(0),
                                separate=config.separate, classes=['slidoc-nosidebar'], printable=config.printable)+'<p></p>\n'

    all_concept_warnings = []
    outfile_buffer = []
    combined_html = []
    if combined_file:
        combined_html.append( '<div id="slidoc-sidebar-right-container" class="slidoc-sidebar-right-container">\n' )
        combined_html.append( '<div id="slidoc-sidebar-right-wrapper" class="slidoc-sidebar-right-wrapper">\n' )

    math_load = False
    pagedown_load = False
    skulpt_load = False
    flist = []
    file_props = {}
    paced_files = set()
    admin_due_date = {}
    out_index = {}
    for j, fnumber in enumerate(fnumbers):
        fhandle = input_files[fnumber-1]
        fname = orig_fnames[fnumber-1]
        outpath = orig_outpaths[fnumber-1]
        outname = fname+".html"
        release_date_str = ''
        due_date_str = ''
        vote_date_str = ''
        file_plugin_defs = base_plugin_defs.copy()
        if not config.separate:
            file_config = config
        else:
            # Separate files (may also be paced)

            # Merge file config with command line
            file_config = parse_merge_args(sliauth.read_header_opts(fhandle)[0], fname, Conf_parser, vars(config), default_args_dict=default_args_dict, verbose=config.verbose)
            if config.preview_port:
                if file_config.gsheet_url:
                    file_config.gsheet_url = ''

            if file_config.plugins:
                # Plugins with same name will override earlier plugins
                plugin_paths = file_config.plugins.split(',')
                for plugin_path in plugin_paths:
                    plugin_name, file_plugin_defs[plugin_name] = parse_plugin( md2md.read_file(plugin_path.strip()) )

            file_config.features = file_config.features or set()
            if 'grade_response' in file_config.features and gd_hmac_key is None:
                # No grading without google sheet
                file_config.features.remove('grade_response')
            if nfiles == 1:
                file_config.strip.add('chapters')

            ##if 'slides_only' in file_config.features and config.printable:
            ##    file_config.features.remove('slides_only')
            ##    message('slides_only feature suppressed by --printable option')

            if 'keep_extras' in file_config.features and config.gsheet_url:
                abort('PACE-ERROR: --features=keep_extras incompatible with --gsheet_url')

            if file_config.retakes and file_config.timed:
                abort('PACE-ERROR: --retakes=... incompatible with --timed=...')

            if file_config.show_score and file_config.show_score not in ('never', 'after_answering', 'after_submitting', 'after_grading'):
                abort('SHOW-ERROR: Must have --show_score=never OR after_answering OR after_submitting OR after_grading (found %s)' % file_config.show_score)

            if not file_config.show_score:
                if file_config.pace >= QUESTION_PACE:
                    file_config.show_score = 'after_answering'
                elif file_config.pace:
                    if gd_hmac_key is None:
                        file_config.show_score = 'after_answering'
                    elif 'assessment' in file_config.features:
                        file_config.show_score = 'after_grading'
                    else:
                        file_config.show_score = 'after_submitting'
            elif file_config.show_score == 'never':
                file_config.show_score = ''

            file_config_vars = vars(file_config)
            settings_list = []
            exclude = set(['anonymous', 'auth_key', 'backup_dir', 'config', 'copy_source', 'create_toc', 'dest_dir', 'dry_run', 'google_login', 'gsheet_url', 'make', 'modify_sessions', 'notebook', 'overwrite', 'preview_port', 'proxy_url', 'server_url', 'split_name', 'test_script', 'toc_header', 'topnav', 'verbose', 'file', 'separate', 'toc', 'index', 'qindex'])
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
            if not return_html:
                message(fname+' settings: '+' '.join(settings_list))
                    
            js_params['features'] = dict([(x, 1) for x in file_config.features])
            js_params['paceLevel'] = file_config.pace or 0

            release_date_obj = None
            due_date_obj = None
            vote_date_obj = None
            if file_config.release_date:
                if file_config.release_date == sliauth.FUTURE_DATE:
                    release_date_str = file_config.release_date
                else:
                    release_date_str = sliauth.get_utc_date(file_config.release_date)
                    release_date_obj = sliauth.parse_date(release_date_str)
                    if not release_date_obj:
                        abort('DATE-ERROR: Invalid release date %s for module %s' % (release_date_str, fname))

            if not file_config.publish and restricted_sessions_re and restricted_sessions_re.search(fname):
                if not release_date_str:
                    abort('RESTRICTED-ERROR: Must specify an actual release date to create restricted session %s' % fname)
                if return_html and release_date_obj:
                    if not start_date_obj:
                        abort('RESTRICTED-ERROR: Must specify site start date to create restricted session %s' % fname)
                    if  sliauth.epoch_ms(release_date_obj) < sliauth.epoch_ms(start_date_obj):
                        abort('RESTRICTED-ERROR: Invalid release date %s before start date %s for restricted session %s' % (release_date_str, config.start_date, fname))

            if file_config.due_date:
                due_date_str = sliauth.get_utc_date(file_config.due_date, pre_midnight=True)
                due_date_obj = sliauth.parse_date(due_date_str)
                if not due_date_obj:
                    abort('DATE-ERROR: Invalid due date %s for module %s' % (due_date_str, fname))

            if file_config.vote_date:
                vote_date_str = sliauth.get_utc_date(file_config.vote_date)
                vote_date_obj = sliauth.parse_date(vote_date_str)
                if not vote_date_obj:
                    abort('DATE-ERROR: Invalid vote date %s for module %s' % (vote_date_str, fname))

            js_params['showScore'] = file_config.show_score or ''
            js_params['sessionPrereqs'] =  file_config.prereqs or ''
            js_params['sessionRevision'] = file_config.revision or ''
            js_params['slideDelay'] = file_config.slide_delay or 0

            js_params['lateCredit'] = file_config.late_credit or 0
            js_params['participationCredit'] = file_config.participation_credit or 0
            js_params['maxRetakes'] = file_config.retakes or 0
            js_params['timedSec'] = file_config.timed or 0
                
            topnav_opts = file_config.topnav or ''
            gd_sheet_url = file_config.gsheet_url or ''
            js_params['gd_sheet_url'] = config.proxy_url if config.proxy_url and gd_sheet_url else gd_sheet_url
            js_params['plugin_share_voteDate'] = vote_date_str
            js_params['releaseDate'] = release_date_str
            js_params['dueDate'] = due_date_str
            js_params['doc_title'] = file_config.doc_title or ''
            js_params['fileName'] = fname

            if js_params['paceLevel'] >= ADMIN_PACE and not gd_sheet_url:
                abort('PACE-ERROR: Must specify -gsheet_url for --pace='+str(js_params['paceLevel']))

            if js_params['paceLevel'] >= ADMIN_PACE and 'shuffle_choice' in file_config.features:
                abort('PACE-ERROR: shuffle_choice feature not compatible with --pace='+str(js_params['paceLevel']))

            if js_params['paceLevel'] >= QUESTION_PACE and file_config.show_score != 'after_answering':
                abort('PACE-ERROR: --show_score=%s feature not compatible with --pace=%s' % (file_config.show_score, js_params['paceLevel']) )

        if not j or config.separate:
            # First file or separate files
            katex_config = ''
            mathjax_config = 'skipStartupTypeset: %s,\n' % ('false' if 'immediate_math' in file_config.features else 'true')
            if 'equation_number' in file_config.features:
                mathjax_config += 'TeX: { equationNumbers: { \n'
                if 'chapters' not in file_config.strip:
                    mathjax_config += 'formatNumber: function (n) {return "%s."+n},\n' % fnumber
                mathjax_config += 'autoNumber: "AMS" } },\n'
            if 'equation_left' in file_config.features:
                mathjax_config += 'displayAlign: "left",\n'
            if 'tex_math' in file_config.features:
                katex_config = ',{left: "$", right: "$", display: false},' # MUST APPEAR AFTER $$ in delimiters array
                mathjax_config += 'tex2jax: { inlineMath: [ ["$","$"], ["\\\\(","\\\\)"] ], processEscapes: true },\n'
            mathjax_config  += 'jax: ["input/TeX","output/%s"]' % ('SVG' if file_config.printable else 'CommonHTML')
            if 'equation_number' in file_config.features:
                math_inc = Mathjax_js % mathjax_config
            else:
                math_inc = KaTeX_js % katex_config

        if not file_config.features.issubset(set(Features_all)):
            abort('FEATURE-ERROR: Unknown feature(s): '+','.join(list(file_config.features.difference(set(Features_all)))) )
            
        filepath = input_paths[fnumber-1]
        filedir = os.path.dirname(os.path.realpath(filepath))
        md_text = fhandle.read()
        fhandle.close()

        # Preprocess line breaks, tabs etc.
        md_text = preprocess(md_text)
        loc = md2md.find_non_ascii(md_text)
        if loc:
            message('ASCII-WARNING: Possible non-ascii character at position %d could create problems: %s' % (loc, repr(md_text[max(0,loc-10):loc+15])) )

        # Strip annotations (may also break slide editing)
        md_text = re.sub(r"(^|\n) {0,3}[Aa]nnotation:(.*?)(\n|$)", '', md_text)

        files_url = '/_files'
        if config.site_name:
            files_url = '/' + config.site_name + files_url
        slide_parser = md2md.Parser(slide_mods_args, images_zipdata=images_zipdict.get(fname), files_url=files_url)
        md_text_modified, _, new_renumber = slide_parser.parse(md_text, filepath)

        if file_config.hide and 'hidden' in file_config.strip:
            md_text_modified = re.sub(r'(^|\n *\n--- *\n( *\n)+) {0,3}#{2,3}[^#][^\n]*'+file_config.hide+r'.*?(\n *\n--- *\n|$)', r'\1', md_text_modified, flags=re.DOTALL)

        prev_file = '' if fnumber == 1      else orig_flinks[fnumber-2]
        next_file = '' if fnumber == nfiles else orig_flinks[fnumber]

        # zipped_md containing will only be created if any images are present (and will also include the original (preprocessed) md_text as content.md)
        fheader, file_toc, renderer, md_params, md_html, zipped_md = md2html(md_text, filename=fname, config=file_config, filenumber=fnumber,
                                                        filedir=filedir, plugin_defs=file_plugin_defs, prev_file=prev_file, next_file=next_file,
                                                        index_id=index_id, qindex_id=qindex_id, zip_content=config.preview_port,
                                                        images_zipdata=images_zipdict.get(fname))
        math_present = renderer.render_mathjax or MathInlineGrammar.any_block_math.search(md_text) or MathInlineGrammar.any_inline_math.search(md_text)

        if len(fnumbers) == 1 and config.separate and config.extract:
            md_extract = md_defaults + ''.join(md_params['md_slides'][config.extract-1:])
            extract_mods_args = md2md.Args_obj.create_args(None,
                                                          image_dir=fname+'_extract_images',
                                                          images=set(['_slidoc', 'zip', 'md']),
                                                          renumber=1)
            extract_parser = md2md.Parser(extract_mods_args, images_zipdata=images_zipdict.get(fname))
            extract_text, extract_zipped, new_renumber = extract_parser.parse(md_extract, filepath)
            if not return_html:
                if extract_zipped:
                    extract_file = dest_dir+fname+"_extract.zip"
                    md2md.write_file(extract_file, extract_zipped)
                else:
                    extract_file = dest_dir+fname+"_extract.md"
                    md2md.write_file(extract_file, extract_text)
                message('Created extract file:', extract_file)

        if js_params['paceLevel']:
            # File-specific js_params
            js_params['pacedSlides'] = renderer.slide_number
            js_params['questionsMax'] = len(renderer.questions)
            js_params['scoreWeight'] = renderer.cum_weights[-1] if renderer.cum_weights else 0
            js_params['otherWeight'] = sum(q.get('vweight',0) for q in renderer.questions) if renderer.questions else 0
            js_params['gradeWeight'] = renderer.cum_gweights[-1] if renderer.cum_gweights else 0
            js_params['gradeFields'] = Score_fields[:] + (renderer.grade_fields[:] if renderer.grade_fields else [])
            js_params['totalWeight'] = js_params['scoreWeight'] + js_params['gradeWeight'] + js_params['otherWeight']
        else:
            js_params['pacedSlides'] = 0
            js_params['questionsMax'] = 0
            js_params['scoreWeight'] = 0
            js_params['otherWeight'] = 0
            js_params['gradeWeight'] = 0
            js_params['gradeFields'] = []
            js_params['totalWeight'] = 0

        js_params['disabledCount'] = renderer.sheet_attributes['disabledCount']
        js_params['discussSlides'] = renderer.sheet_attributes['discussSlides']
        js_params['hiddenSlides'] = renderer.sheet_attributes['hiddenSlides']
        js_params['resubmitAnswers'] = renderer.sheet_attributes['resubmitAnswers']
        js_params['paramDefinitions'] = renderer.all_params
        js_params['paramFunctions'] = renderer.all_functions

        if config.separate:
            plugin_list = list(renderer.plugin_names)
            plugin_list.sort()
            js_params['chapterId'] = renderer.get_chapter_id()
            js_params['plugins'] = plugin_list
            
        max_params = {}
        max_params['id'] = '_max_score'
        max_params['source'] = 'slidoc'
        max_params['initTimestamp'] = None
        max_score_fields = [max_params.get(x,'') for x in Manage_fields+Session_fields]
        if js_params['paceLevel']:
            max_score_fields += ['', js_params['scoreWeight'], js_params['otherWeight'], '']
            max_score_fields += renderer.max_fields if renderer.max_fields else []

        all_concept_warnings += renderer.concept_warnings
        flist.append( (fname, outname, release_date_str, fheader, file_toc) )
        
        comb_plugin_defs.update(renderer.plugin_defs)
        comb_plugin_loads.update(renderer.plugin_loads)
        comb_plugin_embeds.update(renderer.plugin_embeds)
        if math_present:
            math_load = True
        if renderer.render_markdown:
            pagedown_load = True
        if renderer.load_python:
            skulpt_load = True

        js_params['topnavList'] = []
        topnav_html = ''
        sessions_due_html = ''
        announce_due_html = ''
        if topnav_opts and config.separate:
            top_fname = 'home' if fname == 'index' else fname
            js_params['topnavList'] = get_topnav(topnav_opts, fnames=orig_fnames, site_name=config.site_name, separate=config.separate)
            topnav_html = '' if config.create_toc or config.toc else render_topnav(js_params['topnavList'], top_fname, site_name=config.site_name)
            index_display = []
            for opt in topnav_opts.split(','):
                if opt != '/index.html' and (opt.endswith('/index.html') or not opt.endswith('.html')):
                    tempath = os.path.join(dest_dir, opt)
                    if opt.endswith('.html'):
                        temdir = os.path.dirname(opt)
                    else:
                        temdir = opt
                        tempath = os.path.join(tempath, 'index.html')
                    if os.path.exists(tempath):
                        with open(tempath) as f:
                            index_entries = read_index(f, path=tempath)
                    else:
                         index_entries = []
                    for ind_fname, ind_fheader, doc_str, iso_due_str, iso_release_str, index_params in index_entries:
                        if iso_release_str != sliauth.FUTURE_DATE and (ind_fname.startswith('announce') or (iso_due_str and iso_due_str != '-')):
                            index_display.append([temdir+'/'+ind_fname, ind_fname, ind_fheader, doc_str, iso_due_str, iso_release_str])

            if index_display:
                due_index = []
                announce_index = []
                for ind_fpath, ind_fname, ind_fheader, doc_str, iso_due_str, iso_release_str in index_display:
                    release_epoch = 0
                    due_epoch = 0
                    if iso_release_str and iso_release_str != '-':
                        release_epoch = int(sliauth.epoch_ms(sliauth.parse_date(iso_release_str))/1000.0)
                    if iso_due_str and iso_due_str != '-':
                        due_epoch = int(sliauth.epoch_ms(sliauth.parse_date(iso_due_str))/1000.0)
                    
                    if ind_fname.startswith('announce'):
                        entry = '<tr class="slidoc-index-entry" data-release="%d" data-due="%d"><td><a class="slidoc-clickable" href="%s.html"  target="_blank">%s</a>: %s %s</td></tr>\n' % (release_epoch, due_epoch, ind_fpath, ind_fname, ind_fheader, '('+iso_release_str[:10]+')' if release_epoch else '')
                        announce_index.append([due_epoch, ind_fname, entry])
                    else:
                        doc_link = '''(<a class="slidoc-clickable" href="%s.html"  target="_blank">%s</a>)''' % (ind_fpath, doc_str)
                        entry = '<tr class="slidoc-index-entry" data-release="%d" data-due="%d"><td>%s:</td><td> <span id="slidoc-toc-chapters-toggle" class="slidoc-toc-chapters">%s</span>%s</td><td><span class="slidoc-nosidebar"> %s</span></td></tr>\n' % (release_epoch, due_epoch, iso_due_str[:10], ind_fname, SPACER6, doc_link)
                        due_index.append([due_epoch, ind_fname, entry])

                due_index.sort(reverse=True)
                announce_index.sort(reverse=True)
                ul_fmt = '<table class="slidoc-toc-table %s">\n%s\n</table>\n'
                sessions_due_html = ul_fmt %  ('slidoc-due-sessions', '\n'.join(x[-1] for x in due_index))
                announce_due_html = ul_fmt %  ('slidoc-due-announce', '\n'.join(x[-1] for x in announce_index)) if announce_index else ''

        md_html = md_html.replace('<p>SessionsDue:</p>', sessions_due_html)
        md_html = md_html.replace('<p>Announcements:</p>', announce_due_html)

        printable_css = ''
        if file_config.doc_title is not None and not file_config.doc_title:
            # Blank doc_title; suppress browser header/footer by removing margins (but no way to create padding at top/bottom?)
            printable_css = '''<style>@media print { @page { margin-top: 0; margin-bottom: 0; } }</style>''' 
        mid_params = {'session_name': fname,
                      'doc_banner': renderer.banner,
                      'printable_css': printable_css,
                      'math_js': math_inc if math_present else '',
                      'pagedown_js': (Pagedown_js % libraries_params) if renderer.render_markdown else '',
                      'skulpt_js': (Skulpt_js % libraries_params) if renderer.load_python else '',
                      'body_class': 'slidoc-plain-page' if topnav_html else '',
                      'top_nav':  topnav_html,
                      'top_nav_hide': ' slidoc-topnav-hide' if topnav_html else ''}
        mid_params.update(SYMS)
        mid_params['plugin_tops'] = ''.join(renderer.plugin_tops)

        if gd_sheet_url and (not config.dry_run or return_html):
            tem_attributes = renderer.sheet_attributes.copy()
            tem_attributes.update(params=js_params)
            tem_fields = Manage_fields+Session_fields+js_params['gradeFields']
            modify_session = (fname in config.modify_sessions) if isinstance(config.modify_sessions, set) else config.modify_sessions
            max_last_slide, modify_col, row_count = check_gdoc_sheet(gd_sheet_url, gd_hmac_key, js_params['fileName'], js_params['paceLevel'], tem_fields,
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

        doc_desc = []
        if js_params['paceLevel']:
            paced_files.add(fname)
            if gd_sheet_url:
                if js_params['gradeWeight']:
                    file_type = 'graded'
                else:
                    file_type = 'scored'
            else:
                file_type = 'paced'

            doc_desc.append(file_type + ' exercise')
        else:
            file_type = ''

        iso_release_str = '-'
        if release_date_str == sliauth.FUTURE_DATE or (not release_date_str and config.start_date and restricted_sessions_re and restricted_sessions_re.search(fname)):
            # Future release date or restricted session with start date but no release date
            doc_desc.append('UNRELEASED')
            iso_release_str = release_date_str
        elif release_date_str:
            release_date = sliauth.parse_date(release_date_str)
            iso_release_str = sliauth.iso_date(release_date)
            if sliauth.epoch_ms(release_date) > sliauth.epoch_ms():
                # Module not yet released
                doc_desc.append('available ' + sliauth.print_date(release_date, weekday=True, prefix_time=True))

        iso_due_str = '-'
        if js_params['paceLevel']:
            # Additional info for paced files
            admin_ended = bool(admin_due_date.get(fname))
            doc_date_str = admin_due_date[fname] if admin_ended else due_date_str
            if doc_date_str:
                date_time = doc_date_str if isinstance(doc_date_str, datetime.datetime) else sliauth.parse_date(doc_date_str)
                if admin_ended:
                    doc_desc.append('ended '+sliauth.print_date(date_time))
                else:
                    doc_desc.append('due '+sliauth.print_date(date_time, prefix_time=True))
                    iso_due_str = sliauth.iso_date(date_time)

        file_props[fname] = {'type': file_type, 'release_date': iso_release_str, 'due_date': iso_due_str, 'doc_str': ', '.join(doc_desc) or 'view'}

        if config.dry_run and not return_html:
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
                tem_plugin_defs = file_plugin_defs.copy()
                tem_plugin_defs.update(renderer.plugin_defs)
                file_head_html = (js_params_fmt % sliauth.ordered_stringify(js_params)) + font_css(file_config.fontsize) + css_html + insert_resource('doc_include.js') + insert_resource('wcloud.js') + add_scripts

                pre_html = file_head_html + plugin_heads(tem_plugin_defs, renderer.plugin_loads) + (mid_template % mid_params) + body_prefix
                # Prefix index entry as comment
                index_entries = [fname, fheader, file_props[fname]['doc_str'], file_props[fname]['due_date'] or '-', file_props[fname]['release_date'] or '-']
                # Store MD5 digest of preprocessed source and list of character counts at each slide break
                index_dict = {'md_digest': md_params['md_digest'], 'md_defaults': md_params['md_defaults'], 'md_breaks': md_params['md_breaks'],
                              'md_images': md_params['md_images'], 'md_header': md_params['md_header'], 'new_image_number': md_params['new_image_number']}
                index_entries += [ json.dumps(index_dict).replace('<', '&lt;').replace('>', '&gt;')]
                index_head = '\n'.join([Index_prefix] + index_entries + [Index_suffix])+'\n'
                out_index[outpath] = index_head
                pre_html = index_head + pre_html

                tail = md_prefix + md_html + md_suffix
                if file_config.delay_sec or (file_config.gsheet_url and file_config.pace and file_config.printable):
                    tail += Delay_image_format % (site_prefix, file_config.delay_sec or 10, '' if file_config.delay_sec else '&cancel=yes')
                if Missing_ref_num_re.search(md_html) or return_html:
                    # Still some missing reference numbers; output file later
                    outfile_buffer.append([outname, outpath, fnumber, md_params, pre_html, tail, zipped_md])
                else:
                    outfile_buffer.append([outname, outpath, fnumber, md_params, '', '', None])
                    write_doc(dest_dir+outname, pre_html, tail)

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

    toc_all_html = ''
    if toc_file:
        toc_path = dest_dir + toc_file
        toc_mid_params = {'session_name': '',
                          'doc_banner': '',
                          'printable_css': '',
                          'math_js': '',
                          'pagedown_js': '',
                          'skulpt_js': '',
                          'plugin_tops': '',
                          'body_class': 'slidoc-plain-page',
                          'top_nav': render_topnav(topnav_list, toc_path, site_name=config.site_name) if topnav_list else '',
                          'top_nav_hide': ' slidoc-topnav-hide' if topnav_list else ''}
        toc_mid_params.update(SYMS)
        if config.toc_header:
            if isinstance(config.toc_header, io.BytesIO):
                header_insert = config.toc_header.getvalue()
            elif os.path.exists(config.toc_header):
                header_insert = md2md.read_file(config.toc_header)
            else:
                message('TOC-WARNING: ToC header file %s not found!' % config.toc_header)
                header_insert = ''

            if header_insert and (not isinstance(config.toc_header, (str, unicode)) or config.toc_header.endswith('.md')):
                header_insert = MarkdownWithMath(renderer=MathRenderer(escape=False)).render(header_insert)
        else:
            header_insert = ''

        toc_html = []
        if config.index and (Global.primary_tags or Global.primary_qtags):
            toc_html.append(' '+nav_link('INDEX', config.server_url, config.index, hash='#'+index_chapter_id,
                                     separate=config.separate, printable=config.printable))

        toc_html.append('\n<ol class="slidoc-toc-list">\n' if 'sections' in config.strip else '\n<ul class="slidoc-toc-list" style="list-style-type: none;">\n')

        reverse_toc = fprefix.lower().startswith('announce')
        toc_list = []
        addSessionLink = ''
        if config.create_toc:
            # Create ToC using header info from .html files
            smatch = sliauth.SESSION_NAME_RE.match(orig_fnames[-1] if orig_fnames else fprefix+'00')
            if smatch:
                addSessionLink = '<li class="slidoc-restrictedonly" style="display: none"><a class="slidoc-clickable-sym" href="%s/_upload/%s%02d"><b>+</b></a></li>\n' % (site_prefix, smatch.group(1), int(smatch.group(2))+1)

            temlist = orig_outpaths[:]
            if reverse_toc:
                temlist.reverse()
            for jfile, outpath in enumerate(temlist):
                ifile = len(temlist) - jfile - 1 if reverse_toc else jfile

                if outpath in out_index:
                    index_entries = read_index(io.BytesIO(out_index[outpath].encode('utf8')), path=outpath)
                elif os.path.exists(outpath):
                    with open(outpath) as f:
                        index_entries = read_index(f, path=outpath)
                else:
                    message('TOC-WARNING: Output file '+outpath+' not readable for indexing')
                    continue
                if not index_entries:
                    message('TOC-WARNING: Index header not found for '+outpath)
                    continue
                _, fheader, doc_str, iso_due_str, iso_release_str, index_params = index_entries[0]
                entry_class = ''
                entry_prefix = '<a class="slidoc-clickable slidoc-restrictedonly" href="%s/_manage/%s">%s</a> ' % (site_prefix, orig_fnames[ifile], SYMS['gear'])

                nb_str = ''
                if orig_fnames[ifile] in nb_links:
                    nb_str = ''' (<a class="slidoc-clickable" target="_blank" href="%s">notebook</a>)''' % nb_links[orig_fnames[ifile]]
                doc_link = ''
                if doc_str:
                    if doc_str == 'view':
                        doc_link = '''(<a class="slidoc-clickable" href="%s.html">%s</a>)%s''' % (orig_fnames[ifile], 'view', nb_str)
                    elif iso_release_str == sliauth.FUTURE_DATE or 'unreleased' in doc_str.lower():
                        # Preview and alt views
                        entry_class = ' class="slidoc-restrictedonly" style="display: none"'
                        doc_link = '''(<a class="slidoc-clickable" href="%s/_startpreview/%s">%s</a>)%s <span class="slidoc-restrictedonly" style="display: none;">&nbsp;&nbsp;[<a class="slidoc-clickable" href="%s.html?grading=1">%s</a>]</span>&nbsp;&nbsp;[%s] (<span class="slidoc-clickable" onclick="Slidoc.dateLoad('Release date (set to blank for indefinite release)','%s/_release/%s');">%s</span>)''' % (site_prefix, orig_fnames[ifile], 'preview', nb_str, orig_fnames[ifile], 'alt views', doc_str, site_prefix, orig_fnames[ifile], 'release')
                    else:
                        # View and alt views
                        doc_link = '''(<a class="slidoc-clickable" href="%s.html">%s</a>)%s <span class="slidoc-restrictedonly" style="display: none;">&nbsp;&nbsp;[<a class="slidoc-clickable" href="%s.html?grading=1">%s</a>]</span>&nbsp;&nbsp;[%s]''' % (orig_fnames[ifile], 'view',  nb_str, orig_fnames[ifile], 'alt views', doc_str)

                toc_html.append('<li %s>%s<span id="slidoc-toc-chapters-toggle" class="slidoc-toc-chapters">%s</span>%s<span class="slidoc-nosidebar"> %s</span></li>\n' % (entry_class, entry_prefix, fheader, SPACER6, doc_link))
                # Five entries
                toc_list.append(orig_fnames[ifile])
                toc_list.append(fheader)
                toc_list.append(doc_str)
                toc_list.append(iso_due_str)
                toc_list.append(iso_release_str)
                toc_list.append('{}')
                toc_list.append('')
        else:
            # Create ToC using info from rendering
            temlist = flist[:]
            if reverse_toc:
                temlist.reverse()
            for jfile, felem in enumerate(temlist):
                ifile = len(temlist) - jfile - 1 if reverse_toc else jfile
                    
                fname, outname, release_date_str, fheader, file_toc = felem
                if release_date_str == sliauth.FUTURE_DATE:
                    # Future release files not accessible from ToC
                    continue
                chapter_id = make_chapter_id(ifile+1)
                slide_link = ''
                if fname not in paced_files and config.slides:
                    slide_link = ' (<a href="%s%s" class="slidoc-clickable" target="_blank">%s</a>)' % (config.server_url, fname+"-slides.html", 'slides')
                nb_link = ''
                if fname not in paced_files and config.notebook and nb_server_url:
                    nb_link = ' (<a href="%s%s%s.ipynb" class="slidoc-clickable">%s</a>)' % (md2nb.Nb_convert_url_prefix, nb_server_url[len('http://'):], fname, 'notebook')

                if fname in paced_files:
                    doc_link = nav_link(file_props[fname]['doc_str'], config.server_url, outname, target='_blank', separate=True)
                    toggle_link = '<span id="slidoc-toc-chapters-toggle" class="slidoc-toc-chapters">%s</span>' % (fheader,)
                    if test_params:
                        for label, query, proxy_query in test_params:
                            if config.proxy_url:
                                doc_link += ', <a href="/_auth/login/%s&next=%s" target="_blank">%s</a>' % (proxy_query, sliauth.safe_quote('/'+outname+query), label)
                            else:
                                doc_link += ', <a href="%s%s" target="_blank">%s</a>' % (outname, query, label)
                else:
                    doc_link = nav_link('view', config.server_url, outname, hash='#'+chapter_id,
                                        separate=config.separate, printable=config.printable)
                    toggle_link = '''<span id="slidoc-toc-chapters-toggle" class="slidoc-clickable slidoc-toc-chapters" onclick="Slidoc.idDisplay('%s-toc-sections');">%s</span>''' % (chapter_id, fheader)

                toc_html.append('<li>%s%s<span class="slidoc-nosidebar"> (%s)%s%s</span></li>\n' % (toggle_link, SPACER6, doc_link, slide_link, nb_link))

                if fname not in paced_files:
                    f_toc_html = ('\n<div id="%s-toc-sections" class="slidoc-toc-sections" style="display: none;">' % chapter_id)+file_toc+'\n<p></p></div>'
                    toc_html.append(f_toc_html)

        if addSessionLink:
            toc_html.append(addSessionLink)

        toc_html.append('</ol>\n' if 'sections' in config.strip else '</ul>\n')

        if config.toc and config.slides:
            toc_html.append('<em>Note</em>: When viewing slides, type ? for help or click <a class="slidoc-clickable" target="_blank" href="https://github.com/hakimel/reveal.js/wiki/Keyboard-Shortcuts">here</a>.\nSome slides can be navigated vertically.')

        toc_html.append('<p></p><em>'+Formatted_by+'</em><p></p>')

        if not config.dry_run or return_html:
            toc_insert = ''
            if config.toc and fname not in paced_files:
                toc_insert += click_span('+Contents', "Slidoc.hide(this,'slidoc-toc-sections');",
                                        classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-noprint'])
            if combined_file:
                toc_insert = click_span(SYMS['bigram'], "Slidoc.sidebarDisplay();",
                                    classes=['slidoc-clickable-sym', 'slidoc-nosidebar', 'slidoc-noprint']) + SPACER2 + toc_insert
                toc_insert = click_span(SYMS['bigram'], "Slidoc.sidebarDisplay();",
                                    classes=['slidoc-clickable-sym', 'slidoc-sidebaronly', 'slidoc-noprint']) + toc_insert
                toc_insert += SPACER3 + click_span('+All Chapters', "Slidoc.allDisplay(this);",
                                                  classes=['slidoc-clickable', 'slidoc-hide-label', 'slidoc-noprint'])

            if toc_insert:
                toc_insert += '<br>'
            toc_output = chapter_prefix(0, 'slidoc-toc-container slidoc-noslide', hide=False)+(header_insert or Toc_header)+toc_insert+''.join(toc_html)+'</article>\n'
            if combined_file:
                all_container_prefix  = '<div id="slidoc-all-container" class="slidoc-all-container">\n'
                left_container_prefix = '<div id="slidoc-left-container" class="slidoc-left-container">\n'
                left_container_suffix = '</div> <!--slidoc-left-container-->\n'
                combined_html = [all_container_prefix, left_container_prefix, toc_output, left_container_suffix] + combined_html
            else:
                if toc_list:
                    # Include file header info as HTML comment
                    toc_head_html = '\n'.join([Index_prefix]+toc_list+[Index_suffix]) + head_html
                else:
                    toc_head_html = head_html
                toc_all_html = ''.join( [Html_header, toc_js_params+toc_head_html, mid_template % toc_mid_params, body_prefix, toc_output, Html_footer] )
                if not return_html:
                    md2md.write_file(toc_path, toc_all_html)
                    message("Created ToC file:", toc_path)

    if not config.dry_run or return_html:
        if not combined_file:
            if outfile_buffer and not RequestHandler.src_path:
                message('Created output files:', ', '.join(x[0] for x in outfile_buffer))
            for outname, outpath, fnumber, md_params, pre_html, tail, zipped_md in outfile_buffer:
                if tail:
                    # Update "missing" reference numbers and write output file
                    tail = Missing_ref_num_re.sub(Missing_ref_num, tail)
                    if return_html:
                        return {'outpath': outpath, 'out_html':md2md.str_join(Html_header, pre_html, tail, Html_footer), 'toc_html':md2md.stringify(toc_all_html), 'md_params':md_params, 'zipped_md':zipped_md, 'messages': messages}
                    else:
                        write_doc(outpath, pre_html, tail)
            if return_html:
                # No output files
                return {'outpath': '', 'out_html':'', 'toc_html':toc_all_html, 'md_params':{}, 'zipped_md':None, 'messages': messages}
        if config.slides:
            message('Created *-slides.html files')
        if config.notebook:
            message('Created *.ipynb files')

    # Index and X-reference
    xref_list = []
    if config.index and (Global.primary_tags or Global.primary_qtags):
        first_references, covered_first, index_html = make_index(Global.primary_tags, Global.sec_tags, config.server_url, fprefix=fprefix, index_id=index_id, index_file='' if combined_file else config.index)
        if not config.dry_run or return_html:
            index_html = ' <b>CONCEPT</b>\n' + index_html
            if config.qindex:
                index_html = nav_link('QUESTION INDEX', config.server_url, config.qindex, hash='#'+qindex_chapter_id,
                                      separate=config.separate, printable=config.printable) + '<p></p>\n' + index_html
            if config.crossref:
                index_html = ('<a href="%s%s" class="slidoc-clickable">%s</a><p></p>\n' % (config.server_url, config.crossref, 'CROSS-REFERENCING')) + index_html

            index_output = chapter_prefix(nfiles+1, 'slidoc-index-container slidoc-noslide', hide=False) + back_to_contents +'<p></p>' + index_html + '</article>\n'
            if combined_file:
                combined_html.append('<div class="slidoc-noslide">'+index_output+'</div>\n')
            elif not return_html:
                md2md.write_file(dest_dir+config.index, index_output)
                message("Created index in", config.index)

        if config.crossref:
            if config.toc:
                xref_list.append('<a href="%s%s" class="slidoc-clickable">%s</a><p></p>\n' % (config.server_url, combined_file or config.toc, 'BACK TO CONTENTS'))
            xref_list.append("<h3>Tags cross-reference (file prefix: "+fprefix+")</h3><p></p>")
            xref_list.append("\n<b>Tags -> files mapping:</b><br>")
            for tag in first_references:
                links = ['<a href="%s%s.html#%s" class="slidoc-clickable" target="_blank">%s</a>' % (config.server_url, slide_file, slide_id, slide_file[len(fprefix):] or slide_file) for slide_file, slide_id, slide_header in first_references[tag]]
                xref_list.append(("%-32s:" % tag)+', '.join(links)+'<br>')

            xref_list.append("<p></p><b>Primary concepts covered in each file:</b><br>")
            for ifile, felem in enumerate(flist):
                fname, outname, release_date_str, fheader, file_toc = felem
                clist = covered_first[fname].keys()
                clist.sort()
                tlist = []
                for ctag in clist:
                    slide_id, slide_header = covered_first[fname][ctag]
                    tlist.append( '<a href="%s%s.html#%s" class="slidoc-clickable" target="_blank">%s</a>' % (config.server_url, fname, slide_id, ctag) )
                xref_list.append(('%-24s:' % fname[len(fprefix):])+'; '.join(tlist)+'<br>')
            if all_concept_warnings:
                xref_list.append('<pre>\n'+'\n'.join(all_concept_warnings)+'\n</pre>')

    if config.qindex and Global.primary_qtags:
        import itertools
        qout_list = []
        qout_list.append('<b>QUESTION CONCEPT</b>\n')
        first_references, covered_first, qindex_html = make_index(Global.primary_qtags, Global.sec_qtags, config.server_url, question=True, fprefix=fprefix, index_id=qindex_id, index_file='' if combined_file else config.qindex)
        qout_list.append(qindex_html)

        qindex_output = chapter_prefix(nfiles+2, 'slidoc-qindex-container slidoc-noslide', hide=False) + back_to_contents +'<p></p>' + ''.join(qout_list) + '</article>\n'
        if not config.dry_run or return_html:
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
                                               config.server_url, fname+'.html', hash='#'+slide_id,
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
                                                        config.server_url, sub_fname+'.html', hash='#'+sub_slide_id,
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

        plugin_list = list(comb_plugin_embeds)
        plugin_list.sort()
        js_params['plugins'] = plugin_list
        comb_params = {'session_name': combined_name,
                       'printable_css': '',
                       'math_js': math_inc if math_load else '',
                       'pagedown_js': (Pagedown_js % libraries_params) if pagedown_load else '',
                       'skulpt_js': (Skulpt_js % libraries_params) if skulpt_load else '',
                       'plugin_tops': '',
                       'body_class': '',
                       'top_nav': '',
                       'top_nav_hide': ''}
        comb_params.update(SYMS)
        all_plugin_defs = base_plugin_defs.copy()
        all_plugin_defs.update(comb_plugin_defs)
        output_data = [Html_header, (js_params_fmt % json.dumps(js_params))+head_html+plugin_heads(all_plugin_defs, comb_plugin_loads),
                       mid_template % comb_params, body_prefix,
                       '\n'.join(combined_html), Html_footer]
        message('Created combined HTML file in '+combined_file)
        if return_html:
            return {'outpath':dest_dir+combined_file, 'out_html':''.join(output_data), 'toc_html':toc_all_html, 'messages':messages}
        md2md.write_file(dest_dir+combined_file, *output_data)
    return {'messages':messages}


def sort_caseless(list):
    new_list = list[:]
    sorted(new_list, key=lambda s: s.lower())
    return new_list


Html_header = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
'''

Delay_image_format = '''<img class="slidoc-blankimage" src="%s/_user_blankimage?delay=%d%s" style="display:none;">'''

Html_footer = '''
<div id="slidoc-body-footer" class="slidoc-noslide"></div>
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
<script src='%(libraries_link)s/Pagedown/Markdown.Converter.js'></script>
<script src='%(libraries_link)s/Pagedown/Markdown.Sanitizer.js'></script>
<script src='%(libraries_link)s/Pagedown/Markdown.Extra.js'></script>
'''

# NOTE: Any $ delimiter must appear after $$ delimiter in delimiters array
KaTeX_js = r'''<script type="text/javascript">
var KaTeX_opts = { throwOnError: false,
  delimiters: [ {left: "\\(", right: "\\)", display: false}
               ,{left: "\\[", right: "\\]", display: true}
               ,{left: "$$", right: "$$", display: true}
               %s
              ]
};
</script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.9.0-beta/katex.min.css" integrity="sha384-L/SNYu0HM7XECWBeshTGLluQO9uVI1tvkCtunuoUbCHHoTH76cDyXty69Bb9I0qZ" crossorigin="anonymous">
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.9.0-beta/katex.min.js" integrity="sha384-ad+n9lzhJjYgO67lARKETJH6WuQVDDlRfj81AJJSswMyMkXTD49wBj5EP004WOY6" crossorigin="anonymous"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.9.0-beta/contrib/auto-render.min.js" integrity="sha384-EkJr57fExjeMKAZnlVBuoBoX0EJ4BiDPiAd/JyTzIA65ORu4hna7V6aaq4zsUvJ2" crossorigin="anonymous"></script>
'''

Mathjax_js = r'''<script type="text/x-mathjax-config">
  MathJax.Hub.Config({
    %s
  });
</script>
<script src='https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.1/MathJax.js?config=TeX-AMS-MML_HTMLorMML'></script>
'''

Skulpt_js_non_https = r'''
<script src="http://ajax.googleapis.com/ajax/libs/jquery/1.9.0/jquery.min.js" type="text/javascript"></script> 
<script src="http://www.skulpt.org/static/skulpt.min.js" type="text/javascript"></script> 
<script src="http://www.skulpt.org/static/skulpt-stdlib.js" type="text/javascript"></script> 
'''

Skulpt_js = r'''
<script src="%(libraries_link)s/Skulpt/jquery.min.js" type="text/javascript"></script> 
<script src="%(libraries_link)s/Skulpt/skulpt.min.js" type="text/javascript"></script> 
<script src="%(libraries_link)s/Skulpt/skulpt-stdlib.js" type="text/javascript"></script> 
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

def parse_merge_args(args_text, source, parser, cmd_args_dict, default_args_dict={}, exclude_args=set(), include_args=set(), verbose=False):
    # Process file line args and merge with command line args, with command line args being final
    # If default_args_dict is specified, it is updated (overridden) with file line args
    args_text = args_text.strip().replace('\n', ' ')

    try:
        if args_text:
            # '--' prefix for args is optional
            line_args_list = [arg if arg.startswith('-') else '--'+arg for arg in shlex.split(args_text)]
            try:
                line_args_dict = vars(parser.parse_args(line_args_list))
            except SystemExit, excp:
                # Needed because parse_args raises SystemExit
                raise Exception("****OPTIONS-ERROR: Error in parsing argument list %s: %s" % (line_args_list, excp) )
        else:
            line_args_dict = dict([(arg_name, None) for arg_name in include_args]) if include_args else {}

        for arg_name in line_args_dict:
            if include_args and arg_name not in include_args:
                del line_args_dict[arg_name]
            elif exclude_args and arg_name in exclude_args:
                del line_args_dict[arg_name]
        if verbose:
            message('Read command line arguments from ', source, argparse.Namespace(**line_args_dict))
    except Exception, excp:
        abort('slidoc: ERROR in parsing command options in first line of %s: %s' % (source, excp))

    # Process arguments specified in file line or defaults
    arg_names = set(line_args_dict.keys()).union( set(default_args_dict.keys()) )
    merged_args_dict = {}
    for arg_name in arg_names:
        line_arg_value = line_args_dict.get(arg_name)
        if line_arg_value is None:
            # Merge default value for arg not specified in file line
            merged_args_dict[arg_name] = default_args_dict.get(arg_name)
        else:
            # Use arg from file line
            merged_args_dict[arg_name] = line_arg_value

        if arg_name == 'features':
            # Convert feature string to set
            merged_args_dict[arg_name] = md2md.make_arg_set(merged_args_dict[arg_name], Features_all)
        elif arg_name == 'strip':
            # Convert strip string to set
            merged_args_dict[arg_name] = md2md.make_arg_set(merged_args_dict[arg_name], Strip_all)

    if default_args_dict.get('pace'):
        # Ensure minimum pace level if default requiring pacing
        merged_args_dict['pace'] = max(merged_args_dict.get('pace',0), default_args_dict['pace'])

    for arg_name, arg_value in cmd_args_dict.items():
        if arg_name not in merged_args_dict:
            # Argument not specified in file line (copy from command line)
            merged_args_dict[arg_name] = arg_value

        elif (isinstance(arg_value, set) and arg_value) or (not isinstance(arg_value, set) and arg_value is not None):
            # Argument also specified in command line
            if arg_name == 'features' and merged_args_dict[arg_name] and 'override' not in arg_value:
                # Merge features from file with command line (unless 'override' feature is present in command line)
                merged_args_dict[arg_name] = arg_value.union(merged_args_dict[arg_name])
            else:
                # Command line overrides file line
                merged_args_dict[arg_name] = arg_value

    return argparse.Namespace(**merged_args_dict)

class RequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    subproc = None
    httpd = None

    preview_token = str(random.randrange(0,2**32))
    src_path = ''
    md_content = None
    md_params = None
    pptx_opts = {}
    config_dict = None

    log_messages = []
    images_zipfile = None
    images_map = {}
    src_modtime = 0
    upload_content = None
    upload_name = None
    outname = ''
    out_html = 'NO DATA'
    toc_html = 'NO DATA'
    mime_types = {'.gif': 'image/gif', '.jpg': 'image/jpg', '.jpeg': 'image/jpg', '.png': 'image/png'}
        
    @classmethod
    def create_preview(cls):
        fname, fext = os.path.splitext(os.path.basename(cls.src_path))
        cls.src_modtime = os.path.getmtime(cls.src_path)
        input_file = open(cls.src_path)
        images_zipdict = {}
        diff_char_num = 0
        if fext == 'pptx':
            import pptx2md
            md_path = cls.src_path[:-len('.pptx')]+'.md'
            ppt_parser = pptx2md.PPTXParser(cls.pptx_opts)
            md_text, images_zipdata = ppt_parser.parse_pptx(input_file, cls.src_path)
            cls.md_content = md_text.encode('utf8')
            images_zipdict[fname] = images_zipdata
        else:
            md_path = cls.src_path
            new_md_content = input_file.read()
            if cls.md_content is not None:
                nmatch = min(len(cls.md_content), len(new_md_content))
                diff_char_num = nmatch
                for j in xrange(nmatch):
                    if cls.md_content[j] != new_md_content[j]:
                        diff_char_num = j
                        break
            cls.md_content = new_md_content
            images_zipdata = None
        input_file.close()

        diff_slide_num = 0
        if cls.md_params:
            base = len(cls.md_params['md_defaults'])
            if diff_char_num >= base:
                diff_slide_num = len(cls.md_params['md_breaks'])
                for j, count in enumerate(cls.md_params['md_breaks']):
                    if diff_char_num < base+count:
                        diff_slide_num = j+1
                        break

        retval = process_input([io.BytesIO(cls.md_content)], [md_path], cls.config_dict,
                               default_args_dict=cls.default_args_dict, return_html=True, images_zipdict=images_zipdict,
                               restricted_sessions_re=sliauth.RESTRICTED_SESSIONS_RE)
        cls.log_messages = retval['messages']
        cls.outname = os.path.basename(retval['outpath'])
        cls.out_html = retval['out_html']
        cls.toc_html = retval['toc_html']
        cls.md_params = retval['md_params']
        cls.upload_content = retval['zipped_md'] if retval['zipped_md'] else cls.md_content
        cls.upload_name = fname + ('.zip' if retval['zipped_md'] else '.md')
        if retval['zipped_md']:
            cls.images_zipfile = zipfile.ZipFile(io.BytesIO(retval['zipped_md']))
        elif images_zipdata:
            cls.images_zipfile = zipfile.ZipFile(io.BytesIO(images_zipdata))

        if cls.images_zipfile:
            cls.images_map = dict( (os.path.basename(fpath), fpath) for fpath in cls.images_zipfile.namelist() if os.path.basename(fpath))

        for msg in retval['messages']:
            print(msg, file=sys.stderr)

        return diff_slide_num

    def log_message(self, format, *args):
        if args and isinstance(args[0], (str, unicode)) and (args[0].startswith('GET /_') or args[0].startswith('GET /?')):
            return
        return BaseHTTPServer.BaseHTTPRequestHandler.log_message(self, format, *args)

    @classmethod
    def shutdown(cls):
        if cls.subproc:
            out, err = cls.subproc.communicate()
            if out:
                print(out, file=sys.stdout)
            if err:
                print(err, file=sys.stderr)
        if cls.httpd:
            cls.httpd.shutdown()

    def do_GET(self):
        url_comps = urlparse.urlparse(self.path)
        query = urlparse.parse_qs(url_comps.query)
        if url_comps.path == '/' or url_comps.path == '/'+self.outname:
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            if not self.toc_html or url_comps.path == '/'+self.outname:
                self.wfile.write(self.out_html)
            else:
                self.wfile.write(self.toc_html)
            return

        if url_comps.path in ('/_shutdown'):
            import threading
            altproc = threading.Thread(target=RequestHandler.shutdown)
            altproc.daemon = True
            altproc.start()

        if url_comps.path in ('/_user_blankimage'):
            delay = query.get('delay', [])
            if delay and delay[0].isdigit():
                print('DELAY=%s' % delay[0], file=sys.stderr)
                time.sleep(int(delay[0]))
            self.send_response(200)
            self.send_header('Content-type', 'image/gif')
            self.end_headers()
            self.wfile.write(sliauth.blank_gif())
            return

        if url_comps.path in ('/_messages', '/_reloadcheck'):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            token = query.get('token', [])
            if not token and token[0] != self.preview_token:
                self.wfile.write('Error: Invalid preview token')
                return

            if url_comps.path == '/_reloadcheck':
                if os.path.getmtime(self.src_path) > self.src_modtime:
                    try:
                        diff_slide_num = self.create_preview()
                        self.wfile.write(str(diff_slide_num))
                        print('Updated preview\n---', file=sys.stderr)
                    except Exception, excp:
                        self.wfile.write('Error: '+str(excp))
                        print(str(excp)+'\n---', file=sys.stderr)
                else:
                    self.wfile.write('')
                return
            if url_comps.path == '/_messages':
                self.wfile.write('\n'.join(self.log_messages) if self.log_messages else 'No messages')
                return

        if url_comps.path == '/_remoteupload':
            import httplib
            server_url = self.config_dict.get('server_url')
            site_name = self.config_dict.get('site_name', '')
            if not server_url:
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write("Error in upload: Please specify 'slidoc.py --server_url=http://example.com --site_name=... --upload_key=...'")
                return
            upload_key = self.config_dict.get('upload_key')
            headers = {'Content-Type': 'application/octet-stream'}
            qparams = {'version': sliauth.get_version()}
            qparams['digest'] = sliauth.digest_hex(self.upload_content)
            qparams['token'] = sliauth.gen_hmac_token(upload_key, 'upload:'+qparams['digest'])
            load_path = '/_remoteupload/%s?%s' % (self.upload_name, urllib.urlencode(qparams))
            if self.config_dict.get('site_name'):
                load_path = '/' + self.config_dict['site_name'] + load_path
            server_comps = urlparse.urlparse(server_url)
            host, _, port = server_comps.netloc.partition(':')
            port = port or None
            if server_comps.path and server_comps.path != '/':
                load_path = server_comps.path + load_path
            conn = httplib.HTTPSConnection(host, port) if server_comps.scheme == 'https' else httplib.HTTPConnection(host, port)
            conn.request('PUT', load_path, self.upload_content, headers)
            resp = conn.getresponse()
            try:
                respText = resp.read()
            except Exception:
                respText = ''
            conn.close()
            if resp.status != 200:
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write('Error in upload: %d %s\n(%s%s)' % (resp.status, respText.strip() or resp.reason, server_url, load_path))
            else:
                self.send_response(303)
                redirect_url = server_url
                if site_name:
                    redirect_url += '/' + site_name
                self.send_header('Location', redirect_url + '/_preview/index.html')
                self.wfile.write('')
            return

        # Image file?
        filename = os.path.basename(url_comps.path[1:])
        fext = os.path.splitext(filename)[1]
        mime_type = self.mime_types.get(fext.lower())
        if mime_type:
            content = None
            if self.images_zipfile:
                if filename in self.images_map:
                    content = self.images_zipfile.read(self.images_map[filename])
                else:
                    self.send_response(404)
            elif '..' not in url_comps.path and os.path.exists(url_comps.path[1:]):
                with open(url_comps.path[1:]) as f:
                    content = f.read()

            if content is not None:
                self.send_response(200)
                self.send_header("Content-type", mime_type)
                self.end_headers()
                self.wfile.write(content)
                return
        
        self.send_response(404)
    
# Strip options
# For pure web pages, --strip=chapters,contents,navigate,sections
Strip_all = ['answers', 'chapters', 'contents', 'hidden', 'inline_formula', 'navigate', 'notes', 'rule', 'sections', 'tags']

# Features
#   adaptive_rubric: Track comment lines and display suggestions. Start comment lines with '(+/-n)...' to add/subtract points
#   answer_credits: Insert answer weight, retry count, participation credit etc.
#   assessment: Do not warn about concept coverage for assessment documents (also displays print exam menu)
#   auto_noshuffle: Automatically prevent shuffling of 'all of the above' and 'none of the above' options
#   auto_interact: Automatically initiate interactivity (for admin-paced sessions)
#   center_title: Center section titles
#   discuss_all: Enable discussion for all slides
#   equation_left: Left align equations
#   equation_number: Number equations sequentially
#   grade_response: Grade text responses and explanations; provide comments
#   immediate_math: Immediate rendering of math formulas (normally math rendering is delayed to load plugins)
#   incremental_slides: Display portions of slides incrementally (only for the current last slide)
#   keep_extras: Keep Extra: portion of slides (incompatible with remote sheet)
#   math_input: Render math in user input (not needed if session text already contains math)
#   no_markdown: Do not render markdown for remarks, comments, explanations etc.
#   override: Force command line feature set to override file-specific settings (by default, the features are merged)
#   progress_bar: Display progress bar during pace delays
#   quote_response: Display user response as quote (for grading)
#   remote_answers: Correct answers and score are stored remotely until session is graded
#   rollback_interact: option to rollback interactive sessions
#   share_all: share responses for all questions after end of lecture etc.
#   share_answers: share answers for all questions after grading (e.g., after an exam)
#   shuffle_choice: Choices are shuffled randomly. If there are alternative choices, they are picked together (randomly)
#   skip_ahead: Allow questions to be skipped if the previous sequnce of questions were all answered correctly
#   slide_break_avoid: Avoid page breaks within slide
#   slide_break_page: Force page breaks after each slide
#   slides_only: Only slide view is permitted; no scrolling document display
#   tex_math: Allow use of TeX-style dollar-sign delimiters for math
#   two_column: Two column output
#   untitled_number: Untitled slides are automatically numbered (as in a sheet of questions)

Features_all = ['adaptive_rubric', 'answer_credits', 'assessment', 'auto_noshuffle', 'auto_interact', 'center_title', 'dest_dir', 'discuss_all', 'equation_left', 'equation_number', 'grade_response', 'immediate_math', 'incremental_slides', 'keep_extras', 'math_input', 'no_markdown', 'override', 'progress_bar', 'quote_response', 'remote_answers', 'rollback_interact', 'share_all', 'share_answers', 'shuffle_choice', 'skip_ahead', 'slide_break_avoid', 'slide_break_page', 'slides_only', 'tex_math', 'two_column', 'untitled_number']

Conf_parser = argparse.ArgumentParser(add_help=False)
Conf_parser.add_argument('--all', metavar='FILENAME', help='Base name of combined HTML output file')
Conf_parser.add_argument('--crossref', metavar='FILE', help='Cross reference HTML file')
Conf_parser.add_argument('--css', metavar='FILE_OR_URL', help='Custom CSS filepath or URL (derived from doc_custom.css)')
Conf_parser.add_argument('--debug', help='Enable debugging', action="store_true", default=None)
Conf_parser.add_argument('--delay_sec', type=int, default=None, metavar='DELAY', help='Delay time (to finish equation rendering etc.)')
Conf_parser.add_argument('--doc_title', metavar='TITLE', help='Document title (for display and printing header)')
Conf_parser.add_argument('--due_date', metavar='DATE_TIME', help="Due local date yyyy-mm-ddThh:mm (append 'Z' for UTC)")
Conf_parser.add_argument('--features', metavar='OPT1,OPT2,...', help='Enable feature %s|all|all,but,...' % ','.join(Features_all))
Conf_parser.add_argument('--fontsize', metavar='FONTSIZE[,PRINT_FONTSIZE]', help='Font size, e.g., 9pt')
Conf_parser.add_argument('--hide', metavar='REGEX', help='Hide sections with headers matching regex (e.g., "[Aa]nswer")')
Conf_parser.add_argument('--image_dir', metavar='DIR', help="image subdirectory. Default value '_images' translates to 'sessionname_images' when reading images or copying images to dest_dir")
Conf_parser.add_argument('--image_url', metavar='URL', help='URL prefix for images, including image_dir')
Conf_parser.add_argument('--late_credit', type=float, default=None, metavar='FRACTION', help='Fractional credit for late submissions, e.g., 0.25')
Conf_parser.add_argument('--media_url', metavar='URL', help='URL for media')
Conf_parser.add_argument('--pace', type=int, metavar='PACE_LEVEL', help='Pace level: 0 (none), 1 (basic-paced), 2 (question-paced), 3 (instructor-paced)')
Conf_parser.add_argument('--participation_credit', type=int, metavar='INTEGER', help='Participation credit: 0 (none), 1 (per question), 2 (for whole session)')
Conf_parser.add_argument('--plugins', metavar='FILE1,FILE2,...', help='Additional plugin file paths')
Conf_parser.add_argument('--prereqs', metavar='PREREQ_SESSION1,PREREQ_SESSION2,...', help='Session prerequisites')
Conf_parser.add_argument('--printable', help='Printer-friendly output (SVG etc.)', action="store_true", default=None)
Conf_parser.add_argument('--publish', help='Only process files with --publish in first line', action="store_true", default=None)
Conf_parser.add_argument('--release_date', metavar='DATE_TIME', help="Release module on yyyy-mm-ddThh:mm (append 'Z' for UTC) or 'future' (test user always has access)")
Conf_parser.add_argument('--remote_logging', type=int, default=None, help='Remote logging level (0/1/2)')
Conf_parser.add_argument('--retakes', type=int, help='Max. number of retakes allowed (default: 0)')
Conf_parser.add_argument('--revision', metavar='REVISION', help='File revision')
Conf_parser.add_argument('--session_rescale', help='Session rescale (curve) parameters, e.g., *2,^0.5')
Conf_parser.add_argument('--session_weight', type=float, default=None, metavar='WEIGHT', help='Session weight')
Conf_parser.add_argument('--slide_delay', metavar='SEC', type=int, help='Delay between slides for paced sessions')
Conf_parser.add_argument('--show_score', help='Show correct answers after: never, after_answering, after_submitting, after_grading')
Conf_parser.add_argument('--strip', metavar='OPT1,OPT2,...', help='Strip %s|all|all,but,...' % ','.join(Strip_all))
Conf_parser.add_argument('--timed', type=int, help='No. of seconds for timed sessions (default: 0 for untimed)')
Conf_parser.add_argument('--vote_date', metavar='VOTE_DATE_TIME]', help="Votes due local date yyyy-mm-ddThh:mm (append 'Z' for UTC)")
Conf_parser.add_argument('--unhide_slides', help='Unhide all slides', action="store_true", default=None)

alt_parser = argparse.ArgumentParser(parents=[Conf_parser], add_help=False)
alt_parser.add_argument('--anonymous', help='Allow anonymous access (also unset REQUIRE_LOGIN_TOKEN)', action="store_true", default=None)
alt_parser.add_argument('--auth_key', metavar='DIGEST_AUTH_KEY', help='digest_auth_key (authenticate users with HMAC)')
alt_parser.add_argument('--backup_dir', help='Directory to create backup files for last valid version in when dest_dir is specified')
alt_parser.add_argument('--config', metavar='CONFIG_FILENAME', help='File containing default command line')
alt_parser.add_argument('--copy_source', help='Create a modified copy (only if dest_dir is specified)', action="store_true", default=None)
alt_parser.add_argument('--create_toc', help='Create Table of Contents in index.html using *.html output', action="store_true", default=None)
alt_parser.add_argument('--default_args', metavar='ARGS', help="'--arg=val --arg2=val2' default arguments ('file' to read first line of first file)")
alt_parser.add_argument('--dest_dir', metavar='DIR', help='Destination directory for creating files')
alt_parser.add_argument('--dry_run', help='Do not create any HTML files (index only)', action="store_true", default=None)
alt_parser.add_argument('--extract', metavar='SLIDE_NUMBER', type=int, help='Extract content from slide onwards (renumbering images)')
alt_parser.add_argument('--google_login', metavar='CLIENT_ID,API_KEY', help='client_id,api_key (authenticate via Google; not used)')
alt_parser.add_argument('--gsheet_url', metavar='URL', help='Google spreadsheet_url (export sessions to Google Docs spreadsheet)')
alt_parser.add_argument('--indexed', metavar='TOC,INDEX,QINDEX', help='Table_of_contents,concep_index,question_index base filenames, e.g., "toc,ind,qind" (if omitted, all input files are combined, unless pacing)')
alt_parser.add_argument('--libraries_url', metavar='URL', help='URL for library files; default: %s' % LIBRARIES_URL)
alt_parser.add_argument('--make', help='=all OR =filename; enable Make mode, i.e., only process .md files that are newer than corresponding .html files')
alt_parser.add_argument('--modify_sessions', metavar='SESSION1,SESSION2,... OR overwrite OR truncate', help='Module sessions with questions to be modified')
alt_parser.add_argument('--notebook', help='Create notebook files', action="store_true", default=None)
alt_parser.add_argument('--overwrite', help='Overwrite source and nb files', action="store_true", default=None)
alt_parser.add_argument('-p', '--preview_port', type=int, default=0, metavar='PORT', help='Preview document in browser using specified localhost port')
alt_parser.add_argument('--pptx_options', metavar='PPTX_OPTS', default='', help='Powerpoint conversion options (comma-separated)')
alt_parser.add_argument('--preview_mode', help='Do not copy image files to dest directory', action="store_true", default=None)
alt_parser.add_argument('--print_to_pdf', metavar='FILE', help='PDF output file name')
alt_parser.add_argument('--proxy_url', metavar='URL', help='Proxy spreadsheet_url')
alt_parser.add_argument('--site_name', metavar='SITE', help='Site name (default: "")')
alt_parser.add_argument('--server_url', metavar='URL', help='URL prefix to link local HTML files (default: "")')
alt_parser.add_argument('--session_type', metavar='TYPE', help='Module session type, e.g., assignment, exam, ... (default: "")')
alt_parser.add_argument('--slides', metavar='THEME,CODE_THEME,FSIZE,NOTES_PLUGIN', help='Create slides with reveal.js theme(s) (e.g., ",zenburn,190%%")')
alt_parser.add_argument('--split_name', default='', metavar='CHAR', help='Character to split filenames with and retain last non-extension component, e.g., --split_name=-')
alt_parser.add_argument('--test_script', help='Enable scripted testing(=1 OR SCRIPT1[/USER],SCRIPT2/USER2,...)')
alt_parser.add_argument('--start_date', metavar='DATE', help="Date after which all module releases must start yyyy-mm-dd[Thh:mm]")
alt_parser.add_argument('--toc_header', metavar='FILE', help='.html or .md header file for ToC')
alt_parser.add_argument('--topnav', metavar='PATH,PATH2,...', help='=dirs/files/args/path1,path2,... Create top navigation bar (from subdirectory names, HTML filenames, argument filenames, or pathnames)')
alt_parser.add_argument('--unbundle', help='Unbundle resource files from module files', action="store_true", default=None)
alt_parser.add_argument('--upload_key', metavar='KEY', help='Site auth key for uploading to remote server')
alt_parser.add_argument('-v', '--verbose', help='Verbose output', action="store_true", default=None)

cmd_parser = argparse.ArgumentParser(parents=[alt_parser], description='Convert from Markdown to HTML (v%s)' % sliauth.get_version())
cmd_parser.add_argument('file', help='Markdown/pptx filename', type=argparse.FileType('r'), nargs=argparse.ZERO_OR_MORE)

# Some arguments need to be set explicitly to '' by default, rather than staying as None
Cmd_defaults = {'css': '', 'dest_dir': '', 'hide': '', 'image_dir': '_images', 'image_url': '',
                'site_name': '', 'server_url': ''}
    
def cmd_args2dict(cmd_args):
    # Assign default (non-None) values to arguments not specified anywhere
    args_dict = vars(cmd_args)
    for arg_name in Cmd_defaults:
        if args_dict.get(arg_name) == None:
            args_dict[arg_name] = Cmd_defaults[arg_name]
    return args_dict

if __name__ == '__main__':
    cmd_args_orig = cmd_parser.parse_args()
    if cmd_args_orig.config:
        cmd_args = parse_merge_args(md2md.read_file(cmd_args_orig.config), cmd_args_orig.config, Conf_parser, vars(cmd_args_orig),
                                    verbose=cmd_args_orig.verbose)

    else:
        cmd_args = cmd_args_orig

    if cmd_args.default_args == 'file':
        # Read default args from first line of first file
        default_args = parse_merge_args(sliauth.read_header_opts(cmd_args.file[0])[0], cmd_args.file[0].name, Conf_parser, vars(cmd_args),
                                        verbose=cmd_args.verbose)
    elif cmd_args.default_args:
        default_args = parse_merge_args(cmd_args.default_args, '--default_args', Conf_parser, {})
    else:
        default_args = argparse.Namespace()

    default_args_dict = vars(default_args)

    config_dict = cmd_args2dict(cmd_args)

    settings = {}
    if cmd_args.gsheet_url:
        try:
            settings = sliauth.get_settings(sliauth.read_sheet(cmd_args.gsheet_url, cmd_args.auth_key, SETTINGS_SHEET)[0])
        except Exception, excp:
            print('Error in reading settings: %s', str(excp), file=sys.stderr)

    fhandles = config_dict.pop('file')
    input_files = []
    skipped = []
    for fhandle in fhandles:
        header_opts = sliauth.read_header_opts(fhandle)[0]
        if cmd_args.publish and (not header_opts or 'publish' not in header_opts):
            # Skip files without --publish in file header options
            skipped.append(fhandle.name)
            continue
        input_files.append(fhandle)

    if not input_files and not cmd_args.create_toc:
        cmd_parser.error('No files to process!')

    if skipped:
        print('\n******Skipped non-publish files: %s\n' % ', '.join(skipped), file=sys.stderr)

    if cmd_args.verbose:
        print('Effective argument list', file=sys.stderr)
        print('    ', argparse.Namespace(**config_dict), argparse.Namespace(**default_args_dict), file=sys.stderr)

    pptx_opts = {}
    if cmd_args.pptx_options:
        for opt in cmd_args.pptx_options.split(','):
            pptx_opts[opt] = True

    input_paths = [f.name for f in input_files]
    images_zipdict = {}
    pptx_paths = {}
    for j, inpath in enumerate(input_paths):
        fname, fext = os.path.splitext(os.path.basename(inpath))
        if fext == '.pptx' and not cmd_args.preview_port:
            # Convert .pptx to .md
            import pptx2md
            ppt_parser = pptx2md.PPTXParser(pptx_opts)
            md_text, images_zipdata = ppt_parser.parse_pptx(input_files[j], input_files[j].name)
            images_zipdict[fname] = images_zipdata
            input_files[j].close()
            input_files[j] = io.BytesIO(md_text.encode('utf8'))
            md_path = input_paths[j][:-len('.pptx')]+'.md'
            pptx_paths[md_path] = input_paths[j]
            input_paths[j] = md_path

    if cmd_args.preview_port:
        if len(input_files) != 1:
            raise Exception('ERROR: --preview_port only works for a single file')

        if cmd_args.upload_key:
            if not cmd_args.server_url:
                raise Exception('ERROR: Must specify --server_url with --upload_key')
            fname, fext = os.path.splitext(os.path.basename(input_paths[0]))
            if not sliauth.SESSION_NAME_RE.match(fname):
                raise Exception('Invalid session name "%s"; must be of the form "word.md" or "word01.md", with exactly two digits before the file extension' % fname)

        input_files[0].close()
        src_path = input_paths[0]
        fname, fext = os.path.splitext(os.path.basename(src_path))
        RequestHandler.src_path = pptx_paths[src_path] if src_path in pptx_paths else src_path
        RequestHandler.pptx_opts = pptx_opts.copy()
        RequestHandler.pptx_opts['img_dir'] = fname + '_images.zip'
        RequestHandler.pptx_opts['zip_md'] = True
        RequestHandler.config_dict = config_dict
        RequestHandler.default_args_dict = default_args_dict
        try:
            RequestHandler.create_preview()
        except Exception, excp:
            sys.exit(str(excp))

        RequestHandler.httpd = BaseHTTPServer.HTTPServer(('localhost', cmd_args.preview_port), RequestHandler)
        if cmd_args.print_to_pdf:
            command = "sleep 1 && /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --disable-gpu --print-to-pdf=%s 'http://localhost:%d/?print=1' && curl -s 'http://localhost:%d/_shutdown'" % (cmd_args.print_to_pdf, cmd_args.preview_port, cmd_args.preview_port)
        else:
            command = "sleep 1 && open -a 'Google Chrome' 'http://localhost:%d/?reloadcheck=%s&remoteupload=%s'" % (cmd_args.preview_port, RequestHandler.preview_token, '1' if cmd_args.upload_key else '')

        print('Preview at http://localhost:'+str(cmd_args.preview_port), file=sys.stderr)
        print(command, file=sys.stderr)
        RequestHandler.subproc = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True, stderr=subprocess.STDOUT)
        try:
            RequestHandler.httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        RequestHandler.httpd.server_close()
    else:
        process_input(input_files, input_paths, config_dict, default_args_dict=default_args_dict, images_zipdict=images_zipdict,
                      restricted_sessions_re=sliauth.RESTRICTED_SESSIONS_RE, error_exit=True)

        if cmd_args.printable:
            if cmd_args.gsheet_url:
                print("To convert .html to .pdf, use proxy to allow XMLHTTPRequest:\n  wkhtmltopdf -s Letter --print-media-type --cookie slidoc_server 'username::token:' --javascript-delay 5000 http://localhost/file.html file.pdf", file=sys.stderr)
            else:
                print("To convert .html to .pdf, use:\n  wkhtmltopdf -s Letter --print-media-type --javascript-delay 5000 file.html file.pdf", file=sys.stderr)
            print("Additional options that may be useful are:\n  --debug-javascript --load-error-handling ignore --enable-local-file-access --header-right 'Page [page] of [toPage]'", file=sys.stderr)
