#!/usr/bin/env python

'''
Convert lecture/slides from Markdown to Jupyter Notebook format.

Fenced code blocks are converted to notebook code cells, by default.
Optionally, indented code blocks may also be converted to cells.

'''

from __future__ import print_function

import base64
import json
import os
import re
import sys

import md2md

Nb_metadata_format = '''
{
  "metadata": {
  "language_info": {
   "name": "%(lang)s"
  }
 },
  "nbformat": 4,
  "nbformat_minor": 0,
  "cells" : [
%(cells)s
]
}
'''

Cell_formats = {}

Cell_formats['raw'] = '''
{
  "cell_type" : "raw",
  "metadata" : {},
  "source" : %(source)s
}
'''

Cell_formats['markdown'] = '''
{
  "cell_type" : "markdown",
  "metadata" : {},
  "source" : %(source)s
}
'''

Cell_formats['code'] = '''
{
  "cell_type" : "code",
  "execution_count": null,
  "metadata" : {
      "collapsed" : false
  },
  "source" : %(source)s,
  "outputs": %(outputs)s
}
'''


class MDParser(object):
    newline_norm_re =  re.compile( r'\r\n|\r')
    indent_strip_re =  re.compile( r'^ {4}', re.MULTILINE)
    answer_re =        re.compile( r'^Answer:')
    notes_re =         re.compile( r'^Notes:')
    tags_re =          re.compile( r'^Tags:')
    inline_js1 =       re.compile( r"`=(\w+)\.(\w+)\(\s*(\d*)\s*\);([^`\n]*)`")
    inline_js2 =       re.compile( r"`=(\w+)\.(\w+)\(\s*(\d*)\s*\)`")
    plugin_re =        re.compile( r'^=(\w+)\(([^\n]*)\)\s*(\n\s*\n|\n$|$)')
    internal_ref =     re.compile(
        r'^\[('
        r'(?:\[[^^\]]*\]|[^\[\]]|\](?=[^\[]*\]))*'
        r')\]\s*\{\s*#([^^\}]*)\}'
    )

    rules_re = [ ('fenced',            re.compile( r'^ *(`{3,}|~{3,}) *(\S+)? *\n'
                                                   r'([\s\S]+?)\s*'
                                                   r'\1 *(?:\n+|$)' ) ),
                 ('indented',          re.compile( r'^( {4}[^\n]+\n*)+') ),
                 ('block_math',        re.compile( r'^\$\$(.*?)\$\$', re.DOTALL) ),
                 ('latex_environment', re.compile( r'^\\begin\{([a-z]*\*?)\}(.*?)\\end\{\1\}',
                                                   re.DOTALL) ),
                 ('plugin_definition', re.compile(r'^ {0,3}<script +type="x-slidoc-plugin" *>\s*(\w+)\s*=\s*\{(.*?)\n *(// *\1)? *</script> *(\n|$)',
                                                re.DOTALL)),
                 ('plugin_embed',      re.compile(r'^ {0,3}<script +type="x-slidoc-embed" *>\s*(\w+)\(([^\n]*)\)\s*\n(.*?)\n *</script> *(\n|$)',
                                                re.DOTALL)),
                 ('external_link',     re.compile( r'''^ {0,3}(!?)\[([^\]]+)\]\(\s*(<)?(.*?)(?(3)>)(?:\s+['"](.*?)['"])?\s*\) *(\n|$)''') ),
                 ('hrule',      re.compile( r'^([-]{3,}) *(?:\n+|$)') ) ]

    def __init__(self, cmd_args):
        self.cmd_args = cmd_args
        self.cells_buffer = []
        self.buffered_lines = []
        self.skipping_notes = False
        self.filedir = ''

    def clear_buffer(self):
        if not self.buffered_lines:
            return
        self.markdown(''.join(self.buffered_lines))
        self.buffered_lines = []

    def parse_cells(self, content, filepath=''):
        if filepath:
            self.filedir = os.path.dirname(os.path.realpath(filepath))

        content = self.newline_norm_re.sub('\n', content) # Normalize newlines

        while content:
            matched = None
            for rule_name, rule_re in self.rules_re:
                if rule_name == 'indented' and not self.cmd_args.indented:
                    # Do not 'cellify' indented code, unless requested
                    continue

                # Find the first match
                matched = rule_re.match(content)
                if matched:
                    break

            if matched:
                self.clear_buffer()

                # Strip out matched text
                content = content[len(matched.group(0)):]

                if rule_name == 'fenced':
                    self.code_block(matched.group(3), lang=matched.group(2) )

                elif rule_name == 'indented':
                    self.code_block(self.indent_strip_re.sub('', matched.group(0)) )

                elif rule_name == 'block_math':
                    self.math_block(matched.group(0))

                elif rule_name == 'latex_environment':
                    self.math_block(matched.group(0))

                elif rule_name in ('plugin_definition', 'plugin_embed'):
                    self.plugin_block(matched.group(0))

                elif rule_name == 'external_link':
                    self.external_link(matched.group(0), matched.group(2), matched.group(4), matched.group(5) or '')

                elif rule_name == 'hrule':
                    self.hrule(matched.group(1))
                else:
                    raise Exception('Unknown rule: '+rule_name)

            elif '\n' in content:
                line, _, content = content.partition('\n')
                if 'extensions' in self.cmd_args.strip or 'plugin' in self.cmd_args.strip:
                    line = self.inline_js1.sub(r'\4', line)
                    line = self.inline_js2.sub(r'', line)
                if 'extensions' in self.cmd_args.strip:
                    line = self.internal_ref.sub(r'\1', line)
                if self.skipping_notes:
                    pass
                elif self.answer_re.match(line) and 'answer' in self.cmd_args.strip:
                    pass
                elif self.tags_re.match(line) and 'tags' in self.cmd_args.strip:
                    pass
                elif self.notes_re.match(line) and 'notes' in self.cmd_args.strip:
                    self.skipping_notes = True
                elif self.plugin_re.match(line) and 'plugin' in self.cmd_args.strip:
                    pass
                elif not line.strip() and not self.buffered_lines and self.cells_buffer and self.cells_buffer[-1]['cell_type'] == 'code':
                    # Skip blank lines immediately following a code block
                    pass
                else:
                    self.buffered_lines.append(line+'\n')

            else:
                self.markdown(content)
                content = ''

        self.clear_buffer()

        nb_cells = ','.join([self.dump_cell(cell) for cell in self.cells_buffer])
        return Nb_metadata_format % {'lang': 'python', 'cells': nb_cells}


    def hrule(self, text):
        if 'rule' not in self.cmd_args.strip and 'markup' not in self.cmd_args.strip:
            self.buffered_lines.append(text+'\n\n')
        self.skipping_notes = False

    def external_link(self, line, text, link, title):
        nb_output_append = title.startswith('nb_output') and self.cells_buffer and self.cells_buffer[-1]['cell_type'] == 'code'
        if line.lstrip().startswith('!') and (self.cmd_args.embed_images or nb_output_append):
            fpath = link
            if self.filedir:
                fpath = self.filedir + '/' + fpath
            _, extn = os.path.splitext(os.path.basename(fpath))
            extn = extn.lower()
            if extn in ('.gif', '.jpg', '.jpeg', '.png', '.svg'):
                content_type = 'image/jpeg' if extn == '.jpg' else 'image/'+extn[1:]
                f = open(fpath)
                content = f.read()
                f.close()
                img_content = self.image_output(text, content_type, base64.b64encode(content))
                if nb_output_append:
                    self.cells_buffer[-1]['outputs'].append(img_content)
                else:
                    self.cells_buffer.append({'cell_type': 'code', 'source': '', 'outputs': [img_content]})
            else:
                self.buffered_lines.append(line)
        else:
            self.buffered_lines.append(line)

    def plugin_block(self, text):
        if 'extensions' in self.cmd_args.strip or 'plugin' in self.cmd_args.strip:
            pass
        else:
            self.cells_buffer.append({'cell_type': 'raw', 'source': [text]})

    def code_block(self, code, lang=''):
        if lang == 'nb_output' and self.cells_buffer and self.cells_buffer[-1]['cell_type'] == 'code':
            self.cells_buffer[-1]['outputs'].append(self.stream_output(code))
        else:
            self.cells_buffer.append({'cell_type': 'code', 'source': self.split_str(code), 'outputs': []})

    def math_block(self, content):
        if 'markup' not in self.cmd_args.strip:
            self.buffered_lines.append(content)

    def markdown(self, content):
        if 'markup' not in self.cmd_args.strip:
            self.cells_buffer.append({'cell_type': 'markdown', 'source': self.split_str(content, backtick_off=True)})

    def split_str(self, content, backtick_off=False):
        # Split string into list of lines
        if backtick_off:
            # Un-backtick inline math
            content = re.sub(r"(^|[^`])`\$(.+?)\$`", r"\1$\2$", content)
        lines = content.split('\n')
        out_lines = [x+'\n' for x in lines[:-1]]
        if not out_lines or lines[-1]:
            out_lines.append(lines[-1])
        return out_lines

    def stream_output(self, text):
        return {
        "name": "stdout",
        "output_type": "stream",
        "text": self.split_str(text)
        }

    def image_output(self, text, content_type, data):
        return {
        "data": {
        content_type: data,
        "text/plain": [ text ]
        },
        "metadata": {},
        "output_type": "display_data"
        }

    def dump_cell(self, cell):
        if cell['cell_type'] == 'code':
            return Cell_formats['code'] % {'source': json.dumps(cell['source']),
                                           'outputs': json.dumps(cell['outputs'])}
        if cell['cell_type'] == 'markdown':
            return Cell_formats['markdown'] % {'source': json.dumps(cell['source'])}

        return Cell_formats['raw'] % {'source': json.dumps(cell['source'])}


Nb_convert_url_prefix = 'http://nbviewer.jupyter.org/url/'

Args_obj = md2md.ArgsObj( str_args= ['site_url', 'strip'],
                          bool_args= [ 'indented', 'overwrite'],
                          defaults= {})

if __name__ == '__main__':
    import argparse

    strip_all = ['answer', 'extensions', 'internal_ref', 'markup', 'notes', 'plugin', 'rule', 'tags']
    
    parser = argparse.ArgumentParser(description='Convert from Markdown to Jupyter Notebook format')
    parser.add_argument('--embed_images', help='Embed all images', action="store_true")
    parser.add_argument('--indented', help='Convert indented code blocks to notebook cells', action="store_true")
    parser.add_argument('--site_url', help='URL prefix for website (default: "")', default='')
    parser.add_argument('--strip', help='Strip %s|all|all,but,...' % ','.join(strip_all))
    parser.add_argument('--overwrite', help='Overwrite files', action="store_true")
    parser.add_argument('file', help='Markdown filename', type=argparse.FileType('r'), nargs=argparse.ONE_OR_MORE)
    cmd_args = parser.parse_args()
    cmd_args.strip = md2md.make_arg_set(cmd_args.strip, strip_all)

    url_prefix = ''
    if cmd_args.site_url:
        if cmd_args.site_url.startswith('http://'):
            url_prefix = cmd_args.site_url[len('http://'):]
        else:
            url_prefix = cmd_args.site_url

    md_parser = MDParser( Args_obj.create_args(cmd_args) )   # Use args_obj to pass orgs as a consistency check

    fnames = []
    for f in cmd_args.file:
        fcomp = os.path.splitext(os.path.basename(f.name))
        fnames.append(fcomp[0])
        if fcomp[1] != '.md':
            sys.exit('Invalid file extension for '+f.name)

        if os.path.exists(fcomp[0]+'.ipynb') and not cmd_args.overwrite:
            sys.exit("File %s.ipynb already exists. Delete it or specify --overwrite" % fcomp[0])

    flist = []
    for j, f in enumerate(cmd_args.file):
        fname = fnames[j]
        md_text = f.read()
        f.close()
        nb_text = md_parser.parse_cells(md_text, f.name)

        flist.append( (fname, '<a href="%s%s%s.ipynb">%s.ipynb</a>' % (Nb_convert_url_prefix, url_prefix, fname, fname)) )
        outname = fname+".ipynb"
        outfile = open(outname, "wb")
        outfile.write(nb_text)
        outfile.close()
        print("Created ", outname, file=sys.stderr)

    if cmd_args.site_url:
        for fname, flink in flist:
            sys.stdout.write('<ol>\n')
            sys.stdout.write('  <li>%s</li>\n' % flink)
            sys.stdout.write('</ol>\n')
            
